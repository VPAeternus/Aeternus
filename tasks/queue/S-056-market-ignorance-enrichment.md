# Task: S-056

## Tier
sonnet

## Summary
Replace the proxy `market_ignorance_score` in the Structural Force Engine with a real, data-grounded score computed from: sell-side analyst coverage count, institutional ownership %, and news velocity. Cached 7 days on AKG nodes. This transforms dark matter discovery_score from an internal-attention metric into a genuine measure of market blindness.

## Context

### The Problem
S-052 computes `market_ignorance_score` from AKG centrality + `times_surfaced`. This measures *our* attention, not the market's. A company with 40 sell-side analysts scores 1.0 (maximum ignorance) if we haven't looked at it — which is wrong. The score should reflect how blind institutional capital is to the company, not how blind our pipeline is.

### The Three Real Signals

| Signal | Source | Weight | Why |
|--------|--------|--------|-----|
| Analyst coverage count | yfinance `numberOfAnalystOpinions` | 0.50 | Sell-side infrastructure = price discovery exists |
| Institutional ownership % | yfinance `heldPercentInstitutions` | 0.35 | Funds already found it = price is informed |
| News velocity (30d) | AKG `news_count_30d` field (from cashtag enricher) | 0.15 | Media silence = retail and algo blind too |

### Score Formula
```
analyst_ignorance = max(0, 1.0 - analyst_count / 30.0)
inst_ignorance    = max(0, 1.0 - inst_pct / 0.90)
news_ignorance    = max(0, 1.0 - min(news_count_30d / 20.0, 1.0))

market_ignorance_score_real = (
    0.50 * analyst_ignorance +
    0.35 * inst_ignorance   +
    0.15 * news_ignorance
)
```

Ticker NOT in AKG at all → fallback to 1.0 (maximum ignorance, unknown entity).

### TTL
Cache 7 days on AKG node. yfinance call is free but slow; don't call on every pipeline run.

---

## Requirements

### 1. New file: `tradingagents/graph/market_ignorance.py`

```python
"""
Real market ignorance scoring from live data (S-056).
Replaces centrality-proxy in structural force dark matter discovery.
"""
from __future__ import annotations
import datetime as dt
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from tradingagents.graph.knowledge_graph import AeternusKG


def compute_market_ignorance(ticker: str, akg: "AeternusKG") -> float:
    """
    Compute market ignorance score (0.0=fully known, 1.0=completely invisible).

    Sources:
    - analyst_count: yfinance numberOfAnalystOpinions (free)
    - inst_pct: yfinance heldPercentInstitutions (free, same API call)
    - news_count_30d: AKG node field written by cashtag enricher

    Result cached 7 days on AKG node under:
      market_ignorance_score_real, analyst_count, institutional_pct,
      market_ignorance_cached_at

    Falls back to centrality-proxy if yfinance unavailable.
    Tickers not in AKG return 1.0 immediately (maximum ignorance).
    """
    # Ticker not in AKG → completely unknown, max ignorance
    node = akg._nodes.get(ticker)
    if node is None:
        return 1.0

    # 7-day cache hit
    cached_at = node.get("market_ignorance_cached_at")
    if cached_at:
        try:
            age_days = (dt.date.today() - dt.date.fromisoformat(cached_at)).days
            if age_days < 7:
                cached = node.get("market_ignorance_score_real")
                if cached is not None:
                    return float(cached)
        except (ValueError, TypeError):
            pass

    # yfinance fetch
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info

        analyst_count = int(info.get("numberOfAnalystOpinions") or 0)
        inst_pct      = float(info.get("heldPercentInstitutions") or 0.0)
        news_count    = int(node.get("news_count_30d") or 0)

        analyst_ig = max(0.0, 1.0 - analyst_count / 30.0)
        inst_ig    = max(0.0, 1.0 - inst_pct / 0.90)
        news_ig    = max(0.0, 1.0 - min(news_count / 20.0, 1.0))

        score = round(0.50 * analyst_ig + 0.35 * inst_ig + 0.15 * news_ig, 4)

        # Write back to AKG node (cache)
        node["market_ignorance_score_real"] = score
        node["analyst_count"]               = analyst_count
        node["institutional_pct"]           = inst_pct
        node["market_ignorance_cached_at"]  = dt.date.today().isoformat()

        return score

    except Exception:
        # Fallback: centrality proxy (S-052 original logic)
        centrality    = float(node.get("centrality") or 0.0)
        times_surfaced = int(node.get("times_surfaced") or 0)
        return max(0.0, 1.0 - min(centrality + times_surfaced / 100.0, 1.0))
```

### 2. Update `derive_dark_matter()` in `structural_forces.py`

Replace the existing market_ignorance_score computation block with a call to `compute_market_ignorance()`:

```python
# OLD (proxy):
# market_ignorance = 1.0 if not in akg else 1.0 - min(centrality + times_surfaced/100, 1.0)

# NEW (real data, with graceful fallback):
from tradingagents.graph.market_ignorance import compute_market_ignorance
market_ignorance_score = compute_market_ignorance(ticker, akg)
```

