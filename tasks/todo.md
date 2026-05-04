# Insider Alpha Score — S-059 to S-062

## Why

Our finviz_connector (S-058) scores all CEO insider buys at 78.0 identically.
A CEO buying COIN (100% historical win rate) is not the same signal as a CEO buying a company where insider buys are chronically wrong. The Alpha Score fixes this by computing per-ticker insider predictiveness from 5 years of Form 4 history. Cluster buy detection (multiple insiders buying within 14 days) adds a second dimension.

## Data Sources (all free)

- EDGAR Form 4 XML — reuse `_parse_form4_transactions` from `sec_catalyst.py`
- EDGAR submissions API — CIK lookup + filing history (5 years)
- yfinance — forward return prices (5d, 10d, 20d, 30d after each buy)
- AKG — persistent store for computed Alpha Scores (30-day TTL)

---

## S-059: Backtest Script (Sonnet, 1 file)

### File: `scripts/backtest_insider_alpha.py`

Standalone research script. No production code modified.

**What it does:**
1. Load S&P 500 tickers from yfinance or local CSV
2. For each ticker: fetch company CIK from EDGAR company_tickers.json
3. Fetch all Form 4 filings over last 5 years via EDGAR submissions endpoint
4. Reuse `_parse_form4_transactions()` from sec_catalyst.py to extract open-market purchases
5. For each purchase: get date + price, then fetch yfinance forward prices at 5d/10d/20d/30d
6. Compute per-ticker stats:
   - `buy_count` — total open-market purchases in 5-year window
   - `total_value_usd` — sum of all purchase values
   - `win_rate_30d` — % of buys where 30d forward return > 0
   - `avg_fwd_return_30d` — mean 30d forward return across all buys

**Alpha Score formula (0–100):**
- Minimum 5 buys required to qualify; else alpha_score = 50 (no-data default)
- `win_rate_score` = win_rate_30d × 100
- `return_score` = clamp(avg_fwd_return_30d / 0.10 × 100, 0, 100) — 10% avg return = 100
- `frequency_score` = clamp(buy_count / 20 × 100, 0, 100) — 20 buys = 100
- `value_score` = clamp(log10(total_value_usd) / log10(1e9) × 100, 0, 100) — $1B = 100
- `alpha_score` = 0.40 × win_rate_score + 0.30 × return_score + 0.20 × frequency_score + 0.10 × value_score

**Output:**
- `eval_results/insider_alpha_scores.json` — dict of ticker → {alpha_score, win_rate_30d, avg_fwd_return_30d, buy_count, total_value_usd, computed_date}
- `eval_results/insider_alpha_scores.csv` — same data, sortable
- Print top 20 by alpha_score and top 20 by win_rate to console

**Rate limiting:** 0.15s sleep between EDGAR requests. Respect 10 req/s limit.

**Success criteria:**
- Runs end-to-end without crashing
- Produces scores for ≥100 tickers
- Top results match known high-conviction names (energy sector expected to rank well)

---

## S-060: AKG Insider Alpha Fields (Sonnet, 1 file)

### File: `tradingagents/graph/knowledge_graph.py`

Add two methods following the existing `set_perplexity_enrichment / get_perplexity_enrichment` pattern (lines ~1360–1368).

**`set_insider_alpha(ticker, data)`**
```python
def set_insider_alpha(self, ticker: str, data: dict) -> None:
    """Store insider Alpha Score for a ticker. data keys:
    alpha_score, win_rate_30d, avg_fwd_return_30d, buy_count,
    total_value_usd, computed_date (ISO string)
    """
```
- Writes to node attributes under `insider_alpha` key
- Sets `insider_alpha_computed_date` = today

**`get_insider_alpha(ticker, ttl_days=30)`**
```python
def get_insider_alpha(self, ticker: str, ttl_days: int = 30) -> dict | None:
    """Returns insider alpha data if fresh, else None."""
```
- Returns None if node doesn't exist, field missing, or older than ttl_days
- Returns full data dict if fresh

**Success criteria:**
- `set_insider_alpha("COIN", {...})` followed by `get_insider_alpha("COIN")` returns the data
- `get_insider_alpha` returns None after TTL expires (mock date test)

---

## S-061: finviz_connector Augmentation (Sonnet, 1 file)

### File: `tradingagents/dealflow/sources/finviz_connector.py`

Two changes to `collect_finviz_insider_signals`:

**1. Alpha Score modulation**

