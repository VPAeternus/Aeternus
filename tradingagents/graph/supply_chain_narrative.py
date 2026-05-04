"""Portfolio Supply Chain Narrative Engine.

Detects when multiple portfolio positions belong to the same supply chain cluster
and generates a plain-English narrative about latent concentration risk.

Pure Python — no LLM calls, no network I/O.
"""
from __future__ import annotations

from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_notional(symbol: str, pos: dict) -> float:
    """Return abs(net_qty) * (mark_price if mark > 0 else avg_price)."""
    net_qty = abs(pos.get("net_quantity") or 0.0)
    mark = pos.get("last_mark_price") or 0.0
    avg = pos.get("avg_price") or 0.0
    price = mark if mark > 0 else avg
    return net_qty * price


def _build_position_clusters(tickers: list, neighbors: dict) -> List[List[str]]:
    """BFS connected components among position tickers.

    neighbors maps ticker -> set[ticker], where the set contains only
    other position tickers that share a supply chain edge.

    Returns list of clusters; each cluster is a sorted list of tickers.
    """
    visited: set = set()
    clusters: List[List[str]] = []

    for start in tickers:
        if start in visited:
            continue
        # BFS
        cluster = []
        queue = [start]
        while queue:
            node = queue.pop()
            if node in visited:
                continue
            visited.add(node)
            cluster.append(node)
            for nbr in neighbors.get(node, set()):
                if nbr not in visited:
                    queue.append(nbr)
        clusters.append(sorted(cluster))

    return clusters


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_portfolio_narrative(open_positions: dict, akg=None) -> str:
    """Generate a plain-English supply chain concentration narrative.

    Args:
        open_positions: dict of {symbol: position_dict}. Each position_dict
            must contain: net_quantity (float), avg_price (float), and
            optionally last_mark_price (float).
        akg: optional AeternusKnowledgeGraph instance. If None, one is
            loaded from the default path.

    Returns:
        A multi-line narrative string describing supply chain clusters found
        among the portfolio's positions, or "" if no clusters are detected
        or fewer than 2 positions are held.
    """
    # Guard: need at least 2 positions to detect concentration
    tickers = list(open_positions.keys())
    if len(tickers) < 2:
        return ""

    try:
        # Instantiate AKG if not provided
        if akg is None:
            from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
            akg = AeternusKnowledgeGraph()

        ticker_set = set(tickers)

        # Build adjacency restricted to position tickers only
        # neighbors[t] = set of position tickers connected by a supply chain edge
        neighbors: Dict[str, set] = {t: set() for t in tickers}
        for ticker in tickers:
            raw = akg.get_supply_chain_neighbors(ticker, direction="both")
            for entry in raw:
                nbr = entry["ticker"]
                if nbr in ticker_set and nbr != ticker:
                    neighbors[ticker].add(nbr)

        # Find connected components (clusters)
        clusters = _build_position_clusters(tickers, neighbors)

        # Separate clusters with >1 member from isolated singletons
        multi_clusters = [c for c in clusters if len(c) > 1]
        isolated = [c[0] for c in clusters if len(c) == 1]

        # No supply chain links found among positions
        if not multi_clusters:
            return ""

        # Compute notionals
        position_notional: Dict[str, float] = {
            sym: _compute_notional(sym, pos)
            for sym, pos in open_positions.items()
        }
        total_nav = sum(position_notional.values())

        # Compute NAV per cluster
        cluster_navs: List[tuple] = []  # (nav, cluster_tickers)
        for cluster in multi_clusters:
            nav = sum(position_notional.get(t, 0.0) for t in cluster)
            cluster_navs.append((nav, cluster))

        # Sort clusters by NAV descending
        cluster_navs.sort(key=lambda x: x[0], reverse=True)

        # Build narrative
        n_positions = len(tickers)
        n_clusters_total = len(clusters)
        lines: List[str] = [
            "Supply Chain Concentration Analysis:",
            f"  {n_positions} positions span {n_clusters_total} supply chain cluster(s).",
        ]

        for rank, (nav, cluster) in enumerate(cluster_navs, 1):
            concentration = (nav / total_nav * 100) if total_nav > 0 else 0.0
            ticker_str = ", ".join(cluster)
            lines.append(
                f"  {'Dominant' if rank == 1 else f'Cluster {rank}'} cluster: {ticker_str} "
                f"({concentration:.0f}% of NAV, ${nav:,.0f})"
            )
            lines.append(
                "    -- These positions share supply chain dependencies. A single demand shock"
            )
            lines.append(
                "       affecting this network could move all positions simultaneously."
            )
            if concentration > 40.0:
                lines.append(
                    f"  WARNING: {concentration:.0f}% portfolio NAV concentrated in one supply chain cluster."
                )

        isolated_str = ", ".join(sorted(isolated)) if isolated else "none"
        lines.append(
            f"  Isolated positions (no supply chain links to other holdings): {isolated_str}"
        )

        return "\n".join(lines)

    except Exception:
        return ""
