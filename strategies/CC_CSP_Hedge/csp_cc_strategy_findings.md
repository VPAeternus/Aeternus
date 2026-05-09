# CSP / Covered Call Strategy — Finalized Parameters & Backtest Results

## Strategy Overview
Sell Cash Secured Puts (CSPs) and Covered Calls during identified "flat" market periods using a dual KAMA signal.

---

## Finalized Signal Parameters

### KAMA (Dual AMA System)
| Parameter | Value |
|---|---|
| fastLength (AMA) | 1 |
| fastLength2 (AMA2) | 2 |
| slowLength | 15 |
| effRatioLength | 10 |

### Sell Entry (SE)
- RoC > 0.01 **AND**
- AMA > AMA2 **AND**
- Volume < 10-day average volume **AND**
- RSI(14) > 50

### Sell Exit (SX) — whichever comes first:
- **3% take profit** (price drops 3% from entry), OR
- **RoC < 0.01** (SX signal)

### Filters Tested & Rejected
| Filter | Outcome |
|---|---|
| Max hold 1d | Reduces PnL on most tickers |
| Max hold 2d | Reduces PnL on most tickers |
| Max hold 3d | Wins 5/13 vs no-hold 7/13, rejected |
| Max hold 4d | Wins 1/13, rejected |
| Close > SMA200 | Wins only 4/13 tickers, rejected |
| Close < SMA200 | Wins only 1/13 tickers, rejected |
| Close > SMA20 | Redundant — AMA>AMA2 already implies it |
| Close < SMA20 | 0 trades on 9/13 tickers, rejected |
| RSI(14) > 55 | $4,056 vs $4,312 for RSI>50, rejected |
| RSI(14) > 60 | $2,922, worse than no filter, rejected |
| RSI(14) < 50 | Near-zero trades, signal implies RSI>50 |
| 5d vol avg | Wins 5/13 tickers vs 10d, rejected |
| 20d vol avg | Worse than 10d for most tickers |
| 50d vol avg | Worse than 10d for most tickers |
| 5d+5%TP cap | Total PnL -$925 vs +$2,480 original, rejected |
| TP only 5% | +$3,035 vs +$3,094 for 3%, rejected |
| TP only 4% | +$3,030 vs +$3,094 for 3%, rejected |
| TP only 2.5% | +$3,045 wins 88/147, rejected |
| TP only 2% | +$3,067 wins 92/147, rejected |

---

## Backtest Results — Finalized Config (10d Vol, No SMA Filter, No Max Hold)

**Data:** yfinance daily, `auto_adjust=False`, full history per ticker
**Short PnL:** entry_price − exit_price (profit when price falls or stays flat)

| Ticker | Total PnL ($) | Trades | Win Rate | Avg Hold |
|---|---|---|---|---|
| QQQ | +$35.81 | 55 | 72.7% | 1.6d |
| SPY | +$26.71 | 31 | 71.0% | 1.3d |
| IWM | +$12.26 | 41 | 68.3% | 1.5d |
| GLD | +$26.12 | 19 | 68.4% | 1.9d |
| SLV | +$7.92 | 65 | 67.7% | 2.0d |
| USO | +$82.40 | 84 | 73.8% | 1.8d |
| MU | +$9.19 | 317 | 58.7% | 2.6d |
| GOOGL | +$17.42 | 74 | 60.8% | 2.1d |
| MSFT | +$5.17 | 143 | 57.3% | 2.1d |
| AAPL | +$16.68 | 242 | 57.0% | 2.4d |
| AMZN | +$21.80 | 159 | 58.5% | 2.3d |
| NVDA | -$1.58 | 195 | 60.5% | 2.5d |
| TSLA | -$101.33 | 112 | 53.6% | 2.7d |

### Notes
- ETFs (QQQ, SPY, IWM, GLD, SLV, USO) show higher win rates (67–74%) and shorter holds (1.3–2.0d)
- Individual stocks show lower win rates (53–61%) and longer holds (2.1–2.7d)
- NVDA and TSLA are net losers — strategy does not work on high-volatility momentum names
- TSLA loss driven by large adverse moves during "flat" signal windows

