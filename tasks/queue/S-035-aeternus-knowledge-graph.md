# Task S-035: Aeternus Knowledge Graph (AKG) v1

**Assignee:** Sonnet
**Status:** pending
**Branch:** feature/sonnet46 (branch from feature/opus46)
**Priority:** high

## Tier
sonnet

## Summary
Build the AKG — a living, JSON-backed, directed weighted graph that is the institutional memory of Aeternus. It persists across sessions, grows as scouts surface new connections, powers forward-propagation of catalysts to 2nd-order beneficiaries, and exports to Obsidian for visual sector analysis by the operator.

## Context

### Architectural Position
The AKG sits between the deal flow layer and the pipeline orchestrator. It is NOT part of the LangGraph agent pipeline. It is a standalone Python module called by:
1. `tradingagents/dealflow/pipeline.py` — reads dark nodes, writes scout discoveries
2. `tradingagents/dealflow/sources/sec_catalyst.py` (S-034) — writes supply chain edges when 8-K fires
3. The CLI `aeternus source` command — after each deal flow run

The AKG does NOT call LLMs. It is pure Python computation — graph traversal, weight arithmetic, JSON I/O, and Markdown generation. Keep it zero-dependency beyond the stdlib.

### Dependencies
- S-033 (sector_scout.py) must be merged before AKG integration in pipeline.py — the AKG ingests sector scout metadata (themes_matched, source_accounts) to build edges.
- S-034 (sec_catalyst.py) must be merged — the AKG imports `SUPPLY_CHAIN_MAP` from sec_catalyst.py as its seed edge data.
- The AKG itself has no upstream dependencies. Write `knowledge_graph.py` and its tests independently; wire into pipeline after S-033 and S-034 land.

### Storage
JSON file: `eval_results/control/knowledge_graph.json`
This directory already exists (the capital allocator DB lives there). Do not create a new directory.

### Key Design Constraints
- Zero external dependencies. Only stdlib: `json`, `math`, `datetime`, `pathlib`, `collections`.
- All graph operations must complete in < 1 second for a graph of 10,000 nodes and 50,000 edges. Use adjacency lists, not matrices.
- JSON roundtrip must be lossless. All floats stored as Python `float`, all datetimes as ISO 8601 strings.
- The graph is operator-facing infrastructure. Keep the code readable. No clever abstractions.

## Requirements

### 1. Core Graph Class: tradingagents/graph/knowledge_graph.py

**Important:** This goes in `tradingagents/graph/`, not `tradingagents/dealflow/`. The graph package already contains `aeternus_scoring.py`, `trading_graph.py`, etc. The knowledge graph is a cross-cutting concern owned by the graph layer.

```python
"""
Aeternus Knowledge Graph (AKG) v1.

A living directed weighted graph representing relationships between companies,
themes, sectors, and catalysts. JSON-backed, zero external dependencies.

Grows as scouts discover connections. Edges decay without reinforcement.
High-centrality dark nodes are the alpha — connected to hot themes but
not yet analyzed by the pipeline.

Usage:
    graph = AeternusKnowledgeGraph.load()  # loads or initializes from disk
    graph.add_node("AXTI", node_type="company", sector="semis_ai_infrastructure")
    graph.add_edge("NVDA", "AXTI", relationship="supply_chain", confidence=0.9)
    dark = graph.get_dark_nodes(min_centrality=0.3)  # alpha candidates
    graph.propagate_signal("NVDA", signal_strength=0.9)  # {AXTI: 0.54, ...}
    graph.to_obsidian("/path/to/vault")
    graph.save()
"""
```

#### Node Schema (stored in graph.json under `"nodes"` dict, keyed by node id)
```python
{
    "id": "AXTI",
    "node_type": "company",  # company | theme | sector | catalyst | account
    "sector": "semis_ai_infrastructure",  # null for non-company nodes
    "display_name": "AXT Inc",
    "signal_strength": 0.0,   # 0-1, updated by scouts. Decays nightly.
    "centrality": 0.0,        # 0-1, recomputed by get_centrality_scores()
    "times_surfaced": 0,      # incremented each time a scout mentions this node
    "last_surfaced": null,    # ISO date string or null
    "aeternus_score": null,   # float or null; set after pipeline runs on this ticker
    "thesis_track_record": {"confirmed": 0, "invalidated": 0},
    "metadata": {}            # arbitrary extra data, e.g. {"sector_themes": ["InP"]}
}
```

#### Edge Schema (stored in graph.json under `"edges"` list)
```python
{
    "source": "NVDA",
    "target": "AXTI",
    "relationship": "supply_chain",  # supply_chain | co_mention | sector_peer | catalyst_beneficiary | mentioned_by
    "weight": 0.85,          # confidence 0-1. Increases with evidence, decays with time.
    "evidence_count": 1,
    "last_confirmed": "2026-02-25",
    "evidence_sources": ["sec_8k"]  # list of strings: sec_8k | xai_scout | earnings_call | manual
}
```

