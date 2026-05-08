"""High-conviction Top-10 PIT backtest exporter.

Selection uses only selection-time features. Forward returns / outcome labels are
reattached after selections are frozen for diagnostics.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

from tradingagents.research.fundamental.src.selection.high_conviction_top10 import select_high_conviction_top10

RUNNER_VERSION = "fundamental_high_conviction_top10_backtest_task3_v1"
DEFAULT_OUTPUT_DIR = Path("outputs/fundamental_backtest/high_conviction_top10")
REQUIRED_HEADERS = {"ticker", "quarter", "tradable_date", "entry_open", "entry_score_0_100", "eligible_for_backtest"}
LABEL_COLUMNS = ["return_10d_pct", "return_20d_pct", "return_30d_pct", "return_60d_pct", "return_90d_pct"]
OUTCOME_COLUMNS = set(LABEL_COLUMNS) | {"winner_90d_30pct", "loser_90d_minus30pct"}
VARIANTS: dict[str, dict[str, Any]] = {
    "entry_score_top10": {"kind": "entry_score", "top_n": 10},
    "high_conviction_top10_v1": {
        "kind": "selector",
        "top_n": 10,
        "min_score": 70,
        "min_confidence": 3,
        "require_confidence": False,
        "allow_overrides": True,
        "coverage_gating": False,
    },
    "high_conviction_top10_v2_final": {
        "kind": "selector",
        "top_n": 10,
        "min_score": 75,
        "min_confidence": 3,
        "require_confidence": False,
        "allow_overrides": True,
        "coverage_gating": False,
        "core_target": 6,
        "momentum_target": 2,
        "opportunistic_target": 2,
    },
}
OUTPUT_FILES = [
    "selected_names_by_quarter.csv",
    "strategy_by_quarter.csv",
    "strategy_summary.csv",
    "variant_summary.csv",
    "misses_analysis.csv",
    "theme_bucket_summary.csv",
    "rm_hp_tier_contribution.csv",
    "README_ANALYSIS.md",
]


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        headers = reader.fieldnames or []
        missing = sorted(REQUIRED_HEADERS - set(headers))
        if missing:
            raise ValueError(f"PIT panel missing required header(s) {missing}: {path}")
        return list(reader), headers


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], preferred: Sequence[str] = ()) -> None:
    cols = list(preferred)
    for row in rows:
        for key in row:
            if key not in cols:
                cols.append(key)
    if not cols:
        cols = list(preferred) or ["empty"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v for k, v in row.items()})


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _to_float(value: Any) -> float | None:
    try:
        text = str(value).strip()
        return float(text) if text else None
    except (TypeError, ValueError):
        return None


def _avg(rows: Sequence[Mapping[str, Any]], col: str) -> str:
    vals = [_to_float(r.get(col)) for r in rows]
    nums = [v for v in vals if v is not None]
    return f"{sum(nums) / len(nums):.6f}" if nums else ""


def _rate(rows: Sequence[Mapping[str, Any]], col: str) -> str:
    if not rows:
        return ""
    return f"{sum(_truthy(r.get(col)) for r in rows) / len(rows):.6f}"


def _feature_columns(headers: Sequence[str]) -> list[str]:
    forbidden = {h for h in headers if h in OUTCOME_COLUMNS or h.startswith("return_") or h.startswith("forward_")}
    return [h for h in headers if h not in forbidden]


def _decorative_columns(headers: Sequence[str]) -> list[str]:
    needles = ("hp", "rm", "tier", "theme")
    return [h for h in headers if any(n in h.lower() for n in needles)]


def _eligible_groups(rows: Sequence[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if _truthy(row.get("eligible_for_backtest")):
            groups[str(row.get("quarter", "")).strip()].append(row)
    return dict(groups)


def _freeze_selection_row(row: Mapping[str, Any], original: Mapping[str, Any], variant: str, quarter: str, rank: int) -> dict[str, Any]:
    out = dict(row)
    out.update({c: original.get(c, "") for c in OUTCOME_COLUMNS if c in original})
    out["variant"] = variant
    out["quarter"] = quarter
    out["snapshot_date"] = original.get("tradable_date", row.get("tradable_date", ""))
    out["tradable_date"] = original.get("tradable_date", row.get("tradable_date", ""))
    out["selection_rank"] = rank
    out["ticker"] = str(original.get("ticker", row.get("ticker", ""))).upper()
    return out


def _select_entry_score(rows: Sequence[dict[str, str]]) -> list[dict[str, Any]]:
    ranked = sorted(rows, key=lambda r: (-(_to_float(r.get("entry_score_0_100")) or float("-inf")), str(r.get("ticker", "")).upper()))
    selected = []
    for rank, row in enumerate(ranked[:10], 1):
        selected.append({**row, "score": row.get("entry_score_0_100", ""), "composite_score": row.get("entry_score_0_100", ""), "selection_rank": rank, "selected": True})
    return selected


def _select_variant(name: str, rows: Sequence[dict[str, str]], feature_cols: Sequence[str]) -> list[dict[str, Any]]:
    cfg = dict(VARIANTS[name])
    kind = cfg.pop("kind")
    if kind == "entry_score":
        return _select_entry_score([{c: r.get(c, "") for c in feature_cols} for r in rows])
    cfg["score_field"] = "entry_score_0_100"
    safe_rows = [{c: r.get(c, "") for c in feature_cols} for r in rows]
    return select_high_conviction_top10(safe_rows, cfg)["selected_rows"]


def _summarize(variant: str, quarter: str, picks: Sequence[Mapping[str, Any]], eligible_count: int) -> dict[str, Any]:
    row: dict[str, Any] = {"variant": variant, "quarter": quarter, "pick_count": len(picks), "shortfall": len(picks) < 10, "eligible_count": eligible_count}
    for col in LABEL_COLUMNS:
        row[f"avg_{col}"] = _avg(picks, col)
    row["winner_90d_30pct_rate"] = _rate(picks, "winner_90d_30pct")
    row["loser_90d_minus30pct_rate"] = _rate(picks, "loser_90d_minus30pct")
    return row


def _aggregate_strategy(variant: str, picks: Sequence[Mapping[str, Any]], quarter_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    quarters = {r["quarter"] for r in quarter_rows if r["variant"] == variant}
    row: dict[str, Any] = {"variant": variant, "quarter_count": len(quarters), "total_picks": len(picks), "avg_picks_per_quarter": f"{len(picks) / len(quarters):.6f}" if quarters else ""}
    for col in LABEL_COLUMNS:
        row[f"avg_{col}"] = _avg(picks, col)
    row["winner_90d_30pct_rate"] = _rate(picks, "winner_90d_30pct")
    row["loser_90d_minus30pct_rate"] = _rate(picks, "loser_90d_minus30pct")
    return row


def _bucket_count(row: Mapping[str, Any], prefix: str) -> str:
    count = sum(1 for k, v in row.items() if prefix in k.lower() and str(v).strip() not in {"", "0", "False", "false"})
    return "2+" if count >= 2 else str(count)


def _bucket_summaries(picks: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    theme_groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    tier_groups: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in picks:
        theme = row.get("primary_theme") or row.get("theme") or "UNKNOWN"
        theme_groups[(str(row["variant"]), str(theme) or "UNKNOWN")].append(row)
        for dim, needle in (("hp", "hp"), ("rm", "rm"), ("tier", "tier")):
            tier_groups[(str(row["variant"]), dim, _bucket_count(row, needle))].append(row)
    theme_rows = [{"variant": v, "primary_theme": t, "pick_count": len(rs), "avg_return_90d_pct": _avg(rs, "return_90d_pct"), "winner_90d_30pct_rate": _rate(rs, "winner_90d_30pct"), "loser_90d_minus30pct_rate": _rate(rs, "loser_90d_minus30pct")} for (v, t), rs in sorted(theme_groups.items())]
    contrib_rows = [{"variant": v, "dimension": d, "bucket": b, "pick_count": len(rs), "avg_return_90d_pct": _avg(rs, "return_90d_pct"), "winner_90d_30pct_rate": _rate(rs, "winner_90d_30pct"), "loser_90d_minus30pct_rate": _rate(rs, "loser_90d_minus30pct")} for (v, d, b), rs in sorted(tier_groups.items())]
    return theme_rows, contrib_rows


def run_high_conviction_top10_backtest(pit_panel_csv: str | Path, output_dir: str | Path = DEFAULT_OUTPUT_DIR, run_id: str | None = None) -> dict[str, Any]:
    panel_path = Path(pit_panel_csv)
    rows, headers = _read_csv(panel_path)
    feature_cols = _feature_columns(headers)
    decorative_cols = _decorative_columns(headers)
    groups = _eligible_groups(rows)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    backtest_run_id = run_id or f"high-conviction-top10-{uuid4()}"

    selected_rows: list[dict[str, Any]] = []
    strategy_quarter_rows: list[dict[str, Any]] = []
    misses_rows: list[dict[str, Any]] = []

    for variant in VARIANTS:
        for quarter in sorted(groups):
            eligible = sorted(groups[quarter], key=lambda r: str(r.get("ticker", "")).upper())
            selected_feature_rows = _select_variant(variant, eligible, feature_cols)
            by_ticker = {str(r.get("ticker", "")).upper(): r for r in eligible}
            selected_tickers = [str(r.get("ticker", "")).upper() for r in selected_feature_rows]
            frozen: list[dict[str, Any]] = []
            for rank, row in enumerate(selected_feature_rows, 1):
                ticker = str(row.get("ticker", "")).upper()
                frozen.append(_freeze_selection_row(row, by_ticker[ticker], variant, quarter, rank))
            selected_rows.extend(frozen)
            strategy_quarter_rows.append(_summarize(variant, quarter, frozen, len(eligible)))
            non_selected = [r for r in sorted(eligible, key=lambda r: (-(_to_float(r.get("entry_score_0_100")) or float("-inf")), str(r.get("ticker", "")).upper())) if str(r.get("ticker", "")).upper() not in set(selected_tickers)]
            for miss_rank, r in enumerate(non_selected[:20], 1):
                misses_rows.append({"variant": variant, "quarter": quarter, "snapshot_date": r.get("tradable_date", ""), "miss_rank": miss_rank, "ticker": str(r.get("ticker", "")).upper(), "why_missed": "NOT_IN_TOP10", **{c: r.get(c, "") for c in ["entry_score_0_100", *decorative_cols, *OUTCOME_COLUMNS] if c in r}})

    strategy_summary_rows = [_aggregate_strategy(v, [r for r in selected_rows if r["variant"] == v], strategy_quarter_rows) for v in VARIANTS]
    variant_summary_rows = [
        {
            "variant": v,
            "config": json.dumps({k: val for k, val in VARIANTS[v].items() if k != "kind"}, sort_keys=True),
            "quarter_count": len(groups),
            "total_picks": sum(1 for r in selected_rows if r["variant"] == v),
            "avg_picks_per_quarter": f"{sum(1 for r in selected_rows if r['variant'] == v) / len(groups):.6f}" if groups else "",
            "shortfall_quarters": sum(1 for r in strategy_quarter_rows if r["variant"] == v and r["shortfall"]),
        }
        for v in VARIANTS
    ]
    theme_rows, contrib_rows = _bucket_summaries(selected_rows)

    _write_csv(out / "selected_names_by_quarter.csv", selected_rows, ["variant", "quarter", "snapshot_date", "tradable_date", "selection_rank", "ticker", "entry_score_0_100", "score", "composite_score", *decorative_cols, *OUTCOME_COLUMNS])
    _write_csv(out / "strategy_by_quarter.csv", strategy_quarter_rows, ["variant", "quarter", "pick_count", "eligible_count", "shortfall"])
    _write_csv(out / "strategy_summary.csv", strategy_summary_rows, ["variant", "quarter_count", "total_picks", "avg_picks_per_quarter"])
    _write_csv(out / "variant_summary.csv", variant_summary_rows, ["variant", "config", "quarter_count", "total_picks", "avg_picks_per_quarter", "shortfall_quarters"])
    _write_csv(out / "misses_analysis.csv", misses_rows, ["variant", "quarter", "snapshot_date", "miss_rank", "ticker", "why_missed"])
    _write_csv(out / "theme_bucket_summary.csv", theme_rows, ["variant", "primary_theme", "pick_count", "avg_return_90d_pct", "winner_90d_30pct_rate", "loser_90d_minus30pct_rate"])
    _write_csv(out / "rm_hp_tier_contribution.csv", contrib_rows, ["variant", "dimension", "bucket", "pick_count", "avg_return_90d_pct", "winner_90d_30pct_rate", "loser_90d_minus30pct_rate"])
    (out / "README_ANALYSIS.md").write_text(_readme(), encoding="utf-8")

    output_paths = [out / name for name in OUTPUT_FILES]
    manifest = {
        "run_id": backtest_run_id,
        "runner_version": RUNNER_VERSION,
        "input_panel": {"path": str(panel_path), "sha256": _file_sha256(panel_path), "row_count": len(rows)},
        "label_feature_separation_guardrail": "Selection receives feature-only rows with return_/forward_/winner/loser outcome columns removed; labels are copied only after selection.",
        "feature_columns_used_for_selection": feature_cols,
        "forbidden_outcome_columns_removed_from_selection": sorted(set(headers) - set(feature_cols)),
        "variant_configs": VARIANTS,
        "quarter_count": len(groups),
        "eligible_row_count": sum(len(v) for v in groups.values()),
        "pick_count": len(selected_rows),
        "variant_pick_counts": {v: sum(1 for r in selected_rows if r["variant"] == v) for v in VARIANTS},
        "output_hashes": {p.name: _file_sha256(p) for p in output_paths},
    }
    manifest_path = out / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest["output_hashes"]["run_manifest.json"] = _file_sha256(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _readme() -> str:
    return """# High-Conviction Top-10 Fundamental Backtest

Artifacts:
- `selected_names_by_quarter.csv`: selected variant-quarter-rank rows with diagnostic labels.
- `strategy_by_quarter.csv`: per-variant, per-quarter return and winner/loser aggregates.
- `strategy_summary.csv`: aggregate strategy performance by variant.
- `variant_summary.csv`: locked config and shortfall counts.
- `misses_analysis.csv`: top non-selected eligible names with diagnostic labels and miss reason.
- `theme_bucket_summary.csv`: selected pick performance by theme bucket.
- `rm_hp_tier_contribution.csv`: selected pick performance by HP/RM/tier signal-count buckets.
- `run_manifest.json`: input/output hashes, run metadata, locked configs, guardrail evidence.

Labels/outcomes are diagnostic only. Selection never receives forward returns, winner/loser labels, or other forbidden outcome columns; labels are attached after tickers/ranks are frozen.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run high-conviction Top-10 backtest variants over PIT panel")
    parser.add_argument("pit_panel_csv", help="Path to PIT panel CSV")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)
    try:
        manifest = run_high_conviction_top10_backtest(args.pit_panel_csv, args.output_dir, args.run_id)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"pick_count": manifest["pick_count"], "quarter_count": manifest["quarter_count"], "output_dir": args.output_dir}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
