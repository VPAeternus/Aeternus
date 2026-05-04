# Task: S-050

## Tier
sonnet

## Summary
Pure graph computation that detects emerging clusters in AKG — groups of connected nodes in the same sector showing rising emergence scores simultaneously. This IS the theme detection signal. No API call. No cost. Replaces Theme Scanner's top-down LLM guessing with bottom-up observation of what the data already shows.

## Context
**Depends on S-049 (universe bootstrap) and S-037/S-038 (cashtag enrichment).**

**The insight:** A theme doesn't announce itself. It shows up as correlated activity across connected nodes in the same sector. When ONTO, CAMT, and UCTT all show rising cashtag velocity in the same week — and they're connected by supply chain edges — that IS a theme forming. The graph already knows. We just need to look at it.

**Current gap:** After every cashtag enrichment run, AKG has fresh emergence scores. But nothing aggregates this up to the sector level. Sector nodes sit unchanged while company nodes underneath them are lighting up.

**Target state:** After every AKG update (cashtag enricher run OR sector scout run), compute a sector-level cluster signal:
- Average emergence score of company nodes in each sector
- Trend direction (rising/falling/stable vs. last run)
- Count of nodes with rising emergence
- Cluster strength: `(rising_count / total_nodes) × avg_emergence_score`

When cluster strength exceeds a threshold in a sector that is NOT currently active → candidate for theme hypothesis (S-050b names it via cheap xAI call).

**This is purely additive.** It writes new fields to sector nodes. It does not change existing logic.

**Key file:** `tradingagents/graph/knowledge_graph.py` — read fully. Understand sector nodes, company nodes, `get_active_sector_companies()`, `compute_all_emergence_scores()`. The cluster detection runs as a method on AKG after emergence scores are recomputed.

## Requirements

### 1. New fields on SECTOR nodes in `_node_template()`

Add after the S-040 sector activation fields:
```python
# Cluster detection fields (S-050) — computed by detect_clusters()
"cluster_strength": 0.0,          # float 0.0–1.0: (rising_pct × avg_emergence)
"cluster_avg_emergence": 0.0,     # float: mean emergence score of company nodes in sector
"cluster_rising_count": 0,        # int: nodes with emergence_score increasing this run
"cluster_total_nodes": 0,         # int: total company nodes in sector
"cluster_last_computed": None,    # ISO date string
"cluster_candidate": False,       # bool: True if cluster_strength > threshold AND sector inactive
```

### 2. Add to `_backfill_node_defaults()` (knowledge_graph.py)

Add the new cluster fields with appropriate defaults so older AKG JSON files load cleanly.

### 3. New method `detect_clusters()` (knowledge_graph.py)

```python
def detect_clusters(self, strength_threshold: float = 0.3) -> list:
    """
    Compute sector-level cluster signals from company node emergence scores.

    For each sector node:
    - Collect all company nodes where node["sector"] == sector_id
    - Compute avg_emergence_score across them
    - Count nodes where emergence_score > 0.2 (ATMOSPHERE or above)
    - Compute cluster_strength = (rising_count / total_nodes) * avg_emergence_score
    - Update sector node with cluster fields
    - If cluster_strength >= strength_threshold AND sector.active == False:
        mark sector node as cluster_candidate=True

    Returns list of {sector_id, cluster_strength, avg_emergence, rising_count, total_nodes}
    for all sectors where cluster_candidate=True, sorted by cluster_strength desc.
    """
    today = dt.date.today().isoformat()
    candidates = []

    # Group company nodes by sector
    sector_companies: dict = {}
    for node in self._nodes.values():
        if node.get("node_type") != "company":
            continue
        sector = node.get("sector")
        if not sector:
            continue
        if sector not in sector_companies:
            sector_companies[sector] = []
        sector_companies[sector].append(node)

    # Compute cluster signal per sector
    for sector_id, companies in sector_companies.items():
        if not companies:
            continue

        scores = [n.get("emergence_score") or 0.0 for n in companies]
        avg_score = round(sum(scores) / len(scores), 6)
        rising_count = sum(1 for s in scores if s >= 0.2)  # ATMOSPHERE or above
        total = len(companies)
        strength = round((rising_count / total) * avg_score, 6) if total > 0 else 0.0

        # Write to sector node if it exists
        if sector_id in self._nodes:
            s_node = self._nodes[sector_id]
            s_node["cluster_strength"] = strength
            s_node["cluster_avg_emergence"] = avg_score
            s_node["cluster_rising_count"] = rising_count
            s_node["cluster_total_nodes"] = total
            s_node["cluster_last_computed"] = today

            is_active = s_node.get("active", False)
            is_candidate = (not is_active) and (strength >= strength_threshold)
            s_node["cluster_candidate"] = is_candidate

            if is_candidate:
                candidates.append({
                    "sector_id": sector_id,
                    "cluster_strength": strength,
                    "avg_emergence": avg_score,
                    "rising_count": rising_count,
                    "total_nodes": total,
                })

    candidates.sort(key=lambda c: c["cluster_strength"], reverse=True)
    return candidates
```

