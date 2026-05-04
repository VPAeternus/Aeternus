# Task: S-045

## Tier
sonnet

## Summary
AKG Full Brain Step 2 — Write position state (open/close) back to AKG nodes so the brain remembers what it's currently holding and what happened to past trades.

## Context
**Depends on S-044 being complete.**

**Problem:** When a position in NVDA is opened, AKG doesn't know. When it closes, AKG doesn't know. The brain has no memory of execution. This breaks the feedback loop — how will we know to stop analyzing NVDA if we're already in it? How will we record that the NVDA thesis was correct?

**Target:** After `execute-paper` opens a position, write it to the AKG node. After `close-paper` closes a position, write the outcome back.

**Key constraint:** Keep it surgical. This is NOT a position ledger (that's `paper_execution.py`'s job). AKG stores a minimal intelligence snapshot — is there a current position? What was the entry? When did it close and at what return?

**Key files:**
- `tradingagents/graph/knowledge_graph.py` — new fields + methods. Read the full file first.
- `tradingagents/graph/paper_execution.py` — position execution logic. Read relevant functions before modifying.
- `tests/test_knowledge_graph.py` — add tests for new methods.

## Requirements

### 1. New fields in `_node_template()` (knowledge_graph.py)

Add after the S-044 analysis memory block:
```python
# Execution memory (S-045) — written by set_current_position() and close_position()
"current_position": None,       # dict {shares, entry_price, entry_date} or None
"last_closed_position": None,   # dict {exit_date, exit_price, realized_return_pct, hold_days} or None
```

### 2. Add to `_backfill_node_defaults()` (knowledge_graph.py)

Add to `_none_fields` list:
```python
"current_position",
"last_closed_position",
```

### 3. New method `set_current_position()` (knowledge_graph.py)

```python
def set_current_position(self, ticker: str, shares: float,
                          entry_price: float, entry_date: str) -> None:
    """
    Record that a position was opened. Auto-creates node if missing.
    Sets current_position = {shares, entry_price, entry_date}.
    """
    if ticker not in self._nodes:
        self.add_node(ticker, node_type="company")
    self._nodes[ticker]["current_position"] = {
        "shares": shares,
        "entry_price": entry_price,
        "entry_date": entry_date,
    }
```

### 4. New method `close_position()` (knowledge_graph.py)

```python
def close_position(self, ticker: str, exit_price: float, exit_date: str) -> bool:
    """
    Record that a position was closed. Computes realized return.
    Clears current_position. Sets last_closed_position.
    Also calls record_thesis_outcome() based on return sign.
    Returns True if node existed and had a position to close.
    """
    if ticker not in self._nodes:
        return False
    node = self._nodes[ticker]
    pos = node.get("current_position")
    if not pos:
        return False

    entry_price = pos.get("entry_price") or 0.0
    entry_date = pos.get("entry_date") or exit_date

    realized_return_pct = 0.0
    if entry_price > 0:
        realized_return_pct = round((exit_price - entry_price) / entry_price, 6)

    hold_days = 0
    try:
        import datetime as _dt
        d0 = _dt.date.fromisoformat(entry_date)
        d1 = _dt.date.fromisoformat(exit_date)
        hold_days = (d1 - d0).days
    except Exception:
        pass

    node["last_closed_position"] = {
        "exit_date": exit_date,
        "exit_price": exit_price,
        "realized_return_pct": realized_return_pct,
        "hold_days": hold_days,
    }
    node["current_position"] = None

    # Update thesis track record (confirmed if positive return)
    confirmed = realized_return_pct > 0
    self.record_thesis_outcome(ticker, confirmed)

    return True
```

### 5. Wire write-back into `paper_execution.py`

In `tradingagents/graph/paper_execution.py`, find the function that executes orders and writes to the positions ledger. After a successful fill write, add a best-effort AKG write-back:

```python
# Best-effort AKG execution write-back
try:
    from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
    _akg = AeternusKnowledgeGraph.load()
    _akg.set_current_position(ticker, shares, fill_price, fill_date)
    _akg.save()
except Exception:
    pass
```

And for close/exit execution, after the close is recorded:
```python
try:
    from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
    _akg = AeternusKnowledgeGraph.load()
    _akg.close_position(ticker, exit_price, exit_date)
    _akg.save()
except Exception:
    pass
```

**IMPORTANT**: Read `paper_execution.py` carefully before adding these. Find the exact place where fills are written to the positions JSON file — add the AKG call immediately after. Never abort execution on AKG failure.

## Files to Touch
- `tradingagents/graph/knowledge_graph.py` — new fields + `set_current_position()` + `close_position()`
- `tradingagents/graph/paper_execution.py` — two write-back wiring points (open + close)
- `tests/test_knowledge_graph.py` — new tests

## Acceptance Criteria
- [ ] `set_current_position(ticker, shares, price, date)` writes `current_position` dict to AKG node
- [ ] `close_position(ticker, exit_price, exit_date)` computes `realized_return_pct`, sets `last_closed_position`, clears `current_position`, calls `record_thesis_outcome()`
- [ ] `close_position()` on a node with no current position returns False without crashing
- [ ] `_backfill_node_defaults()` fills new fields on older AKG JSON nodes
- [ ] AKG write-backs in `paper_execution.py` are fully wrapped in try/except
- [ ] Pre-existing paper execution tests still pass (no regressions)
- [ ] `python -m pytest tests/test_knowledge_graph.py -v` — all pass
- [ ] `python -m pytest tests/ -v --ignore=tests/test_cli_dealflow.py --ignore=tests/test_cli_hedging.py --ignore=tests/test_cli_score.py` — no regressions

## Status
done

## Handoff

**Completed:** 2026-02-26

**What was built:**
1. `_node_template()` in `knowledge_graph.py` — added `current_position` (None) and `last_closed_position` (None) fields after the S-044 analysis memory block.
2. `_backfill_node_defaults()` — added both S-045 fields to `_none_fields` list for backward compat with older AKG JSON files.
3. `set_current_position(ticker, shares, entry_price, entry_date)` — auto-creates node if missing, writes `current_position` dict.
4. `close_position(ticker, exit_price, exit_date)` — computes `realized_return_pct` and `hold_days`, sets `last_closed_position`, clears `current_position`, calls `record_thesis_outcome()`. Returns False if node or position is missing.
5. `execute_paper_plan()` in `paper_execution.py` — best-effort AKG write-back after positions JSON is saved; loads AKG once, calls `set_current_position()` for each BUY fill, saves.
6. `close_paper_position()` in `paper_execution.py` — best-effort AKG write-back after close is written; calls `close_position()` on the closed ticker.
7. 17 new tests added to `tests/test_knowledge_graph.py` covering all acceptance criteria.

**Test results:**
- `tests/test_knowledge_graph.py`: 108/108 passed
- Broader suite: 1328 passed, 2 pre-existing failures (unrelated to S-045), no regressions introduced.

**Files touched:**
- `tradingagents/graph/knowledge_graph.py`
- `tradingagents/graph/paper_execution.py`
- `tests/test_knowledge_graph.py`
