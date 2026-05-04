# Task: S-041

## Tier
sonnet

## Summary
Build the Theme Scanner — Phase A of the two-phase sector scout. Identifies which macro themes are active and cascades activation to AKG sectors. Weekly + event-triggered.

## Context
**Depends on S-040 being complete.** S-040 adds the activation schema and methods to `knowledge_graph.py`. This task builds the scanner that calls those methods.

**The big picture:** Themes are the cosmological layer. They change monthly, not daily. The theme scanner's job is:
1. Look at the current macro environment (via xAI web_search)
2. Determine which of the AKG's existing theme nodes are currently RELEVANT
3. Activate relevant themes + cascade to their sectors
4. Deactivate themes that no longer apply

**This is the gating decision for all downstream spend.** If a theme is dormant → its sectors are dormant → cashtag enrichment and sector scout skip them → cost = $0.

**Key patterns to follow:**
- `tradingagents/dealflow/sources/sector_scout.py` — follow its structure exactly: `_LLM_RATE_LIMITED` flag, xAI API check, config-gated, returns result dict
- `tradingagents/dealflow/scheduler.py` — follow `_maybe_run_sector_scout()` pattern for new `_maybe_run_theme_scanner()` method
- `tradingagents/graph/knowledge_graph.py` (post S-040) — use `get_active_themes()`, `activate_theme()`, `deactivate_theme()`, `activate_sector()`, `deactivate_sector()`, `get_nodes_by_type("theme")`, `get_nodes_by_type("sector")`

**xAI API pattern (from sector_scout.py):**
```python
from openai import OpenAI
client = OpenAI(api_key=os.getenv("XAI_API_KEY"), base_url="https://api.x.ai/v1")
response = client.chat.completions.create(
    model="grok-4-1-fast-non-reasoning",
    messages=[...],
    tools=[{"type": "function", "function": {"name": "web_search", ...}}]
)
```
Valid xAI model: `grok-4-1-fast-non-reasoning`. Do NOT use `grok-4-1-fast` (invalid) or `grok-3-mini` (wrong price tier).

## Requirements

### 1. New file: `tradingagents/dealflow/sources/theme_scanner.py`

Entry point:
```python
def scan_themes(akg: AeternusKnowledgeGraph, config: dict, as_of_date: str = None) -> dict:
    """
    Evaluate current macro environment and update AKG theme/sector activation.

    Returns: {
        "ran": bool,
        "themes_evaluated": int,
        "themes_activated": list[str],    # theme IDs newly activated
        "themes_deactivated": list[str],  # theme IDs newly deactivated
        "sectors_activated": list[str],   # sector IDs newly activated
        "sectors_deactivated": list[str], # sector IDs newly deactivated
        "macro_summary": str,             # 1-2 sentence macro context summary
        "error": str | None
    }
    ```

**Implementation steps:**
1. Check `XAI_API_KEY` env var. If missing → `{"ran": False, "error": "XAI_API_KEY not set"}`
2. Check `_LLM_RATE_LIMITED` module flag. If True → `{"ran": False, "error": "rate_limited"}`
3. Load all theme nodes from AKG via `akg.get_nodes_by_type("theme")`
4. If no themes exist in AKG → return `{"ran": False, "error": "no_themes_in_akg"}`
5. Build prompt: given the list of themes, ask xAI to evaluate current macro environment and score each theme's relevance (0.0–1.0). Include today's date in prompt for grounding.
6. Make ONE xAI call with web_search enabled (web_search gives real-time macro awareness)
7. Parse response: for each theme, get `relevance_score` and `reasoning`
8. Apply threshold (config `theme_activation_threshold`, default 0.5):
   - relevance >= threshold AND theme currently inactive → call `akg.activate_theme()`
   - relevance < threshold AND theme currently active → call `akg.deactivate_theme()`
9. For activated themes: cascade to sectors. Each theme node should have a `sectors` field (list of sector IDs it activates). Call `akg.activate_sector(sector_id, [theme_id], priority_score=relevance)` for each.
10. For deactivated themes: cascade via `akg.deactivate_sector(sector_id, theme_id=theme_id)` for each sector in the theme's `sectors` list.
11. Return result dict.

**Prompt design** (critical — this determines quality):
```
Today's date: {date}.

You are evaluating which macro investment themes are currently ACTIVE based on the real-time macro environment.

Themes to evaluate:
{for each theme: theme_id, description, macro_trigger_hints}

For each theme, provide a JSON object with:
  - "theme_id": the theme ID
  - "relevance_score": float 0.0–1.0 (1.0 = highly active macro driver, 0.0 = not relevant now)
  - "reasoning": 1-sentence explanation referencing current events

Use web_search to check current macro conditions (Fed policy, market conditions, geopolitical events).

Return a JSON array of theme evaluations.
```

