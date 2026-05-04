"""
CSP/CC Signal Scanner
=====================
Run after 4:30pm ET — Yahoo has final EOD close and volume by then.
Signals fire on today's close; enter at TOMORROW's open.

Usage:
    python research/scanner.py
    python research/scanner.py --date 2026-04-07   # backfill a specific date
    python research/scanner.py --out signals.csv   # custom output path
"""

import warnings
warnings.filterwarnings('ignore')

import argparse
import numpy as np
import pandas as pd
from datetime import date, datetime
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as datastore

# ── Universe ─────────────────────────────────────────────────────────────────
UNIVERSE = [
    # Stocks
    "ARWR","KLAC","NVAX","INTU","SNPS","GTLS","ADBE","MRVL","META","TMO",
    "ABNB","MU","ORCL","ACLS","SIGI","NXPI","MARA","JPM","SHW","STRL",
    "UNH","AMAT","CRM","SPGI","ISRG","LRCX","HON","MA","RIOT","NXT",
    "DY","AMZN","IONQ","MMM","GE","SPXC","NOW","XOM","IBM","CLSK",
    "ONTO","AXP","TTMI","IRTC","ON","TMDX","MRK","BLK","RTX","GOOGL",
    "MCD","CVX","AAPL","DXCM","BAC","ABBV","ACN","TXN","CDNS","JNJ",
    "INTC","PANW","BX","CTAS","T","INSP","CRDO","GOOG","PRCT","PFE",
    "HL","PM","LIN","BRK-B","ITRI","PRAX","HD","V","KO","PYPL",
    "CAVA","CSCO","PG","MSFT","ORLY","AMGN","ABT","SCHW","AVGO","AMD",
    "PIPR","PEP","HOOD","DIS","FTNT","NKE","NVDA","ACAD","MDLZ","BBIO",
    "WMT","AEIS","TREX","NFLX","GH","NEE","MOD","QCOM","SOFI","HWC",
    "SPSC","BWXT","AHR","TRV","TMUS","BKNG","ADI","MGNI","SFM","GS",
    "SMCI","SATS","ENSG","REGN","IREN","COST","CELH","SKYW","BE","CDE",
    "PLTR","TTD","CEG","CRWD","LLY","FN","CAT","MELI","RMBS","TSLA",
    "KTOS","BA","SNDK","MDGL",
    # ETFs
    "USO","XOP","QQQ","SPY","IWM","GLD","SMH","SLV","XHB","ITB",
    "KRE","XLE","ARKK","XLF","IBB","XLV","XLY","XLB","XLI","XLK",
    "XLC","XLRE","XLP","XLU","XRT","XBI","DIA","DIA",
]
# Deduplicate while preserving order
seen = set()
UNIVERSE = [t for t in UNIVERSE if not (t in seen or seen.add(t))]

ETF_SET = {
    "USO","XOP","QQQ","SPY","IWM","GLD","SMH","SLV","XHB","ITB",
    "KRE","XLE","ARKK","XLF","IBB","XLV","XLY","XLB","XLI","XLK",
    "XLC","XLRE","XLP","XLU","XRT","XBI","DIA",
}

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

def compute_rsi(prices, period=14):
    deltas = np.diff(prices)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_g = np.zeros(len(prices)); avg_l = np.zeros(len(prices))
    avg_g[period] = gains[:period].mean()
    avg_l[period] = losses[:period].mean()
    for i in range(period+1, len(prices)):
        avg_g[i] = (avg_g[i-1]*(period-1) + gains[i-1]) / period
        avg_l[i] = (avg_l[i-1]*(period-1) + losses[i-1]) / period
    rs  = np.where(avg_l != 0, avg_g / avg_l, 100.0)
    rsi = np.where(avg_l == 0, 100.0, 100 - 100/(1+rs))
    rsi[:period] = np.nan
    return rsi

