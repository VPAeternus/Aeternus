import csv
import json
from pathlib import Path

from tradingagents.research.fundamental.backtests.high_conviction_top15_exception_sleeve import (
    TARGET_RIGHT_TAIL_NAMES,
    run_high_conviction_top15_exception_sleeve_backtest,
)
from tradingagents.research.fundamental.src.selection.right_tail_queues import RIGHT_TAIL_SCORING_COLUMNS


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
        "akg_universe_tier": "",
        "macro_entry_action": "",
        "source_file_hash": "fixture-source-hash",
    }
    row.update(extra)
    return row


def _write_csv(path: Path, rows):
    fieldnames = sorted({k for r in rows for k in r})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _fixture(tmp_path, inject_forbidden=False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    pit = tmp_path / "pit.csv"
    prior = tmp_path / "prior.csv"
    out = tmp_path / "out"
    rows = [_row(f"C{i}", score=100 - i, ret90=5 + i) for i in range(10)]
    rows += [_row("CRNC", quarter="2024Q4", score=30, ret90=120, rm1_low_price_dislocation_momentum="1", primary_theme="ai")]
    rows += [_row("MISS", score=10, ret90=150)]
    for ticker in TARGET_RIGHT_TAIL_NAMES[1:]:
        rows.append(_row(ticker, score=30, ret90=0, eligible_for_backtest="False"))
    if inject_forbidden:
        for idx, row in enumerate(rows):
            row.update({
                "return_999d_pct": "999999" if idx % 2 else "-999999",
                "return_since_signal_extreme_pct": "999999",
                "future_return_pct": "999999",
                "winner_future_label": "1",
                "target_label": "BUY_NOW",
                "final_current_return_rank": "1",
                "monitoring_score_shadow": "100",
            })
    _write_csv(pit, rows)
    baseline = [dict(r, variant="high_conviction_top10_v2_final", selection_rank=i + 1) for i, r in enumerate(rows[:10])]
    _write_csv(prior, baseline)
    manifest = run_high_conviction_top15_exception_sleeve_backtest(pit, prior, out)
    return out, manifest


def _read_rows(path: Path):
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_v2_candidates_returns_full_ex_ante_ranked_pool():
    from tradingagents.research.fundamental.backtests.high_conviction_top10 import _select_v2, _v2_candidates

    rows = [_row(f"C{i}", score=100 - i) for i in range(12)]
    rows[-1]["return_90d_pct"] = "999"
    pool = _v2_candidates(rows)
    selected = _select_v2(rows)

    assert len(pool) == 12
    assert [r["ticker"] for r in pool[:10]] == [r["ticker"] for r in selected]
    assert [r["core_candidate_rank"] for r in pool[:3]] == [1, 2, 3]
    assert pool[-1]["ticker"] == "C11"


def test_top15_backtest_outputs_exist(tmp_path):
    out, _ = _fixture(tmp_path)
    for name in [
        "selected_names_by_quarter_top15.csv",
        "strategy_summary_top15.csv",
        "strategy_by_quarter_top15.csv",
        "core_vs_exception_contribution.csv",
        "exception_slot_diagnostics.csv",
        "core_deterioration_review_queue.csv",
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
        "demote_review_priority_1.csv",
        "demote_review_priority_2.csv",
        "demote_review_low_priority.csv",
        "thin_signal_watchlist_queue.csv",
        "thin_signal_watchlist_top100.csv",
        "right_tail_evidence_score_diagnostics.csv",
        "pit_feature_lineage_audit.csv",
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
        "target_scout_or_top15_routed",
        "target_demote_review_routed",
        "target_buy_underwriting_routed",
    }
    assert required.issubset(rows[0])
    assert any(r["ticker"] == "CRNC" and r["target_buy_underwriting_routed"] == "1" for r in rows)


def test_manifest_records_right_tail_queue_no_leakage_and_selected_hash(tmp_path):
    out, _ = _fixture(tmp_path)
    manifest = json.loads((out / "run_manifest.json").read_text())
    assert "right_tail_queue_outputs" in manifest
    assert "core_deterioration_review_count" in manifest
    assert "core_deterioration_review_queue" in manifest["right_tail_queue_outputs"]
    assert "right_tail_queue_feature_columns" not in manifest
    assert not set(manifest["right_tail_queue_input_columns"]) & set(manifest["right_tail_queue_forbidden_columns"])
    assert not set(manifest["right_tail_queue_scoring_columns"]) & set(manifest["right_tail_queue_forbidden_columns"])
    assert "pipeline_run_id" not in manifest["right_tail_queue_scoring_columns"]
    for field in [
        "post_llm_demote_severity",
        "post_llm_demote_reason_code",
        "post_llm_demote_overrideable",
        "post_llm_demote_evidence",
        "filing_theme_growth_flag",
        "filing_theme_guidance_flag",
        "theme_tags",
        "theme_evidence_summary",
    ]:
        assert field in manifest["right_tail_queue_scoring_columns"]
    assert manifest["top15_selected_rows_unchanged_from_prior_hash"] is None
    assert manifest["top15_selected_rows_hash_guard_warning"]
    assert "target_scout_or_top15_count" in manifest
    assert "target_demote_review_count" in manifest

    pit = tmp_path / "pit.csv"
    prior = tmp_path / "prior.csv"
    run_high_conviction_top15_exception_sleeve_backtest(pit, prior, out)
    manifest = json.loads((out / "run_manifest.json").read_text())
    assert manifest["top15_selected_rows_unchanged_from_prior_hash"] is True
    assert manifest["prior_selected_names_by_quarter_top15_sha256"] == manifest["new_selected_names_by_quarter_top15_sha256"]


def test_right_tail_manifest_scoring_columns_match_constant(tmp_path):
    out, _ = _fixture(tmp_path)
    manifest = json.loads((out / "run_manifest.json").read_text())

    assert set(manifest["right_tail_queue_scoring_columns"]) == set(RIGHT_TAIL_SCORING_COLUMNS)


def test_pit_feature_lineage_audit_covers_selection_and_right_tail_fields(tmp_path):
    out, _ = _fixture(tmp_path)
    manifest = json.loads((out / "run_manifest.json").read_text())
    audit = _read_rows(out / "pit_feature_lineage_audit.csv")
    by_field = {row["field"]: row for row in audit}

    assert set(manifest["feature_columns_used_for_selection"]) <= set(by_field)
    assert set(RIGHT_TAIL_SCORING_COLUMNS) <= set(by_field)
    assert by_field["entry_score_0_100"]["layer"] == "both"
    assert by_field["akg_universe_tier"]["pit_status"] == "not_full_production_v2_validated_missing_pit_provenance"
    assert by_field["primary_theme"]["pit_status"] == "not_full_production_v2_validated"
    assert by_field["macro_entry_action"]["pit_status"] == "not_full_production_v2_validated"
    assert "pit_feature_lineage_status_counts" in manifest
    assert "pit_feature_lineage_audit.csv" in manifest["output_hashes"]
    assert manifest["right_tail_queue_outputs"]["pit_feature_lineage_audit"] == "pit_feature_lineage_audit.csv"


def test_injected_forbidden_columns_do_not_change_top15_or_right_tail_outputs(tmp_path):
    clean_out, _ = _fixture(tmp_path / "clean")
    injected_out, _ = _fixture(tmp_path / "injected", inject_forbidden=True)

    for name in [
        "selected_names_by_quarter_top15.csv",
        "top15_exception_candidate_queue.csv",
        "right_tail_scout_queue.csv",
        "demote_review_queue.csv",
        "thin_signal_watchlist_queue.csv",
        "right_tail_evidence_score_diagnostics.csv",
    ]:
        assert (injected_out / name).read_text(encoding="utf-8") == (clean_out / name).read_text(encoding="utf-8")

    manifest = json.loads((injected_out / "run_manifest.json").read_text())
    assert "return_999d_pct" in manifest["forbidden_selection_columns_removed_excluded"]
    assert "target_label" in manifest["right_tail_queue_forbidden_columns"]
    assert "return_999d_pct" not in manifest["right_tail_queue_input_columns"]


def test_v4_diagnostics_are_visibility_not_buy_list(tmp_path):
    out, _ = _fixture(tmp_path)
    rows = _read_rows(out / "v4_rescue_variant_summary.csv")
    assert {r["variant"] for r in rows} >= {
        "top15_v4_exception_plus_scout",
        "top15_v4_soft_demote_override",
        "top15_v4_theme_akg_supplier_rescue",
    }
    assert all("visibility" in r["description"].lower() for r in rows)
    assert {"scout_or_top15_routed_count", "demote_review_routed_count"}.issubset(rows[0])


def test_top15_analysis_emits_queue_visibility_tables(tmp_path):
    from scripts.analyze_fundamental_top15_exception_sleeve import run

    out_bundle, _ = _fixture(tmp_path)
    analysis_out = tmp_path / "analysis"
    report = tmp_path / "report.md"
    run(out_bundle, Path("outputs/fundamental_backtest/analysis"), analysis_out, report)

    assert (analysis_out / "right_tail_queue_summary.csv").exists()
    assert (analysis_out / "target_visibility_metrics.csv").exists()
    assert (analysis_out / "target_miss_rescue_audit.csv").exists()
    assert (analysis_out / "demote_review_priority_1.csv").exists()
    assert (analysis_out / "thin_signal_watchlist_top100.csv").exists()
    text = report.read_text()
    assert "Right-Tail Scout + Demote Review" in text
    assert "visibility/research outputs, not buy lists" in text
    assert "visibility-routed" in text
    assert "`blocked_hard_demote` counts as visibility only" in text
    assert "non-hard `demote_review` is human research review" in text
    assert "target_scout_or_top15_routed_count" in (analysis_out / "target_visibility_metrics.csv").read_text()
    assert "target_demote_review_routed_count" in (analysis_out / "target_visibility_metrics.csv").read_text()
