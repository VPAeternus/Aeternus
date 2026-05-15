import csv

from tradingagents.research.fundamental.src.daily_run.status import build_daily_status_rows, write_daily_status


def test_daily_status_tracks_scored_and_rejected_tickers(tmp_path):
    rows = build_daily_status_rows(
        quarter="2026Q2",
        universe_rows=[{"ticker": "AAA", "quarter": "2026Q2", "cik": "1", "company_title": "AAA Inc", "daily_source_label": "master_start"}],
        identity_rejections=[{"ticker": "BBB", "quarter": "2026Q2", "identity_status": "ticker_or_name_unresolved", "rejection_reason": "no SEC filer found"}],
        coverage_rows=[{"ticker": "AAA", "quarter": "2026Q2", "coverage_status": "CACHED_READY"}],
        pre_rows=[{"ticker": "AAA", "quarter": "2026Q2", "pre_llm_fundamental_bucket": "good"}],
        llm_eligible_rows=[{"ticker": "AAA", "quarter": "2026Q2"}],
        packet_rows=[{"ticker": "AAA", "quarter": "2026Q2"}],
        post_llm_rows=[{"ticker": "AAA", "quarter": "2026Q2"}],
        final_rows=[{"ticker": "AAA", "quarter": "2026Q2"}],
    )

    by_ticker = {row["ticker"]: row for row in rows}
    assert by_ticker["AAA"]["source_status"] == "master_start"
    assert by_ticker["AAA"]["final_score_status"] == "scored"
    assert by_ticker["AAA"]["llm_completion_status"] == "complete"
    assert by_ticker["BBB"]["source_status"] == "rejected"
    assert by_ticker["BBB"]["final_score_status"] == "rejected"
    assert by_ticker["BBB"]["rejection_reason"] == "no SEC filer found"


def test_write_daily_status_outputs_csv(tmp_path):
    path = write_daily_status(
        tmp_path / "daily_ticker_status.csv",
        quarter="2026Q2",
        universe_rows=[{"ticker": "AAA", "quarter": "2026Q2", "cik": "1", "company_title": "AAA Inc"}],
    )

    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["ticker"] == "AAA"
    assert rows[0]["identity_status"] == "resolved"


def test_daily_status_labels_existing_master_additions_plainly():
    rows = build_daily_status_rows(
        quarter="2026Q2",
        universe_rows=[{"ticker": "CCC", "quarter": "2026Q2", "cik": "3", "company_title": "CCC Inc", "master_universe_source": "daily_scout_append"}],
    )

    assert rows[0]["source_status"] == "existing_master_addition"
