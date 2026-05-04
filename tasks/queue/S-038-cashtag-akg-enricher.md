# Task: S-038

## Tier
sonnet

## Summary
Build a scheduled cashtag enricher that writes velocity/sentiment to high-centrality AKG nodes — scoped, staleness-gated, never runs during pipeline.

## Context

**Depends on**: S-037 (AKG must have `enrich_node_cashtag()` and `compute_emergence_score()` methods).

**Problem being solved**: Cashtag stream currently runs as a pipeline connector (discovery mode — finding new tickers via X). This is expensive and redundant with AKG. The new pattern:
- Cashtag's JOB = enrich AKG nodes with velocity + sentiment (not discover new tickers)
- Scope = only the ~50 highest-centrality nodes in AKG (no cold universe scanning)
- Cadence = every 4h via scheduler, with staleness gate (skip if updated < 4h ago)
- Pipeline reads AKG for free; pipeline does NOT call cashtag for discovery

**Cost model**: 50 nodes × $0.005/call = $0.25 per enrichment run × 6 runs/day = $1.50/day max (only if all 50 need refresh). In practice far less because staleness gate skips recently-updated nodes.

**Existing cashtag code**: `tradingagents/dealflow/sources/cashtag_stream.py` already has the core logic for fetching x_search data and computing velocity/sentiment scores. This task adds a new `enrich_akg()` entry point that reuses that logic but writes to AKG instead of returning DealFlowSignal objects.

## Requirements

1. **New file `tradingagents/dealflow/sources/cashtag_enricher.py`**:
   ```python
   def enrich_akg_with_cashtags(
       akg,              # AeternusKnowledgeGraph instance
       config: dict,
       as_of_date: str,
   ) -> dict:
       """
       Enrich high-centrality AKG nodes with cashtag velocity/sentiment.
       Returns dict with: enriched_count, skipped_stale, skipped_no_data, symbols_enriched.
       """
   ```
   - Step 1: `akg.get_centrality_scores()` → take top-N by centrality (N = `config.get("cashtag_enricher_top_n", 50)`)
   - Step 2: Filter stale — skip nodes where `cashtag_last_updated` is within `cashtag_enricher_min_interval_hours` (default 4.0) hours
   - Step 3: For each in-scope symbol, call cashtag data fetch (reuse logic from cashtag_stream.py). If XAI_API_KEY missing, return early with {"ran": False, "reason": "no_api_key"}.
   - Step 4: For each result, call `akg.enrich_node_cashtag(ticker, velocity_z, mentions_7d, velocity_trend, sentiment, as_of_date)`
   - Step 5: After all enrichments, call `akg.compute_all_emergence_scores()`
   - Return result dict

2. **Staleness check**: Use the same ISO datetime parsing pattern from `scheduler.py` (`_parse_iso_dt`). A node is stale-ok (skip) if `cashtag_last_updated` is within the minimum interval.

3. **Graceful degradation**: xAI rate limit → mark `_LLM_RATE_LIMITED`, stop enriching remaining symbols (same pattern as sector_scout.py). Return partial results dict.

4. **Wire into `DealFlowScheduler`** — add `_maybe_run_cashtag_enricher()` method to `tradingagents/dealflow/scheduler.py`:
   ```python
   def _maybe_run_cashtag_enricher(
       self,
       state: Dict[str, Any],
       now_utc: dt.datetime,
       run_date: str,
   ) -> Dict[str, Any]:
   ```
   - Checks `cashtag_enricher_enabled` config (default False — opt-in)
   - Checks elapsed time since `state["last_cashtag_enricher_ts"]`
   - Loads AKG from config path (`akg_json_path`)
   - Calls `enrich_akg_with_cashtags(akg, config, run_date)`
   - Saves AKG back to JSON path after enrichment
   - Returns result dict

5. **Call from `run_once()`** — add call before `self.pipeline.run()`, same pattern as `_maybe_run_sector_scout()`:
   ```python
   _enricher_result = self._maybe_run_cashtag_enricher(state, now_utc, run_date)
   if _enricher_result.get("ran"):
       state["last_cashtag_enricher_ts"] = now_utc.isoformat()
       state["last_cashtag_enricher_count"] = int(_enricher_result.get("enriched_count", 0))
   ```

6. **Config keys** — add to `tradingagents/default_config.py`:
   - `"cashtag_enricher_enabled": False`
   - `"cashtag_enricher_top_n": 50`
   - `"cashtag_enricher_min_interval_hours": 4.0`

7. **Tests** — `tests/test_cashtag_enricher.py`:
   - `test_enrich_akg_no_api_key` — missing XAI_API_KEY → returns {ran: False}
   - `test_enrich_akg_skips_stale_nodes` — nodes updated recently → skipped
   - `test_enrich_akg_enriches_in_scope_nodes` — mock x_search → enrich_node_cashtag called
   - `test_enrich_akg_handles_rate_limit` — 429 error → stops, returns partial result
   - `test_maybe_run_cashtag_enricher_disabled` — config disabled → {ran: False}
   - `test_maybe_run_cashtag_enricher_interval_gate` — last run < 4h → {ran: False}
   - `test_scheduler_state_updated_on_enrichment` — state["last_cashtag_enricher_ts"] set on run
   - All existing scheduler tests still pass

## Files to Touch
- `tradingagents/dealflow/sources/cashtag_enricher.py` (new)
- `tradingagents/dealflow/scheduler.py` (add _maybe_run_cashtag_enricher + call in run_once)
- `tradingagents/default_config.py` (3 new keys)
- `tests/test_cashtag_enricher.py` (new)

## Acceptance Criteria
- [ ] `enrich_akg_with_cashtags()` scopes to top-N centrality nodes, respects staleness gate
- [ ] `_maybe_run_cashtag_enricher()` wired into scheduler with interval gate
- [ ] Config defaults all to disabled/conservative values
- [ ] AKG saved atomically after enrichment
- [ ] 8+ tests pass
- [ ] `python -m pytest tests/test_cashtag_enricher.py -v` — all pass
- [ ] `python -m pytest tests/ -v` — no regressions

## Status
done

---

## Handoff

**Work Done:**
- Created `tradingagents/dealflow/sources/cashtag_enricher.py` — `enrich_akg_with_cashtags()` entry point + `_fetch_cashtag_data()` helper + `_is_within_interval()` staleness check + `_is_rate_limited_error()` + JSON extraction utils. Module-level `_LLM_RATE_LIMITED` flag follows same pattern as `sector_scout.py`.
- Added `_maybe_run_cashtag_enricher()` to `tradingagents/dealflow/scheduler.py` (after `_maybe_run_sector_scout`), wired into `run_once()` with state update on success.
- Added 3 config keys to `tradingagents/default_config.py` near existing `cashtag_` keys: `cashtag_enricher_enabled` (False), `cashtag_enricher_top_n` (50), `cashtag_enricher_min_interval_hours` (4.0).
- Created `tests/test_cashtag_enricher.py` with 8 tests — all pass. Zero regressions on 174 pre-existing tests.

**Learnings:**
- Background task output files in this env appear to be empty immediately; use synchronous pytest calls for result verification.
- `_LLM_RATE_LIMITED` is a module-level flag that must be reset at the start of each `enrich_akg_with_cashtags()` call (not persistent across invocations).

**Follow-ups:** S-039 (pipeline can now query get_emerging_planets for enriched nodes)
