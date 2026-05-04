# S-076: X Feed Discovery Scout — Broad Trending Cashtag Scanner

**Assignee:** Sonnet
**Status:** done
**Branch:** feature/sonnet46 (branch from feature/opus46)
**Estimated files:** 3 new, 2 modified

---

## Context

Aeternus has NO broad discovery mechanism. All existing scouts operate on tickers we already know
about. We need a scout that asks: "What's trending on financial X right now?" and writes the
answers back to AKG. This is the wide-net that feeds the entire emergence tier system.

One xAI x_search call costs $0.005 and returns real X data. A few calls per run gives us
broad market pulse for pennies.

---

## What Already Exists (Do Not Rebuild)

| Component | Location | Notes |
|---|---|---|
| xAI client pattern | `sources/cashtag_enricher.py:199-209` | `OpenAI(base_url="https://api.x.ai/v1")`, `client.responses.create(tools=[{"type": "x_search"}])` |
| AKG `add_node()` | `knowledge_graph.py:415` | Idempotent. `add_node(ticker, node_type="company")` |
| AKG `enrich_node_cashtag()` | `knowledge_graph.py` | Sets velocity_z, mentions_7d, velocity_trend, sentiment |
| AKG `compute_all_emergence_scores()` | `knowledge_graph.py` | Recomputes DARK→ROCKY→ATMOSPHERE→HABITABLE |
| AKG `update_node_field()` | `knowledge_graph.py` | Generic field setter |
| Rate limit pattern | `sources/cashtag_enricher.py:285-297` | `_is_rate_limited_error()` |
| JSON extraction | `sources/cashtag_enricher.py:264-282` | `_extract_json_payload()` |
| CLI command pattern | `cli/commands/roll_monitor.py` | `@app.command()` + Rich output |
| Config pattern | `default_config.py` | All settings env-var overridable |

---

## NOT in Scope

- Running discovered tickers through the 12 pipeline connectors
- Modifying pipeline.py or scoring.py
- Modifying emergence tier logic
- Sentiment analysis of individual posts (that's cashtag_enricher's job)
- X_BEARER_TOKEN / direct Twitter API (we use xAI x_search only)

---

## Architecture

```
aeternus x-discover  (CLI command, also callable by scheduler)
       ↓
  x_feed_scout.py
    ├── xAI x_search call 1: "trending stock tickers on X last 24h"
    ├── xAI x_search call 2: "unusual volume cashtags finance X today"
    ├── xAI x_search call 3: "most discussed stocks financial twitter right now"
    ├── Parse structured JSON response → list of (ticker, mention_estimate, context)
    ├── Validate tickers (regex, length, skip crypto/forex)
    ├── For each ticker:
    │     ├── If exists in AKG → update_node_field("x_trending_at", timestamp)
    │     └── If NOT in AKG → add_node(ticker) + set metadata
    ├── compute_all_emergence_scores()
    └── akg.save()
```

**Cost per run:** 3 xAI x_search calls × $0.005 = $0.015 total.

---

## Implementation

### NEW: `tradingagents/dealflow/sources/x_feed_scout.py` (~120 lines)

