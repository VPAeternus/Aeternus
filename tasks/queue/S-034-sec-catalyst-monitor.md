# Task S-034: SEC Catalyst Monitor

**Assignee:** Sonnet
**Status:** pending
**Branch:** feature/sonnet46 (branch from feature/opus46)
**Priority:** high

## Tier
sonnet

## Summary
Build a daily SEC EDGAR monitor that surfaces material 8-K filings and insider buy clusters as deal flow signals, hours before they propagate to social feeds, using only free public APIs (no key required).

## Context

### Where This Lives
New file: `tradingagents/dealflow/sources/sec_catalyst.py`
Primary entry point: `collect_sec_catalyst_signals(universe, as_of_date, config) -> List[DealFlowSignal]`

This is a pure HTTP connector — no xAI, no LLM. It calls EDGAR's free public APIs and returns structured signals. It follows the same structural pattern as existing connectors in `tradingagents/dealflow/sources/`. Read `tradingagents/dealflow/sources/smart_money.py` for the closest pattern (HTTP requests, no auth, daily-run cadence).

### Contract Types
Read `tradingagents/dealflow/contracts.py`. S-033 adds `"sec_8k_catalyst"`, `"insider_cluster"`, and `"supply_chain_propagation"` to the `DealFlowSignal.signal_family` Literal. This task depends on S-033 completing that change. If S-033 is not yet merged, add those signal families yourself.

### Existing Config
`tradingagents/default_config.py` already has:
```python
"dealflow_sec_user_agent": os.getenv("SEC_API_USER_AGENT", "AeternusAgentsAG/1.0 (research@aeternus.ai)"),
```
Use this exact user agent string for all EDGAR HTTP requests. EDGAR requires a valid user agent or returns 403.

### Pipeline Wiring
After implementation, wire into the pipeline:
1. `tradingagents/dealflow/sources/__init__.py` — add import + `__all__` entry
2. `tradingagents/dealflow/pipeline.py` — add `collect_sec_catalyst_signals` call in `run()`, same pattern as cashtag connector (try/except wrapper, connector_health tracking, signals fed into `score_candidates`)
3. `tradingagents/default_config.py` — add new config keys (see below)

## Requirements

### 1. New Config Keys in default_config.py

```python
"sec_catalyst_enabled": os.getenv("SEC_CATALYST_ENABLED", "true").lower() == "true",
"sec_catalyst_lookback_days": int(os.getenv("SEC_CATALYST_LOOKBACK_DAYS", "1")),
"sec_catalyst_8k_enabled": os.getenv("SEC_CATALYST_8K_ENABLED", "true").lower() == "true",
"sec_catalyst_insider_enabled": os.getenv("SEC_CATALYST_INSIDER_ENABLED", "true").lower() == "true",
"sec_catalyst_insider_cluster_min": int(os.getenv("SEC_CATALYST_INSIDER_CLUSTER_MIN", "3")),
"sec_catalyst_insider_cluster_days": int(os.getenv("SEC_CATALYST_INSIDER_CLUSTER_DAYS", "5")),
"sec_catalyst_insider_min_value_usd": float(os.getenv("SEC_CATALYST_INSIDER_MIN_VALUE_USD", "50000")),
"sec_catalyst_supply_chain_enabled": os.getenv("SEC_CATALYST_SUPPLY_CHAIN_ENABLED", "true").lower() == "true",
"sec_catalyst_request_delay_s": float(os.getenv("SEC_CATALYST_REQUEST_DELAY_S", "0.12")),
"sec_catalyst_timeout_s": float(os.getenv("SEC_CATALYST_TIMEOUT_S", "15.0")),
```

### 2. Supply Chain Map

Define `SUPPLY_CHAIN_MAP` as a module-level constant in `sec_catalyst.py`. This is a static directed graph: `{tier_1_ticker: [tier_2_tickers]}`. When a catalyst fires on a tier-1 name, auto-generate signals for its tier-2 dependents with reduced confidence.

