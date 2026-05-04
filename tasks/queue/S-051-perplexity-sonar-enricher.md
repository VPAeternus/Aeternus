# Task: S-051

## Tier
sonnet

## Summary
Perplexity `sonar` enricher — for HABITABLE-tier AKG nodes (high emergence score, unscored), fetch a 2-3 paragraph briefing via Perplexity sonar (~$0.003/call). Cached 30 days on the AKG node. Opt-in, scheduled, cost-capped at top-5 nodes per run.

## Context
**Depends on S-050/S-050b being complete.** No other dependencies.

**The gap:** After cluster detection and theme naming, we know *which* sectors are lighting up and *which* tickers inside them are rising. But we have zero narrative context — who are their customers? What supply chains are they part of? Why now? A $0.003 Perplexity sonar call per high-conviction node answers these in seconds and stores the answer for 30 days.

**What sonar returns:** Perplexity searches the web and synthesizes 2-3 paragraphs covering: what the company does, key supply chain relationships, and the most significant recent catalyst. This is stored as `perplexity_enrichment` on the AKG node and is available to the research pipeline when the stock is scored.

**Cost arithmetic:**
- `sonar` model: ~$0.003/call
- Top-5 nodes per scheduler run × $0.003 = **$0.015/run max**
- 30-day TTL per node = each node enriched at most once per month
- Monthly ceiling: ~$0.45 (5 new HABITABLE nodes/day × $0.003 × 30 days = $0.45/month worst case)

**Gate:** `akg_perplexity_enabled: False` by default. Requires `PERPLEXITY_API_KEY` in env. Opt-in only.

**Key files to read before touching:**
- `tradingagents/graph/knowledge_graph.py` — read FULLY. Current test count: 158.
- `tradingagents/dealflow/scheduler.py` — read FULLY. Understand `run_once()` and how `_maybe_run_cashtag_enricher()` is structured. S-050b already wired naming into that method.
- `tradingagents/dataflows/xai.py` — use as a pattern for `perplexity.py`.

## Requirements

### 1. New file: `tradingagents/dataflows/perplexity.py`

```python
"""Perplexity sonar connector for AKG enrichment (S-051)."""
from __future__ import annotations
import os
from typing import Optional


def get_company_enrichment(
    ticker: str,
    display_name: str,
    sector_display: str,
    velocity_z: float = 0.0,
) -> Optional[str]:
    """
    Call Perplexity sonar for a 2-3 paragraph company briefing.
    Returns enrichment text or None on any failure.

    Cost: ~$0.003/call (sonar model).
    Requires PERPLEXITY_API_KEY in environment.
    """
    api_key = os.environ.get("PERPLEXITY_API_KEY", "").strip()
    if not api_key:
        return None

    prompt = (
        f"Company: {display_name} ({ticker}) | Sector: {sector_display}\n\n"
        f"Provide a concise 2-3 paragraph briefing:\n"
        f"1. What this company does and why it is gaining momentum in the {sector_display} sector\n"
        f"2. Key supply chain relationships (main customers, suppliers, partners)\n"
        f"3. Most significant recent development or catalyst\n\n"
        f"Be factual and brief. Focus on what makes this company notable right now."
    )

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://api.perplexity.ai")
        resp = client.chat.completions.create(
            model="sonar",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0.2,
        )
        text = resp.choices[0].message.content.strip()
        return text if text else None
    except Exception:
        return None
```

### 2. New fields on company nodes in `_node_template()` (knowledge_graph.py)

Add after the S-050b theme naming block:
```python
# Perplexity enrichment cache (S-051) — written by scheduler
"perplexity_enrichment": None,      # str: enrichment text from sonar
"perplexity_enriched_at": None,     # ISO date string
```

### 3. Add to `_backfill_node_defaults()` (knowledge_graph.py)

Add both fields to `_none_fields`:
```python
"perplexity_enrichment",
"perplexity_enriched_at",
```

### 4. New methods (knowledge_graph.py)

