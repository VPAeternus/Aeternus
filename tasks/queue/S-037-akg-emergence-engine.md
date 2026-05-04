# Task: S-037

## Tier
sonnet

## Summary
Extend AKG node schema with social-attention fields + emergence scoring engine so the pipeline can query "emerging planet" candidates by tier.

## Context

**Background**: The Universe Brain architecture (see VISION.md "The Universe Brain") designates AKG as the single source of truth for the investment universe. Nodes now need to carry cashtag velocity/sentiment fields so the pipeline can query for "emerging planets" — companies where structural importance (centrality) is converging with forming social attention (velocity + sentiment).

**Current state**: `tradingagents/graph/knowledge_graph.py` has nodes with fields:
`id, node_type, sector, display_name, signal_strength, centrality, times_surfaced, last_surfaced, aeternus_score, thesis_track_record, metadata`

**What's needed**: Add cashtag attention fields + emergence scoring so S-038 (cashtag enricher) can write them and S-039 (pipeline simplification) can query them.

**Emergence tiers**:
- DARK: centrality > 0.3, no velocity signal
- ROCKY: velocity present, velocity_z < 1.0
- ATMOSPHERE: velocity_z ≥ 1.0 OR sentiment ≥ 0.3
- HABITABLE: velocity_z ≥ 2.0 AND sentiment ≥ 0.5 AND unscored → ALPHA CANDIDATE
- SCORED: has aeternus_score (already analyzed)

**Emergence score formula** (0.0–1.0):
```
emergence_score = 0.40 × centrality + 0.40 × normalize(velocity_z, 0, 5) + 0.20 × normalize(sentiment, -1, 1)
```
Where normalize(x, min, max) = clamp((x - min) / (max - min), 0.0, 1.0).

## Requirements

1. **Extend `_node_template()`** — add these fields with None defaults:
   - `cashtag_velocity_z: float | None` — z-score of 7d cashtag mentions vs 90d baseline
   - `cashtag_mentions_7d: int | None` — absolute mention count last 7 days
   - `cashtag_velocity_trend: str | None` — one of "ACCELERATING", "STABLE", "DECELERATING"
   - `cashtag_sentiment: float | None` — composite sentiment, -1.0 to 1.0
   - `cashtag_last_updated: str | None` — ISO date string of last cashtag enrichment
   - `sec_event_type: str | None` — last SEC event type (e.g. "8K_SUPPLY_AGREEMENT")
   - `sec_event_date: str | None` — ISO date of last SEC event
   - `emergence_score: float | None` — computed 0.0–1.0
   - `emergence_tier: str | None` — one of "DARK", "ROCKY", "ATMOSPHERE", "HABITABLE", "SCORED"

2. **Backward compat in `from_json()`** — after loading nodes from JSON, call `_backfill_node_defaults()` to fill any missing new fields with None. Existing nodes should not lose their existing values.

3. **Add `enrich_node_cashtag()` method**:
   ```python
   def enrich_node_cashtag(
       self,
       ticker: str,
       velocity_z: float,
       mentions_7d: int,
       velocity_trend: str,
       sentiment: float,
       as_of_date: str,
   ) -> None:
   ```
   - Auto-creates node if missing (node_type="company")
   - Writes the 5 cashtag fields
   - Calls `compute_emergence_score(ticker)` automatically after writing

4. **Add `compute_emergence_score()` method**:
   ```python
   def compute_emergence_score(self, ticker: str) -> float:
   ```
   - Reads centrality, cashtag_velocity_z, cashtag_sentiment for the node
   - Returns 0.0 if centrality is 0.0 and velocity/sentiment are None
   - Applies the formula: 0.40×centrality + 0.40×normalize(velocity_z, 0, 5) + 0.20×normalize(sentiment, -1, 1)
   - Stores result in node["emergence_score"]
   - Computes and stores `emergence_tier`:
     - "SCORED" if aeternus_score is not None
     - "HABITABLE" if velocity_z ≥ 2.0 AND sentiment ≥ 0.5 AND unscored
     - "ATMOSPHERE" if velocity_z ≥ 1.0 OR sentiment ≥ 0.3
     - "ROCKY" if any cashtag data present but not meeting ATMOSPHERE
     - "DARK" otherwise
   - Returns the emergence_score float

5. **Add `get_emerging_planets()` method**:
   ```python
   def get_emerging_planets(
       self,
       min_score: float = 0.3,
       min_tier: str = "ATMOSPHERE",
       max_aeternus_score: Optional[float] = None,
       top_k: int = 50,
   ) -> List[dict]:
   ```
   - Filters company nodes by: emergence_tier in target tiers AND emergence_score >= min_score
   - Target tiers for `min_tier="ATMOSPHERE"`: ["ATMOSPHERE", "HABITABLE"]
   - If `max_aeternus_score` is not None, also filter out nodes where `aeternus_score > max_aeternus_score`
   - Returns top_k nodes sorted by emergence_score descending
   - Each returned dict: {id, sector, centrality, emergence_score, emergence_tier, cashtag_velocity_z, cashtag_sentiment, cashtag_velocity_trend, cashtag_last_updated}

