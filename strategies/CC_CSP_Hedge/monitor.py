"""
CSP/CC Position Monitor
=======================
Check which open positions have hit their exit condition (3% TP or RoC < 0.01).
Run anytime — uses latest Yahoo close data.

Usage:
    python research/monitor.py

Edit the POSITIONS list below with your open trades.
Format: (ticker, entry_price, entry_date)
"""

import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from datetime import date
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as datastore

# ── YOUR OPEN POSITIONS ───────────────────────────────────────────────────────
# Edit this list with your actual open trades.
# entry_price = the open price you sold the CSP/CC at (open[i+1])
# entry_date  = the date you entered (YYYY-MM-DD)

POSITIONS = [
    # Examples — replace with your actual trades:
    # ('AAPL',  170.50, '2026-04-07'),
    # ('QQQ',   445.20, '2026-04-07'),
    # ('NVDA',  890.00, '2026-04-06'),
]

TP_PCT = 0.03   # 3% take profit — matches backtest

# ── Indicators ────────────────────────────────────────────────────────────────
def compute_kama(prices, fast=1, fast2=2, slow=15, er_len=10):
    n = len(prices)
    fast_sc = 2/(fast+1); fast2_sc = 2/(fast2+1); slow_sc = 2/(slow+1)
    ama = np.full(n, np.nan); ama2 = np.full(n, np.nan)
    ama[0] = ama2[0] = prices[0]
    for i in range(1, n):
        start = max(0, i - er_len)
        direction  = abs(prices[i] - prices[start])
        volatility = np.sum(np.abs(np.diff(prices[start:i+1])))
        er  = direction / volatility if volatility != 0 else 0
        sc  = (er*(fast_sc  - slow_sc) + slow_sc)**2
        sc2 = (er*(fast2_sc - slow_sc) + slow_sc)**2
        ama[i]  = ama[i-1]  + sc  * (prices[i] - ama[i-1])
        ama2[i] = ama2[i-1] + sc2 * (prices[i] - ama2[i-1])
    return ama, ama2

# ── Monitor ───────────────────────────────────────────────────────────────────
def check_position(ticker, entry_price, entry_date):
    try:
        raw = datastore.get_prices(ticker)
        if raw is None or len(raw) < 60:
            return None

        close  = raw['Close'].values.astype(float)
        dates  = raw.index
        n = len(close)

        ama, ama2 = compute_kama(close)
        roc = np.abs((ama2 - np.roll(ama2, 1)) / np.roll(ama2, 1))
        roc[0] = 0

        # Find entry bar index
        entry_idx = None
        for j in range(n):
            if dates[j].strftime('%Y-%m-%d') >= entry_date:
                entry_idx = j
                break
        if entry_idx is None:
            return None

        latest_idx   = n - 1
        latest_close = close[latest_idx]
        latest_date  = dates[latest_idx].strftime('%Y-%m-%d')
        hold_days    = latest_idx - entry_idx
        pnl          = entry_price - latest_close   # short PnL
        pnl_pct      = pnl / entry_price * 100

        # Check exit conditions on latest bar
        tp_hit = pnl_pct >= TP_PCT * 100
        sx_hit = roc[latest_idx] < 0.01

        if tp_hit:
            status = '🟢 EXIT — TP HIT'
        elif sx_hit:
            status = '🟡 EXIT — SX (RoC < 0.01)'
        else:
            status = '🔵 HOLD'

        return {
            'ticker':       ticker,
            'entry_date':   entry_date,
            'entry_price':  entry_price,
            'latest_date':  latest_date,
            'latest_close': round(latest_close, 2),
            'hold_days':    hold_days,
            'pnl':          round(pnl, 2),
            'pnl_pct':      round(pnl_pct, 2),
            'roc':          round(roc[latest_idx] * 100, 4),
            'tp_hit':       tp_hit,
            'sx_hit':       sx_hit,
            'status':       status,
        }
    except Exception as e:
        return {'ticker': ticker, 'status': f'ERROR: {e}'}

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    today = date.today().strftime('%Y-%m-%d')

    print(f"\n{'='*65}")
    print(f"  CSP/CC Position Monitor — {today}")
    print(f"  Exit rules: 3% TP  |  RoC < 0.01 (signal gone)")
    print(f"{'='*65}\n")

    if not POSITIONS:
        print("  No open positions. Edit POSITIONS in monitor.py to add trades.\n")
        return

    results = []
    for ticker, entry_price, entry_date in POSITIONS:
        print(f"  Checking {ticker}...", end='\r')
        r = check_position(ticker, entry_price, entry_date)
        if r:
            results.append(r)

    print(f"  {'─'*63}")
    exits = [r for r in results if r.get('tp_hit') or r.get('sx_hit')]
    holds = [r for r in results if not r.get('tp_hit') and not r.get('sx_hit')]

    # Print exits first
    if exits:
        print(f"\n  ACTION REQUIRED — Close these positions today:\n")
        print(f"  {'Ticker':<8} {'Entry':>7} {'Close':>7} {'PnL$':>7} {'PnL%':>7} {'Hold':>5}  Status")
        print(f"  {'─'*63}")
        for r in exits:
            print(f"  {r['ticker']:<8} {r['entry_price']:>7.2f} {r['latest_close']:>7.2f} "
                  f"${r['pnl']:>6.2f} {r['pnl_pct']:>6.2f}% {r['hold_days']:>3}d  {r['status']}")

    # Print holds
    if holds:
        print(f"\n  HOLD — No exit signal:\n")
        print(f"  {'Ticker':<8} {'Entry':>7} {'Close':>7} {'PnL$':>7} {'PnL%':>7} {'Hold':>5}  RoC%")
        print(f"  {'─'*63}")
        for r in holds:
            print(f"  {r['ticker']:<8} {r['entry_price']:>7.2f} {r['latest_close']:>7.2f} "
                  f"${r['pnl']:>6.2f} {r['pnl_pct']:>6.2f}% {r['hold_days']:>3}d  {r['roc']:.4f}%")

    print(f"\n  Total positions: {len(results)} | Exits: {len(exits)} | Holds: {len(holds)}\n")

if __name__ == '__main__':
    main()
