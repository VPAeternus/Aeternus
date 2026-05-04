# Task: S-049

## Tier
sonnet

## Summary
Load S&P 500 + Russell 2000 constituents into AKG as DARK nodes on first boot. Free, one-time operation. Gives AKG a broad watching universe so cluster detection (S-050) can observe velocity on any ticker — not just the ~50 we manually seeded.

## Context
**Depends on nothing. Build first.**

**The problem:** AKG currently seeds ~50 hardcoded companies (SEED_COMPANIES in knowledge_graph.py). Cashtag enricher monitors only the top-50 by centrality. If a new theme forms in a sector we never seeded (quantum computing, humanoid robotics, climate tech), we have zero nodes to detect velocity on. The spark fires in a room we're not watching.

**Target state:** On AKG initialization (when `knowledge_graph.json` doesn't exist), bootstrap with the full S&P 500 + Russell 2000 constituent list. ~3,000-5,000 tickers. All as `node_type="company"`, `emergence_tier="DARK"`, `centrality=0.0`. No data fetched — just node registration so the cashtag enricher and SEC catalyst can start tracking them.

**Key design decisions:**
1. **Free source**: Use a static CSV bundled with the repo OR yfinance `tickers.tickers` list. Do NOT make API calls per-ticker during bootstrap — that defeats the purpose.
2. **Idempotent**: If nodes already exist, `add_node()` is already idempotent — it won't overwrite existing data.
3. **Low priority**: Bootstrap nodes have `confidence: 0.1` in metadata so they're clearly lower trust than manually seeded or discovered nodes.
4. **Sector classification**: yfinance's `Ticker.info["sector"]` can classify, but calling it for 3,000 tickers is expensive. Solution: set sector=None (UNKNOWN) on bootstrap. SEC catalyst and cashtag enricher will fill in sector when they encounter the ticker.
5. **Canonical sector mapping**: AKG uses internal sector IDs (e.g., "semis_ai_infrastructure", "biotech_pharma"). yfinance sectors are different ("Technology", "Healthcare"). We need a sector translation map.

**Key file:** `tradingagents/graph/knowledge_graph.py` — add `_bootstrap_universe()` method called by `_seed()`. Read the full file before touching anything.

## Requirements

### 1. Static constituent file

Create `tradingagents/graph/data/universe_constituents.csv` with columns: `ticker,name,exchange,sector_yf`.

Populate it with S&P 500 + Russell 2000 constituents. The sector_yf column uses yfinance sector names (can be left blank initially). This file is bundled with the repo — no runtime fetch needed.

To generate this file, use a one-time script (do NOT put this in production code):
```python
# scripts/generate_universe_csv.py  (write this too — used once to generate the CSV)
import yfinance as yf
import pandas as pd

# S&P 500 from Wikipedia table (free)
sp500 = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")[0]
# Russell 2000 — use IWM ETF constituents or a static list

# Write to tradingagents/graph/data/universe_constituents.csv
```

The script is a one-off tool. The CSV it generates is what gets committed. Production code reads the CSV — no Wikipedia fetch at runtime.

### 2. Sector translation map

Add a module-level constant to `knowledge_graph.py`:

```python
_YFINANCE_SECTOR_MAP = {
    "Technology": "semis_ai_infrastructure",
    "Healthcare": "biotech_pharma",
    "Industrials": "defense_aerospace",
    "Energy": "energy_power",
    "Basic Materials": "materials_critical_minerals",
    "Financial Services": "fintech_banking",
    "Consumer Cyclical": None,
    "Consumer Defensive": None,
    "Real Estate": None,
    "Communication Services": "semis_ai_infrastructure",  # GOOGL, META
    "Utilities": "energy_power",
}
```

This maps yfinance sector names to AKG internal sector IDs. Return None for sectors we don't track — those nodes get sector=None (DARK nodes without sector).

### 3. `_bootstrap_universe()` method (knowledge_graph.py)

```python
def _bootstrap_universe(self) -> int:
    """
    Load universe constituents from bundled CSV as DARK nodes.
    Idempotent — existing nodes are not overwritten.
    Returns number of new nodes added.
    """
    csv_path = Path(__file__).parent / "data" / "universe_constituents.csv"
    if not csv_path.exists():
        return 0

    import csv
    added = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = row.get("ticker", "").strip().upper()
            if not ticker or len(ticker) > 6:
                continue
            if ticker in self._nodes:
                continue  # idempotent — don't overwrite
            sector_yf = row.get("sector_yf", "")
            sector = _YFINANCE_SECTOR_MAP.get(sector_yf)
            self.add_node(
                ticker,
                node_type="company",
                sector=sector,
                display_name=row.get("name", ticker),
                metadata={"source": "universe_bootstrap", "confidence": 0.1},
            )
            added += 1
    return added
```

### 4. Wire into `_seed()` (knowledge_graph.py)

In `_seed()`, after seeding sectors, themes, and companies, add:

```python
# Bootstrap broad universe (S-049)
self._bootstrap_universe()
```

This means the universe is loaded on first AKG initialization when the JSON file doesn't exist.

### 5. New config key (default_config.py)

```python
"akg_universe_bootstrap_enabled": True,  # Load S&P 500 + Russell 2000 on first boot
```

Gate `_bootstrap_universe()` on this config key. Since `_seed()` doesn't take config, check an env var:
```python
if os.environ.get("AKG_UNIVERSE_BOOTSTRAP_ENABLED", "1") != "0":
    self._bootstrap_universe()
```

### 6. `generate_universe_csv.py` script

Write `scripts/generate_universe_csv.py` that:
1. Fetches S&P 500 from Wikipedia table (free, no API key)
2. Uses a static Russell 2000 list (or IWM ETF constituents from yfinance)
3. Writes `tradingagents/graph/data/universe_constituents.csv`

This script is run ONCE to generate the CSV. It is NOT called by production code.

## Files to Touch
- `tradingagents/graph/knowledge_graph.py` — `_YFINANCE_SECTOR_MAP` constant, `_bootstrap_universe()` method, wire into `_seed()`
- `tradingagents/graph/data/universe_constituents.csv` — generated by the script, committed to repo
- `tradingagents/default_config.py` — `akg_universe_bootstrap_enabled: True`
- `scripts/generate_universe_csv.py` — one-time generation script
- `tests/test_knowledge_graph.py` — test `_bootstrap_universe()`

## Acceptance Criteria
- [ ] `_bootstrap_universe()` reads from CSV and adds nodes, returns count of new nodes added
- [ ] Calling `_bootstrap_universe()` twice does not duplicate nodes (idempotent)
- [ ] Nodes added from CSV have `node_type="company"`, `emergence_tier=None` (will be set by cashtag enricher), `metadata.source="universe_bootstrap"`, `metadata.confidence=0.1`
- [ ] Tickers with len > 6 are skipped (filters out bad data)
- [ ] `_bootstrap_universe()` returns 0 gracefully if CSV doesn't exist (no crash)
- [ ] `_seed()` calls `_bootstrap_universe()` after seeding the manual seed data
- [ ] Pre-existing SEED_COMPANIES nodes are NOT overwritten (idempotent — `add_node` already handles this)
- [ ] `python -m pytest tests/test_knowledge_graph.py -v` — all pass
- [ ] `python -m pytest tests/ -v --ignore=tests/test_cli_dealflow.py --ignore=tests/test_cli_hedging.py --ignore=tests/test_cli_score.py` — no regressions
- [ ] `scripts/generate_universe_csv.py` runs without error and produces the CSV

## Status
done

## Handoff

Completed 2026-02-26 by Sonnet. 713 rows in CSV (503 S&P 500 + 210 Russell 2000 non-overlapping). 9 new tests. 144 total tests passing. Zero regressions.
