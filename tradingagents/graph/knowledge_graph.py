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

import datetime as dt
import json
import os
from collections import defaultdict, deque
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from tradingagents.graph.kg_seed_data import (
    EMERGENCE_SIGNALS,
    SEED_COMPANIES,
    SEED_SECTORS,
    SEED_THEMES,
    SUPPLY_CHAIN_MAP,
    _DEFAULT_KG_PATH,
    _YFINANCE_SECTOR_MAP,
)



# ---------------------------------------------------------------------------
# Seed constants
# ---------------------------------------------------------------------------



# Default JSON path (relative to CWD at runtime)

# ---------------------------------------------------------------------------
# S-049: yfinance sector name → AKG internal sector ID translation map.
# Used by _bootstrap_universe() to set sector on CSV-loaded nodes.
# None means "no matching AKG sector" — node stays sector-less (DARK).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Emergence signal table — defines all signal sources, normalization ranges,
# and relative weights for compute_emergence_score().
# (field_name, lo, hi, weight, uses_abs)
# ---------------------------------------------------------------------------


def _node_template(node_id: str, node_type: str = "company", sector: Optional[str] = None,
                   display_name: Optional[str] = None, metadata: Optional[dict] = None) -> dict:
    return {
        "id": node_id,
        "node_type": node_type,
        "sector": sector,
        "display_name": display_name or node_id,
        "signal_strength": 0.0,
        "centrality": 0.0,
        "times_surfaced": 0,
        "last_surfaced": None,
        "aeternus_score": None,
        "thesis_track_record": {"confirmed": 0, "invalidated": 0},
        "metadata": metadata or {},
        # Social-attention fields (S-037)
        "cashtag_velocity_z": None,
        "cashtag_mentions_7d": None,
        "cashtag_velocity_trend": None,
        "cashtag_sentiment": None,
        "cashtag_last_updated": None,
        "sec_event_type": None,
        "sec_event_date": None,
        "emergence_score": None,
        "emergence_tier": None,
        "emergence_n_sources": 0,
        # Activation fields (S-040) — used by theme and sector nodes
        "active": False,
        "activation_date": None,
        "deactivation_date": None,
        "macro_trigger": None,
        "conviction": 0.0,
        "expected_duration_months": None,
        "active_themes": [],
        "priority_score": 0.0,
        "activated_date": None,
        "deactivated_date": None,
        # Analysis memory (S-044) — written by record_rating()
        "last_aeternus_score": None,    # float (0-100) from most recent full analysis
        "last_aeternus_rating": None,   # str ("Strong Buy", "Buy", "Hold", "Sell", "Strong Sell")
        "last_scored_date": None,       # ISO date string of last analysis
        "last_conviction": None,        # int 1-5 confidence from scorer
        "last_catalyst": None,          # str — key catalyst truncated to 200 chars
        "score_history": [],            # list of {date, score, rating} — rolling last 10
        # Execution memory (S-045) — written by set_current_position() and close_position()
        "current_position": None,       # dict {shares, entry_price, entry_date} or None
        "last_closed_position": None,   # dict {exit_date, exit_price, realized_return_pct, hold_days} or None
        # Fundamentals cache (S-046) — written by fundamental_engine.py
        "fundamentals_snapshot": None,  # dict — cached fundamental metrics
        "fundamentals_fetched_at": None, # ISO date string — when snapshot was taken
        "earnings_date_next": None,     # ISO date string — next earnings date (TTL: until date passes)
        # Outcome weight feedback (S-047) — Hebbian learning
        "outcome_weight": 1.0,          # float 0.5–2.0, multiplies emergence score
        "outcome_stats": None,          # dict {n_trades, n_wins, win_rate, avg_return, avg_hold_days}
        # Cluster detection fields (S-050) — computed by detect_clusters()
        "cluster_strength": 0.0,          # float 0.0–1.0: (rising_pct × avg_emergence)
        "cluster_avg_emergence": 0.0,     # float: mean emergence score of company nodes in sector
        "cluster_rising_count": 0,        # int: nodes with emergence_score >= 0.2 (ATMOSPHERE+)
        "cluster_total_nodes": 0,         # int: total company nodes in sector
        "cluster_last_computed": None,    # ISO date string
        "cluster_candidate": False,       # bool: True if cluster_strength >= threshold AND sector inactive
        # Theme naming fields (S-050b) — written by name_cluster_theme()
        "cluster_theme_name": None,                  # str: human-readable theme name ("AI Inference Edge")
        "cluster_theme_hypothesis": None,            # str: 1-sentence thesis
        "cluster_theme_named_at": None,              # ISO date string
        "cluster_theme_strength_at_naming": 0.0,    # float: cluster_strength when named (for re-naming gate)
        "cluster_theme_is_coincidence": None,        # bool: True if cluster is likely coincidental
        "cluster_theme_confidence": None,            # float 0-1: thesis confidence
        "cluster_theme_missing_players": None,       # list of {ticker, reasoning} — potential additions
        # Perplexity enrichment cache (S-051) — written by scheduler
        "perplexity_enrichment": None,      # str: enrichment text from sonar
        "perplexity_enriched_at": None,     # ISO date string
        # Market ignorance enrichment (S-056) — written by market_ignorance.compute_market_ignorance()
        "market_ignorance_score_real": None,  # float: real ignorance score (0=known, 1=invisible)
        "analyst_count": None,                # int: number of sell-side analysts covering
        "institutional_pct": None,            # float: fraction held by institutions (0.0–1.0)
        "market_ignorance_cached_at": None,   # ISO date string: when last computed
        # Breakout discovery fields
        "breakout_score": None,          # float 0-100: breakout score from scanner
        "breakout_near_high": None,      # float 0-1: proximity to 52-week high
        "breakout_vol_ratio": None,      # float: volume ratio vs 60-day baseline
        "breakout_last_updated": None,   # ISO date string
        # IV divergence fields (populated by iv_scanner)
        "iv_implied_move_pct": None,     # float: ATM straddle implied move %
        "iv_historical_move_pct": None,  # float: avg historical earnings surprise %
        "iv_divergence": None,           # float: (historical - implied) / implied
        "iv_signal": None,               # "UNDERPRICED" | "OVERPRICED" | "NEUTRAL" | None
        "iv_earnings_date": None,        # ISO date of upcoming earnings
        "iv_scanned_at": None,           # ISO date of last scan
        # Universe metadata (populated by seeder)
        "asset_class": None,             # "Equity" | "ETF" | "CommodityProxy" | None
        "sector_gics": None,             # GICS sector label ("Technology", "Healthcare", etc.)
        "aliases": [],                   # List[str] — cashtag aliases (["gold", "xau"])
        "liquidity_score": None,         # float 0-100: percentile of 60-day avg dollar volume
        "liquidity_cached_at": None,     # ISO date string
        # S-078: Signal memory slots — one group per signal type
        # SEC catalyst
        "signal_sec_catalyst_score": None,       # float 0-100
        "signal_sec_catalyst_direction": None,   # "bullish" | "bearish"
        "signal_sec_catalyst_updated": None,     # ISO date string
        # Insider buying
        "signal_insider_score": None,            # float 0-100
        "signal_insider_buyer_count": None,      # int
        "signal_insider_updated": None,          # ISO date string
        # Smart money
        "signal_smart_money_score": None,        # float 0-100
        "signal_smart_money_direction": None,    # "bullish" | "bearish"
        "signal_smart_money_updated": None,      # ISO date string
        # Price momentum
        "signal_momentum_score": None,           # float 0-100
        "signal_momentum_rs_spy": None,          # float: relative strength vs SPY
        "signal_momentum_updated": None,         # ISO date string
        # Sector rotation
        "signal_sector_rotation_score": None,    # float 0-100
        "signal_sector_rotation_updated": None,  # ISO date string
        # Social / news
        "signal_social_score": None,             # float 0-100
        "signal_news_catalyst_score": None,      # float 0-100
        "signal_social_news_updated": None,      # ISO date string
        # Value overlay
        "signal_value_score": None,              # float 0-100
        "signal_value_updated": None,            # ISO date string
        # Macro regime
        "signal_macro_score": None,              # float 0-100
        "signal_macro_regime_tag": None,         # "risk_on" | "risk_off" | "neutral"
        "signal_macro_updated": None,            # ISO date string
    }


def _edge_template(source: str, target: str, relationship: str,
                   confidence: float, evidence_source: str) -> dict:
    return {
        "source": source,
        "target": target,
        "relationship": relationship,
        "weight": round(min(1.0, max(0.0, confidence)), 6),
        "evidence_count": 1,
        "last_confirmed": dt.date.today().isoformat(),
        "evidence_sources": [evidence_source],
    }