# ── Scanner ───────────────────────────────────────────────────────────────────
def scan_ticker(ticker, as_of_date=None):
    """
    Returns signal dict if entry fires on the latest (or as_of) bar, else None.
    as_of_date: string 'YYYY-MM-DD' to backfill a specific date.
    """
    try:
        raw = datastore.get_prices(ticker)
        if raw is None or len(raw) < 60:
            return None

        # Trim to as_of_date if provided
        if as_of_date:
            raw = raw[raw.index <= as_of_date]
            if len(raw) < 60:
                return None

        # Trim to as_of_date if backfilling, otherwise use full data
        # (data.py never caches today's bar, so today is always fetched
        # live with final EOD close/volume after 4:30pm ET)
        if as_of_date:
            raw = raw[raw.index <= as_of_date]
            if len(raw) < 60:
                return None

        close  = raw['Close'].values.astype(float)
        volume = raw['Volume'].values.astype(float)
        dates  = raw.index
        n = len(close)

        ama, ama2 = compute_kama(close)
        roc = np.abs((ama2 - np.roll(ama2, 1)) / np.roll(ama2, 1))
        roc[0] = 0
        vol_avg = np.array([volume[max(0,i-10):i].mean() for i in range(n)])
        rsi = compute_rsi(close)

        # Signal bar = latest bar (today's final close after 4:30pm ET)
        i = n - 1
        if np.isnan(rsi[i]):
            return None

        roc_ok  = roc[i] > 0.01
        ama_ok  = ama[i] > ama2[i]
        vol_ok  = volume[i] < vol_avg[i]
        rsi_ok  = rsi[i] > 50

        if not (roc_ok and ama_ok and vol_ok and rsi_ok):
            return None

        signal_date = dates[i].strftime('%Y-%m-%d')
        is_etf = ticker in ETF_SET

        return {
            'ticker':       ticker,
            'type':         'ETF' if is_etf else 'Stock',
            'signal_date':  signal_date,
            'close':        round(close[i], 2),
            'ama':          round(ama[i], 2),
            'ama2':         round(ama2[i], 2),
            'roc':          round(roc[i] * 100, 4),   # as %
            'rsi':          round(rsi[i], 1),
            'vol_ratio':    round(volume[i] / vol_avg[i], 2),  # <1.0 = below avg
            'open_gt_ama2pct': round((ama[i] * 1.02), 2),      # threshold for >2% gap
        }
    except Exception as e:
        return None

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='CSP/CC Signal Scanner')
    parser.add_argument('--date', default=None, help='Scan as of date YYYY-MM-DD (default: today)')
    parser.add_argument('--out',  default=None, help='Output CSV path (default: auto-named)')
    args = parser.parse_args()

    scan_date  = args.date or date.today().strftime('%Y-%m-%d')
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_path   = args.out or os.path.join(script_dir, f"signals_{scan_date}.csv")

    # Load backtest stats for historical context
    stats_path = os.path.join(script_dir, 'csp_cc_backtest_open_entry.csv')
    stats = {}
    if os.path.exists(stats_path):
        st = pd.read_csv(stats_path)
        for _, row in st.iterrows():
            stats[row['ticker']] = row

    print(f"\n{'='*60}")
    print(f"  CSP/CC Signal Scanner — {scan_date}")
    print(f"  Universe: {len(UNIVERSE)} tickers")
    print(f"{'='*60}")
    print(f"  Entry rules:")
    print(f"    RoC > 0.01%  |  AMA > AMA2  |  Vol < 10d avg  |  RSI > 50")
    print(f"  Signal bar: today's close (run after 4:30pm ET)")
    print(f"  Action: sell CSP or CC at TOMORROW's open")
    print(f"{'='*60}\n")

    signals = []
    for i, ticker in enumerate(UNIVERSE):
        print(f"  [{i+1:>3}/{len(UNIVERSE)}] {ticker:<8}", end='\r')
        result = scan_ticker(ticker, as_of_date=args.date)
        if result:
            signals.append(result)

    print(f"  Scanned {len(UNIVERSE)} tickers{' '*20}")

    if not signals:
        print(f"\n  No signals today.\n")
        return

    df = pd.DataFrame(signals)

    # Join backtest stats
    df['total_pnl']    = df['ticker'].map(lambda t: stats[t]['total_pnl']          if t in stats else None)
    df['win_rate']     = df['ticker'].map(lambda t: stats[t]['win_rate']            if t in stats else None)
    df['trades']       = df['ticker'].map(lambda t: int(stats[t]['trades'])         if t in stats else None)
    df['avg_pnl']      = df['ticker'].map(lambda t: stats[t]['avg_pnl_per_trade']   if t in stats else None)
    df['avg_hold']     = df['ticker'].map(lambda t: stats[t]['avg_hold']            if t in stats else None)

    # Recommend structure based on backtest PnL and VIX
    def recommend(row):
        pnl = row['total_pnl']
        if pnl is None:
            return '?'
        if pnl <= 0:
            return 'SKIP / Spread'
        if row['type'] == 'ETF':
            return 'CSP/CC'
        # For stocks: flag spread if historically marginal
        if pnl < 10:
            return 'Spread'
        return 'CSP/CC'

    df['structure'] = df.apply(recommend, axis=1)

    # Sort: profitable ETFs first, then stocks by total_pnl desc
    df['_prof'] = df['total_pnl'].fillna(-9999)
    df['_sort'] = df['type'].map({'ETF': 0, 'Stock': 1})
    df = df.sort_values(['_sort', '_prof'], ascending=[True, False]).drop(columns=['_sort', '_prof'])

    print(f"\n  ✅ {len(df)} signal(s) — sell at tomorrow's open\n")

    # Header
    h = (f"  {'Ticker':<7} {'Type':<6} {'Close':>7} {'RSI':>5} {'Vol/Avg':>8}"
         f"  {'TotPnL':>8} {'Win%':>6} {'Trades':>7} {'$/Tr':>6} {'Hold':>5}  {'Action':<12}")
    print(h)
    print(f"  {'─'*len(h)}")

    for _, row in df.iterrows():
        pnl_str  = f"${row['total_pnl']:>7.0f}"  if row['total_pnl'] is not None else '      N/A'
        win_str  = f"{row['win_rate']:>5.1f}%"    if row['win_rate']  is not None else '   N/A'
        trd_str  = f"{row['trades']:>7}"          if row['trades']    is not None else '     N/A'
        avg_str  = f"{row['avg_pnl']:>6.3f}"      if row['avg_pnl']   is not None else '   N/A'
        hld_str  = f"{row['avg_hold']:>4.1f}d"    if row['avg_hold']  is not None else '  N/A'
        action   = row['structure']
        flag     = ' ⚠️ ' if action in ('SKIP / Spread', 'Spread') else '    '

        print(f"  {row['ticker']:<7} {row['type']:<6} {row['close']:>7.2f} {row['rsi']:>5.1f} {row['vol_ratio']:>7.2f}x"
              f"  {pnl_str} {win_str} {trd_str} {avg_str} {hld_str}  {action}{flag}")

    print(f"\n  TotPnL / Win% / $/Tr = historical backtest (open[i+1] entry, 3% TP or SX exit)")
    print(f"  Action: CSP/CC = full naked | Spread = use credit spread | SKIP = avoid")
    print(f"  ⚠️  = historically unprofitable — consider spread to cap downside\n")

    df.drop(columns=['open_gt_ama2pct']).to_csv(out_path, index=False)
    print(f"  Saved: {out_path}\n")

if __name__ == '__main__':
    main()
