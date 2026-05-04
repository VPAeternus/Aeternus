# S-075: Seed AKG from S&P500 + Russell 2000 + NASDAQ + ARK + ETF Holdings + Growth Watchlist

**Assignee:** Sonnet
**Status:** done
**Branch:** feature/sonnet46 (branch from feature/opus46)
**Estimated files:** 3 new, 1 modified

---

## Context

AKG currently has 784 company nodes seeded from a hand-curated supply chain map + a 713-row CSV
(`tradingagents/graph/data/universe_constituents.csv`). The user wants EVERY investable US security
in AKG so scouts can cast a wide net and light up nodes.

The goal is NOT to run all these tickers through the 12 pipeline connectors. The goal is to have
them IN AKG so scouts (cashtag_enricher, sector_scout, etc.) can accumulate evidence on them and
promote them through emergence tiers (DARK → ROCKY → ATMOSPHERE → HABITABLE → SCORED).

---

## What Already Exists (Do Not Rebuild)

| Component | Location | Notes |
|---|---|---|
| `add_node()` | `knowledge_graph.py:415` | Idempotent. `add_node("AAPL")` = minimum call. |
| `_bootstrap_universe()` | `knowledge_graph.py:1534` | Loads from CSV, sets sector via `_YFINANCE_SECTOR_MAP` |
| `universe_constituents.csv` | `tradingagents/graph/data/` | 713 rows: `ticker,name,exchange,sector_yf` |
| `save()` / `load()` | `knowledge_graph.py` | JSON at `eval_results/control/knowledge_graph.json`, atomic write |
| `seed_from_supply_chain_map()` | `knowledge_graph.py:1518` | Idempotent, adds nodes + edges |
| yfinance | `requirements.txt`, `pyproject.toml` | Already a dependency |
| `AKG_UNIVERSE_BOOTSTRAP_ENABLED` | `default_config.py` | Defaults to `"1"` (enabled) |

---

## NOT in Scope

- Running these tickers through the 12 pipeline connectors (separate step)
- Modifying pipeline.py universe gate (Opus will handle after seeding)
- Modifying emergence tier logic
- Adding supply chain edges for new tickers (that's the scouts' job)
- Centrality recomputation (happens naturally when edges are added later)

---

## Data Sources — Fetch Logic

### 1. S&P 500 (~503 tickers)
```python
import pandas as pd
url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
tables = pd.read_html(url)
sp500 = tables[0]["Symbol"].str.strip().str.replace(".", "-", regex=False).tolist()
```
Source tag: `"sp500"`

### 2. Full NASDAQ Listed (~3,500 tickers)
```python
# NASDAQ Trader FTP (public, no auth)
url = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10000&exchange=nasdaq"
headers = {"User-Agent": "Mozilla/5.0"}
resp = requests.get(url, headers=headers)
rows = resp.json()["data"]["table"]["rows"]
nasdaq_tickers = [r["symbol"].strip() for r in rows if r.get("symbol")]
```
If that API blocks: fallback to `ftp://ftp.nasdaqtrader.com/SymbolDirectory/nasdaqtraded.txt`
(pipe-delimited, filter where `ETF == "N"` and `Test Issue == "N"`)

Source tag: `"nasdaq"`

### 3. Russell 2000 (~2,000 tickers)
Best free approach: iShares IWM holdings CSV
```python
url = "https://www.ishares.com/us/products/239710/ishares-russell-2000-etf/1467271812596.ajax?fileType=csv&fileName=IWM_holdings&dataType=fund"
```
Parse the CSV (skip header rows until you find `Ticker,Name,Sector,...`).
If iShares blocks: use `yfinance.Ticker("IWM").get_holdings()` or a static fallback.

Source tag: `"russell2000"`

### 4. Dow 30
Static list — changes rarely:
```python
DOW_30 = [
    "AAPL", "AMGN", "AMZN", "AXP", "BA", "CAT", "CRM", "CSCO", "CVX", "DIS",
    "GS", "HD", "HON", "IBM", "JNJ", "JPM", "KO", "MCD", "MMM", "MRK",
    "MSFT", "NKE", "NVDA", "PG", "SHW", "TRV", "UNH", "V", "VZ", "WMT",
]
```
Source tag: `"dow"`