---

## Vol Filter Comparison (No SMA Filter, No Max Hold)

| Ticker | 5d PnL | 10d PnL | 20d PnL | Winner |
|---|---|---|---|---|
| QQQ | +$58.34 | +$35.81 | — | 5d |
| SPY | +$19.11 | +$26.71 | — | 10d |
| IWM | +$13.49 | +$12.26 | — | 5d |
| GLD | +$12.22 | +$26.12 | — | 10d |
| SLV | +$4.60 | +$7.92 | — | 10d |
| USO | +$75.26 | +$82.40 | — | 10d |
| MU | -$16.48 | +$9.19 | — | 10d |
| GOOGL | +$4.35 | +$17.42 | — | 10d |
| MSFT | +$8.33 | +$5.17 | — | 5d |
| AAPL | +$0.24 | +$16.68 | — | 10d |
| AMZN | +$28.78 | +$21.80 | — | 5d |
| NVDA | -$6.86 | -$1.58 | — | 10d |
| TSLA | -$214.76 | -$101.33 | — | 10d |
| **Score** | **5/13** | **8/13** | | **10d wins** |

**Decision: 10d volume average is the finalized filter.**

---

## Backtest Results — Finalized Config (10d Vol, 3% TP or SX, 147 Stocks)

**Data:** yfinance daily, `auto_adjust=False`, full history per ticker
**Exit:** 3% take profit OR RoC < 0.01, whichever comes first
**CSV:** `research/csp_cc_backtest_final_3pct_tp.csv`

| Metric | Value |
|---|---|
| Total tickers | 147 |
| Profitable | 99/147 (67%) |
| Losing | 48/147 (33%) |
| Total PnL | +$3,097 |
| Avg win rate | 60.3% |
| Avg hold | 2.3d |

### Top 15 by Total PnL
| Rank | Ticker | Group | PnL ($) | Trades | Win% | Avg Hold | Avg$/Tr |
|---|---|---|---|---|---|---|---|
| 1 | ARWR | IWM50 | +$1,850 | 278 | 53.6% | 3.2d | $5.14 |
| 2 | NVAX | IWM50 | +$282 | 209 | 65.9% | 2.5d | $0.74 |
| 3 | KLAC | QQQ50 | +$264 | 278 | 61.1% | 2.5d | $0.93 |
| 4 | GTLS | IWM50 | +$108 | 154 | 62.7% | 2.2d | $0.83 |
| 5 | SNPS | QQQ50 | +$93 | 149 | 67.1% | 2.0d | $0.63 |
| 6 | MRVL | QQQ50 | +$73 | 155 | 71.8% | 2.2d | $0.45 |
| 7 | ADBE | QQQ50 | +$69 | 229 | 63.5% | 2.3d | $0.29 |
| 8 | META | QQQ50+SPY50 | +$57 | 50 | 64.0% | 2.1d | $1.14 |
| 9 | TMO | SPY50 | +$56 | 154 | 60.4% | 2.0d | $0.37 |
| 10 | ABNB | QQQ50 | +$54 | 32 | 75.0% | 1.7d | $1.92 |
| 11 | INTU | QQQ50+SPY50 | +$53 | 154 | 60.6% | 2.1d | $0.34 |
| 12 | ACLS | IWM50 | +$53 | 177 | 66.9% | 2.4d | $0.30 |
| 13 | ORCL | SPY50 | +$50 | 203 | 61.0% | 2.2d | $0.26 |
| 14 | MU | QQQ50+SPY50 | +$47 | 317 | 59.2% | 2.5d | $0.15 |
| 15 | SIGI | IWM50 | +$46 | 169 | 63.3% | 1.9d | $0.26 |