The rest of the DarkMatterCandidate construction is unchanged.

### 3. New AKG node fields in `_node_template()` (knowledge_graph.py)

Add to the template (after perplexity fields):
```python
# Market ignorance enrichment (S-056) — written by market_ignorance.compute_market_ignorance()
"market_ignorance_score_real": None,  # float: real ignorance score (0=known, 1=invisible)
"analyst_count": None,                # int: number of sell-side analysts covering
"institutional_pct": None,            # float: fraction held by institutions (0.0–1.0)
"market_ignorance_cached_at": None,   # ISO date string: when last computed
```

Add to `_backfill_node_defaults()` `_none_fields` list:
```python
"market_ignorance_score_real",
"analyst_count",
"institutional_pct",
"market_ignorance_cached_at",
```

### 4. New CLI flag on `forces dark-matter` (cli/commands/forces.py)

Add `--enrich / --no-enrich` flag (default: `--no-enrich`):
- `--enrich`: calls `compute_market_ignorance()` live for each candidate before display
- `--no-enrich`: uses cached AKG value or falls back to proxy

Show `analyst_count` and `institutional_pct` columns in the output table when enrichment data is available.

### 5. Config key (default_config.py)

```python
"market_ignorance_cache_ttl_days": 7,   # days before refreshing yfinance data
```

---

## Files to Touch
- `tradingagents/graph/market_ignorance.py` — NEW
- `tradingagents/graph/structural_forces.py` — update `derive_dark_matter()` to use real score
- `tradingagents/graph/knowledge_graph.py` — 4 new node fields + backfill
- `tradingagents/default_config.py` — 1 new config key
- `cli/commands/forces.py` — `--enrich` flag on `dark-matter` command
- `tests/test_market_ignorance.py` — NEW (keep separate from test_structural_forces.py)

---

## Tests (`tests/test_market_ignorance.py`)

1. Ticker not in AKG → returns 1.0 immediately (no yfinance call)
2. 7-day cache hit → returns cached value without calling yfinance
3. Cache miss → calls yfinance, computes score, writes back to node
4. `analyst_count=0, inst_pct=0.0, news=0` → score = 1.0 (fully invisible)
5. `analyst_count=30, inst_pct=0.9, news=20` → score = 0.0 (fully known)
6. `analyst_count=15, inst_pct=0.45, news=10` → score = 0.50 (midpoint, verify arithmetic)
7. yfinance raises exception → falls back to centrality proxy, does NOT raise
8. `derive_dark_matter()` uses `compute_market_ignorance()` (mock it, verify called per ticker)
9. `_backfill_node_defaults()` sets new fields to None on old nodes

---

## Acceptance Criteria
- [ ] `compute_market_ignorance()` returns 1.0 for unknown tickers
- [ ] 7-day cache prevents redundant yfinance calls
- [ ] Score formula matches spec arithmetic (verified in test 6)
- [ ] yfinance failures fall back to centrality proxy gracefully
- [ ] `derive_dark_matter()` now uses real ignorance scores
- [ ] `aeternus forces dark-matter --enrich` shows analyst_count + institutional_pct
- [ ] `_backfill_node_defaults()` fills 4 new fields
- [ ] All 9 tests pass
- [ ] `python -m pytest tests/ -v --ignore=tests/test_cli_dealflow.py --ignore=tests/test_cli_hedging.py --ignore=tests/test_cli_score.py` — no regressions

---

## Status
done

## Handoff Note (2026-02-28)
Implementation complete. All 6 deliverables shipped:

1. **`tradingagents/graph/market_ignorance.py`** (NEW) — `compute_market_ignorance()` with 7-day AKG cache, yfinance fetch, fallback to centrality proxy. Returns 1.0 immediately for tickers not in AKG._nodes.

2. **`tradingagents/graph/structural_forces.py`** — `derive_dark_matter()` now imports and calls `compute_market_ignorance()` per ticker. Removed old centrality-proxy inline logic.

3. **`tradingagents/graph/knowledge_graph.py`** — 4 new fields in `_node_template()` (`market_ignorance_score_real`, `analyst_count`, `institutional_pct`, `market_ignorance_cached_at`) and in `_backfill_node_defaults()`.

4. **`tradingagents/default_config.py`** — Added `"market_ignorance_cache_ttl_days": 7`.

5. **`cli/commands/forces.py`** — Added `--enrich/--no-enrich` flag to `forces dark-matter` command. Shows analyst_count + institutional_pct columns when enriched.

6. **`tests/test_market_ignorance.py`** (NEW) — 12 tests (9 from spec + 3 supplementary). All 12 pass.

**Regressions:** Zero. The 2 affected existing structural_forces tests (test_ticker_in_akg_gets_computed_ignorance, test_discovery_score_with_akg_centrality) were updated with `monkeypatch` to force yfinance fallback, preserving centrality-proxy test semantics.

## Priority
HIGH — without this, discovery_score reflects our attention not the market's blindness. The entire dark matter thesis depends on correctly identifying what institutional capital hasn't found yet.