#### Graph JSON root structure
```json
{
    "version": 1,
    "created_at": "2026-02-25T00:00:00Z",
    "updated_at": "2026-02-25T12:34:56Z",
    "nodes": {
        "AXTI": { ...node schema... },
        "NVDA": { ...node schema... }
    },
    "edges": [
        { ...edge schema... }
    ]
}
```

#### Required Methods

**`AeternusKnowledgeGraph.load(path=None) -> AeternusKnowledgeGraph`** (classmethod)
Load from JSON at `path` (default: `eval_results/control/knowledge_graph.json`). If file does not exist, call `_seed()` to initialize with baseline data and return the seeded instance (do NOT save yet — caller decides when to save). If file exists but is malformed JSON, raise `ValueError` with clear message.

**`save(path=None)`**
Write full graph to JSON. Atomic write: write to `.tmp` file, then `os.replace()`. Never leave a half-written file.

**`add_node(id, node_type="company", sector=None, display_name=None, metadata=None)`**
Idempotent. If node exists, update only: `display_name` (if provided), `sector` (if provided), `metadata` (shallow merge). Never overwrite `signal_strength`, `centrality`, `times_surfaced`, `aeternus_score`, or `thesis_track_record` if node already exists — those are owned by other methods.

**`add_edge(source, target, relationship, confidence, evidence_source)`**
- Auto-creates missing source/target nodes (node_type="company", no sector).
- If edge already exists (same source+target+relationship), update it:
  - `weight = min(1.0, existing_weight + 0.05 * confidence)` — Hebbian strengthening
  - `evidence_count += 1`
  - `last_confirmed = today`
  - Append `evidence_source` to `evidence_sources` if not already present
- If edge is new, create it with the given `confidence` as initial weight.

**`propagate_signal(source_node_id, signal_strength, decay=0.5, max_hops=3) -> Dict[str, float]`**
BFS from `source_node_id`. At each hop, multiply signal by `decay * edge_weight`. Returns dict of `{node_id: propagated_strength}` for all reached nodes (excluding source). Stops at `max_hops` or when propagated strength < 0.01.

```python
def propagate_signal(self, source_node_id, signal_strength, decay=0.5, max_hops=3):
    result = {}
    queue = deque([(source_node_id, signal_strength, 0)])
    visited = {source_node_id}

    while queue:
        node_id, strength, hops = queue.popleft()
        if hops >= max_hops:
            continue
        for edge in self._outgoing_edges(node_id):
            neighbor = edge["target"]
            propagated = strength * decay * edge["weight"]
            if propagated < 0.01:
                continue
            if neighbor not in visited:
                visited.add(neighbor)
                result[neighbor] = propagated
                queue.append((neighbor, propagated, hops + 1))
            elif propagated > result.get(neighbor, 0):
                result[neighbor] = propagated  # keep highest path

    return result
```

**`get_centrality_scores() -> Dict[str, float]`**
Compute degree-based centrality for all nodes. Full PageRank is too slow for daily runs; use weighted in-degree + out-degree normalized to 0-1.

```python
def get_centrality_scores(self):
    degree: Dict[str, float] = {}
    for edge in self._edges:
        degree[edge["source"]] = degree.get(edge["source"], 0) + edge["weight"]
        degree[edge["target"]] = degree.get(edge["target"], 0) + edge["weight"]

    if not degree:
        return {}

    max_degree = max(degree.values())
    if max_degree == 0:
        return {n: 0.0 for n in degree}

    scores = {n: d / max_degree for n, d in degree.items()}
    # Update centrality on node objects in-place
    for node_id, score in scores.items():
        if node_id in self._nodes:
            self._nodes[node_id]["centrality"] = round(score, 6)
    return scores
```

**`decay_all(days_elapsed=1)`**
Apply exponential decay to all edge weights. Default: 10% decay per 30 days (for each 1-day tick: `weight *= 0.9 ** (days_elapsed / 30)`). Never decay below 0.01. Also decay `signal_strength` on all nodes: same formula.

```python
def decay_all(self, days_elapsed=1):
    decay_factor = 0.9 ** (days_elapsed / 30.0)
    min_weight = 0.01

    for edge in self._edges:
        edge["weight"] = max(min_weight, round(edge["weight"] * decay_factor, 6))

    for node in self._nodes.values():
        node["signal_strength"] = max(0.0, round(node["signal_strength"] * decay_factor, 6))
```

**`get_dark_nodes(min_centrality=0.3) -> List[Dict]`**
Return all company nodes where:
- `centrality >= min_centrality` (connected to important nodes)
- `aeternus_score is None` (never been analyzed by the pipeline)

