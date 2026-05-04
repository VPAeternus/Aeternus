# Task: S-040

## Tier
sonnet

## Summary
Extend AKG knowledge_graph.py with theme/sector activation schema — the cosmological layer that gates all downstream writers.

## Context
The AKG currently stores company nodes, sector nodes, and theme nodes but has no concept of "active" vs "dormant" state. The corrected cosmology requires:
- **Themes** (macro-driven: rate cycles, elections, wars, legislation) activate and deactivate on monthly/quarterly cycles
- **Sectors** are activated *by* themes — when a theme goes live, its dependent sectors become ACTIVE
- **Stock discovery and cashtag enrichment** are gated by sector activation — DORMANT sectors cost $0

This task is purely schema + methods on `knowledge_graph.py`. No scheduler wiring yet (that's S-041+).

**Key files:**
- `tradingagents/graph/knowledge_graph.py` — The AKG class. Understand existing node structure first: `_node_template()`, `add_company_node()`, `add_sector_node()`, `add_theme_node()`, `from_json()`, `to_json()`.
- `tests/test_knowledge_graph.py` — Existing 49 tests all pass. Add new tests to the same file.

**Existing node template (simplified):**
```python
def _node_template(self, node_type: str) -> dict:
    return {
        "node_type": node_type,
        "created_at": ...,
        "centrality": 0.0,
        ...
    }
```

## Requirements

### 1. New activation fields on THEME nodes
When `add_theme_node()` creates a theme node, the template must include:
```python
"active": False,                    # bool — is this theme currently live?
"activation_date": None,            # ISO date string of last activation
"deactivation_date": None,          # ISO date string of last deactivation
"macro_trigger": None,              # str — human-readable reason (e.g. "Fed signals rate cuts")
"conviction": 0.0,                  # float 0.0–1.0, scanner confidence in theme relevance
"expected_duration_months": None,   # float — estimated shelf life
```

### 2. New activation fields on SECTOR nodes
When `add_sector_node()` creates a sector node, the template must include:
```python
"active": False,                    # bool — is this sector currently in a live theme?
"active_themes": [],                # list of theme node IDs activating this sector
"priority_score": 0.0,             # float 0.0–1.0, how central to active themes
"activated_date": None,             # ISO date of most recent activation
"deactivated_date": None,           # ISO date of most recent deactivation
```

### 3. Backfill on from_json()
`_backfill_node_defaults()` must already exist (added in S-037). Add these new fields to the backfill so existing AKG JSON files load without error. All new fields default to their zero/None/False values when not present.

### 4. New methods: Theme activation/deactivation
```python
def activate_theme(self, theme_id: str, macro_trigger: str, conviction: float = 0.5,
                   expected_duration_months: float = None) -> bool:
    """
    Mark a theme node as active. Returns True if theme existed and was updated.
    Sets: active=True, activation_date=today ISO, macro_trigger, conviction, expected_duration_months.
    Does NOT cascade to sectors — that is the theme scanner's job (S-041).
    """

def deactivate_theme(self, theme_id: str) -> bool:
    """
    Mark a theme node as inactive. Returns True if theme existed and was updated.
    Sets: active=False, deactivation_date=today ISO.
    Does NOT cascade to sectors.
    """
```

### 5. New methods: Sector activation/deactivation
```python
def activate_sector(self, sector_id: str, theme_ids: list, priority_score: float = 0.5) -> bool:
    """
    Mark a sector node as active. Merges theme_ids into active_themes (no duplicates).
    Sets: active=True, priority_score (max of current and new), activated_date=today ISO.
    Returns True if sector existed and was updated.
    """

def deactivate_sector(self, sector_id: str, theme_id: str = None) -> bool:
    """
    Remove theme_id from sector's active_themes list.
    If theme_id is None: deactivate fully regardless of remaining themes.
    If active_themes is now empty after removal: set active=False, deactivated_date=today ISO.
    If active_themes still has entries: keep active=True (other themes still activating it).
    Returns True if sector existed and was updated.
    """
```

### 6. New query methods
```python
def get_active_themes(self) -> list:
    """Return list of theme node dicts where active=True, sorted by conviction desc."""

def get_active_sectors(self) -> list:
    """Return list of sector node dicts where active=True, sorted by priority_score desc."""

def get_active_sector_ids(self) -> set:
    """Return set of sector node IDs where active=True. Used for fast membership check."""

def get_active_sector_companies(self, sector_id: str) -> list:
    """
    Return list of company node dicts belonging to the given sector.
    Match on node["sector"] == sector_id OR node_type=="company" with sector membership.
    Sort by centrality desc.
    """
```

## Files to Touch
- `tradingagents/graph/knowledge_graph.py`
- `tests/test_knowledge_graph.py`
- `tradingagents/default_config.py` — add config keys: `theme_scanner_enabled: False`, `theme_scanner_interval_hours: 168.0`

## Acceptance Criteria
- [ ] All 49 pre-existing knowledge_graph tests still pass
- [ ] New tests cover: activate_theme, deactivate_theme, activate_sector, deactivate_sector with theme_id (partial), deactivate_sector with no theme_id (full), multi-theme sector (deactivate one theme, sector stays active for other), get_active_themes (empty + populated), get_active_sectors, get_active_sector_ids, get_active_sector_companies, backfill on from_json for nodes missing new fields
- [ ] `from_json()` loads an existing AKG file with no new fields without KeyError
- [ ] `python -m pytest tests/test_knowledge_graph.py -v` — all pass

## Status
done

---

## Handoff
*Completed 2026-02-25.*

**Work Done:**
- Added 10 activation fields to `_node_template()`: `active`, `activation_date`, `deactivation_date`, `macro_trigger`, `conviction`, `expected_duration_months` (theme fields) + `active_themes`, `priority_score`, `activated_date`, `deactivated_date` (sector fields). All nodes get these fields at creation time.
- Updated `_backfill_node_defaults()` to fill all new S-040 fields on nodes loaded from older JSON (None/False/0.0/[] defaults as appropriate). No KeyError on legacy AKG files.
- Added `add_theme_node()` and `add_sector_node()` convenience wrappers (delegate to `add_node` with correct node_type).
- Added `update_node_field()` helper method.
- Added `activate_theme()`, `deactivate_theme()`, `activate_sector()`, `deactivate_sector()` methods with exact semantics from spec (merge without duplicates, max priority_score, cascade-free).
- Added `get_active_themes()`, `get_active_sectors()`, `get_active_sector_ids()`, `get_active_sector_companies()` query methods.
- Added `theme_scanner_enabled: False` and `theme_scanner_interval_hours: 168.0` to `DEFAULT_CONFIG` in `default_config.py`.
- Added 33 new tests covering all new methods. All 82 tests pass (49 pre-existing + 33 new).

**Learnings:**
- The `_node_template()` is a module-level function. Adding all activation fields there (not just for theme/sector types) is cleaner than conditional logic — unused fields on company/account nodes are negligible overhead.
- Backfill must handle `active_themes` as `[]` (not None) because sector methods do `.remove()` on it without None checks.

**Follow-ups:**
- S-041: Theme scanner scheduler — wires `activate_theme()` / `activate_sector()` calls to a periodic macro scan job (now gated by `theme_scanner_enabled` config key).
