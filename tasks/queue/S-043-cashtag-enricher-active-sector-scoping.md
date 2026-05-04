# Task: S-043

## Tier
sonnet

## Summary
Scope cashtag enricher to ACTIVE sectors only — when themes are dormant, enrichment cost drops to $0 automatically.

## Context
**Depends on S-040 being complete.** S-041/S-042 run parallel to this.

**Current state of `cashtag_enricher.py`:** Enriches top-N company nodes by centrality, regardless of which sectors are active. If all themes are dormant, it still runs on N nodes.

**Target state:** Only enrich company nodes that belong to ACTIVE sectors (as determined by `akg.get_active_sector_ids()`). When all themes are dormant → enrichment list is empty → scanner returns immediately → zero xAI calls.

**Also:** Outlier path for inactive-sector nodes. If a company node is in an INACTIVE sector but has very high cashtag velocity (e.g., velocity_z >= 3.0), don't enrich it, but log it as an outlier for review (same pattern as S-042).

**Key file:** `tradingagents/dealflow/sources/cashtag_enricher.py` — read the full file before changing anything. Follow existing patterns.

## Requirements

### 1. Active-sector filtering in enrichment candidate selection

In `enrich_akg_with_cashtags()`, after pulling top-N nodes by centrality, filter to active sectors:

```python
active_sector_ids = akg.get_active_sector_ids()
if not active_sector_ids:
    return {
        "ran": False,
        "reason": "no_active_sectors",
        "enriched_count": 0,
        "skipped_inactive_sector": 0,
    }

# Filter candidate nodes to active sectors only
candidates = [
    n for n in top_n_nodes
    if n.get("sector") in active_sector_ids
]
skipped_inactive = len(top_n_nodes) - len(candidates)
```

Include `"skipped_inactive_sector": skipped_inactive` in the return dict.

### 2. Outlier detection for high-velocity inactive-sector nodes

After filtering, scan excluded nodes for outliers:
```python
outlier_threshold = float(config.get("cashtag_enricher_outlier_velocity_z", 3.0))
outliers = []
for n in top_n_nodes:
    if n.get("sector") not in active_sector_ids:
        vz = n.get("cashtag_velocity_z") or 0.0
        if vz >= outlier_threshold:
            outliers.append({"ticker": n["id"], "sector": n.get("sector"), "velocity_z": vz})
            # Don't enrich — just flag
            akg.update_node_field(n["id"], "cashtag_outlier_flagged", True)
```

Include `"outlier_count": len(outliers)` in return dict.

### 3. Config key
```python
"cashtag_enricher_outlier_velocity_z": 3.0,
```

Add to `tradingagents/default_config.py` if not already present.

### 4. Result dict updates
The returned dict should now include:
```python
{
    "ran": bool,
    "enriched_count": int,
    "skipped_stale": int,
    "skipped_no_data": int,
    "skipped_inactive_sector": int,  # NEW
    "outlier_count": int,            # NEW
    "symbols_enriched": list[str],
    "reason": str | None,            # for early-return cases
}
```

## Files to Touch
- `tradingagents/dealflow/sources/cashtag_enricher.py` — active-sector filter + outlier path
- `tradingagents/default_config.py` — `cashtag_enricher_outlier_velocity_z` if not present

## Acceptance Criteria
- [ ] When `akg.get_active_sector_ids()` returns empty set → returns `{"ran": False, "reason": "no_active_sectors"}` immediately
- [ ] When active sectors exist → only enriches nodes whose `sector` field is in active sector IDs
- [ ] Outlier nodes (inactive sector, high velocity_z) get `cashtag_outlier_flagged=True` set on AKG node but are NOT enriched
- [ ] `skipped_inactive_sector` count in return dict is accurate
- [ ] Pre-existing tests all pass (they mock `get_active_sector_ids` as returning a set with the test sector)
- [ ] New tests cover: all sectors inactive (early return), mixed active/inactive sectors (correct filtering), outlier flagging
- [ ] `python -m pytest tests/test_cashtag_enricher.py -v` — all pass
- [ ] `python -m pytest tests/ -v --ignore=tests/test_cli_dealflow.py --ignore=tests/test_cli_hedging.py --ignore=tests/test_cli_score.py` — no regressions

## Status
done

---

## Handoff

**Work Done:**
- Added `cashtag_enricher_outlier_velocity_z: 3.0` to `tradingagents/default_config.py` (env-var overridable via `CASHTAG_ENRICHER_OUTLIER_VELOCITY_Z`).
- Modified `enrich_akg_with_cashtags()` in `tradingagents/dealflow/sources/cashtag_enricher.py`:
  - After computing top-N by centrality, calls `akg.get_active_sector_ids()`.
  - If empty → returns `{"ran": False, "reason": "no_active_sectors", ...}` immediately (zero xAI calls).
  - Filters `top_n_nodes` to only those whose `sector` is in active sector IDs.
  - Scans excluded (inactive-sector) nodes for outliers: if `cashtag_velocity_z >= cashtag_enricher_outlier_velocity_z`, calls `akg.update_node_field(ticker, "cashtag_outlier_flagged", True)` but does NOT enrich them.
  - Return dict now includes `skipped_inactive_sector` and `outlier_count` fields.
- Updated `_FakeAKG` in `tests/test_cashtag_enricher.py`:
  - Added `active_sector_ids` constructor param (defaults to `{"test_sector"}`).
  - Added `get_active_sector_ids()` and `update_node_field()` methods with call tracking.
- Updated `_company_node` helper to accept `sector` (default `"test_sector"`) and `cashtag_velocity_z` params so existing tests work without changes.
- Added 3 new tests:
  - `test_enrich_akg_no_active_sectors_early_return` — empty sector set → early return.
  - `test_enrich_akg_filters_inactive_sector_nodes` — mixed active/inactive → only active enriched, `skipped_inactive_sector=1`.
  - `test_enrich_akg_outlier_flagged_for_high_velocity_inactive_node` — inactive sector + velocity_z=4.5 → outlier flagged, NOT enriched.
- All 11 tests pass. No regressions in broader suite (1260 passed; 4 pre-existing failures unrelated to these changes).

**Learnings:**
- Defaulting `_FakeAKG._active_sector_ids` to a non-empty set (`{"test_sector"}`) and `_company_node` sector to `"test_sector"` is the cleanest way to maintain backward compatibility for pre-existing tests without touching each test individually.

**Follow-ups:**
- None. S-041/S-042 run in parallel to this task.
