"""
Aeternus Core — Per-Ticker Signal P&L Calculator
Computes cumulative short P&L for each ticker across all signals.

Two execution models:
  RTH signals (S2-S6, S7b): Signal on bar i → Short at Open[i+1] → Cover at Close[i+1]
  Overnight signals (S7a):   Signal on bar i → Short at Close[i] → Cover at Open[i+1]

1-share fixed sizing, GROSS P&L (no transaction costs).
Cost adjustment is a separate execution concern.
"""

import os
import json
import time

from . import data_engine, phase_engine, config as cfg
import numpy as np

CACHE_FILE = os.path.join(os.path.dirname(__file__), ".cache", "ticker_pnl.json")


def compute_ticker_pnl(ticker, df=None, phases=None, leader_df=None, leader_phases=None, leader_date_idx=None):
    """
    Compute cumulative signal short P&L for a single ticker.
    Returns dict: {total_pnl, trade_count, avg_pnl, win_rate, signals_breakdown}
    """
    if df is None:
        df = data_engine.load(ticker)
    if phases is None:
        phases = phase_engine.classify_phases(df)

    t = ticker.upper()
    n = len(df)

    total_pnl = 0.0
    wins = 0
    trades = 0
    signal_counts = {}

    for i in range(n - 1):  # -1 because we need bar i+1 for execution
        # ── RTH signals (S2-S6, S7b) ──
        if t in cfg.METALS_TICKERS:
            if leader_df is None or leader_phases is None or leader_date_idx is None:
                rth_sig = ""
            else:
                date = df.iloc[i]['date']
                if date not in leader_date_idx:
                    rth_sig = ""
                else:
                    li = leader_date_idx[date]
                    rth_sig = ""
                    if phase_engine.is_metals_md_flush(leader_df, leader_phases, li):
                        rth_sig = "metals_md_flush"
                    elif phase_engine.is_metals_mu_spike(leader_df, leader_phases, li):
                        rth_sig = "metals_mu_spike"
        else:
            rth_sig = phase_engine.should_short_rth(df, phases, i, ticker)

        if rth_sig:
            # Execute at bar i+1: short at open, cover at close
            next_bar = df.iloc[i + 1]
            raw_pnl = next_bar['open'] - next_bar['close']
            total_pnl += raw_pnl
            trades += 1
            if raw_pnl > 0:
                wins += 1
            signal_counts[rth_sig] = signal_counts.get(rth_sig, 0) + 1

        # ── Overnight signals (S7a) — independent, can fire same day as RTH ──
        overnight_sig = phase_engine.should_short_overnight(df, phases, i, ticker)
        if overnight_sig:
            # Execute: short at close[i], cover at open[i+1]
            entry = df.iloc[i]['close']
            exit_price = df.iloc[i + 1]['open']
            raw_pnl = entry - exit_price
            total_pnl += raw_pnl
            trades += 1
            if raw_pnl > 0:
                wins += 1
            signal_counts[overnight_sig] = signal_counts.get(overnight_sig, 0) + 1

    return {
        "ticker": ticker,
        "total_pnl": round(total_pnl, 2),
        "trades": trades,
        "avg_pnl": round(total_pnl / trades, 2) if trades > 0 else 0,
        "win_rate": round(wins / trades * 100, 1) if trades > 0 else 0,
        "signals": signal_counts,
    }


def compute_all_pnl(tickers=None, use_cache=True):
    """
    Compute P&L for all tickers. Caches results (recompute takes ~30s for 33 tickers).
    """
    if tickers is None:
        tickers = cfg.UNIVERSE

    # Check cache
    if use_cache and os.path.exists(CACHE_FILE):
        age_hours = (time.time() - os.path.getmtime(CACHE_FILE)) / 3600
        if age_hours < 24:  # Cache valid for 24 hours
            with open(CACHE_FILE, 'r') as f:
                return json.load(f)

    # Pre-load metals leader
    leader_df = None
    leader_phases = None
    leader_date_idx = None
    metals_needed = any(t.upper() in cfg.METALS_TICKERS for t in tickers)

    if metals_needed:
        try:
            leader_df = data_engine.load(cfg.METALS_LEADER)
            leader_phases = phase_engine.classify_phases(leader_df)
            leader_date_idx = {row['date']: idx for idx, row in leader_df.iterrows()}
        except Exception as e:
            print(f"WARNING: Failed to load metals leader: {e}")

    results = {}
    for ticker in tickers:
        try:
            df = data_engine.load(ticker)
            phases = phase_engine.classify_phases(df)
            pnl = compute_ticker_pnl(
                ticker, df, phases,
                leader_df=leader_df,
                leader_phases=leader_phases,
                leader_date_idx=leader_date_idx,
            )
            results[ticker] = pnl
        except Exception as e:
            print(f"  WARNING: {ticker} failed: {e}")
            results[ticker] = {"ticker": ticker, "total_pnl": 0, "trades": 0, "avg_pnl": 0, "win_rate": 0, "signals": {}}

    # Cache
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, 'w') as f:
        json.dump(results, f, indent=2)

    return results