### 5. ARKK + ARKG Holdings (~70 unique tickers)
ARK publishes daily CSVs:
```python
ARK_URLS = {
    "ARKK": "https://ark-funds.com/wp-content/uploads/funds-etf-csv/ARK_INNOVATION_ETF_ARKK_HOLDINGS.csv",
    "ARKG": "https://ark-funds.com/wp-content/uploads/funds-etf-csv/ARK_GENOMIC_REVOLUTION_ETF_ARKG_HOLDINGS.csv",
}
# CSV has columns: date, fund, company, ticker, cusip, shares, market_value, weight
```
Source tag: `"ark"`

### 6. Sector ETF Tickers (the ETFs themselves)
```python
SECTOR_ETFS = [
    "XLF", "XLE", "XLK", "XLV", "XLY", "XLP", "XLI", "XLU", "XLRE", "XLB", "XLC",
    "SMH", "XBI", "IBB", "XHB", "XRT", "KRE", "KBE", "XOP", "OIH", "ITB",
    "HACK", "SKYY", "BOTZ", "ROBO", "LIT", "TAN", "ICLN", "QCLN", "PBW",
]
```
Source tag: `"sector_etf"`

### 7. Sector ETF Holdings (the stocks INSIDE each ETF)
For each sector ETF in the list above:
```python
import yfinance as yf
etf = yf.Ticker("XLF")
# Try etf.funds_data.top_holdings or etf.info.get("holdings")
# yfinance may not support this for all ETFs — use best-effort
```
Alternative: just rely on S&P500 + Russell 2000 covering most sector ETF holdings (they do — XLF
holdings are all S&P500 financials). Only fetch ARK holdings explicitly since those are
non-index growth names.

**Decision: fetch holdings for ARKK + ARKG only.** Sector ETF holdings are covered by S&P500 + Russell.
Source tag: same as parent ETF (`"ark"`)

### 8. Emerging Market + International ETF Tickers
```python
EM_ETFS = [
    "EEM", "VWO", "IEMG", "EFA", "EWZ", "EWJ", "FXI", "INDA", "EWT", "EWY",
    "EWG", "EWU", "KWEB", "MCHI", "ASHR",
]
```
Source tag: `"em_etf"`
(Just the ETF tickers — their holdings are foreign stocks, not directly tradeable US equities)

### 9. Commodity ETF Tickers
```python
COMMODITY_ETFS = [
    "GLD", "SLV", "PPLT", "USO", "UNG", "DBC", "DBA", "CORN", "WEAT", "SOYB",
    "GDX", "GDXJ", "SIL", "COPX", "XME", "PDBC", "GSG", "CPER",
]
```
Source tag: `"commodity_etf"`

### 10. Growth Watchlist (user-maintained JSON file)
**Create** `eval_results/control/growth_watchlist.json`:
```json
{
    "description": "User-maintained growth/thematic watchlist. Add tickers here and run akg-seed to include them.",
    "tickers": [
        "IREN", "NBIS", "CRWV", "ALAB", "CRDO", "CIFR", "WULF", "TSSI",
        "RKLB", "LUNR", "RDW", "MNTS", "ASTS", "BWXT", "SMR",
        "IONQ", "RGTI", "QUBT", "QBTS",
        "JOBY", "ACHR", "LILM",
        "OPEN", "RDFN", "CVNA"
    ]
}
```
Source tag: `"growth_watchlist"`

---

## Implementation

### NEW: `tradingagents/dealflow/sources/universe_seeder.py` (~200 lines)

```python
"""Seed AKG with tickers from S&P500, NASDAQ, Russell 2000, Dow, ARK, ETFs, and growth watchlist."""

import json, csv, time, sys, os
from pathlib import Path
from typing import Dict, List, Set, Tuple

def fetch_sp500() -> List[Tuple[str, str]]:
    """Return [(ticker, "sp500"), ...]"""

def fetch_nasdaq_listed() -> List[Tuple[str, str]]:
    """Return [(ticker, "nasdaq"), ...]"""

def fetch_russell2000() -> List[Tuple[str, str]]:
    """Return [(ticker, "russell2000"), ...]"""

def fetch_ark_holdings() -> List[Tuple[str, str]]:
    """Return [(ticker, "ark"), ...] from ARKK + ARKG CSVs"""

def get_static_etfs() -> List[Tuple[str, str]]:
    """Return static ETF tickers: sector, EM, commodity"""

def load_growth_watchlist(path: Path = None) -> List[Tuple[str, str]]:
    """Return [(ticker, "growth_watchlist"), ...] from user-maintained JSON"""

def build_full_seed_universe() -> Dict[str, List[str]]:
    """
    Fetch all sources, dedupe, return {ticker: [source1, source2, ...]}.
    A ticker in both sp500 and nasdaq gets both tags.
    Prints progress to stderr.
    """

def seed_akg(dry_run: bool = False) -> dict:
    """
    Load AKG, add all tickers from build_full_seed_universe().
    For each new node: akg.add_node(ticker, node_type="company", metadata={"seed_sources": [...]})
    For existing nodes: just update metadata["seed_sources"] (append new sources, don't overwrite).

    Save AKG if not dry_run.

    Returns {"total_fetched": int, "new_nodes_added": int, "existing_updated": int, "errors": [...]}
    """
```