**Error handling:**
- JSON parse failure → log, return `{"ran": False, "error": "parse_error"}`
- Rate limit / API error → set `_LLM_RATE_LIMITED = True`, return `{"ran": False, "error": ...}`

### 2. Wire into scheduler

In `tradingagents/dealflow/scheduler.py`, add `_maybe_run_theme_scanner()`:

```python
def _maybe_run_theme_scanner(self, state: dict, now_utc: datetime, run_date: str) -> dict:
    if not self.config.get("theme_scanner_enabled", False):
        return {"ran": False}
    last_ts = state.get("last_theme_scanner_ts")
    interval_hours = float(self.config.get("theme_scanner_interval_hours", 168.0))  # 168h = weekly
    if last_ts and _hours_since(last_ts, now_utc) < interval_hours:
        return {"ran": False}
    from tradingagents.dealflow.sources.theme_scanner import scan_themes
    result = scan_themes(self.akg, self.config, as_of_date=run_date)
    return result
```

Wire in `run_once()` BEFORE `_maybe_run_sector_scout()` (theme scanner must run first to determine which sectors are active):
```python
_theme_result = self._maybe_run_theme_scanner(state, now_utc, run_date)
if _theme_result.get("ran"):
    state["last_theme_scanner_ts"] = now_utc.isoformat()
```

### 3. Config keys (add to `tradingagents/default_config.py`)
```python
"theme_scanner_enabled": False,          # opt-in
"theme_scanner_interval_hours": 168.0,   # weekly
"theme_activation_threshold": 0.5,       # min relevance to activate a theme
```

## Files to Touch
- `tradingagents/dealflow/sources/theme_scanner.py` — new file
- `tradingagents/dealflow/scheduler.py` — add `_maybe_run_theme_scanner()` and wire in `run_once()`
- `tradingagents/default_config.py` — 3 new config keys (if not already added by S-040)

## Acceptance Criteria
- [ ] `theme_scanner.py` imports cleanly: `from tradingagents.dealflow.sources.theme_scanner import scan_themes`
- [ ] When `XAI_API_KEY` not set → returns `{"ran": False}` without crashing
- [ ] When `theme_scanner_enabled=False` → scheduler skips without calling scanner
- [ ] Tests cover: no XAI key path, no themes in AKG path, theme activation (mocked API), theme deactivation, sector cascade on activation, sector cascade on deactivation, partial deactivation (multi-theme sector keeps active)
- [ ] `python -m pytest tests/test_theme_scanner.py -v` — all pass
- [ ] `python -m pytest tests/ -v --ignore=tests/test_cli_dealflow.py --ignore=tests/test_cli_hedging.py --ignore=tests/test_cli_score.py` — no regressions

## Status
done

---

## Handoff

**Work Done:**
- Created `tradingagents/dealflow/sources/theme_scanner.py` with `scan_themes(akg, config, as_of_date)`. Module-level `_LLM_RATE_LIMITED` flag, XAI key check, no-themes guard, xAI chat completions call (grok-4-1-fast-non-reasoning), JSON parse with fallback extraction, threshold-based activate/deactivate logic, sector cascade via `_get_theme_sectors()` (checks `metadata["sectors"]` and top-level `sectors` field).
- Added `get_nodes_by_type(node_type)` to `AeternusKnowledgeGraph` (was referenced in spec but missing from the class).
- Added `theme_activation_threshold: 0.5` to `tradingagents/default_config.py` (the other two keys `theme_scanner_enabled` and `theme_scanner_interval_hours` were already added by S-040).
- Added `_maybe_run_theme_scanner()` to `DealFlowScheduler` in `tradingagents/dealflow/scheduler.py`, wired BEFORE `_maybe_run_sector_scout()` in `run_once()`.
- Wrote 14 tests in `tests/test_theme_scanner.py`: no-key path, no-themes path, rate-limited flag, activation, deactivation, no-re-activation of already-active theme, sector cascade on activation, sector cascade on deactivation, partial deactivation (multi-theme sector stays active), parse error, API rate-limit exception, unknown theme_id ignored, `get_nodes_by_type` directly, activation with no sectors field.

**Learnings:**
- `get_nodes_by_type` was specified in the task but not yet implemented in knowledge_graph.py (S-040 left it for S-041 to add when needed). Always verify AKG API surface before writing scanner code.
- The spec says "sectors field stored on the theme node" — this can be in `metadata["sectors"]` (via `add_theme_node` metadata kwarg) or a top-level `sectors` field. `_get_theme_sectors()` checks both.

**Follow-ups:**
- S-042 or future task: add `macro_trigger_hints` field to seed theme nodes so the prompt has richer grounding data.
- Consider adding sector-level `priority_score` decay over time (themes deactivate but sectors don't decay unless explicitly deactivated).
