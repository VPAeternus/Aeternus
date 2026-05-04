#!/usr/bin/env python3
"""Audit adaptive macro backtest outputs for avoidable blank data."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

REQUIRED_DAILY = [
    "date",
    "spy_close",
    "snapshot_date",
    "regime",
    "technical_panic_state",
    "adaptive_combined_panic_state",
    "stress_layer3_state",
    "adaptive_inputs_available",
    "adaptive_score_reason",
    "action_guidance",
]
ADAPTIVE_INPUTS = [
    "adaptive_gold_vs_spy",
    "adaptive_btc_vs_spy",
    "adaptive_bond_support_20d",
    "adaptive_dollar_20d_return",
    "adaptive_commodity_20d_return",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="eval_results/macro_backtest/adaptive_proxy_1999")
    args = parser.parse_args()
    out = Path(args.output_dir)
    daily = pd.read_csv(out / "daily_spy_adaptive_regime_buckets_1999_2026.csv", parse_dates=["date", "snapshot_date"])
    snap = pd.read_csv(out / "adaptive_macro_snapshots_labeled.csv", parse_dates=["snapshot_date"])
    prices = pd.read_csv(out / "adaptive_proxy_prices.csv", parse_dates=["Date"])

    lines: list[str] = []
    fail = False

    def section(title: str) -> None:
        lines.append(f"\n## {title}")

    section("Required daily fields")
    missing_cols = [c for c in REQUIRED_DAILY if c not in daily.columns]
    if missing_cols:
        fail = True
        lines.append(f"FAIL missing columns: {missing_cols}")
    else:
        nulls = daily[REQUIRED_DAILY].isna().sum().to_dict()
        lines.append(str(nulls))
        bad = {k: v for k, v in nulls.items() if v}
        if bad:
            fail = True
            lines.append(f"FAIL required daily nulls: {bad}")

    section("Date/index integrity")
    dup_daily = int(daily["date"].duplicated().sum())
    dup_snap = int(snap["snapshot_date"].duplicated().sum())
    lines.append(f"daily rows={len(daily)} range={daily.date.min().date()}->{daily.date.max().date()} duplicate_dates={dup_daily}")
    lines.append(f"snapshot rows={len(snap)} range={snap.snapshot_date.min().date()}->{snap.snapshot_date.max().date()} duplicate_dates={dup_snap}")
    if dup_daily or dup_snap:
        fail = True

    section("Adaptive input coverage")
    for col in ADAPTIVE_INPUTS:
        first = snap.loc[snap[col].notna(), "snapshot_date"].min() if col in snap else pd.NaT
        last = snap.loc[snap[col].notna(), "snapshot_date"].max() if col in snap else pd.NaT
        n = int(snap[col].notna().sum()) if col in snap else 0
        lines.append(f"{col}: non_null={n} first={first.date() if pd.notna(first) else None} last={last.date() if pd.notna(last) else None}")

    section("Stress scoring")
    stress = snap["regime"].isin(["VOL_SHOCK", "HIGH_VOL", "RISK_OFF", "BEAR"])
    scored = int((stress & snap["adaptive_panic_rebound_quality_score"].notna()).sum())
    insufficient = int((stress & snap["adaptive_panic_rebound_quality_score"].isna()).sum())
    lines.append(f"stress_rows={int(stress.sum())} scored={scored} insufficient={insufficient}")
    lines.append(str(snap["adaptive_score_reason"].value_counts(dropna=False).to_dict()))

    # Avoidable blank check: after an adaptive input has first become available, blank runs in daily
    # stress rows are suspicious unless BTC pre-inception or explicit insufficient inputs.
    section("Post-availability blank checks")
    for col in ADAPTIVE_INPUTS:
        if col not in daily:
            continue
        first = daily.loc[daily[col].notna(), "date"].min()
        post = daily[daily["date"] >= first] if pd.notna(first) else daily.iloc[0:0]
        blanks = int(post[col].isna().sum())
        lines.append(f"{col}: first={first.date() if pd.notna(first) else None} post_first_blanks={blanks}")
        # BTC can still have blanks only before first. Others should be ffilled once live.
        if col != "adaptive_btc_vs_spy" and blanks:
            fail = True
            sample = post.loc[post[col].isna(), ["date", "snapshot_date", "regime", col]].head(10)
            lines.append("FAIL sample:\n" + sample.to_string(index=False))

    section("Source labels")
    for col in ["adaptive_commodity_source", "adaptive_bond_source"]:
        if col in snap:
            lines.append(f"{col}: {snap[col].value_counts(dropna=False).to_dict()}")

    section("Price source availability")
    for col in ["SPY", "^VIX", "GC=F", "GLD", "CL=F", "HG=F", "DBC", "DX-Y.NYB", "UUP", "^TNX", "TLT", "BTC-USD"]:
        if col in prices:
            s = prices[["Date", col]].dropna()
            lines.append(f"{col}: rows={len(s)} first={s.Date.min().date() if len(s) else None} last={s.Date.max().date() if len(s) else None}")

    report = "\n".join(lines).strip() + "\n"
    (out / "adaptive_blank_data_audit.md").write_text(report)
    print(report)
    if fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