class AeternusKnowledgeGraph:
    """
    Living directed weighted graph for Aeternus institutional memory.

    Zero external dependencies (stdlib only).
    All operations < 1 second for 10k nodes / 50k edges.
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, dict] = {}
        self._edges: List[dict] = []
        self._adj_out: Dict[str, List[int]] = defaultdict(list)
        self._adj_in: Dict[str, List[int]] = defaultdict(list)
        self._edge_index: Dict[Tuple[str, str, str], int] = {}
        self._created_at: str = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        self._updated_at: str = self._created_at
        self._version: int = 1
        self._causal_events: Dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Class methods: load / from_json
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path=None) -> "AeternusKnowledgeGraph":
        """Load from JSON at path. Initialize from seed if file missing."""
        if path is None:
            path = _DEFAULT_KG_PATH
        path = Path(path)

        if not path.exists():
            g = cls()
            g._seed()
            return g

        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as e:
            raise ValueError(f"AKG: cannot read {path}: {e}") from e

        try:
            g = cls.from_json(raw)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise ValueError(f"AKG: malformed JSON at {path}: {e}") from e

        company_nodes = [
            node for node in g._nodes.values()
            if node.get("node_type") == "company"
        ]
        if not company_nodes or not g._edges:
            g._seed()
            g.get_centrality_scores()
            refreshed_company_nodes = [
                node for node in g._nodes.values()
                if node.get("node_type") == "company"
            ]
            if refreshed_company_nodes:
                g.save(path)
        return g

    @classmethod
    def from_json(cls, json_str: str) -> "AeternusKnowledgeGraph":
        """Deserialize from a JSON string. Rebuilds adjacency indexes."""
        data = json.loads(json_str)
        g = cls()
        g._version = data.get("version", 1)
        g._created_at = data.get("created_at", g._created_at)
        g._updated_at = data.get("updated_at", g._updated_at)
        g._nodes = data.get("nodes", {})

        for i, edge in enumerate(data.get("edges", [])):
            g._edges.append(edge)
            src = edge["source"]
            tgt = edge["target"]
            rel = edge["relationship"]
            g._adj_out[src].append(i)
            g._adj_in[tgt].append(i)
            g._edge_index[(src, tgt, rel)] = i

        g._causal_events = data.get("causal_events", {})
        g._backfill_node_defaults()
        return g

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def to_json(self, path=None) -> str:
        """Serialize to JSON string; optionally write to path atomically."""
        self._updated_at = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        payload = {
            "version": self._version,
            "created_at": self._created_at,
            "updated_at": self._updated_at,
            "nodes": self._nodes,
            "edges": self._edges,
            "causal_events": self._causal_events,
        }
        json_str = json.dumps(payload, indent=2, ensure_ascii=False)
        if path is not None:
            self._atomic_write(Path(path), json_str)
        return json_str

    def save(self, path=None) -> None:
        """Atomic write to path (default: eval_results/control/knowledge_graph.json)."""
        if path is None:
            path = _DEFAULT_KG_PATH
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        json_str = self.to_json()  # updates _updated_at
        self._atomic_write(path, json_str)

    def _atomic_write(self, path: Path, content: str) -> None:
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(str(tmp_path), str(path))

    # ------------------------------------------------------------------
    # Node operations
    # ------------------------------------------------------------------

    def get_node(self, node_id: str) -> Optional[dict]:
        """Return node dict by exact ID, or None when absent.

        Transitional public API for callers that previously read _nodes directly.
        Returns the live node dict so existing mutation semantics are preserved.
        """
        return self._nodes.get(node_id)

    def iter_nodes(self):
        """Iterate over a snapshot container of live node dicts."""
        return iter(tuple(self._nodes.values()))

    def iter_edges(self):
        """Iterate over a snapshot container of live edge dicts."""
        return iter(tuple(self._edges))

    def add_node(self, node_id: str, node_type: str = "company", sector: Optional[str] = None,
                 display_name: Optional[str] = None, metadata: Optional[dict] = None) -> None:
        """
        Idempotent node add. If node exists, update display_name/sector/metadata only.
        Never overwrites: signal_strength, centrality, times_surfaced,
        aeternus_score, thesis_track_record.
        """
        if node_id in self._nodes:
            existing = self._nodes[node_id]
            if display_name is not None:
                existing["display_name"] = display_name
            if sector is not None:
                existing["sector"] = sector
            if metadata:
                existing["metadata"].update(metadata)
            return

        self._nodes[node_id] = _node_template(
            node_id=node_id,
            node_type=node_type,
            sector=sector,
            display_name=display_name,
            metadata=metadata,
        )

    def remove_nodes(self, node_ids: List[str]) -> int:
        """Remove nodes and any attached edges. Returns number of nodes removed."""
        targets = {
            str(node_id or "").upper().strip()
            for node_id in node_ids
            if str(node_id or "").strip()
        }
        existing = targets & set(self._nodes.keys())
        if not existing:
            return 0

        for node_id in existing:
            self._nodes.pop(node_id, None)

        kept_edges = [
            edge for edge in self._edges
            if edge.get("source") not in existing and edge.get("target") not in existing
        ]
        self._edges = []
        self._adj_out = defaultdict(list)
        self._adj_in = defaultdict(list)
        self._edge_index = {}
        for edge in kept_edges:
            idx = len(self._edges)
            self._edges.append(edge)
            self._adj_out[edge["source"]].append(idx)
            self._adj_in[edge["target"]].append(idx)
            self._edge_index[(edge["source"], edge["target"], edge["relationship"])] = idx

        self._updated_at = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        return len(existing)

    # ------------------------------------------------------------------
    # Edge operations
    # ------------------------------------------------------------------

    def add_edge(self, source: str, target: str, relationship: str,
                 confidence: float, evidence_source: str) -> None:
        """
        Add edge. Auto-creates missing nodes.
        If edge (source, target, relationship) already exists: Hebbian strengthening.
        """
        # Auto-create missing nodes
        if source not in self._nodes:
            self.add_node(source, node_type="company")
        if target not in self._nodes:
            self.add_node(target, node_type="company")

        key = (source, target, relationship)
        if key in self._edge_index:
            # Hebbian strengthening
            idx = self._edge_index[key]
            edge = self._edges[idx]
            edge["weight"] = min(1.0, round(edge["weight"] + 0.05 * confidence, 6))
            edge["evidence_count"] += 1
            edge["last_confirmed"] = dt.date.today().isoformat()
            if evidence_source not in edge["evidence_sources"]:
                edge["evidence_sources"].append(evidence_source)
            return

        # New edge
        edge = _edge_template(source, target, relationship, confidence, evidence_source)
        idx = len(self._edges)
        self._edges.append(edge)
        self._adj_out[source].append(idx)
        self._adj_in[target].append(idx)
        self._edge_index[key] = idx

    def _outgoing_edges(self, node_id: str) -> List[dict]:
        return [self._edges[i] for i in self._adj_out.get(node_id, [])]

    def _incoming_edges(self, node_id: str) -> List[dict]:
        return [self._edges[i] for i in self._adj_in.get(node_id, [])]

    # ------------------------------------------------------------------
    # Graph algorithms
    # ------------------------------------------------------------------

    def propagate_signal(self, source_node_id: str, signal_strength: float,
                         decay: float = 0.5, max_hops: int = 3) -> Dict[str, float]:
        """
        BFS from source_node_id. At each hop: strength *= decay * edge_weight.
        Returns {node_id: propagated_strength} (source excluded).
        Stops at max_hops or strength < 0.01.
        """
        result: Dict[str, float] = {}
        queue: deque = deque([(source_node_id, signal_strength, 0)])
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

    def get_centrality_scores(self) -> Dict[str, float]:
        """
        Weighted degree centrality (in-degree + out-degree by edge weight).
        Normalized to 0-1. Updates centrality field on each node in-place.
        """
        degree: Dict[str, float] = {}
        for edge in self._edges:
            degree[edge["source"]] = degree.get(edge["source"], 0.0) + edge["weight"]
            degree[edge["target"]] = degree.get(edge["target"], 0.0) + edge["weight"]

        if not degree:
            return {}

        max_degree = max(degree.values())
        if max_degree == 0:
            return {n: 0.0 for n in degree}

        scores = {n: round(d / max_degree, 6) for n, d in degree.items()}

        for node_id, score in scores.items():
            if node_id in self._nodes:
                self._nodes[node_id]["centrality"] = score

        return scores

    def get_dark_nodes(self, min_centrality: float = 0.3) -> List[dict]:
        """
        Return company nodes with centrality >= min_centrality and aeternus_score is None.
        Sorted by centrality descending.  These are the alpha candidates.
        """
        dark = [
            node for node in self._nodes.values()
            if node["node_type"] == "company"
            and node["centrality"] >= min_centrality
            and node["aeternus_score"] is None
        ]
        return sorted(dark, key=lambda n: n["centrality"], reverse=True)

    def get_open_positions(self) -> List[dict]:
        """Return company nodes that have an open position (current_position is not None)."""
        return [
            node for node in self._nodes.values()
            if node.get("node_type") == "company" and node.get("current_position") is not None
        ]

    def get_rescan_candidates(self, max_age_days: int = 7) -> List[dict]:
        """Return SCORED company nodes with recent scout signals.

        These are previously-analyzed tickers that have fresh activity — they
        should stay in the universe for re-analysis rather than falling out.
        """
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=max_age_days)).strftime("%Y-%m-%d")
        candidates = []
        for node in self._nodes.values():
            if node.get("node_type") != "company":
                continue
            is_scored_rescan = node.get("emergence_tier") == "SCORED"
            is_theme_acceleration_rescan = bool(node.get("theme_acceleration_rescan_flag"))
            if not (is_scored_rescan or is_theme_acceleration_rescan):
                continue
            has_recent = False
            for key, val in node.items():
                if key.startswith("signal_") and key.endswith("_updated") and val and str(val) >= cutoff:
                    has_recent = True
                    break
            if not has_recent:
                cashtag_updated = node.get("cashtag_last_updated")
                if cashtag_updated and str(cashtag_updated) >= cutoff:
                    has_recent = True
            if has_recent:
                candidates.append(node)
        return sorted(candidates, key=lambda n: float(n.get("emergence_score", 0) or 0), reverse=True)

    # ------------------------------------------------------------------
    # Emergence scoring engine (S-037)
    # ------------------------------------------------------------------

    def _backfill_node_defaults(self) -> None:
        """
        Fill any missing S-037 social-attention fields and S-040 activation fields
        with appropriate defaults on all loaded nodes.
        Called by from_json() for backward compatibility with older serialized graphs.
        """
        _none_fields = [
            # S-037 cashtag / emergence fields
            "cashtag_velocity_z",
            "cashtag_mentions_7d",
            "cashtag_velocity_trend",
            "cashtag_sentiment",
            "cashtag_last_updated",
            "sec_event_type",
            "sec_event_date",
            "emergence_score",
            "emergence_tier",
            # S-040 theme activation fields (None defaults)
            "activation_date",
            "deactivation_date",
            "macro_trigger",
            "expected_duration_months",
            # S-040 sector activation fields (None defaults)
            "activated_date",
            "deactivated_date",
            # S-044 analysis memory fields (None defaults)
            "last_aeternus_score",
            "last_aeternus_rating",
            "last_scored_date",
            "last_conviction",
            "last_catalyst",
            # S-045 execution memory fields (None defaults)
            "current_position",
            "last_closed_position",
            # S-046 fundamentals cache fields (None defaults)
            "fundamentals_snapshot",
            "fundamentals_fetched_at",
            "earnings_date_next",
            # S-047 outcome stats (None default)
            "outcome_stats",
            # S-050 cluster detection fields (None default)
            "cluster_last_computed",
            # S-050b theme naming fields (None defaults)
            "cluster_theme_name",
            "cluster_theme_hypothesis",
            "cluster_theme_named_at",
            "cluster_theme_is_coincidence",
            "cluster_theme_confidence",
            "cluster_theme_missing_players",
            # S-051 Perplexity enrichment cache fields (None defaults)
            "perplexity_enrichment",
            "perplexity_enriched_at",
            # S-056 market ignorance enrichment fields (None defaults)
            "market_ignorance_score_real",
            "analyst_count",
            "institutional_pct",
            "market_ignorance_cached_at",
            # Breakout discovery fields
            "breakout_score",
            "breakout_near_high",
            "breakout_vol_ratio",
            "breakout_last_updated",
            # IV divergence fields
            "iv_implied_move_pct",
            "iv_historical_move_pct",
            "iv_divergence",
            "iv_signal",
            "iv_earnings_date",
            "iv_scanned_at",
            # Universe metadata fields (None defaults)
            "asset_class",
            "sector_gics",
            "liquidity_score",
            "liquidity_cached_at",
            # S-078: Signal memory slots (None defaults)
            "signal_sec_catalyst_score",
            "signal_sec_catalyst_direction",
            "signal_sec_catalyst_updated",
            "signal_insider_score",
            "signal_insider_buyer_count",
            "signal_insider_updated",
            "signal_smart_money_score",
            "signal_smart_money_direction",
            "signal_smart_money_updated",
            "signal_momentum_score",
            "signal_momentum_rs_spy",
            "signal_momentum_updated",
            "signal_sector_rotation_score",
            "signal_sector_rotation_updated",
            "signal_social_score",
            "signal_news_catalyst_score",
            "signal_social_news_updated",
            "signal_value_score",
            "signal_value_updated",
            "signal_macro_score",
            "signal_macro_regime_tag",
            "signal_macro_updated",
            # AKG Theme Acceleration fields
            "primary_theme",
            "secondary_themes",
            "theme_role",
            "theme_confidence",
            "theme_driver_type",
            "theme_momentum",
            "theme_evidence",
            "signal_theme_acceleration_score",
            "signal_theme_acceleration_updated",
            "theme_acceleration_reason",
            "theme_acceleration_research_visibility",
        ]
        for node in self._nodes.values():
            for field in _none_fields:
                if field not in node:
                    node[field] = None
            # S-040 theme activation bool/float fields
            if "active" not in node:
                node["active"] = False
            if "conviction" not in node:
                node["conviction"] = 0.0
            # S-040 sector activation fields with non-None defaults
            if "active_themes" not in node:
                node["active_themes"] = []
            if "priority_score" not in node:
                node["priority_score"] = 0.0
            if "theme_acceleration_rescan_flag" not in node:
                node["theme_acceleration_rescan_flag"] = False
            # S-044 analysis memory list field
            if "score_history" not in node:
                node["score_history"] = []
            # S-047 outcome weight (non-None default: 1.0)
            if "outcome_weight" not in node:
                node["outcome_weight"] = 1.0
            # S-050 cluster detection fields (non-None defaults)
            if "cluster_strength" not in node:
                node["cluster_strength"] = 0.0
            if "cluster_avg_emergence" not in node:
                node["cluster_avg_emergence"] = 0.0
            if "cluster_rising_count" not in node:
                node["cluster_rising_count"] = 0
            if "cluster_total_nodes" not in node:
                node["cluster_total_nodes"] = 0
            if "cluster_candidate" not in node:
                node["cluster_candidate"] = False
            # S-050b theme naming field (non-None default)
            if "cluster_theme_strength_at_naming" not in node:
                node["cluster_theme_strength_at_naming"] = 0.0
            # S-079: emergence multi-source count (non-None default)
            if "emergence_n_sources" not in node:
                node["emergence_n_sources"] = 0
            # Universe metadata list field
            if "aliases" not in node:
                node["aliases"] = []

    # ------------------------------------------------------------------
    # Theme / sector activation methods (S-040)
    # ------------------------------------------------------------------

    def add_theme_node(self, theme_id: str, display_name: Optional[str] = None,
                       metadata: Optional[dict] = None) -> None:
        """Idempotent theme node add. Delegates to add_node with node_type='theme'."""
        self.add_node(theme_id, node_type="theme", display_name=display_name, metadata=metadata)

    def add_sector_node(self, sector_id: str, display_name: Optional[str] = None,
                        metadata: Optional[dict] = None) -> None:
        """Idempotent sector node add. Delegates to add_node with node_type='sector'."""
        self.add_node(sector_id, node_type="sector", display_name=display_name, metadata=metadata)

    def update_node_field(self, node_id: str, field: str, value) -> bool:
        """Set a single field on a node. Returns True if node existed, False otherwise."""
        if node_id not in self._nodes:
            return False
        self._nodes[node_id][field] = value
        return True

    def activate_theme(self, theme_id: str, macro_trigger: str,
                       conviction: float = 0.5,
                       expected_duration_months: float = None) -> bool:
        """
        Mark a theme node as active. Returns True if theme existed and was updated.
        Sets: active=True, activation_date=today ISO, macro_trigger, conviction,
        expected_duration_months. Does NOT cascade to sectors.
        """
        if theme_id not in self._nodes:
            return False
        node = self._nodes[theme_id]
        node["active"] = True
        node["activation_date"] = dt.date.today().isoformat()
        node["macro_trigger"] = macro_trigger
        node["conviction"] = conviction
        node["expected_duration_months"] = expected_duration_months
        return True

    def deactivate_theme(self, theme_id: str) -> bool:
        """
        Mark a theme node as inactive. Returns True if theme existed and was updated.
        Sets: active=False, deactivation_date=today ISO. Does NOT cascade to sectors.
        """
        if theme_id not in self._nodes:
            return False
        node = self._nodes[theme_id]
        node["active"] = False
        node["deactivation_date"] = dt.date.today().isoformat()
        return True

    def activate_sector(self, sector_id: str, theme_ids: list,
                        priority_score: float = 0.5) -> bool:
        """
        Mark a sector node as active. Merges theme_ids into active_themes (no duplicates).
        Sets: active=True, priority_score (max of current and new), activated_date=today ISO.
        Returns True if sector existed and was updated.
        """
        if sector_id not in self._nodes:
            return False
        node = self._nodes[sector_id]
        existing = node.get("active_themes") or []
        for tid in theme_ids:
            if tid not in existing:
                existing.append(tid)
        node["active_themes"] = existing
        node["active"] = True
        node["priority_score"] = max(node.get("priority_score") or 0.0, priority_score)
        node["activated_date"] = dt.date.today().isoformat()
        return True

    def deactivate_sector(self, sector_id: str, theme_id: str = None) -> bool:
        """
        Remove theme_id from sector's active_themes list.
        If theme_id is None: deactivate fully regardless of remaining themes.
        If active_themes is now empty after removal: set active=False, deactivated_date=today ISO.
        If active_themes still has entries: keep active=True (other themes still activating it).
        Returns True if sector existed and was updated.
        """
        if sector_id not in self._nodes:
            return False
        node = self._nodes[sector_id]
        if theme_id is None:
            node["active"] = False
            node["active_themes"] = []
            node["deactivated_date"] = dt.date.today().isoformat()
        else:
            existing = node.get("active_themes") or []
            if theme_id in existing:
                existing.remove(theme_id)
            node["active_themes"] = existing
            if not existing:
                node["active"] = False
                node["deactivated_date"] = dt.date.today().isoformat()
        return True

    def get_active_themes(self) -> list:
        """Return list of theme node dicts where active=True, sorted by conviction desc."""
        themes = [
            node for node in self._nodes.values()
            if node.get("node_type") == "theme" and node.get("active") is True
        ]
        return sorted(themes, key=lambda n: n.get("conviction") or 0.0, reverse=True)

    def get_active_sectors(self) -> list:
        """Return list of sector node dicts where active=True, sorted by priority_score desc."""
        sectors = [
            node for node in self._nodes.values()
            if node.get("node_type") == "sector" and node.get("active") is True
        ]
        return sorted(sectors, key=lambda n: n.get("priority_score") or 0.0, reverse=True)

    def get_active_sector_ids(self) -> set:
        """Return set of sector node IDs where active=True. Used for fast membership check."""
        return {
            node_id for node_id, node in self._nodes.items()
            if node.get("node_type") == "sector" and node.get("active") is True
        }

    def get_active_sector_companies(self, sector_id: str) -> list:
        """
        Return list of company node dicts belonging to the given sector.
        Matches on node["sector"] == sector_id for company nodes.
        Sorted by centrality desc.
        """
        companies = [
            node for node in self._nodes.values()
            if node.get("node_type") == "company" and node.get("sector") == sector_id
        ]
        return sorted(companies, key=lambda n: n.get("centrality") or 0.0, reverse=True)

    def get_nodes_by_type(self, node_type: str) -> list:
        """Return list of node dicts matching the given node_type. No guaranteed order."""
        return [node for node in self._nodes.values() if node.get("node_type") == node_type]

    def enrich_node_cashtag(
        self,
        ticker: str,
        velocity_z: float,
        mentions_7d: int,
        velocity_trend: str,
        sentiment: float,
        as_of_date: str,
    ) -> None:
        """
        Write cashtag attention fields onto a node and recompute emergence score.
        Auto-creates node (node_type="company") if it does not yet exist.
        """
        if ticker not in self._nodes:
            self.add_node(ticker, node_type="company")
        node = self._nodes[ticker]
        node["cashtag_velocity_z"] = velocity_z
        node["cashtag_mentions_7d"] = mentions_7d
        node["cashtag_velocity_trend"] = velocity_trend
        node["cashtag_sentiment"] = sentiment
        node["cashtag_last_updated"] = as_of_date
        self.compute_emergence_score(ticker)

    def enrich_node_breakout(
        self,
        ticker: str,
        score: float,
        near_high: float,
        vol_ratio: float,
        as_of_date: str,
    ) -> None:
        """Write breakout scanner fields onto a node and recompute emergence score.
        Auto-creates node (node_type="company") if it does not yet exist."""
        if ticker not in self._nodes:
            self.add_node(ticker, node_type="company")
        node = self._nodes[ticker]
        node["breakout_score"] = round(float(score), 4)
        node["breakout_near_high"] = round(float(near_high), 6)
        node["breakout_vol_ratio"] = round(float(vol_ratio), 4)
        node["breakout_last_updated"] = as_of_date
        self.compute_emergence_score(ticker)

    def enrich_node_iv(
        self,
        ticker: str,
        implied_move_pct: float,
        historical_move_pct: float,
        divergence: float,
        signal: str,
        earnings_date: str,
        as_of_date: str,
    ) -> None:
        """Write IV divergence fields onto a node and recompute emergence score.
        Auto-creates node (node_type="company") if it does not yet exist."""
        if ticker not in self._nodes:
            self.add_node(ticker, node_type="company")
        node = self._nodes[ticker]
        node["iv_implied_move_pct"] = round(float(implied_move_pct), 4)
        node["iv_historical_move_pct"] = round(float(historical_move_pct), 4)
        node["iv_divergence"] = round(float(divergence), 4)
        node["iv_signal"] = signal
        node["iv_earnings_date"] = earnings_date
        node["iv_scanned_at"] = as_of_date
        self.compute_emergence_score(ticker)

    # ------------------------------------------------------------------
    # S-078: Signal memory — TTL helper + 8 enrichment write methods
    # ------------------------------------------------------------------

    def _is_field_fresh(self, ticker: str, timestamp_field: str, ttl_hours: float) -> bool:
        """Check whether a signal timestamp field is still within its TTL.

        Returns True if the field exists, is a valid ISO date, and is less than
        ttl_hours old.  Returns False otherwise (missing node, missing field,
        expired, or unparseable date).
        """
        if ticker not in self._nodes:
            return False
        ts_str = self._nodes[ticker].get(timestamp_field)
        if not ts_str:
            return False
        try:
            ts_date = dt.date.fromisoformat(ts_str)
            age_days = (dt.date.today() - ts_date).days
            return age_days * 24 < ttl_hours
        except (ValueError, TypeError):
            return False

    def enrich_node_sec_catalyst(
        self, ticker: str, score: float, direction: str, as_of_date: str,
    ) -> None:
        """Write SEC catalyst signal fields and recompute emergence score."""
        if ticker not in self._nodes:
            self.add_node(ticker, node_type="company")
        node = self._nodes[ticker]
        node["signal_sec_catalyst_score"] = round(float(score), 4)
        node["signal_sec_catalyst_direction"] = direction
        node["signal_sec_catalyst_updated"] = as_of_date
        self.compute_emergence_score(ticker)

    def enrich_node_insider_cluster(
        self, ticker: str, score: float, buyer_count: int, as_of_date: str,
    ) -> None:
        """Write insider buying signal fields and recompute emergence score."""
        if ticker not in self._nodes:
            self.add_node(ticker, node_type="company")
        node = self._nodes[ticker]
        node["signal_insider_score"] = round(float(score), 4)
        node["signal_insider_buyer_count"] = int(buyer_count)
        node["signal_insider_updated"] = as_of_date
        self.compute_emergence_score(ticker)

    def enrich_node_insider_sell(
        self, ticker: str, score: float, seller_count: int, as_of_date: str,
    ) -> None:
        """Write insider selling signal fields and recompute emergence score."""
        if ticker not in self._nodes:
            self.add_node(ticker, node_type="company")
        node = self._nodes[ticker]
        node["signal_insider_sell_score"] = round(float(score), 4)
        node["signal_insider_sell_count"] = int(seller_count)
        node["signal_insider_sell_updated"] = as_of_date
        self.compute_emergence_score(ticker)

    def enrich_node_smart_money(
        self, ticker: str, score: float, direction: str, as_of_date: str,
    ) -> None:
        """Write smart money signal fields and recompute emergence score."""
        if ticker not in self._nodes:
            self.add_node(ticker, node_type="company")
        node = self._nodes[ticker]
        node["signal_smart_money_score"] = round(float(score), 4)
        node["signal_smart_money_direction"] = direction
        node["signal_smart_money_updated"] = as_of_date
        self.compute_emergence_score(ticker)

    def enrich_node_price_momentum(
        self, ticker: str, score: float, rs_spy: float, as_of_date: str,
    ) -> None:
        """Write price momentum signal fields and recompute emergence score."""
        if ticker not in self._nodes:
            self.add_node(ticker, node_type="company")
        node = self._nodes[ticker]
        node["signal_momentum_score"] = round(float(score), 4)
        node["signal_momentum_rs_spy"] = round(float(rs_spy), 4)
        node["signal_momentum_updated"] = as_of_date
        self.compute_emergence_score(ticker)

    def enrich_node_sector_rotation(
        self, ticker: str, score: float, as_of_date: str,
    ) -> None:
        """Write sector rotation signal fields and recompute emergence score."""
        if ticker not in self._nodes:
            self.add_node(ticker, node_type="company")
        node = self._nodes[ticker]
        node["signal_sector_rotation_score"] = round(float(score), 4)
        node["signal_sector_rotation_updated"] = as_of_date
        self.compute_emergence_score(ticker)

    def enrich_node_social_news(
        self, ticker: str, social_score: float, news_catalyst_score: float,
        as_of_date: str,
    ) -> None:
        """Write social + news catalyst signal fields and recompute emergence score."""
        if ticker not in self._nodes:
            self.add_node(ticker, node_type="company")
        node = self._nodes[ticker]
        node["signal_social_score"] = round(float(social_score), 4)
        node["signal_news_catalyst_score"] = round(float(news_catalyst_score), 4)
        node["signal_social_news_updated"] = as_of_date
        self.compute_emergence_score(ticker)

    def enrich_node_value(
        self, ticker: str, score: float, as_of_date: str,
    ) -> None:
        """Write value overlay signal fields and recompute emergence score."""
        if ticker not in self._nodes:
            self.add_node(ticker, node_type="company")
        node = self._nodes[ticker]
        node["signal_value_score"] = round(float(score), 4)
        node["signal_value_updated"] = as_of_date
        self.compute_emergence_score(ticker)

    def enrich_node_macro_regime(
        self, ticker: str, score: float, regime_tag: str, as_of_date: str,
    ) -> None:
        """Write macro regime signal fields and recompute emergence score."""
        if ticker not in self._nodes:
            self.add_node(ticker, node_type="company")
        node = self._nodes[ticker]
        node["signal_macro_score"] = round(float(score), 4)
        node["signal_macro_regime_tag"] = regime_tag
        node["signal_macro_updated"] = as_of_date
        self.compute_emergence_score(ticker)

    def update_theme_acceleration_signal(self, ticker: str, payload: dict) -> None:
        """Write filing-confirmed theme acceleration fields to an AKG node."""
        symbol = str(ticker or "").upper().strip()
        if not symbol:
            return
        if symbol not in self._nodes:
            self.add_node(symbol, node_type="company")
        node = self._nodes[symbol]
        node.setdefault("theme_acceleration_rescan_flag", False)
        score = _clamp_float(payload.get("theme_acceleration_score"), 0.0, 15.0)
        as_of_date = str(payload.get("as_of_date") or payload.get("signal_theme_acceleration_updated") or "")
        evidence = payload.get("theme_evidence") or []
        if isinstance(evidence, str):
            evidence = [evidence] if evidence.strip() else []
        evidence = [str(item).strip() for item in evidence if str(item).strip()]
        if not evidence:
            score = 0.0
        node["primary_theme"] = str(payload.get("primary_theme") or "").strip() or None
        secondary = payload.get("secondary_themes") or []
        if isinstance(secondary, str):
            secondary = [secondary] if secondary.strip() else []
        node["secondary_themes"] = [str(item).strip() for item in secondary if str(item).strip()]
        node["theme_role"] = str(payload.get("theme_role") or "").strip() or None
        node["theme_confidence"] = str(payload.get("theme_confidence") or "").strip() or None
        node["theme_driver_type"] = str(payload.get("theme_driver_type") or "").strip() or None
        node["theme_momentum"] = str(payload.get("theme_momentum") or "").strip() or None
        node["theme_evidence"] = evidence
        node["signal_theme_acceleration_score"] = round(score, 4)
        node["signal_theme_acceleration_updated"] = as_of_date or None
        reason = str(payload.get("theme_acceleration_reason") or payload.get("theme_driver_summary") or "").strip()
        node["theme_acceleration_reason"] = reason or None
        confidence = str(node.get("theme_confidence") or "").lower()
        node["theme_acceleration_research_visibility"] = bool(score >= 10.0 and confidence in {"medium", "high"})
        if score >= 5.0:
            node["theme_acceleration_rescan_flag"] = True
        self.compute_emergence_score(symbol)

    def mark_theme_acceleration_rescan(self, ticker: str, reason: str = "") -> None:
        symbol = str(ticker or "").upper().strip()
        if not symbol:
            return
        if symbol not in self._nodes:
            self.add_node(symbol, node_type="company")
        self._nodes[symbol]["theme_acceleration_rescan_flag"] = True
        if reason:
            self._nodes[symbol]["theme_acceleration_reason"] = str(reason)

    def get_theme_acceleration_candidates(self, as_of_date: str | None = None) -> List[dict]:
        """Return company nodes flagged for theme-acceleration rescan."""
        candidates = []
        for node in self._nodes.values():
            if node.get("node_type") != "company":
                continue
            if not node.get("theme_acceleration_rescan_flag"):
                continue
            updated = str(node.get("signal_theme_acceleration_updated") or "")
            if as_of_date and updated and updated > str(as_of_date):
                continue
            candidates.append(node)
        return sorted(candidates, key=lambda n: float(n.get("signal_theme_acceleration_score") or 0), reverse=True)

    def compute_emergence_score(self, ticker: str) -> float:
        """
        Compute emergence score (0.0-1.0) for the given node and store result.

        Formula: 0.15 * centrality + 0.85 * weighted_signal_average
        where weighted_signal_average is computed over all populated signals
        in EMERGENCE_SIGNALS, using only signals with non-None values.

        Returns 0.0 gracefully if node is missing.
        Also stores emergence_tier and emergence_n_sources on the node.
        """
        if ticker not in self._nodes:
            return 0.0

        node = self._nodes[ticker]

        def _normalize(x, lo, hi):
            if x is None:
                return 0.0
            return max(0.0, min(1.0, (x - lo) / (hi - lo)))

        centrality = node.get("centrality") or 0.0
        aeternus_score = node.get("aeternus_score")

        # Weighted average over all populated signals
        weight_sum = 0
        value_sum = 0.0
        n_sources = 0
        for field, lo, hi, weight, uses_abs in EMERGENCE_SIGNALS:
            raw = node.get(field)
            if raw is None:
                continue
            n_sources += 1
            val = abs(raw) if uses_abs else raw
            value_sum += weight * _normalize(val, lo, hi)
            weight_sum += weight

        if weight_sum > 0:
            signal_avg = value_sum / weight_sum
        else:
            signal_avg = 0.0

        score = 0.15 * centrality + 0.85 * signal_avg

        # Apply outcome weight (Hebbian feedback)
        outcome_weight = node.get("outcome_weight") or 1.0
        score = round(max(0.0, min(1.0, score * outcome_weight)), 6)
        node["emergence_score"] = score
        node["emergence_n_sources"] = n_sources

        # Tier classification — legacy gates preserved, multi-source gates added
        velocity_z = node.get("cashtag_velocity_z")
        sentiment = node.get("cashtag_sentiment")
        breakout_score_val = node.get("breakout_score")
        iv_divergence_val = node.get("iv_divergence")

        if aeternus_score is not None:
            tier = "SCORED"
        elif (
            (velocity_z is not None and sentiment is not None
             and velocity_z >= 2.0 and sentiment >= 0.5)
            or (breakout_score_val is not None
                and node.get("breakout_vol_ratio") is not None
                and breakout_score_val >= 85.0
                and node.get("breakout_vol_ratio") >= 2.0)
            or (iv_divergence_val is not None
                and abs(iv_divergence_val) >= 0.3)
            or (n_sources >= 4 and signal_avg >= 0.5)
        ):
            tier = "HABITABLE"
        elif (
            (velocity_z is not None and velocity_z >= 1.0)
            or (sentiment is not None and sentiment >= 0.3)
            or (breakout_score_val is not None
                and node.get("breakout_vol_ratio") is not None
                and breakout_score_val >= 70.0
                and node.get("breakout_vol_ratio") >= 1.5)
            or iv_divergence_val is not None
            or (n_sources >= 3 and signal_avg >= 0.3)
        ):
            tier = "ATMOSPHERE"
        elif n_sources >= 1:
            tier = "ROCKY"
        else:
            tier = "DARK"

        node["emergence_tier"] = tier
        return score

    def get_emerging_planets(
        self,
        min_score: float = 0.3,
        min_tier: str = "ATMOSPHERE",
        max_aeternus_score: Optional[float] = None,
        top_k: int = 50,
    ) -> List[dict]:
        """
        Return company nodes that are emerging alpha candidates.

        Filters by: tier in qualifying tiers AND emergence_score >= min_score.
        For min_tier="ATMOSPHERE" the qualifying tiers are ["ATMOSPHERE", "HABITABLE"].
        If max_aeternus_score is not None, nodes with aeternus_score > max_aeternus_score
        are excluded.
        Returns top_k sorted by emergence_score descending.
        """
        _tier_order = ["DARK", "ROCKY", "ATMOSPHERE", "HABITABLE", "SCORED"]
        if min_tier in _tier_order:
            min_idx = _tier_order.index(min_tier)
        else:
            min_idx = 0
        qualifying_tiers = set(_tier_order[min_idx:min_idx + 2]) if min_tier == "ATMOSPHERE" else {min_tier}
        # For ATMOSPHERE: include ATMOSPHERE and HABITABLE (not SCORED)
        # Rebuild more precisely: tiers >= min_tier but stop before SCORED
        qualifying_tiers = {t for t in _tier_order[min_idx:] if t != "SCORED"}

        results = []
        for node in self._nodes.values():
            if node.get("node_type") != "company":
                continue
            tier = node.get("emergence_tier")
            if tier not in qualifying_tiers:
                continue
            score = node.get("emergence_score")
            if score is None or score < min_score:
                continue
            if max_aeternus_score is not None:
                aeternus = node.get("aeternus_score")
                if aeternus is not None and aeternus > max_aeternus_score:
                    continue
            results.append({
                "id": node["id"],
                "sector": node.get("sector"),
                "centrality": node.get("centrality"),
                "emergence_score": score,
                "emergence_tier": tier,
                "n_signal_sources": node.get("emergence_n_sources", 0),
                "cashtag_velocity_z": node.get("cashtag_velocity_z"),
                "cashtag_sentiment": node.get("cashtag_sentiment"),
                "cashtag_velocity_trend": node.get("cashtag_velocity_trend"),
                "cashtag_last_updated": node.get("cashtag_last_updated"),
            })

        results.sort(key=lambda r: r["emergence_score"], reverse=True)
        return results[:top_k]

    def compute_all_emergence_scores(self) -> None:
        """Recompute emergence score for all company nodes in one pass."""
        for node_id, node in self._nodes.items():
            if node.get("node_type") == "company":
                self.compute_emergence_score(node_id)

    # ------------------------------------------------------------------
    # Cluster detection (S-050) — sector-level theme formation signal
    # ------------------------------------------------------------------

    def detect_clusters(self, strength_threshold: float = 0.3) -> list:
        """
        Compute sector-level cluster signals from company node emergence scores.

        For each sector node:
        - Collect all company nodes where node["sector"] == sector_id
        - Compute avg_emergence_score across them
        - Count nodes where emergence_score >= 0.2 (ATMOSPHERE or above)
        - Compute cluster_strength = (rising_count / total_nodes) * avg_emergence_score
        - Update sector node with cluster fields
        - If cluster_strength >= strength_threshold AND sector.active == False:
            mark sector node as cluster_candidate=True

        Returns list of {sector_id, cluster_strength, avg_emergence, rising_count, total_nodes}
        for all sectors where cluster_candidate=True, sorted by cluster_strength desc.
        """
        today = dt.date.today().isoformat()
        candidates = []

        # Group company nodes by sector
        sector_companies: dict = {}
        for node in self._nodes.values():
            if node.get("node_type") != "company":
                continue
            sector = node.get("sector")
            if not sector:
                continue
            if sector not in sector_companies:
                sector_companies[sector] = []
            sector_companies[sector].append(node)

        # Compute cluster signal per sector
        for sector_id, companies in sector_companies.items():
            if not companies:
                continue

            scores = [n.get("emergence_score") or 0.0 for n in companies]
            avg_score = round(sum(scores) / len(scores), 6)
            rising_count = sum(1 for s in scores if s >= 0.2)  # ATMOSPHERE or above
            total = len(companies)
            strength = round((rising_count / total) * avg_score, 6) if total > 0 else 0.0

            # Write to sector node if it exists
            if sector_id in self._nodes:
                s_node = self._nodes[sector_id]
                s_node["cluster_strength"] = strength
                s_node["cluster_avg_emergence"] = avg_score
                s_node["cluster_rising_count"] = rising_count
                s_node["cluster_total_nodes"] = total
                s_node["cluster_last_computed"] = today

                is_active = s_node.get("active", False)
                is_candidate = (not is_active) and (strength >= strength_threshold)
                s_node["cluster_candidate"] = is_candidate

                if is_candidate:
                    candidates.append({
                        "sector_id": sector_id,
                        "cluster_strength": strength,
                        "avg_emergence": avg_score,
                        "rising_count": rising_count,
                        "total_nodes": total,
                    })

        candidates.sort(key=lambda c: c["cluster_strength"], reverse=True)
        return candidates

    def get_cluster_candidates(self) -> list:
        """
        Return sector nodes marked as cluster_candidate=True, sorted by cluster_strength desc.
        These are dormant sectors showing signs of theme formation.
        """
        candidates = [
            node for node in self._nodes.values()
            if node.get("node_type") == "sector" and node.get("cluster_candidate") is True
        ]
        return sorted(candidates, key=lambda n: n.get("cluster_strength") or 0.0, reverse=True)

    def validate_cluster_theme(
        self,
        sector_id: str,
        tickers: list,
        strength: float,
        rename_threshold: float = 0.1,
    ):
        """
        Validate an emerging cluster theme with supply-chain context and thesis analysis.

        Feeds AKG relationships, emergence tiers, and scores to the LLM for
        thesis validation, coincidence detection, and missing player identification.

        Args:
            sector_id: AKG sector node ID (e.g. "semis_ai_infrastructure")
            tickers: list of rising ticker symbols in the cluster
            strength: current cluster_strength
            rename_threshold: only re-validate if strength has risen by this much since last naming

        Returns:
            {"theme_name", "hypothesis", "is_coincidence", "thesis_confidence",
             "missing_players": [{"ticker", "reasoning"}]} on success, None otherwise.
            Also writes results directly to the sector node.
        """
        if sector_id not in self._nodes:
            return None

        s_node = self._nodes[sector_id]

        # Idempotency gate: skip if already named and strength hasn't risen enough
        last_strength = s_node.get("cluster_theme_strength_at_naming") or 0.0
        if s_node.get("cluster_theme_name") and (strength - last_strength) < rename_threshold:
            return None  # Already named, not strong enough to re-validate

        # Build context: tickers with AKG metadata
        capped_tickers = tickers[:10]
        ticker_str = ", ".join(capped_tickers)
        display_name = s_node.get("display_name") or sector_id

        # Gather supply chain edges between cluster members
        edge_lines = []
        for t in capped_tickers:
            neighbors = self.get_supply_chain_neighbors(t)
            for n in neighbors:
                if n["ticker"] in capped_tickers:
                    edge_lines.append(f"  {t} --{n['direction']}--> {n['ticker']} (weight={n['weight']:.2f})")

        # Gather AKG node metadata per ticker
        meta_lines = []
        for t in capped_tickers:
            node = self._nodes.get(t, {})
            tier = node.get("emergence_tier", "DARK")
            score = node.get("emergence_score") or 0.0
            meta_lines.append(f"  {t}: tier={tier}, emergence={score:.3f}")

        context_block = ""
        if meta_lines:
            context_block += "Cluster members:\n" + "\n".join(meta_lines) + "\n"
        if edge_lines:
            context_block += "Supply chain links between members:\n" + "\n".join(edge_lines) + "\n"

        prompt = (
            f"These stocks are showing correlated rising momentum in the {display_name} sector: {ticker_str}.\n\n"
            f"{context_block}\n"
            f"Answer these 5 questions in JSON:\n"
            f"1. theme_name: 3-6 word theme name\n"
            f"2. hypothesis: 1-sentence investment thesis — why are these correlated?\n"
            f"3. is_coincidence: bool — is this a real structural driver or just coincidence?\n"
            f"4. missing_players: up to 3 tickers that benefit from this theme but aren't listed "
            f"(each as {{\"ticker\": \"SYM\", \"reasoning\": \"why\"}})\n"
            f"5. thesis_confidence: float 0-1 — how confident is this thesis?\n\n"
            f"Return JSON only: {{\"theme_name\": str, \"hypothesis\": str, \"is_coincidence\": bool, "
            f"\"missing_players\": [{{\"ticker\": str, \"reasoning\": str}}], \"thesis_confidence\": float}}"
        )

        try:
            from tradingagents.dataflows.llm_quick import quick_complete
            raw = quick_complete(prompt, max_tokens=250, temperature=0.3)
            if not raw:
                return None
            raw = raw.strip()
            import json as _json
            import re as _re
            # Extract JSON from response (model may add markdown fences)
            m = _re.search(r'\{.*\}', raw, _re.DOTALL)
            if not m:
                return None
            data = _json.loads(m.group())
            theme_name = str(data.get("theme_name", "")).strip()
            hypothesis = str(data.get("hypothesis", "")).strip()
            if not theme_name:
                return None

            is_coincidence = bool(data.get("is_coincidence", False))
            thesis_confidence = float(data.get("thesis_confidence") or 0.0)
            thesis_confidence = max(0.0, min(1.0, thesis_confidence))
            missing_players = data.get("missing_players") or []
            if not isinstance(missing_players, list):
                missing_players = []
            # Sanitize: cap at 3 entries, ensure each has ticker+reasoning
            clean_players = []
            for mp in missing_players[:3]:
                if isinstance(mp, dict) and mp.get("ticker"):
                    clean_players.append({
                        "ticker": str(mp["ticker"]).upper().strip(),
                        "reasoning": str(mp.get("reasoning", "")).strip(),
                    })
            missing_players = clean_players

            # Write to sector node
            s_node["cluster_theme_name"] = theme_name
            s_node["cluster_theme_hypothesis"] = hypothesis
            s_node["cluster_theme_named_at"] = dt.date.today().isoformat()
            s_node["cluster_theme_strength_at_naming"] = strength
            s_node["cluster_theme_is_coincidence"] = is_coincidence
            s_node["cluster_theme_confidence"] = thesis_confidence
            s_node["cluster_theme_missing_players"] = missing_players

            return {
                "theme_name": theme_name,
                "hypothesis": hypothesis,
                "is_coincidence": is_coincidence,
                "thesis_confidence": thesis_confidence,
                "missing_players": missing_players,
            }

        except Exception:
            return None

    def name_cluster_theme(
        self,
        sector_id: str,
        tickers: list,
        strength: float,
        rename_threshold: float = 0.1,
    ):
        """Backward-compatible alias for validate_cluster_theme()."""
        return self.validate_cluster_theme(sector_id, tickers, strength, rename_threshold)

    def decay_all(self, days_elapsed: int = 1) -> None:
        """
        Exponential decay on all edge weights and node signal_strength.
        Default rate: 10% per 30 days.  Floor: 0.01 for edges, 0.0 for signals.
        """
        decay_factor = 0.9 ** (days_elapsed / 30.0)
        min_weight = 0.01

        for edge in self._edges:
            edge["weight"] = max(min_weight, round(edge["weight"] * decay_factor, 6))

        for node in self._nodes.values():
            node["signal_strength"] = max(
                0.0, round(node["signal_strength"] * decay_factor, 6)
            )

    # ------------------------------------------------------------------
    # Convenience domain methods
    # ------------------------------------------------------------------

    def record_scout_hit(self, ticker: str, sector: str, themes_matched: List[str],
                         source_accounts: List[str], signal_strength: float) -> None:
        """Called after each sector scout run to update the graph."""
        self.add_node(ticker, node_type="company", sector=sector)
        node = self._nodes[ticker]
        node["times_surfaced"] += 1
        node["last_surfaced"] = dt.date.today().isoformat()
        node["signal_strength"] = min(1.0, node["signal_strength"] + signal_strength * 0.2)

        for theme in themes_matched:
            self.add_node(theme, node_type="theme")
            self.add_edge(ticker, theme, "catalyst_beneficiary",
                          confidence=0.7, evidence_source="xai_scout")

        for account in source_accounts:
            self.add_node(account, node_type="account")
            self.add_edge(account, ticker, "mentioned_by",
                          confidence=0.6, evidence_source="xai_scout")

    def record_pipeline_score(self, ticker: str, aeternus_score: float) -> None:
        """Called by trading_graph.py after propagate() returns a rating."""
        if ticker not in self._nodes:
            self.add_node(ticker, node_type="company")
        self._nodes[ticker]["aeternus_score"] = aeternus_score

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

        # Store thesis summary if provided
        thesis = rating.get("thesis_summary")
        if thesis:
            node["last_thesis_summary"] = str(thesis)[:150]

        # Ensemble data (per-model scores, weights, quant-only reference)
        ensemble_model_scores = rating.get("ensemble_model_scores")
        if ensemble_model_scores:
            node["last_ensemble_model_scores"] = ensemble_model_scores
        ensemble_weights = rating.get("ensemble_weights")
        if ensemble_weights:
            node["last_ensemble_weights"] = ensemble_weights
        quant_only_score = rating.get("quant_only_score")
        if quant_only_score is not None:
            node["last_quant_only_score"] = quant_only_score
        # Pillar breakdown
        breakdown = rating.get("breakdown")
        if breakdown:
            node["last_breakdown"] = breakdown
            self.write_pillar_scores(ticker, breakdown, date)
        weight_regime = rating.get("weight_regime")
        if weight_regime:
            node["last_weight_regime"] = weight_regime

        # Rolling score history (last 10) — now includes ensemble data
        if score is not None:
            history = node.get("score_history") or []
            entry = {"date": date, "score": score, "rating": rating_str}
            if ensemble_model_scores:
                entry["ensemble_model_scores"] = ensemble_model_scores
            if quant_only_score is not None:
                entry["quant_only_score"] = quant_only_score
            history.append(entry)
            node["score_history"] = history[-10:]

        # Backward compat: update legacy aeternus_score field
        if score is not None:
            node["aeternus_score"] = score

        # Recompute emergence tier (scored nodes become SCORED tier)
        self.compute_emergence_score(ticker)

    def write_pillar_scores(self, ticker: str, breakdown: dict, as_of_date: str) -> None:
        """Write per-pillar scores to node so thesis stress detection works."""
        if ticker not in self._nodes:
            return
        node = self._nodes[ticker]
        for pillar, score in breakdown.items():
            if score is not None:
                node[f"last_{pillar}_score"] = round(float(score), 4)
        node["last_pillar_scores_updated"] = as_of_date

    def record_thesis_outcome(self, ticker: str, confirmed: bool) -> None:
        """
        Increment thesis_track_record.  Adjust outgoing edge weights:
        confirmed: +0.03, invalidated: -0.05 (floor 0.01).
        """
        if ticker not in self._nodes:
            self.add_node(ticker, node_type="company")

        record = self._nodes[ticker]["thesis_track_record"]
        if confirmed:
            record["confirmed"] += 1
            delta = 0.03
        else:
            record["invalidated"] += 1
            delta = -0.05

        for idx in self._adj_out.get(ticker, []):
            edge = self._edges[idx]
            edge["weight"] = max(0.01, round(edge["weight"] + delta, 6))

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
            d0 = dt.date.fromisoformat(entry_date)
            d1 = dt.date.fromisoformat(exit_date)
            hold_days = (d1 - d0).days
        except Exception:
            pass

        node["last_closed_position"] = {
            "exit_date": exit_date,
            "exit_price": exit_price,
            "realized_return_pct": realized_return_pct,
            "hold_days": hold_days,
        }
        self.record_outcome(ticker, realized_return_pct, hold_days)
        node["current_position"] = None

        # Update thesis track record (confirmed if positive return)
        confirmed = realized_return_pct > 0
        self.record_thesis_outcome(ticker, confirmed)

        return True

    def get_open_positions(self) -> list:
        """Return all company nodes with an active current_position."""
        results = []
        for node_id, node in self._nodes.items():
            if node.get("node_type") != "company":
                continue
            pos = node.get("current_position")
            if not pos or not isinstance(pos, dict) or not pos.get("shares"):
                continue
            results.append({
                "id": node_id,
                "sector": node.get("sector"),
                "current_position": dict(pos),
                "last_aeternus_score": node.get("last_aeternus_score"),
                "last_scored_date": node.get("last_scored_date"),
                "outcome_weight": node.get("outcome_weight") or 1.0,
                "score_history": node.get("score_history") or [],
            })
        return sorted(results, key=lambda r: r["id"])

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

    def set_fundamentals_cache(self, ticker: str, snapshot: dict, earnings_date: str = None) -> None:
        """
        Cache a fundamentals snapshot on the AKG node.
        snapshot: the dict returned by fundamental_engine (metrics, ratios, etc.)
        earnings_date: optional ISO date string for next earnings.
        """
        if ticker not in self._nodes:
            self.add_node(ticker, node_type="company")
        node = self._nodes[ticker]
        node["fundamentals_snapshot"] = snapshot
        node["fundamentals_fetched_at"] = dt.date.today().isoformat()
        if earnings_date:
            node["earnings_date_next"] = earnings_date

    def get_fundamentals_cache(self, ticker: str, ttl_days: int = 90) -> dict:
        """
        Return cached fundamentals snapshot if within TTL, else None.
        Returns None if: node missing, no snapshot, or snapshot older than ttl_days.
        """
        if ticker not in self._nodes:
            return None
        node = self._nodes[ticker]
        snapshot = node.get("fundamentals_snapshot")
        fetched_at = node.get("fundamentals_fetched_at")
        if not snapshot or not fetched_at:
            return None
        try:
            fetched = dt.date.fromisoformat(fetched_at)
            if (dt.date.today() - fetched).days > ttl_days:
                return None
        except (ValueError, TypeError):
            return None
        return snapshot

    # ------------------------------------------------------------------
    # Structural Force Engine (S-052) — dark matter candidates
    # ------------------------------------------------------------------

    def get_dark_matter_candidates(
        self,
        min_discovery_score: float = 0.5,
        top_k: int = 20,
    ) -> list:
        """
        Run derive_dark_matter() for all active structural forces.
        Deduplicate by ticker (keep highest discovery_score).
        Return top_k sorted by discovery_score desc.

        Each dict: {ticker, force_id, causal_step, necessity_score, market_ignorance_score,
                    force_acceleration, discovery_score, reasoning, already_in_akg}
        """
        from tradingagents.graph.structural_forces import get_active_forces, derive_dark_matter
        candidates = []
        for force in get_active_forces():
            candidates.extend(derive_dark_matter(force, self))

        # Deduplicate: keep highest discovery_score per ticker
        by_ticker: dict = {}
        for c in candidates:
            if c.ticker not in by_ticker or c.discovery_score > by_ticker[c.ticker].discovery_score:
                by_ticker[c.ticker] = c

        results = sorted(by_ticker.values(), key=lambda x: x.discovery_score, reverse=True)
        return [vars(c) for c in results[:top_k] if c.discovery_score >= min_discovery_score]

    def set_perplexity_enrichment(self, ticker: str, text: str) -> None:
        """Cache Perplexity sonar enrichment on AKG node."""
        if ticker not in self._nodes:
            self.add_node(ticker, node_type="company")
        node = self._nodes[ticker]
        node["perplexity_enrichment"] = text
        node["perplexity_enriched_at"] = dt.date.today().isoformat()

    def get_perplexity_enrichment(self, ticker: str, ttl_days: int = 30) -> str | None:
        """
        Return cached enrichment text if within TTL, else None.
        Returns None for missing nodes, no enrichment, or expired TTL.
        """
        if ticker not in self._nodes:
            return None
        node = self._nodes[ticker]
        text = node.get("perplexity_enrichment")
        fetched_at = node.get("perplexity_enriched_at")
        if not text or not fetched_at:
            return None
        try:
            fetched = dt.date.fromisoformat(fetched_at)
            if (dt.date.today() - fetched).days > ttl_days:
                return None
        except (ValueError, TypeError):
            return None
        return text

    def set_insider_alpha(self, ticker: str, data: dict) -> None:
        """Cache insider Alpha Score data on AKG node."""
        if ticker not in self._nodes:
            self.add_node(ticker, node_type="company")
        node = self._nodes[ticker]
        node["insider_alpha_score"] = data.get("alpha_score")
        node["insider_alpha_win_rate_30d"] = data.get("win_rate_30d")
        node["insider_alpha_avg_fwd_return_30d"] = data.get("avg_fwd_return_30d")
        node["insider_alpha_buy_count"] = data.get("buy_count")
        node["insider_alpha_total_value_usd"] = data.get("total_value_usd")
        node["insider_alpha_insufficient_data"] = data.get("insufficient_data")
        node["insider_alpha_computed_date"] = dt.date.today().isoformat()

    def get_insider_alpha(self, ticker: str, ttl_days: int = 30) -> dict | None:
        """
        Return cached insider Alpha Score data if within TTL, else None.
        Returns None for missing nodes, no computed date, or expired TTL.
        """
        if ticker not in self._nodes:
            return None
        node = self._nodes[ticker]
        computed_date = node.get("insider_alpha_computed_date")
        if not computed_date:
            return None
        try:
            computed = dt.date.fromisoformat(computed_date)
            if (dt.date.today() - computed).days > ttl_days:
                return None
        except (ValueError, TypeError):
            return None
        return {
            "alpha_score": node.get("insider_alpha_score"),
            "win_rate_30d": node.get("insider_alpha_win_rate_30d"),
            "avg_fwd_return_30d": node.get("insider_alpha_avg_fwd_return_30d"),
            "buy_count": node.get("insider_alpha_buy_count"),
            "total_value_usd": node.get("insider_alpha_total_value_usd"),
            "insufficient_data": node.get("insider_alpha_insufficient_data"),
        }

    def update_from_sec_8k(self, source_ticker: str, target_tickers: List[str],
                            confidence: float = 0.95) -> None:
        """Called by sec_catalyst.py after parsing a supply agreement 8-K."""
        self.add_node(source_ticker, node_type="company")
        for target in target_tickers:
            self.add_node(target, node_type="company")
            self.add_edge(source_ticker, target, "supply_chain",
                          confidence=confidence, evidence_source="sec_8k")

    def seed_from_supply_chain_map(self, supply_chain_map: Dict[str, List[str]]) -> None:
        """
        Seed edges from a supply chain map dict (same format as SUPPLY_CHAIN_MAP).
        Idempotent — can be called multiple times safely.
        """
        for source, targets in supply_chain_map.items():
            self.add_node(source, node_type="company")
            for target in targets:
                self.add_node(target, node_type="company")
                self.add_edge(source, target, "supply_chain",
                              confidence=0.8, evidence_source="seed")

    # ------------------------------------------------------------------
    # Seed initialization (private)
    # ------------------------------------------------------------------

    def _bootstrap_universe(self) -> int:
        """
        Load universe constituents from bundled CSV as DARK nodes.
        Idempotent — existing nodes are not overwritten.
        Returns number of new nodes added.
        """
        csv_path = Path(__file__).parent / "data" / "universe_constituents.csv"
        if not csv_path.exists():
            return 0

        import csv
        added = 0
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ticker = row.get("ticker", "").strip().upper()
                if not ticker or len(ticker) > 6:
                    continue
                if ticker in self._nodes:
                    continue  # idempotent — don't overwrite
                sector_yf = row.get("sector_yf", "")
                sector = _YFINANCE_SECTOR_MAP.get(sector_yf)
                self.add_node(
                    ticker,
                    node_type="company",
                    sector=sector,
                    display_name=row.get("name", ticker),
                    metadata={"source": "universe_bootstrap", "confidence": 0.1},
                )
                added += 1
        return added

    def _seed(self) -> None:
        """Initialize graph with baseline data. Called by load() when file missing."""
        # Sector super-nodes
        for sector in SEED_SECTORS:
            self.add_node(sector, node_type="sector",
                          display_name=sector.replace("_", " ").title())

        # Theme nodes
        for theme in SEED_THEMES:
            self.add_node(theme, node_type="theme",
                          display_name=theme.replace("_", " "))

        # Company nodes
        for ticker, sector, display_name in SEED_COMPANIES:
            self.add_node(ticker, node_type="company", sector=sector,
                          display_name=display_name)

        # Try to import SUPPLY_CHAIN_MAP from sec_catalyst (S-034).
        # Fall back to inline SUPPLY_CHAIN_MAP if module not yet merged.
        try:
            from tradingagents.dealflow.sources.sec_catalyst import (  # type: ignore
                SUPPLY_CHAIN_MAP as _catalyst_map,
            )
            scm = _catalyst_map
        except ImportError:
            scm = SUPPLY_CHAIN_MAP

        self.seed_from_supply_chain_map(scm)

        # Bootstrap broad universe (S-049)
        if os.environ.get("AKG_UNIVERSE_BOOTSTRAP_ENABLED", "1") != "0":
            self._bootstrap_universe()

    # ------------------------------------------------------------------
    # Obsidian export
    # ------------------------------------------------------------------

    def to_obsidian(self, vault_path) -> int:
        """
        Export full graph as an Obsidian-compatible Markdown vault.
        Returns count of files written.
        """
        vault = Path(vault_path)
        (vault / "companies").mkdir(parents=True, exist_ok=True)
        (vault / "themes").mkdir(parents=True, exist_ok=True)
        (vault / "sectors").mkdir(parents=True, exist_ok=True)
        (vault / "forces").mkdir(parents=True, exist_ok=True)

        # Ensure centrality is up-to-date
        self.get_centrality_scores()

        files_written = 0

        # Group nodes by type
        company_nodes = [n for n in self._nodes.values() if n["node_type"] == "company"]
        theme_nodes = [n for n in self._nodes.values() if n["node_type"] == "theme"]
        sector_nodes = [n for n in self._nodes.values() if n["node_type"] == "sector"]

        # --- Company files ---
        for node in company_nodes:
            content = self._render_company_md(node)
            filename = _sanitize_filename(node["id"]) + ".md"
            (vault / "companies" / filename).write_text(content, encoding="utf-8")
            files_written += 1

        # --- Theme files ---
        for node in theme_nodes:
            content = self._render_theme_md(node)
            filename = _sanitize_filename(node["id"]) + ".md"
            (vault / "themes" / filename).write_text(content, encoding="utf-8")
            files_written += 1

        # --- Sector files ---
        for node in sector_nodes:
            content = self._render_sector_md(node, company_nodes)
            filename = _sanitize_filename(node["id"]) + ".md"
            (vault / "sectors" / filename).write_text(content, encoding="utf-8")
            files_written += 1

        # --- Structural forces ---
        files_written += self._render_forces_to_vault(vault)

        # --- Graph summary ---
        summary = self._render_summary(company_nodes, theme_nodes, sector_nodes)
        (vault / "_graph_summary.md").write_text(summary, encoding="utf-8")
        files_written += 1

        return files_written

    def _render_forces_to_vault(self, vault: Path) -> int:
        """Export structural forces as Obsidian-linked Markdown files."""
        try:
            from tradingagents.graph.structural_forces import STRUCTURAL_FORCES
        except ImportError:
            return 0

        files = 0
        for force in STRUCTURAL_FORCES:
            lines = [
                "---",
                f"force_id: {force.force_id}",
                f"conviction: {force.effective_conviction}",
                f"acceleration: {force.effective_acceleration}",
                f"horizon_months: {force.horizon_months}",
                "---",
                "",
                f"# {force.display_name}",
                "",
                force.description,
                "",
                "## Why Durable",
                force.why_durable,
                "",
                "## Causal Chain",
            ]
            for step in force.causal_chain:
                ticker_links = ", ".join(f"[[{t}]]" for t in step.derived_tickers)
                lines += [
                    f"### Step {step.step}: {step.description}",
                    f"- **Necessity:** {step.necessity_score:.0%}",
                    f"- **Sector:** [[{step.sector_id}]]",
                    f"- **Tickers:** {ticker_links}",
                    f"- {step.reasoning}",
                    "",
                ]
            lines += ["## Must Be True"]
            for cond in force.must_be_true:
                lines.append(f"- [ ] {cond}")
            lines += ["", "## Anti-Fragile To"]
            for item in force.anti_fragile_to:
                lines.append(f"- {item}")
            content = "\n".join(lines) + "\n"
            fname = _sanitize_filename(force.force_id) + ".md"
            (vault / "forces" / fname).write_text(content, encoding="utf-8")
            files += 1

        # Forces index
        index_lines = ["# Structural Forces", ""]
        for f in STRUCTURAL_FORCES:
            index_lines.append(
                f"- [[{f.force_id}]] — {f.display_name} "
                f"(conviction {f.effective_conviction:.0%}, {f.effective_acceleration})"
            )
        (vault / "forces" / "_index.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
        files += 1
        return files

    def _render_company_md(self, node: dict) -> str:
        nid = node["id"]
        score_val = node["aeternus_score"]
        score_str = str(score_val) if score_val is not None else "null"

        tier = node.get("emergence_tier") or "DARK"
        e_score = node.get("emergence_score") or 0.0
        lines = [
            "---",
            f"ticker: {nid}",
            f"sector: {node['sector'] or 'null'}",
            f"signal_strength: {node['signal_strength']}",
            f"centrality: {node['centrality']}",
            f"aeternus_score: {score_str}",
            f"emergence_tier: {tier}",
            f"emergence_score: {e_score}",
            f"times_surfaced: {node['times_surfaced']}",
            f"last_surfaced: {node['last_surfaced'] or 'null'}",
            f"thesis_confirmed: {node['thesis_track_record']['confirmed']}",
            f"thesis_invalidated: {node['thesis_track_record']['invalidated']}",
            "---",
            "",
            f"# {node['display_name']} (${nid})",
            "",
            f"**Sector:** [[{node['sector']}]]" if node.get("sector") else "",
            f"**Emergence:** {tier} (score: {e_score:.4f})" if tier != "DARK" or e_score > 0 else f"**Emergence:** {tier}",
            "",
        ]

        # Outgoing edges grouped by relationship
        outgoing = self._outgoing_edges(nid)
        rel_map: Dict[str, List[str]] = defaultdict(list)
        for e in outgoing:
            rel_map[e["relationship"]].append(e["target"])

        lines.append("## Connected Companies")
        if "supply_chain" in rel_map:
            lines.append("### Supplies to")
            for t in rel_map["supply_chain"]:
                lines.append(f"- [[{t}]]")
            lines.append("")

        if "sector_peer" in rel_map:
            lines.append("### Sector Peers")
            for t in rel_map["sector_peer"]:
                lines.append(f"- [[{t}]]")
            lines.append("")

        if "catalyst_beneficiary" in rel_map:
            lines.append("### Catalyst Beneficiaries")
            for t in rel_map["catalyst_beneficiary"]:
                lines.append(f"- [[{t}]]")
            lines.append("")

        # Incoming mentioned_by edges
        incoming = self._incoming_edges(nid)
        mentioners = [e["source"] for e in incoming if e["relationship"] == "mentioned_by"]
        if mentioners:
            lines.append("## Mentioned By")
            for src in mentioners:
                lines.append(f"- [[{src}]]")
            lines.append("")

        # Themes (outgoing catalyst_beneficiary to theme nodes)
        themes = [
            e["target"] for e in outgoing
            if e["relationship"] == "catalyst_beneficiary"
            and self._nodes.get(e["target"], {}).get("node_type") == "theme"
        ]
        if themes:
            lines.append("## Themes")
            for t in themes:
                lines.append(f"- [[{t}]]")
            lines.append("")

        lines += [
            "## Signal History",
            f"- times_surfaced: {node['times_surfaced']}",
            f"- last_surfaced: {node['last_surfaced'] or 'null'}",
            f"- signal_strength: {node['signal_strength']}",
            "",
            "## Track Record",
            f"- Confirmed theses: {node['thesis_track_record']['confirmed']}",
            f"- Invalidated: {node['thesis_track_record']['invalidated']}",
        ]

        return "\n".join(lines) + "\n"

    def _render_theme_md(self, node: dict) -> str:
        nid = node["id"]
        display = node["display_name"] or nid

        lines = [
            "---",
            f"theme: {nid}",
            "node_type: theme",
            "---",
            "",
            f"# {display}",
            "",
            "## Companies in This Theme",
        ]

        # Incoming catalyst_beneficiary edges from company nodes
        incoming = self._incoming_edges(nid)
        companies = [
            e["source"] for e in incoming
            if e["relationship"] == "catalyst_beneficiary"
            and self._nodes.get(e["source"], {}).get("node_type") == "company"
        ]
        for c in companies:
            lines.append(f"- [[{c}]]")

        return "\n".join(lines) + "\n"

    def _render_sector_md(self, node: dict, all_company_nodes: List[dict]) -> str:
        nid = node["id"]
        display = node["display_name"] or nid

        sector_companies = [
            c for c in all_company_nodes if c.get("sector") == nid
        ]
        sector_companies.sort(key=lambda n: n["centrality"], reverse=True)

        lines = [
            "---",
            f"sector: {nid}",
            "---",
            "",
            f"# {display}",
            "",
            "## Companies",
        ]

        for c in sector_companies:
            score_str = str(c["aeternus_score"]) if c["aeternus_score"] is not None else "null"
            lines.append(
                f"- [[{c['id']}]] — centrality: {c['centrality']}, "
                f"signal: {c['signal_strength']}, score: {score_str}"
            )

        return "\n".join(lines) + "\n"

    def _render_summary(self, company_nodes: List[dict], theme_nodes: List[dict],
                        sector_nodes: List[dict]) -> str:
        total_nodes = len(self._nodes)
        total_edges = len(self._edges)
        now = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")

        all_nodes_sorted = sorted(self._nodes.values(), key=lambda n: n["centrality"], reverse=True)
        top_15 = all_nodes_sorted[:15]
        dark = self.get_dark_nodes(min_centrality=0.0)[:10]

        # Hot sectors by average signal_strength
        sector_signals: Dict[str, List[float]] = defaultdict(list)
        for c in company_nodes:
            if c.get("sector"):
                sector_signals[c["sector"]].append(c["signal_strength"])
        sector_avgs = [
            (sec, sum(sigs) / len(sigs))
            for sec, sigs in sector_signals.items() if sigs
        ]
        sector_avgs.sort(key=lambda x: x[1], reverse=True)

        lines = [
            "# Aeternus Knowledge Graph — Summary",
            "",
            f"Generated: {now}",
            "",
            "## Stats",
            f"- Total nodes: {total_nodes}",
            f"- Total edges: {total_edges}",
            f"- Company nodes: {len(company_nodes)}",
            f"- Theme nodes: {len(theme_nodes)}",
            f"- Sector nodes: {len(sector_nodes)}",
            "",
            "## Top Centrality Nodes",
            "| Ticker | Centrality | Signal | Score | Times Surfaced |",
            "|--------|------------|--------|-------|----------------|",
        ]

        for n in top_15:
            score_str = str(n["aeternus_score"]) if n["aeternus_score"] is not None else "null"
            lines.append(
                f"| {n['id']} | {n['centrality']} | {n['signal_strength']} "
                f"| {score_str} | {n['times_surfaced']} |"
            )

        lines += [
            "",
            "## Dark Nodes (High Centrality, Not Yet Scored)",
            "| Ticker | Centrality | Times Surfaced | Sector |",
            "|--------|------------|----------------|--------|",
        ]
        for n in dark:
            lines.append(
                f"| {n['id']} | {n['centrality']} | {n['times_surfaced']} | {n.get('sector') or 'null'} |"
            )

        lines += ["", "## Hot Sectors (by average signal_strength)"]
        for i, (sec, avg) in enumerate(sector_avgs, 1):
            lines.append(f"{i}. [[{sec}]] — avg signal: {round(avg, 4)}")

        # Emergence tier distribution
        tier_counts: Dict[str, int] = {}
        for c in company_nodes:
            tier = c.get("emergence_tier") or "DARK"
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
        tier_order = ["DARK", "ROCKY", "ATMOSPHERE", "HABITABLE", "SCORED"]
        lines += ["", "## Emergence Pipeline"]
        lines.append("| Tier | Count | Description |")
        lines.append("|------|-------|-------------|")
        tier_descs = {
            "DARK": "No cashtag/sentiment data",
            "ROCKY": "1 signal source present",
            "ATMOSPHERE": "Both velocity + sentiment",
            "HABITABLE": "High conviction (v_z >= 2.0 AND sentiment >= 0.5)",
            "SCORED": "Pipeline-analyzed with AeternusScore",
        }
        for tier in tier_order:
            count = tier_counts.get(tier, 0)
            if count > 0:
                lines.append(f"| {tier} | {count} | {tier_descs.get(tier, '')} |")

        # Structural forces reference
        try:
            from tradingagents.graph.structural_forces import STRUCTURAL_FORCES
            lines += ["", "## Structural Forces"]
            for f in STRUCTURAL_FORCES:
                lines.append(
                    f"- [[{f.force_id}]] — {f.display_name} "
                    f"(conviction {f.effective_conviction:.0%}, {f.effective_acceleration})"
                )
        except ImportError:
            pass

        return "\n".join(lines) + "\n"

    # ─── Causal Chain Fields (S-068) ─────────────────────────────────────────

    def set_causal_event(self, event_id: str, data: dict) -> None:
        """Store a causal event. data keys: ticker, event_type, event_date, magnitude, direction, source, processed_at."""
        self._causal_events[event_id] = dict(data)
        self._updated_at = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")

    def get_recent_causal_events(self, max_age_hours: int = 48) -> List[dict]:
        """Return all causal events processed within max_age_hours. Used for dedup."""
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=max_age_hours)
        result = []
        for event in self._causal_events.values():
            processed_at = event.get("processed_at", "")
            try:
                ts = dt.datetime.fromisoformat(processed_at.replace("Z", "+00:00"))
                if ts >= cutoff:
                    result.append(event)
            except (ValueError, TypeError):
                pass
        return result

    def get_supply_chain_neighbors(self, ticker: str, direction: str = "both") -> List[dict]:
        """Return supply_chain neighbors with direction and weight.

        direction: 'upstream' | 'downstream' | 'both'
        upstream  = ticker's suppliers (edges where ticker is the target)
        downstream = ticker's customers (edges where ticker is the source)
        Returns: [{"ticker", "direction", "weight", "evidence_count"}]
        """
        results = []
        if direction in ("upstream", "both"):
            for idx in self._adj_in.get(ticker, []):
                edge = self._edges[idx]
                if edge.get("relationship") == "supply_chain":
                    results.append({
                        "ticker": edge["source"],
                        "direction": "upstream",
                        "weight": edge.get("weight", 1.0),
                        "evidence_count": edge.get("evidence_count", 1),
                    })
        if direction in ("downstream", "both"):
            for idx in self._adj_out.get(ticker, []):
                edge = self._edges[idx]
                if edge.get("relationship") == "supply_chain":
                    results.append({
                        "ticker": edge["target"],
                        "direction": "downstream",
                        "weight": edge.get("weight", 1.0),
                        "evidence_count": edge.get("evidence_count", 1),
                    })
        return results

    # ─── Thesis Claims (S-thesis-monitor) ────────────────────────────────────────

    def set_thesis_claims(self, ticker: str, claims: list, entry_date: str = None) -> None:
        """Store thesis monitoring claims derived from entry rating pillar scores.

        claims: list of dicts with keys: pillar, claim, stress_threshold, entry_score
        entry_date: ISO date when position was entered
        """
        if ticker not in self._nodes:
            self.add_node(ticker, node_type="company")
        self._nodes[ticker]["thesis_claims"] = claims
        self._nodes[ticker]["thesis_claims_set_at"] = entry_date or dt.date.today().isoformat()
        self._updated_at = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")

    def get_thesis_claims(self, ticker: str) -> list:
        """Return stored thesis claims for a ticker, or [] if none."""
        if ticker not in self._nodes:
            return []
        return self._nodes[ticker].get("thesis_claims", [])

    def get_thesis_stress_report(self, ticker: str) -> dict:
        """
        Check current AKG pillar scores against stored thesis claims.

        Returns:
        {
            "ticker": str,
            "claims_total": int,
            "claims_stressed": int,
            "stress_level": "NONE" | "WATCH" | "STRESS" | "CRITICAL",
            "stressed_claims": [{"pillar", "claim", "entry_score", "current_score", "stress_threshold"}],
        }
        """
        claims = self.get_thesis_claims(ticker)
        if not claims:
            return {
                "ticker": ticker,
                "claims_total": 0,
                "claims_stressed": 0,
                "stress_level": "NONE",
                "stressed_claims": [],
            }

        node = self._nodes.get(ticker, {})
        stressed = []
        for claim in claims:
            pillar = claim.get("pillar", "")
            threshold = claim.get("stress_threshold", 45)
            entry_score = claim.get("entry_score", 0)
            # Check current pillar scores from most recent aeternus breakdown
            # Stored in node under "last_{pillar}_score" — set by monitor
            current_score = node.get(f"last_{pillar}_score")
            if current_score is not None and current_score < threshold:
                stressed.append({
                    "pillar": pillar,
                    "claim": claim.get("claim", ""),
                    "entry_score": entry_score,
                    "current_score": current_score,
                    "stress_threshold": threshold,
                })

        n_stressed = len(stressed)
        if n_stressed == 0:
            level = "NONE"
        elif n_stressed == 1:
            level = "WATCH"
        elif n_stressed == 2:
            level = "STRESS"
        else:
            level = "CRITICAL"

        return {
            "ticker": ticker,
            "claims_total": len(claims),
            "claims_stressed": n_stressed,
            "stress_level": level,
            "stressed_claims": stressed,
        }


def _clamp_float(raw, lo: float, hi: float) -> float:
    try:
        value = float(raw)
    except Exception:
        value = lo
    return max(lo, min(hi, value))


def _sanitize_filename(name: str) -> str:
    """Replace characters unsafe in filenames."""
    for ch in r"/\:":
        name = name.replace(ch, "_")
    return name
