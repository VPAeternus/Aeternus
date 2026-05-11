import csv

from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


def _write_scores(path):
    rows = []
    for idx in range(9):
        rows.append({"ticker": f"C{idx}", "entry_score_0_100": str(100 - idx), "confidence": "4", "cik": "123", "cik_status": "resolved", "document_status": "CACHED_READY"})
    rows.insert(5, {
        "ticker": "BAD",
        "entry_score_0_100": "95",
        "confidence": "4",
        "cik": "123",
        "cik_status": "resolved",
        "document_status": "CACHED_READY",
        "score_change": "-2",
        "negative_revision_risk": "2",
        "pre_llm_fundamental_bucket": "weak",
        "primary_theme": "",
        "rm1_low_price_dislocation_momentum": "RM1 - Low-price dislocation momentum",
        "rm2_weak_acceleration": "RM2 - Weak-bucket acceleration",
        "rm4_persistent_repricing_wave": "RM4 - Persistent repricing wave",
    })
    rows.append({"ticker": "NEXT", "entry_score_0_100": "89", "confidence": "4", "cik": "123", "cik_status": "resolved", "document_status": "CACHED_READY"})
    fieldnames = sorted({k for r in rows for k in r})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _invoke_shadow(scores, *args):
    return runner.invoke(app, [
        "fundamental-top15-refill-shadow",
        "--scores-csv", str(scores),
        *args,
    ])


def test_fundamental_top15_refill_shadow_cli_writes_shadow_outputs(tmp_path):
    scores = tmp_path / "scores.csv"
    out = tmp_path / "out"
    _write_scores(scores)

    result = _invoke_shadow(
        scores,
        "--output-root", str(out),
        "--date", "2026-05-11",
        "--mode", "strict",
    )

    assert result.exit_code == 0, result.output
    assert (out / "high_conviction_top15_core_deterioration_refill_shadow.csv").exists()
    assert (out / "core_deterioration_refill_shadow_replacements.csv").exists()
    assert "Wrote shadow" in result.output


def test_fundamental_top15_refill_shadow_cli_json_output(tmp_path):
    scores = tmp_path / "scores.csv"
    out = tmp_path / "out"
    _write_scores(scores)

    result = _invoke_shadow(
        scores,
        "--output-root", str(out),
        "--date", "2026-05-11",
        "--format", "json",
    )

    assert result.exit_code == 0, result.output
    assert "high_conviction_top15_v4_core_deterioration_refill_shadow" in result.output
    assert "core_deterioration_refill_rows" in result.output


def test_fundamental_top15_refill_shadow_cli_rejects_invalid_mode(tmp_path):
    scores = tmp_path / "scores.csv"
    _write_scores(scores)

    result = _invoke_shadow(scores, "--mode", "rank78_review")

    assert result.exit_code != 0
    assert "--mode must be" in result.output


def test_fundamental_top15_refill_shadow_cli_missing_scores_path(tmp_path):
    result = _invoke_shadow(tmp_path / "missing.csv")

    assert result.exit_code != 0
    assert "scores CSV not found" in result.output


def test_fundamental_top15_refill_shadow_cli_rejects_scores_directory(tmp_path):
    result = _invoke_shadow(tmp_path)

    assert result.exit_code != 0
    assert "scores CSV not found" in result.output


def test_fundamental_top15_refill_shadow_cli_rejects_invalid_date(tmp_path):
    scores = tmp_path / "scores.csv"
    _write_scores(scores)

    result = _invoke_shadow(scores, "--date", "../shadow")

    assert result.exit_code != 0
    assert "--date must be YYYY-MM-DD" in result.output


def test_fundamental_top15_refill_shadow_cli_default_output_root(tmp_path, monkeypatch):
    scores = tmp_path / "scores.csv"
    _write_scores(scores)
    monkeypatch.chdir(tmp_path)

    result = _invoke_shadow(scores, "--date", "2026-05-11")

    assert result.exit_code == 0, result.output
    out = tmp_path / "eval_results" / "fundamental" / "2026-05-11"
    assert (out / "high_conviction_top15_core_deterioration_refill_shadow.csv").exists()
    assert (out / "core_deterioration_refill_shadow_replacements.csv").exists()


def test_fundamental_top15_refill_shadow_cli_missing_coverage_manifest(tmp_path):
    scores = tmp_path / "scores.csv"
    _write_scores(scores)

    result = _invoke_shadow(scores, "--coverage-manifest", str(tmp_path / "missing_coverage.csv"))

    assert result.exit_code != 0
    assert "coverage manifest not found" in result.output


def test_fundamental_top15_refill_shadow_cli_rejects_coverage_manifest_directory(tmp_path):
    scores = tmp_path / "scores.csv"
    _write_scores(scores)

    result = _invoke_shadow(scores, "--coverage-manifest", str(tmp_path))

    assert result.exit_code != 0
    assert "coverage manifest not found" in result.output
