"""
Kerberos %B(20,2) Mean-Reversion Backtest — Short VXX + Put Option Variant
===========================================================================
Two modes:
  1. NAKED SHORT: short VXX directly with 50% stop loss
  2. PUT OPTION:  buy ATM put on VXX (defined risk = premium only)

Signal: VXX %B(20,2) crosses above 1 → entry. %B(20,1) crosses below 1 → exit.
Put pricing: Black-Scholes using ^VIX as IV proxy, 14-day expiry, ATM strike.

Usage: python3 scripts/backtest_kerberos_pctb.py
"""

import pandas as pd
import numpy as np
import yfinance as yf
from scipy.stats import norm

# ── Configuration ────────────────────────────────────────────────────────────

TICKER = "VXX"
START = "2009-01-30"       # VXX inception
STOP_LOSS_PCT = 50         # naked short: cover if VXX rises this %
PUT_DTE = 14               # days to expiry for synthetic puts
RISK_FREE_RATE = 0.04      # fallback if ^TNX unavailable


# ── Indicator Computation ────────────────────────────────────────────────────

def compute_pct_b(close: pd.Series, period: int, num_sd: float) -> pd.Series:
    """%B = (Close - LowerBand) / (UpperBand - LowerBand)"""
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = sma + num_sd * std
    lower = sma - num_sd * std
    return (close - lower) / (upper - lower)


# ── Black-Scholes Put Pricing ───────────────────────────────────────────────

