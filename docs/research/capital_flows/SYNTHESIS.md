# Capital Flows Research — Synthesis & Aeternus Implementation Map

Source: 8 PDFs from capitalflowsresearch.com, read 2026-02-28.

---

## Executive Summary

The Capital Flows framework treats macro regime detection as a **capital rotation problem**: money flows from safe assets (bills → bonds → IG credit → HY credit → equities → alts → crypto) and back when confidence reverses. Credit spreads are the PRIMARY leading indicator — they widen 3–6 months before equity sell-offs. The current Aeternus macro_engine has NO credit spread data. This is the biggest gap.

---

## Framework Map: 8 PDFs → Current State → Gaps

### 1. Beyond the Credit Cycle (Asset-Liability Macro Primer)

**Core insight:** Balance sheet STRUCTURE matters more than cycle phase. Duration mismatch + refinancing risk creates non-linear crises. Yield curve SHAPE (not just level) determines who is stressed.

**Yield curve shapes:**
- Bull steepening (long rates rise, short rates fall): recovery, risk-on → Financials lead
- Bear steepening (both rise, long faster): inflation/fiscal fear → Commodities, short duration
- Bull flattening (both fall, short faster): risk-off, recession → Defensives, bonds
- Bear flattening (both rise, short faster): tightening, inversion approaching → Sell duration

**Current Aeternus state:**
- DGS10 and DGS2 fetched as single-point FRED observations
- 2s10s spread classified as inverted/not-inverted flag only
- No shape classification (direction of change for each leg is not computed)

**Gap (S-063):** Fetch 30-point FRED history for DGS2 and DGS10, compute 30d rate-of-change for each leg, classify yield curve shape. Add `yield_curve_shape` to macro_engine indicators and regime triggers.

---

### 2. Macroeconomic Framework of Capital Flows (Comprehensive Playbook)

**Core insight:** The risk curve is the organizing principle. Capital flows from safe to risky assets (risk-on) and reverses (risk-off). The position of capital on the risk curve tells you current regime confidence.

**Risk curve:** Bills → Short Bonds → Long Bonds → IG Credit → HY Credit → Equities → Alts → Crypto (Bitcoin at far end)

**Key signals:**
- IG spreads tightening + HY spreads tightening = risk-on capital flowing outward
- HY spreads widening (leading equities by weeks) = risk-off incoming
- Credit spreads are the FASTEST and most reliable leading indicator

**Current Aeternus state:**
- No credit spread data. monetary_stress uses gold/BTC/USD as stress proxy
- TLT trend used as rate proxy only (not credit risk proxy)

**Gap (IMPLEMENTED):** Add HYG (high yield) and LQD (investment grade) to macro_engine. Compute `hyg_vs_tlt` (HY credit spread direction) and `lqd_vs_tlt` (IG spread direction) as primary credit stress signals. These are the missing link between rate regimes and equity outcomes.

---

### 3. Inflationary Cycle Playbook

**Core insight:** Inflation is not binary. There are 5 phases with different asset class winners:

| Phase | CPI Signal | Winners | Losers |
|-------|-----------|---------|--------|
| Emergence | CPI rising 2–4% | Commodities, Energy, REITs | Bonds, Utilities |
| Acceleration | CPI > 4%, rising | Hard assets, commodities, TIPS | Growth, Long duration |
| Peak | CPI declining from >4% | Defensives, Quality, TIPS | Energy (demand fears) |
| Moderation | CPI 2–4%, falling | Balanced equity, IG bonds | Short-duration only |
| Full Disinflation | CPI < 2% | Growth, Tech, Long duration | Energy, commodities |

**Current Aeternus state:**
- Binary INFLATION_SHOCK regime (CPI ≥ 4.0%)
- 13 CPI observations already fetched from FRED (enough for trend direction)
- Missing: trend direction (is CPI accelerating or decelerating from current level?)

**Gap (S-064):** Compute CPI 3-month trend (compare current vs 3-months-ago CPI YoY). Classify into 5 inflation phases. Add `inflation_phase` to indicators. Adjust sector scores by phase (e.g., Energy: +8 in Emergence/Acceleration, -5 in Peak; Tech: +8 in Disinflation, -8 in Acceleration).

