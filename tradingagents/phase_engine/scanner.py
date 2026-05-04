"""
Aeternus Core — Production Signal Scanner
Runs after market close OR during market hours with live Alpaca data.

Outputs for each signal:
  - Ticker, signal name, sub-system
  - Current close, SMA levels, VIX, volume vs 3d avg
  - Phase, historical avg PnL for that signal on that ticker
  - Action: SHORT at tomorrow's open, COVER at tomorrow's close
"""

import json
from datetime import datetime

from . import data_engine, phase_engine, config as cfg
from . import alpaca_data
import pandas as pd
import numpy as np


# ─── Default Universe ─────────────────────────────────────────────────────────
DEFAULT_UNIVERSE = [
    # Indices (S2 + S3 + S4)
    "QQQ", "SPY", "IWM",
    # Mega-cap
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA",
    # Growth / Semis
    "AVGO", "AMD", "AMAT", "ASML", "INTC", "MU", "WDC",
    # Fintech / New Economy
    "COIN", "HOOD", "SOFI", "PLTR", "HIMS",
    # Space / Energy
    "RKLB", "OKLO", "IREN",
    # Other
    "CRM", "NFLX", "BABA", "FCX",
    # Commodities
    "GDX", "URA",
    # Metals (S5 + S6, GLD-led)
    "GLD", "SLV",
]


def _vol_3d(df, i):
    """Compute 3-day volume average at bar i."""
    if i < cfg.VOLUME_AVG_SHORT:
        return np.nan
    vol_avg = 0.0
    for j in range(cfg.VOLUME_AVG_SHORT):
        vol_avg += df.iloc[i - j]['volume']
    return vol_avg / cfg.VOLUME_AVG_SHORT


def scan_ticker(ticker, df, phases, leader_df=None, leader_phases=None,
                leader_date_idx=None):
    """
    Scan a single ticker for today's signals.

    For metals tickers, we use date-based alignment with the leader (GLD).
    The bar index i on the trade ticker maps to the correct leader bar via
    leader_date_idx[date].

    Returns list of signal dicts (0, 1, or 2). A ticker can fire both an
    RTH signal and an overnight signal on the same day (different execution windows).
    """
    t = ticker.upper()
    n = len(df)
    if n < 2:
        return []

    i = n - 1  # last bar = today (most recent close)
    row = df.iloc[i]
    date = row['date']
    results = []

    # ── Metals: need date-aligned leader bar ──
    if t in cfg.METALS_TICKERS:
        if leader_df is None or leader_phases is None or leader_date_idx is None:
            return []
        if date not in leader_date_idx:
            return []
        li = leader_date_idx[date]
        sig = ""
        if phase_engine.is_metals_md_flush(leader_df, leader_phases, li):
            sig = "metals_md_flush"
        elif phase_engine.is_metals_mu_spike(leader_df, leader_phases, li):
            sig = "metals_mu_spike"

        if not sig:
            return []

        # Context from leader
        lr = leader_df.iloc[li]
        leader_phase = leader_phases.iloc[li]
        leader_vol_3d = _vol_3d(leader_df, li)

        return [{
            "ticker": ticker,
            "date": str(date)[:10],
            "signal": sig,
            "subsystem": "metals",
            "session": "rth",
            "action": "SHORT at tomorrow open → COVER at tomorrow close",
            "phase": str(leader_phase),
            "phase_source": "GLD (leader)",
            "close": float(row['close']),
            "leader_close": float(lr['close']),
            "leader_sma3": float(lr.get('sma3', np.nan)),
            "leader_sma10": float(lr.get('sma10', np.nan)),
            "leader_sma50": float(lr.get('sma50', np.nan)),
            "leader_sma200": float(lr.get('sma200', np.nan)),
            "leader_volume": int(lr['volume']),
            "leader_vol_3d": round(leader_vol_3d, 0) if not np.isnan(leader_vol_3d) else None,
            "leader_vol_ratio": round(float(lr['volume']) / leader_vol_3d, 2) if not np.isnan(leader_vol_3d) and leader_vol_3d > 0 else None,
            "vix": float(row.get('vix', np.nan)),
        }]

    # ── Equity: standard RTH signal check ──
    phase = phases.iloc[i]
    vol_3d_val = _vol_3d(df, i)
    subsystem = "index" if t in cfg.INDEX_TICKERS else "stock"

    def _equity_context(sig, session, action):
        return {
            "ticker": ticker,
            "date": str(date)[:10],
            "signal": sig,
            "subsystem": subsystem,
            "session": session,
            "action": action,
            "phase": str(phase),
            "close": float(row['close']),
            "sma3": float(row.get('sma3', np.nan)),
            "sma10": float(row.get('sma10', np.nan)),
            "sma20": float(row.get('sma20', np.nan)),
            "sma50": float(row.get('sma50', np.nan)),
            "sma200": float(row.get('sma200', np.nan)),
            "volume": int(row['volume']),
            "vol_3d": round(vol_3d_val, 0) if not np.isnan(vol_3d_val) else None,
            "vol_ratio": round(float(row['volume']) / vol_3d_val, 2) if not np.isnan(vol_3d_val) and vol_3d_val > 0 else None,
            "vix": float(row.get('vix', np.nan)),
            "fvg_ratio": float(row.get('fvg_ratio', np.nan)),
        }

    rth_sig = phase_engine.should_short_rth(df, phases, i, ticker)
    if rth_sig:
        results.append(_equity_context(
            rth_sig, "rth",
            "SHORT at tomorrow open → COVER at tomorrow close"
        ))

    # ── Overnight signal check (independent — can fire same day as RTH) ──
    overnight_sig = phase_engine.should_short_overnight(df, phases, i, ticker)
    if overnight_sig:
        results.append(_equity_context(
            overnight_sig, "overnight",
            "SHORT at today close → COVER at tomorrow open"
        ))

    return results


