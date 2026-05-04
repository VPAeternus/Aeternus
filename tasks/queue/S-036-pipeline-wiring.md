# Task S-036: Pipeline Front-Gate Wiring
**Assignee:** Sonnet
**Status:** pending
**Branch:** feature/sonnet46 (branch from feature/opus46)
**Priority:** high
**Depends on:** S-033 (sector_scout), S-034 (sec_catalyst), S-035 (knowledge_graph) — all must be merged first

---

## Goal

Wire sector_scout, sec_catalyst, and knowledge_graph at the **front** of the deal flow pipeline so that:

1. Scout-discovered symbols **expand the universe** before all other connectors run (currently they don't — sector_scout runs after the universe is already built)
2. SEC catalyst hits **also expand the universe** before scoring
3. Knowledge graph **dark nodes** (high-centrality, unscored companies) are injected into the discovery targets at the start
4. Knowledge graph is **updated** at the end of each run with new discoveries

The pipeline must never analyze garbage. The front gate ensures only scout-cleared or core-universe names enter the expensive analysis phase.

---

## Files to Modify

1. `tradingagents/dealflow/pipeline.py` — surgical changes only (see exact line references below)
2. `tradingagents/dealflow/sources/__init__.py` — add `collect_sec_catalyst_signals`
3. `tradingagents/default_config.py` — add `akg_enabled`, `akg_json_path`, `akg_dark_node_injection_enabled`

**Do NOT change:** scoring logic, ranking logic, cashtag double-run pattern, connector health tracking structure, any connector other than the three above.

---

## Current Pipeline Flow (simplified)

```
1. cashtag discovery run → prioritized_discovered
2. universe = build_universe(prioritized_discovered | manual_symbols)
3. cashtag re-run against full universe → cashtag_signals
4. all other connectors in parallel (social_news, finnhub, macro, breakout, ...)
5. sector_scout runs HERE (after universe built) ← WRONG POSITION
6. score_candidates(signals)
7. rank_candidates
```

Problem: sector_scout and SEC catalyst discovered symbols never expand the universe. Names they find that aren't already in the universe get silently ignored.

---

## Target Pipeline Flow

```
0. knowledge_graph.get_dark_nodes() → dark_node_symbols   [NEW]
1. EARLY DISCOVERY PHASE (parallel):                       [RESTRUCTURED]
   a. cashtag discovery run → cashtag_discovered
   b. sector_scout run → scout_signals + scout_discovered  [MOVED EARLIER]
   c. sec_catalyst run → catalyst_signals + catalyst_discovered [NEW]
2. universe = build_universe(                              [EXPANDED]
       cashtag_discovered | scout_discovered |
       catalyst_discovered | dark_node_symbols | manual_symbols
   )
3. cashtag re-run against full universe → cashtag_signals  [UNCHANGED]
4. all other connectors in parallel                        [UNCHANGED]
5. merge scout_signals + catalyst_signals into signals     [MOVED FROM STEP 5]
6. score_candidates(signals)                               [UNCHANGED]
7. rank_candidates                                         [UNCHANGED]
8. knowledge_graph.update(signals, catalyst_signals)       [NEW]
```

---

## Exact Changes to pipeline.py

### Change 1: Add imports (top of file, after existing imports)

After the `from .sources import (...)` block, add:

```python
from .sources.sec_catalyst import collect_sec_catalyst_signals
from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
```

Wrap in try/except so the pipeline degrades gracefully if either module isn't installed yet:

```python
try:
    from .sources.sec_catalyst import collect_sec_catalyst_signals as _collect_sec_catalyst
    _SEC_CATALYST_AVAILABLE = True
except ImportError:
    _SEC_CATALYST_AVAILABLE = False

try:
    from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph as _AKG
    _AKG_AVAILABLE = True
except ImportError:
    _AKG_AVAILABLE = False
```

### Change 2: Knowledge graph dark node injection (before cashtag discovery)

In `DealFlowPipeline.run()`, after `manual_symbols` is built (currently ~line 65) and before the first cashtag call (~line 73), add:

```python
# --- Knowledge Graph: inject dark nodes into discovery targets ---
_dark_node_symbols: List[str] = []
if _AKG_AVAILABLE and self.config.get("akg_enabled", True) and self.config.get("akg_dark_node_injection_enabled", True):
    try:
        _akg = _AKG.load(self.config.get("akg_json_path", "eval_results/control/knowledge_graph.json"))
        _dark_nodes = _akg.get_dark_nodes(
            min_centrality=float(self.config.get("akg_dark_node_min_centrality", 0.3))
        )
        _dark_node_symbols = [n["id"] for n in _dark_nodes if n.get("id")]
    except Exception:
        _dark_node_symbols = []
```

### Change 3: Run sector_scout EARLY (parallel with cashtag discovery)

Currently sector_scout runs at ~lines 204-225, AFTER the universe is built. Move it to run in parallel with the cashtag discovery (before the universe expansion).

After the first cashtag discovery run block (currently ~lines 73-103), add the early sector scout and SEC catalyst runs:

```python
# --- Early sector scout (parallel with cashtag discovery) ---
# Run once here — results used for universe expansion AND signal scoring.
# Not re-run after universe expansion (cost: 7-8 xAI calls per run).
_scout_signals: List[Dict] = []
_scout_metadata: Dict[str, Any] = {}
_scout_discovered: List[str] = []
_scout_health: Dict[str, Any] = {}
_scout_start = time.perf_counter()
try:
    _scout_signals, _scout_metadata = collect_sector_scout_signals(
        base_universe,
        as_of_date=as_of_date,
        config=self.config,
    )
    # Extract discovered symbols: tickers in scout signals not in base universe
    base_syms = {str(r.get("symbol", "")).upper() for r in base_universe}
    _scout_discovered = [
        s["symbol"] for s in _scout_signals
        if s.get("symbol") and s["symbol"] not in base_syms
    ]
    _scout_health = self._build_connector_health_entry(
        connector_name="sector_scout",
        signals=_scout_signals,
        latency_ms=(time.perf_counter() - _scout_start) * 1000.0,
        error_message="",
        metadata={"sectors_swept": len(self.config.get("sector_scout_sectors", {}))},
    )
except Exception as exc:
    _scout_health = self._build_connector_health_entry(
        connector_name="sector_scout",
        signals=[],
        latency_ms=(time.perf_counter() - _scout_start) * 1000.0,
        error_message=str(exc),
    )

# --- Early SEC catalyst monitor ---
_catalyst_signals: List[Dict] = []
_catalyst_discovered: List[str] = []
_catalyst_health: Dict[str, Any] = {}
_catalyst_start = time.perf_counter()
if _SEC_CATALYST_AVAILABLE and self.config.get("dealflow_sec_enabled", True):
    try:
        _catalyst_signals = _collect_sec_catalyst(
            as_of_date=as_of_date,
            config=self.config,
        )
        base_syms = {str(r.get("symbol", "")).upper() for r in base_universe}
        _catalyst_discovered = [
            s["symbol"] for s in _catalyst_signals
            if s.get("symbol") and s["symbol"] not in base_syms
        ]
        _catalyst_health = self._build_connector_health_entry(
            connector_name="sec_catalyst",
            signals=_catalyst_signals,
            latency_ms=(time.perf_counter() - _catalyst_start) * 1000.0,
            error_message="",
        )
    except Exception as exc:
        _catalyst_health = self._build_connector_health_entry(
            connector_name="sec_catalyst",
            signals=[],
            latency_ms=(time.perf_counter() - _catalyst_start) * 1000.0,
            error_message=str(exc),
        )
```

### Change 4: Expand universe with all discovery sources

The current universe expansion (~lines 105-108) uses only cashtag discoveries:
```python
# CURRENT:
universe = build_universe(
    extra_symbols=sorted(set(prioritized_discovered) | set(manual_symbols)),
    ...
)
```

Change to include scout and catalyst discoveries AND dark nodes:
```python
# NEW:
_all_discovered = (
    set(prioritized_discovered)
    | set(_scout_discovered)
    | set(_catalyst_discovered)
    | set(_dark_node_symbols)
    | set(manual_symbols)
)
universe = build_universe(
    extra_symbols=sorted(_all_discovered),
    min_extra_adv_usd=float(self.config.get("dealflow_dynamic_universe_min_adv_usd", 50_000_000.0)),
)
```

### Change 5: Remove the late sector_scout block

Delete the current sector_scout block at ~lines 204-225:
```python
# DELETE THIS ENTIRE BLOCK:
sector_scout_start = time.perf_counter()
sector_scout_error = ""
sector_scout_metadata: Dict[str, Any] = {}
sector_scout_signals: List[Dict] = []
try:
    sector_scout_signals, sector_scout_metadata = collect_sector_scout_signals(...)
    ...
connector_health.append(...)
signals.extend(sector_scout_signals)
```

### Change 6: Add scout and catalyst signals + health entries after parallel block

After the parallel connector block completes (~line 202, where `signals.extend(cashtag_signals)` is), add:

```python
# Add pre-computed scout and catalyst signals (run early for universe expansion)
signals.extend(_scout_signals)
signals.extend(_catalyst_signals)
connector_health.append(_scout_health)
connector_health.append(_catalyst_health)
```

### Change 7: Knowledge graph update at end of run

After `ranked` is computed (~line 274, after `rank_candidates`), add:

```python
# --- Knowledge Graph: update with discoveries from this run ---
if _AKG_AVAILABLE and self.config.get("akg_enabled", True):
    try:
        _akg = _AKG.load(self.config.get("akg_json_path", "eval_results/control/knowledge_graph.json"))
        # Add all surfaced symbols as nodes
        for sig in _scout_signals + _catalyst_signals:
            sym = sig.get("symbol")
            if sym:
                sector = _scout_metadata.get(sym, {}).get("sectors", ["unknown"])[0] if sig.get("signal_family") == "sector_scout" else "sec_catalyst"
                _akg.add_node(
                    node_id=sym,
                    node_type="company",
                    sector=sector,
                    metadata={"last_surfaced": as_of_date},
                )
        # Add supply chain edges from catalyst signals
        for sig in _catalyst_signals:
            if sig.get("signal_family") == "supply_chain_propagation":
                source = sig.get("metadata", {}).get("propagated_from")
                target = sig.get("symbol")
                if source and target:
                    _akg.add_edge(source, target, "supply_chain", confidence=0.7, evidence=["sec_8k"])
        _akg.to_json(self.config.get("akg_json_path", "eval_results/control/knowledge_graph.json"))
    except Exception:
        pass  # AKG update failure must never break the pipeline
```

---

## sources/__init__.py Changes

Add `collect_sec_catalyst_signals` to imports and `__all__`:

```python
# Add this line (after existing imports, guarded for import safety):
try:
    from .sec_catalyst import collect_sec_catalyst_signals
    __all__.append("collect_sec_catalyst_signals")
except ImportError:
    pass  # sec_catalyst not yet installed
```

---

## default_config.py Changes

Add these keys (find the dealflow section and append):

```python
# Knowledge Graph
"akg_enabled": True,
"akg_json_path": "eval_results/control/knowledge_graph.json",
"akg_obsidian_vault_path": "eval_results/akg_vault",
"akg_dark_node_min_centrality": 0.3,
"akg_dark_node_injection_enabled": True,
"akg_decay_rate_per_30_days": 0.10,
"akg_hebbian_strength_increment": 0.05,
```

---

## Critical Constraints

1. **AKG and sec_catalyst import failures must be silent** — the pipeline runs fine without them. Use try/except on all imports and all AKG operations.
2. **Sector scout must NOT run twice** — it already ran in the early phase. Delete the late block entirely.
3. **Cashtag still runs twice** — this is intentional (existing pattern, don't change it).
4. **connector_health order** — existing connectors must appear in the same order in the health summary. Scout and catalyst health entries append at the end.
5. **No new external dependencies** — everything is stdlib + existing packages.
6. **The AKG update at the end is best-effort** — wrap entirely in try/except, never propagate exceptions.

---

## Verification

```bash
# Smoke test (no API keys needed — all connectors degrade gracefully when not configured)
python -m cli.main --help

# Full pipeline smoke (requires API keys in .env)
aeternus source --date 2026-02-25 --trigger manual --top-k 20 --format table

# Connector health should now show sector_scout and sec_catalyst entries
# Scout signals should appear in the shortlist candidates

# Test suite — no new failures vs baseline (66 pre-existing)
python -m pytest tests/ -q 2>&1 | tail -5
```

---

## What Done Looks Like

- `python -m pytest tests/ -q` — no new failures
- `aeternus source` completes with `sector_scout` and `sec_catalyst` entries in connector health
- Names discovered by sector scout that aren't in core universe appear in the shortlist
- Knowledge graph JSON updated at `eval_results/control/knowledge_graph.json` after each run
- No second sector_scout call (verify via log or timing)