6. **Add `compute_all_emergence_scores()` method** — run `compute_emergence_score()` for all company nodes in one pass (used after batch enrichment by scheduler).

7. **Tests** — new file `tests/test_knowledge_graph.py` (extend if exists, create if not):
   - `test_node_template_has_new_fields` — verify all 9 new fields present with None defaults
   - `test_from_json_backfills_missing_fields` — load JSON without new fields → fields populated as None
   - `test_enrich_node_cashtag_writes_fields` — verify all 5 cashtag fields written
   - `test_enrich_node_cashtag_autocreates_node` — enriching unknown ticker creates node
   - `test_compute_emergence_score_dark_node` — zero centrality, no velocity → score 0.0, tier DARK
   - `test_compute_emergence_score_habitable` — high velocity + sentiment → tier HABITABLE
   - `test_compute_emergence_score_atmosphere` — velocity_z=1.5 → tier ATMOSPHERE
   - `test_compute_emergence_score_scored` — node with aeternus_score → tier SCORED regardless
   - `test_get_emerging_planets_returns_atmosphere_and_habitable` — verify correct tier filter
   - `test_get_emerging_planets_top_k` — top_k=3 returns at most 3 sorted descending
   - `test_get_emerging_planets_max_aeternus_score` — high-scored nodes excluded
   - `test_get_emerging_planets_empty_when_no_cashtag_data` — no enrichment → nothing returned
   - `test_compute_all_emergence_scores_batch` — runs for all nodes, scores stored
   - `test_normalize_clamp` — velocity_z > 5 clamps to 1.0; velocity_z < 0 clamps to 0.0
   - All existing knowledge_graph tests still pass

## Files to Touch
- `tradingagents/graph/knowledge_graph.py`
- `tests/test_knowledge_graph.py` (create or extend)

## Acceptance Criteria
- [ ] `_node_template()` returns dict with all 9 new fields (None default)
- [ ] `from_json()` backward compat: loading old JSON → new fields all None
- [ ] `enrich_node_cashtag()` writes fields + auto-triggers compute_emergence_score
- [ ] `compute_emergence_score()` applies formula + sets tier correctly for all 5 cases
- [ ] `get_emerging_planets()` returns correct tier subset sorted by score
- [ ] 15+ tests pass
- [ ] `python -m pytest tests/test_knowledge_graph.py -v` — all pass
- [ ] `python -m pytest tests/ -v` — no regressions

## Status
done

---

## Handoff

**Work Done:**
- Extended `_node_template()` with 9 new social-attention fields (all None defaults): `cashtag_velocity_z`, `cashtag_mentions_7d`, `cashtag_velocity_trend`, `cashtag_sentiment`, `cashtag_last_updated`, `sec_event_type`, `sec_event_date`, `emergence_score`, `emergence_tier`.
- Added `_backfill_node_defaults()` private method called from `from_json()` for backward compat — older serialized graphs get new fields filled as None on load.
- Added `enrich_node_cashtag(ticker, velocity_z, mentions_7d, velocity_trend, sentiment, as_of_date)` — auto-creates node if missing, writes 5 cashtag fields, then calls `compute_emergence_score()`.
- Added `compute_emergence_score(ticker)` — formula: `0.40×centrality + 0.40×normalize(velocity_z,0,5) + 0.20×normalize(sentiment,-1,1)`. Stores score and tier (DARK/ROCKY/ATMOSPHERE/HABITABLE/SCORED). Returns 0.0 gracefully if node missing.
- Added `get_emerging_planets(min_score, min_tier, max_aeternus_score, top_k)` — filters company nodes by tier and score, excludes high-scored nodes when `max_aeternus_score` set, returns top_k sorted descending.
- Added `compute_all_emergence_scores()` — batch recompute for all company nodes.
- Added 16 new tests to `tests/test_knowledge_graph.py` (49 total, 33 pre-existing + 16 new). All pass.

**Learnings:**
- The `get_emerging_planets()` tier filter logic: `min_tier="ATMOSPHERE"` should return ATMOSPHERE and HABITABLE but NOT SCORED. Implemented by taking tiers from min_tier index onward, then excluding SCORED.
- normalize(-1.0 for zero sentiment) = 0.5, so a node with no velocity but sentiment=0.0 still gets 0.20*0.5 = 0.10 from sentiment component.

**Follow-ups:** S-038 (cashtag enricher reads these fields), S-039 (pipeline queries get_emerging_planets)
