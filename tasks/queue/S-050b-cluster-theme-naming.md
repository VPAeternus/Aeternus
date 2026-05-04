# Task: S-050b

## Tier
sonnet

## Summary
When `detect_clusters()` finds a new cluster candidate, make a single cheap xAI call (~$0.001) to name the emerging theme and write a one-sentence hypothesis to the sector node. This is the last free-standing piece before Perplexity enrichment (S-051).

## Context
**Depends on S-050 being complete** (which adds `detect_clusters()` and `cluster_candidate` fields to sector nodes).

**The gap:** After S-050, we know *which* sectors have rising connected components — but the sector node's name ("semis_ai_infrastructure") is a technical ID, not a human-readable theme. A trader can't act on "cluster_candidate=True in semis_ai_infrastructure." They need "AI Inference Edge Computing" or "HBM Memory Supercycle."

**One cheap xAI call per new candidate.** Not per enricher run — only when a sector transitions to `cluster_candidate=True` for the first time (or the cluster re-strengthens significantly after being quiet).

**Cost control:**
- Model: `grok-3-mini` — cheapest xAI model ($0.30/$0.50/M in/out)
- Prompt: ~150 input tokens max, response capped at 80 tokens
- Cost per call: ~$0.0001 (0.01 cents) — negligible
- Gate: `akg_cluster_naming_enabled: False` by default. Opt-in.
- Idempotency: if `cluster_theme_name` already set and `cluster_strength` hasn't risen by >0.1 since last naming, skip the call.

**Key files:**
- `tradingagents/graph/knowledge_graph.py` — new fields + `name_cluster_theme()` method
- `tradingagents/dealflow/scheduler.py` — call `name_cluster_theme()` after `detect_clusters()`
- `tradingagents/default_config.py` — `akg_cluster_naming_enabled: False`
- `tests/test_knowledge_graph.py` — tests (mock xAI call)

**Read fully before editing:** `tradingagents/dataflows/xai.py` (for xAI client pattern), `tradingagents/dealflow/scheduler.py`, `tradingagents/graph/knowledge_graph.py`.

## Requirements

### 1. New fields on sector nodes in `_node_template()` (knowledge_graph.py)

Add after the S-050 cluster detection fields:
```python
# Theme naming fields (S-050b) — written by name_cluster_theme()
"cluster_theme_name": None,        # str: human-readable theme name ("AI Inference Edge")
"cluster_theme_hypothesis": None,  # str: 1-sentence thesis
"cluster_theme_named_at": None,    # ISO date string
"cluster_theme_strength_at_naming": 0.0,  # float: cluster_strength when named (for re-naming gate)
```

### 2. Add to `_backfill_node_defaults()` (knowledge_graph.py)

Add to `_none_fields` list:
```python
"cluster_theme_name",
"cluster_theme_hypothesis",
"cluster_theme_named_at",
```

And to non-None defaults section:
```python
if "cluster_theme_strength_at_naming" not in node:
    node["cluster_theme_strength_at_naming"] = 0.0
```

### 3. New method `name_cluster_theme()` (knowledge_graph.py)

```python
def name_cluster_theme(
    self,
    sector_id: str,
    tickers: list,
    strength: float,
    rename_threshold: float = 0.1,
) -> dict | None:
    """
    Call xAI grok-3-mini to name an emerging cluster theme.

    Args:
        sector_id: AKG sector node ID (e.g. "semis_ai_infrastructure")
        tickers: list of rising ticker symbols in the cluster
        strength: current cluster_strength
        rename_threshold: only re-name if strength has risen by this much since last naming

    Returns:
        {"theme_name": str, "hypothesis": str} if call succeeds, None otherwise.
        Also writes result directly to the sector node.
    """
    if sector_id not in self._nodes:
        return None

    s_node = self._nodes[sector_id]

    # Idempotency gate: skip if already named and strength hasn't risen enough
    last_strength = s_node.get("cluster_theme_strength_at_naming") or 0.0
    if s_node.get("cluster_theme_name") and (strength - last_strength) < rename_threshold:
        return None  # Already named, not strong enough to re-name

    # Build prompt
    ticker_str = ", ".join(tickers[:10])  # cap at 10 tickers for token budget
    display_name = s_node.get("display_name") or sector_id
    prompt = (
        f"These stocks are showing correlated rising momentum in the {display_name} sector: {ticker_str}. "
        f"In JSON, return exactly: {{\"theme_name\": \"<3-6 word theme name>\", \"hypothesis\": \"<1 sentence thesis>\"}}"
    )

    try:
        import os
        from openai import OpenAI
        api_key = os.environ.get("XAI_API_KEY", "").strip()
        if not api_key or api_key.startswith("your_"):
            return None
        client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
        resp = client.chat.completions.create(
            model="grok-3-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=80,
            temperature=0.3,
        )
        raw = resp.choices[0].message.content.strip()
        import json, re
        # Extract JSON from response (model may add markdown fences)
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group())
        theme_name = str(data.get("theme_name", "")).strip()
        hypothesis = str(data.get("hypothesis", "")).strip()
        if not theme_name:
            return None

        # Write to sector node
        import datetime as dt
        s_node["cluster_theme_name"] = theme_name
        s_node["cluster_theme_hypothesis"] = hypothesis
        s_node["cluster_theme_named_at"] = dt.date.today().isoformat()
        s_node["cluster_theme_strength_at_naming"] = strength
        return {"theme_name": theme_name, "hypothesis": hypothesis}

    except Exception:
        return None
```