```python
"""X Feed Discovery Scout — scans financial X for trending cashtags via xAI x_search.

Designed to run on a schedule (every 4-8 hours) or on-demand via CLI.
Writes discovered tickers directly to AKG. Cost: ~$0.015 per run.
"""

from __future__ import annotations
import datetime as dt, json, os, re, sys
from typing import Any, Dict, List, Optional, Tuple

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

TICKER_RE = re.compile(r"^[A-Z]{1,5}$")

# Skip crypto, forex, indices
SKIP_SYMBOLS = {
    "BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "DOT", "AVAX", "MATIC", "LINK",
    "USD", "EUR", "GBP", "JPY", "CNY", "SPX", "NDX", "DJI", "VIX", "RUT",
    "HODL", "FOMO", "YOLO", "IMO", "LMAO", "NYSE", "NASDAQ",
}

DISCOVERY_PROMPTS = [
    (
        "Search X for financial discussions in the last 24 hours. "
        "What stock tickers (US equities only, not crypto) are getting the MOST mentions right now? "
        "Return JSON only: {\"trending\": [{\"ticker\": \"AAPL\", \"mentions_estimate\": 500, "
        "\"context\": \"brief reason for attention\"}, ...]}. Top 20 tickers by mention volume."
    ),
    (
        "Search X for stock cashtags with UNUSUAL volume spikes today vs their normal baseline. "
        "Which US stock tickers are being discussed significantly more than usual? "
        "Return JSON only: {\"trending\": [{\"ticker\": \"SMCI\", \"mentions_estimate\": 200, "
        "\"context\": \"earnings surprise\"}, ...]}. Top 20 by spike magnitude. No crypto."
    ),
    (
        "Search X for what retail traders and financial accounts are talking about RIGHT NOW. "
        "Which US stock tickers are generating the most debate, analysis, or excitement today? "
        "Return JSON only: {\"trending\": [{\"ticker\": \"NVDA\", \"mentions_estimate\": 1000, "
        "\"context\": \"AI demand narrative\"}, ...]}. Top 20. No crypto, no forex."
    ),
]


def scan_x_feed(
    config: Optional[dict] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Scan financial X via xAI x_search for trending tickers.
    Write discoveries to AKG.

    Returns:
        {
            "ran": bool,
            "reason": str,
            "calls_made": int,
            "tickers_found": int,
            "new_nodes_created": int,
            "existing_nodes_updated": int,
            "tickers": [{"ticker": str, "mentions_estimate": int, "context": str, "is_new": bool}, ...],
            "errors": [str, ...],
        }
    """
    cfg = config or {}
    api_key = str(os.getenv("XAI_API_KEY", "")).strip()
    if not api_key or OpenAI is None:
        return {"ran": False, "reason": "no_xai_api_key", "calls_made": 0,
                "tickers_found": 0, "new_nodes_created": 0, "existing_nodes_updated": 0,
                "tickers": [], "errors": []}

    model = cfg.get("x_feed_scout_model", "grok-4-1-fast-reasoning")
    max_calls = int(cfg.get("x_feed_scout_max_calls", 3))
    prompts = DISCOVERY_PROMPTS[:max_calls]

    # --- Fetch phase ---
    all_tickers: Dict[str, Dict[str, Any]] = {}  # ticker → best entry (highest mentions)
    calls_made = 0
    errors: List[str] = []

    client = OpenAI(base_url="https://api.x.ai/v1", api_key=api_key)

    for prompt in prompts:
        try:
            response = client.responses.create(
                model=model,
                instructions="You are a financial markets analyst. Search X for real data. Return valid JSON only.",
                input=[{"role": "user", "content": prompt}],
                tools=[{"type": "x_search"}],
                temperature=0.0,
                max_output_tokens=1500,
            )
            calls_made += 1
            content = response.output_text or ""
            parsed = _extract_json_payload(content)

            if isinstance(parsed, dict):
                for entry in parsed.get("trending", []):
                    ticker = str(entry.get("ticker", "")).strip().upper().replace(".", "-")
                    if not _is_valid_ticker(ticker):
                        continue
                    mentions = int(entry.get("mentions_estimate", 0) or 0)
                    context = str(entry.get("context", ""))[:200]
                    existing = all_tickers.get(ticker)
                    if not existing or mentions > existing.get("mentions_estimate", 0):
                        all_tickers[ticker] = {
                            "ticker": ticker,
                            "mentions_estimate": mentions,
                            "context": context,
                        }
        except Exception as exc:
            errors.append(f"x_search call failed: {exc}")
            calls_made += 1

    if not all_tickers:
        return {"ran": True, "reason": "no_tickers_found", "calls_made": calls_made,
                "tickers_found": 0, "new_nodes_created": 0, "existing_nodes_updated": 0,
                "tickers": [], "errors": errors}

    # --- Write phase ---
    if dry_run:
        ticker_list = sorted(all_tickers.values(), key=lambda t: -t["mentions_estimate"])
        for t in ticker_list:
            t["is_new"] = True  # can't check without loading AKG
        return {"ran": True, "reason": "dry_run", "calls_made": calls_made,
                "tickers_found": len(ticker_list), "new_nodes_created": 0,
                "existing_nodes_updated": 0, "tickers": ticker_list, "errors": errors}

    from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
    akg = AeternusKnowledgeGraph.load()
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")

    new_count = 0
    updated_count = 0
    ticker_list = []

    for ticker, entry in sorted(all_tickers.items(), key=lambda kv: -kv[1]["mentions_estimate"]):
        is_new = ticker not in akg._nodes
        if is_new:
            akg.add_node(ticker, node_type="company",
                         metadata={"seed_sources": ["x_feed_scout"],
                                   "discovered_at": now_iso,
                                   "discovery_context": entry["context"]})
            new_count += 1
        else:
            updated_count += 1

        akg.update_node_field(ticker, "x_trending_at", now_iso)
        akg.update_node_field(ticker, "x_trending_mentions", entry["mentions_estimate"])
        akg.update_node_field(ticker, "x_trending_context", entry["context"])

        entry["is_new"] = is_new
        ticker_list.append(entry)

    akg.compute_all_emergence_scores()
    akg.save()

    return {
        "ran": True,
        "reason": "ok",
        "calls_made": calls_made,
        "tickers_found": len(ticker_list),
        "new_nodes_created": new_count,
        "existing_nodes_updated": updated_count,
        "tickers": ticker_list,
        "errors": errors,
    }


def _is_valid_ticker(ticker: str) -> bool:
    """Return True if ticker looks like a valid US equity symbol."""
    if not ticker or not TICKER_RE.match(ticker):
        return False
    if ticker in SKIP_SYMBOLS:
        return False
    if len(ticker) < 1:
        return False
    return True


def _extract_json_payload(content: str):
    """Extract a JSON object from an LLM response string."""
    # (Copy the same pattern from cashtag_enricher.py:264-282)
    raw = str(content or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(raw[start:end + 1])
        except Exception:
            return None
    return None
```

