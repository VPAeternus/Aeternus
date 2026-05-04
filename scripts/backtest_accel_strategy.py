"""
Momentum Acceleration Strategy Backtest — QQQ
==============================================
Trades QQQ long/flat using the two strongest cross-stock signals
from the parameter sweep study:

  BUY:  accel_dn on SMA10/lb5  (fast deceleration onset → buy the dip)
  SELL: accel_up on SMA50/lb20 (slow acceleration onset → exit exhaustion)

Compares against buy-and-hold on the same period.

Usage: python3 scripts/backtest_accel_strategy.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from tradingagents.phase_engine import data_engine

# ── Configuration ────────────────────────────────────────────────────────────

TICKER = "QQQ"
MAX_HOLD_DAYS = 20  # force exit if no sell signal after N days

# Signal parameters (from the study's top cross-stock combos)
BUY_SMA = 10
BUY_LB = 5
SELL_SMA = 10
SELL_LB = 5


# ── Core functions ───────────────────────────────────────────────────────────

def compute_accel(close, sma, lookback):
    """Second derivative of SMA slope."""
    slope = (sma - sma.shift(lookback)) / (close * lookback)
    return slope - slope.shift(lookback)


def build_signals(df):
    """Compute buy/sell signal columns."""
    buy_accel = compute_accel(df["close"], df[f"sma{BUY_SMA}"], BUY_LB)
    sell_accel = compute_accel(df["close"], df[f"sma{SELL_SMA}"], SELL_LB)

    # Zero-crossing detection (vectorized)
    buy_prev = buy_accel.shift(1)
    sell_prev = sell_accel.shift(1)

    df["buy_signal"] = (buy_accel < 0) & (buy_prev >= 0)   # accel_dn: decel onset
    df["sell_signal"] = (sell_accel > 0) & (sell_prev <= 0)  # accel_up: accel onset
    df["buy_accel"] = buy_accel
    df["sell_accel"] = sell_accel
    return df


def simulate(df):
    """
    Simulate long/flat strategy.

    Rules:
      - Start in cash (position = 0)
      - On buy_signal and not already long → enter long at next day's open
      - On sell_signal and long → exit at next day's open
      - Force exit after MAX_HOLD_DAYS bars
      - No compounding: each trade risks the full account value at entry
    """
    close = df["close"].values
    buy_sig = df["buy_signal"].values
    sell_sig = df["sell_signal"].values

    n = len(df)
    position = np.zeros(n)       # 1 = long, 0 = flat
    entry_price = np.zeros(n)
    bars_held = np.zeros(n, dtype=int)
    trades = []

    in_pos = False
    cur_entry = 0.0
    cur_bars = 0
    cur_entry_idx = 0

    for i in range(1, n):
        if in_pos:
            cur_bars += 1
            # Check exit conditions
            exit_now = False
            reason = ""
            if sell_sig[i]:
                exit_now = True
                reason = "sell_signal"
            elif cur_bars >= MAX_HOLD_DAYS:
                exit_now = True
                reason = "max_hold"

            if exit_now:
                ret = (close[i] - cur_entry) / cur_entry
                trades.append({
                    "entry_idx": cur_entry_idx,
                    "exit_idx": i,
                    "entry_price": cur_entry,
                    "exit_price": close[i],
                    "return": ret,
                    "bars_held": cur_bars,
                    "exit_reason": reason,
                })
                in_pos = False
                position[i] = 0
            else:
                position[i] = 1
                entry_price[i] = cur_entry
                bars_held[i] = cur_bars
        else:
            # Check entry
            if buy_sig[i]:
                in_pos = True
                cur_entry = close[i]
                cur_entry_idx = i
                cur_bars = 0
                position[i] = 1
                entry_price[i] = cur_entry

    # Close any open position at the end
    if in_pos:
        ret = (close[-1] - cur_entry) / cur_entry
        trades.append({
            "entry_idx": cur_entry_idx,
            "exit_idx": n - 1,
            "entry_price": cur_entry,
            "exit_price": close[-1],
            "return": ret,
            "bars_held": cur_bars,
            "exit_reason": "end_of_data",
        })

    df["position"] = position
    return df, trades


def compute_equity(df, trades):
    """Build equity curves for strategy and buy-and-hold."""
    close = df["close"].values
    n = len(close)

    # Buy and hold: invest $1 at the start
    bh_equity = close / close[0]

    # Strategy: compound trade returns
    strat_equity = np.ones(n)
    account = 1.0

    for trade in trades:
        ei = trade["entry_idx"]
        xi = trade["exit_idx"]
        # Mark-to-market within the trade
        for j in range(ei, xi + 1):
            mtm = account * (close[j] / trade["entry_price"])
            strat_equity[j] = mtm
        account *= (1 + trade["return"])
        # Fill flat periods with current account value
        if xi + 1 < n:
            next_entry = n  # default: flat to end
            for next_t in trades:
                if next_t["entry_idx"] > xi:
                    next_entry = next_t["entry_idx"]
                    break
            for j in range(xi + 1, min(next_entry, n)):
                strat_equity[j] = account

    # Fill any remaining flat period at the end
    last_exit = trades[-1]["exit_idx"] if trades else 0
    for j in range(last_exit + 1, n):
        strat_equity[j] = account

    return strat_equity, bh_equity


def compute_metrics(equity, daily_rf=0.0):
    """Compute standard performance metrics from an equity curve."""
    returns = np.diff(equity) / equity[:-1]
    returns = returns[np.isfinite(returns)]

    total_ret = equity[-1] / equity[0] - 1
    n_years = len(equity) / 252
    cagr = (equity[-1] / equity[0]) ** (1 / n_years) - 1 if n_years > 0 else 0

    # Sharpe (annualized)
    excess = returns - daily_rf
    sharpe = np.mean(excess) / np.std(excess) * np.sqrt(252) if np.std(excess) > 0 else 0

    # Max drawdown
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    max_dd = dd.min()

    # Calmar ratio
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    return {
        "total_return": total_ret,
        "cagr": cagr,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "calmar": calmar,
        "volatility": np.std(returns) * np.sqrt(252),
        "n_years": n_years,
    }


def compute_trade_stats(trades):
    """Compute trade-level statistics."""
    if not trades:
        return {}
    rets = np.array([t["return"] for t in trades])
    wins = rets > 0
    losses = rets <= 0
    bars = np.array([t["bars_held"] for t in trades])
    reasons = [t["exit_reason"] for t in trades]

    return {
        "n_trades": len(trades),
        "win_rate": wins.mean() * 100,
        "avg_return": rets.mean() * 100,
        "avg_win": rets[wins].mean() * 100 if wins.any() else 0,
        "avg_loss": rets[losses].mean() * 100 if losses.any() else 0,
        "best_trade": rets.max() * 100,
        "worst_trade": rets.min() * 100,
        "avg_bars_held": bars.mean(),
        "profit_factor": abs(rets[wins].sum() / rets[losses].sum()) if losses.any() and rets[losses].sum() != 0 else float("inf"),
        "pct_exit_signal": sum(1 for r in reasons if r == "sell_signal") / len(reasons) * 100,
        "pct_exit_maxhold": sum(1 for r in reasons if r == "max_hold") / len(reasons) * 100,
        "time_in_market": bars.sum() / len(rets) if len(rets) > 0 else 0,
    }


def print_ascii_chart(strat_equity, bh_equity, width=70, height=20):
    """Print a simple ASCII equity chart."""
    n = len(strat_equity)
    # Downsample to width
    step = max(1, n // width)
    s_sampled = strat_equity[::step]
    b_sampled = bh_equity[::step]

    all_vals = np.concatenate([s_sampled, b_sampled])
    ymin, ymax = all_vals.min(), all_vals.max()
    yrange = ymax - ymin
    if yrange == 0:
        yrange = 1

    def to_row(v):
        return int((v - ymin) / yrange * (height - 1))

    chart = [[" "] * len(s_sampled) for _ in range(height)]

    for col in range(len(s_sampled)):
        sr = to_row(s_sampled[col])
        br = to_row(b_sampled[col])
        if sr == br:
            chart[height - 1 - sr][col] = "X"
        else:
            chart[height - 1 - sr][col] = "S"
            chart[height - 1 - br][col] = "B"

    # Y-axis labels
    print(f"\n  {'Equity Curve':^{len(s_sampled) + 10}}")
    print(f"  {'S = Strategy, B = Buy&Hold, X = overlap':^{len(s_sampled) + 10}}\n")
    for row_idx in range(height):
        val = ymax - (row_idx / (height - 1)) * yrange
        line = "".join(chart[row_idx])
        print(f"  {val:6.2f} |{line}|")
    print(f"  {'':6s} +{'─' * len(s_sampled)}+")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  Momentum Acceleration Strategy Backtest — QQQ")
    print("=" * 70)
    print(f"\n  BUY:  accel_dn on SMA{BUY_SMA}/lb{BUY_LB} (fast deceleration onset)")
    print(f"  SELL: accel_up on SMA{SELL_SMA}/lb{SELL_LB} (slow acceleration onset)")
    print(f"  Max hold: {MAX_HOLD_DAYS} days\n")

    df = data_engine.load(TICKER)
    print(f"  Data: {len(df)} bars\n")

    df = build_signals(df)
    df, trades = simulate(df)
    strat_equity, bh_equity = compute_equity(df, trades)

    # ── Metrics ──
    strat_m = compute_metrics(strat_equity)
    bh_m = compute_metrics(bh_equity)
    trade_s = compute_trade_stats(trades)

    print(f"  {'Metric':<25s} {'Strategy':>12s} {'Buy & Hold':>12s} {'Delta':>12s}")
    print(f"  {'─' * 61}")

    def row(label, sk, bk, fmt=".2%"):
        sv, bv = strat_m[sk], bh_m[bk]
        delta = sv - bv
        print(f"  {label:<25s} {sv:>12{fmt}} {bv:>12{fmt}} {delta:>+12{fmt}}")

    row("Total Return", "total_return", "total_return")
    row("CAGR", "cagr", "cagr")
    row("Sharpe Ratio", "sharpe", "sharpe", ".2f")
    row("Max Drawdown", "max_drawdown", "max_drawdown")
    row("Calmar Ratio", "calmar", "calmar", ".2f")
    row("Volatility (ann.)", "volatility", "volatility")

    print(f"\n  {'─── Trade Statistics ───'}")
    print(f"  {'Trades':<25s} {trade_s.get('n_trades', 0):>12d}")
    print(f"  {'Win Rate':<25s} {trade_s.get('win_rate', 0):>11.1f}%")
    print(f"  {'Avg Return/Trade':<25s} {trade_s.get('avg_return', 0):>11.2f}%")
    print(f"  {'Avg Win':<25s} {trade_s.get('avg_win', 0):>11.2f}%")
    print(f"  {'Avg Loss':<25s} {trade_s.get('avg_loss', 0):>11.2f}%")
    print(f"  {'Best Trade':<25s} {trade_s.get('best_trade', 0):>11.2f}%")
    print(f"  {'Worst Trade':<25s} {trade_s.get('worst_trade', 0):>11.2f}%")
    print(f"  {'Profit Factor':<25s} {trade_s.get('profit_factor', 0):>11.2f}")
    print(f"  {'Avg Bars Held':<25s} {trade_s.get('avg_bars_held', 0):>11.1f}")
    print(f"  {'Exit via Signal':<25s} {trade_s.get('pct_exit_signal', 0):>11.1f}%")
    print(f"  {'Exit via Max Hold':<25s} {trade_s.get('pct_exit_maxhold', 0):>11.1f}%")

    # Time in market
    in_market_bars = int(df["position"].sum())
    total_bars = len(df)
    print(f"  {'Time in Market':<25s} {in_market_bars / total_bars:>11.1%} "
          f"({in_market_bars}/{total_bars} bars)")

    # Exposure-adjusted return
    time_pct = in_market_bars / total_bars
    if time_pct > 0:
        exposure_adj_cagr = strat_m["cagr"] / time_pct
        print(f"  {'Exposure-adj CAGR':<25s} {exposure_adj_cagr:>11.2%}")

    print_ascii_chart(strat_equity, bh_equity)

    # ── Year-by-year breakdown ──
    df_copy = df.copy()
    df_copy["_date"] = pd.to_datetime(df_copy["date"])

    df_copy["_year"] = df_copy["_date"].dt.year
    df_copy["_strat_eq"] = strat_equity
    df_copy["_bh_eq"] = bh_equity

    # Build trade-level date mapping
    trade_records = []
    for t in trades:
        entry_year = df_copy.iloc[t["entry_idx"]]["_date"].year
        trade_records.append({**t, "year": entry_year})

    print(f"\n  {'─── Annual Breakdown ───'}")
    header = (f"  {'Year':<6s} {'Strat':>8s} {'B&H':>8s} {'Delta':>8s} "
              f"{'#Tr':>4s} {'Win%':>6s} {'AvgRet':>8s} "
              f"{'Best':>8s} {'Worst':>8s} {'PF':>6s} "
              f"{'InMkt':>6s} {'MaxDD':>8s}")
    print(header)
    print(f"  {'─' * (len(header) - 2)}")

    yearly_rows = []
    for year, grp in df_copy.groupby("_year"):
        if len(grp) < 20:
            continue
        s_ret = grp["_strat_eq"].iloc[-1] / grp["_strat_eq"].iloc[0] - 1
        b_ret = grp["_bh_eq"].iloc[-1] / grp["_bh_eq"].iloc[0] - 1

        # Trades for this year
        yr_trades = [t for t in trade_records if t["year"] == year]
        n_tr = len(yr_trades)
        if n_tr > 0:
            yr_rets = np.array([t["return"] for t in yr_trades])
            wins = yr_rets > 0
            win_pct = wins.mean() * 100
            avg_ret = yr_rets.mean() * 100
            best = yr_rets.max() * 100
            worst = yr_rets.min() * 100
            win_sum = yr_rets[wins].sum() if wins.any() else 0
            loss_sum = yr_rets[~wins].sum() if (~wins).any() else 0
            pf = abs(win_sum / loss_sum) if loss_sum != 0 else float("inf")
        else:
            win_pct = avg_ret = best = worst = 0
            pf = 0

        # Time in market this year
        yr_in = grp["position"].sum()
        yr_bars = len(grp)
        in_mkt = yr_in / yr_bars * 100

        # Max drawdown this year (strategy equity)
        yr_eq = grp["_strat_eq"].values
        yr_peak = np.maximum.accumulate(yr_eq)
        yr_dd = ((yr_eq - yr_peak) / yr_peak).min() * 100

        pf_str = f"{pf:6.2f}" if pf < 100 else "   inf"
        print(f"  {year:<6d} {s_ret:>+8.1%} {b_ret:>+8.1%} {s_ret - b_ret:>+8.1%} "
              f"{n_tr:>4d} {win_pct:>5.0f}% {avg_ret:>+7.2f}% "
              f"{best:>+7.1f}% {worst:>+7.1f}% {pf_str} "
              f"{in_mkt:>5.0f}% {yr_dd:>+7.1f}%")

        yearly_rows.append({
            "year": year, "strat": s_ret, "bh": b_ret, "delta": s_ret - b_ret,
            "n_trades": n_tr, "win_pct": win_pct,
        })

    # Summary stats
    yr_df = pd.DataFrame(yearly_rows)
    strat_wins = (yr_df["delta"] > 0).sum()
    total_yrs = len(yr_df)
    print(f"  {'─' * (len(header) - 2)}")
    print(f"  Strategy beat B&H in {strat_wins}/{total_yrs} years ({strat_wins/total_yrs*100:.0f}%)")
    print(f"  Avg annual delta: {yr_df['delta'].mean():+.1%}  |  "
          f"Median: {yr_df['delta'].median():+.1%}")

    # Show best/worst delta years
    best_yr = yr_df.loc[yr_df["delta"].idxmax()]
    worst_yr = yr_df.loc[yr_df["delta"].idxmin()]
    print(f"  Best year vs B&H:  {int(best_yr['year'])} ({best_yr['delta']:+.1%})")
    print(f"  Worst year vs B&H: {int(worst_yr['year'])} ({worst_yr['delta']:+.1%})")

    # ── Individual trade log ──
    print(f"\n  {'─── Full Trade Log ───'}")
    print(f"  {'#':>4s} {'Entry Date':>12s} {'Exit Date':>12s} {'Entry$':>8s} "
          f"{'Exit$':>8s} {'Return':>8s} {'Bars':>5s} {'Exit Reason':>12s}")
    print(f"  {'─' * 75}")
    for i, t in enumerate(trade_records):
        entry_date = df_copy.iloc[t["entry_idx"]]["_date"].strftime("%Y-%m-%d")
        exit_date = df_copy.iloc[t["exit_idx"]]["_date"].strftime("%Y-%m-%d")
        ret_str = f"{t['return'] * 100:+7.2f}%"
        print(f"  {i+1:>4d} {entry_date:>12s} {exit_date:>12s} "
              f"{t['entry_price']:>8.2f} {t['exit_price']:>8.2f} "
              f"{ret_str:>8s} {t['bars_held']:>5d} {t['exit_reason']:>12s}")

    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
