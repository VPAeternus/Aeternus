# Task: S-039

## Tier
sonnet

## Summary
Simplify the deal flow pipeline by replacing cashtag discovery with an AKG emerging-planets query — zero API cost universe expansion.

## Context

**Depends on**: S-037 (AKG `get_emerging_planets()` method must exist). S-038 preferred but not hard-required (pipeline gracefully handles empty AKG cashtag data).

**Problem being solved**: The pipeline currently runs `cashtag_stream.py` as a discovery connector — it spends xAI credits to find tickers by scanning X cashtags. This is now redundant: the cashtag enricher (S-038) writes velocity/sentiment to AKG nodes on a schedule, and the pipeline should just READ those pre-computed results for free.

**Architecture being implemented** (from VISION.md "The Universe Brain"):
```
OLD: pipeline → cashtag_stream (xAI calls) → discovered tickers + signals
NEW: pipeline → akg.get_emerging_planets() → already-enriched ATMOSPHERE/HABITABLE nodes (free)
```

The cashtag connector is NOT deleted entirely. It is retained for a narrow optional pass: after initial scoring, the top-K finalists can get a fresh cashtag sentiment check. This is configurable and defaults to disabled.

**Current pipeline flow** (relevant section in `tradingagents/dealflow/pipeline.py`):
- Runs `_collect_cashtag_signals()` which calls `cashtag_stream.collect_cashtag_signals()`
- Results: `_cashtag_signals` (scored signals) and `_cashtag_discovered` (new ticker symbols)
- `_cashtag_discovered` contributes to universe expansion (`_all_discovered`)
- `_cashtag_signals` contributes to the scored signal list

**After this task**:
- Universe expansion: `akg.get_emerging_planets()` replaces `_cashtag_discovered`
- Signal list: AKG emerging planet scores replace raw cashtag scores (synthesized from emergence_score)
- Cashtag connector: removed from main pipeline flow; optional finalist pass only

## Requirements

1. **Replace cashtag discovery in `pipeline.py`**:
   - Remove the `_collect_cashtag_signals()` call from the main pipeline flow
   - Add AKG emerging planets query after existing dark node query:
     ```python
     # --- AKG Emerging Planets: zero-cost universe expansion ---
     _emerging_planets: List[dict] = []
     _emerging_planet_symbols: List[str] = []
     if _AKG_AVAILABLE and self.config.get("akg_enabled", True):
         try:
             _akg_path = self.config.get("akg_json_path", "eval_results/control/knowledge_graph.json")
             _akg = _AKG.load(_akg_path)
             _akg.get_centrality_scores()
             _emerging_planets = _akg.get_emerging_planets(
                 min_score=float(self.config.get("akg_emerging_min_score", 0.3)),
                 min_tier=str(self.config.get("akg_emerging_min_tier", "ATMOSPHERE")),
                 top_k=int(self.config.get("akg_emerging_top_k", 50)),
             )
             _emerging_planet_symbols = [p["id"] for p in _emerging_planets]
         except Exception:
             pass
     ```
   - Add `_emerging_planet_symbols` to universe expansion:
     ```python
     _all_discovered = (
         set(prioritized_discovered)
         | set(_catalyst_discovered)
         | set(_dark_node_symbols)
         | set(_emerging_planet_symbols)   # replaces _cashtag_discovered
         | set(manual_symbols)
     )
     ```

2. **Convert emerging planet signals** — synthesize `DealFlowSignal` objects from emerging planet data:
   ```python
   # Signals synthesized from AKG emergence scores (free, no API cost)
   _emerging_signals: List[Dict] = []
   for planet in _emerging_planets:
       _emerging_signals.append({
           "symbol": planet["id"],
           "signal_family": "akg_emerging",
           "raw_score": float(round(planet["emergence_score"] * 100.0, 4)),
           "z_score": planet.get("cashtag_velocity_z") or 0.0,
           "direction": _direction_from_emergence(planet),
           "evidence_count": 1,
           "freshness_hours": 0.0,
           "source_status": "OK",
           "source_name": "akg_emerging_planets",
       })
   ```
   Add helper `_direction_from_emergence(planet)` → "BULLISH" if sentiment > 0.2, "BEARISH" if < -0.2, else "NEUTRAL".
   Add `signals.extend(_emerging_signals)` to signal list.

