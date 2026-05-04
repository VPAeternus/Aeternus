# Task: S-044

## Tier
sonnet

## Summary
AKG Full Brain Step 1 — After every analysis run, write the AeternusRating back to the AKG node so the brain remembers what it thought about each stock and when.

## Context
**Depends on S-040 being complete.** S-040 added the AKG activation schema. This task adds the analysis memory layer.

**Problem:** `record_pipeline_score(ticker, score)` currently only writes one float to AKG. The brain has no memory of rating, conviction, catalyst, or history. After 100 analysis runs, AKG knows NVDA was scored 82.5 — but not when, at what conviction, or what the key catalyst was. This is a single neuron firing, not a memory.

**Target:** After each `run_analysis()` completes, write a condensed intelligence snapshot to AKG:
- `last_aeternus_score` — the score
- `last_aeternus_rating` — "Strong Buy", "Buy", etc.
- `last_scored_date` — ISO date
- `last_conviction` — 1-5 confidence
- `last_catalyst` — key catalyst string (truncated to 200 chars)
- `score_history` — rolling list of {date, score, rating} last 10 entries

**Key pattern:** AKG stores derived intelligence, not raw data. Never store full rationale text or sub-scores in the node — those belong in the analysis JSON file. AKG stores the summary that enables fast filtering and prioritization.

**Key files:**
- `tradingagents/graph/knowledge_graph.py` — read fully before touching. Follow existing method style.
- `cli/commands/scoring.py` — `run_analysis()` function, after line where `final_state["aeternus_score"]` is set (around line 400). Also the `score` command at line ~564.
- `tests/test_knowledge_graph.py` — add to existing test file.

## Requirements

### 1. New fields in `_node_template()` (knowledge_graph.py)

Add after the existing `"active_themes": []` block:
```python
# Analysis memory (S-044) — written by record_rating()
"last_aeternus_score": None,    # float (0-100) from most recent full analysis
"last_aeternus_rating": None,   # str ("Strong Buy", "Buy", "Hold", "Sell", "Strong Sell")
"last_scored_date": None,       # ISO date string of last analysis
"last_conviction": None,        # int 1-5 confidence from scorer
"last_catalyst": None,          # str — key catalyst truncated to 200 chars
"score_history": [],            # list of {date, score, rating} — rolling last 10
```

### 2. Add to `_backfill_node_defaults()` (knowledge_graph.py)

Add to `_none_fields` list:
```python
"last_aeternus_score",
"last_aeternus_rating",
"last_scored_date",
"last_conviction",
"last_catalyst",
```

And separately:
```python
if "score_history" not in node:
    node["score_history"] = []
```

### 3. New method `record_rating()` (knowledge_graph.py)

Add after `record_pipeline_score()`:

```python
def record_rating(self, ticker: str, rating: dict) -> None:
    """
    Write condensed intelligence from an AeternusRating dict to the AKG node.
    AeternusRating is a TypedDict — access fields with dict syntax.
    Updates the legacy aeternus_score field for backward compat.
    Auto-creates node if missing. Recomputes emergence tier.
    """
    if ticker not in self._nodes:
        self.add_node(ticker, node_type="company")
    node = self._nodes[ticker]

    score = rating.get("aeternus_score")
    rating_str = rating.get("rating")
    date = rating.get("date") or dt.date.today().isoformat()
    conviction = rating.get("confidence")
    catalyst = rating.get("catalyst") or ""

    node["last_aeternus_score"] = score
    node["last_aeternus_rating"] = rating_str
    node["last_scored_date"] = date
    node["last_conviction"] = conviction
    node["last_catalyst"] = str(catalyst)[:200]

    # Rolling score history (last 10)
    if score is not None:
        history = node.get("score_history") or []
        history.append({"date": date, "score": score, "rating": rating_str})
        node["score_history"] = history[-10:]

    # Backward compat: update legacy aeternus_score field
    if score is not None:
        node["aeternus_score"] = score

    # Recompute emergence tier (scored nodes become SCORED tier)
    self.compute_emergence_score(ticker)
```

### 4. Wire write-back into `run_analysis()` (scoring.py)

In `cli/commands/scoring.py`, find the block after `final_state["aeternus_score"]` is set (around line 400). After the `RatingAuditLog` block, add:

```python
# Best-effort AKG rating write-back
try:
    from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
    _akg = AeternusKnowledgeGraph.load()
    _akg.record_rating(selections["ticker"], final_state["aeternus_score"])
    _akg.save()
except Exception:
    pass
```

