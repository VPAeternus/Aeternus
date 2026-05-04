import sys, os
sys.path.insert(0, '.')
import pandas as pd
import numpy as np
from tradingagents.phase_engine import data_engine

TICKERS = [
    # Indices
    'QQQ', 'SPY', 'IWM',
    # Mega-cap (SPY + QQQ overlap)
    'AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL', 'AVGO', 'TSLA',
    'BRK-B', 'JPM', 'LLY', 'UNH', 'COST', 'NFLX', 'V', 'MA',
    'HD', 'XOM', 'AMD', 'ADBE',
    # SPY large-cap (next tier)
    'PG', 'JNJ', 'WMT', 'BAC', 'CRM', 'ORCL', 'ABBV', 'KO', 'PEP',
    'MRK', 'TMO', 'CSCO', 'ABT', 'DHR', 'TXN', 'PM', 'NEE', 'UNP',
    # QQQ large-cap (next tier)
    'QCOM', 'AMGN', 'ISRG', 'INTU', 'AMAT', 'BKNG', 'ADP', 'LRCX',
    'PANW', 'SNPS', 'CDNS', 'MELI',
    # Russell 2000 top holdings (mid/small cap) - skip ITCI (delisted)
    'SMCI', 'DECK', 'ELF', 'FN', 'ONTO', 'LNTH',
    'CARG', 'PCVX', 'ANF', 'KTOS', 'CRDO',
    'SFM', 'CVLT', 'SKYW', 'FNB', 'OZK',
    'CADE', 'GBCI', 'HWC', 'CALM', 'PIPR', 'VIRT',
    'RHP', 'EXPO', 'NOVT', 'SIG', 'RMBS', 'PNFP',
    'IBOC', 'BGC', 'ENSG', 'CRC', 'TGTX', 'CSWI',
    'WDFC', 'BJ', 'UFPI', 'TBBK', 'COOP', 'ASGN',
    'SFBS', 'STEP', 'ALKS', 'GSHD', 'MTDR', 'PLXS',
]

INDEX_TICKERS = {'QQQ', 'SPY', 'IWM'}

def compute_accel(close_series, sma_series, lb=5):
    slope = (sma_series - sma_series.shift(lb)) / (close_series * lb)
    accel = slope - slope.shift(lb)
    return accel.values

def run_cc_overbought(df, holdout=3):
    close  = df['close'].values
    sma3   = df['sma3'].values
    sma50  = df['sma50'].values
    sma200 = df['sma200'].values

    accel   = compute_accel(df['close'], df['sma3'], lb=5)
    accel_s = pd.Series(accel)
    p90 = accel_s.expanding(min_periods=252).quantile(0.90).values
    p97 = accel_s.expanding(min_periods=252).quantile(0.97).values
    p03 = accel_s.expanding(min_periods=252).quantile(0.03).values

    n       = len(close)
    position = np.zeros(n)
    state    = 'long'
    days_out = 0
    exits    = {'ob': 0, 'fs': 0, 'dc': 0}
    entries  = 0
    start_i  = 252

    for i in range(start_i, n):
        pa   = accel[i]
        pc   = close[i]
        ps3  = sma3[i]
        ps50 = sma50[i]
        ps200= sma200[i]

        if any(np.isnan(v) for v in [pa, ps3, ps50, ps200]):
            position[i] = 1 if state == 'long' else 0
            if state == 'cash':
                days_out += 1
            continue

        above_200 = pc > ps200
        above_50  = pc > ps50

        if state == 'long':
            exit_now = False
            if above_200 and above_50 and pa > p90[i]:
                exit_now = True; exits['ob'] += 1
            elif above_200 and not above_50 and pa < p03[i]:
                exit_now = True; exits['fs'] += 1
            elif not above_200 and pa > p97[i]:
                exit_now = True; exits['dc'] += 1

            if exit_now:
                state = 'cash'; days_out = 0; position[i] = 0
            else:
                position[i] = 1
        else:
            days_out += 1
            if days_out >= holdout and pc > ps3:
                state = 'long'; position[i] = 1; entries += 1
            else:
                position[i] = 0

    daily_pts = np.diff(close); daily_pts = np.insert(daily_pts, 0, 0.0)
    daily_ret = np.diff(close) / close[:-1]; daily_ret = np.insert(daily_ret, 0, 0.0)
    strat_pts = position * daily_pts
    strat_ret = position * daily_ret

    s  = start_i
    sp = strat_pts[s:]; bp = daily_pts[s:]
    sr = strat_ret[s:]; br = daily_ret[s:]
    pos = position[s:]

    cum_s  = np.cumsum(sp); cum_b  = np.cumsum(bp)
    peak_s = np.maximum.accumulate(cum_s)
    peak_b = np.maximum.accumulate(cum_b)
    mdd_s  = (cum_s - peak_s).min()
    mdd_b  = (cum_b - peak_b).min()

    sr_s = sr.mean() / (sr.std() + 1e-10) * np.sqrt(252)
    sr_b = br.mean() / (br.std() + 1e-10) * np.sqrt(252)

    return {
        'Strategy_Pts':       round(float(sp.sum()), 2),
        'BuyHold_Pts':        round(float(bp.sum()), 2),
        'Delta_Pts':          round(float(sp.sum() - bp.sum()), 2),
        'Delta_Pct':          round(float((sp.sum() - bp.sum()) / (abs(bp.sum()) + 1e-10) * 100), 2),
        'Sharpe_Strat':       round(float(sr_s), 3),
        'Sharpe_BH':          round(float(sr_b), 3),
        'MaxDD_Strat':        round(float(mdd_s), 2),
        'MaxDD_BH':           round(float(mdd_b), 2),
        'Invested_Pct':       round(float(pos.mean() * 100), 1),
        'Exits_Overbought':   int(exits['ob']),
        'Exits_FailedSupport':int(exits['fs']),
        'Exits_DeadCat':      int(exits['dc']),
        'Total_Exits':        int(sum(exits.values())),
        'N_Bars':             int(len(close) - s),
        'Start_Price':        round(float(close[s]), 2),
        'End_Price':          round(float(close[-1]), 2),
    }