```python
SUPPLY_CHAIN_MAP: Dict[str, List[str]] = {
    # NVDA ecosystem
    "NVDA": ["TSM", "AMKR", "ASX", "GLW", "COHR", "LITE", "MRVL", "AXTI", "SMCI"],
    # Hyperscaler AI spend → neoclouds and infra
    "MSFT": ["CRWV", "NBIS", "IREN", "TSSI", "DLR", "EQIX"],
    "GOOGL": ["CRWV", "AXTI", "LITE", "EQIX", "VRT"],
    "AMZN": ["CRWV", "NBIS", "TSSI", "DLR", "VRT"],
    "META": ["SMCI", "VRT", "EQIX", "NTAP"],
    # TSMC substrate/packaging suppliers
    "TSM": ["AXTI", "INTC", "GLW", "AMKR", "ASX"],
    # Memory → packaging
    "MU": ["AMKR", "ASX"],
    "SNDK": ["AMKR"],
    # Apple supply chain
    "AAPL": ["TSM", "QRVO", "SWKS", "COHU", "SMTC"],
    # Data center power/cooling
    "VRT": ["ACHR", "FUELC"],
    # Semiconductor equipment
    "AMAT": ["CCMP", "ENTG", "ICHR"],
    "LRCX": ["ENTG", "ICHR", "CCMP"],
    "KLAC": ["CCMP", "ENTG"],
    "ASML": ["ENTG", "CCMP", "TSM"],
    # EV battery supply chain
    "TSLA": ["LTHM", "ALB", "SQM", "PDCE", "MP"],
    "GM": ["LTHM", "ALB", "SQM"],
    "F": ["LTHM", "ALB"],
    # Defense prime contractors → component suppliers
    "LMT": ["KTOS", "AVAV", "HEI", "TDG"],
    "RTX": ["HEI", "TDG", "KTOS", "HEICO"],
    "NOC": ["KTOS", "HEI", "AVAV"],
    # Nuclear / SMR
    "BWXT": ["NNE", "LEU", "UUUU"],
    "OKLO": ["LEU", "UUUU"],
    # Critical minerals
    "MP": ["LYNAS", "USA"],
    # Biotech → CRO/CDMO
    "MRNA": ["CTLT", "CDMO", "BCRX"],
    "PFE": ["CTLT", "WCG", "CDMO"],
    # Cloud → storage
    "CRM": ["NOW", "MDB", "DDOG"],
    # LNG export
    "LNG": ["DNOW", "NESR"],
    # Fintech infrastructure
    "SQ": ["FLYW", "PAYC", "PCOR"],
    "PYPL": ["FLYW", "AFRM"],
    # Satellite / space
    "SPCE": ["RKLB", "ASTS"],
    "HII": ["RKLB", "KTOS"],
}
```

This is v0 — a hardcoded starting point. S-035 (Knowledge Graph) will make this dynamic. The `SUPPLY_CHAIN_MAP` here should be importable by S-035.

### 3. 8-K Material Event Monitor

**EDGAR Full-Text Search API — no key required:**
```
GET https://efts.sec.gov/LATEST/search-index?q="supply agreement"&dateRange=custom&startdt=YYYY-MM-DD&enddt=YYYY-MM-DD&forms=8-K
```

Headers required:
```python
{"User-Agent": config.get("dealflow_sec_user_agent", "AeternusAgentsAG/1.0 (research@aeternus.ai)")}
```

**Implement `_fetch_8k_signals(as_of_date, config) -> List[Dict]`:**

Step 1: Build search queries for high-signal 8-K item types. Run separate queries for different keyword clusters. The EDGAR full-text search supports boolean queries:

```python
MATERIAL_8K_QUERIES = [
    # Supply agreements and customer wins (Item 1.01)
    '"supply agreement" OR "supply contract" OR "purchase agreement" OR "strategic partnership"',
    # Executive changes with activist signal (Item 5.02)
    '"Chief Executive Officer" OR "Chief Financial Officer" OR "director appointment" OR "director resignation"',
    # Novel disclosures (Item 8.01)
    '"material event" OR "definitive agreement" OR "regulatory approval" OR "government contract"',
]
```

Step 2: For each query, call EDGAR:
```python
params = {
    "q": query,
    "dateRange": "custom",
    "startdt": start_date,  # as_of_date - lookback_days
    "enddt": as_of_date,
    "forms": "8-K",
    "_source": "filing_date,period_of_report,entity_name,file_num,period_of_report",
}
response = requests.get(
    "https://efts.sec.gov/LATEST/search-index",
    params=params,
    headers=headers,
    timeout=timeout_s,
)
```

