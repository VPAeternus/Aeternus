import json


def test_build_scout_quality_daily_counts_detection_and_event_card_contribution():
    from tradingagents.dealflow.scout_quality import build_scout_quality_daily

    scout_audit = {
        "signals": [
            {"symbol": "XLE", "source": "technical_ignition"},
            {"symbol": "BABA", "source": "earnings_options"},
        ],
        "breakout": {"alerts": [{"ticker": "NVDA"}]},
        "insider": {"buy_clusters": [{"ticker": "ABNB"}], "sell_clusters": []},
    }
    event_cards = [
        {"event_card_id": "evt_1", "source_bundle": ["technical_ignition", "x_feed"]},
        {"event_card_id": "evt_2", "source_bundle": ["earnings_options"]},
    ]
    coverage_precheck = {
        "rows": [
            {"event_card_id": "evt_1", "coverage_status": "COMPLETE"},
            {"event_card_id": "evt_2", "coverage_status": "PARTIAL"},
        ]
    }

    payload = build_scout_quality_daily(
        as_of_date="2026-03-15",
        scout_audit=scout_audit,
        event_cards=event_cards,
        coverage_precheck=coverage_precheck,
    )

    by_source = {row["source"]: row for row in payload["rows"]}
    assert by_source["technical_ignition"]["detection_count"] == 1
    assert by_source["technical_ignition"]["event_card_contribution_count"] == 1
    assert by_source["technical_ignition"]["complete_count"] == 1
    assert by_source["earnings_options"]["partial_count"] == 1
    assert by_source["breakout"]["detection_count"] == 1
    assert by_source["insider_cluster"]["detection_count"] == 1


def test_persist_scout_quality_daily_writes_artifact(tmp_path):
    from tradingagents.dealflow.scout_quality import persist_scout_quality_daily

    payload = {"date": "2026-03-15", "rows": [{"source": "technical_ignition", "detection_count": 1}]}
    result = persist_scout_quality_daily(
        as_of_date="2026-03-15",
        payload=payload,
        base_dir=tmp_path / "eval_results" / "deal_flow",
    )

    out = tmp_path / "eval_results" / "deal_flow" / "2026-03-15" / "scout_quality_daily.json"
    assert out.exists()
    assert json.loads(out.read_text())["rows"][0]["source"] == "technical_ignition"
    assert result["output_path"].endswith("scout_quality_daily.json")


def test_build_scout_quality_daily_uses_source_records_when_detection_counts_are_missing():
    from tradingagents.dealflow.scout_quality import build_scout_quality_daily

    payload = build_scout_quality_daily(
        as_of_date="2026-03-15",
        scout_audit={"signals": [], "breakout": {"alerts": []}, "insider": {"buy_clusters": [], "sell_clusters": []}},
        event_cards=[
            {
                "event_card_id": "evt_1",
                "source_bundle": ["x_feed"],
                "source_records": [
                    {"source_family": "x_feed"},
                    {"source_family": "x_feed"},
                ],
            }
        ],
        coverage_precheck={"rows": [{"event_card_id": "evt_1", "coverage_status": "PARTIAL"}]},
    )

    by_source = {row["source"]: row for row in payload["rows"]}
    assert by_source["x_feed"]["detection_count"] == 2
