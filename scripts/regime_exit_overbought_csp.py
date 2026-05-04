"""
CC Overbought Signal — Forward Return Analysis (CSP Strategy Study)
====================================================================
For each QQQ constituent:
  1. Run the CCOverboughtEngine state machine, recording every date where
     exit_reason == "overbought" (ABOVE_BOTH + accel > P90).
  2. For each such date, measure forward returns at 1d, 5d, 10d, 20d, 30d.
  3. Also compute max drawdown and max gain in the 30-day forward window.

Key question: "If you sold a 30-day ATM CSP every time CCOverbought fired
an overbought signal across QQQ names, what is the aggregate win rate
and avg forward return?"

A CSP seller profits when the stock does NOT fall (i.e., forward return > 0
OR stock stays above the put strike). Win rate = pct of signals where
30d forward return > 0 (stock stays above ATM strike approximately).
"""

import sys
import os
sys.path.insert(0, "/Users/aeternusholdings/Documents/AeternusAgents-opus46")

import numpy as np
import pandas as pd
from tradingagents.phase_engine import data_engine
from tradingagents.phase_engine.cc_overbought import (
    _compute_accel,
    _expanding_quantiles,
    _classify_regime,
)

# ── Universe ───────────────────────────────────────────────────────────────────
# QQQ top ~100 constituents (known list, stable)
TICKERS = list(dict.fromkeys([
    "AAPL", "MSFT", "AMZN", "NVDA", "META", "GOOGL", "GOOG", "AVGO", "TSLA", "COST",
    "NFLX", "TMUS", "AMD", "ADBE", "PEP", "CSCO", "LIN", "QCOM", "ISRG", "INTU",
    "TXN", "AMGN", "CMCSA", "AMAT", "BKNG", "HON", "PANW", "ADP", "MU", "LRCX",
    "ADI", "SBUX", "KLAC", "MDLZ", "GILD", "INTC", "REGN", "MELI", "SNPS", "CDNS",
    "PYPL", "VRTX", "CRWD", "CTAS", "MAR", "MRVL", "CEG", "ORLY", "ABNB", "FTNT",
    "DASH", "WDAY", "CSX", "ADSK", "CHTR", "MNST", "ROP", "TEAM", "DXCM", "NXPI",
    "TTD", "PCAR", "PAYX", "GEHC", "FANG", "CPRT", "AEP", "ODFL", "FAST", "KDP",
    "ROST", "EA", "LULU", "VRSK", "EXC", "CTSH", "BKR", "KHC", "MCHP", "XEL",
    "IDXX", "CCEP", "DDOG", "CSGP", "ON", "ANSS", "CDW", "ZS", "TTWO", "GFS",
    "BIIB", "ILMN", "WBD", "SMCI", "ARM", "MDB", "MRNA", "DLTR", "SIRI", "CRM",
    # A few more high-vol QQQ names worth including
    "SNOW", "COIN", "SHOP", "NET", "PLTR", "UBER", "RBLX",
]))

WARMUP    = 252   # min periods for expanding quantiles (matches CCOverboughtEngine default)
HOLDOUT   = 3     # days out before re-entry (matches CCOverboughtEngine default)
HORIZONS  = [1, 5, 10, 20, 30]


# ── Core: extract all overbought exit dates from a ticker's price history ──────

def find_overbought_exits(df: pd.DataFrame) -> list[dict]:
    """
    Replays the CCOverboughtEngine state machine on df and records every bar
    where the state transitions LONG → CASH with exit_reason == 'overbought'.

    Returns list of dicts: {date, bar_index, close}
    """
    df = df.reset_index(drop=True)

    accel = _compute_accel(df)
    pcts  = _expanding_quantiles(accel, min_periods=WARMUP)

    close_arr  = df["close"].values
    sma3_arr   = df["close"].rolling(3).mean().values
    sma50_arr  = df["close"].rolling(50).mean().values
    sma200_arr = df["close"].rolling(200).mean().values
    accel_arr  = accel.values
    p03_arr    = pcts["p03"].values
    p90_arr    = pcts["p90"].values
    p97_arr    = pcts["p97"].values
    dates_arr  = df["date"].values
    n          = len(df)

    state     = "long"
    days_out  = 0
    exits     = []

    for i in range(WARMUP, n):
        close  = close_arr[i]
        sma3   = sma3_arr[i]
        sma50  = sma50_arr[i]
        sma200 = sma200_arr[i]
        a      = accel_arr[i]
        p03    = p03_arr[i]
        p90    = p90_arr[i]
        p97    = p97_arr[i]

        # Skip bars where thresholds are not yet valid
        if np.isnan(p03) or np.isnan(p90) or np.isnan(p97):
            continue
        if np.isnan(a) or np.isnan(sma3) or np.isnan(sma50) or np.isnan(sma200):
            continue

        regime = _classify_regime(close, sma50, sma200)

        if state == "long":
            if regime == "ABOVE_BOTH" and a > p90:
                # OVERBOUGHT EXIT — record this
                exits.append({
                    "bar_index": i,
                    "date":      pd.Timestamp(dates_arr[i]),
                    "close":     float(close),
                    "accel":     float(a),
                    "accel_p90": float(p90),
                })
                state    = "cash"
                days_out = 0
            elif regime == "ABOVE_200_BELOW_50" and a < p03:
                state    = "cash"
                days_out = 0
            elif regime in ("BELOW_200_ABOVE_50", "BELOW_BOTH"):
                if a > p97:
                    state    = "cash"
                    days_out = 0
        else:  # cash
            days_out += 1
            if days_out >= HOLDOUT and close > sma3:
                state    = "long"
                days_out = 0

    return exits