### Consistent Losers (avoid for CSP/CC)
| Ticker | PnL ($) | Note |
|---|---|---|
| MDGL | -$177 | High-beta biotech |
| SNDK | -$116 | Recent spinoff, extreme vol |
| TSLA | -$101 | Momentum, large adverse moves |
| BA | -$88 | Cyclical, gap risk |
| RMBS | -$76 | Semiconductor IP, thin float |
| CRWD | -$67 | High-growth, momentum |

---

## ETF Backtest Results — Finalized Config (10d Vol, 3% TP or SX)

**CSV:** `research/csp_cc_backtest_etfs_3pct_tp.csv`
**28/30 ETFs profitable** — strategy works well across ETF universe

| Ticker | Group | PnL ($) | Trades | Win% | Avg Hold | Avg$/Tr |
|---|---|---|---|---|---|---|
| USO | BroadETF | +$82.40 | 84 | 73.8% | 1.8d | $0.98 |
| XOP | SectorETF | +$56.31 | 85 | 58.8% | 2.2d | $0.66 |
| QQQ | BroadETF | +$35.81 | 55 | 72.7% | 1.6d | $0.65 |
| SPY | BroadETF | +$26.71 | 31 | 71.0% | 1.3d | $0.86 |
| GLD | BroadETF | +$26.12 | 19 | 68.4% | 1.9d | $1.38 |
| SMH | SectorETF | +$17.00 | 83 | 59.0% | 1.9d | $0.21 |
| XHB | SectorETF | +$16.79 | 56 | 71.4% | 1.5d | $0.30 |
| IWM | BroadETF | +$12.26 | 41 | 68.3% | 1.5d | $0.30 |
| ITB | SectorETF | +$11.93 | 69 | 66.7% | 1.9d | $0.17 |
| XLE | SectorETF | +$11.88 | 62 | 62.9% | 1.7d | $0.19 |
| KRE | SectorETF | +$11.77 | 51 | 58.8% | 1.6d | $0.23 |
| SLV | BroadETF | +$7.92 | 65 | 67.7% | 2.0d | $0.12 |
| ARKK | SectorETF | +$7.65 | 53 | 58.5% | 2.0d | $0.14 |
| IBB | SectorETF | +$7.55 | 60 | 63.3% | 1.7d | $0.13 |
| XLY | SectorETF | +$7.46 | 50 | 70.0% | 1.6d | $0.15 |
| XLF | SectorETF | +$7.24 | 42 | 71.4% | 1.5d | $0.17 |
| XLV | SectorETF | +$7.09 | 20 | **80.0%** | 1.6d | $0.36 |
| XLB | SectorETF | +$6.48 | 53 | 71.7% | 1.6d | $0.12 |
| XLI | SectorETF | +$5.22 | 46 | 71.7% | 1.4d | $0.11 |
| XBI | SectorETF | +$4.47 | 71 | 54.9% | 2.0d | $0.06 |
| XRT | SectorETF | +$4.18 | 40 | 70.0% | 1.8d | $0.10 |
| XLK | SectorETF | +$3.42 | 55 | 56.4% | 1.7d | $0.06 |
| HYG | BroadETF | +$2.60 | 4 | 50.0% | 1.0d | $0.65 |
| XLU | SectorETF | +$2.15 | 21 | 61.9% | 1.3d | $0.10 |
| XLC | SectorETF | +$1.65 | 10 | 50.0% | 1.8d | $0.17 |
| XLP | SectorETF | +$0.98 | 8 | 75.0% | 1.4d | $0.12 |
| XLRE | SectorETF | +$0.73 | 10 | 70.0% | 1.5d | $0.07 |
| LQD | BroadETF | +$0.63 | 1 | 100.0% | 1.0d | $0.63 |
| DIA | BroadETF | -$0.47 | 22 | 59.1% | 1.5d | -$0.02 |
| TLT | BroadETF | -$2.24 | 6 | 66.7% | 1.8d | -$0.37 |

