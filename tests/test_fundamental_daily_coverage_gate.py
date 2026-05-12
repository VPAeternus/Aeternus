from tradingagents.research.fundamental.src.daily_run.coverage import classify_coverage_summary, normalize_coverage_summary, should_continue_fetch
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
