# AKG (Aeternus Knowledge Graph) — Complete System Specification

**Version:** 2026-02-26
**Purpose:** This document is the single source of truth for what IS built and what WILL be built in the AKG system. Written so another AI model can implement remaining tasks exactly.

---

## Table of Contents

1. [What AKG Is](#1-what-akg-is)
2. [File Locations](#2-file-locations)
3. [Node Schema (Complete)](#3-node-schema-complete)
4. [Edge Schema](#4-edge-schema)
5. [All Methods (41 public methods)](#5-all-methods)
6. [Emergence Tier System](#6-emergence-tier-system)
7. [Seed Data & Bootstrap](#7-seed-data--bootstrap)
8. [Writers (What Feeds AKG)](#8-writers-what-feeds-akg)
9. [Readers (What Reads AKG)](#9-readers-what-reads-akg)
10. [Config Keys (default_config.py)](#10-config-keys)
11. [Task Status Matrix](#11-task-status-matrix)
12. [DONE: What Is Built (S-037 through S-047)](#12-done-what-is-built)
13. [PENDING: What Must Be Built (S-049, S-050)](#13-pending-what-must-be-built)
14. [Dead Code (Safe to Delete)](#14-dead-code)
15. [Test Coverage](#15-test-coverage)
16. [Architecture Diagram](#16-architecture-diagram)
17. [Critical Rules](#17-critical-rules)

---

## 1. What AKG Is

AKG is a JSON-backed directed weighted graph that serves as the institutional memory of Aeternus. It stores:

- **Companies** — tickers with scores, positions, fundamentals cache, social velocity, emergence tiers
- **Themes** — macro themes (AI CapEx, nuclear SMR, chip export ban) with activation state
- **Sectors** — sector groups with activation state, cluster detection, priority scores
- **Edges** — supply chain relationships, catalyst links, mentions, with Hebbian weight strengthening

**Persistence:** `eval_results/control/knowledge_graph.json` (atomic writes via .tmp file)

**Core class:** `AeternusKnowledgeGraph` in `tradingagents/graph/knowledge_graph.py`

**Key design principle:** AKG stores derived intelligence, not raw data. Never store full rationale text or sub-scores in nodes — those belong in analysis JSON files. AKG stores summaries that enable fast filtering and prioritization.

---

## 2. File Locations

| File | Purpose | Lines |
|------|---------|-------|
| `tradingagents/graph/knowledge_graph.py` | Core AKG class — all methods, node/edge templates, emergence scoring | ~1,395 |
| `tradingagents/graph/data/universe_constituents.csv` | S&P 500 + Russell 2000 bootstrap data | ~3,000 rows |
| `tradingagents/default_config.py` | All AKG config keys | ~870 |
| `tradingagents/dealflow/scheduler.py` | Scheduled AKG writers (sector scout, cashtag enricher, theme scanner) | ~600 |
| `tradingagents/dealflow/pipeline.py` | Pipeline that reads AKG (get_emerging_planets) | ~400 |
| `tradingagents/dealflow/sources/sector_scout.py` | Scheduled writer: discovers tickers by sector via xAI | ~200 |
| `tradingagents/dealflow/sources/cashtag_enricher.py` | Scheduled writer: enriches top-N centrality nodes with velocity/sentiment | ~200 |
| `tradingagents/dealflow/sources/sec_catalyst.py` | Scheduled writer: 8-K events + supply chain edges (free EDGAR) | ~300 |
| `tradingagents/dealflow/sources/theme_scanner.py` | Scheduled writer: macro theme activation/deactivation | ~200 |
| `tradingagents/agents/utils/fundamental_engine.py` | Reads/writes AKG fundamentals cache (90-day TTL) | ~300 |
| `tradingagents/graph/paper_execution.py` | Writes position state to AKG on open/close | ~800 |
| `cli/commands/scoring.py` | Writes rating to AKG after analysis | ~600 |
| `tradingagents/graph/session_assembler.py` | Writes rating to AKG after session analysis | ~700 |
| `tests/test_knowledge_graph.py` | 135+ tests covering all AKG functionality | ~1,200 |

---

## 3. Node Schema (Complete)

Every node created via `_node_template()` has these fields. Grouped by the task that added them.

### Baseline Fields (S-035)
```python
"id": node_id,                    # str — unique identifier (ticker, theme_id, sector_id)
"node_type": "company",           # str — "company" | "theme" | "sector" | "account"
"sector": None,                   # str | None — AKG sector ID
"display_name": node_id,          # str — human-readable name
"signal_strength": 0.0,           # float — propagated signal strength
"centrality": 0.0,               # float — weighted degree centrality (in+out)
"times_surfaced": 0,             # int — how many times discovered by connectors
"last_surfaced": None,           # str | None — ISO date of last discovery
"aeternus_score": None,          # float | None — 0-100 composite score from analysis
"thesis_track_record": {"confirmed": 0, "invalidated": 0},  # dict — win/loss count
"metadata": {},                   # dict — arbitrary metadata
```

### Social & Emergence Fields (S-037)
```python
"cashtag_velocity_z": None,       # float | None — z-score of cashtag mention velocity
"cashtag_mentions_7d": None,      # int | None — total mentions in last 7 days
"cashtag_velocity_trend": None,   # str | None — "rising" | "falling" | "stable"
"cashtag_sentiment": None,        # float | None — -1.0 to 1.0 sentiment score
"cashtag_last_updated": None,     # str | None — ISO date of last enrichment
"sec_event_type": None,           # str | None — SEC event type (e.g., "supply_agreement")
"sec_event_date": None,           # str | None — ISO date of SEC event
"emergence_score": None,          # float | None — 0.0-1.0 composite emergence score
"emergence_tier": None,           # str | None — "DARK"|"ROCKY"|"ATMOSPHERE"|"HABITABLE"|"SCORED"
```

### Theme/Sector Activation Fields (S-040)
```python
# Theme-specific:
"active": False,                  # bool — is this theme/sector currently active?
"activation_date": None,          # str | None — ISO date theme was activated
"deactivation_date": None,        # str | None — ISO date theme was deactivated
"macro_trigger": None,            # str | None — what triggered activation (e.g., "Fed pivot")
"conviction": 0.0,               # float — 0.0-1.0 conviction level
"expected_duration_months": None, # float | None — how long theme expected to last

# Sector-specific:
"active_themes": [],              # list[str] — theme IDs driving this sector's activation
"priority_score": 0.0,           # float — 0.0-1.0 priority for resource allocation
"activated_date": None,           # str | None — ISO date sector was activated
"deactivated_date": None,         # str | None — ISO date sector was deactivated
```

### Analysis Memory Fields (S-044)
```python
"last_aeternus_score": None,      # float | None — 0-100 most recent analysis score
"last_aeternus_rating": None,     # str | None — "Strong Buy"|"Buy"|"Hold"|"Sell"|"Strong Sell"
"last_scored_date": None,         # str | None — ISO date of last analysis
"last_conviction": None,          # int | None — 1-5 confidence from scorer
"last_catalyst": None,            # str | None — key catalyst, truncated to 200 chars
"score_history": [],              # list[dict] — rolling last 10 {date, score, rating}
```

### Execution Memory Fields (S-045)
```python
"current_position": None,         # dict | None — {shares, entry_price, entry_date}
"last_closed_position": None,     # dict | None — {exit_date, exit_price, realized_return_pct, hold_days}
```

### Fundamentals Cache Fields (S-046)
```python
"fundamentals_snapshot": None,    # dict | None — cached fundamental metrics from engine
"fundamentals_fetched_at": None,  # str | None — ISO date when snapshot was taken
"earnings_date_next": None,       # str | None — ISO date of next earnings
```

### Outcome Weight Fields (S-047)
```python
"outcome_weight": 1.0,           # float — 0.5-2.0, multiplies emergence score (Hebbian)
"outcome_stats": None,            # dict | None — {n_trades, n_wins, win_rate, avg_return, avg_hold_days, total_return, total_hold_days}
```

### Cluster Detection Fields (S-050 — PENDING)
These fields go on SECTOR nodes only:
```python
"cluster_strength": 0.0,          # float — (rising_pct × avg_emergence)
"cluster_avg_emergence": 0.0,     # float — mean emergence of company nodes in sector
"cluster_rising_count": 0,        # int — nodes with emergence_score >= 0.2
"cluster_total_nodes": 0,         # int — total company nodes in sector
"cluster_last_computed": None,    # str | None — ISO date
"cluster_candidate": False,       # bool — True if strength > threshold AND sector inactive
```

---

## 4. Edge Schema

Every edge has:
```python
"source": str,                    # source node ID
"target": str,                    # target node ID
"relationship": str,              # relationship type (see below)
"weight": float,                  # 0.0-1.0, rounded to 6 decimals
"evidence_count": int,            # incremented on Hebbian strengthening
"last_confirmed": str,            # ISO date of last confirmation
"evidence_sources": list[str],    # list of evidence source names
```

### Relationship Types
| Type | Meaning | Created By |
|------|---------|------------|
| `supply_chain` | A supplies/partners with B | `seed_from_supply_chain_map()`, `update_from_sec_8k()` |
| `catalyst_beneficiary` | Company benefits from theme | `record_scout_hit()` |
| `mentioned_by` | Account/person mentioned company | `record_scout_hit()` |

### Hebbian Strengthening
When `add_edge()` is called on an existing edge:
```python
weight = min(1.0, old_weight + 0.05 * confidence)
evidence_count += 1
last_confirmed = today
```

### Edge Decay
`decay_all(days_elapsed=1)` applies exponential decay:
- Edge weights: `weight *= (1 - 0.10/30) ^ days_elapsed`, floor 0.01
- Node signal_strength: same formula, floor 0.0

---

## 5. All Methods

### Class/Factory Methods
| Method | Signature | Purpose |
|--------|-----------|---------|
| `load` | `(path=None) -> AeternusKnowledgeGraph` | Load from JSON; initialize from seed if missing |
| `from_json` | `(json_str: str) -> AeternusKnowledgeGraph` | Deserialize from JSON string |

### Persistence
| Method | Signature | Purpose |
|--------|-----------|---------|
| `to_json` | `(path=None) -> str` | Serialize to JSON; optionally write atomically |
| `save` | `(path=None) -> None` | Atomic write to default path |

### Node Operations
| Method | Signature | Purpose |
|--------|-----------|---------|
| `add_node` | `(node_id, node_type="company", sector=None, display_name=None, metadata=None) -> None` | Idempotent add; never overwrites signal_strength/centrality/score/track_record |
| `add_theme_node` | `(theme_id, display_name=None, metadata=None) -> None` | Delegates to add_node with node_type="theme" |
| `add_sector_node` | `(sector_id, display_name=None, metadata=None) -> None` | Delegates to add_node with node_type="sector" |
| `update_node_field` | `(node_id, field, value) -> bool` | Set single field; returns True if node existed |
| `get_nodes_by_type` | `(node_type) -> list` | Return nodes matching type |

### Edge Operations
| Method | Signature | Purpose |
|--------|-----------|---------|
| `add_edge` | `(source, target, relationship, confidence, evidence_source) -> None` | Add/strengthen edge; auto-creates missing nodes |
| `_outgoing_edges` | `(node_id) -> List[dict]` | Private: outgoing edges from node |
| `_incoming_edges` | `(node_id) -> List[dict]` | Private: incoming edges to node |

### Graph Algorithms
| Method | Signature | Purpose |
|--------|-----------|---------|
| `propagate_signal` | `(source_node_id, signal_strength, decay=0.5, max_hops=3) -> Dict[str, float]` | BFS signal propagation through edges |
| `get_centrality_scores` | `() -> Dict[str, float]` | Weighted degree centrality; updates all nodes |

### Emergence & Dark Nodes
| Method | Signature | Purpose |
|--------|-----------|---------|
| `get_dark_nodes` | `(min_centrality=0.3) -> List[dict]` | Company nodes with high centrality but no score |
| `compute_emergence_score` | `(ticker) -> float` | Compute 0.0-1.0 emergence + assign tier |
| `compute_all_emergence_scores` | `() -> None` | Recompute for all company nodes |
| `get_emerging_planets` | `(min_score=0.3, min_tier="ATMOSPHERE", max_aeternus_score=None, top_k=50) -> List[dict]` | Alpha candidates by emergence tier |

### Theme/Sector Activation (S-040)
| Method | Signature | Purpose |
|--------|-----------|---------|
| `activate_theme` | `(theme_id, macro_trigger, conviction=0.5, expected_duration_months=None) -> bool` | Mark theme active |
| `deactivate_theme` | `(theme_id) -> bool` | Mark theme inactive |
| `activate_sector` | `(sector_id, theme_ids: list, priority_score=0.5) -> bool` | Mark sector active; merges theme_ids |
| `deactivate_sector` | `(sector_id, theme_id=None) -> bool` | Remove theme from sector; deactivate if empty |
| `get_active_themes` | `() -> list` | Active theme nodes, sorted by conviction desc |
| `get_active_sectors` | `() -> list` | Active sector nodes, sorted by priority desc |
| `get_active_sector_ids` | `() -> set` | Set of active sector node IDs |
| `get_active_sector_companies` | `(sector_id) -> list` | Company nodes in sector, sorted by centrality desc |

### Score & Rating (S-044)
| Method | Signature | Purpose |
|--------|-----------|---------|
| `record_pipeline_score` | `(ticker, aeternus_score) -> None` | Write score after pipeline propagate() |
| `record_rating` | `(ticker, rating: dict) -> None` | Write full rating snapshot + rolling history (max 10) |

### Thesis & Outcome (S-045, S-047)
| Method | Signature | Purpose |
|--------|-----------|---------|
| `record_thesis_outcome` | `(ticker, confirmed: bool) -> None` | Increment track record; adjust edge weights |
| `record_outcome` | `(ticker, realized_return_pct, hold_days=0) -> None` | Hebbian outcome weight: +0.05 win, -0.08 loss, clamped [0.5, 2.0] |

### Position Tracking (S-045)
| Method | Signature | Purpose |
|--------|-----------|---------|
| `set_current_position` | `(ticker, shares, entry_price, entry_date) -> None` | Record position open |
| `close_position` | `(ticker, exit_price, exit_date) -> bool` | Record close; compute return; calls record_outcome + record_thesis_outcome |

### Fundamentals Cache (S-046)
| Method | Signature | Purpose |
|--------|-----------|---------|
| `set_fundamentals_cache` | `(ticker, snapshot: dict, earnings_date=None) -> None` | Cache fundamentals with today's timestamp |
| `get_fundamentals_cache` | `(ticker, ttl_days=90) -> dict | None` | Return cached snapshot if within TTL |

### Cashtag Enrichment (S-037/S-038)
| Method | Signature | Purpose |
|--------|-----------|---------|
| `enrich_node_cashtag` | `(ticker, velocity_z, mentions_7d, velocity_trend, sentiment, as_of_date) -> None` | Write cashtag fields; recompute emergence |
| `decay_all` | `(days_elapsed=1) -> None` | Exponential decay on edges and signal_strength |

### Domain Convenience
| Method | Signature | Purpose |
|--------|-----------|---------|
| `record_scout_hit` | `(ticker, sector, themes_matched, source_accounts, signal_strength) -> None` | After sector scout discovery |
| `update_from_sec_8k` | `(source_ticker, target_tickers, confidence=0.95) -> None` | After SEC 8-K parsing |
| `seed_from_supply_chain_map` | `(supply_chain_map: Dict[str, List[str]]) -> None` | Bulk seed supply chain edges |

### Export
| Method | Signature | Purpose |
|--------|-----------|---------|
| `to_obsidian` | `(vault_path) -> int` | Export full graph as Obsidian Markdown vault |

### Private
| Method | Purpose |
|--------|---------|
| `_node_template(...)` | Default node fields |
| `_edge_template(...)` | Default edge fields |
| `_seed()` | Initialize with seed sectors, themes, companies, supply chain map |
| `_bootstrap_universe()` | Load S&P 500 + Russell 2000 from CSV (S-049) |
| `_backfill_node_defaults()` | Fill missing fields on older JSON nodes |
| `_atomic_write(path, content)` | Atomic file write via .tmp |
| `_render_company_md(node)` | Obsidian export helper |
| `_render_theme_md(node)` | Obsidian export helper |
| `_render_sector_md(node, all_company_nodes)` | Obsidian export helper |
| `_render_summary(...)` | Obsidian export helper |

---

## 6. Emergence Tier System

### Tiers (ascending toward alpha)
| Tier | Meaning | Criteria |
|------|---------|----------|
| **DARK** | No velocity/sentiment data; pure centrality | Default for new nodes |
| **ROCKY** | Some signal forming | velocity_z >= 1.0 OR sentiment >= 0.3 |
| **ATMOSPHERE** | Velocity or sentiment forming but not yet habitable | (velocity_z >= 1.0 OR sentiment >= 0.3) AND NOT habitable |
| **HABITABLE** | Alpha candidate — velocity AND sentiment confirm interest | velocity_z >= 2.0 AND sentiment >= 0.5 |
| **SCORED** | Already analyzed — has an aeternus_score | aeternus_score is not None |

### Emergence Score Formula
```
score = 0.40 × centrality
      + 0.40 × normalize(velocity_z, 0, 5)
      + 0.20 × normalize(sentiment, -1, 1)

# Apply Hebbian outcome weight
score = max(0.0, min(1.0, score × outcome_weight))

# normalize(x, lo, hi):
#   if x is None: return 0.0
#   return max(0.0, min(1.0, (x - lo) / (hi - lo)))
```

### Tier Classification Logic (applied after score computation)
```python
if aeternus_score is not None:
    tier = "SCORED"
elif velocity_z >= 2.0 and sentiment >= 0.5:
    tier = "HABITABLE"
elif velocity_z >= 1.0 or sentiment >= 0.3:
    tier = "ATMOSPHERE"
elif velocity_z is not None or sentiment is not None:
    tier = "ROCKY"
else:
    tier = "DARK"
```

---

## 7. Seed Data & Bootstrap

### Manual Seeds (in `_seed()`, ~200 lines of constants)
- **8 sectors:** semis_ai_infrastructure, biotech_pharma, macro_rates, defense_aerospace, energy_power, materials_critical_minerals, china_geopolitics, fintech_banking
- **20 themes:** HBM, InP_substrates, silicon_photonics, advanced_packaging, AI_CapEx, neocloud, rare_earth, glass_substrate, nuclear_SMR, grid_interconnection, PDUFA_catalyst, Fed_pivot, yield_curve_inversion, chip_export_ban, supply_chain_decoupling, insider_cluster, LNG_export, critical_minerals, stablecoin_legislation, DoD_contract
- **~70 seed companies:** NVDA, TSM, AXTI, LITE, COHR, MSFT, GOOGL, AMZN, META, MU, INTC, AAPL, MRNA, BNTX, LMT, RTX, NOC, KTOS, MP, ALB, etc.
- **~200 supply chain edges** via SUPPLY_CHAIN_MAP constant

### Universe Bootstrap (S-049 — DONE)
`_bootstrap_universe()` loads `tradingagents/graph/data/universe_constituents.csv` (S&P 500 + Russell 2000, ~3,000 tickers) as DARK nodes on first AKG initialization. Idempotent. Gated by `AKG_UNIVERSE_BOOTSTRAP_ENABLED` env var.

Sector translation via `_YFINANCE_SECTOR_MAP`:
```python
"Technology" → "semis_ai_infrastructure"
"Healthcare" → "biotech_pharma"
"Industrials" → "defense_aerospace"
"Energy" → "energy_power"
"Basic Materials" → "materials_critical_minerals"
"Financial Services" → "fintech_banking"
"Communication Services" → "semis_ai_infrastructure"
"Utilities" → "energy_power"
"Consumer Cyclical" → None
"Consumer Defensive" → None
"Real Estate" → None
```

---

## 8. Writers (What Feeds AKG)

### Scheduled Writers (time-gated, NOT in pipeline)

| Writer | Schedule | Cost | What It Writes | Config Gate |
|--------|----------|------|----------------|-------------|
| **Sector Scout** | Once/20h | ~$0.10/run (8 xAI calls) | New company nodes via `record_scout_hit()` | `sector_scout_enabled` (disabled by default) |
| **Cashtag Enricher** | Once/4h | ~$0.015/run (50 xAI calls) | velocity_z, sentiment, mentions_7d via `enrich_node_cashtag()` | `cashtag_enricher_enabled` (disabled by default) |
| **Theme Scanner** | Once/168h | ~$0.003/run (1 xAI call) | Theme/sector activation via `activate_theme()`, `activate_sector()` | `theme_scanner_enabled` (disabled by default) |
| **SEC Catalyst** | Every pipeline run | $0 (free EDGAR) | Supply chain edges via `update_from_sec_8k()` | Always on |

### Pipeline Writers (during analysis)

| Writer | When | What It Writes | File |
|--------|------|----------------|------|
| **Rating write-back** | After analysis completes | `record_rating(ticker, rating_dict)` | `cli/commands/scoring.py`, `session_assembler.py` |
| **Position open** | After paper order fills | `set_current_position(ticker, shares, price, date)` | `paper_execution.py` |
| **Position close** | After paper close | `close_position(ticker, exit_price, exit_date)` → triggers `record_outcome()` + `record_thesis_outcome()` | `paper_execution.py` |
| **Fundamentals cache** | After fundamental_engine computes | `set_fundamentals_cache(ticker, snapshot)` | `fundamental_engine.py` |
| **Pipeline score** | After pipeline scoring | `record_pipeline_score(ticker, score)` | `pipeline.py` |

**CRITICAL:** ALL writers are wrapped in `try/except: pass`. AKG write-back is NEVER allowed to abort the pipeline.

---

## 9. Readers (What Reads AKG)

| Reader | What It Reads | Purpose |
|--------|---------------|---------|
| `pipeline.py` | `get_emerging_planets(min_score, min_tier, top_k)` | Universe expansion — zero API cost |
| `pipeline.py` | `get_dark_nodes(min_centrality)` | Alpha candidates for analysis |
| `fundamental_engine.py` | `get_fundamentals_cache(ticker, ttl_days=90)` | Skip Alpha Vantage fetch if cached |
| `sector_scout.py` | `get_active_sector_ids()`, `get_active_sector_companies()` | Scope scout to active sectors only |
| `cashtag_enricher.py` | `get_centrality_scores()`, `get_active_sector_ids()` | Scope enrichment to active sectors + top-N centrality |
| `scheduler.py` | `detect_clusters()` (S-050) | After enricher runs, detect sector-level formation |

---

## 10. Config Keys

All AKG-related config keys in `tradingagents/default_config.py`:

```python
# Sector scout (S-042)
"sector_scout_outlier_velocity_z": 3.0,

# Theme scanner (S-040/S-041)
"theme_scanner_enabled": False,
"theme_scanner_interval_hours": 168.0,
"theme_activation_threshold": 0.5,

# Cashtag enricher (S-038)
"cashtag_enricher_enabled": False,   # DISABLED by default
"cashtag_enricher_top_n": 50,
"cashtag_enricher_min_interval_hours": 4.0,
"cashtag_enricher_outlier_velocity_z": 3.0,

# AKG emerging planets reader (S-039)
"akg_emerging_min_score": 0.3,
"akg_emerging_min_tier": "ATMOSPHERE",
"akg_emerging_top_k": 50,

# AKG fundamentals cache (S-046)
"akg_fundamentals_cache_enabled": True,

# Cashtag finalist pass (S-039)
"dealflow_cashtag_finalist_pass_enabled": False,
"dealflow_cashtag_finalist_top_k": 20,

# Universe bootstrap (S-049)
"akg_universe_bootstrap_enabled": True,

# Cluster detection (S-050)
"akg_cluster_strength_threshold": 0.3,
```

---

## 11. Task Status Matrix

| Task ID | Name | Status | What It Adds |
|---------|------|--------|--------------|
| S-033 | Sector Scout | **DONE** | `sector_scout.py` — parallel xAI sector sweeps |
| S-034 | SEC Catalyst | **DONE** | `sec_catalyst.py` — 8-K + Form 4 + supply chain |
| S-035 | AKG v1 | **DONE** | `knowledge_graph.py` — core graph, persistence, Obsidian export |
| S-036 | Pipeline Front-Gate | **DONE** | `pipeline.py` — universe expansion via AKG |
| S-037 | Emergence Engine | **DONE** | Social fields + emergence scoring + tier classification |
| S-038 | Cashtag Enricher | **DONE** | `cashtag_enricher.py` — scheduled velocity/sentiment writer |
| S-039 | Pipeline AKG Reader | **DONE** | `get_emerging_planets()` replaces cashtag discovery |
| S-040 | Theme/Sector Activation | **DONE** | Activation schema + methods on AKG |
| S-041 | Theme Scanner | **DONE** | `theme_scanner.py` — weekly macro eval |
| S-042 | Sector Scout Refactor | **DONE** | Active-sector scoping + outlier detection |
| S-043 | Cashtag Active Scoping | **DONE** | Dormant sectors = $0 cost |
| S-044 | Rating Write-back | **DONE** | Analysis memory (score, rating, catalyst, history) |
| S-045 | Execution Memory | **DONE** | Position state (open/close/return) |
| S-046 | Fundamentals Cache | **DONE** | 90-day TTL caching of quarterly data |
| S-047 | Outcome Weight | **DONE** | Hebbian learning: +0.05 win, -0.08 loss, clamped [0.5, 2.0] |
| **S-049** | **Universe Bootstrap** | **DONE** | Load S&P 500 + Russell 2000 as DARK nodes |
| **S-050** | **Cluster Detection** | **PENDING** | Sector-level cluster strength computation |

---

## 12. DONE: What Is Built

### S-037 — Emergence Engine
- 9 new node fields (cashtag_velocity_z through emergence_tier)
- `enrich_node_cashtag()` — writes velocity/sentiment, recomputes emergence
- `compute_emergence_score()` / `compute_all_emergence_scores()`
- `get_emerging_planets()` — query by tier/score
- Tier classification: DARK → ROCKY → ATMOSPHERE → HABITABLE → SCORED

### S-038 — Cashtag AKG Enricher
- `cashtag_enricher.py` — staleness-gated (4h interval), top-N centrality
- Scoped to active sectors (S-043)
- Writes via `enrich_node_cashtag()` on AKG
- Wired into `scheduler.py` via `_maybe_enrich_akg_cashtags()`

### S-039 — Pipeline AKG Reader
- `pipeline.py` reads `akg.get_emerging_planets()` for zero-cost universe expansion
- Replaces cashtag discovery entirely (no API calls for discovery)
- Optional cashtag finalist pass for top-K (disabled by default)

### S-040 — Theme/Sector Activation Schema
- 10 new node fields for themes and sectors (active, conviction, priority_score, etc.)
- `activate_theme()`, `deactivate_theme()`, `activate_sector()`, `deactivate_sector()`
- `get_active_themes()`, `get_active_sectors()`, `get_active_sector_ids()`, `get_active_sector_companies()`

### S-041 — Theme Scanner
- `theme_scanner.py` — macro-driven theme evaluation (1 xAI call/week)
- Activates/deactivates themes and cascades to sectors
- Wired into scheduler with 168h interval

### S-042 — Sector Scout Refactor
- Scoped to active sectors only (dormant = $0)
- Outlier detection: velocity_z > threshold flags companies for priority enrichment

### S-043 — Cashtag Enricher Active-Sector Scoping
- Only enriches nodes in active sectors
- Dormant sectors consume zero API calls

### S-044 — Rating Write-back
- 6 new node fields: last_aeternus_score, last_aeternus_rating, last_scored_date, last_conviction, last_catalyst, score_history
- `record_rating(ticker, rating_dict)` — writes all fields + rolling history (max 10)
- Wired into `scoring.py` (after analysis) and `session_assembler.py` (after session analysis)

### S-045 — Execution Memory
- 2 new node fields: current_position, last_closed_position
- `set_current_position(ticker, shares, entry_price, entry_date)`
- `close_position(ticker, exit_price, exit_date)` — computes realized_return_pct, hold_days, calls record_thesis_outcome()
- Wired into `paper_execution.py` (open + close paths)

### S-046 — Fundamentals Cache
- 3 new node fields: fundamentals_snapshot, fundamentals_fetched_at, earnings_date_next
- `set_fundamentals_cache(ticker, snapshot, earnings_date=None)`
- `get_fundamentals_cache(ticker, ttl_days=90)` — returns cached dict or None
- Wired into `fundamental_engine.py` — cache check at start, write-back at end
- Gated by `akg_fundamentals_cache_enabled` config key

### S-047 — Outcome Weight Feedback (Hebbian Learning)
- 2 new node fields: outcome_weight (default 1.0), outcome_stats
- `record_outcome(ticker, realized_return_pct, hold_days)` — adjusts weight: +0.05 win, -0.08 loss, clamped [0.5, 2.0]
- `compute_emergence_score()` multiplies base score by outcome_weight
- `close_position()` calls `record_outcome()` automatically

### S-049 — Universe Bootstrap
- `_bootstrap_universe()` method — reads `data/universe_constituents.csv`
- `_YFINANCE_SECTOR_MAP` — translates yfinance sectors to AKG sector IDs
- Called by `_seed()` on first AKG initialization
- `scripts/generate_universe_csv.py` — one-time script to generate the CSV
- Gated by `AKG_UNIVERSE_BOOTSTRAP_ENABLED` env var

---

## 13. PENDING: What Must Be Built

### S-050 — Cluster Detection

**Purpose:** Pure graph computation that detects emerging clusters — groups of connected nodes in the same sector showing rising emergence scores simultaneously. This IS the theme detection signal. No API call. No cost.

**New sector node fields:**
```python
"cluster_strength": 0.0,          # (rising_pct × avg_emergence)
"cluster_avg_emergence": 0.0,     # mean emergence of company nodes in sector
"cluster_rising_count": 0,        # nodes with emergence_score >= 0.2
"cluster_total_nodes": 0,         # total company nodes in sector
"cluster_last_computed": None,    # ISO date
"cluster_candidate": False,       # True if strength > threshold AND sector inactive
```

**New methods:**

1. `detect_clusters(strength_threshold=0.3) -> list` — For each sector: compute avg emergence, count rising nodes (score >= 0.2), compute `cluster_strength = (rising_count / total) × avg_score`. If strength >= threshold AND sector is NOT active → mark as candidate. Returns list of candidate dicts sorted by strength desc.

2. `get_cluster_candidates() -> list` — Return sector nodes where `cluster_candidate=True`, sorted by cluster_strength desc.

**Wiring:** In `scheduler.py`, after `_maybe_enrich_akg_cashtags()` runs and AKG is saved:
```python
if result.get("ran") and self.akg:
    self.akg.compute_all_emergence_scores()
    cluster_candidates = self.akg.detect_clusters(
        strength_threshold=float(self.config.get("akg_cluster_strength_threshold", 0.3))
    )
    self.akg.save()
```

**Config key:** `"akg_cluster_strength_threshold": 0.3`

**Files to touch:**
- `tradingagents/graph/knowledge_graph.py` — new fields, `detect_clusters()`, `get_cluster_candidates()`
- `tradingagents/dealflow/scheduler.py` — wire after cashtag enricher
- `tradingagents/default_config.py` — config key (ALREADY ADDED)
- `tests/test_knowledge_graph.py` — new tests

**Backfill:** Add all 6 cluster fields to `_backfill_node_defaults()`.

---

## 14. Dead Code (Safe to Delete)

These files are NOT called by anything in the active codebase:

| File | Reason |
|------|--------|
| `tradingagents/dealflow/sources/apewisdom.py` | Never imported anywhere |
| `tradingagents/dealflow/sources/finnhub_social.py` | Replaced by social_news.py |
| `tradingagents/dealflow/sources/stocktwits.py` | Replaced by social_news.py |
| `tradingagents/dataflows/openai.py` | Not in default vendor chain |
| `tradingagents/dataflows/xai.py` | Not in default vendor chain (xAI hardcoded only in cashtag_stream) |

---

## 15. Test Coverage

All tests in `tests/test_knowledge_graph.py`. Current count: **135+ tests**.

Tests cover:
- Node template fields for all tasks (S-037 through S-047)
- `_backfill_node_defaults()` for all field groups
- All public methods (add_node, add_edge, emergence scoring, activation, rating, positions, cache, outcome weight)
- Edge cases: missing nodes, expired TTL, invalid dates, None values, clamping
- Roundtrip: save/load preserves all fields
- Idempotency: add_node twice doesn't overwrite

**Run command:**
```bash
python -m pytest tests/test_knowledge_graph.py -v
```

**Full suite (excluding known slow/broken tests):**
```bash
python -m pytest tests/ -v --ignore=tests/test_cli_dealflow.py --ignore=tests/test_cli_hedging.py --ignore=tests/test_cli_score.py
```

**Pre-existing failures (NOT regressions):**
- `test_dataflow_xai.py::test_get_news_vendor_order_prefers_xai_before_google`
- `test_paper_execution.py::test_fetch_alpaca_positions_snapshot_writes_file`

---

## 16. Architecture Diagram

```
                    ┌─────────────────────────────────────────┐
                    │              SCHEDULER                    │
                    │  (time-gated, writes to AKG)             │
                    ├─────────────────────────────────────────┤
                    │ Theme Scanner    → activate/deactivate   │
                    │ (1 xAI/168h)      themes & sectors       │
                    │                                          │
                    │ Sector Scout     → record_scout_hit()    │
                    │ (8 xAI/20h)       new company nodes      │
                    │                                          │
                    │ Cashtag Enricher → enrich_node_cashtag() │
                    │ (50 xAI/4h)       velocity, sentiment    │
                    │                                          │
                    │ SEC Catalyst     → update_from_sec_8k()  │
                    │ (free EDGAR)       supply chain edges     │
                    │                                          │
                    │ Cluster Detection→ detect_clusters()     │
                    │ (free, S-050)      sector-level signals   │
                    └──────────────┬──────────────────────────┘
                                   │ writes
                                   ▼
                    ┌─────────────────────────────────────────┐
                    │                  AKG                      │
                    │    eval_results/control/knowledge_graph   │
                    │                                          │
                    │  ~3,000 company nodes (S&P + Russell)    │
                    │  8 sector nodes                          │
                    │  20 theme nodes                          │
                    │  ~200 supply chain edges                 │
                    │                                          │
                    │  Emergence: DARK → ROCKY → ATMOSPHERE    │
                    │              → HABITABLE → SCORED         │
                    │                                          │
                    │  Hebbian weights: outcome_weight 0.5-2.0 │
                    │  Fundamentals cache: 90-day TTL          │
                    │  Score history: rolling last 10          │
                    │  Position memory: open/close/return      │
                    └──────────────┬──────────────────────────┘
                                   │ reads (zero API cost)
                                   ▼
                    ┌─────────────────────────────────────────┐
                    │              PIPELINE                     │
                    │  (reads AKG for free)                     │
                    ├─────────────────────────────────────────┤
                    │ get_emerging_planets()                    │
                    │   → ATMOSPHERE/HABITABLE tier nodes       │
                    │   → universe expansion                   │
                    │                                          │
                    │ get_dark_nodes()                          │
                    │   → high centrality + unscored            │
                    │   → forward alpha candidates              │
                    │                                          │
                    │ get_fundamentals_cache()                  │
                    │   → skip API fetch if cached < 90 days   │
                    │                                          │
                    │ 8 parallel connectors → score → rank     │
                    │ → research queue → analysis → portfolio  │
                    └──────────────┬──────────────────────────┘
                                   │ writes back after analysis
                                   ▼
                    ┌─────────────────────────────────────────┐
                    │         ANALYSIS WRITE-BACK               │
                    │                                          │
                    │ record_rating()      → score, rating,    │
                    │                        catalyst, history  │
                    │ set_current_position()→ entry tracking    │
                    │ close_position()     → return, hold_days  │
                    │   → record_outcome() → Hebbian weight    │
                    │   → record_thesis_outcome() → edge adj   │
                    │ set_fundamentals_cache() → 90d cache     │
                    └─────────────────────────────────────────┘
```

---

## 17. Critical Rules

1. **ALL AKG writes in pipeline code MUST be wrapped in `try/except: pass`.** AKG is a side effect. Never abort the pipeline on AKG failure.

2. **Idempotency.** `add_node()` never overwrites signal_strength, centrality, aeternus_score, or thesis_track_record on second call. All seed operations are idempotent.

3. **Atomic persistence.** `save()` writes to `.tmp` then renames. Never partial writes.

4. **Cost gate.** Scheduled writers (sector scout, cashtag enricher, theme scanner) are ALL disabled by default. Must be explicitly enabled via config. SEC catalyst is always on because it's free (EDGAR).

5. **Backfill.** Every new field MUST be added to `_backfill_node_defaults()` so older JSON files load cleanly. This is called by `from_json()`.

6. **Emergence score formula.** Changes to the emergence formula affect ALL downstream behavior (which tickers get analyzed, which get prioritized). The formula is: `0.40×centrality + 0.40×normalize(velocity_z) + 0.20×normalize(sentiment)`, multiplied by `outcome_weight`, clamped to [0.0, 1.0].

7. **Data freshness taxonomy.** Do NOT cache daily-changing data (prices, RSI, news). DO cache quarterly data (P/E, margins, F-Score → 90-day TTL). Earnings date → cache until date passes.

8. **The edge of the event horizon of quality and cost.** Before any new API call: what does it cost, can it be cached, is the quality gain worth it? Persistent stores written by scheduled jobs → pipeline reads for free.
