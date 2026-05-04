# Deal Flow Scouts

Scouts are broad-net discovery mechanisms that write signals to AKG on a schedule.
They are **not** in the per-ticker analysis pipeline — they run independently.

## Active Scouts

### X Feed Discovery Scout (`x_feed_scout.py`)

**What it does:** Single xAI `x_search` call discovers trending US equity tickers,
sentiment, and active macro themes from financial X in the last 24 hours.

**Writes to AKG:**
- Ticker nodes: `enrich_node_cashtag()` → `cashtag_velocity_z`, `cashtag_sentiment`,
  `cashtag_mentions_7d`, `cashtag_velocity_trend` (drives emergence tier progression)
- Audit fields: `x_trending_at`, `x_trending_mentions`, `x_trending_context`
- Theme nodes: `activate_theme()` / `deactivate_theme()` with conviction + reasoning
- Sector nodes: `activate_sector()` with theme linkage
- Sentiment reversals: `x_sentiment_reversal_from/to/catalyst/at` for tickers where
  X sentiment sharply flipped direction in last 48 hours
- Dormant-sector outliers: flags high-velocity companies in inactive sectors

**Cost per run:** ~$0.005 (1 xAI x_search call)
**Schedule:** Every 4-8 hours
**CLI:** `aeternus x-discover [--dry-run]`
**API key:** `XAI_API_KEY`

---

### Commodity Shock Scout (`commodity_shock_scout.py`)

**What it does:** Scans 5 geopolitical clusters (Oil Disruption, Tech Conflict,
Agriculture Squeeze, Defense Buildup, Safe Haven Flight) for unusual volume/price
activity signaling institutional pre-positioning before commodity shocks or conflicts.

**Writes to AKG:** `set_causal_event()` — event type `COMMODITY_SHOCK`, keyed as
`CS_<cluster>_<date>` (e.g., `CS_OIL_DISRUPTION_2026-03-02`).

**Cost per run:** $0.00 (yfinance batch download, ~30 tickers)
**Schedule:** Daily
**CLI:** `aeternus commodity-scan`
**API key:** None required

---

### DoD Contract Scout (`dod_contract_scout.py`)

**What it does:** Reads USASpending.gov public API for defense contract award spikes
across 4 sectors (Munitions, Fuel Supply, Medical Forward, Engineering Base).
Detects spending buildup 4-8 weeks before operations become public.

**Writes to AKG:** `set_causal_event()` — event type `COMMODITY_SHOCK`, keyed as
`DOD_<sector>_<date>` (e.g., `DOD_MUNITIONS_2026-03-02`).

**Cost per run:** $0.00 (8 API calls to public USASpending.gov, no auth)
**Schedule:** Daily
**CLI:** `aeternus dod-scan`
**API key:** None required

---

### Breakout Scanner (`breakout_scanner.py`)

**Role:** Discovery engine — NOT a signal connector.

**Thesis:** Catch stocks breaking out in silence (no social buzz, no analyst coverage,
no news catalyst) and advance them through AKG emergence tiers. The goal is to never
miss the next MU, SNDK, or AXTI — stocks making 52-week highs with elevated volume
before anyone is talking about them. We don't invest immediately; we advance the node
from DARK → ATMOSPHERE → HABITABLE and let the full 5-pillar pipeline do its work
once the stock reaches sufficient emergence tier.

**What it does:** Scans AKG universe (company nodes with centrality >= 0.05 plus all
base universe symbols). Filters by ADV >= $5M. Qualifying breakouts (score >= 50,
near_high >= 0.95) are written to AKG via `enrich_node_breakout()`.

**Writes to AKG:** YES — `enrich_node_breakout()` advances emergence tier:
- score >= 85 + vol_ratio >= 2.0 → HABITABLE
- score >= 70 + vol_ratio >= 1.5 → ATMOSPHERE
- any breakout detected → ROCKY (exits DARK)

**OHLCV cache:** `eval_results/deal_flow/breakout_ohlcv.json` — incremental (first run:
380d history; subsequent runs: append new bars only, cap at 252 bars).

**Returns:** List of discovered symbols (logging only). No DealFlowSignal objects.

**Cost per run:** $0.00 (yfinance)
**Schedule:** Once per pipeline run, before connector phase
**API key:** None

---

### IV Scanner (`iv_scanner.py`)

**What it does:** Scans ~100 S&P 500 / NASDAQ 100 tickers for upcoming earnings
(7-14 days out). Computes ATM straddle implied move vs 8-quarter historical
surprise magnitude. Flags IV underpriced (force_queue) and overpriced (covered call).

**Writes to AKG:** No — returns advisory dict for portfolio management.

**Cost per run:** $0.00 (yfinance per-ticker option chain lookups)
**Schedule:** On-demand
**CLI:** `aeternus iv-scan`
**API key:** None required

---

### Technical Ignition Scout (`technical_ignition_scout.py`)

**Role:** Discovery engine — NOT a signal connector.

**What it does:** Reads the cached `KAMA + bullish FVG regime` state from
`eval_results/control/technical_signal_cache.db` and flags names currently in
`BUY_TRIGGER` or `BUY_ZONE`. Fresh setups are promoted into the filtered universe
during `discover()`. `TREND_UP_NOT_FRESH` names are kept as audit-only context.

**Writes to AKG:** No direct AKG writes in v1.

**Writes to discovery artifacts:** YES — promoted names are persisted through:
- `scout_audit.json`
- `discovery_delta.json`
- `universe_filter.json`

**Cost per run:** $0.00 (cache read only)
**Schedule:** Once per pipeline run, before universe build
**API key:** None

---

## Deleted Scouts (superseded)

| Scout | Reason | Superseded By |
|---|---|---|
| `cashtag_enricher.py` | 3 blockers, $0.25/run, never ran | X Feed Scout ($0.005/run) |
| `theme_scanner.py` | Wrong API, wrong model, backwards architecture | X Feed Scout (same call) |
| `sector_scout.py` | Expensive per-sector calls, redundant | Outlier detection extracted into X Feed Scout |

## Cost Summary

| Scout | Cost/run | Frequency | Est. daily cost |
|---|---|---|---|
| X Feed Scout | $0.005 | 3-6×/day | $0.015-0.03 |
| Commodity Shock | $0.00 | 1×/day | $0.00 |
| DoD Contract | $0.00 | 1×/day | $0.00 |
| Breakout Scanner | $0.00 | per pipeline run | $0.00 |
| IV Scanner | $0.00 | on-demand | $0.00 |
| **Total** | | | **~$0.03/day** |