Sort by `centrality` descending. These are the alpha — nodes the graph thinks are important but that the pipeline has never scored.

**`record_scout_hit(ticker, sector, themes_matched, source_accounts, signal_strength)`**
Convenience method called after each sector scout run:
1. `add_node(ticker, node_type="company", sector=sector)`
2. Increment `times_surfaced` on the node
3. Set `last_surfaced = today`
4. Update `signal_strength = min(1.0, existing + signal_strength * 0.2)` (additive up to cap)
5. For each theme in `themes_matched`: `add_node(theme, node_type="theme")` + `add_edge(ticker, theme, "catalyst_beneficiary", confidence=0.7, evidence_source="xai_scout")`
6. For each account in `source_accounts`: `add_node(account, node_type="account")` + `add_edge(account, ticker, "mentioned_by", confidence=0.6, evidence_source="xai_scout")`

**`record_pipeline_score(ticker, aeternus_score)`**
Update `aeternus_score` on the node. This is called by `trading_graph.py` after `propagate()` returns a rating.

**`record_thesis_outcome(ticker, confirmed: bool)`**
Increment `thesis_track_record["confirmed"]` or `["invalidated"]`. Strengthen or weaken connected edges:
- Confirmed: add 0.03 to all outgoing edges from ticker
- Invalidated: subtract 0.05 from all outgoing edges (floor 0.01)

**`update_from_sec_8k(source_ticker, target_tickers, confidence=0.95)`**
Called by sec_catalyst.py after parsing a supply agreement 8-K. Creates supply_chain edges from source to each target.

**`to_obsidian(vault_path) -> int`** (returns count of files written)
Export the full graph as an Obsidian-compatible Markdown vault. Details in section 4 below.

**`to_json(path=None) -> str`** (returns JSON string, also writes to path if provided)
Serialize graph to JSON string.

**`from_json(json_str) -> AeternusKnowledgeGraph`** (classmethod)
Deserialize from JSON string. Used for testing.

**`_seed()`** (private)
Initialize the graph with baseline data. Called by `load()` when file does not exist. Seeds:
- 7 sector super-nodes
- 20 theme nodes
- Company nodes from a hardcoded SEED_COMPANIES list
- Supply chain edges from `SUPPLY_CHAIN_MAP` imported from `tradingagents.dealflow.sources.sec_catalyst`

```python
SEED_SECTORS = [
    "semis_ai_infrastructure", "biotech_pharma", "macro_rates",
    "defense_aerospace", "energy_power", "materials_critical_minerals",
    "china_geopolitics", "fintech_banking",
]

SEED_THEMES = [
    "HBM", "InP_substrates", "silicon_photonics", "advanced_packaging",
    "AI_CapEx", "neocloud", "rare_earth", "glass_substrate",
    "nuclear_SMR", "grid_interconnection", "PDUFA_catalyst",
    "Fed_pivot", "yield_curve_inversion", "chip_export_ban",
    "supply_chain_decoupling", "insider_cluster", "LNG_export",
    "critical_minerals", "stablecoin_legislation", "DoD_contract",
]

SEED_COMPANIES = [
    # Semis/AI infra
    ("NVDA", "semis_ai_infrastructure", "NVIDIA Corp"),
    ("TSM", "semis_ai_infrastructure", "Taiwan Semiconductor Mfg"),
    ("AXTI", "semis_ai_infrastructure", "AXT Inc"),
    ("LITE", "semis_ai_infrastructure", "Lumentum Holdings"),
    ("COHR", "semis_ai_infrastructure", "Coherent Corp"),
    ("MRVL", "semis_ai_infrastructure", "Marvell Technology"),
    ("AMKR", "semis_ai_infrastructure", "Amkor Technology"),
    ("SMCI", "semis_ai_infrastructure", "Super Micro Computer"),
    ("AVGO", "semis_ai_infrastructure", "Broadcom Inc"),
    ("AMAT", "semis_ai_infrastructure", "Applied Materials"),
    ("ASML", "semis_ai_infrastructure", "ASML Holding"),
    ("LRCX", "semis_ai_infrastructure", "Lam Research"),
    ("KLAC", "semis_ai_infrastructure", "KLA Corp"),
    ("ENTG", "semis_ai_infrastructure", "Entegris Inc"),
    # Hyperscalers
    ("MSFT", "semis_ai_infrastructure", "Microsoft Corp"),
    ("GOOGL", "semis_ai_infrastructure", "Alphabet Inc"),
    ("AMZN", "semis_ai_infrastructure", "Amazon.com Inc"),
    ("META", "semis_ai_infrastructure", "Meta Platforms"),
    # Neoclouds
    ("CRWV", "semis_ai_infrastructure", "CoreWeave Inc"),
    ("NBIS", "semis_ai_infrastructure", "Nebius Group"),
    # Energy/power infra
    ("VRT", "energy_power", "Vertiv Holdings"),
    ("EQIX", "energy_power", "Equinix Inc"),
    ("DLR", "energy_power", "Digital Realty Trust"),
    # Biotech
    ("MRNA", "biotech_pharma", "Moderna Inc"),
    ("BNTX", "biotech_pharma", "BioNTech SE"),
    # Defense
    ("LMT", "defense_aerospace", "Lockheed Martin"),
    ("RTX", "defense_aerospace", "RTX Corp"),
    ("NOC", "defense_aerospace", "Northrop Grumman"),
    ("KTOS", "defense_aerospace", "Kratos Defense"),
    ("AVAV", "defense_aerospace", "AeroVironment Inc"),
    # Critical minerals
    ("MP", "materials_critical_minerals", "MP Materials"),
    ("ALB", "materials_critical_minerals", "Albemarle Corp"),
    ("LTHM", "materials_critical_minerals", "Livent Corp"),
    # EV
    ("TSLA", "semis_ai_infrastructure", "Tesla Inc"),
    # Nuclear
    ("BWXT", "energy_power", "BWX Technologies"),
    ("OKLO", "energy_power", "Oklo Inc"),
    # Fintech
    ("SQ", "fintech_banking", "Block Inc"),
    ("PYPL", "fintech_banking", "PayPal Holdings"),
    # Semis — legacy
    ("INTC", "semis_ai_infrastructure", "Intel Corp"),
    ("QCOM", "semis_ai_infrastructure", "Qualcomm Inc"),
    ("MU", "semis_ai_infrastructure", "Micron Technology"),
    ("AAPL", "semis_ai_infrastructure", "Apple Inc"),
    ("GLW", "semis_ai_infrastructure", "Corning Inc"),
]
```

