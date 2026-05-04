# Task: S-047

## Tier
sonnet

## Summary
AKG Full Brain Step 4 — Hebbian outcome weight. When a position closes, compute outcome stats per node and adjust a multiplier (0.5–2.0) that feeds back into the emergence score. Nodes that deliver wins get promoted; nodes that fail get demoted.

## Context
**Depends on S-045 being complete** (which adds `close_position()` to AKG).

**Problem:** AKG has no memory of performance. NVDA has been analyzed 20 times, scored well each time, but we've never made money on it. The brain should down-weight it. AMD has been analyzed 5 times and every trade was profitable. The brain should amplify it. Without outcome feedback, the emergence score is purely technical — it doesn't incorporate what actually worked.

**The pattern:** Hebbian learning — "neurons that fire together, wire together." When a thesis is confirmed (trade profit), the node's weight increases. When the thesis fails (trade loss), the weight decreases. This is the same principle as the existing edge-weight Hebbian strengthening in `add_edge()`, applied at the node level.

**Target:** `outcome_weight` field (0.5–2.0) on each company node. Multiplied into the emergence score formula. Updated when positions close.

**Key constraint:** `outcome_weight` is a gentle signal nudge, not a hard gate. It shifts emergence scores by ±50% at extremes. The emergence score formula stays the same, but the final value is scaled.

**Key files:**
- `tradingagents/graph/knowledge_graph.py` — new field + `record_outcome()` method + update `compute_emergence_score()`.
- `tests/test_knowledge_graph.py` — new tests.

## Requirements

### 1. New fields in `_node_template()` (knowledge_graph.py)

Add after the S-046 fundamentals cache block:
```python
# Outcome weight feedback (S-047) — Hebbian learning
"outcome_weight": 1.0,          # float 0.5–2.0, multiplies emergence score
"outcome_stats": None,          # dict {n_trades, n_wins, win_rate, avg_return, avg_hold_days}
```

### 2. Add to `_backfill_node_defaults()` (knowledge_graph.py)

Add to the non-None-default section:
```python
if "outcome_weight" not in node:
    node["outcome_weight"] = 1.0
```

And to `_none_fields`:
```python
"outcome_stats",
```

### 3. New method `record_outcome()` (knowledge_graph.py)

```python
def record_outcome(self, ticker: str, realized_return_pct: float, hold_days: int = 0) -> None:
    """
    Update outcome_weight after a position closes.
    outcome_weight rises when returns are positive, falls when negative.
    Clamped to [0.5, 2.0]. Updates outcome_stats.
    Recomputes emergence score with new weight.
    """
    if ticker not in self._nodes:
        return
    node = self._nodes[ticker]

    # Update outcome_stats
    stats = node.get("outcome_stats") or {
        "n_trades": 0, "n_wins": 0, "total_return": 0.0, "total_hold_days": 0
    }
    stats["n_trades"] += 1
    if realized_return_pct > 0:
        stats["n_wins"] += 1
    stats["total_return"] = round(stats.get("total_return", 0.0) + realized_return_pct, 6)
    stats["total_hold_days"] = stats.get("total_hold_days", 0) + hold_days

    n = stats["n_trades"]
    stats["win_rate"] = round(stats["n_wins"] / n, 4) if n > 0 else 0.0
    stats["avg_return"] = round(stats["total_return"] / n, 6) if n > 0 else 0.0
    stats["avg_hold_days"] = round(stats["total_hold_days"] / n, 1) if n > 0 else 0.0
    node["outcome_stats"] = stats

    # Adjust outcome_weight
    # +5% for each win, -8% for each loss (asymmetric: harder to earn back than to lose)
    if realized_return_pct > 0:
        delta = 0.05
    else:
        delta = -0.08
    new_weight = round(
        max(0.5, min(2.0, (node.get("outcome_weight") or 1.0) + delta)), 4
    )
    node["outcome_weight"] = new_weight

    # Recompute emergence score with new weight
    self.compute_emergence_score(ticker)
```

### 4. Update `compute_emergence_score()` (knowledge_graph.py)

In the existing `compute_emergence_score()` method, after computing `score`, multiply by `outcome_weight`:

```python
# Apply outcome weight (Hebbian feedback)
outcome_weight = node.get("outcome_weight") or 1.0
score = round(max(0.0, min(1.0, score * outcome_weight)), 6)
```

This single line addition means: nodes with positive track records float higher, nodes with negative track records sink lower.

### 5. Wire `record_outcome()` into `close_position()` (knowledge_graph.py, already in S-045)

**IMPORTANT:** S-045 adds `close_position()`. That method should call `record_outcome()`:

In `close_position()`, after computing `realized_return_pct` and before `node["current_position"] = None`, add:
```python
self.record_outcome(ticker, realized_return_pct, hold_days)
```

Since S-045 may already be merged, check if `close_position()` exists and add this call. Do NOT duplicate the method — just add the `record_outcome()` call inside it.

## Files to Touch
- `tradingagents/graph/knowledge_graph.py` — `outcome_weight` field, `record_outcome()` method, update `compute_emergence_score()`, update `close_position()` if needed
- `tests/test_knowledge_graph.py` — new tests

## Acceptance Criteria
- [ ] `outcome_weight` starts at 1.0 on all new nodes
- [ ] `record_outcome(ticker, 0.15, 10)` (win) increases `outcome_weight` by 0.05
- [ ] `record_outcome(ticker, -0.10, 5)` (loss) decreases `outcome_weight` by 0.08
- [ ] `outcome_weight` is clamped to [0.5, 2.0] — never goes below 0.5 or above 2.0
- [ ] `outcome_stats` correctly accumulates `n_trades`, `n_wins`, `win_rate`, `avg_return`
- [ ] `compute_emergence_score()` multiplies score by `outcome_weight` before returning
- [ ] A node with `outcome_weight=2.0` and base emergence_score=0.5 returns 1.0 (capped)
- [ ] A node with `outcome_weight=0.5` and base emergence_score=0.8 returns 0.4
- [ ] `_backfill_node_defaults()` sets `outcome_weight=1.0` on nodes loaded from older AKG JSON
- [ ] `close_position()` calls `record_outcome()` with the computed return
- [ ] `python -m pytest tests/test_knowledge_graph.py -v` — all pass
- [ ] `python -m pytest tests/ -v --ignore=tests/test_cli_dealflow.py --ignore=tests/test_cli_hedging.py --ignore=tests/test_cli_score.py` — no regressions

## Status
done

## Handoff

Implementation complete. All acceptance criteria verified.

**Files changed:**
- `tradingagents/graph/knowledge_graph.py` — 4 surgical edits:
  1. Added `outcome_weight: 1.0` and `outcome_stats: None` to `_node_template()`
  2. Added `"outcome_stats"` to `_none_fields` in `_backfill_node_defaults()`; added `outcome_weight` non-None guard (default 1.0)
  3. Modified `compute_emergence_score()`: multiplies base score by `outcome_weight` before the clamp — `score = round(max(0.0, min(1.0, score * outcome_weight)), 6)`
  4. Added `self.record_outcome(ticker, realized_return_pct, hold_days)` call inside `close_position()` before `node["current_position"] = None`
  5. Added `record_outcome()` method (standalone, publicly callable)

- `tests/test_knowledge_graph.py` — 14 new tests added covering all acceptance criteria

**Test results:**
- `test_knowledge_graph.py`: 135 passed, 0 failed
- Broader suite (excluding pre-existing failures): 1355 passed, 2 pre-existing failures (unrelated to S-047), no regressions