**Important implementation details:**
- Every fetch function must be wrapped in try/except — if one source fails, continue with others.
- Rate limit: `time.sleep(0.5)` between external fetches.
- Ticker sanitization: `.strip().upper()`, replace `.` with `-` (BRK.B → BRK-B).
- Filter out non-equity tickers: skip if ticker contains `^`, `/`, or is > 5 chars with no letters.
- `metadata["seed_sources"]` is a list of strings: `["sp500", "nasdaq", "russell2000"]`.
- Print progress to stderr: `[universe_seeder] Fetching S&P 500... got 503 tickers`

### NEW: CLI command in `cli/commands/universe_seeder.py` (~40 lines)

```python
@app.command()
def akg_seed(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be added without modifying AKG"),
):
    """Seed AKG with tickers from S&P 500, NASDAQ, Russell 2000, Dow, ARK, ETFs, and growth watchlist."""
    from tradingagents.dealflow.sources.universe_seeder import seed_akg
    result = seed_akg(dry_run=dry_run)
    # Print Rich summary table: source counts, new vs existing, errors
```

Register in `cli/main.py`: `importlib.import_module("cli.commands.universe_seeder")`

### NEW: `eval_results/control/growth_watchlist.json`
The initial watchlist file (see data above).

### MODIFY: `cli/main.py` (+1 line)
```python
importlib.import_module("cli.commands.universe_seeder")
```

---

## DO NOT TOUCH

- `knowledge_graph.py` — no modifications needed. `add_node()` already handles everything.
- `pipeline.py` — Opus will modify the universe gate after seeding is confirmed.
- `universe.py` — the hardcoded 137 list stays as a fallback.
- `_bootstrap_universe()` — the existing CSV bootstrap stays as-is.
- Any emergence tier logic.

---

## Tests

### NEW: `tests/test_universe_seeder.py` (~80 lines)

All external fetches mocked. No real network calls in tests.

1. `test_fetch_sp500_parses_wikipedia_table` — mock requests.get, return fake HTML table, verify tickers extracted
2. `test_fetch_nasdaq_parses_api_response` — mock API JSON, verify tickers extracted
3. `test_fetch_ark_parses_csv` — mock CSV content, verify tickers extracted
4. `test_growth_watchlist_loads_json` — write temp JSON, verify load
5. `test_growth_watchlist_missing_file_returns_empty` — no file = empty list, no crash
6. `test_build_full_seed_universe_dedupes` — mock all sources returning overlapping tickers, verify dedup
7. `test_seed_akg_adds_new_nodes` — mock AKG, verify add_node called for new tickers
8. `test_seed_akg_updates_existing_metadata` — verify seed_sources merged, not overwritten
9. `test_seed_akg_dry_run_no_save` — verify akg.save() NOT called in dry_run mode
10. `test_ticker_sanitization` — BRK.B → BRK-B, lowercase → upper, whitespace stripped

---

## Verification

```bash
# 1. Tests
python3 -m pytest tests/test_universe_seeder.py -v

# 2. Dry run (shows what would be added, no AKG modification)
aeternus akg-seed --dry-run

# 3. Real seed
aeternus akg-seed

# 4. Verify AKG node count grew
python3 -c "
from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
akg = AeternusKnowledgeGraph.load()
companies = [n for n in akg._nodes.values() if n.get('node_type') == 'company']
seeded = [n for n in companies if n.get('metadata', {}).get('seed_sources')]
print(f'Total company nodes: {len(companies)}')
print(f'Seeded nodes: {len(seeded)}')
"

# 5. Regression
python3 -m pytest tests/test_knowledge_graph.py -v
```

---

## Expected Outcome

- AKG grows from ~784 company nodes to ~5,000–6,000 company nodes
- Each new node has `metadata.seed_sources` tracking origin
- All nodes start as DARK (no emergence data yet — scouts will light them up later)
- Growth watchlist file exists for user to maintain
- Pipeline behavior UNCHANGED (Opus modifies the gate after this lands)