Seed all supply chain edges from `SUPPLY_CHAIN_MAP`:
```python
from tradingagents.dealflow.sources.sec_catalyst import SUPPLY_CHAIN_MAP
for source, targets in SUPPLY_CHAIN_MAP.items():
    self.add_node(source, node_type="company")
    for target in targets:
        self.add_node(target, node_type="company")
        self.add_edge(source, target, relationship="supply_chain",
                      confidence=0.8, evidence_source="seed")
```

### 2. Internal Data Structures

Use dict-based adjacency for performance:

```python
class AeternusKnowledgeGraph:
    def __init__(self):
        self._nodes: Dict[str, dict] = {}   # node_id -> node dict
        self._edges: List[dict] = []        # flat list of edge dicts
        self._adj_out: Dict[str, List[int]] = defaultdict(list)   # node_id -> list of edge indices
        self._adj_in: Dict[str, List[int]] = defaultdict(list)    # node_id -> list of edge indices
        self._edge_index: Dict[Tuple[str, str, str], int] = {}    # (src, tgt, rel) -> edge list index
        self._created_at: str = dt.datetime.utcnow().isoformat() + "Z"
        self._updated_at: str = self._created_at
        self._version: int = 1
```

When an edge is added, update both `_adj_out[source]` and `_adj_in[target]` with the edge index. `_edge_index` allows O(1) lookup for "does this edge exist?"

**`_outgoing_edges(node_id) -> List[dict]`**: return `[self._edges[i] for i in self._adj_out[node_id]]`

### 3. File Layout

```
tradingagents/graph/knowledge_graph.py   ← core class (this task)
tests/test_knowledge_graph.py            ← tests (this task)
```

No CLI command in this task. The AKG is library code. A CLI command (`aeternus kg-status`) can be added in a future task.

### 4. Obsidian Export

**`to_obsidian(vault_path) -> int`**

Create directory structure:
```
{vault_path}/
  companies/        ← one .md per company node
  themes/           ← one .md per theme node
  sectors/          ← one .md per sector super-node
  _graph_summary.md ← global overview
```

**Company file format** (`companies/AXTI.md`):
```markdown
---
ticker: AXTI
sector: semis_ai_infrastructure
signal_strength: 0.87
centrality: 0.72
aeternus_score: 71.5
times_surfaced: 14
last_surfaced: 2026-02-25
thesis_confirmed: 3
thesis_invalidated: 1
---

# AXT Inc ($AXTI)

## Supply Chain Position
<!-- outgoing supply_chain edges -->
Supplies: [[InP_substrates]] → downstream customers

## Connected Companies
<!-- all outgoing edges grouped by relationship type -->
### Supplies to
- [[LITE]]
- [[COHR]]

### Sector Peers
- [[SMTC]]

### Catalyst Beneficiaries
- [[NVDA]]
- [[GOOGL]]

## Mentioned By
<!-- incoming mentioned_by edges -->
- [[SemiAnalysis]]

## Themes
<!-- outgoing catalyst_beneficiary edges to theme nodes -->
- [[InP_substrates]]
- [[silicon_photonics]]

## Signal History
- times_surfaced: 14
- last_surfaced: 2026-02-25
- signal_strength: 0.87

## Track Record
- Confirmed theses: 3
- Invalidated: 1
```