### NEW: CLI command `cli/commands/x_feed_scout.py` (~35 lines)

```python
"""CLI command for X Feed Discovery Scout."""
import typer
from cli.common import *

@app.command()
def x_discover(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show discoveries without writing to AKG"),
):
    """Scan financial X for trending tickers via xAI x_search. Writes discoveries to AKG."""
    from tradingagents.dealflow.sources.x_feed_scout import scan_x_feed
    from tradingagents.default_config import DEFAULT_CONFIG

    result = scan_x_feed(config=DEFAULT_CONFIG, dry_run=dry_run)

    if not result.get("ran"):
        console.print(f"[red]Did not run: {result.get('reason')}[/red]")
        raise typer.Exit(1)

    # Rich table: Ticker | Mentions | Context | New?
    table = Table(title="X Feed Discovery Scout")
    table.add_column("Ticker", style="bold")
    table.add_column("Mentions", justify="right")
    table.add_column("Context")
    table.add_column("Status")

    for t in result.get("tickers", []):
        status = "[green]NEW[/green]" if t.get("is_new") else "[dim]existing[/dim]"
        table.add_row(t["ticker"], str(t["mentions_estimate"]), t["context"], status)

    console.print(table)
    console.print(
        f"\nCalls: {result['calls_made']} | "
        f"Found: {result['tickers_found']} | "
        f"New: {result['new_nodes_created']} | "
        f"Updated: {result['existing_nodes_updated']}"
    )
    if result.get("errors"):
        for err in result["errors"]:
            console.print(f"[yellow]Warning: {err}[/yellow]")
```

### MODIFY: `cli/main.py` (+1 line)
```python
importlib.import_module("cli.commands.x_feed_scout")
```

### MODIFY: `tradingagents/default_config.py` (+3 keys)
```python
# X Feed Discovery Scout
"x_feed_scout_model": os.getenv("X_FEED_SCOUT_MODEL", "grok-4-1-fast-reasoning"),
"x_feed_scout_max_calls": int(os.getenv("X_FEED_SCOUT_MAX_CALLS", "3")),
"x_feed_scout_enabled": os.getenv("X_FEED_SCOUT_ENABLED", "1") != "0",
```

---

## Tests

### NEW: `tests/test_x_feed_scout.py` (~60 lines)

All xAI calls mocked. No real network calls.

1. `test_scan_returns_tickers` — mock 3 x_search responses with overlapping tickers, verify dedup by highest mentions
2. `test_scan_skips_crypto` — mock response containing BTC, ETH, SOL — verify all filtered out
3. `test_scan_skips_invalid_tickers` — mock response with "TOOLONG", "123", "" — verify filtered
4. `test_scan_writes_to_akg` — mock AKG, verify add_node called for new tickers, update_node_field for all
5. `test_scan_dry_run_no_save` — verify akg.save() NOT called in dry_run mode
6. `test_scan_no_api_key` — unset XAI_API_KEY, verify ran=False reason=no_xai_api_key
7. `test_scan_api_error_continues` — mock first call raising exception, verify remaining calls still fire
8. `test_existing_node_not_recreated` — ticker already in AKG, verify add_node NOT called, update_node_field IS called

---

## Verification

```bash
# 1. Tests
python3 -m pytest tests/test_x_feed_scout.py -v

# 2. Dry run
aeternus x-discover --dry-run

# 3. Real run
aeternus x-discover

# 4. Verify AKG got new nodes
python3 -c "
from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
akg = AeternusKnowledgeGraph.load()
trending = [n for n in akg._nodes.values() if n.get('x_trending_at')]
print(f'Nodes with x_trending_at: {len(trending)}')
for n in sorted(trending, key=lambda x: -(x.get(\"x_trending_mentions\") or 0))[:10]:
    print(f'  {n[\"id\"]:6s}  mentions={n.get(\"x_trending_mentions\", 0):>5}  {n.get(\"x_trending_context\", \"\")[:60]}')
"

# 5. Regression
python3 -m pytest tests/test_knowledge_graph.py -v
```

---

## Expected Outcome

- 3 xAI x_search calls per run, cost ~$0.015
- Returns 20-60 unique trending tickers (after dedup across 3 prompts)
- New tickers added to AKG as company nodes with `seed_sources: ["x_feed_scout"]`
- Existing nodes get `x_trending_at`, `x_trending_mentions`, `x_trending_context` updated
- Emergence scores recomputed — nodes with trending data start moving from DARK toward ROCKY
- CLI: `aeternus x-discover [--dry-run]`

---

## DO NOT TOUCH

- `knowledge_graph.py` — no modifications needed
- `pipeline.py` — Opus modifies the universe gate separately
- `cashtag_enricher.py` — separate scout, separate job
- `cashtag_stream.py` — connector, different purpose
- Any emergence tier logic
