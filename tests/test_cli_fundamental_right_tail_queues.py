import csv
import json

from typer.testing import CliRunner

import cli.main  # noqa: F401
from cli.common import app

runner = CliRunner()


def write_scores_csv(tmp_path):
    scores = tmp_path / "scores.csv"
    rows = [
        {"ticker": "CRNC", "quarter": "2024Q4", "entry_score_0_100": "29", "post_llm_demote_flag": "1", "rm_buy_review_flag": "1", "market_repricing_score": "10"},
        {"ticker": "ICHR", "quarter": "2026Q1", "entry_score_0_100": "3", "primary_theme": "semicap", "theme_role": "supplier", "market_repricing_score": "14", "theme_tailwind_score": "8", "filing_theme_growth_flag": "1"},
        {"ticker": "CRDO", "quarter": "2024Q3", "entry_score_0_100": "88", "primary_theme": "optical supplier", "theme_role": "supplier", "market_repricing_score": "14", "repricing_momentum_priority": "1"},
    ]
    with scores.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=sorted({k for r in rows for k in r}))
        writer.writeheader()
        writer.writerows(rows)
    return scores


def write_top15_selected_csv(tmp_path, keys):
    path = tmp_path / "high_conviction_top15.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["ticker", "quarter", "selected_sleeve"])
        writer.writeheader()
        for ticker, quarter in keys:
            writer.writerow({"ticker": ticker, "quarter": quarter, "selected_sleeve": "right_tail_exception"})
    return path


def write_target_events_csv(tmp_path):
    path = tmp_path / "targets.csv"
    path.write_text("ticker,quarter\nCRNC,2024Q4\nICHR,2026Q1\n", encoding="utf-8")
    return path


def test_fundamental_right_tail_queues_writes_default_daily_outputs_without_target_audit(tmp_path):
    scores = write_scores_csv(tmp_path)
    top15 = write_top15_selected_csv(tmp_path, [("CRDO", "2024Q3")])
    out = tmp_path / "out"

    result = runner.invoke(app, [
        "fundamental-right-tail-queues",
        "--scores-csv", str(scores),
        "--top15-selected-csv", str(top15),
        "--output-root", str(out),
        "--date", "2026-05-09",
        "--format", "json",
    ])

    assert result.exit_code == 0, result.output
    for name in [
        "top15_exception_candidate_queue.csv",
        "right_tail_scout_queue.csv",
        "demote_review_queue.csv",
        "demote_review_priority_1.csv",
        "demote_review_priority_2.csv",
        "demote_review_low_priority.csv",
        "thin_signal_watchlist_queue.csv",
        "thin_signal_watchlist_top100.csv",
        "right_tail_evidence_score_diagnostics.csv",
        "right_tail_queues.json",
    ]:
        assert (out / name).exists()
    assert not (out / "target_miss_rescue_audit.csv").exists()
    payload = json.loads((out / "right_tail_queues.json").read_text())
    assert payload["date"] == "2026-05-09"
    assert "thin_signal_watchlist_top100" in payload["output_paths"]
    assert "demote_review_priority_1" in payload["output_paths"]


def test_fundamental_right_tail_queues_writes_target_audit_only_when_requested(tmp_path):
    scores = write_scores_csv(tmp_path)
    top15 = write_top15_selected_csv(tmp_path, [("CRDO", "2024Q3")])
    target_events = write_target_events_csv(tmp_path)
    out = tmp_path / "out"

    result = runner.invoke(app, [
        "fundamental-right-tail-queues",
        "--scores-csv", str(scores),
        "--top15-selected-csv", str(top15),
        "--target-events-csv", str(target_events),
        "--output-root", str(out),
    ])

    assert result.exit_code == 0, result.output
    assert (out / "target_miss_rescue_audit.csv").exists()


def test_missing_top15_selected_csv_warns_but_does_not_fail(tmp_path):
    scores = write_scores_csv(tmp_path)
    out = tmp_path / "out"

    result = runner.invoke(app, [
        "fundamental-right-tail-queues",
        "--scores-csv", str(scores),
        "--output-root", str(out),
    ])

    assert result.exit_code == 0, result.output
    assert "Top15 selected CSV not provided" in result.output