**IMPORTANT**: This must be wrapped in try/except. AKG write-back is never allowed to abort the pipeline. The pipeline result is authoritative; AKG write-back is a side effect.

### 5. Wire write-back into `score` command (scoring.py)

In the `score` command (around line ~567-595), after `rating = graph.aeternus_scorer.score(...)` returns, add:

```python
# Best-effort AKG rating write-back
try:
    from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
    _akg = AeternusKnowledgeGraph.load()
    _akg.record_rating(ticker, rating)
    _akg.save()
except Exception:
    pass
```

## Files to Touch
- `tradingagents/graph/knowledge_graph.py` — new fields + `record_rating()` method
- `cli/commands/scoring.py` — two write-back wiring points
- `tests/test_knowledge_graph.py` — new tests

## Acceptance Criteria
- [x] `record_rating(ticker, rating_dict)` writes `last_aeternus_score`, `last_aeternus_rating`, `last_scored_date`, `last_conviction`, `last_catalyst` to AKG node
- [x] `score_history` rolls at 10 entries (11th entry evicts oldest)
- [x] `aeternus_score` field is updated for backward compat (does not break `get_dark_nodes()`)
- [x] `emergence_tier` transitions to `SCORED` after record_rating (compute_emergence_score called)
- [x] `record_rating()` on a non-existent node auto-creates it (same as record_pipeline_score)
- [x] `_backfill_node_defaults()` fills all new fields on nodes loaded from older AKG JSON
- [x] AKG write-back in `run_analysis()` is fully wrapped in try/except — never aborts pipeline
- [x] `python -m pytest tests/test_knowledge_graph.py -v` — all pass (pre-existing + new)
- [x] `python -m pytest tests/ -v --ignore=tests/test_cli_dealflow.py --ignore=tests/test_cli_hedging.py --ignore=tests/test_cli_score.py` — no regressions

## Status
done

## Handoff

Implemented 2026-02-26 by Sonnet.

### What was done

**`tradingagents/graph/knowledge_graph.py`** (3 changes):
1. Added 6 new fields to `_node_template()` under the S-044 comment block: `last_aeternus_score`, `last_aeternus_rating`, `last_scored_date`, `last_conviction`, `last_catalyst` (all `None`), and `score_history` (`[]`).
2. Added the 5 None-default fields to the `_none_fields` list in `_backfill_node_defaults()`, plus added a `score_history` guard block to backfill old nodes with `[]`.
3. Added `record_rating(self, ticker: str, rating: dict) -> None` method after `record_pipeline_score()`. Writes all 5 memory fields, maintains rolling `score_history` (max 10), updates legacy `aeternus_score` for backward compat, and calls `compute_emergence_score()` to transition tier to SCORED.

**`cli/commands/scoring.py`** (2 changes):
1. In `run_analysis()`: added best-effort AKG write-back in `try/except` block after the `RatingAuditLog` block.
2. In `score` command: added best-effort AKG write-back in `try/except` block after `RatingAuditLog` block.

**`tests/test_knowledge_graph.py`** (12 new tests added):
- `test_node_template_has_s044_fields` — verifies all 6 fields present on fresh node
- `test_backfill_adds_s044_fields_to_old_nodes` — verifies backfill on old JSON
- `test_record_rating_writes_all_fields` — verifies all 5 memory fields written
- `test_record_rating_updates_legacy_aeternus_score` — backward compat check
- `test_record_rating_autocreates_node` — auto-create on unknown ticker
- `test_record_rating_score_history_rolling_10` — eviction on 11th entry
- `test_record_rating_triggers_scored_tier` — emergence_tier becomes SCORED
- `test_record_rating_catalyst_truncated_to_200` — 200-char truncation
- `test_record_rating_missing_catalyst_defaults_to_empty` — None catalyst fallback
- `test_record_rating_missing_date_defaults_to_today` — None date fallback
- `test_record_rating_does_not_add_to_history_when_score_is_none` — no score = no history entry
- `test_record_rating_roundtrip` — save/load preserves all S-044 fields

### Test results
- `test_knowledge_graph.py`: 94 passed (82 pre-existing + 12 new)
- Broader suite (with standard ignores): 1314 passed, 0 new failures (2 pre-existing failures in test_dataflow_xai.py and test_paper_execution.py are unrelated to this task)
