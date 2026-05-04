from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict

from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph


_TICKER_RE = re.compile(r"\$([A-Z]{1,5})\b")


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    with open(path, "r") as fh:
        return json.load(fh)


def update_observed_edges_for_cycle(
    source_date: str,
    *,
    knowledge_graph_path: Path | str = Path("eval_results/control/knowledge_graph.json"),
    x_feed_root: Path | str = Path("eval_results/x_feed"),
) -> Dict[str, Any]:
    knowledge_graph_path = Path(knowledge_graph_path)
    x_feed_root = Path(x_feed_root)
    merged = _load_json(x_feed_root / source_date / "merged.json") or {}
    graph = AeternusKnowledgeGraph.load(knowledge_graph_path)
    edges_added = 0
    evidence_source = f"x_feed:{source_date}"

    for symbol, row in dict(merged).items():
        source_symbol = str(symbol or row.get("ticker") or "").upper().strip()
        catalyst = str((row or {}).get("catalyst") or "")
        if not source_symbol or not catalyst:
            continue
        mentioned = {match.upper().strip() for match in _TICKER_RE.findall(catalyst)}
        mentioned.discard(source_symbol)
        for target_symbol in sorted(mentioned):
            graph.add_edge(source_symbol, target_symbol, "co_mentioned", confidence=0.35, evidence_source=evidence_source)
            edges_added += 1

    graph.save(knowledge_graph_path)
    return {
        "status": "OK",
        "source_date": source_date,
        "edges_added": edges_added,
        "knowledge_graph_path": str(knowledge_graph_path),
    }
