"""Serialization/load/save helpers for AeternusKnowledgeGraph."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any


def load_graph(graph_cls: type, path: Any, default_path: str):
    """Load graph_cls from JSON path. Initialize/seed when missing or empty."""
    if path is None:
        path = default_path
    path = Path(path)

    if not path.exists():
        graph = graph_cls()
        graph._seed()
        return graph

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"AKG: cannot read {path}: {exc}") from exc

    try:
        graph = graph_cls.from_json(raw)
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f"AKG: malformed JSON at {path}: {exc}") from exc

    company_nodes = [
        node for node in graph._nodes.values()
        if node.get("node_type") == "company"
    ]
    if not company_nodes or not graph._edges:
        graph._seed()
        graph.get_centrality_scores()
        refreshed_company_nodes = [
            node for node in graph._nodes.values()
            if node.get("node_type") == "company"
        ]
        if refreshed_company_nodes:
            graph.save(path)
    return graph


def graph_from_json(graph_cls: type, json_str: str):
    """Deserialize graph_cls from a JSON string. Rebuild adjacency indexes."""
    data = json.loads(json_str)
    graph = graph_cls()
    graph._version = data.get("version", 1)
    graph._created_at = data.get("created_at", graph._created_at)
    graph._updated_at = data.get("updated_at", graph._updated_at)
    graph._nodes = data.get("nodes", {})

    for i, edge in enumerate(data.get("edges", [])):
        graph._edges.append(edge)
        src = edge["source"]
        tgt = edge["target"]
        rel = edge["relationship"]
        graph._adj_out[src].append(i)
        graph._adj_in[tgt].append(i)
        graph._edge_index[(src, tgt, rel)] = i

    graph._causal_events = data.get("causal_events", {})
    graph._backfill_node_defaults()
    return graph


def graph_to_json(graph, path: Any = None) -> str:
    """Serialize graph to JSON string; optionally write to path atomically."""
    graph._updated_at = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    payload = {
        "version": graph._version,
        "created_at": graph._created_at,
        "updated_at": graph._updated_at,
        "nodes": graph._nodes,
        "edges": graph._edges,
        "causal_events": graph._causal_events,
    }
    json_str = json.dumps(payload, indent=2, ensure_ascii=False)
    if path is not None:
        atomic_write(Path(path), json_str)
    return json_str


def save_graph(graph, path: Any, default_path: str) -> None:
    """Atomic write to path, using default path when None."""
    if path is None:
        path = default_path
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    json_str = graph_to_json(graph)
    atomic_write(path, json_str)


def atomic_write(path: Path, content: str) -> None:
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(str(tmp_path), str(path))
