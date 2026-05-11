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


def test_fundamental_top15_refill_shadow_cli_writes_shadow_outputs(tmp_path):
    scores = tmp_path / "scores.csv"
    out = tmp_path / "out"
    _write_scores(scores)

    result = runner.invoke(app, [
        "fundamental-top15-refill-shadow",
        "--scores-csv", str(scores),
        "--output-root", str(out),
        "--date", "2026-05-11",
        "--mode", "strict",
    ])

    assert result.exit_code == 0, result.output
    assert (out / "high_conviction_top15_core_deterioration_refill_shadow.csv").exists()
    assert (out / "core_deterioration_refill_shadow_replacements.csv").exists()
    assert "Wrote shadow" in result.output
