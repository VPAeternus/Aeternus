import csv
import json
from pathlib import Path

from tradingagents.research.fundamental.backtests.high_conviction_top15_exception_sleeve import (
    TARGET_RIGHT_TAIL_NAMES,
    run_high_conviction_top15_exception_sleeve_backtest,
)


def _row(ticker, quarter="2025Q1", score=80, ret90=10, **extra):
    row = {
        "ticker": ticker,
        "quarter": quarter,
        "tradable_date": "2025-01-02",
        "entry_open": "10",
        "entry_score_0_100": str(score),
        "eligible_for_backtest": "True",
        "return_10d_pct": "1",
        "return_20d_pct": "2",
        "return_30d_pct": "3",
        "return_60d_pct": "4",
        "return_90d_pct": str(ret90),
        "winner_90d_30pct": str(ret90 >= 30),
        "loser_90d_minus30pct": str(ret90 <= -30),
        "confidence": "4",
        "cik": "123",
        "cik_status": "resolved",
        "document_status": "CACHED_READY",
    }
    row.update(extra)
    return row


def _write_csv(path: Path, rows):
    fieldnames = sorted({k for r in rows for k in r})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _fixture(tmp_path):
    pit = tmp_path / "pit.csv"
    prior = tmp_path / "prior.csv"
    out = tmp_path / "out"
    rows = [_row(f"C{i}", score=100 - i, ret90=5 + i) for i in range(10)]
    rows += [_row("CRNC", quarter="2024Q4", score=30, ret90=120, rm1_low_price_dislocation_momentum="1", primary_theme="ai")]
    rows += [_row("MISS", score=10, ret90=150)]
    for ticker in TARGET_RIGHT_TAIL_NAMES[1:]:
        rows.append(_row(ticker, score=30, ret90=0, eligible_for_backtest="False"))
    _write_csv(pit, rows)
    baseline = [dict(r, variant="high_conviction_top10_v2_final", selection_rank=i + 1) for i, r in enumerate(rows[:10])]
    _write_csv(prior, baseline)
    manifest = run_high_conviction_top15_exception_sleeve_backtest(pit, prior, out)
    return out, manifest


def _read_rows(path: Path):
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_top15_backtest_outputs_exist(tmp_path):
    out, _ = _fixture(tmp_path)
    for name in [
        "selected_names_by_quarter_top15.csv",
        "strategy_summary_top15.csv",
        "strategy_by_quarter_top15.csv",
        "core_vs_exception_contribution.csv",
        "exception_slot_diagnostics.csv",
        "right_tail_capture_comparison.csv",
        "left_tail_penalty_comparison.csv",
        "missed_right_tail_after_top15.csv",
        "run_manifest.json",
        "README_ANALYSIS.md",
    ]:
        assert (out / name).exists()


def test_core_vs_exception_contribution_present(tmp_path):
    out, _ = _fixture(tmp_path)
    rows = _read_rows(out / "core_vs_exception_contribution.csv")
    assert {r["sleeve"] for r in rows} >= {"core", "right_tail_exception"}


def test_top15_main_variant_includes_core_sleeve_rows(tmp_path):
    out, _ = _fixture(tmp_path)
    rows = _read_rows(out / "selected_names_by_quarter_top15.csv")
    core = [
        r
        for r in rows
        if r["variant"] == "high_conviction_top15_v3_exception_sleeve" and r["selected_sleeve"] == "core"
    ]
    assert len(core) == 10


def test_baseline_top10_name_is_preserved_in_top15_core(tmp_path):
    out, _ = _fixture(tmp_path)
    rows = _read_rows(out / "selected_names_by_quarter_top15.csv")
    baseline = {
        (r["quarter"], r["ticker"])
        for r in rows
        if r["variant"] == "high_conviction_top10_v2_final"
    }
    top15_core = {
        (r["quarter"], r["ticker"])
        for r in rows
        if r["variant"] == "high_conviction_top15_v3_exception_sleeve" and r["selected_sleeve"] == "core"
    }
    assert baseline <= top15_core


def test_right_tail_capture_cannot_mark_old_selected_as_top15_missed(tmp_path):
    out, _ = _fixture(tmp_path)
    rows = _read_rows(out / "right_tail_capture_comparison.csv")
    assert not [
        r
        for r in rows
        if r["old_v2_status"] == "selected" and r["top15_status"] == "missed"
    ]