After determining base_score (78.0 CEO, 62.0 other), look up AKG alpha:
```python
# Try AKG alpha score lookup
alpha_data = None
try:
    from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
    akg = AeternusKnowledgeGraph()
    alpha_data = akg.get_insider_alpha(symbol)
except Exception:
    pass

if alpha_data:
    alpha_score = float(alpha_data.get("alpha_score", 50.0))
    raw_score = base_score * 0.60 + alpha_score * 0.40
    raw_score = max(40.0, min(95.0, raw_score))
else:
    raw_score = base_score
```

**2. Cluster buy detection**

Before looping over universe symbols, compute cluster map from the full insider DataFrame:
```python
def _detect_clusters(insider_df, as_of, lookback_days=14):
    """Return dict: ticker → distinct_buyer_count within lookback window."""
```
- Filter to last `lookback_days` days, Buy only
- Group by Ticker, count distinct Owner values
- Return {ticker: count}

In the signal builder:
```python
cluster_count = cluster_map.get(symbol, 0)
if cluster_count >= 3:
    raw_score = min(95.0, raw_score + 15.0)
    direction = "BULLISH"
elif cluster_count == 2:
    raw_score = min(95.0, raw_score + 8.0)
```

Add `cluster_buy_count` to signal metadata (evidence_count += cluster_count).

**Success criteria:**
- Ticker with alpha_score=90 + CEO buy → raw_score ≈ 89 (78×0.6 + 90×0.4)
- Ticker with alpha_score=30 + CEO buy → raw_score ≈ 59 (78×0.6 + 30×0.4), clamped to 40 floor
- No AKG data → raw_score = base_score unchanged
- 3-insider cluster → raw_score += 15, capped at 95

---

## S-062: Tests (Haiku, 1 file)

### File: `tests/test_insider_alpha_connector.py`

8 tests, all mocked:

1. Alpha score high (90) + CEO → raw_score = 78×0.6 + 90×0.4 = 82.8
2. Alpha score low (20) + CEO → clamped to 40.0 floor
3. No AKG data → raw_score = 78.0 unchanged
4. AKG lookup throws exception → raw_score = 78.0 (no crash)
5. Cluster of 2 distinct buyers → raw_score += 8
6. Cluster of 3+ distinct buyers → raw_score += 15, cap 95
7. Single buyer → no cluster bonus
8. Cluster detection outside lookback window → no cluster bonus

---

## Sequence

S-059 (backtest) → run it → produces `insider_alpha_scores.json`
S-060 (AKG fields) → can build in parallel with S-059
S-061 (connector) → needs S-060 done
S-062 (tests) → needs S-061 done

After S-059 runs: bulk-load scores into AKG using a one-time loader script (trivial loop, not a separate task).

## Status

- [x] S-059: Backtest script — complete. Outputs eval_results/insider_alpha_scores.json + .csv
- [x] S-060: AKG insider alpha fields — set_insider_alpha/get_insider_alpha, 30-day TTL, verified
- [x] S-061: finviz_connector augmentation — AKG modulation + cluster detection, 10 tests passing
- [x] S-062: Tests — 9 new tests, 19 total passing

---

# Capital Flows Research Integration — S-063 to S-065

## Why

Read 8 capitalflowsresearch.com PDFs. Key finding: Aeternus macro_engine had zero credit
spread data. Credit spreads are the PRIMARY leading indicator (widen 3-6mo before equity sell-offs).
Synthesis at docs/research/capital_flows/SYNTHESIS.md.

## Completed (2026-02-28)

- [x] Moved all 8 PDFs to docs/research/capital_flows/
- [x] Added HYG + LQD to macro_engine _TICKERS (credit spread proxies)
- [x] Computed hyg_vs_tlt, lqd_vs_tlt, credit_spread_regime, real_rate indicators
- [x] Updated monetary_stress weights to include credit spread signal (0.15 weight)
- [x] Added credit_spreads_widening regime trigger in _classify_regime
- [x] Updated macro_reviewer prompt: added Capital Flows dimension 7 (credit spread + risk curve)
- [x] 47 macro_engine tests pass, import clean

## S-063: Yield Curve Shape Classification (Sonnet, 1 file)

### File: `tradingagents/agents/utils/macro_engine.py`

**What it does:**
Classify yield curve into 5 shapes using DGS2 + DGS10 rate-of-change over 30 days.

**Current state:** Only latest-point DGS2/DGS10 fetched. No shape classification.

**Changes to `_try_fetch_fred()`:**
- Fetch last 30 observations for both DGS2 and DGS10 (change `limit=1` to `limit=30`)
- Compute `dgs2_30d_change = dgs2_latest - dgs2_30d_ago`
- Compute `dgs10_30d_change = dgs10_latest - dgs10_30d_ago`

