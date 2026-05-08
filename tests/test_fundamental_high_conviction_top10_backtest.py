import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tradingagents.research.fundamental.backtests.high_conviction_top10 import main, run_high_conviction_top10_backtest
from tradingagents.research.fundamental.backtests.pit_panel import SELECTION_FEATURE_COLUMNS

REQUIRED_OUTPUTS = {
    "selected_names_by_quarter.csv",
    "strategy_by_quarter.csv",
    "strategy_summary.csv",
    "variant_summary.csv",
    "misses_analysis.csv",
    "theme_bucket_summary.csv",
    "rm_hp_tier_contribution.csv",
    "run_manifest.json",
    "README_ANALYSIS.md",
}
VARIANTS = {"entry_score_top10", "high_conviction_top10_v1", "high_conviction_top10_v2_final"}


def _write_csv(path: Path, rows, fieldnames=None):
    fieldnames = fieldnames or list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path):
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _panel_rows(count=12, quarter="2025Q4"):
    rows = []
    tickers = ["ZZZ", "AAA", "MMM", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH", "III", "JJJ"][:count]
    scores = [95, 95, 90, 89, 88, 87, 86, 85, 84, 83, 82, 81][:count]
    for i, (ticker, score) in enumerate(zip(tickers, scores)):
        rows.append(
            {
                "ticker": ticker,
                "quarter": quarter,
                "tradable_date": "2026-01-05",
                "entry_open": str(10 + i),
                "entry_score_0_100": str(score),
                "eligible_for_backtest": "True",
                "return_10d_pct": str(i),
                "return_20d_pct": str(i + 1),
                "return_30d_pct": str(i + 2),
                "return_60d_pct": str(i + 3),
                "return_90d_pct": str(100 - i),
                "winner_90d_30pct": "True" if i % 2 == 0 else "False",
                "loser_90d_minus30pct": "False",
                "primary_theme": "AI" if i % 2 == 0 else "Energy",
                "hp1_priority": "True" if i % 3 == 0 else "False",
                "rm1_priority": "True" if i % 4 == 0 else "False",
                "tier1_L1_priority": "True" if i % 5 == 0 else "False",
            }
        )
    return rows


def test_writes_required_outputs_and_locked_variants(tmp_path):
    panel = tmp_path / "pit_panel.csv"
    _write_csv(panel, _panel_rows())

    manifest = run_high_conviction_top10_backtest(panel, tmp_path / "out")

    assert {p.name for p in (tmp_path / "out").iterdir()} == REQUIRED_OUTPUTS
    selected = _read_csv(tmp_path / "out" / "selected_names_by_quarter.csv")
    assert {r["variant"] for r in selected} == VARIANTS
    assert manifest["variant_configs"] == {
        "entry_score_top10": {"kind": "entry_score_formula", "top_n": 10, "min_entry_score": 70},
        "high_conviction_top10_v1": {"kind": "hc_formula_v1", "top_n": 10},
        "high_conviction_top10_v2_final": {"kind": "hc_formula_v2_final", "top_n": 10},
    }
    assert "return_90d_pct" in selected[0]
    assert "label" in manifest["label_feature_separation_guardrail"] or "Selection receives feature-only" in manifest["label_feature_separation_guardrail"]


def test_entry_score_variant_excludes_below_70_and_ranks_score_desc_then_ticker(tmp_path):
    panel = tmp_path / "pit_panel.csv"
    rows = _panel_rows()
    rows[9]["entry_score_0_100"] = "69"
    rows[10]["entry_score_0_100"] = "68"
    rows[11]["entry_score_0_100"] = "67"
    _write_csv(panel, rows)

    run_high_conviction_top10_backtest(panel, tmp_path / "out")

    picks = [r for r in _read_csv(tmp_path / "out" / "selected_names_by_quarter.csv") if r["variant"] == "entry_score_top10"]
    assert [(r["selection_rank"], r["ticker"]) for r in picks[:3]] == [("1", "AAA"), ("2", "ZZZ"), ("3", "MMM")]
    assert len(picks) == 9
    assert {r["ticker"] for r in picks}.isdisjoint({"HHH", "III", "JJJ"})
    assert all(r["hc_score"] == r["entry_score_0_100"] + ".000000" for r in picks)


def test_v1_v2_rank_hc_desc_then_entry_desc_then_ticker_asc(tmp_path):
    panel = tmp_path / "pit_panel.csv"
    rows = _panel_rows(5)
    base_flags = {
        "hp_production_extension": "False",
        "hp_LLM_best": "False",
        "repricing_momentum_priority": "False",
        "market_repricing_score": "0",
        "rm_buy_review_flag": "False",
        "theme_acceleration_research_visibility": "False",
        "akg_universe_tier": "",
        "macro_entry_action": "",
        "risk_penalty_score": "0",
        "post_llm_demote_flag": "0",
    }
    for row in rows:
        row.update(base_flags)
    rows[0].update({"ticker": "ENTRY96", "entry_score_0_100": "96"})
    rows[1].update({"ticker": "HP80", "entry_score_0_100": "80", "hp_production_extension": "True", "hp_LLM_best": "True"})
    rows[2].update({"ticker": "ENTRY95", "entry_score_0_100": "95"})
    rows[3].update({"ticker": "CCC", "entry_score_0_100": "94"})
    rows[4].update({"ticker": "BBB", "entry_score_0_100": "94"})
    _write_csv(panel, rows)

    run_high_conviction_top10_backtest(panel, tmp_path / "out")

    selected = _read_csv(tmp_path / "out" / "selected_names_by_quarter.csv")
    expected = [
        ("1", "ENTRY96", "96", "96.000000"),
        ("2", "HP80", "80", "96.000000"),
        ("3", "ENTRY95", "95", "95.000000"),
        ("4", "BBB", "94", "94.000000"),
        ("5", "CCC", "94", "94.000000"),
    ]
    for variant in ["high_conviction_top10_v1", "high_conviction_top10_v2_final"]:
        picks = [r for r in selected if r["variant"] == variant]
        assert [(r["selection_rank"], r["ticker"], r["entry_score_0_100"], r["hc_score"]) for r in picks] == expected


def test_selection_features_use_strict_allowlist_without_forbidden_columns(tmp_path):
    panel = tmp_path / "pit_panel.csv"
    rows = _panel_rows(3)
    for row in rows:
        row["outcome_like_alpha_not_allowlisted"] = "999"
        row["monitoring_score_0_100"] = "999"
        row["final_rank_score_0_100"] = "999"
    _write_csv(panel, rows)

    manifest = run_high_conviction_top10_backtest(panel, tmp_path / "out")

    assert set(manifest["feature_columns_used_for_selection"]).issubset(set(SELECTION_FEATURE_COLUMNS))
    assert not set(manifest["feature_columns_used_for_selection"]) & set(manifest["selection_forbidden_columns"])
    assert "eligible_for_backtest" not in manifest["feature_columns_used_for_selection"]
    assert "outcome_like_alpha_not_allowlisted" in manifest["columns_excluded_from_selection"]


def test_numeric_float_strings_parse_for_eligibility_and_hp_rm_flags(tmp_path):
    panel = tmp_path / "pit_panel.csv"
    rows = _panel_rows(6)
    for row in rows:
        row.update(
            {
                "entry_score_0_100": "50",
                "eligible_for_backtest": "1.0",
                "hp_production_extension": "0.0",
                "hp_LLM_best": "0.0",
                "repricing_momentum_priority": "0.0",
                "market_repricing_score": "0",
                "rm_buy_review_flag": "0.0",
                "theme_acceleration_research_visibility": "0.0",
            }
        )
    rows[0].update({"ticker": "HPFLOAT", "entry_score_0_100": "60", "hp_production_extension": "1.0", "hp_LLM_best": "1.0"})
    rows[1].update({"ticker": "HPZERO", "entry_score_0_100": "60", "hp_production_extension": "0.0", "hp_LLM_best": "0.0"})
    rows[2].update({"ticker": "RMFLOAT", "repricing_momentum_priority": "1.0", "rm_buy_review_flag": "1.0"})
    rows[3].update({"ticker": "RMZERO", "repricing_momentum_priority": "0.0", "rm_buy_review_flag": "0.0"})
    rows[4].update({"ticker": "INELZERO", "entry_score_0_100": "99", "eligible_for_backtest": "0.0"})
    _write_csv(panel, rows)

    manifest = run_high_conviction_top10_backtest(panel, tmp_path / "out")

    selected = _read_csv(tmp_path / "out" / "selected_names_by_quarter.csv")
    v1_tickers = {r["ticker"] for r in selected if r["variant"] == "high_conviction_top10_v1"}
    v2_tickers = {r["ticker"] for r in selected if r["variant"] == "high_conviction_top10_v2_final"}
    assert manifest["eligible_row_count"] == 5
    assert "HPFLOAT" in v1_tickers
    assert "HPZERO" not in v1_tickers
    assert "RMFLOAT" in v2_tickers
    assert "RMZERO" not in v2_tickers
    assert "INELZERO" not in {r["ticker"] for r in selected}


def test_v1_admits_hp_override_rejects_59_and_computes_exact_hc_score(tmp_path):
    panel = tmp_path / "pit_panel.csv"
    rows = _panel_rows(6)
    for row in rows:
        row["entry_score_0_100"] = "50"
        row["hp_production_extension"] = "False"
        row["hp_LLM_best"] = "False"
        row["risk_penalty_score"] = "0"
    rows[0].update({"ticker": "HP60", "entry_score_0_100": "60", "hp_production_extension": "True", "hp_LLM_best": "True"})
    rows[1].update({"ticker": "HP59", "entry_score_0_100": "59", "hp_production_extension": "True", "hp_LLM_best": "True"})
    rows[2].update({"ticker": "CORE", "entry_score_0_100": "70", "risk_penalty_score": "15"})
    _write_csv(panel, rows)

    run_high_conviction_top10_backtest(panel, tmp_path / "out")

    picks = [r for r in _read_csv(tmp_path / "out" / "selected_names_by_quarter.csv") if r["variant"] == "high_conviction_top10_v1"]
    by_ticker = {r["ticker"]: r for r in picks}
    assert "HP60" in by_ticker
    assert "HP59" not in by_ticker
    assert by_ticker["HP60"]["hc_score"] == "76.000000"
    assert by_ticker["CORE"]["hc_score"] == "65.000000"


def test_v2_admits_overrides_blocks_macro_and_computes_exact_hc_score(tmp_path):
    panel = tmp_path / "pit_panel.csv"
    base = _panel_rows(8)
    for row in base:
        row.update(
            {
                "entry_score_0_100": "50",
                "hp_production_extension": "False",
                "hp_LLM_best": "False",
                "repricing_momentum_priority": "False",
                "market_repricing_score": "0",
                "rm_buy_review_flag": "False",
                "theme_acceleration_research_visibility": "False",
                "akg_universe_tier": "",
                "macro_entry_action": "",
                "risk_penalty_score": "0",
                "post_llm_demote_flag": "0",
            }
        )
    base[0].update({"ticker": "RMOK", "repricing_momentum_priority": "True", "market_repricing_score": "14"})
    base[1].update({"ticker": "THEME", "theme_acceleration_research_visibility": "True"})
    base[2].update({"ticker": "T5", "akg_universe_tier": "T5_RESCAN"})
    base[3].update({"ticker": "BLOCK1", "entry_score_0_100": "90", "macro_entry_action": "watchlist_only"})
    base[4].update({"ticker": "BLOCK2", "repricing_momentum_priority": "True", "rm_buy_review_flag": "True", "macro_entry_action": "no_new_buy"})
    base[5].update({"ticker": "EXACT", "entry_score_0_100": "70", "hp_LLM_best": "True", "hp_production_extension": "True", "repricing_momentum_priority": "True", "market_repricing_score": "14", "theme_acceleration_research_visibility": "True", "akg_universe_tier": "T5_RESCAN", "risk_penalty_score": "15", "post_llm_demote_flag": "1"})
    _write_csv(panel, base)

    run_high_conviction_top10_backtest(panel, tmp_path / "out")

    picks = [r for r in _read_csv(tmp_path / "out" / "selected_names_by_quarter.csv") if r["variant"] == "high_conviction_top10_v2_final"]
    by_ticker = {r["ticker"]: r for r in picks}
    assert {"RMOK", "THEME", "T5", "EXACT"}.issubset(by_ticker)
    assert "BLOCK1" not in by_ticker
    assert "BLOCK2" not in by_ticker
    assert by_ticker["RMOK"]["hc_score"] == "64.000000"
    assert by_ticker["THEME"]["hc_score"] == "56.000000"
    assert by_ticker["T5"]["hc_score"] == "54.000000"
    assert by_ticker["EXACT"]["hc_score"] == "95.000000"


def test_monitoring_and_final_rank_scores_do_not_affect_selection(tmp_path):
    panel_a = tmp_path / "a_scores.csv"
    panel_b = tmp_path / "b_scores.csv"
    rows_a = _panel_rows()
    rows_b = [dict(r) for r in rows_a]
    for i, row in enumerate(rows_b):
        row["monitoring_score_0_100"] = str(1000 - i)
        row["final_rank_score_0_100"] = str(2000 - i)
    _write_csv(panel_a, rows_a)
    _write_csv(panel_b, rows_b)

    run_high_conviction_top10_backtest(panel_a, tmp_path / "out_a")
    run_high_conviction_top10_backtest(panel_b, tmp_path / "out_b")

    def selected(path):
        rows = _read_csv(path / "selected_names_by_quarter.csv")
        return [(r["variant"], r["quarter"], r["selection_rank"], r["ticker"]) for r in rows]

    assert selected(tmp_path / "out_a") == selected(tmp_path / "out_b")


def test_labels_attached_post_selection_do_not_affect_ranking(tmp_path):
    panel_a = tmp_path / "a.csv"
    panel_b = tmp_path / "b.csv"
    rows_a = _panel_rows()
    rows_b = [dict(r) for r in rows_a]
    for i, row in enumerate(rows_b):
        row["return_90d_pct"] = str(10000 - i * 777)
        row["winner_90d_30pct"] = "False" if row["winner_90d_30pct"] == "True" else "True"
    _write_csv(panel_a, rows_a)
    _write_csv(panel_b, rows_b)

    run_high_conviction_top10_backtest(panel_a, tmp_path / "out_a")
    run_high_conviction_top10_backtest(panel_b, tmp_path / "out_b")

    def selected(path):
        rows = _read_csv(path / "selected_names_by_quarter.csv")
        return [(r["variant"], r["quarter"], r["selection_rank"], r["ticker"]) for r in rows]

    assert selected(tmp_path / "out_a") == selected(tmp_path / "out_b")
    assert "return_90d_pct" in json.loads((tmp_path / "out_a" / "run_manifest.json").read_text())["forbidden_outcome_columns_removed_from_selection"]


def test_duplicate_quarter_ticker_rows_fail_fast(tmp_path):
    panel = tmp_path / "pit_panel.csv"
    duplicate = {**_panel_rows(1)[0]}
    _write_csv(panel, _panel_rows(1) + [duplicate])

    with pytest.raises(ValueError, match=r"duplicate \(quarter,ticker\)"):
        run_high_conviction_top10_backtest(panel, tmp_path / "out")


def test_shortfall_with_fewer_than_10_eligible_rows(tmp_path):
    panel = tmp_path / "pit_panel.csv"
    rows = _panel_rows(5) + [{**_panel_rows(1)[0], "ticker": "INEL", "eligible_for_backtest": "False", "entry_score_0_100": "999"}]
    _write_csv(panel, rows)

    run_high_conviction_top10_backtest(panel, tmp_path / "out")

    by_quarter = _read_csv(tmp_path / "out" / "strategy_by_quarter.csv")
    assert all(r["pick_count"] == "5" and r["shortfall"] == "True" for r in by_quarter)
    selected_tickers = {r["ticker"] for r in _read_csv(tmp_path / "out" / "selected_names_by_quarter.csv")}
    assert "INEL" not in selected_tickers


def test_misses_theme_and_hp_rm_tier_outputs_aggregate(tmp_path):
    panel = tmp_path / "pit_panel.csv"
    _write_csv(panel, _panel_rows(12))

    run_high_conviction_top10_backtest(panel, tmp_path / "out")

    misses = _read_csv(tmp_path / "out" / "misses_analysis.csv")
    assert misses
    assert all(r["why_missed"] == "NOT_IN_TOP10" for r in misses)
    selected = {(r["variant"], r["quarter"], r["ticker"]) for r in _read_csv(tmp_path / "out" / "selected_names_by_quarter.csv")}
    assert not any((r["variant"], r["quarter"], r["ticker"]) in selected for r in misses)
    assert _read_csv(tmp_path / "out" / "theme_bucket_summary.csv")
    contrib = _read_csv(tmp_path / "out" / "rm_hp_tier_contribution.csv")
    assert {r["dimension"] for r in contrib} == {"hp", "rm", "tier"}


def test_missing_required_panel_headers_fail_fast(tmp_path):
    panel = tmp_path / "bad.csv"
    _write_csv(panel, [{"ticker": "AAA", "quarter": "2025Q4"}])

    with pytest.raises(ValueError, match="missing required header"):
        run_high_conviction_top10_backtest(panel, tmp_path / "out")


def test_main_default_output_dir_contract(tmp_path, monkeypatch, capsys):
    panel = tmp_path / "pit_panel.csv"
    _write_csv(panel, _panel_rows(10))
    monkeypatch.chdir(tmp_path)

    assert main([str(panel)]) == 0

    captured = capsys.readouterr()
    default_out = tmp_path / "outputs" / "fundamental_backtest" / "high_conviction_top10"
    assert json.loads(captured.out)["output_dir"] == "outputs/fundamental_backtest/high_conviction_top10"
    assert {p.name for p in default_out.iterdir()} == REQUIRED_OUTPUTS


def test_module_cli_explicit_output_dir_contract(tmp_path):
    panel = tmp_path / "pit_panel.csv"
    _write_csv(panel, _panel_rows(10))
    out = tmp_path / "out"

    result = subprocess.run(
        [sys.executable, "-m", "tradingagents.research.fundamental.backtests.high_conviction_top10", str(panel), "--output-dir", str(out)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout)["quarter_count"] == 1
    assert {p.name for p in out.iterdir()} == REQUIRED_OUTPUTS


def test_strategy_summary_averages_quarterly_portfolio_returns_not_pooled_picks(tmp_path):
    panel = tmp_path / "pit_panel.csv"
    q1 = _panel_rows(10, "2025Q4")
    q2 = _panel_rows(2, "2026Q1")
    for row in q1:
        row["return_90d_pct"] = "10"
    for row in q2:
        row["return_90d_pct"] = "100"
    _write_csv(panel, q1 + q2)

    run_high_conviction_top10_backtest(panel, tmp_path / "out")

    summary = {r["variant"]: r for r in _read_csv(tmp_path / "out" / "strategy_summary.csv")}
    assert summary["entry_score_top10"]["avg_return_90d_pct"] == "55.000000"


def test_manifest_excludes_self_hash(tmp_path):
    panel = tmp_path / "pit_panel.csv"
    _write_csv(panel, _panel_rows())

    run_high_conviction_top10_backtest(panel, tmp_path / "out")

    manifest = json.loads((tmp_path / "out" / "run_manifest.json").read_text())
    assert "run_manifest.json" not in manifest["output_hashes"]
    assert "self-referential" in manifest["manifest_hash_note"]


def test_module_cli_missing_file_returns_exit_2_without_traceback(tmp_path):
    missing = tmp_path / "missing.csv"

    result = subprocess.run(
        [sys.executable, "-m", "tradingagents.research.fundamental.backtests.high_conviction_top10", str(missing), "--output-dir", str(tmp_path / "out")],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "error:" in result.stderr
    assert "Traceback" not in result.stderr


def test_multi_quarter_grouping_reflected_in_outputs(tmp_path):
    panel = tmp_path / "pit_panel.csv"
    _write_csv(panel, _panel_rows(12, "2025Q4") + _panel_rows(12, "2026Q1"))

    manifest = run_high_conviction_top10_backtest(panel, tmp_path / "out")

    assert manifest["quarter_count"] == 2
    by_quarter = _read_csv(tmp_path / "out" / "strategy_by_quarter.csv")
    assert {r["quarter"] for r in by_quarter} == {"2025Q4", "2026Q1"}
    assert {r["variant"] for r in by_quarter} == VARIANTS
    assert len(by_quarter) == len(VARIANTS) * 2
    variant_summary = _read_csv(tmp_path / "out" / "variant_summary.csv")
    assert {r["variant"]: r["quarter_count"] for r in variant_summary} == {v: "2" for v in VARIANTS}
