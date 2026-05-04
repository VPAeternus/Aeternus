# Task S-033: Sector Scout

**Assignee:** Sonnet
**Status:** pending
**Branch:** feature/sonnet46 (branch from feature/opus46)
**Priority:** high

## Tier
sonnet

## Summary
Build a config-driven, parallel, sector-sweep deal flow connector that replaces manual alpha source monitoring by running one xAI x_search call per sector per day.

## Context

### Where This Lives
New file: `tradingagents/dealflow/sources/sector_scout.py`
Primary entry point: `collect_sector_scout_signals(universe, as_of_date, config) -> List[DealFlowSignal]`

This follows the exact same pattern as `tradingagents/dealflow/sources/cashtag_stream.py`. Read that file in full before writing a single line. Key patterns to replicate:
- `_is_scout_configured()` check gating the entire connector
- `OpenAI(base_url="https://api.x.ai/v1", api_key=XAI_API_KEY)` client instantiation
- `client.responses.create(model=..., tools=[{"type": "x_search"}], ...)` call signature
- `_parse_xai_search_response(content)` for text fallback parsing
- `_extract_json_payload(content)` for JSON extraction
- `_LLM_RATE_LIMITED` process-local guard for rate limiting
- `CASHTAG_RE = re.compile(r"\$([A-Za-z]{1,6})")` for ticker extraction
- Graceful degradation: if xAI not configured, return signals with `source_status="NOT_CONFIGURED"`

### Contract Types
Read `tradingagents/dealflow/contracts.py`. The `DealFlowSignal` TypedDict is the output. Note that `signal_family` is a `Literal` — you must add the new families to that union in `contracts.py`. Add: `"sector_scout"`, `"sec_8k_catalyst"`, `"insider_cluster"`, `"supply_chain_propagation"`.

### Pipeline Wiring
After implementation, wire into the pipeline:
1. `tradingagents/dealflow/sources/__init__.py` — add import + `__all__` entry
2. `tradingagents/dealflow/pipeline.py` — add `collect_sector_scout_signals` call in `run()`, same pattern as cashtag connector (try/except wrapper, connector_health tracking, signals fed into `score_candidates`)
3. `tradingagents/default_config.py` — add all sector scout config keys (see below)

### Config keys to add to DEFAULT_CONFIG in default_config.py
Add these alongside the existing `dealflow_*` keys:

```python
"sector_scout_enabled": os.getenv("SECTOR_SCOUT_ENABLED", "true").lower() == "true",
"sector_scout_model": os.getenv("SECTOR_SCOUT_MODEL", "grok-4-1-fast"),
"sector_scout_top_k_per_sector": int(os.getenv("SECTOR_SCOUT_TOP_K_PER_SECTOR", "5")),
"sector_scout_top_k_total": int(os.getenv("SECTOR_SCOUT_TOP_K_TOTAL", "20")),
"sector_scout_lookback_days": int(os.getenv("SECTOR_SCOUT_LOOKBACK_DAYS", "3")),
"sector_scout_min_mentions": int(os.getenv("SECTOR_SCOUT_MIN_MENTIONS", "1")),
"sector_scout_sectors": { ... },  # full sector config dict below
```