```python
def set_perplexity_enrichment(self, ticker: str, text: str) -> None:
    """Cache Perplexity sonar enrichment on AKG node."""
    if ticker not in self._nodes:
        self.add_node(ticker, node_type="company")
    node = self._nodes[ticker]
    node["perplexity_enrichment"] = text
    node["perplexity_enriched_at"] = dt.date.today().isoformat()

def get_perplexity_enrichment(self, ticker: str, ttl_days: int = 30) -> str | None:
    """
    Return cached enrichment text if within TTL, else None.
    Returns None for missing nodes, no enrichment, or expired TTL.
    """
    if ticker not in self._nodes:
        return None
    node = self._nodes[ticker]
    text = node.get("perplexity_enrichment")
    fetched_at = node.get("perplexity_enriched_at")
    if not text or not fetched_at:
        return None
    try:
        fetched = dt.date.fromisoformat(fetched_at)
        if (dt.date.today() - fetched).days > ttl_days:
            return None
    except (ValueError, TypeError):
        return None
    return text
```

`dt` is already imported in knowledge_graph.py as `import datetime as dt`.

### 5. New scheduler method: `_maybe_run_perplexity_enricher()` (scheduler.py)

Read the existing `_maybe_run_cashtag_enricher()` and `_maybe_run_sector_scout()` methods as patterns. Follow the same structure: config gate → no_akg check → interval gate → do work → update state → return result dict.

```python
def _maybe_run_perplexity_enricher(self, state: dict, now_utc, run_date: str) -> dict:
    """
    Enrich top HABITABLE AKG nodes with Perplexity sonar briefings.
    Gate: akg_perplexity_enabled=False. Cost: ~$0.003/node.
    Runs at most once per akg_perplexity_enricher_interval_h hours (default 24h).
    """
    if not self.config.get("akg_perplexity_enabled", False):
        return {"ran": False, "reason": "disabled"}
    if not self.akg:
        return {"ran": False, "reason": "no_akg"}

    # Interval gate
    last_ts = state.get("last_perplexity_enricher_ts")
    interval_h = float(self.config.get("akg_perplexity_enricher_interval_h", 24))
    if last_ts:
        elapsed_h = (now_utc - last_ts).total_seconds() / 3600
        if elapsed_h < interval_h:
            return {"ran": False, "reason": f"last run {elapsed_h:.1f}h ago, interval={interval_h}h"}

    top_k = int(self.config.get("akg_perplexity_top_k", 5))
    min_score = float(self.config.get("akg_perplexity_min_emergence", 0.5))
    ttl_days = int(self.config.get("akg_perplexity_ttl_days", 30))

    # Find HABITABLE nodes that need enrichment (sorted by emergence_score desc)
    candidates = [
        (nid, n) for nid, n in self.akg._nodes.items()
        if n.get("node_type") == "company"
        and (n.get("emergence_score") or 0.0) >= min_score
        and self.akg.get_perplexity_enrichment(nid, ttl_days) is None
    ]
    candidates.sort(key=lambda x: x[1].get("emergence_score") or 0.0, reverse=True)
    candidates = candidates[:top_k]

    if not candidates:
        return {"ran": False, "reason": "no_candidates"}

    from tradingagents.dataflows.perplexity import get_company_enrichment
    enriched = 0
    for ticker, node in candidates:
        sector_id = node.get("sector") or ""
        sector_node = self.akg._nodes.get(sector_id, {})
        sector_display = sector_node.get("display_name") or sector_id.replace("_", " ").title()

        text = get_company_enrichment(
            ticker=ticker,
            display_name=node.get("display_name") or ticker,
            sector_display=sector_display,
            velocity_z=float(node.get("velocity_z") or 0.0),
        )
        if text:
            self.akg.set_perplexity_enrichment(ticker, text)
            enriched += 1

    if enriched:
        self.akg.save()

    state["last_perplexity_enricher_ts"] = now_utc
    state["last_perplexity_enricher_count"] = enriched
    return {"ran": True, "enriched": enriched, "checked": len(candidates)}
```