def compute_forward_returns(df: pd.DataFrame, exits: list[dict]) -> list[dict]:
    """
    For each exit event, compute forward returns at each horizon in HORIZONS,
    plus max drawdown and max gain in the 30-day window.
    """
    close_arr = df["close"].values
    n         = len(df)
    records   = []

    for ev in exits:
        i = ev["bar_index"]
        entry_close = ev["close"]

        fwd = {}
        for h in HORIZONS:
            j = i + h
            if j < n:
                fwd[f"fwd_{h}d"] = (close_arr[j] - entry_close) / entry_close * 100.0
            else:
                fwd[f"fwd_{h}d"] = np.nan

        # Max drawdown & max gain in 30-day window
        window_end = min(i + 31, n)
        window     = close_arr[i + 1:window_end]
        if len(window) > 0:
            pct_changes  = (window - entry_close) / entry_close * 100.0
            max_gain     = float(np.nanmax(pct_changes))
            max_drawdown = float(np.nanmin(pct_changes))
        else:
            max_gain     = np.nan
            max_drawdown = np.nan

        records.append({
            "date":          ev["date"],
            "close":         entry_close,
            "accel":         ev["accel"],
            "accel_p90":     ev["accel_p90"],
            "max_gain_30d":  max_gain,
            "max_dd_30d":    max_drawdown,
            **fwd,
        })

    return records


# ── Main loop ──────────────────────────────────────────────────────────────────

print("=" * 72)
print("CC Overbought → Forward Return Analysis (CSP Study)")
print(f"Universe: {len(TICKERS)} QQQ constituent tickers")
print(f"Warmup: {WARMUP} bars | Holdout: {HOLDOUT} days | Horizons: {HORIZONS}")
print("=" * 72)
print("Loading data and running state machine...\n")

all_records  = []   # flat list of all signal→forward-return rows
per_ticker   = []   # per-ticker summary rows
failed       = []

for idx, ticker in enumerate(TICKERS):
    if idx % 20 == 0 and idx > 0:
        print(f"  ...processed {idx}/{len(TICKERS)}")

    try:
        df = data_engine.load(ticker)
    except Exception as e:
        failed.append(ticker)
        continue

    if df is None or len(df) < WARMUP + 100:
        failed.append(ticker)
        continue

    exits = find_overbought_exits(df)
    if not exits:
        continue

    records = compute_forward_returns(df, exits)
    rdf     = pd.DataFrame(records)
    rdf["ticker"] = ticker

    # Per-ticker summary
    valid30 = rdf["fwd_30d"].dropna()
    if len(valid30) == 0:
        continue

    win_rate_30d = (valid30 > 0).mean() * 100.0
    avg_fwd_30d  = valid30.mean()

    per_ticker.append({
        "Ticker":        ticker,
        "Signals":       len(rdf),
        "Valid30":       len(valid30),
        "AvgFwd1d":      rdf["fwd_1d"].mean(),
        "AvgFwd5d":      rdf["fwd_5d"].mean(),
        "AvgFwd10d":     rdf["fwd_10d"].mean(),
        "AvgFwd20d":     rdf["fwd_20d"].mean(),
        "AvgFwd30d":     avg_fwd_30d,
        "WinRate30d":    win_rate_30d,
        "AvgMaxGain30d": rdf["max_gain_30d"].mean(),
        "AvgMaxDD30d":   rdf["max_dd_30d"].mean(),
        "MedianFwd30d":  valid30.median(),
    })

    all_records.extend(rdf.to_dict("records"))