def test_right_tail_capture_comparison_includes_target_miss_names(tmp_path):
    out, _ = _fixture(tmp_path)
    rows = _read_rows(out / "right_tail_capture_comparison.csv")
    assert set(TARGET_RIGHT_TAIL_NAMES) <= {r["ticker"] for r in rows}
    assert any(r["ticker"] == "CRNC" and r["top15_status"] == "selected" for r in rows)


def test_left_tail_penalty_comparison_present(tmp_path):
    out, _ = _fixture(tmp_path)
    rows = _read_rows(out / "left_tail_penalty_comparison.csv")
    assert "delta_loser_rate_vs_top10" in rows[0]
    assert {r["variant"] for r in rows} >= {"high_conviction_top10_v2_final", "high_conviction_top15_v3_exception_sleeve"}


def test_selection_forbidden_columns_excluded(tmp_path):
    out, manifest = _fixture(tmp_path)
    data = json.loads((out / "run_manifest.json").read_text(encoding="utf-8"))
    forbidden = set(data["forbidden_selection_columns_removed_excluded"])
    assert "return_90d_pct" in forbidden
    assert "return_90d_pct" not in data["feature_columns_used_for_selection"]
    assert manifest["no_leakage_statement"]


def test_manifest_notes_self_hash_exclusion_and_hashes_other_outputs(tmp_path):
    out, _ = _fixture(tmp_path)
    data = json.loads((out / "run_manifest.json").read_text(encoding="utf-8"))
    output_names = {p.name for p in out.iterdir() if p.is_file() and p.name != "run_manifest.json"}
    assert data["manifest_hash_note"]
    assert set(data["output_hashes"]) == output_names
    assert "run_manifest.json" not in data["output_hashes"]


def test_right_tail_visibility_queue_outputs_exist(tmp_path):
    out, _ = _fixture(tmp_path)
    for name in [
        "top15_exception_candidate_queue.csv",
        "right_tail_scout_queue.csv",
        "demote_review_queue.csv",
        "right_tail_evidence_score_diagnostics.csv",
        "target_miss_rescue_audit.csv",
        "v4_rescue_variant_summary.csv",
    ]:
        assert (out / name).exists()


def test_target_audit_has_visibility_metric_columns(tmp_path):
    out, _ = _fixture(tmp_path)
    rows = _read_rows(out / "target_miss_rescue_audit.csv")
    required = {
        "miss_failure_mode",
        "selected_in_top15_v3",
        "selected_sleeve",
        "routed_visibility_layer",
        "target_visibility_routed",
        "target_actionable_research_routed",
        "target_buy_underwriting_routed",
    }
    assert required.issubset(rows[0])
    assert any(r["ticker"] == "CRNC" and r["target_buy_underwriting_routed"] == "1" for r in rows)


def test_manifest_records_right_tail_queue_no_leakage_and_selected_hash(tmp_path):
    out, _ = _fixture(tmp_path)
    manifest = json.loads((out / "run_manifest.json").read_text())
    assert "right_tail_queue_outputs" in manifest
    assert not set(manifest["right_tail_queue_feature_columns"]) & set(manifest["right_tail_queue_forbidden_columns"])
    assert manifest["top15_selected_rows_unchanged_from_prior_hash"] is None
    assert manifest["top15_selected_rows_hash_guard_warning"]

    pit = tmp_path / "pit.csv"
    prior = tmp_path / "prior.csv"
    run_high_conviction_top15_exception_sleeve_backtest(pit, prior, out)
    manifest = json.loads((out / "run_manifest.json").read_text())
    assert manifest["top15_selected_rows_unchanged_from_prior_hash"] is True
    assert manifest["prior_selected_names_by_quarter_top15_sha256"] == manifest["new_selected_names_by_quarter_top15_sha256"]


def test_v4_diagnostics_are_visibility_not_buy_list(tmp_path):
    out, _ = _fixture(tmp_path)
    rows = _read_rows(out / "v4_rescue_variant_summary.csv")
    assert {r["variant"] for r in rows} >= {
        "top15_v4_exception_plus_scout",
        "top15_v4_soft_demote_override",
        "top15_v4_theme_akg_supplier_rescue",
    }
    assert all("visibility" in r["description"].lower() for r in rows)
