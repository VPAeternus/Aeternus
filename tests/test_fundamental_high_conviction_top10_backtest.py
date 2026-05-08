import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tradingagents.research.fundamental.backtests.high_conviction_top10 import run_high_conviction_top10_backtest

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
    assert set(manifest["variant_configs"]) == VARIANTS
    assert "return_90d_pct" in selected[0]
    assert "label" in manifest["label_feature_separation_guardrail"] or "Selection receives feature-only" in manifest["label_feature_separation_guardrail"]


def test_entry_score_variant_ranks_score_desc_then_ticker(tmp_path):
    panel = tmp_path / "pit_panel.csv"
    _write_csv(panel, _panel_rows())

    run_high_conviction_top10_backtest(panel, tmp_path / "out")

    picks = [r for r in _read_csv(tmp_path / "out" / "selected_names_by_quarter.csv") if r["variant"] == "entry_score_top10"]
    assert [(r["selection_rank"], r["ticker"]) for r in picks[:3]] == [("1", "AAA"), ("2", "ZZZ"), ("3", "MMM")]
    assert len(picks) == 10


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


def test_module_cli_default_contract(tmp_path):
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