**`_classify_yield_curve_shape(dgs2_change, dgs10_change)` → str:**
```
Bull Steepening:  dgs2 falling (< -0.15), dgs10 rising or stable   → recovery
Bear Steepening:  both rising, dgs10 rises faster (dgs10 > dgs2)    → inflation/fiscal fear
Bull Flattening:  both falling, dgs2 falls faster (dgs2 < dgs10)    → recession/risk-off
Bear Flattening:  both rising, dgs2 rises faster (dgs2 > dgs10)     → tightening
Flat/Stable:      |both changes| < 0.10                              → no strong signal
```

**Output:** Add `yield_curve_shape` to indicators dict and `_FRED_CACHE` result.

**Sector adjustments in `_compute_rate_headwind()`:**
- Bull Steepening: Financials +8, Growth +3 (recovery signal)
- Bear Steepening: Energy/Materials +5, Tech -8 (inflation, avoid duration)
- Bull Flattening: Defensives +5, Tech -3 (recession = avoid cyclicals)
- Bear Flattening: Financials -5, Short duration preferred

**Success criteria:**
- `yield_curve_shape` field present in snapshot dict
- Sector adjustments fire correctly for each shape
- Existing 47 tests still pass + 5 new yield_curve_shape tests

---

## S-064: Inflation Phase + Real Rate + TIPS Breakeven (Sonnet, 1 file)

### File: `tradingagents/agents/utils/macro_engine.py`

**What it does:**
1. Classify inflation into 5 phases using CPI trend (already have 13 observations)
2. Surface real_rate (dgs10 - cpi_yoy) as a scored signal for growth stocks + crypto
3. Add TIPS breakeven via FRED DFII10 (10Y TIPS yield) if available

**Inflation phase detection (from existing 13 CPI observations):**
- Compare CPI YoY now vs 3-months-ago (observations[0] vs observations[3])
- Phase = Emergence: CPI 2-4% AND rising
- Phase = Acceleration: CPI > 4% AND rising
- Phase = Peak: CPI > 4% AND falling
- Phase = Moderation: CPI 2-4% AND falling
- Phase = Disinflation: CPI < 2%

**Sector score adjustments by phase (in `_compute_regime_fit`):**
- Emergence: Energy/Materials +6, Tech/Growth -3
- Acceleration: Hard assets +8, Tech/Growth -8
- Peak: Defensives/Utilities +5, Energy -3
- Moderation: Balanced (no adjustment)
- Disinflation: Tech/Growth +8, Energy/Materials -5

**Real rate signal (already computed as indicators["real_rate"]):**
- Real rate > 3%: Growth/Tech/Crypto additional -8 in rate_headwind
- Real rate 1-3%: -3 penalty
- Real rate < 0%: Growth/Crypto +5 bonus (negative real rates = asset inflation)

**DFII10 FRED fetch (optional, same pattern as DGS10):**
```
breakeven_inflation = dgs10 - dfii10
```
Add to indicators dict. Use in macro_reviewer prompt alongside real_rate.

**Success criteria:**
- `inflation_phase` field present in snapshot
- `breakeven_inflation` present when FRED key available
- Phase-based sector adjustments work correctly
- All existing tests pass + 6 new inflation_phase tests

---

## S-065: Market Breadth via RSP (Haiku, 1 file)

### File: `tradingagents/agents/utils/macro_engine.py`

Add RSP (Invesco S&P 500 Equal Weight ETF) to _TICKERS.
Compute `spy_vs_rsp_20d` = SPY 20d return - RSP 20d return.
- Positive: cap-weighted outperforming equal-weight = narrow breadth = concentration risk
- Negative: equal-weight outperforming = broad rally = healthier

Add to indicators dict as `market_breadth_signal`.
When spy_vs_rsp_20d > 0.03 (narrow breadth), reduce regime_fit by 5 points (fragile rally).
Add regime trigger `narrow_breadth` when threshold exceeded.

**Success criteria:**
- `market_breadth_signal` in snapshot
- Narrow breadth trigger fires correctly
- All existing tests pass

## Sequence

S-063 and S-064 can be built in parallel (both modify macro_engine.py — assign one to Sonnet, the other to a separate worktree).
S-065 is tiny — Haiku.

## Status

- [ ] S-063: Yield curve shape — pending
- [ ] S-064: Inflation phase + real rate + TIPS — pending
- [ ] S-065: Market breadth (RSP) — pending