**Theme file format** (`themes/InP_substrates.md`):
```markdown
---
theme: InP_substrates
node_type: theme
---

# InP Substrates

## Companies in This Theme
<!-- incoming catalyst_beneficiary edges from company nodes -->
- [[AXTI]]
- [[LITE]]
```

**Sector file format** (`sectors/semis_ai_infrastructure.md`):
```markdown
---
sector: semis_ai_infrastructure
---

# Semis / AI Infrastructure

## Companies
<!-- all company nodes in this sector, sorted by centrality desc -->
- [[NVDA]] — centrality: 0.95, signal: 0.9, score: 88.5
- [[AXTI]] — centrality: 0.72, signal: 0.87, score: 71.5
- [[LITE]] — centrality: 0.65, signal: 0.6, score: null
```

**`_graph_summary.md`**:
```markdown
# Aeternus Knowledge Graph — Summary

Generated: 2026-02-25T12:34:56Z

## Stats
- Total nodes: 143
- Total edges: 312
- Company nodes: 60
- Theme nodes: 20
- Sector nodes: 8

## Top Centrality Nodes
| Ticker | Centrality | Signal | Score | Times Surfaced |
|--------|------------|--------|-------|----------------|
| NVDA   | 0.95       | 0.90   | 88.5  | 47             |
| AXTI   | 0.72       | 0.87   | 71.5  | 14             |
...top 15...

## Dark Nodes (High Centrality, Not Yet Scored)
| Ticker | Centrality | Times Surfaced | Sector |
|--------|------------|----------------|--------|
| CRWV   | 0.68       | 8              | semis_ai_infrastructure |
...up to 10...

## Hot Sectors (by average signal_strength)
1. semis_ai_infrastructure — avg signal: 0.74
2. energy_power — avg signal: 0.61
...
```

**Implementation notes for `to_obsidian`:**
- Use `pathlib.Path` throughout. Create directories with `mkdir(parents=True, exist_ok=True)`.
- Sanitize node IDs for filenames: replace `/`, `\`, `:` with `_`.
- Obsidian wiki links are `[[FileName]]` — use the node's `display_name` if available, else `id`.
- Return count of files written.

### 5. Pipeline Integration in pipeline.py

This wiring happens AFTER S-033 and S-034 are merged. The spec is provided here so Sonnet knows the intent.

Add to `tradingagents/dealflow/pipeline.py`:

```python
# After all connectors have run and signals are collected:
from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph

# Load graph (or initialize from seed)
try:
    kg = AeternusKnowledgeGraph.load()
except Exception:
    kg = None

# 1. Get dark nodes before scoring — elevate them in deal flow
if kg is not None:
    dark_nodes = kg.get_dark_nodes(min_centrality=0.25)
    dark_tickers = [n["id"] for n in dark_nodes[:10]]
    # These tickers get signal_strength metadata for downstream framework use
    # (this is informational for now; scorer integration is a follow-up task)

# 2. After deal flow run completes, update graph with discoveries
if kg is not None:
    # From sector scout metadata (sector_scout_metadata from collect_sector_scout_signals)
    for ticker, meta in sector_scout_metadata.items():
        kg.record_scout_hit(
            ticker=ticker,
            sector=meta.get("sector", "unknown"),
            themes_matched=meta.get("themes_matched", []),
            source_accounts=meta.get("source_accounts", []),
            signal_strength=meta.get("conviction", 0.5),
        )

    # From SEC catalyst 8-K supply chain discoveries
    for signal in sec_catalyst_signals:
        if signal["signal_family"] == "sec_8k_catalyst":
            from tradingagents.dealflow.sources.sec_catalyst import SUPPLY_CHAIN_MAP
            targets = SUPPLY_CHAIN_MAP.get(signal["symbol"], [])
            if targets:
                kg.update_from_sec_8k(signal["symbol"], targets)

    # Nightly decay (run only once per day, check last decay date)
    kg.decay_all(days_elapsed=1)
    kg.get_centrality_scores()  # recompute after updates
    kg.save()
```

**Important:** The pipeline integration block should be wrapped in `try/except Exception` so that a graph error never aborts a deal flow run.

### 6. trading_graph.py Integration

In `tradingagents/graph/trading_graph.py`, after `propagate()` returns a rating, call:

```python
# Update knowledge graph with pipeline score
try:
    from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
    kg = AeternusKnowledgeGraph.load()
    kg.record_pipeline_score(ticker, aeternus_rating["score"])
    kg.save()
