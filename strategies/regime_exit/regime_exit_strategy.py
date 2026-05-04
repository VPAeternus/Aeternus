"""
Covered Call Overbought Momentum Strategy
==========================================
Standalone backtest — zero dependencies on AeternusAgents codebase.
Requires only: yfinance, pandas, numpy (standard install).

Strategy logic:
  - Default state: LONG (invested by default)
  - Exits only at acceleration extremes within specific price regimes
  - Uses SMA3 acceleration (second derivative) with expanding percentile thresholds
  - Re-enters after holdout days when close > SMA3

Exit rules:
  Regime 1: close > SMA50 AND close > SMA200 (above both)
    → Exit when accel > P90  (overbought reversal)

  Regime 2: close > SMA200 AND close < SMA50 (above 200, below 50)
    → Exit when accel < P03  (failed support crash)

  Regime 3: close < SMA200 (below 200)
    → Exit when accel > P97  (dead cat bounce)
    → BUT if accel < P03 (capitulation) → STAY IN (mean reversion recovery)

  Re-entry: close > SMA3 after holdout days

Usage:
  python3 regime_exit_strategy.py AAPL
  python3 regime_exit_strategy.py AAPL --start 1999-01-01 --holdout 3 --csv
  python3 regime_exit_strategy.py --tickers AAPL MSFT NVDA
Portfolio math:
  - Assumes starting capital equal to 100 shares on the first post-warmup bar
  - Strategy is fully invested when position == 1, otherwise sits in cash
  - Buy-and-hold remains fully invested throughout
  - Reports compounded return %, CAGR, Sharpe, and max drawdown
"""

import argparse
from math import sqrt

import numpy as np
import pandas as pd
import yfinance as yf