# ── Build DataFrames ──────────────────────────────────────────────────────────

adf = pd.DataFrame(all_records)
pdf = pd.DataFrame(per_ticker)

total_signals = len(adf)
valid30_mask  = adf["fwd_30d"].notna()
valid30_adf   = adf[valid30_mask]

n_valid      = len(valid30_adf)
agg_win_rate = (valid30_adf["fwd_30d"] > 0).mean() * 100.0
agg_avg_fwd  = valid30_adf["fwd_30d"].mean()
agg_med_fwd  = valid30_adf["fwd_30d"].median()

# ── Print results ──────────────────────────────────────────────────────────────

print(f"\n{'=' * 72}")
print("AGGREGATE RESULTS — ALL TICKERS COMBINED")
print(f"{'=' * 72}")
print(f"Tickers processed:       {len(pdf)} (out of {len(TICKERS)}, {len(failed)} failed)")
print(f"Total overbought signals: {total_signals:,}")
print(f"Signals with 30d data:   {n_valid:,}")
print()
print(f"{'Horizon':<12s} {'Avg Fwd Ret %':>14s} {'Median Fwd Ret %':>17s} {'Win Rate %':>12s}")
print("-" * 58)
for h in HORIZONS:
    col      = f"fwd_{h}d"
    valid    = adf[col].dropna()
    avg_ret  = valid.mean()
    med_ret  = valid.median()
    win_rate = (valid > 0).mean() * 100.0
    print(f"  {h:>2d}d          {avg_ret:>+13.2f}% {med_ret:>+16.2f}% {win_rate:>11.1f}%")

print()
print(f"Max gain in 30d window (avg):      {valid30_adf['max_gain_30d'].mean():>+.2f}%")
print(f"Max drawdown in 30d window (avg):  {valid30_adf['max_dd_30d'].mean():>+.2f}%")
print()
print(f"CSP KEY METRIC — 30d Win Rate: {agg_win_rate:.1f}%")
print(f"  (pct of signals where stock closes ABOVE entry price after 30d)")
print(f"  Avg 30d forward return: {agg_avg_fwd:+.2f}%")
print(f"  Median 30d fwd return:  {agg_med_fwd:+.2f}%")

# ── Split: tickers where avg 30d > 0 vs < 0 ──────────────────────────────────

pos_tickers = pdf[pdf["AvgFwd30d"] > 0]
neg_tickers = pdf[pdf["AvgFwd30d"] <= 0]

print(f"\n{'=' * 72}")
print("SPLIT BY TICKER DIRECTION")
print(f"{'=' * 72}")
print(f"Tickers where avg 30d fwd > 0 (CSP friendly):  {len(pos_tickers)}/{len(pdf)} ({len(pos_tickers)/len(pdf)*100:.0f}%)")
print(f"  Combined signals: {pos_tickers['Signals'].sum()}")
print(f"  Avg 30d return:   {pos_tickers['AvgFwd30d'].mean():+.2f}%")
print(f"  Avg win rate:     {pos_tickers['WinRate30d'].mean():.1f}%")
print()
print(f"Tickers where avg 30d fwd <= 0 (CSP hostile):  {len(neg_tickers)}/{len(pdf)} ({len(neg_tickers)/len(pdf)*100:.0f}%)")
print(f"  Combined signals: {neg_tickers['Signals'].sum()}")
print(f"  Avg 30d return:   {neg_tickers['AvgFwd30d'].mean():+.2f}%")
print(f"  Avg win rate:     {neg_tickers['WinRate30d'].mean():.1f}%")

# ── Year-by-year breakdown ────────────────────────────────────────────────────

print(f"\n{'=' * 72}")
print("YEAR-BY-YEAR BREAKDOWN (30d forward return)")
print(f"{'=' * 72}")
print(f"{'Year':>6s} {'Signals':>8s} {'WinRate':>9s} {'AvgFwd30d':>11s} {'MedFwd30d':>11s} {'MaxGain':>9s} {'MaxDD':>9s}")
print("-" * 68)

adf["year"] = pd.to_datetime(adf["date"]).dt.year
for yr, g in adf.groupby("year"):
    valid = g["fwd_30d"].dropna()
    if len(valid) == 0:
        continue
    wr = (valid > 0).mean() * 100.0
    print(
        f"{yr:>6d} {len(valid):>8d} {wr:>8.1f}% {valid.mean():>+10.2f}% "
        f"{valid.median():>+10.2f}% "
        f"{g['max_gain_30d'].dropna().mean():>+8.2f}% "
        f"{g['max_dd_30d'].dropna().mean():>+8.2f}%"
    )