except Exception:
    pass  # graph update is best-effort, never abort pipeline
```

**Implementor note:** Do NOT wire `trading_graph.py` changes in this task. The trading_graph.py integration is a follow-up. Focus on the core KG class and its tests. The pipeline.py wiring is conditional on S-033/S-034; stub it with `pass` if those are not yet merged.

## Files to Touch
- `tradingagents/graph/knowledge_graph.py` (new)
- `tests/test_knowledge_graph.py` (new)
- `tradingagents/dealflow/pipeline.py` (add kg integration block — wrap in try/except, conditional on S-033/S-034 being merged)

Do NOT touch `trading_graph.py` in this task.

## Tests: tests/test_knowledge_graph.py

All tests must run without network access, without writing to `eval_results/`, and without importing S-033/S-034 (use tmp_path for file I/O).

```python
# Test 1: add_node is idempotent
def test_add_node_idempotent():
    g = AeternusKnowledgeGraph()
    g.add_node("AXTI", node_type="company", sector="semis_ai_infrastructure", display_name="AXT Inc")
    g.add_node("AXTI", node_type="company", sector="semis_ai_infrastructure", display_name="AXT Inc Updated")
    assert len(g._nodes) == 1
    # display_name updated
    assert g._nodes["AXTI"]["display_name"] == "AXT Inc Updated"
    # node_type not changed if called twice
    assert g._nodes["AXTI"]["node_type"] == "company"

# Test 2: add_edge creates edge on first call
def test_add_edge_creates():
    g = AeternusKnowledgeGraph()
    g.add_edge("NVDA", "AXTI", "supply_chain", confidence=0.9, evidence_source="sec_8k")
    assert len(g._edges) == 1
    edge = g._edges[0]
    assert edge["source"] == "NVDA"
    assert edge["target"] == "AXTI"
    assert edge["weight"] == 0.9
    assert edge["evidence_count"] == 1

# Test 3: add_edge strengthens existing edge (Hebbian)
def test_add_edge_hebbian_strengthening():
    g = AeternusKnowledgeGraph()
    g.add_edge("NVDA", "AXTI", "supply_chain", confidence=0.9, evidence_source="sec_8k")
    initial_weight = g._edges[0]["weight"]
    g.add_edge("NVDA", "AXTI", "supply_chain", confidence=0.9, evidence_source="xai_scout")
    # weight should increase but stay <= 1.0
    assert g._edges[0]["weight"] > initial_weight
    assert g._edges[0]["weight"] <= 1.0
    assert g._edges[0]["evidence_count"] == 2
    assert "xai_scout" in g._edges[0]["evidence_sources"]
    # Still only one edge — not duplicated
    assert len(g._edges) == 1

# Test 4: add_edge auto-creates missing nodes
def test_add_edge_auto_creates_nodes():
    g = AeternusKnowledgeGraph()
    g.add_edge("UNKNOWN_SRC", "UNKNOWN_TGT", "supply_chain", confidence=0.5, evidence_source="seed")
    assert "UNKNOWN_SRC" in g._nodes
    assert "UNKNOWN_TGT" in g._nodes

# Test 5: propagate_signal correct BFS with decay
def test_propagate_signal_bfs():
    g = AeternusKnowledgeGraph()
    g.add_node("A")
    g.add_node("B")
    g.add_node("C")
    # A → B (weight 1.0), B → C (weight 1.0)
    g.add_edge("A", "B", "supply_chain", confidence=1.0, evidence_source="seed")
    g.add_edge("B", "C", "supply_chain", confidence=1.0, evidence_source="seed")
    result = g.propagate_signal("A", signal_strength=1.0, decay=0.5, max_hops=3)
    # B: 1.0 * 0.5 * 1.0 = 0.5
    # C: 0.5 * 0.5 * 1.0 = 0.25
    assert abs(result.get("B", 0) - 0.5) < 0.001
    assert abs(result.get("C", 0) - 0.25) < 0.001
    # Source not in result
    assert "A" not in result

# Test 6: propagate_signal respects max_hops
def test_propagate_signal_max_hops():
    g = AeternusKnowledgeGraph()
    for i in range(5):
        g.add_edge(str(i), str(i + 1), "supply_chain", confidence=1.0, evidence_source="seed")
    result = g.propagate_signal("0", signal_strength=1.0, decay=0.8, max_hops=2)
    assert "1" in result
    assert "2" in result
    assert "3" not in result  # hop 3 cut off