def bs_put_price(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """European put price. T in years, sigma as decimal (e.g. 0.80)."""
    if T <= 0 or sigma <= 0:
        return max(K - S, 0.0)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


# ── Signal Generation ───────────────────────────────────────────────────────

def compute_signals(close: pd.Series):
    """Return (short_signal, cover_signal) boolean Series."""
    pct_b_2sd = compute_pct_b(close, 20, 2)
    pct_b_1sd = compute_pct_b(close, 20, 1)
    short_signal = (pct_b_2sd > 1) & (pct_b_2sd.shift(1) <= 1)
    cover_signal = (pct_b_1sd < 1) & (pct_b_1sd.shift(1) >= 1)
    return short_signal, cover_signal


# ── Backtest: Naked Short ───────────────────────────────────────────────────

def run_short_backtest(df: pd.DataFrame) -> list[dict]:
    """Short VXX with stop loss."""
    close = df["Close"]
    open_ = df["Open"]
    short_signal, cover_signal = compute_signals(close)
    stop_level = STOP_LOSS_PCT / 100

    trades = []
    in_position = False
    entry_date = entry_price = None

    for i in range(1, len(df)):
        today = df.index[i]
        prev = i - 1

        if not in_position and short_signal.iloc[prev]:
            in_position = True
            entry_date = today
            entry_price = open_.iloc[i]

        elif in_position:
            stopped = close.iloc[prev] >= entry_price * (1 + stop_level)
            signaled = cover_signal.iloc[prev]
            if stopped or signaled:
                exit_price = open_.iloc[i]
                ret = (entry_price - exit_price) / entry_price * 100
                trades.append({
                    "entry_date": entry_date,
                    "entry_price": round(entry_price, 2),
                    "exit_date": today,
                    "exit_price": round(exit_price, 2),
                    "return_pct": round(ret, 2),
                    "hold_days": (today - entry_date).days,
                    "exit_reason": "stop" if stopped else "signal",
                })
                in_position = False
    return trades


# ── Backtest: Put Options ───────────────────────────────────────────────────

def run_put_backtest(df: pd.DataFrame, vix: pd.Series) -> list[dict]:
    """Buy ATM puts on VXX using BS pricing with VIX as IV proxy."""
    close = df["Close"]
    open_ = df["Open"]
    short_signal, cover_signal = compute_signals(close)

    trades = []
    in_position = False
    entry_date = strike = premium = None

    for i in range(1, len(df)):
        today = df.index[i]
        prev = i - 1

        if not in_position and short_signal.iloc[prev]:
            spot = open_.iloc[i]
            # IV from VIX (as decimal); VXX vol is typically ~1.5x VIX level
            iv = vix.iloc[prev] / 100 * 1.5 if prev < len(vix) and pd.notna(vix.iloc[prev]) else 0.80
            iv = max(iv, 0.20)  # floor

            strike = round(spot)  # ATM
            T = PUT_DTE / 365
            premium = bs_put_price(spot, strike, T, RISK_FREE_RATE, iv)

            if premium <= 0.01:
                continue  # skip degenerate pricing

            in_position = True
            entry_date = today
            entry_spot = spot

        elif in_position:
            days_held = (today - entry_date).days
            expired = days_held >= PUT_DTE
            signaled = cover_signal.iloc[prev]

            if signaled or expired:
                exit_spot = open_.iloc[i]
                # Put value at exit: intrinsic (ignore remaining time value for simplicity on exit)
                intrinsic = max(strike - exit_spot, 0.0)

                # If exiting before expiry and still has time value, add it
                if not expired and days_held < PUT_DTE:
                    remaining_T = (PUT_DTE - days_held) / 365
                    iv_now = vix.iloc[prev] / 100 * 1.5 if prev < len(vix) and pd.notna(vix.iloc[prev]) else 0.80
                    iv_now = max(iv_now, 0.20)
                    exit_value = bs_put_price(exit_spot, strike, remaining_T, RISK_FREE_RATE, iv_now)
                else:
                    exit_value = intrinsic

                pnl = exit_value - premium
                ret_on_premium = pnl / premium * 100

                trades.append({
                    "entry_date": entry_date,
                    "entry_price": round(entry_spot, 2),
                    "exit_date": today,
                    "exit_price": round(exit_spot, 2),
                    "strike": strike,
                    "premium": round(premium, 2),
                    "exit_value": round(exit_value, 2),
                    "pnl": round(pnl, 2),
                    "return_pct": round(ret_on_premium, 2),
                    "hold_days": days_held,
                    "exit_reason": "expiry" if expired else "signal",
                })
                in_position = False
    return trades


# ── Analysis ─────────────────────────────────────────────────────────────────

def print_summary(title: str, trades: list[dict], capital: float = 10000.0):
    """Print stats for a trade list."""
    if not trades:
        print(f"\n  {title}: No trades generated.")
        return

    rets = np.array([t["return_pct"] for t in trades])
    holds = np.array([t["hold_days"] for t in trades])
    winners = rets[rets > 0]
    losers = rets[rets <= 0]
    n = len(rets)

    # Consecutive streaks
    is_win = rets > 0
    max_cw = max_cl = cw = cl = 0
    for w in is_win:
        if w:
            cw += 1; cl = 0; max_cw = max(max_cw, cw)
        else:
            cl += 1; cw = 0; max_cl = max(max_cl, cl)

    gross_profit = winners.sum() if len(winners) else 0
    gross_loss = abs(losers.sum()) if len(losers) else 1e-9
    profit_factor = gross_profit / gross_loss

    # Equity curve
    equity = capital
    peak = equity
    max_dd_pct = 0.0
    for r in rets:
        equity *= (1 + r / 100)
        peak = max(peak, equity)
        dd_pct = (peak - equity) / peak * 100
        max_dd_pct = max(max_dd_pct, dd_pct)
    total_return = (equity / capital - 1) * 100

    recovery = total_return / max_dd_pct if max_dd_pct > 0 else float("inf")

    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")
    print(f"  Total trades:          {n}")
    print(f"  Win rate:              {len(winners) / n * 100:.1f}%")
    print(f"  Loss rate:             {len(losers) / n * 100:.1f}%")
    print(f"  Avg return/trade:      {rets.mean():+.2f}%")
    print(f"  Avg winner:            {winners.mean():+.2f}%" if len(winners) else "  Avg winner:            N/A")
    print(f"  Avg loser:             {losers.mean():+.2f}%" if len(losers) else "  Avg loser:             N/A")
    print(f"  Avg hold days:         {holds.mean():.1f}")
    print(f"  Max consec winners:    {max_cw}")
    print(f"  Max consec losers:     {max_cl}")
    print(f"  Profit factor:         {profit_factor:.2f}")
    print(f"  Max drawdown:          {max_dd_pct:.1f}%")
    print(f"  Total return:          {total_return:+.1f}%")
    print(f"  Recovery factor:       {recovery:.2f}")

    return trades


def print_trade_log(trades: list[dict], mode: str):
    """Print trade-by-trade detail."""
    print(f"\n{'─' * 72}")
    print(f"  Trade Log ({mode})")
    print(f"{'─' * 72}")

    if mode == "puts":
        print(f"  {'Entry':<12} {'Spot':>7} {'K':>6} {'Prem':>6} {'Exit':<12} "
              f"{'ExSpot':>7} {'Value':>6} {'P&L':>7} {'Ret%':>7} {'D':>3} {'Why':>6}")
        print(f"  {'-'*12} {'-'*7} {'-'*6} {'-'*6} {'-'*12} "
              f"{'-'*7} {'-'*6} {'-'*7} {'-'*7} {'-'*3} {'-'*6}")
        for t in trades:
            print(f"  {t['entry_date'].strftime('%Y-%m-%d'):<12} "
                  f"{t['entry_price']:>7.2f} {t['strike']:>6} {t['premium']:>6.2f} "
                  f"{t['exit_date'].strftime('%Y-%m-%d'):<12} "
                  f"{t['exit_price']:>7.2f} {t['exit_value']:>6.2f} "
                  f"{t['pnl']:>+7.2f} {t['return_pct']:>+7.1f} "
                  f"{t['hold_days']:>3} {t['exit_reason']:>6}")
    else:
        print(f"  {'Entry':<12} {'Short$':>8} {'Cover':<12} {'Cover$':>8} "
              f"{'Ret%':>7} {'Days':>5} {'Exit':>6}")
        print(f"  {'-'*12} {'-'*8} {'-'*12} {'-'*8} {'-'*7} {'-'*5} {'-'*6}")
        for t in trades:
            print(f"  {t['entry_date'].strftime('%Y-%m-%d'):<12} "
                  f"{t['entry_price']:>8.2f} "
                  f"{t['exit_date'].strftime('%Y-%m-%d'):<12} "
                  f"{t['exit_price']:>8.2f} "
                  f"{t['return_pct']:>+7.2f} {t['hold_days']:>5} {t['exit_reason']:>6}")
    print()


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"Downloading {TICKER} + ^VIX data from {START}...")
    vxx = yf.download(TICKER, start=START, auto_adjust=True, progress=False)
    vix_raw = yf.download("^VIX", start=START, auto_adjust=True, progress=False)

    if vxx.empty:
        print("ERROR: No VXX data.")
        return

    # Flatten MultiIndex columns
    for d in [vxx, vix_raw]:
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)

    print(f"  {TICKER}: {len(vxx)} bars")
    print(f"  ^VIX:  {len(vix_raw)} bars")

    # Align VIX to VXX dates
    vix_close = vix_raw["Close"].reindex(vxx.index, method="ffill")

    period = f"{vxx.index[0].strftime('%Y-%m-%d')} to {vxx.index[-1].strftime('%Y-%m-%d')}"
    print(f"  Period: {period}")

    # ── Mode 1: Naked Short ──────────────────────────────────────────────
    short_trades = run_short_backtest(vxx)
    print_summary(f"MODE 1: Naked Short {TICKER} (stop {STOP_LOSS_PCT}%)", short_trades)
    print_trade_log(short_trades, "short")

    # ── Mode 2: Put Options ──────────────────────────────────────────────
    put_trades = run_put_backtest(vxx, vix_close)
    print_summary(f"MODE 2: Buy {TICKER} Puts (ATM, {PUT_DTE}-day, BS-priced)", put_trades)
    print_trade_log(put_trades, "puts")

    # ── Side-by-Side Comparison ──────────────────────────────────────────
    if short_trades and put_trades:
        sr = np.array([t["return_pct"] for t in short_trades])
        pr = np.array([t["return_pct"] for t in put_trades])
        sw = sr[sr > 0]; sl = sr[sr <= 0]
        pw = pr[pr > 0]; pl = pr[pr <= 0]
        print(f"{'=' * 60}")
        print(f"  COMPARISON")
        print(f"{'=' * 60}")
        print(f"  {'Metric':<25} {'Naked Short':>15} {'ATM Puts':>15}")
        print(f"  {'-'*25} {'-'*15} {'-'*15}")
        print(f"  {'Trades':<25} {len(sr):>15} {len(pr):>15}")
        print(f"  {'Win rate':<25} {len(sw)/len(sr)*100:>14.1f}% {len(pw)/len(pr)*100:>14.1f}%")
        print(f"  {'Avg return/trade':<25} {sr.mean():>+14.2f}% {pr.mean():>+14.2f}%")
        print(f"  {'Max loss (single)':<25} {sr.min():>+14.2f}% {pr.min():>+14.2f}%")
        sgp = sw.sum() if len(sw) else 0; sgl = abs(sl.sum()) if len(sl) else 1e-9
        pgp = pw.sum() if len(pw) else 0; pgl = abs(pl.sum()) if len(pl) else 1e-9
        print(f"  {'Profit factor':<25} {sgp/sgl:>15.2f} {pgp/pgl:>15.2f}")
        print()


if __name__ == "__main__":
    main()