---

### 4. Building a Falsifiable Investment Thesis

**Core insight:** A good investment thesis has explicit falsification triggers. Without them, confirmation bias dominates. The 9-step checklist forces the analyst to name exactly what would make them wrong.

**9-step thesis structure:**
1. State the thesis in one sentence
2. Identify the causal mechanism
3. Identify the primary variable to watch
4. State the time horizon
5. Set the price target and entry/exit
6. Name 3 scenarios that would invalidate the thesis
7. Name 3 scenarios that would confirm it
8. State what market consensus misses
9. Describe the edge

**Current Aeternus state:**
- macro_reviewer uses Dalio Big Cycle framework (6 dimensions, solid)
- No explicit falsification trigger structure in any analyst prompt
- Researcher debate (bull vs bear) has some of this implicitly but not structured

**Gap (Prompt):** Add dimension 7 to macro_reviewer prompt: "Capital Flows Falsification — Name the single data point that, if it appeared, would invalidate the macro thesis for this ticker. Is credit spread tightening or widening? Does the current yield curve shape confirm or deny the thesis?" This forces explicit falsification into the LLM analysis.

---

### 5. Consumer Macroeconomic Playbook

**Core insight:** The consumer (60–70% of GDP) transmits macro shocks via the Debt Service Ratio (DSR). When DSR rises (high debt + high rates), consumer spending contracts → recession. PCE is the leading macro indicator.

**5-regime consumer matrix:**
- High Growth / Low Inflation (Boom): risk-on, cyclicals, discretionary
- High Growth / High Inflation (Overheat): commodities, energy, short duration
- Low Growth / High Inflation (Stagflation): hardest regime — defensives, commodities, TIPS
- Low Growth / Low Inflation (Recession): bonds, defensives, gold
- Tight Liquidity (Credit Crunch): cash, short bills, NO credit risk

**Current Aeternus state:**
- macro_engine regime labels (BEAR, RISK_OFF, INFLATION_SHOCK, etc.) roughly map to these consumer regimes
- No DSR proxy or consumer spending signal

**Gap:** No new FRED call needed for now — the 5-regime matrix is already approximated by current regime classification. However, Consumer Discretionary (XLY) vs Consumer Staples (XLP) ratio could be added as a consumer confidence proxy via yfinance. Deferred — lower priority than credit spreads.

---

### 6. S&P 500 Macro Regime Playbook (GIP Framework)

**Core insight:** GIP (Growth + Inflation + Policy/Liquidity) are the three axes. Market breadth (SPX vs RSP equal-weight) reveals whether rallies are broad or narrow. Volatility structure (IV vs RV, term structure) reveals positioning fragility.

**Key signals:**
- RSP (equal-weight S&P 500) underperforming SPY = narrow breadth = fragile rally
- VIX term structure in backwardation (front > back) = fear elevated = risk-off positioning
- High options dispersion relative to correlation = idiosyncratic risk dominant (good for stock picking)

**Current Aeternus state:**
- SPY SMA200 and SMA20 as primary market regime signals
- VIX close as volatility signal
- No RSP comparison, no VIX term structure

**Gap (S-065):** Add RSP to ticker list. Compute SPY/RSP ratio 20d trend. When SPY strongly outperforms RSP (breadth narrowing), reduce regime_fit score — narrow breadth = fragile rally = elevated risk. Add `market_breadth` indicator.

---

### 7. U.S. Interest Rates Tactical Playbook

**Core insight:** Rates markets are driven by growth/inflation expectations, Fed policy (rate + QE/QT), and supply/demand dynamics (fiscal deficit forcing Treasury supply). The historical regime arc (1940s–2025) shows regimes can last 10–20 years.

**Key signals:**
- TIPS breakeven (10Y nominal - 10Y real) = inflation expectations
- Swap spread (interest rate swap - Treasury yield) = credit/liquidity risk in rates market
- Repo stress = dealer balance sheet constraints = market fragility
- Convexity hedging flows = when rates move suddenly, MBS hedgers force more selling → amplification