Wait `config.get("sec_catalyst_request_delay_s", 0.12)` seconds between requests (EDGAR's politeness requirement is max 10/s).

Step 3: Parse EDGAR response. The search-index API returns:
```json
{
  "hits": {
    "hits": [
      {
        "_source": {
          "entity_name": "NVIDIA Corp",
          "file_num": "000-23985",
          "period_of_report": "2026-02-24",
          "form_type": "8-K"
        }
      }
    ]
  }
}
```

Step 4: Resolve entity name to ticker. Use a lightweight lookup:
- Try `entity_name.upper()` against `universe` symbols directly (name matching is imperfect but fast)
- Keep a small hardcoded mapping dict `EDGAR_NAME_TO_TICKER` for the top 50 most-filed companies:
```python
EDGAR_NAME_TO_TICKER = {
    "NVIDIA": "NVDA", "APPLE": "AAPL", "MICROSOFT": "MSFT", "ALPHABET": "GOOGL",
    "AMAZON": "AMZN", "META PLATFORMS": "META", "TESLA": "TSLA",
    "TAIWAN SEMICONDUCTOR": "TSM", "BROADCOM": "AVGO", "QUALCOMM": "QCOM",
    # ... add ~40 more common names
}
```
- If no match found, skip the filing.

Step 5: For matched tickers, build a signal:
```python
{
    "symbol": ticker,
    "signal_family": "sec_8k_catalyst",
    "raw_score": 75.0,  # 8-K is always high-signal; score tuned later by scorer
    "z_score": 0.0,
    "direction": "BULLISH",  # default; Item 5.02 CEO departure is BEARISH (override)
    "evidence_count": 1,
    "freshness_hours": hours_since_filing,
    "source_status": "OK",
    "source_name": "sec_catalyst",
}
```

CEO/director departure filings get `direction = "BEARISH"` and `raw_score = 60.0`. Supply agreement and customer win filings get `direction = "BULLISH"` and `raw_score = 85.0`.

### 4. Form 4 Insider Cluster Detector

**EDGAR submissions API:**
```
GET https://data.sec.gov/submissions/CIK{cik_padded}.json
```
(CIK must be zero-padded to 10 digits)

**Form 4 full-text search:**
```
GET https://efts.sec.gov/LATEST/search-index?forms=4&dateRange=custom&startdt=YYYY-MM-DD&enddt=YYYY-MM-DD
```

**Implement `_fetch_insider_cluster_signals(universe, as_of_date, config) -> List[Dict]`:**

Step 1: Query EDGAR for recent Form 4 filings:
```python
params = {
    "forms": "4",
    "dateRange": "custom",
    "startdt": start_date,
    "enddt": as_of_date,
}
```

Step 2: Parse response to extract:
- `entity_name` (issuer company name)
- `period_of_report` (transaction date)
- `file_num` (for CIK lookup)

Step 3: Extract transaction details from filing text. Form 4 is XML. Look for:
- `transactionCode = "P"` (open market purchase — the only code that matters)
- `transactionPricePerShare` × `transactionShares` to compute `value_usd`
- `reportingOwnerName` (insider name)
- Filter: `value_usd >= config.get("sec_catalyst_insider_min_value_usd", 50000)`

Step 4: Group purchases by issuer ticker within the cluster window (default 5 trading days).

Step 5: If `len(cluster) >= config.get("sec_catalyst_insider_cluster_min", 3)`:
```python
{
    "symbol": ticker,
    "signal_family": "insider_cluster",
    "raw_score": min(95.0, 60.0 + 5.0 * len(cluster)),  # more insiders = higher score
    "z_score": 0.0,
    "direction": "BULLISH",  # insider buys are always bullish signals
    "evidence_count": len(cluster),
    "freshness_hours": hours_since_earliest_in_cluster,
    "source_status": "OK",
    "source_name": "sec_catalyst",
}
```

**Important:** Form 4 XML parsing can be brittle. Wrap in try/except. If XML parsing fails for a filing, skip it and move on. Never let a malformed filing abort the entire run.

### 5. Supply Chain Propagation

**Implement `_propagate_supply_chain(primary_signals, config) -> List[DealFlowSignal]`:**

For each signal in `primary_signals` (8-K catalysts and insider clusters):
1. Look up `SUPPLY_CHAIN_MAP.get(signal["symbol"], [])`
2. For each tier-2 ticker in that list:
```python
propagated_signal = {
    "symbol": tier2_ticker,
    "signal_family": "supply_chain_propagation",
    "raw_score": signal["raw_score"] * 0.5,  # 50% of primary signal
    "z_score": 0.0,
    "direction": signal["direction"],
    "evidence_count": 1,
    "freshness_hours": signal["freshness_hours"],
    "source_status": "OK",
    "source_name": "sec_catalyst",
}
```

Deduplication: if a tier-2 ticker appears in multiple propagations, take the one with the highest `raw_score`. Never create a propagated signal for a ticker that already has a primary (8-K or insider) signal — the primary always wins.

### 6. Main Entry Point

```python
def collect_sec_catalyst_signals(
    universe: Iterable[UniverseRow],
    as_of_date: Optional[str] = None,
    config: Optional[Dict] = None,
) -> List[DealFlowSignal]:
    cfg = config or {}
    if not cfg.get("sec_catalyst_enabled", True):
        return []  # Return empty, pipeline treats as NOT_CONFIGURED

    primary_signals: List[DealFlowSignal] = []

    if cfg.get("sec_catalyst_8k_enabled", True):
        try:
            primary_signals.extend(_fetch_8k_signals(as_of_date, cfg))
        except Exception:
            pass  # graceful degradation

    if cfg.get("sec_catalyst_insider_enabled", True):
        try:
            primary_signals.extend(_fetch_insider_cluster_signals(list(universe), as_of_date, cfg))
        except Exception:
            pass

    propagated: List[DealFlowSignal] = []
    if cfg.get("sec_catalyst_supply_chain_enabled", True):
        propagated = _propagate_supply_chain(primary_signals, cfg)

    return primary_signals + propagated
```

### 7. Pipeline Wiring

In `tradingagents/dealflow/pipeline.py`, add after the cashtag connector block:

```python
sec_catalyst_start = time.perf_counter()
sec_catalyst_error = ""
try:
    sec_catalyst_signals = collect_sec_catalyst_signals(
        base_universe,
        as_of_date=as_of_date,
        config=self.config,
    )
except Exception as exc:
    sec_catalyst_error = str(exc)
    sec_catalyst_signals = []
connector_health.append({
    "connector": "sec_catalyst",
    "signals": len(sec_catalyst_signals),
    "elapsed_s": round(time.perf_counter() - sec_catalyst_start, 3),
    "error": sec_catalyst_error,
})
```

Feed `sec_catalyst_signals` into `score_candidates()`.

## Files to Touch
- `tradingagents/dealflow/sources/sec_catalyst.py` (new)
- `tradingagents/dealflow/sources/__init__.py` (add import)
- `tradingagents/dealflow/contracts.py` (add signal families — coordinate with S-033)
- `tradingagents/dealflow/pipeline.py` (wire connector)
- `tradingagents/default_config.py` (add sec catalyst config keys)
- `tests/test_sec_catalyst.py` (new)

## Tests: tests/test_sec_catalyst.py

All EDGAR HTTP calls must be mocked (no live network). Use `monkeypatch` to mock `requests.get`.

```python
# Test 1: disabled via config returns empty list
def test_disabled_returns_empty():
    signals = collect_sec_catalyst_signals([], config={"sec_catalyst_enabled": False})
    assert signals == []

# Test 2: 8-K supply agreement maps to BULLISH signal
def test_8k_supply_agreement_is_bullish(monkeypatch):
    # Mock EDGAR search-index response with one NVDA supply agreement filing
    # Assert: signal for NVDA, signal_family="sec_8k_catalyst", direction="BULLISH"

# Test 3: 8-K CEO departure maps to BEARISH signal
def test_8k_ceo_departure_is_bearish(monkeypatch):
    # Mock EDGAR response with "Chief Executive Officer" "resignation" filing for AAPL
    # Assert: direction="BEARISH", raw_score=60.0

# Test 4: Form 4 cluster fires at exactly 3 insiders
def test_insider_cluster_fires_at_three(monkeypatch):
    # Mock Form 4 EDGAR response with 3 P-type purchase transactions for MSFT, >$50K each
    # within 5 days
    # Assert: signal returned with signal_family="insider_cluster", evidence_count=3

# Test 5: Form 4 cluster does NOT fire at 2 insiders
def test_insider_cluster_no_fire_at_two(monkeypatch):
    # Mock response with only 2 insider purchases
    # Assert: no insider_cluster signal returned

# Test 6: Form 4 sells (code 'S') are ignored
def test_insider_sales_ignored(monkeypatch):
    # Mock Form 4 with transactionCode='S' (sale)
    # Assert: no signal returned

# Test 7: Form 4 purchases below min value are ignored
def test_insider_below_min_value_ignored(monkeypatch):
    # Mock 3 purchases, each $10K (below $50K threshold)
    # Assert: no cluster signal

# Test 8: Supply chain propagation fires for NVDA dependents
def test_supply_chain_propagation():
    primary = [{"symbol": "NVDA", "signal_family": "sec_8k_catalyst", "raw_score": 80.0,
                 "direction": "BULLISH", "evidence_count": 1, "freshness_hours": 2.0,
                 "z_score": 0.0, "source_status": "OK", "source_name": "sec_catalyst"}]
    propagated = _propagate_supply_chain(primary, config={})
    prop_tickers = [s["symbol"] for s in propagated]
    # NVDA maps to: TSM, AMKR, ASX, GLW, COHR, LITE, MRVL, AXTI, SMCI
    assert "TSM" in prop_tickers
    assert "AXTI" in prop_tickers
    # Verify propagated score is 50% of primary
    tsm_signal = next(s for s in propagated if s["symbol"] == "TSM")
    assert abs(tsm_signal["raw_score"] - 40.0) < 0.1  # 80 * 0.5

# Test 9: Primary ticker is not also in propagated list
def test_primary_not_in_propagated():
    primary = [{"symbol": "NVDA", ...}]
    propagated = _propagate_supply_chain(primary, config={})
    assert not any(s["symbol"] == "NVDA" for s in propagated)

# Test 10: EDGAR request includes correct User-Agent header
def test_edgar_user_agent_set(monkeypatch):
    captured_headers = {}
    def mock_get(url, params, headers, timeout):
        captured_headers.update(headers)
        return MockResponse({"hits": {"hits": []}})
    monkeypatch.setattr("requests.get", mock_get)
    _fetch_8k_signals("2026-02-25", {"dealflow_sec_user_agent": "TestAgent/1.0"})
    assert captured_headers.get("User-Agent") == "TestAgent/1.0"

# Test 11: Request delay between EDGAR calls
def test_request_delay(monkeypatch):
    # Verify time.sleep is called with delay between multiple requests
    import time
    sleep_calls = []
    monkeypatch.setattr(time, "sleep", lambda s: sleep_calls.append(s))
    _fetch_8k_signals("2026-02-25", {"sec_catalyst_request_delay_s": 0.12})
    assert any(abs(s - 0.12) < 0.01 for s in sleep_calls)

# Test 12: Malformed Form 4 XML is skipped gracefully
def test_malformed_xml_skipped(monkeypatch):
    # Mock one filing with invalid XML, one valid
    # Assert: valid filing still processed, no exception raised

# Test 13: SUPPLY_CHAIN_MAP is importable at module level
def test_supply_chain_map_importable():
    from tradingagents.dealflow.sources.sec_catalyst import SUPPLY_CHAIN_MAP
    assert "NVDA" in SUPPLY_CHAIN_MAP
    assert isinstance(SUPPLY_CHAIN_MAP["NVDA"], list)
    assert len(SUPPLY_CHAIN_MAP["NVDA"]) >= 3
```

## Acceptance Criteria
- [ ] `collect_sec_catalyst_signals` returns `[]` (not raises) when EDGAR is unreachable or returns errors
- [ ] 8-K filings parsed with correct direction (BULLISH for supply agreements, BEARISH for executive departures)
- [ ] Insider cluster fires at `>= 3` open-market purchases (transaction code P), minimum $50K each
- [ ] Supply chain propagation generates tier-2 signals at 50% of primary score
- [ ] Primary tickers never duplicated in propagated output
- [ ] EDGAR User-Agent header correctly set on every request
- [ ] Rate limiting delay (0.12s) applied between sequential EDGAR requests
- [ ] `SUPPLY_CHAIN_MAP` is a module-level constant with at least 25 tier-1 tickers
- [ ] New signal families in contracts.py Literal (coordinate with S-033 to avoid conflict)
- [ ] 13 tests in `tests/test_sec_catalyst.py`, all passing with mocked HTTP
- [ ] All existing tests pass: `python -m pytest tests/ -v`

---

## Handoff
*Fill in when marking done. Opus reads this to parse completion without reading the implementation.*

**Work Done:** `tradingagents/dealflow/sources/sec_catalyst.py` (new — full connector), `tradingagents/dealflow/contracts.py` (signal families already present from S-033), `tradingagents/default_config.py` (added 10 sec_catalyst_* keys), `tradingagents/dealflow/sources/__init__.py` (import added), `tradingagents/dealflow/pipeline.py` (wired into connector_tasks), `tests/test_sec_catalyst.py` (new — 13 tests). Ships daily 8-K material event monitor, Form 4 insider cluster detector, and SUPPLY_CHAIN_MAP-driven supply chain propagation.

**Learnings:** (1) When mocking requests.get for multi-step EDGAR flows, use `params=None` keyword signature and check `params.get("forms") == "4"` (dict key check), not `"forms=4" in str(params)` (string repr check) — the string repr uses `: ` not `=`. (2) Add a `transaction_code == "P"` filter at the cluster-accumulation layer as defense in depth even though the XML parser already filters — the mock layer exposed this gap. (3) Double monkeypatch within the same test (patch function, then patch requests.get) works fine with pytest monkeypatch, just order matters.

**Follow-ups:** S-035 (Knowledge Graph) imports SUPPLY_CHAIN_MAP from this module — no changes needed here.