# ── Run all tickers ──────────────────────────────────────────────────────────
rows = []
failed = []
for ticker in TICKERS:
    try:
        df = data_engine.load(ticker)
        r  = run_cc_overbought(df)
        r['Ticker']   = ticker
        r['Category'] = 'Index' if ticker in INDEX_TICKERS else 'Stock'
        r['Beat_BH']  = r['Delta_Pts'] > 0
        r['Sharpe_Win'] = r['Sharpe_Strat'] > r['Sharpe_BH']
        r['MaxDD_Win']  = r['MaxDD_Strat']  > r['MaxDD_BH']
        rows.append(r)
        marker = '<<<' if r['Beat_BH'] else '   '
        print(f"  {ticker:6s} {marker}  delta={r['Delta_Pts']:>+9.2f}  strat={r['Strategy_Pts']:>+9.2f}  BH={r['BuyHold_Pts']:>+9.2f}  inv={r['Invested_Pct']:.0f}%  bars={r['N_Bars']}")
    except Exception as e:
        failed.append(ticker)
        print(f"  {ticker:6s} FAIL: {e}")

# ── Save CSV ─────────────────────────────────────────────────────────────────
col_order = [
    'Ticker', 'Category', 'Beat_BH', 'Sharpe_Win', 'MaxDD_Win',
    'Strategy_Pts', 'BuyHold_Pts', 'Delta_Pts', 'Delta_Pct',
    'Sharpe_Strat', 'Sharpe_BH', 'MaxDD_Strat', 'MaxDD_BH',
    'Invested_Pct', 'Exits_Overbought', 'Exits_FailedSupport',
    'Exits_DeadCat', 'Total_Exits', 'N_Bars', 'Start_Price', 'End_Price',
]
df_out = pd.DataFrame(rows)[col_order]
df_out = df_out.sort_values('Delta_Pts', ascending=False)

out_path = 'eval_results/cc_overbought_backtest.csv'
os.makedirs('eval_results', exist_ok=True)
df_out.to_csv(out_path, index=False)
print(f'\nSaved → {out_path}  ({len(df_out)} rows)')

# ── Print summary ─────────────────────────────────────────────────────────────
stocks = df_out[df_out['Category'] == 'Stock']
n = len(stocks)
beat = stocks['Beat_BH'].sum()
sw   = stocks['Sharpe_Win'].sum()
mw   = stocks['MaxDD_Win'].sum()

print(f'\n{"="*60}')
print(f'  STOCKS ({n}):')
print(f'    Beat B&H:   {int(beat)}/{n} ({beat/n*100:.0f}%)')
print(f'    Sharpe win: {int(sw)}/{n} ({sw/n*100:.0f}%)')
print(f'    MaxDD win:  {int(mw)}/{n} ({mw/n*100:.0f}%)')
print(f'    Avg delta:  {stocks["Delta_Pts"].mean():+.2f} pts')
print(f'    Med delta:  {stocks["Delta_Pts"].median():+.2f} pts')
if failed:
    print(f'\n  Failed ({len(failed)}): {failed}')
print(f'{"="*60}')