# ── Top 20: best CSP candidates ───────────────────────────────────────────────

print(f"\n{'=' * 72}")
print("TOP 20 TICKERS BY AVG 30D FORWARD RETURN (Best CSP Candidates)")
print(f"{'=' * 72}")
print(f"{'Ticker':<8s} {'Signals':>7s} {'WinRate30d':>11s} {'AvgFwd30d':>11s} {'MedFwd30d':>11s} {'MaxGain30d':>12s} {'MaxDD30d':>10s}")
print("-" * 75)

top20 = pdf[pdf["Valid30"] >= 3].sort_values("AvgFwd30d", ascending=False).head(20)
for _, r in top20.iterrows():
    print(
        f"{r['Ticker']:<8s} {r['Valid30']:>7.0f} {r['WinRate30d']:>10.1f}% "
        f"{r['AvgFwd30d']:>+10.2f}% {r['MedianFwd30d']:>+10.2f}% "
        f"{r['AvgMaxGain30d']:>+11.2f}% {r['AvgMaxDD30d']:>+9.2f}%"
    )

# ── Bottom 20: worst CSP candidates ──────────────────────────────────────────

print(f"\n{'=' * 72}")
print("BOTTOM 20 TICKERS BY AVG 30D FORWARD RETURN (Worst CSP Candidates)")
print(f"{'=' * 72}")
print(f"{'Ticker':<8s} {'Signals':>7s} {'WinRate30d':>11s} {'AvgFwd30d':>11s} {'MedFwd30d':>11s} {'MaxGain30d':>12s} {'MaxDD30d':>10s}")
print("-" * 75)

bot20 = pdf[pdf["Valid30"] >= 3].sort_values("AvgFwd30d", ascending=True).head(20)
for _, r in bot20.iterrows():
    print(
        f"{r['Ticker']:<8s} {r['Valid30']:>7.0f} {r['WinRate30d']:>10.1f}% "
        f"{r['AvgFwd30d']:>+10.2f}% {r['MedianFwd30d']:>+10.2f}% "
        f"{r['AvgMaxGain30d']:>+11.2f}% {r['AvgMaxDD30d']:>+9.2f}%"
    )

# ── Signal frequency distribution ────────────────────────────────────────────

print(f"\n{'=' * 72}")
print("SIGNAL FREQUENCY (Overbought exits per ticker, over full history)")
print(f"{'=' * 72}")
for pct_label, pct_val in [("P10", 10), ("P25", 25), ("P50", 50), ("P75", 75), ("P90", 90)]:
    print(f"  {pct_label}: {np.percentile(pdf['Signals'], pct_val):.0f} signals/ticker")
print(f"  Mean: {pdf['Signals'].mean():.1f} | Max: {pdf['Signals'].max():.0f} | Min: {pdf['Signals'].min():.0f}")

# ── Distribution of 30d forward returns ─────────────────────────────────────

print(f"\n{'=' * 72}")
print("DISTRIBUTION OF 30D FORWARD RETURNS (all signals)")
print(f"{'=' * 72}")
valid30 = valid30_adf["fwd_30d"]
for pct_label, pct_val in [("P5", 5), ("P10", 10), ("P25", 25), ("P50", 50), ("P75", 75), ("P90", 90), ("P95", 95)]:
    print(f"  {pct_label}: {np.percentile(valid30, pct_val):+.2f}%")
print(f"  Stdev: {valid30.std():.2f}%")

# ── Save CSVs ─────────────────────────────────────────────────────────────────

os.makedirs(
    "/Users/aeternusholdings/Documents/AeternusAgents-opus46/eval_results",
    exist_ok=True
)
out_dir = "/Users/aeternusholdings/Documents/AeternusAgents-opus46/eval_results"

pdf_sorted = pdf.sort_values("AvgFwd30d", ascending=False)
pdf_sorted.to_csv(f"{out_dir}/cc_overbought_ob_csp_per_ticker.csv", index=False)

adf_out = adf.sort_values(["ticker", "date"])
adf_out.to_csv(f"{out_dir}/cc_overbought_ob_csp_all_signals.csv", index=False)

print(f"\nSaved:")
print(f"  {out_dir}/cc_overbought_ob_csp_per_ticker.csv  ({len(pdf)} rows)")
print(f"  {out_dir}/cc_overbought_ob_csp_all_signals.csv  ({len(adf)} rows)")

if failed:
    print(f"\nFailed to load ({len(failed)}): {', '.join(failed)}")
