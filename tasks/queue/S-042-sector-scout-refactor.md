# Task: S-042

## Tier
sonnet

## Summary
Refactor sector_scout.py to only sweep ACTIVE sectors (Phase B of two-phase scout) and add bottom-up outlier detection for inactive sector spikes.

## Context
**Depends on S-040 being complete.** S-041 (theme scanner) runs parallel to this — S-042 does NOT depend on S-041.

**Current state of `sector_scout.py`:** Sweeps a hardcoded list of 8 sectors on every run, regardless of whether those sectors have active themes. 8 xAI x_search calls/day, blind.

**Target state:** Scout only sweeps sectors where `akg.get_active_sectors()` returns active. If only 2 sectors are active, only 2 calls fire. If no sectors are active (all themes dormant), the scout does nothing.

**Additional job:** Bottom-up outlier detection. If cashtag velocity_z is very high for a company in an INACTIVE sector, that's potentially a signal that a new theme is forming before we've classified it. Flag it — don't enrich it, just mark it in AKG for the user to review.

**Key file:** `tradingagents/dealflow/sources/sector_scout.py` — read the full file before touching anything. Understand the existing flow, prompt structure, and how it writes to AKG.

**Pattern constraint:** Follow existing sector_scout.py style exactly. Don't add abstractions that don't exist there. Keep the rate-limit guard, the config gate, and the result dict return.

## Requirements

### 1. Active-sector scoping

In `scan_sectors()` (or equivalent entry function), replace the hardcoded sector list with:
```python
active_sectors = akg.get_active_sectors()
if not active_sectors:
    return {"ran": False, "reason": "no_active_sectors"}
sector_ids_to_scan = [s["id"] for s in active_sectors]
```

For each active sector, only call xAI x_search for that sector (not all 8).

### 2. Saturation-aware prompt injection

Before calling xAI for each sector, pull existing company nodes in that sector:
```python
existing_symbols = [
    n["id"] for n in akg.get_active_sector_companies(sector_id)
]
```

Inject into prompt:
```
We already track these companies in {sector_name}: {', '.join(existing_symbols)}.
Find NEW supply chain beneficiaries NOT already in this list.
Focus on: secondary suppliers, component manufacturers, service providers within active theme: {theme_names}.
```

This prevents re-surfacing NVDA when we already have it, and guides discovery toward planets not already in the AKG.

### 3. Bottom-up outlier detection

After the main sector sweep, add an outlier scan:
```python
def _detect_inactive_sector_outliers(akg, config) -> list:
    """
    Find company nodes in INACTIVE sectors with high cashtag velocity.
    High velocity in a dormant sector = potential new theme forming.
    Returns list of {ticker, sector, velocity_z, flag_reason} dicts.
    """
    active_sector_ids = akg.get_active_sector_ids()
    outliers = []
    threshold = float(config.get("sector_scout_outlier_velocity_z", 3.0))
    for node in akg.get_nodes_by_type("company"):
        sector = node.get("sector")
        if sector and sector not in active_sector_ids:
            vz = node.get("cashtag_velocity_z") or 0.0
            if vz >= threshold:
                outliers.append({
                    "ticker": node["id"],
                    "sector": sector,
                    "velocity_z": vz,
                    "flag_reason": "high_velocity_in_dormant_sector"
                })
                # Mark in AKG for review — don't enrich, just flag
                akg.update_node_field(node["id"], "sector_outlier_flagged", True)
    return outliers
```

Add `outlier_flags` to the result dict returned by the scanner.

### 4. Add `update_node_field()` to knowledge_graph.py if it doesn't exist
Simple helper:
```python
def update_node_field(self, node_id: str, field: str, value) -> bool:
    """Set a single field on a node. Returns True if node exists."""
    if node_id in self.nodes:
        self.nodes[node_id][field] = value
        return True
    return False
```

### 5. Config key (add to default_config.py if not present)
```python
"sector_scout_outlier_velocity_z": 3.0,  # z-score threshold for dormant-sector outlier flag
```

## Files to Touch
- `tradingagents/dealflow/sources/sector_scout.py` — refactor to active-sector scoping + bottom-up outlier detection
- `tradingagents/graph/knowledge_graph.py` — add `update_node_field()` if not present
- `tradingagents/default_config.py` — add `sector_scout_outlier_velocity_z`

## Acceptance Criteria
- [ ] When `akg.get_active_sectors()` returns empty list → scanner returns `{"ran": False, "reason": "no_active_sectors"}` immediately (zero API calls)
- [ ] When 2 sectors are active → exactly 2 xAI calls (not 8)
- [ ] Existing company nodes in active sector are injected into prompt as "we already track these"
- [ ] Outlier detection finds company nodes in inactive sectors with velocity_z >= threshold
- [ ] `sector_scout_enabled: False` still gates the entire function (no regression)
- [ ] Tests cover: no active sectors (early return), active sectors (mocked API, check prompt injection), outlier detection (mock AKG with dormant sector + high velocity node)
- [ ] `python -m pytest tests/test_sector_scout.py -v` — all pass (including pre-existing)
- [ ] `python -m pytest tests/ -v --ignore=tests/test_cli_dealflow.py --ignore=tests/test_cli_hedging.py --ignore=tests/test_cli_score.py` — no regressions

## Status
done

---

## Handoff

**Work Done:**
- `sector_scout.py`: Added `akg=None` optional param to `collect_sector_scout_signals`. When AKG is provided, pulls `get_active_sectors()` and returns `{"ran": False, "reason": "no_active_sectors"}` immediately if empty (zero API calls). Only active sectors get xAI calls.
- `sector_scout.py`: Added saturation-aware prompt injection in `_sweep_one_sector`. When `akg` is provided, calls `get_active_sector_companies(sector_name)` and prepends "We already track X, Y, Z — find NEW names" to the prompt.
- `sector_scout.py`: Added `_detect_inactive_sector_outliers(akg, config)` helper that iterates `akg.get_nodes_by_type("company")`, skips active-sector nodes, flags company nodes in dormant sectors with `cashtag_velocity_z >= threshold`, calls `akg.update_node_field(ticker, "sector_outlier_flagged", True)`. Result added to `metadata["_outlier_flags"]`.
- `knowledge_graph.py`: Added `get_nodes_by_type(node_type)` method (required by outlier helper). `update_node_field()` was already present from S-040.
- `default_config.py`: Added `sector_scout_outlier_velocity_z: 3.0`.
- `tests/test_sector_scout.py`: Added 4 new tests (11-14): no active sectors early return, active-sector scoping limits call count to 2 not 8, prompt injection of existing symbols, outlier detection with mock AKG.

**Learnings:**
- `get_nodes_by_type()` was referenced in the spec but not yet present in `knowledge_graph.py` — needed to add it alongside `get_active_sectors()` family.
- `update_node_field()` was already added by S-040 — no action needed there.
- Adding `akg=None` as optional param to `collect_sector_scout_signals` preserves full backward compatibility: existing callers without AKG fall through to legacy static-config sector list.

**Follow-ups:**
- None. Spec fully satisfied. AKG-gated scanning is in place.
