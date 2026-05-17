import json

from tradingagents.research.fundamental.src.daily_run.coverage import classify_coverage_summary, load_raw_documents_from_coverage, materialize_alias_documents_from_queue, normalize_coverage_summary, should_continue_fetch
from tradingagents.research.fundamental.src.daily_run.models import GateStatus


def test_coverage_allows_pre_llm_when_exhibits_missing_but_companyfacts_ready():
    summary = classify_coverage_summary(ticker_count=1276, companyfacts_ready_count=1276, coverage_status_counts={"CACHED_READY": 76, "BLOCKED_METADATA_OR_ISSUER_REALITY": 1200}, missing_input_counts={"earnings_exhibit_metadata": 1015, "8k_item_202_metadata": 185}, fetch_queue_count=0, blocked_tickers=["NOK", "SILC", "TSEM"])
    assert summary["pre_llm_blocked"] is False
    assert summary["llm_doc_ready_count"] == 76
    assert summary["remaining_work_type"] == "metadata_or_parser_routing"


def test_should_not_continue_fetch_when_queue_zero_even_if_metadata_missing():
    assert should_continue_fetch(fetch_queue_count=0, missing_input_counts={"earnings_exhibit_metadata": 1015}) is False


def test_coverage_hard_stops_when_companyfacts_missing_for_broad_universe():
    summary = classify_coverage_summary(ticker_count=1276, companyfacts_ready_count=100, coverage_status_counts={}, missing_input_counts={"companyfacts": 1176}, fetch_queue_count=0, blocked_tickers=[])
    assert summary["gate_status"] == GateStatus.HARD_STOP.value
    assert summary["pre_llm_blocked"] is True


def test_normalize_coverage_summary_has_stable_contract():
    raw = {"ticker_count": 1276, "status_counts": {"CACHED_READY": 76}, "missing_input_counts": {"earnings_exhibit_metadata": 1015}, "fetch_queue_count": 0, "blocked_tickers": ["NOK"], "outputs": {"manifest_csv": "manifest.csv"}}
    summary = normalize_coverage_summary(raw, universe_count=1276, companyfacts_ready_count=1276)
    assert summary["ticker_count"] == 1276
    assert summary["companyfacts_ready_count"] == 1276
    assert summary["llm_doc_ready_count"] == 76
    assert summary["outputs"] == {"manifest_csv": "manifest.csv"}


def test_load_raw_documents_searches_shared_sec_cache(tmp_path):
    import csv

    live = tmp_path / "live_sec"
    shared = tmp_path / "sec_docs_text"
    shared.mkdir()
    manifest = tmp_path / "manifest.csv"
    rows = [
        {
            "ticker": "AAA",
            "quarter": "2026Q2",
            "coverage_status": "CACHED_READY",
            "earnings_8k_accession": "00000000-AAA",
            "earnings_8k_primary_document": "8k.htm",
            "earnings_exhibit_document": "ex99.htm",
            "periodic_accession": "00000000-AAAQ",
            "periodic_primary_document": "10q.htm",
        }
    ]
    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for file_name in ["AAA_00000000AAA_8k.htm", "AAA_00000000AAA_ex99.htm", "AAA_00000000AAAQ_10q.htm"]:
        (shared / file_name).write_text("<html>Revenue and margin improved.</html>")

    docs = load_raw_documents_from_coverage(manifest, live, extra_document_roots=[shared])

    assert {doc["document_type"] for doc in docs} == {"primary_8k", "earnings_exhibit", "periodic_10q_10k"}
    assert (live / "documents" / "AAA_00000000AAA_ex99.htm").exists()


def test_materialize_alias_documents_from_queue_copies_parent_ticker_docs(tmp_path):
    out = tmp_path / "run"
    live = tmp_path / "live_sec"
    docs = live / "documents"
    docs.mkdir(parents=True)
    accession = "000168504023000026"
    (docs / f"BHF_{accession}_bhf-20230508.htm").write_text("<html>8-K</html>", encoding="utf-8")
    (docs / f"BHF_{accession}_q12023bhfearningspressrele.htm").write_text("<html>press release</html>", encoding="utf-8")
    queue = {
        "items": [
            {
                "kind": "complete_submission",
                "ticker": "BHFAO",
                "accession": "0001685040-23-000026",
                "documents": [
                    {"document": "bhf-20230508.htm", "cache_key": f"documents/BHFAO_{accession}_bhf-20230508.htm"},
                    {"document": "q12023bhfearningspressrele.htm", "cache_key": f"documents/BHFAO_{accession}_q12023bhfearningspressrele.htm"},
                ],
            }
        ]
    }
    out.mkdir()
    (out / "sec_fetch_queue_resumable.json").write_text(json.dumps(queue), encoding="utf-8")

    summary = materialize_alias_documents_from_queue(out_root=out, live_sec_root=live)

    assert summary["alias_document_materialized_count"] == 2
    assert (docs / f"BHFAO_{accession}_bhf-20230508.htm").exists()
    assert (docs / f"BHFAO_{accession}_q12023bhfearningspressrele.htm").exists()