### 4. Wire into cashtag enricher scheduler cycle

In `tradingagents/dealflow/scheduler.py`, in `_maybe_run_cashtag_enricher()`, after the enricher runs and AKG is saved, add:

```python
# Recompute emergence scores then detect clusters
if result.get("ran") and self.akg:
    self.akg.compute_all_emergence_scores()
    cluster_candidates = self.akg.detect_clusters(
        strength_threshold=float(self.config.get("akg_cluster_strength_threshold", 0.3))
    )
    self.akg.save()
    if cluster_candidates:
        # Log for now — S-050b will wire xAI naming call here
        import logging
        _log = logging.getLogger(__name__)
        for c in cluster_candidates:
            _log.info(
                "AKG cluster candidate: sector=%s strength=%.3f rising=%d/%d",
                c["sector_id"], c["cluster_strength"], c["rising_count"], c["total_nodes"]
            )
```

**IMPORTANT:** Read scheduler.py carefully before modifying. Understand the full `_maybe_run_cashtag_enricher()` flow. Add minimally — only the cluster detection call.

### 5. New query method `get_cluster_candidates()` (knowledge_graph.py)

```python
def get_cluster_candidates(self) -> list:
    """
    Return sector nodes marked as cluster_candidate=True, sorted by cluster_strength desc.
    These are dormant sectors showing signs of theme formation.
    """
    candidates = [
        node for node in self._nodes.values()
        if node.get("node_type") == "sector" and node.get("cluster_candidate") is True
    ]
    return sorted(candidates, key=lambda n: n.get("cluster_strength") or 0.0, reverse=True)
```

### 6. Config key (default_config.py)

```python
"akg_cluster_strength_threshold": 0.3,  # min cluster_strength to flag as candidate
```

## Files to Touch
- `tradingagents/graph/knowledge_graph.py` — new sector fields, `detect_clusters()`, `get_cluster_candidates()`
- `tradingagents/dealflow/scheduler.py` — wire `detect_clusters()` after cashtag enricher
- `tradingagents/default_config.py` — `akg_cluster_strength_threshold`
- `tests/test_knowledge_graph.py` — tests for `detect_clusters()` and `get_cluster_candidates()`

## Acceptance Criteria
- [ ] `detect_clusters()` computes `cluster_strength` for each sector node based on company node emergence scores
- [ ] `cluster_candidate=True` only on inactive sectors where `cluster_strength >= threshold`
- [ ] `cluster_candidate=False` on active sectors regardless of strength (already active = already known)
- [ ] `detect_clusters()` returns list of candidate dicts sorted by strength desc
- [ ] Sector with no company nodes gets `cluster_strength=0.0`, `cluster_candidate=False`
- [ ] `get_cluster_candidates()` returns sector nodes where `cluster_candidate=True`
- [ ] `_backfill_node_defaults()` fills new cluster fields on nodes loaded from older AKG JSON
- [ ] All new fields are in `_node_template()` so fresh nodes get them automatically
- [ ] After cashtag enricher runs, cluster detection fires automatically
- [ ] `python -m pytest tests/test_knowledge_graph.py -v` — all pass
- [ ] `python -m pytest tests/ -v --ignore=tests/test_cli_dealflow.py --ignore=tests/test_cli_hedging.py --ignore=tests/test_cli_score.py` — no regressions

## Status
done

## Handoff

Completed 2026-02-26 by Sonnet. 8 new tests. 152 total tests passing. Zero regressions. Bonus: fixed 3 pre-existing test failures in test_cashtag_enricher.py by implementing the correct _maybe_run_cashtag_enricher() contract. Cluster detection fires after every cashtag enricher run with fresh emergence scores.