3. **Optional finalist cashtag pass** (configurable, default disabled):
   - Config key: `dealflow_cashtag_finalist_pass_enabled` (default False)
   - If enabled: after initial scoring, take top-K scored candidates (up to `dealflow_cashtag_finalist_top_k`, default 20)
   - Run narrow cashtag check on those symbols only
   - Merge into signal list (update existing entries if already present)
   - This is a "polish" pass, not discovery. Ensure it's gated and never runs by default.

4. **Remove cashtag connector health from the run** — since cashtag no longer runs, remove `_cashtag_health` from `connector_health` list. Update `connector_health_summary` accordingly.

5. **Config keys** — add to `tradingagents/default_config.py`:
   - `"akg_emerging_min_score": 0.3`
   - `"akg_emerging_min_tier": "ATMOSPHERE"`
   - `"akg_emerging_top_k": 50`
   - `"dealflow_cashtag_finalist_pass_enabled": False`
   - `"dealflow_cashtag_finalist_top_k": 20`

6. **Tests** — update `tests/test_dealflow_pipeline.py` (or create):
   - `test_pipeline_uses_emerging_planets_for_universe_expansion` — mock AKG with 3 ATMOSPHERE nodes → all 3 in universe
   - `test_pipeline_synthesizes_akg_signals` — emerging planet nodes → DealFlowSignal with signal_family="akg_emerging"
   - `test_pipeline_graceful_when_akg_missing` — AKG file missing → pipeline runs without error, empty emerging list
   - `test_pipeline_direction_bullish` — sentiment > 0.2 → direction BULLISH
   - `test_cashtag_finalist_pass_disabled_by_default` — cashtag_stream NOT called when config default
   - Existing connector tests still pass

## Files to Touch
- `tradingagents/dealflow/pipeline.py`
- `tradingagents/default_config.py` (5 new keys)
- `tests/test_dealflow_pipeline.py` (update or create)

## Acceptance Criteria
- [ ] Pipeline queries `akg.get_emerging_planets()` for universe expansion (zero API cost path)
- [ ] Cashtag discovery removed from main pipeline flow
- [ ] `DealFlowSignal` objects synthesized from AKG emerging planet data
- [ ] Finalist cashtag pass defaults to disabled
- [ ] Pipeline handles missing AKG gracefully (empty emerging list, no error)
- [ ] 6+ tests pass
- [ ] `python -m pytest tests/ -v` — no regressions
- [ ] `aeternus source --trigger manual --top-k 20` runs end-to-end without cashtag API calls

## Status
done

---

## Handoff

**Work Done:**
- Modified `tradingagents/dealflow/pipeline.py`:
  - Added AKG emerging planets query after dark node section, reusing the `_akg_path` variable (loads a fresh instance for emerging planets to avoid state coupling).
  - Added `_emerging_planet_symbols` to `_all_discovered` set for universe expansion.
  - Added `_emerging_signals` list synthesized from planet data (signal_family="akg_emerging", direction from `_direction_from_emergence`, raw_score = emergence_score * 100).
  - Added `_direction_from_emergence(planet)` helper at module level.
  - Gated cashtag connector behind `dealflow_cashtag_finalist_pass_enabled` (default False). When disabled, cashtag_stream health entry is `NOT_CONFIGURED`. The second "recompute cashtag" call is also gated.
  - Removed `_cashtag_discovered` from `_all_discovered` (was previously `prioritized_discovered` from cashtag, now only populated when finalist pass enabled).
- Modified `tradingagents/default_config.py`: Added 5 new config keys: `akg_emerging_min_score`, `akg_emerging_min_tier`, `akg_emerging_top_k`, `dealflow_cashtag_finalist_pass_enabled`, `dealflow_cashtag_finalist_top_k`.
- Created `tests/test_dealflow_pipeline.py` with 10 tests (6 required + 4 extras): direction helper unit tests + pipeline integration tests covering universe expansion, signal synthesis, graceful AKG failure, cashtag disabled by default, health entry NOT_CONFIGURED.

**Learnings:**
- The pipeline had two cashtag calls (initial discovery + recompute against expanded universe). Both had to be gated, not just the first.
- AKG loading pattern: dark nodes and emerging planets both load from the same path. Using separate `_AKG.load()` calls per query is cleaner than sharing a single instance (avoids side effects from `get_centrality_scores()` mutating node state).

**Follow-ups:** None — this completes the Universe Brain architecture (S-037 → S-038 → S-039).
