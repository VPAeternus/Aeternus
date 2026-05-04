"""
RTH vs Overnight Returns by SMA200 Regime — Full Universe Study
Tests: When stock is above SMA200, does RTH bleed? Bucketed by volatility.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from tradingagents.phase_engine import data_engine

# Full S&P 500 + Growth ETFs
SP500 = [
    # Tech
    'AAPL','MSFT','NVDA','AMZN','META','GOOGL','GOOG','AVGO','TSLA','ORCL',
    'CRM','AMD','ADBE','CSCO','ACN','IBM','INTC','INTU','QCOM','TXN',
    'AMAT','NOW','SNPS','CDNS','LRCX','PANW','KLAC','MCHP','FTNT','CRWD',
    'MRVL','ON','NXPI','KEYS','ANSS','GEN','EPAM','FSLR','MPWR','SWKS',
    'AKAM','JNPR','FFIV','WDC','ZBRA','TRMB','TER','NTAP','CTSH','IT',
    'HPQ','HPE','DELL','STX','ENPH','SEDG',
    # Financials
    'BRK-B','JPM','V','MA','BAC','WFC','GS','MS','SPGI','BLK',
    'SCHW','CB','MMC','AIG','MET','PRU','ICE','CME','MCO','MSCI',
    'AON','TFC','PNC','USB','AXP','COF','TROW','BK','C','FITB',
    'HBAN','KEY','CFG','RF','ZION','MTB','DFS','SYF','CINF','GL',
    'AJG','WRB','RJF','L','BRO','FDS','NDAQ','CBOE','RE','IVZ',
    # Healthcare
    'LLY','UNH','JNJ','ABBV','MRK','TMO','ABT','DHR','PFE','AMGN',
    'ISRG','VRTX','BMY','GILD','MDT','SYK','BSX','REGN','CI','ELV',
    'HCA','ZTS','BDX','DXCM','IDXX','MTD','IQV','A','BAX','EW',
    'HOLX','ALGN','TECH','MOH','CNC','HUM','BIIB','GEHC','RMD','WAT',
    'PODD','INCY','RVTY','XRAY','DGX','LH','CAH','MCK','COR','HSIC',
    # Consumer Discretionary
    'HD','COST','NFLX','MCD','LOW','NKE','SBUX','TJX','BKNG','ORLY',
    'MAR','AZO','GM','F','CMG','DHI','LEN','ROST','YUM','TSCO',
    'EBAY','BBY','DG','DLTR','POOL','GPC','APTV','GRMN','ULTA','WYNN',
    'LVS','MGM','CZR','RCL','CCL','EXPE','ABNB','DASH',
    # Consumer Staples
    'PG','PEP','KO','WMT','PM','MO','MDLZ','CL','KMB','GIS',
    'SJM','HSY','K','TSN','HRL','CPB','CAG','KHC','STZ','KDP',
    'MNST','CHD','CLX','SYY','KR','WBA','TGT','EL',
    # Industrials
    'CAT','GE','HON','UNP','RTX','BA','LMT','DE','UPS','GD',
    'MMM','EMR','ITW','ETN','ROK','PH','CMI','DOV','FTV','IR',
    'OTIS','SWK','FAST','CTAS','PCAR','CSX','NSC','WM','RSG','DAL',
    'UAL','LUV','ODFL','CARR','XYL','GNRC','TDG','HWM','PWR','VRSK',
    'CPRT','PAYX','LDOS','J','PAYC','NDSN','WAB',
    # Energy
    'XOM','CVX','COP','EOG','SLB','MPC','PSX','VLO','OXY','DVN',
    'HAL','HES','FANG','BKR','TRGP','KMI','WMB','OKE','CTRA',
    # Utilities
    'NEE','SO','DUK','D','AEP','SRE','EXC','XEL','WEC','ED',
    'ES','AEE','CMS','DTE','FE','PPL','EVRG','ATO','NI','PNW','CEG',
    # REITs
    'AMT','PLD','CCI','EQIX','PSA','O','SPG','WELL','DLR','AVB',
    'EQR','VTR','ARE','UDR','MAA','ESS','PEAK','KIM','REG','BXP',
    'HST','SBA','WY','IRM',
    # Materials
    'LIN','APD','SHW','ECL','DD','NEM','FCX','NUE','STLD','CF',
    'VMC','MLM','ALB','IFF','FMC','CE','SEE','EMN','IP','PKG','AVY',
    # Communication Services
    'T','VZ','TMUS','DIS','CMCSA','CHTR','NFLX','EA','TTWO','WBD',
    'MTCH','FOXA','FOX','IPG','OMC','LYV','PARA',
    # Growth ETFs + High-Vol Names
    'ARKK','ARKG','ARKF','ARKW','ARKQ',
    'QQQ','SPY','IWM','XLK','XLF','XLE','XLV','XLI','XLY','XLP','XLU',
    'SOXX','SMH','KWEB','MCHI','EEM','FXI',
    'COIN','SHOP','SQ','ROKU','SNAP','PINS','PLTR','RBLX','HOOD',
    'MELI','TTD','DDOG','ZS','NET','MDB','SNOW','BILL','HUBS',
    'TEAM','WDAY','OKTA','TWLO','U','DOCU','CRWD','PANW',
]

# Deduplicate
TICKERS = list(dict.fromkeys(SP500))

print(f"RTH vs Overnight by SMA200 Regime — {len(TICKERS)} tickers")
print(f"Loading data...")

results = []
failed = []

for idx, ticker in enumerate(TICKERS):
    if idx % 50 == 0 and idx > 0:
        print(f"  ...processed {idx}/{len(TICKERS)}")

    try:
        df = data_engine.load(ticker)
    except Exception:
        failed.append(ticker)
        continue

    if df is None or len(df) < 302:
        failed.append(ticker)
        continue

    df['date'] = pd.to_datetime(df['date'])
    close = df['close'].values
    opn = df['open'].values
    sma50 = df['sma50'].values
    sma200 = df['sma200'].values
    n = len(close)
    start_i = 252

    # Realized volatility
    daily_ret = np.abs(np.diff(close) / close[:-1])
    avg_vol = np.mean(daily_ret[start_i:]) * 100

    above_rth = 0; above_on = 0; above_days = 0
    below_rth = 0; below_on = 0; below_days = 0

    for i in range(start_i, n - 1):
        pc = close[i]
        ps200 = sma200[i]
        if np.isnan(ps200):
            continue

        rth = close[i+1] - opn[i+1]
        overnight = opn[i+1] - close[i]

        if pc > ps200:
            above_rth += rth; above_on += overnight; above_days += 1
        else:
            below_rth += rth; below_on += overnight; below_days += 1

    if above_days + below_days < 100:
        failed.append(ticker)
        continue

    avg_close = np.mean(close[start_i:])
    above_rth_bps = (above_rth / above_days / avg_close * 10000) if above_days > 0 else 0
    below_rth_bps = (below_rth / below_days / avg_close * 10000) if below_days > 0 else 0

    results.append({
        'Ticker': ticker,
        'AvgDailyVol': round(avg_vol, 3),
        'AboveDays': above_days,
        'AboveRTH': round(above_rth, 2),
        'AboveON': round(above_on, 2),
        'AboveTotal': round(above_rth + above_on, 2),
        'AboveRTH_BPS': round(above_rth_bps, 2),
        'BelowDays': below_days,
        'BelowRTH': round(below_rth, 2),
        'BelowON': round(below_on, 2),
        'BelowTotal': round(below_rth + below_on, 2),
        'BelowRTH_BPS': round(below_rth_bps, 2),
        'Bleeds': above_rth < 0,
    })

print(f"\nLoaded: {len(results)} | Failed: {len(failed)}")

# Save full CSV
df_out = pd.DataFrame(results).sort_values('AboveRTH')
out_path = 'eval_results/rth_regime_study.csv'
os.makedirs('eval_results', exist_ok=True)
df_out.to_csv(out_path, index=False)
print(f"Saved: {out_path}")

# Summary
bleeders = [r for r in results if r['Bleeds']]
gainers = [r for r in results if not r['Bleeds']]
print(f"\n{'='*70}")
print(f"RTH bleeds above SMA200: {len(bleeders)}/{len(results)} ({len(bleeders)/len(results)*100:.0f}%)")
print(f"Avg vol — Bleeders: {np.mean([r['AvgDailyVol'] for r in bleeders]):.2f}%  |  Gainers: {np.mean([r['AvgDailyVol'] for r in gainers]):.2f}%")

# Volatility quintiles
vols = sorted([r['AvgDailyVol'] for r in results])
q20 = np.percentile(vols, 20)
q40 = np.percentile(vols, 40)
q60 = np.percentile(vols, 60)
q80 = np.percentile(vols, 80)

print(f"\nBy volatility quintile:")
print(f"{'Quintile':<30s} {'Count':>6s} {'Bleed':>6s} {'Bleed%':>7s} {'Avg RTH bps/d':>14s}")
print('-' * 65)
for label, lo, hi in [
    (f'Q1 Low (<{q20:.2f}%)', 0, q20),
    (f'Q2 ({q20:.2f}-{q40:.2f}%)', q20, q40),
    (f'Q3 ({q40:.2f}-{q60:.2f}%)', q40, q60),
    (f'Q4 ({q60:.2f}-{q80:.2f}%)', q60, q80),
    (f'Q5 High (>{q80:.2f}%)', q80, 100),
]:
    bucket = [r for r in results if lo <= r['AvgDailyVol'] < hi]
    if not bucket:
        continue
    n_bleed = sum(1 for r in bucket if r['Bleeds'])
    avg_bps = np.mean([r['AboveRTH_BPS'] for r in bucket])
    print(f"  {label:<28s} {len(bucket):>6d} {n_bleed:>6d} {n_bleed/len(bucket)*100:>6.0f}% {avg_bps:>+13.2f}")

# Aggregate
total_above_rth = sum(r['AboveRTH'] for r in results)
total_above_on = sum(r['AboveON'] for r in results)
total_below_rth = sum(r['BelowRTH'] for r in results)
total_below_on = sum(r['BelowON'] for r in results)
print(f"\nAGGREGATE ({len(results)} tickers):")
print(f"  Above SMA200:  RTH {total_above_rth:>+12.2f}  |  ON {total_above_on:>+12.2f}  |  Total {total_above_rth+total_above_on:>+12.2f}")
print(f"  Below SMA200:  RTH {total_below_rth:>+12.2f}  |  ON {total_below_on:>+12.2f}  |  Total {total_below_rth+total_below_on:>+12.2f}")

# Top 20 worst bleeders
print(f"\nTop 20 worst RTH bleeders above SMA200:")
print(f"{'Ticker':<8s} {'Vol%':>6s} {'RTH Pts':>10s} {'ON Pts':>10s} {'RTH bps/d':>10s}")
print('-' * 48)
worst = sorted(results, key=lambda x: x['AboveRTH'])[:20]
for r in worst:
    print(f"{r['Ticker']:<8s} {r['AvgDailyVol']:>6.2f} {r['AboveRTH']:>+10.2f} {r['AboveON']:>+10.2f} {r['AboveRTH_BPS']:>+10.2f}")

# Top 20 best RTH gainers above SMA200
print(f"\nTop 20 best RTH gainers above SMA200:")
print(f"{'Ticker':<8s} {'Vol%':>6s} {'RTH Pts':>10s} {'ON Pts':>10s} {'RTH bps/d':>10s}")
print('-' * 48)
best = sorted(results, key=lambda x: x['AboveRTH'], reverse=True)[:20]
for r in best:
    print(f"{r['Ticker']:<8s} {r['AvgDailyVol']:>6.2f} {r['AboveRTH']:>+10.2f} {r['AboveON']:>+10.2f} {r['AboveRTH_BPS']:>+10.2f}")

if failed:
    print(f"\nFailed ({len(failed)}): {', '.join(failed[:30])}{'...' if len(failed)>30 else ''}")