### 4. Wire into scheduler (`tradingagents/dealflow/scheduler.py`)

In `_maybe_run_cashtag_enricher()`, after `detect_clusters()` already fires, add theme naming for each candidate. The config gate uses `akg_cluster_naming_enabled`.

After the existing cluster detection logging block:
```python
# Theme naming (S-050b) — cheap xAI call per new candidate
if cluster_candidates and self.config.get("akg_cluster_naming_enabled", False):
    import logging
    _log = logging.getLogger(__name__)
    for c in cluster_candidates:
        # Collect rising tickers for this sector
        sector_id = c["sector_id"]
        tickers = [
            n.get("display_name") or nid
            for nid, n in self.akg._nodes.items()
            if n.get("node_type") == "company"
            and n.get("sector") == sector_id
            and (n.get("emergence_score") or 0.0) >= 0.2
        ][:10]
        result = self.akg.name_cluster_theme(
            sector_id=sector_id,
            tickers=tickers,
            strength=c["cluster_strength"],
        )
        if result:
            _log.info(
                "AKG cluster theme named: sector=%s name=%r",
                sector_id, result["theme_name"]
            )
    self.akg.save()
```

**Read `_maybe_run_cashtag_enricher()` carefully before inserting.** Fit within the existing save pattern — don't add a second `self.akg.save()` if one already follows cluster detection. Just append the naming block before the existing save.

### 5. Config key in `default_config.py`

```python
"akg_cluster_naming_enabled": False,  # opt-in: cheap xAI call to name detected clusters
```

Note: `False` by default because it requires `XAI_API_KEY`. Users enable it when they want theme names.

## Files to Touch
- `tradingagents/graph/knowledge_graph.py` — new fields, `name_cluster_theme()` method, backfill
- `tradingagents/dealflow/scheduler.py` — wire naming after cluster detection
- `tradingagents/default_config.py` — `akg_cluster_naming_enabled: False`
- `tests/test_knowledge_graph.py` — tests (mock xAI call)

## Acceptance Criteria
- [ ] `cluster_theme_name`, `cluster_theme_hypothesis`, `cluster_theme_named_at`, `cluster_theme_strength_at_naming` present in `_node_template()`
- [ ] `_backfill_node_defaults()` fills new fields on older AKG JSON nodes
- [ ] `name_cluster_theme()` returns `None` gracefully if XAI_API_KEY missing
- [ ] `name_cluster_theme()` skips re-naming if theme already set and strength < rename_threshold
- [ ] `name_cluster_theme()` writes `cluster_theme_name`, `cluster_theme_hypothesis`, `cluster_theme_named_at`, `cluster_theme_strength_at_naming` to sector node on success
- [ ] `name_cluster_theme()` returns `None` (does not raise) on any xAI exception
- [ ] Scheduler calls `name_cluster_theme()` for each candidate only when `akg_cluster_naming_enabled=True`
- [ ] `python -m pytest tests/test_knowledge_graph.py -v` — all pass
- [ ] `python -m pytest tests/ -v --ignore=tests/test_cli_dealflow.py --ignore=tests/test_cli_hedging.py --ignore=tests/test_cli_score.py` — no regressions

## Status
done

## Handoff

Completed 2026-02-26 by Sonnet. 6 new tests. 158 total tests passing. Zero regressions. Key detail: `self.akg.save()` restructured to fire after both cluster detection AND theme naming (single atomic write). Default `akg_cluster_naming_enabled: False` — opt-in when XAI_API_KEY is available.