# Test 7: propagate_signal stops when strength below 0.01
def test_propagate_signal_strength_cutoff():
    g = AeternusKnowledgeGraph()
    g.add_edge("A", "B", "supply_chain", confidence=0.01, evidence_source="seed")
    g.add_edge("B", "C", "supply_chain", confidence=0.01, evidence_source="seed")
    result = g.propagate_signal("A", signal_strength=0.1, decay=0.5, max_hops=10)
    # A→B: 0.1 * 0.5 * 0.01 = 0.0005 < 0.01 → B not in result or C not in result
    # At least C should not be reached
    assert "C" not in result

# Test 8: get_centrality_scores returns normalized values
def test_centrality_normalized():
    g = AeternusKnowledgeGraph()
    g.add_edge("NVDA", "AXTI", "supply_chain", confidence=0.9, evidence_source="seed")
    g.add_edge("NVDA", "LITE", "supply_chain", confidence=0.8, evidence_source="seed")
    scores = g.get_centrality_scores()
    assert max(scores.values()) == pytest.approx(1.0, abs=0.01)
    assert all(0.0 <= v <= 1.0 for v in scores.values())

# Test 9: get_dark_nodes returns nodes with no aeternus_score
def test_dark_nodes_detection():
    g = AeternusKnowledgeGraph()
    # Add NVDA (high centrality) with no score
    g.add_edge("NVDA", "AXTI", "supply_chain", confidence=0.9, evidence_source="seed")
    g.add_edge("NVDA", "LITE", "supply_chain", confidence=0.8, evidence_source="seed")
    g.get_centrality_scores()
    dark = g.get_dark_nodes(min_centrality=0.0)
    tickers = [n["id"] for n in dark]
    assert "NVDA" in tickers
    # Score NVDA — now it should not appear
    g.record_pipeline_score("NVDA", 88.5)
    dark2 = g.get_dark_nodes(min_centrality=0.0)
    tickers2 = [n["id"] for n in dark2]
    assert "NVDA" not in tickers2

# Test 10: decay_all reduces edge weights
def test_decay_all():
    g = AeternusKnowledgeGraph()
    g.add_edge("NVDA", "AXTI", "supply_chain", confidence=1.0, evidence_source="seed")
    initial_weight = g._edges[0]["weight"]
    g.decay_all(days_elapsed=30)
    # After 30 days: weight * 0.9^(30/30) = weight * 0.9
    assert g._edges[0]["weight"] < initial_weight
    assert abs(g._edges[0]["weight"] - initial_weight * 0.9) < 0.01

# Test 11: decay never goes below 0.01
def test_decay_floor():
    g = AeternusKnowledgeGraph()
    g.add_edge("A", "B", "supply_chain", confidence=0.01, evidence_source="seed")
    g.decay_all(days_elapsed=365 * 10)  # 10 years
    assert g._edges[0]["weight"] >= 0.01

# Test 12: JSON save/load roundtrip is lossless
def test_json_roundtrip(tmp_path):
    g = AeternusKnowledgeGraph()
    g.add_node("AXTI", node_type="company", sector="semis_ai_infrastructure", display_name="AXT Inc")
    g.add_edge("NVDA", "AXTI", "supply_chain", confidence=0.85, evidence_source="sec_8k")
    g.record_pipeline_score("AXTI", 71.5)

    save_path = tmp_path / "kg.json"
    g.save(save_path)
    assert save_path.exists()

    g2 = AeternusKnowledgeGraph.load(save_path)
    assert "AXTI" in g2._nodes
    assert g2._nodes["AXTI"]["aeternus_score"] == pytest.approx(71.5)
    assert len(g2._edges) == 1
    assert g2._edges[0]["weight"] == pytest.approx(0.85)

# Test 13: load initializes from seed when file missing
def test_load_seeds_when_missing(tmp_path, monkeypatch):
    # Monkeypatch SUPPLY_CHAIN_MAP to a small dict for speed
    from tradingagents.graph import knowledge_graph as kg_mod
    monkeypatch.setattr(kg_mod, "SUPPLY_CHAIN_MAP", {"NVDA": ["AXTI"]})

    nonexistent = tmp_path / "nonexistent.json"
    g = AeternusKnowledgeGraph.load(nonexistent)
    # Seed should have created NVDA and AXTI nodes + supply_chain edge
    assert "NVDA" in g._nodes
    assert "AXTI" in g._nodes
    assert any(e["source"] == "NVDA" and e["target"] == "AXTI" for e in g._edges)

