"""AKG-native theme heatmap reporting."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List

from tradingagents.dealflow.theme_aliases import canonicalize_theme_id, load_theme_aliases


def build_theme_heatmap(akg: Any, *, as_of_date: str) -> Dict[str, Any]:
    aliases = load_theme_aliases()
    buckets: Dict[str, Dict[str, Any]] = {}

    for theme_id, info in aliases.items():
        buckets[str(theme_id)] = _empty_bucket(str(theme_id), str(info.get("theme_name") or theme_id))

    for node in _iter_nodes(akg):
        if node.get("node_type") != "company":
            continue
        ticker = str(node.get("id", "")).upper().strip()
        if not ticker:
            continue
        theme_ids = _node_theme_ids(node, aliases)
        for theme_id in theme_ids:
            bucket = buckets.setdefault(theme_id, _empty_bucket(theme_id, theme_id))
            _add_node_to_bucket(bucket, node)

    _add_active_theme_nodes(akg, buckets, aliases)
    _add_edge_linked_tickers(akg, buckets, aliases)

    themes = []
    for bucket in buckets.values():
        linked = sorted(bucket.pop("_linked_tickers", set()))
        tickers = sorted(bucket.pop("_tickers", set()))
        momentum_scores = bucket.pop("_momentum_scores", [])
        accel_scores = bucket.pop("_acceleration_scores", [])
        evidence = bucket.pop("_evidence", [])
        top_tickers = sorted(bucket.pop("_top_ticker_rows", []), key=lambda r: (-r["score"], r["ticker"]))[:10]
        bucket.update({
            "active_theme_node_count": len(bucket.pop("_active_theme_nodes", set())),
            "linked_edge_count": int(bucket.get("linked_edge_count", 0)),
            "linked_ticker_count": len(set(linked) | set(tickers)),
            "number_with_emergence_signals": int(bucket.get("number_with_emergence_signals", 0)),
            "number_with_price_momentum": int(bucket.get("number_with_price_momentum", 0)),
            "number_with_filing_acceleration": int(bucket.get("number_with_filing_acceleration", 0)),
            "average_momentum_score": round(sum(momentum_scores) / len(momentum_scores), 4) if momentum_scores else 0.0,
            "average_theme_acceleration_score": round(sum(accel_scores) / len(accel_scores), 4) if accel_scores else 0.0,
            "top_tickers": [row["ticker"] for row in top_tickers],
            "top_evidence_snippets": evidence[:10],
        })
        if bucket["linked_ticker_count"] or bucket["number_with_emergence_signals"] or bucket["number_with_filing_acceleration"]:
            themes.append(bucket)

    themes.sort(key=lambda row: (-row["number_with_filing_acceleration"], -row["average_theme_acceleration_score"], -row["number_with_emergence_signals"], row["theme_id"]))
    return {
        "as_of_date": as_of_date,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "theme_count": len(themes),
        "themes": themes,
    }


def write_theme_heatmap(akg: Any, *, as_of_date: str, out_dir: Path | str = Path("eval_results") / "deal_flow") -> Path:
    payload = build_theme_heatmap(akg, as_of_date=as_of_date)
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"theme_heatmap_{as_of_date}.json"
    path.write_text(json.dumps(payload, indent=2, default=str))
    day_dir = root / as_of_date
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / "theme_heatmap.json").write_text(json.dumps(payload, indent=2, default=str))
    return path


def _empty_bucket(theme_id: str, theme_name: str) -> Dict[str, Any]:
    return {
        "theme_id": theme_id,
        "theme_name": theme_name,
        "active_theme_node_count": 0,
        "linked_edge_count": 0,
        "number_with_emergence_signals": 0,
        "number_with_price_momentum": 0,
        "number_with_filing_acceleration": 0,
        "_active_theme_nodes": set(),
        "_linked_tickers": set(),
        "_tickers": set(),
        "_momentum_scores": [],
        "_acceleration_scores": [],
        "_evidence": [],
        "_top_ticker_rows": [],
    }


def _node_theme_ids(node: Dict[str, Any], aliases: Dict[str, Dict[str, Any]]) -> List[str]:
    raw = []
    if node.get("primary_theme"):
        raw.append(node.get("primary_theme"))
    raw.extend(node.get("secondary_themes") or [])
    raw.extend(node.get("theme_links") or [])
    out = []
    for item in raw:
        tid = canonicalize_theme_id(str(item or ""), aliases)
        if tid and tid not in out:
            out.append(tid)
    return out


def _add_node_to_bucket(bucket: Dict[str, Any], node: Dict[str, Any]) -> None:
    ticker = str(node.get("id", "")).upper().strip()
    bucket["_tickers"].add(ticker)
    if node.get("emergence_score") is not None or node.get("emergence_tier") not in {None, "DARK"}:
        bucket["number_with_emergence_signals"] += 1
    momentum = _float(node.get("signal_momentum_score"))
    if momentum > 0:
        bucket["number_with_price_momentum"] += 1
        bucket["_momentum_scores"].append(momentum)
    accel = _float(node.get("signal_theme_acceleration_score"))
    if accel > 0:
        bucket["number_with_filing_acceleration"] += 1
        bucket["_acceleration_scores"].append(accel)
        for snippet in list(node.get("theme_evidence") or [])[:3]:
            text = str(snippet).strip()
            if text:
                bucket["_evidence"].append({"ticker": ticker, "evidence": text[:300]})
    score = max(_float(node.get("emergence_score")) * 100.0, momentum, accel * 6.6667)
    bucket["_top_ticker_rows"].append({"ticker": ticker, "score": score})


def _add_active_theme_nodes(akg: Any, buckets: Dict[str, Dict[str, Any]], aliases: Dict[str, Dict[str, Any]]) -> None:
    for node in _iter_nodes(akg):
        if node.get("node_type") != "theme":
            continue
        theme_id = canonicalize_theme_id(str(node.get("id", "")), aliases)
        if not theme_id:
            continue
        bucket = buckets.setdefault(theme_id, _empty_bucket(theme_id, theme_id))
        bucket["_active_theme_nodes"].add(str(node.get("id", theme_id)))


def _add_edge_linked_tickers(akg: Any, buckets: Dict[str, Dict[str, Any]], aliases: Dict[str, Dict[str, Any]]) -> None:
    nodes = _node_map(akg)
    for edge in _iter_edges(akg):
        source = str(edge.get("source", "")).upper().strip()
        target = str(edge.get("target", "")).strip()
        rel = str(edge.get("relationship", ""))
        if rel not in {"catalyst_beneficiary", "supply_chain", "theme_exposure"}:
            continue
        if source in nodes and nodes[source].get("node_type") == "company":
            theme_id = canonicalize_theme_id(target, aliases)
            ticker = source
        elif target.upper() in nodes and nodes[target.upper()].get("node_type") == "company":
            theme_id = canonicalize_theme_id(source, aliases)
            ticker = target.upper()
        else:
            continue
        bucket = buckets.setdefault(theme_id, _empty_bucket(theme_id, theme_id))
        bucket["_linked_tickers"].add(ticker)
        bucket["linked_edge_count"] += 1


def _iter_nodes(akg: Any):
    if hasattr(akg, "iter_nodes"):
        return akg.iter_nodes()
    return iter(tuple(getattr(akg, "_nodes", {}).values()))


def _iter_edges(akg: Any):
    if hasattr(akg, "iter_edges"):
        return akg.iter_edges()
    return iter(tuple(getattr(akg, "_edges", [])))


def _node_map(akg: Any) -> Dict[str, Dict[str, Any]]:
    return {str(node.get("id", "")): node for node in _iter_nodes(akg)}


def _float(raw: Any) -> float:
    try:
        return float(raw)
    except Exception:
        return 0.0