def run_scan(tickers=None, as_json=False, refresh=False, live=False):
    """
    Run the full scan across the universe.

    Args:
        live: If True, use Alpaca real-time data (requires .env with API keys).
              If False, use cached Yahoo data from data_engine.
    """
    if tickers is None:
        tickers = DEFAULT_UNIVERSE

    # Select data loader
    if live:
        _load = alpaca_data.load_live
        data_source = "ALPACA LIVE"
    else:
        _load = data_engine.load
        data_source = "CACHED"

    # Force refresh if requested (only applies to cached mode)
    if refresh and not live:
        import os
        import shutil
        if os.path.exists(cfg.CACHE_DIR):
            shutil.rmtree(cfg.CACHE_DIR)

    # ── Pre-load metals leader ──
    leader_df = None
    leader_phases = None
    leader_date_idx = None
    metals_needed = any(t.upper() in cfg.METALS_TICKERS for t in tickers)

    if metals_needed:
        try:
            leader_df = _load(cfg.METALS_LEADER)
            leader_phases = phase_engine.classify_phases(leader_df)
            leader_date_idx = {row['date']: idx for idx, row in leader_df.iterrows()}
        except Exception as e:
            print(f"WARNING: Failed to load metals leader {cfg.METALS_LEADER}: {e}")

    # ── Scan all tickers ──
    signals = []
    flat = []
    errors = []

    for ticker in tickers:
        try:
            df = _load(ticker)
            phases = phase_engine.classify_phases(df)
            result = scan_ticker(
                ticker, df, phases,
                leader_df=leader_df,
                leader_phases=leader_phases,
                leader_date_idx=leader_date_idx,
            )
            if result:
                signals.extend(result)
            else:
                # Gather flat ticker context
                n = len(df)
                if n > 0:
                    row = df.iloc[n - 1]
                    phase = phases.iloc[n - 1]
                    flat.append({
                        "ticker": ticker,
                        "phase": str(phase),
                        "close": float(row['close']),
                        "vix": float(row.get('vix', np.nan)),
                    })
        except Exception as e:
            errors.append({"ticker": ticker, "error": str(e)})

    # ── Output ──
    scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if as_json:
        output = {
            "scan_time": scan_time,
            "data_source": data_source,
            "signals": signals,
            "flat": flat,
            "errors": errors,
        }
        print(json.dumps(output, indent=2, default=str))
        return output

    # ── Pretty print ──
    print()
    print("=" * 72)
    print(f"  AETERNUS SIGNAL SCANNER — {scan_time}  [{data_source}]")
    print("=" * 72)

    if signals:
        print(f"\n  {len(signals)} SHORT SIGNAL{'S' if len(signals) != 1 else ''} FOR TOMORROW")
        print("  " + "-" * 68)

        for s in signals:
            print(f"\n  {s['ticker']:<8} | {s['signal']:<20} | {s['subsystem']}")
            print(f"           {s['action']}")
            print(f"           Phase: {s['phase']}")
            print(f"           Close: ${s['close']:.2f}", end="")

            if s['subsystem'] == 'metals':
                print(f"  (Leader GLD: ${s['leader_close']:.2f})")
                print(f"           GLD SMA10: ${s['leader_sma10']:.2f}  SMA50: ${s['leader_sma50']:.2f}")
                vr = s.get('leader_vol_ratio')
                print(f"           GLD Vol: {s['leader_volume']:,.0f}  3d Avg: {s['leader_vol_3d']:,.0f}  Ratio: {vr:.2f}x" if vr else "")
            else:
                print()
                print(f"           SMA3: ${s['sma3']:.2f}  SMA10: ${s['sma10']:.2f}  SMA50: ${s['sma50']:.2f}")
                vr = s.get('vol_ratio')
                print(f"           Vol: {s['volume']:,.0f}  3d Avg: {s['vol_3d']:,.0f}  Ratio: {vr:.2f}x" if vr else "")

            vix = s.get('vix')
            if vix and not np.isnan(vix):
                print(f"           VIX: {vix:.1f}")

        print()
    else:
        print("\n  NO SIGNALS — ALL FLAT TOMORROW")
        print()

    if flat:
        print(f"  FLAT TICKERS ({len(flat)}):")
        # Group by phase
        for phase in ["MARK_UP", "MARK_DOWN", "DIST_ACCUM"]:
            phase_tickers = [f for f in flat if f['phase'] == phase]
            if phase_tickers:
                names = ", ".join(f['ticker'] for f in phase_tickers)
                print(f"    {phase:<12} ({len(phase_tickers)}): {names}")
        print()

    if errors:
        print(f"  ERRORS ({len(errors)}):")
        for e in errors:
            print(f"    {e['ticker']}: {e['error']}")
        print()

    print("=" * 72)
    return {"signals": signals, "flat": flat, "errors": errors}