# ── Indicator computation ─────────────────────────────────────────────────────

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add SMA3/10/20/50/200 and volume SMA20 to df (in-place)."""
    close = df["Close"]
    df["sma3"]   = close.rolling(3).mean()
    df["sma10"]  = close.rolling(10).mean()
    df["sma20"]  = close.rolling(20).mean()
    df["sma50"]  = close.rolling(50).mean()
    df["sma200"] = close.rolling(200).mean()
    if "Volume" in df.columns:
        df["vol_sma20"] = df["Volume"].rolling(20).mean()
    return df


def compute_accel(close: pd.Series, sma3: pd.Series, lb: int = 5) -> pd.Series:
    """
    Second derivative of SMA3 slope (normalized by price).

    slope = (sma3 - sma3.shift(lb)) / (close * lb)
    accel = slope - slope.shift(lb)
    """
    slope = (sma3 - sma3.shift(lb)) / (close * lb)
    accel = slope - slope.shift(lb)
    return accel


# ── Core backtest ─────────────────────────────────────────────────────────────

def run_cc_overbought(df: pd.DataFrame, holdout: int = 3) -> pd.DataFrame:
    """
    State machine backtest of the CC overbought strategy.

    Expanding percentile thresholds (min_periods=252, no lookahead).
    Returns df with columns added: position (0/1), state, regime, exit_type.
    """
    close  = df["Close"].values
    sma3   = df["sma3"].values
    sma50  = df["sma50"].values
    sma200 = df["sma200"].values
    accel_s = df["accel"].values

    n = len(df)

    # Pre-compute expanding percentiles — no lookahead
    accel_series = df["accel"]
    p90 = accel_series.expanding(min_periods=252).quantile(0.90).values
    p97 = accel_series.expanding(min_periods=252).quantile(0.97).values
    p03 = accel_series.expanding(min_periods=252).quantile(0.03).values

    position  = np.zeros(n, dtype=int)
    state_arr = np.empty(n, dtype=object)
    regime_arr= np.zeros(n, dtype=int)
    exit_arr  = np.empty(n, dtype=object)

    state_arr[:] = "warmup"
    exit_arr[:]  = ""

    # Warmup: need 252 bars for expanding percentile baseline + SMA200 (200 bars)
    # Start the simulation from bar 252
    WARMUP = 252

    # State machine variables
    in_pos    = True   # default: LONG
    holdout_remaining = 0

    for i in range(n):
        c   = close[i]
        s3  = sma3[i]
        s50 = sma50[i]
        s200= sma200[i]
        acc = accel_s[i]

        # Skip warmup bars — mark as invested but don't apply logic
        if i < WARMUP:
            position[i]  = 1
            state_arr[i] = "warmup"
            regime_arr[i]= 0
            continue

        # Determine regime
        if np.isnan(s200) or np.isnan(s50) or np.isnan(s3):
            # Still building SMAs — stay in
            position[i]  = 1
            state_arr[i] = "warmup"
            continue

        if c > s50 and c > s200:
            regime = 1
        elif c > s200 and c <= s50:
            regime = 2
        else:
            regime = 3

        regime_arr[i] = regime

        # Handle holdout countdown
        if not in_pos:
            holdout_remaining -= 1
            # Re-entry check
            if holdout_remaining <= 0 and not np.isnan(s3) and c > s3:
                in_pos = True
                holdout_remaining = 0
                state_arr[i] = "reentry"
                position[i]  = 1
            else:
                state_arr[i] = "holdout"
                position[i]  = 0
            continue

        # We are in position — check exit conditions
        if np.isnan(acc) or np.isnan(p90[i]) or np.isnan(p97[i]) or np.isnan(p03[i]):
            position[i]  = 1
            state_arr[i] = "long"
            continue

        exit_triggered = False
        etype = ""

        if regime == 1:
            # Above both SMAs: exit on overbought acceleration
            if acc > p90[i]:
                exit_triggered = True
                etype = "overbought"

        elif regime == 2:
            # Above 200, below 50: exit on failed support crash
            if acc < p03[i]:
                exit_triggered = True
                etype = "failed_support"

        else:  # regime == 3
            # Below 200: exit on dead cat bounce
            if acc > p97[i]:
                exit_triggered = True
                etype = "dead_cat"
            elif acc < p03[i]:
                # Capitulation — STAY IN (mean reversion recovery)
                exit_triggered = False
                etype = ""

        if exit_triggered:
            in_pos = False
            holdout_remaining = holdout
            position[i]  = 0
            state_arr[i] = "exit"
            exit_arr[i]  = etype
        else:
            position[i]  = 1
            state_arr[i] = "long"

    df = df.copy()
    df["position"]  = position
    df["state"]     = state_arr
    df["regime"]    = regime_arr
    df["exit_type"] = exit_arr
    return df


# ── Performance metrics ───────────────────────────────────────────────────────

def compute_metrics(df: pd.DataFrame, result_df: pd.DataFrame, initial_shares: int = 100) -> dict:
    """
    Compute strategy vs buy-and-hold performance metrics.

    Uses points-based P&L (1 share, no compounding) from the WARMUP bar onward.
    """
    # Slice to post-warmup bars only
    mask = result_df["state"] != "warmup"
    rd   = result_df[mask].copy()

    if len(rd) < 2:
        return {}

    close = rd["Close"].values
    pos   = rd["position"].values

    # Daily price change in points
    daily_pts = np.diff(close)            # len = N-1

    # Strategy: position determined by prior bar's position
    strat_daily = pos[:-1] * daily_pts    # hold pos[i] entering bar i+1
    bh_daily    = daily_pts               # always long

    strat_pts   = strat_daily.sum()
    bh_pts      = bh_daily.sum()
    delta       = strat_pts - bh_pts
    delta_pct   = (delta / abs(bh_pts) * 100) if bh_pts != 0 else 0.0

    # Daily percentage returns and compounded equity curves.
    daily_pct = np.diff(close) / close[:-1]
    strat_pct = pos[:-1] * daily_pct
    bh_pct = daily_pct

    initial_capital = float(close[0] * initial_shares)
    strat_equity = initial_capital * np.concatenate(([1.0], np.cumprod(1.0 + strat_pct)))
    bh_equity = initial_capital * np.concatenate(([1.0], np.cumprod(1.0 + bh_pct)))

    strategy_return_pct = (strat_equity[-1] / initial_capital - 1.0) * 100.0
    buy_hold_return_pct = (bh_equity[-1] / initial_capital - 1.0) * 100.0

    n_days = max(1, len(daily_pct))
    years = n_days / 252.0
    strategy_cagr_pct = ((strat_equity[-1] / initial_capital) ** (1.0 / years) - 1.0) * 100.0 if years > 0 else 0.0
    buy_hold_cagr_pct = ((bh_equity[-1] / initial_capital) ** (1.0 / years) - 1.0) * 100.0 if years > 0 else 0.0

    # Sharpe: (mean / std) * sqrt(252)
    def _sharpe(daily):
        std = daily.std()
        return (daily.mean() / std) * sqrt(252) if std > 0 else 0.0

    sharpe_strat = _sharpe(strat_pct)
    sharpe_bh    = _sharpe(bh_pct)

    # Max drawdown from compounded equity curves
    def _maxdd_pct(equity):
        peak = np.maximum.accumulate(equity)
        dd = equity / peak - 1.0
        return float(dd.min() * 100.0)

    max_dd_strat = _maxdd_pct(strat_equity)
    max_dd_bh    = _maxdd_pct(bh_equity)

    # Invested %
    invested_pct = float(pos.mean() * 100)

    # Exit counts (only post-warmup)
    exits = rd["exit_type"]
    n_overbought    = int((exits == "overbought").sum())
    n_failed_support= int((exits == "failed_support").sum())
    n_dead_cat      = int((exits == "dead_cat").sum())
    total_exits     = n_overbought + n_failed_support + n_dead_cat

    # Start / end price
    start_price = float(close[0])
    end_price   = float(close[-1])
    n_bars      = len(rd)

    return {
        "strat_pts":          round(strat_pts, 2),
        "bh_pts":             round(bh_pts, 2),
        "delta":              round(delta, 2),
        "delta_pct":          round(delta_pct, 2),
        "strategy_return_pct": round(strategy_return_pct, 2),
        "buy_hold_return_pct": round(buy_hold_return_pct, 2),
        "strategy_cagr_pct":   round(strategy_cagr_pct, 2),
        "buy_hold_cagr_pct":   round(buy_hold_cagr_pct, 2),
        "sharpe_strat":       round(sharpe_strat, 3),
        "sharpe_bh":          round(sharpe_bh, 3),
        "max_dd_strat":       round(max_dd_strat, 2),
        "max_dd_bh":          round(max_dd_bh, 2),
        "invested_pct":       round(invested_pct, 1),
        "exits_overbought":   n_overbought,
        "exits_failed_support": n_failed_support,
        "exits_dead_cat":     n_dead_cat,
        "total_exits":        total_exits,
        "n_bars":             n_bars,
        "start_price":        round(start_price, 2),
        "end_price":          round(end_price, 2),
        "initial_shares":     int(initial_shares),
        "initial_capital":    round(initial_capital, 2),
        "strategy_end_capital": round(float(strat_equity[-1]), 2),
        "buy_hold_end_capital": round(float(bh_equity[-1]), 2),
    }


# ── Output formatting ─────────────────────────────────────────────────────────

def print_results(ticker: str, metrics: dict) -> None:
    """Print formatted comparison table for a single ticker."""
    m = metrics
    sep = "=" * 55

    beat_bh    = m["strategy_return_pct"] > m["buy_hold_return_pct"]
    sharpe_win = m["sharpe_strat"] > m["sharpe_bh"]
    dd_win     = m["max_dd_strat"] > m["max_dd_bh"]   # less negative = better

    delta_return = m["strategy_return_pct"] - m["buy_hold_return_pct"]
    delta_return_sign = "+" if delta_return >= 0 else ""

    print()
    print(sep)
    print(f"  CC OVERBOUGHT MOMENTUM STRATEGY — {ticker}")
    print(f"  SMA3/lb5 | Expanding P90/P97/P03 | {metrics.get('holdout', 3)}-day holdout | {m['initial_shares']} shares start")
    print(sep)
    print()
    print(f"  Strategy Return:   {m['strategy_return_pct']:>+8.2f}%")
    print(f"  Buy & Hold Return: {m['buy_hold_return_pct']:>+8.2f}%")
    print(f"  Return Delta:      {delta_return_sign}{delta_return:>7.2f}%")
    print()
    print(f"  Start Capital:     ${m['initial_capital']:>10,.2f}")
    print(f"  Strategy CAGR:     {m['strategy_cagr_pct']:>+8.2f}%")
    print(f"  Buy & Hold CAGR:   {m['buy_hold_cagr_pct']:>+8.2f}%")
    print(f"  Strategy End Value:${m['strategy_end_capital']:>10,.2f}")
    print(f"  Buy & Hold End:   ${m['buy_hold_end_capital']:>10,.2f}")
    print()
    print(f"  Sharpe (strategy):  {m['sharpe_strat']:>6.2f}{'  *' if sharpe_win else ''}")
    print(f"  Sharpe (B&H):       {m['sharpe_bh']:>6.2f}")
    print(f"  MaxDD (strategy): {m['max_dd_strat']:>7.2f}%{'  *' if dd_win else ''}")
    print(f"  MaxDD (B&H):      {m['max_dd_bh']:>7.2f}%")
    print(f"  Invested:           {m['invested_pct']:>5.1f}%")
    print()
    print(f"  Exit breakdown:")
    print(f"    Overbought:     {m['exits_overbought']:>4d}")
    print(f"    Failed Support: {m['exits_failed_support']:>4d}")
    print(f"    Dead Cat:       {m['exits_dead_cat']:>4d}")
    print(f"    Total:          {m['total_exits']:>4d}")
    print()
    print(sep)
    print()


# ── Full pipeline ─────────────────────────────────────────────────────────────

def run(ticker: str, start: str = "1999-01-01", holdout: int = 3,
        save_csv: bool = False) -> dict | None:
    """
    Full pipeline: download → indicators → backtest → print.

    Returns metrics dict, or None if download failed.
    """
    try:
        raw = yf.download(ticker, start=start, auto_adjust=True, progress=False)
    except Exception as e:
        print(f"WARNING: Failed to download {ticker}: {e}")
        return None

    if raw is None or raw.empty:
        print(f"WARNING: No data returned for {ticker}")
        return None

    # Handle MultiIndex columns from yfinance (single ticker can still return MultiIndex)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    # Ensure we have Close column
    if "Close" not in raw.columns:
        print(f"WARNING: No Close column for {ticker}")
        return None

    df = raw[["Close"]].copy()
    if "Volume" in raw.columns:
        df["Volume"] = raw["Volume"]

    df = df.dropna(subset=["Close"])
    df = df.reset_index()  # brings Date into columns

    if len(df) < 300:
        print(f"WARNING: Insufficient data for {ticker} ({len(df)} bars)")
        return None

    # Compute indicators
    df = compute_indicators(df)

    # Compute acceleration (SMA3, lb=5)
    df["accel"] = compute_accel(df["Close"], df["sma3"], lb=5)

    # Run backtest
    result_df = run_cc_overbought(df, holdout=holdout)

    # Compute metrics
    metrics = compute_metrics(df, result_df)
    if not metrics:
        print(f"WARNING: Could not compute metrics for {ticker}")
        return None

    metrics["holdout"] = holdout

    # Print results
    print_results(ticker, metrics)

    # Optionally save CSV
    if save_csv:
        out_path = f"{ticker}_cc_overbought.csv"
        result_df.to_csv(out_path, index=False)
        print(f"  Saved to {out_path}")

    return metrics


# ── Multi-ticker comparison ───────────────────────────────────────────────────

def run_multi(tickers: list[str], start: str = "1999-01-01",
              holdout: int = 3, save_csv: bool = False) -> None:
    """Run on multiple tickers and print a sorted comparison table."""
    results = []
    for ticker in tickers:
        print(f"Running {ticker}...")
        m = run(ticker, start=start, holdout=holdout, save_csv=save_csv)
        if m is not None:
            # Determine beat flags
            beat_bh    = m["strat_pts"] > m["bh_pts"]
            sharpe_win = m["sharpe_strat"] > m["sharpe_bh"]
            dd_win     = m["max_dd_strat"] > m["max_dd_bh"]
            results.append({
                "Ticker":           ticker,
                "Beat_BH":          beat_bh,
                "Sharpe_Win":       sharpe_win,
                "MaxDD_Win":        dd_win,
                "Strategy_Return_Pct": m["strategy_return_pct"],
                "BuyHold_Return_Pct":  m["buy_hold_return_pct"],
                "Strategy_CAGR_Pct":   m["strategy_cagr_pct"],
                "BuyHold_CAGR_Pct":    m["buy_hold_cagr_pct"],
                "Strategy_Pts":     m["strat_pts"],
                "BuyHold_Pts":      m["bh_pts"],
                "Delta_Pts":        m["delta"],
                "Delta_Pct":        m["delta_pct"],
                "Sharpe_Strat":     m["sharpe_strat"],
                "Sharpe_BH":        m["sharpe_bh"],
                "MaxDD_Strat":      m["max_dd_strat"],
                "MaxDD_BH":         m["max_dd_bh"],
                "Invested_Pct":     m["invested_pct"],
                "Exits_Overbought": m["exits_overbought"],
                "Exits_FailedSupport": m["exits_failed_support"],
                "Exits_DeadCat":    m["exits_dead_cat"],
                "Total_Exits":      m["total_exits"],
                "N_Bars":           m["n_bars"],
                "Start_Price":      m["start_price"],
                "End_Price":        m["end_price"],
            })

    if not results:
        print("No results to display.")
        return

    df_res = pd.DataFrame(results)
    df_res["Delta_Return_Pct"] = df_res["Strategy_Return_Pct"] - df_res["BuyHold_Return_Pct"]
    df_res = df_res.sort_values("Delta_Return_Pct", ascending=False)

    # Print comparison table
    sep = "=" * 100
    print()
    print(sep)
    print(f"  CC OVERBOUGHT STRATEGY — MULTI-TICKER COMPARISON ({len(df_res)} tickers)")
    print(f"  Sorted by Return Delta (Strategy - Buy & Hold), descending")
    print(sep)
    print()

    # Header
    hdr = (f"  {'Ticker':<8} {'Beat_BH':>7} {'StratRet':>10} {'BHRet':>10} "
           f"{'DeltaRet':>10} {'Sharpe_S':>9} {'Sharpe_BH':>9} "
           f"{'MaxDD_S':>9} {'MaxDD_BH':>9} {'Invested%':>10} {'Exits':>6}")
    print(hdr)
    print(f"  {'-' * 97}")

    for _, row in df_res.iterrows():
        beat_str = "Yes" if row["Beat_BH"] else "No"
        print(f"  {row['Ticker']:<8} {beat_str:>7} {row['Strategy_Return_Pct']:>9.2f}% "
              f"{row['BuyHold_Return_Pct']:>9.2f}% {row['Delta_Return_Pct']:>+9.2f}% "
              f"{row['Sharpe_Strat']:>9.3f} {row['Sharpe_BH']:>9.3f} "
              f"{row['MaxDD_Strat']:>8.2f}% {row['MaxDD_BH']:>8.2f}% {row['Invested_Pct']:>9.1f}% "
              f"{int(row['Total_Exits']):>6d}")

    print(f"  {'-' * 97}")

    # Summary
    n_beat = int(df_res["Beat_BH"].sum())
    n_total = len(df_res)
    avg_delta_pct = df_res["Delta_Return_Pct"].mean()
    print(f"\n  Beat B&H: {n_beat}/{n_total}  |  "
          f"Avg Return Delta: {avg_delta_pct:+.1f}%")
    print()
    print(sep)
    print()

    # Optionally save comparison CSV
    if save_csv:
        csv_path = "cc_overbought_multi.csv"
        df_res.to_csv(csv_path, index=False)
        print(f"Saved comparison CSV to {csv_path}")


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="CC Overbought Momentum Strategy — standalone backtest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("ticker", nargs="?", default="AAPL",
                        help="Ticker symbol (default: AAPL)")
    parser.add_argument("--start", default="1999-01-01",
                        help="Start date YYYY-MM-DD (default: 1999-01-01)")
    parser.add_argument("--holdout", type=int, default=3,
                        help="Holdout days after exit before re-entry (default: 3)")
    parser.add_argument("--csv", action="store_true",
                        help="Save per-bar results to CSV")
    parser.add_argument("--tickers", nargs="+",
                        help="Run on multiple tickers and print comparison table")
    args = parser.parse_args()

    if args.tickers:
        run_multi(args.tickers, start=args.start, holdout=args.holdout,
                  save_csv=args.csv)
    else:
        run(args.ticker, start=args.start, holdout=args.holdout,
            save_csv=args.csv)
