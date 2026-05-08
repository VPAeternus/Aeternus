import csv
import json

from typer.testing import CliRunner

import cli.main  # noqa: F401 - registers commands
from cli.common import app


runner = CliRunner()


def _row(ticker: str, score: int, confidence: int = 4, lane: str = "core") -> dict[str, str]:
    return {
        "ticker": ticker,
        "entry_score_0_100": str(score),
        "confidence": str(confidence),
        "cik": "123456",
        "cik_status": "resolved",
        "document_status": "CACHED_READY",
        "lane": lane,
    }


def _write_scores(path, rows):
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def test_fundamental_top10_help_exposes_command_options():
    result = runner.invoke(app, ["fundamental-top10", "--help"])

    assert result.exit_code == 0
    assert "--scores-csv" in result.output
    assert "--coverage-manifest" in result.output
    assert "--top-n" in result.output


def test_fundamental_top10_smoke_writes_csv_json(tmp_path):
    scores = tmp_path / "scores.csv"
    out = tmp_path / "out"
    _write_scores(scores, [_row("AAA", 90), _row("BBB", 69), _row("CCC", 80, lane="momentum")])

    result = runner.invoke(
        app,
        [
            "fundamental-top10",
            "--scores-csv",
            str(scores),
            "--output-root",
            str(out),
            "--date",
            "2026-05-08",
            "--top-n",
            "2",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    csv_path = out / "high_conviction_top10.csv"
    json_path = out / "high_conviction_top10.json"
    assert csv_path.exists()
    assert json_path.exists()
    recommendation_path = out / "high_conviction_top10_daily_recommendation.md"
    assert recommendation_path.exists()

    with csv_path.open("r", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert [row["ticker"] for row in rows] == ["AAA", "CCC"]
    assert {"ticker", "selection_rank", "composite_score", "score", "confidence_numeric", "lane_normalized", "reason_codes"}.issubset(rows[0])

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["date"] == "2026-05-08"
    assert payload["output_paths"]["csv"] == str(csv_path)
    assert payload["output_paths"]["recommendation_md"] == str(recommendation_path)
    assert payload["summary"]["selected_count"] == 2
    assert payload["operating_recommendation"]["operating_setting"] == "high_conviction_top10_v2_final"
    recommendation_text = recommendation_path.read_text(encoding="utf-8")
    assert "single-RM-signal bucket" in recommendation_text
    assert "Be more cautious with RM 2+" in recommendation_text
    assert "higher-left-tail-risk" in recommendation_text
    assert "Apply macro permission manually/live" in recommendation_text
    assert "forward-validating AKG theme acceleration / T5_RESCAN" in recommendation_text


def test_fundamental_top10_rejects_non_positive_top_n(tmp_path):
    scores = tmp_path / "scores.csv"
    _write_scores(scores, [_row("AAA", 90)])

    result = runner.invoke(app, ["fundamental-top10", "--scores-csv", str(scores), "--top-n", "0"])

    assert result.exit_code != 0
    assert "Invalid value" in result.output or "top_n must be > 0" in result.output


def test_fundamental_top10_enables_coverage_gating_when_manifest_provided(tmp_path):
    scores = tmp_path / "scores.csv"
    coverage = tmp_path / "coverage.csv"
    out = tmp_path / "out"
    _write_scores(scores, [_row("AAA", 90), _row("BBB", 88)])
    with coverage.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["ticker", "status"])
        writer.writeheader()
        writer.writerow({"ticker": "AAA", "status": "NEEDS_FETCH"})
        writer.writerow({"ticker": "BBB", "status": "CACHED_READY"})

    result = runner.invoke(
        app,
        [
            "fundamental-top10",
            "--scores-csv",
            str(scores),
            "--coverage-manifest",
            str(coverage),
            "--output-root",
            str(out),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads((out / "high_conviction_top10.json").read_text(encoding="utf-8"))
    assert [row["ticker"] for row in payload["selected_rows"]] == ["BBB"]
    assert payload["config_snapshot"]["coverage_gating"] is True