### 6. Wire into `run_once()` (scheduler.py)

In `run_once()`, after the cashtag enricher call, add:
```python
self._maybe_run_perplexity_enricher(state, now_utc, run_date)
```

Read `run_once()` fully before inserting. Fit within the existing pattern.

### 7. Config keys in `default_config.py`

```python
"akg_perplexity_enabled": False,              # opt-in: requires PERPLEXITY_API_KEY
"akg_perplexity_top_k": 5,                   # max nodes to enrich per run
"akg_perplexity_min_emergence": 0.5,         # min emergence_score to qualify
"akg_perplexity_enricher_interval_h": 24,    # hours between enricher runs
"akg_perplexity_ttl_days": 30,               # days before re-enriching same node
```

## Files to Touch
- `tradingagents/dataflows/perplexity.py` — new file
- `tradingagents/graph/knowledge_graph.py` — new fields + `set_perplexity_enrichment()` + `get_perplexity_enrichment()`
- `tradingagents/dealflow/scheduler.py` — `_maybe_run_perplexity_enricher()` + wire into `run_once()`
- `tradingagents/default_config.py` — 5 new config keys
- `tests/test_knowledge_graph.py` — tests for new methods

## Tests

Add to `tests/test_knowledge_graph.py`:

1. `set_perplexity_enrichment(ticker, text)` writes enrichment + today's date to node
2. `get_perplexity_enrichment(ticker, ttl_days=30)` returns text when within TTL
3. `get_perplexity_enrichment()` returns None for missing node
4. `get_perplexity_enrichment()` returns None when no enrichment set
5. `get_perplexity_enrichment()` returns None when TTL expired (set fetched_at to old date)
6. `_backfill_node_defaults()` fills `perplexity_enrichment` and `perplexity_enriched_at` as None

For the `get_company_enrichment()` function in `perplexity.py`, add a test in a new file `tests/test_perplexity_dataflow.py` (keep it separate from knowledge_graph tests):

7. Returns None when PERPLEXITY_API_KEY not set
8. Returns text on successful mock response
9. Returns None on API exception

For tests 8-9, mock `openai.OpenAI` the same way as S-050b mocked xAI.

## Acceptance Criteria
- [ ] `tradingagents/dataflows/perplexity.py` exists with `get_company_enrichment()`
- [ ] Returns None gracefully when PERPLEXITY_API_KEY missing
- [ ] Returns None on any API exception
- [ ] `set_perplexity_enrichment()` writes enrichment text + today's date to AKG node
- [ ] `get_perplexity_enrichment()` returns None for missing node, no enrichment, or expired TTL
- [ ] `get_perplexity_enrichment()` returns cached text within TTL
- [ ] `_backfill_node_defaults()` fills new fields
- [ ] `_maybe_run_perplexity_enricher()` returns `{"ran": False, "reason": "disabled"}` when `akg_perplexity_enabled=False`
- [ ] `_maybe_run_perplexity_enricher()` respects interval gate
- [ ] `_maybe_run_perplexity_enricher()` only enriches nodes with `emergence_score >= min_score` and no fresh cached enrichment
- [ ] `run_once()` calls `_maybe_run_perplexity_enricher()` after cashtag enricher
- [ ] `python -m pytest tests/test_knowledge_graph.py -v` — all pass
- [ ] `python -m pytest tests/test_perplexity_dataflow.py -v` — all pass
- [ ] `python -m pytest tests/ -v --ignore=tests/test_cli_dealflow.py --ignore=tests/test_cli_hedging.py --ignore=tests/test_cli_score.py` — no regressions

## Status
done

## Handoff

Completed 2026-02-26 by Sonnet. 6 new tests in test_knowledge_graph.py (164 total), 3 new tests in test_perplexity_dataflow.py. Zero regressions. Default akg_perplexity_enabled=False — opt-in. Wired into run_once() after cashtag enricher.