**ETF insight:** Energy (USO, XOP, XLE) dominates. Broad market ETFs (QQQ, SPY, IWM) are consistent. XLV highest win rate at 80%. TLT and DIA are the only losers — bonds and Dow underperform.

---

## Realistic Entry: open[i+1] vs close[i] Comparison

**Signal fires at close[i] — realistic entry is open[i+1] (MOC or next-day open)**
**Exit: close[j] for both TP and SX (unchanged)**
**CSV:** `research/csp_cc_backtest_open_entry.csv`

| Metric | Close[i], no RSI | Close[i], RSI>50 | Open[i+1], RSI>50 |
|---|---|---|---|
| Total PnL | $3,097 | **$4,312** | $4,047 |
| Profitable tickers | 99/147 | — | 121/174 |
| Avg win rate | 60.3% | 60.3% | 59.7% |
| Avg hold | 2.3d | 2.3d | 1.2d |

**Finding:** Open[i+1] with RSI>50 is -$265 vs the close[i] RSI>50 baseline — a small
but real execution cost for realistic fills. Close[i] is not achievable in live trading
(signal computed from that same bar's close). **$4,047 is the correct live-trading baseline.**

### Gap Filter Analysis (open > AMA+2% for stocks)
Tested but **rejected** — more trades is better when selling options premium.
Every signal = a CSP/CC entry = premium collected. Filtering reduces income.

| | Stocks baseline | Stocks >AMA+2% only |
|---|---|---|
| PnL | $3,639 | $2,919 |
| Trades | 18,723 | 10,468 (−44%) |
| Avg $/trade | $0.194 | $0.279 |

Gap filter improves per-trade quality but cuts 44% of premium-selling opportunities.
Rejected. Baseline (no gap filter) is locked.

---

## 🔒 LOCKED FINAL CONFIG

| Parameter | Value |
|---|---|
| Signal | Dual KAMA: AMA (fast=1), AMA2 (fast=2), slow=15, ER=10 |
| Entry condition | RoC > 0.01 AND AMA > AMA2 AND Vol < 10d avg AND RSI(14) > 50 |
| Entry price | open[i+1] — next day open after signal fires |
| Exit | 3% take profit OR RoC < 0.01, whichever comes first |
| Exit price | close[j] |
| Gap filter | None — all signals taken |
| **Total PnL** | **$4,047** |
| **Trades** | **19,956** |
| **Win rate** | **59.7%** |
| **Avg hold** | **1.2d** |
| Profitable tickers | 121/174 (69%) |

### Top 15 (open[i+1] entry)
| Rank | Ticker | Group | PnL | Trades | Win% | Avg Hold | $/Trade |
|---|---|---|---|---|---|---|---|
| 1 | ARWR | IWM50 | +$2,013 | 235 | 56.6% | 2.3d | $8.57 |
| 2 | KLAC | QQQ50 | +$318 | 276 | 56.5% | 1.5d | $1.15 |
| 3 | MELI | QQQ50 | +$150 | 137 | 65.7% | 1.3d | $1.09 |
| 4 | GTLS | IWM50 | +$118 | 149 | 59.7% | 1.3d | $0.79 |
| 5 | SNPS | QQQ50 | +$110 | 147 | 67.3% | 1.0d | $0.75 |
| 6 | KTOS | IWM50 | +$91 | 159 | 64.8% | 1.6d | $0.57 |
| 7 | INTU | QQQ50+SPY50 | +$80 | 154 | 60.4% | 1.1d | $0.52 |
| 8 | NXPI | QQQ50 | +$72 | 80 | 66.2% | 1.0d | $0.90 |
| 9 | TMO | SPY50 | +$66 | 155 | 51.6% | 1.0d | $0.43 |
| 10 | ONTO | IWM50 | +$62 | 46 | 71.7% | 1.6d | $1.35 |
| 11 | USO | ETF | +$59 | 81 | 65.4% | 0.8d | $0.73 |
| 12 | MU | QQQ50+SPY50 | +$58 | 304 | 57.9% | 1.5d | $0.19 |
| 13 | NVAX | IWM50 | +$57 | 189 | 66.7% | 1.7d | $0.30 |
| 14 | ADBE | QQQ50 | +$54 | 224 | 60.3% | 1.3d | $0.24 |
| 15 | MRVL | QQQ50 | +$48 | 146 | 67.1% | 1.2d | $0.33 |

### Notable flips vs close[i] entry
| Ticker | Close[i] PnL | Open[i+1] PnL | Verdict |
|---|---|---|---|
| MELI | -$64 | +$150 | Flip to winner |
| KTOS | -$75 | +$91 | Flip to winner |
| PRAX | +$9 | -$113 | Flip to loser |
| CEG | -$40 | -$39 | Still loser |
| TSLA | -$71 | -$78 | Still loser |

---

## VIX Bucket Analysis — Full Universe (147 Stocks + 30 ETFs)

**Total trades:** 20,079 | **Entry tagged with ^VIX level at trade date** | **175 tickers (147 stocks + 30 ETFs, ALTR excluded)**
**CSV:** `research/csp_cc_vix_bucket_analysis.csv` (summary) | `research/csp_cc_vix_bucket_per_ticker.csv` (per-ticker)

### Summary by VIX Regime

| Bucket | Trades | Total PnL | Win% | Avg$/Trade | % of Trades |
|---|---|---|---|---|---|
| VIX <15 | 5,522 | +$1,675.09 | 60.9% | $0.303 | 27.5% |
| VIX 15-20 | 5,581 | +$1,695.37 | 60.7% | $0.304 | 27.8% |
| VIX 20-25 | 4,264 | +$661.49 | 60.4% | $0.155 | 21.2% |
| VIX 25-30 | 1,789 | +$489.90 | 66.8% | $0.274 | 8.9% |
| VIX >30 | 1,402 | +$537.85 | 69.2% | $0.384 | 7.0% |
| **Total** | **20,079** | **+$4,314.15** | **61.5%** | **$0.215** | |

### Key Patterns

1. **Win rate rises with VIX** (60.9% → 69.2%) — but VIX 20-25 is the outlier (win rate high, avg$/trade low)
2. **VIX 20-25 is the quality dead zone** — avg PnL/trade drops to $0.155 vs $0.303-0.384 for other buckets. Volume is high but edge is weak.
3. **VIX 15-20 is the sweet spot** — high volume (27.8%) AND solid avg PnL ($0.304/trade). Best absolute dollar bucket (+$1,695.37).
4. **VIX >30 is highest quality** — 69.2% win rate, $0.384/trade, but only 7.0% of trade opportunities.
5. **VIX <20 generates 55% of all trades** and ~$3,370 of total PnL — strategy is primarily a low-vol regime play.

### Actionable VIX Filters to Test
- **Skip VIX 20-25:** Cut 21.2% of trades, save ~$3,653 of $4,314 total PnL (84.7% retention at 78.8% trade count).
- **VIX <20 only:** Liquid, high-frequency regime — captures the bulk of opportunity with solid per-trade quality.
- **VIX >25 size-up mode:** Win rate jumps to 66-69%. Scale notional when VIX >25.
- **VIX >30 premium:** Consider wider strikes / larger notional — 69.2% win rate, $0.384/trade average.

### Notable Per-Ticker VIX Patterns
- **ARWR:** Dominates at VIX <15 (+$1,328) and VIX 15-20 (+$992). Avoid VIX >25 (signal quality degrades).
- **GTLS:** Best bucket is VIX 25-30 (+$97). One of few names that thrives in elevated vol.
- **INTU:** Reverses — loses at VIX <15, best at VIX 25-30 (+$54). High-vol regime name.
- **TSLA/BA/MDGL/RMBS/CRWD:** Consistent losers across all VIX buckets — avoid in all regimes.
- **LLY:** Extreme variance by VIX — loses $136 at VIX <15, gains $114 at VIX 20-25. Regime-sensitive biotech..