The `sector_scout_sectors` dict is NOT env-var overridable (it's structured data). It should be a plain Python dict hardcoded in default_config.py.

## Requirements

### 1. Sector Configuration Dict

Add `sector_scout_sectors` to `DEFAULT_CONFIG` in `tradingagents/default_config.py`:

```python
"sector_scout_sectors": {
    "semis_ai_infrastructure": {
        "handles": ["SemiAnalysis", "patrickhmoorhead", "IanCutress", "chinahanddan", "moorheadresearch"],
        "themes": ["InP substrate", "HBM", "photonics", "silicon photonics", "advanced packaging",
                   "AI CapEx", "neocloud", "TSMC", "CoWoS", "glass substrate", "OSAT", "HBM3E"],
        "top_k": 5,
        # Sources: SemiAnalysis newsletter (Dylan Patel), IEEE Spectrum, SEMI.org equipment data, TSMC earnings transcripts
    },
    "biotech_pharma": {
        "handles": ["adamfeuerstein", "matthewherper", "JohnCarrollNews", "BrittanyMeiling", "medcitynews"],
        "themes": ["PDUFA", "FDA approval", "Phase 3 readout", "IND filing", "NDA submission",
                   "clinical catalyst", "accelerated approval", "breakthrough designation", "BLA"],
        "top_k": 5,
        # Sources: STAT News (statnews.com), Endpoints News (endpts.com), FDA PDUFA calendar (public)
    },
    "macro_rates": {
        "handles": ["NickTimiraos", "JeffSnider_AIP", "LukeGromen", "AndreasSteno", "GregDaco"],
        "themes": ["Fed pivot", "yield curve inversion", "credit spreads", "Eurodollar", "repo market",
                   "dollar milkshake", "liquidity cycle", "rate regime", "QT", "SOFR", "Treasury auction"],
        "top_k": 5,
        # Sources: FRED (already integrated), CME FedWatch, BIS quarterly review, WSJ Fed coverage
    },
    "defense_aerospace": {
        "handles": ["TheWarZone", "BreakingDefense", "DefenseOne", "natsecgeek", "SpaceNews"],
        "themes": ["DoD contract award", "NDAA", "hypersonic", "satellite constellation", "drone",
                   "rare earth", "ITAR", "export control", "Space Force", "C2ISR"],
        "top_k": 5,
        # Sources: USASpending.gov API (free, real contract awards), SAM.gov, Breaking Defense
    },
    "energy_power": {
        "handles": ["heatmap_news", "Jesse_Jenkins", "canarymedianews", "BloombergNEF", "EIAgov"],
        "themes": ["AI power demand", "nuclear SMR", "grid interconnection", "long-duration storage",
                   "LNG export", "FERC filing", "capacity market", "hyperscaler power", "data center load"],
        "top_k": 5,
        # Sources: EIA weekly data (free API), FERC.gov filings (free), Princeton ZERO Lab
    },
    "materials_critical_minerals": {
        "handles": ["RareEarthExchange", "MineMagazine", "SPGlobalMining", "CriticalMinerals_"],
        "themes": ["rare earth", "lithium", "cobalt", "InP", "gallium", "germanium",
                   "export restriction", "China mining", "critical mineral stockpile", "DPA Title III"],
        "top_k": 5,
        # Sources: USGS Minerals Information (free), Critical Minerals Alliance, S&P Global Commodity Insights
    },
    "china_geopolitics": {
        "handles": ["TechNodeChina", "jordanschnyc", "MacroPolo_gg", "sgourley", "CSIS"],
        "themes": ["chip export ban", "BIS entity list", "CATL", "Huawei", "PLA procurement",
                   "Taiwan strait", "CFIUS review", "supply chain decoupling", "EAR99", "CCL"],
        "top_k": 5,
        # Sources: CSIS (csis.org), Rhodium Group, TechNode (technode.com), China Law Translate
    },
    "fintech_banking": {
        "handles": ["nic__carter", "FrancesCoppola", "FinancialReg", "PaymentsNerd", "AmericanBanker"],
        "themes": ["bank charter", "CFPB rule", "payment rails", "stablecoin legislation",
                   "open banking", "core banking replacement", "credit card routing", "OCC guidance"],
        "top_k": 5,
        # Sources: OCC filings, Federal Register regulatory announcements, American Banker
    },
},
```

### 2. Core Module: sector_scout.py

Implement `tradingagents/dealflow/sources/sector_scout.py` with these public functions:

**`collect_sector_scout_signals(universe, as_of_date, config) -> List[DealFlowSignal]`**
Main entry point. Called by pipeline.py. Follows the same signature convention as `collect_cashtag_signals`.

Logic:
1. Check `config.get("sector_scout_enabled", True)` and `_is_scout_configured()`. If either is False, return signals with `source_status="NOT_CONFIGURED"`.
2. Load `sector_scout_sectors` from config.
3. Run `_run_sector_sweeps(sectors, as_of_date, config)` — parallel execution.
4. Aggregate results with `_aggregate_cross_sector(sector_results, config)`.
5. Convert to `DealFlowSignal` list and return.

**`_run_sector_sweeps(sectors: dict, as_of_date: str, config: dict) -> Dict[str, List[SectorHit]]`**
Runs one xAI call per sector in a `ThreadPoolExecutor`. Returns dict of `{sector_name: [SectorHit, ...]}`.
- Max workers = min(len(sectors), 8) to avoid hammering the API
- Each sector call: `_sweep_one_sector(sector_name, sector_cfg, as_of_date, config)`
- If a sector call raises, log it and return `[]` for that sector (never propagate exceptions)

**`_sweep_one_sector(sector_name, sector_cfg, as_of_date, config) -> List[SectorHit]`**
Builds prompt, calls xAI, parses response. Returns list of `SectorHit` dicts.

Prompt construction:
```python
handles_str = ", ".join(f"@{h}" for h in sector_cfg["handles"])
themes_str = ", ".join(sector_cfg["themes"])
cutoff = (as_of - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

prompt = (
    f"Search X for investment analysis posts about these themes: {themes_str}. "
    f"Focus on posts from these accounts: {handles_str}. "
    f"Look back {lookback_days} days (since {cutoff}). "
    f"For each stock ticker mentioned, extract: the ticker symbol, sentiment (bullish/bearish/neutral), "
    f"which specific themes from the list were discussed, and which accounts mentioned it. "
    f"Return as JSON array: [{{\"ticker\": \"AXTI\", \"sentiment\": \"bullish\", "
    f"\"themes_matched\": [\"InP substrate\", \"photonics\"], \"source_accounts\": [\"SemiAnalysis\"], "
    f"\"conviction\": 0.85, \"summary\": \"one sentence catalyst\"}}]"
)
```

xAI call — exact same pattern as `_collect_scout_posts` in cashtag_stream.py:
```python
client = OpenAI(base_url="https://api.x.ai/v1", api_key=api_key)
response = client.responses.create(
    model=model,
    instructions="You are a financial sector intelligence analyst. Search X for investment signals. Return valid JSON only.",
    input=[{"role": "user", "content": prompt}],
    tools=[{"type": "x_search"}],
    max_tool_calls=1,
    temperature=0.0,
    max_output_tokens=3000,
)
content = response.output_text or ""
```

**`SectorHit` internal dict schema:**
```python
# Not a TypedDict — just a regular dict used internally
{
    "ticker": str,           # extracted cashtag, uppercased
    "sector": str,           # sector_name this came from
    "sentiment": str,        # "bullish" | "bearish" | "neutral"
    "sentiment_score": float, # +1.0, -1.0, or 0.0 from sentiment string
    "themes_matched": List[str],  # subset of sector themes that appeared
    "source_accounts": List[str],  # which monitored accounts mentioned it
    "conviction": float,     # 0-1 from xAI response, or computed fallback
    "summary": str,          # one-sentence catalyst description
}
```

Response parsing:
1. Use `_extract_json_payload(content)` (import the same helper or re-implement identically).
2. If JSON parse fails, use `CASHTAG_RE` to scan text content and build minimal SectorHit entries.
3. Validate each ticker with `SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,6}$")`.
4. Cap at `sector_cfg.get("top_k", 5)` hits per sector.

**`_aggregate_cross_sector(sector_results: Dict[str, List[SectorHit]], config: dict) -> List[SectorHit]`**
Groups by ticker, applies cross-sector multiplier, returns ranked final list.

Algorithm:
```python
# Group hits by ticker
by_ticker: Dict[str, List[SectorHit]] = defaultdict(list)
for sector_name, hits in sector_results.items():
    for hit in hits:
        by_ticker[hit["ticker"]].append(hit)

# Score each ticker
final_scores: List[Tuple[str, float, List[SectorHit]]] = []
for ticker, hits in by_ticker.items():
    sector_count = len(set(h["sector"] for h in hits))
    avg_conviction = sum(h["conviction"] for h in hits) / len(hits)
    # Cross-sector multiplier: each additional sector adds 30% weight
    cross_sector_mult = 1.0 + 0.3 * (sector_count - 1)
    final_score = avg_conviction * cross_sector_mult
    # Clamp to 1.0 max
    final_score = min(1.0, final_score)
    final_scores.append((ticker, final_score, hits))

# Sort descending, take top_k_total
final_scores.sort(key=lambda x: -x[1])
top_k_total = config.get("sector_scout_top_k_total", 20)
final_scores = final_scores[:top_k_total]
```

**Converting to DealFlowSignal:**
```python
{
    "symbol": ticker,
    "signal_family": "sector_scout",
    "raw_score": float(round(final_score * 100.0, 4)),  # 0-100 scale
    "z_score": 0.0,  # not computed at this stage
    "direction": _direction_from_sentiment(avg_sentiment),
    "evidence_count": len(all_hits_for_ticker),
    "freshness_hours": 0.0,  # sector scout is always "now"
    "source_status": "OK",
    "source_name": "sector_scout",
    # Extra fields for AKG integration (not in TypedDict, passed as pipeline metadata):
    # These are stored separately in metadata, not in DealFlowSignal itself
}
```

Also return a metadata dict `{ticker: {"sectors": [...], "themes_matched": [...], "source_accounts": [...]}}` as a second return value from `collect_sector_scout_signals` — callers that want it can unpack it.

### 3. contracts.py update

In `tradingagents/dealflow/contracts.py`, add the new signal families to the `DealFlowSignal.signal_family` Literal:
```python
"sector_scout",
"sec_8k_catalyst",
"insider_cluster",
"supply_chain_propagation",
```
These are needed by S-034 too — add all four now.

### 4. Pipeline wiring in pipeline.py

In `tradingagents/dealflow/pipeline.py`:
1. Add import: `from .sources import collect_sector_scout_signals`
2. In `run()`, after the cashtag connector block, add a sector scout block following the same try/except pattern:

```python
sector_scout_start = time.perf_counter()
sector_scout_error = ""
sector_scout_metadata: Dict[str, Any] = {}
try:
    sector_scout_signals, sector_scout_metadata = collect_sector_scout_signals(
        base_universe,
        as_of_date=as_of_date,
        config=self.config,
    )
except Exception as exc:
    sector_scout_error = str(exc)
    sector_scout_signals = []
connector_health.append({
    "connector": "sector_scout",
    "signals": len(sector_scout_signals),
    "elapsed_s": round(time.perf_counter() - sector_scout_start, 3),
    "error": sector_scout_error,
})
```

3. Feed `sector_scout_signals` into `score_candidates()` alongside other signals.

## Files to Touch
- `tradingagents/dealflow/sources/sector_scout.py` (new)
- `tradingagents/dealflow/sources/__init__.py` (add import)
- `tradingagents/dealflow/contracts.py` (add signal families to Literal)
- `tradingagents/dealflow/pipeline.py` (wire connector)
- `tradingagents/default_config.py` (add sector scout config)
- `tests/test_sector_scout.py` (new)

## Tests: tests/test_sector_scout.py

Write these test cases (no live API calls — all xAI calls mocked):

```python
# Test 1: _is_scout_configured returns False when XAI_API_KEY missing
def test_scout_not_configured_when_no_api_key(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    signals, _ = collect_sector_scout_signals([], config={})
    assert all(s["source_status"] == "NOT_CONFIGURED" for s in signals)

# Test 2: Single sector sweep parses xAI JSON response correctly
def test_sweep_one_sector_parses_json(monkeypatch):
    mock_response_content = json.dumps([
        {"ticker": "AXTI", "sentiment": "bullish", "themes_matched": ["InP substrate"],
         "source_accounts": ["SemiAnalysis"], "conviction": 0.9, "summary": "InP supply tightening"}
    ])
    # Mock OpenAI client
    # Assert SectorHit has ticker="AXTI", conviction=0.9

# Test 3: Multi-sector deduplication — same ticker in 2 sectors gets cross-sector multiplier
def test_cross_sector_multiplier():
    hits = {
        "semis_ai_infrastructure": [{"ticker": "NVDA", "conviction": 0.8, "sector": "semis_ai_infrastructure", ...}],
        "energy_power": [{"ticker": "NVDA", "conviction": 0.7, "sector": "energy_power", ...}],
    }
    result = _aggregate_cross_sector(hits, config={"sector_scout_top_k_total": 20})
    nvda = next(r for r in result if r["ticker"] == "NVDA")
    # With 2 sectors: mult = 1.3, avg_conviction = 0.75 → final = min(1.0, 0.975)
    assert nvda["conviction"] > 0.8  # must be higher than single-sector conviction

# Test 4: Single-sector ticker gets NO multiplier (cross_sector_mult = 1.0)
def test_single_sector_no_multiplier():
    hits = {"semis_ai_infrastructure": [{"ticker": "AXTI", "conviction": 0.85, "sector": "semis_ai_infrastructure", ...}]}
    result = _aggregate_cross_sector(hits, config={"sector_scout_top_k_total": 20})
    axti = next(r for r in result if r["ticker"] == "AXTI")
    assert abs(axti["conviction"] - 0.85) < 0.01  # unchanged

# Test 5: Invalid ticker symbols are filtered out
def test_invalid_tickers_filtered():
    # Response includes "N/A", "123INVALID", "$$$" — verify they are dropped

# Test 6: Fallback text parsing when JSON malformed
def test_fallback_text_parsing():
    content = "SemiAnalysis is very bullish on $AXTI due to InP demand\nAlso mentions $LITE"
    hits = _parse_sector_response_text(content, sector_name="semis_ai_infrastructure", sector_cfg={...})
    tickers = [h["ticker"] for h in hits]
    assert "AXTI" in tickers
    assert "LITE" in tickers

# Test 7: top_k_per_sector cap is respected
def test_top_k_per_sector_cap():
    # Mock response returning 10 tickers for one sector
    # Config: sector_scout_top_k_per_sector = 3
    # Assert only 3 hits returned for that sector

# Test 8: Rate limit flag prevents further calls
def test_rate_limit_flag_stops_calls():
    # Set _LLM_RATE_LIMITED = True, assert no API call is made

# Test 9: DealFlowSignal output conforms to schema
def test_output_conforms_to_signal_schema():
    signals, _ = collect_sector_scout_signals([], config={"sector_scout_enabled": False})
    # OR mock a full run and verify all required TypedDict keys are present

# Test 10: sector_scout_enabled=False returns NOT_CONFIGURED
def test_disabled_via_config():
    signals, _ = collect_sector_scout_signals([], config={"sector_scout_enabled": False})
    assert all(s["source_status"] == "NOT_CONFIGURED" for s in signals)
```

## Acceptance Criteria
- [ ] `collect_sector_scout_signals` runs without error when XAI_API_KEY is not set (returns NOT_CONFIGURED)
- [ ] All 8 sectors sweep in parallel (ThreadPoolExecutor, never sequential)
- [ ] Cross-sector ticker aggregation correctly boosts tickers appearing in 2+ sectors
- [ ] New signal families added to `DealFlowSignal` Literal in contracts.py
- [ ] Connector wired into pipeline.py with proper try/except health tracking
- [ ] All sector config in default_config.py with env-var overrides for scalar values
- [ ] 10 tests in `tests/test_sector_scout.py`, all passing
- [ ] All existing tests pass: `python -m pytest tests/ -v`
- [ ] Zero live API calls in tests (all mocked)

---

## Handoff
*Fill in when marking done. Opus reads this to parse completion without reading the implementation.*

**Work Done:** [files changed + one-line summary of what shipped]

**Learnings:** [anything surprising, a footgun hit, or a pattern worth capturing — or "none"]

**Follow-ups:** [new tasks this work reveals, if any — or "none"]