**Current Aeternus state:**
- TIPS not in ticker list (could proxy via TIP ETF via yfinance)
- No breakeven inflation computed (need DGS10 + DFII10 from FRED)

**Gap (S-064 extension):** Add FRED DFII10 (10Y TIPS yield) to FRED fetch. Compute breakeven = DGS10 - DFII10. Add `breakeven_inflation` to indicators. This is market-implied inflation vs CPI actual — divergence signals positioning shifts. Also: add `real_rate = dgs10 - cpi_yoy` as an immediate computable proxy.

---

### 8. Bitcoin as Macro Liquidity Release Valve

**Core insight:** Bitcoin has no intrinsic value — it's a liquidity release valve at the far end of the risk curve. Driven by real interest rates (falls when real rates rise) and central bank balance sheet expansion (global M2). BTC is a MACRO signal, not just a crypto asset.

**5-step Bitcoin strategic framework:**
1. Identify macro regime (Global M2 direction, real rates direction)
2. Gauge risk flows across risk curve (HY spreads, DXY direction)
3. Monitor BTC-specific flows (ETF inflows, futures OI, funding rates)
4. Lead/lag indicators (Nasdaq 100 as risk proxy, gold divergence)
5. Align trade strategy to macro phase

**Current Aeternus state:**
- BTC-USD 20d return used in monetary_stress (0.20 weight vs gold's 0.45)
- No real rate computation (though DGS10 and CPI YoY are both available)

**Gap (IMPLEMENTED via S-064):** Add `real_rate = dgs10 - cpi_yoy` to indicators. When real rates are rising (nominal up faster than inflation or inflation falling), BTC faces headwind. This improves the BTC sub-score interpretation in the macro_reviewer prompt.

---

## Implementation Completed Today (2026-02-28)

### macro_engine.py changes
- Added HYG, LQD to `_TICKERS` (two free yfinance ETFs)
- Computed `hyg_vs_tlt` (HY credit spread direction vs rate-free TLT)
- Computed `lqd_vs_tlt` (IG credit spread direction vs TLT)
- Added `credit_spread_regime` field: TIGHTENING / STABLE / WIDENING
- Updated `_compute_monetary_stress()` weights: gold_vs_spy 0.35, btc_vs_spy 0.15, usd_trend -0.25, silver_vs_gold 0.10, hyg_vs_tlt (credit stress) -0.15
- Added `real_rate` computation from existing DGS10 + CPI YoY

### macro_reviewer.py changes
- Added dimension 7: Capital Flows Credit Spread & Risk Curve Position
- Prompt now references: credit spread direction, yield curve shape context, risk curve capital rotation position, real rate level for BTC/growth stock interpretation

---

## Follow-on Task Specs

| Task | What | Source PDF | Priority |
|------|------|------------|----------|
| S-063 | Yield curve shape (5 shapes from DGS2/DGS10 30d trend) | Beyond Credit Cycle | HIGH |
| S-064 | Inflation phase (5 phases from CPI trend), TIPS breakeven, real rate | Inflationary Cycle Playbook | HIGH |
| S-065 | Market breadth via RSP vs SPY ratio | S&P 500 Regime Playbook | MEDIUM |
| S-066 | Consumer health proxy via XLY/XLP ratio | Consumer Macro Playbook | LOW |

---

## Mapping to Aeternus 5-Pillar Scorer

The Capital Flows frameworks map directly to the Macro pillar (20% weight):

| Capital Flows Signal | Aeternus Sub-score | Weight in Composite |
|---------------------|-------------------|---------------------|
| Credit spreads (HYG/LQD vs TLT) | monetary_stress | 25% of 20% = 5% |
| Yield curve shape | rate_headwind | 25% of 20% = 5% |
| Inflation phase | regime_fit | 25% of 20% = 5% |
| Commodity cycle (DBC) | commodity_cycle | 25% of 20% = 5% |

Together, the Capital Flows improvements touch all 4 macro sub-scores. Net effect: a more differentiated macro regime signal that leads equity outcomes by weeks rather than lagging them.
