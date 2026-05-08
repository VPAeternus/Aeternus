import json
from pathlib import Path

from src.features.llm_packets import build_llm_packets
from src.features.pre_llm_scores import build_pre_llm_rows
from src.ingest.prices import compute_return_checkpoints
from src.pipeline.run_quarter import run_quarter_pipeline
from src.reporting.daily_report import write_daily_reports
from src.storage import read_table, write_table


def test_run_quarter_normalizes_float_cik_from_csv(tmp_path: Path):
    universe = tmp_path / "universe.csv"
    universe.write_text("ticker,quarter,cik\nABC,2026Q1,1109116.0\n", encoding="utf-8")
    calls = []

    class FakeClient:
        def submissions(self, cik):
            calls.append(cik)
            return {"filings": {"recent": {"form": [], "filingDate": [], "reportDate": [], "accessionNumber": [], "items": [], "primaryDocument": [], "acceptanceDateTime": []}}}

        def companyfacts(self, cik):
            return {"facts": {}}

    import src.pipeline.run_quarter as rq
    original = rq.SecClient
    rq.SecClient = lambda: FakeClient()
    try:
        run_quarter_pipeline(
            quarter="2026Q1",
            universe_path=universe,
            as_of="2026-05-02",
            lake_root=tmp_path / "lake",
            skip_llm=True,
            skip_price_fetch=True,
        )
    finally:
        rq.SecClient = original

    assert calls == ["1109116"]


def test_fake_quarter_end_to_end_no_network_no_llm(tmp_path: Path):
    universe = tmp_path / "universe.csv"
    universe.write_text(
        "ticker,quarter,cik,revenue_value,net_income_value,assets_value,financing_cash_flow_value,investing_cash_flow_value,operating_cash_flow_value,revenue_bucket,tradable_date,entry_open,has_identifiable_catalyst,invalidation_trigger\n"
        "ABC,2026Q1,1,200000000,20000000,150000000,0,-5000000,30000000,$100M-$500M,2026-04-01,9,1,test invalidation\n",
        encoding="utf-8",
    )
    llm = tmp_path / "llm.csv"
    llm.write_text(
        "ticker,quarter,post_llm_candidate_flag,post_llm_high_priority_flag,post_llm_demote_flag,causal_change,negative_revision_risk,narrative_delta_bucket,operating_leverage_quality,durability,proof_alignment,score_addition,driver_summary,bear_case_summary,confidence\n"
        "ABC,2026Q1,1,1,0,3,1,inflecting,2,2,3,3,demand improves,risk,high\n",
        encoding="utf-8",
    )

    result = run_quarter_pipeline(
        quarter="2026Q1",
        universe_path=universe,
        as_of="2026-05-02",
        lake_root=tmp_path / "lake",
        post_llm_path=llm,
        skip_sec_fetch=True,
        skip_llm=True,
    )

    candidates = read_table(tmp_path / "lake", "candidate_scores")
    tiers = read_table(tmp_path / "lake", "tier_classification")
    pre = read_table(tmp_path / "lake", "pre_llm_scores")

    assert result["candidate_rows"] == 1
    assert len(candidates) == 1
    assert len(tiers) == 1
    assert len(pre) == 1
    assert candidates.iloc[0]["entry_score_0_100"] >= 70


def test_llm_packet_builder_uses_documents_and_blocks_returns():
    docs = [
        {
            "ticker": "ABC",
            "quarter": "2026Q1",
            "document_type": "earnings_exhibit",
            "clean_text": "Revenue grew because demand improved. Guidance raised. Margin expanded.",
        }
    ]
    candidates = [{"ticker": "ABC", "quarter": "2026Q1", "return_90d_pct": "999"}]

    packets = build_llm_packets(candidates, docs)

    assert packets[0]["sample_id"] == "ABC_2026Q1"
    assert "return_90d_pct" not in json.dumps(packets)
    assert "Revenue grew" in packets[0]["evidence_snippets"][0]


def test_build_pre_llm_rows_persists_scoreable_fields():
    rows = build_pre_llm_rows(
        [
            {
                "ticker": "ABC",
                "quarter": "2026Q1",
                "revenue_value": "200",
                "net_income_value": "20",
                "assets_value": "100",
                "financing_cash_flow_value": "0",
                "investing_cash_flow_value": "-5",
                "operating_cash_flow_value": "30",
                "revenue_bucket": "$100M-$500M",
            }
        ]
    )

    assert rows[0]["pre_llm_fundamental_bucket"] == "strong"
    assert rows[0]["missing_fields"] == ""


def test_return_checkpoints_use_raw_open_and_close():
    prices = [
        {"date": "2026-04-01", "open": 10, "close": 10, "volume": 100},
        {"date": "2026-04-11", "open": 11, "close": 12, "volume": 100},
        {"date": "2026-05-01", "open": 11, "close": 13, "volume": 100},
    ]

    returns = compute_return_checkpoints(prices, tradable_date="2026-04-01", actual_entry_price=10)

    assert returns["entry_open"] == 10
    assert returns["current_return_pct"] == 30.0
    assert returns["return_since_purchase_pct"] == 30.0


def test_daily_reports_include_score_changes(tmp_path: Path):
    rows = [{"ticker": "ABC", "quarter": "2026Q1", "entry_score_0_100": 80, "active_monitoring_score_0_100": 70, "applied_monitoring_delta": -10}]

    paths = write_daily_reports(rows, as_of="2026-05-02", out_dir=tmp_path)

    assert tmp_path / "20260502_score_changes.csv" in paths