# Test 14: Obsidian export creates correct directory structure
def test_obsidian_export(tmp_path):
    g = AeternusKnowledgeGraph()
    g.add_node("AXTI", node_type="company", sector="semis_ai_infrastructure", display_name="AXT Inc")
    g.add_node("InP_substrates", node_type="theme", display_name="InP Substrates")
    g.add_node("semis_ai_infrastructure", node_type="sector", display_name="Semis / AI Infrastructure")
    g.add_edge("AXTI", "InP_substrates", "catalyst_beneficiary", confidence=0.7, evidence_source="xai_scout")
    g.record_pipeline_score("AXTI", 71.5)

    vault = tmp_path / "vault"
    count = g.to_obsidian(vault)

    assert (vault / "companies" / "AXTI.md").exists()
    assert (vault / "themes" / "InP_substrates.md").exists()
    assert (vault / "sectors" / "semis_ai_infrastructure.md").exists()
    assert (vault / "_graph_summary.md").exists()
    assert count >= 4

    # Check company file contains correct frontmatter
    content = (vault / "companies" / "AXTI.md").read_text()
    assert "ticker: AXTI" in content
    assert "aeternus_score: 71.5" in content
    assert "[[InP_substrates]]" in content

# Test 15: record_thesis_outcome strengthens/weakens edges
def test_thesis_outcome_adjusts_edges():
    g = AeternusKnowledgeGraph()
    g.add_edge("AXTI", "InP_substrates", "catalyst_beneficiary", confidence=0.5, evidence_source="xai_scout")
    initial = g._edges[0]["weight"]

    g.record_thesis_outcome("AXTI", confirmed=True)
    assert g._edges[0]["weight"] > initial

    g.record_thesis_outcome("AXTI", confirmed=False)
    # After invalidation, weight should decrease from the strengthened value
    # (Not necessarily below original — one confirm + one invalidate is net ~0)
    assert g._nodes["AXTI"]["thesis_track_record"]["confirmed"] == 1
    assert g._nodes["AXTI"]["thesis_track_record"]["invalidated"] == 1

# Test 16: record_scout_hit creates node and theme edges
def test_record_scout_hit():
    g = AeternusKnowledgeGraph()
    g.record_scout_hit(
        ticker="AXTI",
        sector="semis_ai_infrastructure",
        themes_matched=["InP substrate", "photonics"],
        source_accounts=["SemiAnalysis"],
        signal_strength=0.9,
    )
    assert "AXTI" in g._nodes
    assert g._nodes["AXTI"]["times_surfaced"] == 1
    assert g._nodes["AXTI"]["signal_strength"] > 0
    # Theme and account nodes created
    assert any(n["node_type"] == "theme" for n in g._nodes.values())
    assert any(n["node_type"] == "account" for n in g._nodes.values())

# Test 17: atomic save writes .tmp before replacing
def test_atomic_save(tmp_path, monkeypatch):
    import os
    replaced = []
    original_replace = os.replace
    monkeypatch.setattr(os, "replace", lambda src, dst: replaced.append((src, dst)) or original_replace(src, dst))

    g = AeternusKnowledgeGraph()
    g.add_node("AXTI")
    save_path = tmp_path / "kg.json"
    g.save(save_path)

    assert len(replaced) == 1
    src, dst = replaced[0]
    assert str(dst) == str(save_path)
    assert str(src).endswith(".tmp")
```

## Acceptance Criteria
- [ ] `AeternusKnowledgeGraph.load()` initializes from seed when file missing, loads from JSON when present
- [ ] `add_node()` is idempotent — calling twice never creates two nodes or overwrites score/track_record
- [ ] `add_edge()` strengthens existing edges (Hebbian) and never creates duplicate edges for same (src, tgt, rel) triple
- [ ] `propagate_signal()` correctly applies BFS with per-hop decay, respects max_hops and 0.01 floor cutoff
- [ ] `get_dark_nodes()` returns only company nodes with `aeternus_score=None` above centrality threshold
- [ ] `decay_all()` reduces edge weights exponentially, never below 0.01
- [ ] `to_json()` / `from_json()` roundtrip is lossless for all field types
- [ ] `save()` uses atomic write (tmp file + os.replace)
- [ ] `to_obsidian()` creates `companies/`, `themes/`, `sectors/`, `_graph_summary.md` with correct Obsidian wiki links
- [ ] Seed data includes all supply chain edges from `SUPPLY_CHAIN_MAP` in sec_catalyst.py
- [ ] 17 tests in `tests/test_knowledge_graph.py`, all passing
- [ ] All existing tests pass: `python -m pytest tests/ -v`
- [ ] Zero external dependencies (stdlib only)
- [ ] Performance: `propagate_signal()` on a 1000-node, 5000-edge graph completes in < 0.1s

---

## Handoff
*Fill in when marking done. Opus reads this to parse completion without reading the implementation.*

**Work Done:** [files changed + one-line summary of what shipped]

**Learnings:** [anything surprising, a footgun hit, or a pattern worth capturing — or "none"]

**Follow-ups:** [new tasks this work reveals, if any — or "none"]
