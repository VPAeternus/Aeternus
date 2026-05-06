"""Evidence quality telemetry for finalized X-feed artifacts."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

WEIGHTS = {
    "verified_source_count": 0.20,
    "source_diversity": 0.15,
    "recency": 0.10,
    "theme_novelty": 0.15,
    "low_contradiction": 0.15,
    "source_integrity": 0.15,
    "theme_leadership": 0.10,
}


def build_x_feed_evidence_quality(
    *,
    as_of_date: str,
    merged: Optional[Dict[str, Dict[str, Any]]] = None,
    graph: Optional[Dict[str, Any]] = None,
    lookback_days: int = 14,
    base_dir: Path | str = Path("eval_results") / "x_feed",
) -> Dict[str, Dict[str, Any]]:
    """Return per-ticker evidence quality scores from finalized X-feed artifacts.

    Deterministic telemetry only. Missing fields degrade; nothing defaults high.
    """
    base = Path(base_dir)
    merged = merged if merged is not None else _load_json(base / as_of_date / "merged.json") or {}
    graph = graph if graph is not None else _load_json(base / as_of_date / "theme_emergence_graph.json") or {}
    history = _load_prior_theme_history(base=base, as_of_date=as_of_date, lookback_days=lookback_days)
    graph_tickers = dict((graph or {}).get("tickers", {}) or {})
    theme_nodes = dict((graph or {}).get("themes", {}) or {})

    out: Dict[str, Dict[str, Any]] = {}
    for ticker, row in dict(merged or {}).items():
        symbol = str(ticker).upper().strip()
        if not symbol:
            continue
        components = _score_components(symbol, dict(row or {}), graph_tickers.get(symbol, {}), theme_nodes, history, as_of_date)
        score = round(sum(float(components[k]) * w for k, w in WEIGHTS.items()), 4)
        out[symbol] = {
            "ticker": symbol,
            "evidence_quality_score": max(0.0, min(100.0, score)),
            "quality_components": components,
            "quality_version": "x_feed_evidence_quality_v1",
        }
    return out


def _score_components(
    ticker: str,
    row: Dict[str, Any],
    graph_row: Dict[str, Any],
    theme_nodes: Dict[str, Any],
    history: Dict[str, Dict[str, float]],
    as_of_date: str,
) -> Dict[str, float]:
    evidence = _evidence_rows(row)
    verified_count = _verified_source_count(row, evidence)
    accounts = _unique_values(row, evidence, "accounts_cited")
    pass_types = _unique_values(row, evidence, "source_pass_type") | _unique_values(row, evidence, "source_pass_types")
    themes = set(_as_list(graph_row.get("theme_links") or row.get("theme_links")))
    sentiment_values = [_float(e.get("sentiment"), 0.0) for e in evidence if isinstance(e, dict)]
    if not sentiment_values and "sentiment" in row:
        sentiment_values = [_float(row.get("sentiment"), 0.0)]

    no_source = bool(row.get("no_source_found")) or any(bool(e.get("no_source_found")) for e in evidence if isinstance(e, dict))
    source_quality = str(row.get("source_quality", "")).lower()
    catalyst = str(row.get("catalyst", "") or "")

    return {
        "verified_source_count": min(100.0, verified_count / 5.0 * 100.0),
        "source_diversity": min(100.0, (len(accounts) * 14.0) + (len(pass_types) * 15.0)),
        "recency": _recency_score(row, evidence, as_of_date),
        "theme_novelty": _theme_novelty_score(ticker, themes, history),
        "low_contradiction": _low_contradiction_score(sentiment_values, row, evidence),
        "source_integrity": 0.0 if no_source else (85.0 if source_quality == "cited" or catalyst else 60.0),
        "theme_leadership": _theme_leadership_score(ticker, themes, graph_row, theme_nodes),
    }


def _evidence_rows(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    evidence = row.get("evidence")
    return [e for e in evidence if isinstance(e, dict)] if isinstance(evidence, list) else []


def _verified_source_count(row: Dict[str, Any], evidence: List[Dict[str, Any]]) -> int:
    count = 0
    rows = evidence or [row]
    for item in rows:
        if bool(item.get("no_source_found")):
            continue
        if item.get("accounts_cited") or item.get("source_quality") == "cited" or item.get("catalyst"):
            count += 1
    return count


def _unique_values(row: Dict[str, Any], evidence: List[Dict[str, Any]], key: str) -> set[str]:
    vals: set[str] = set()
    for raw in _as_list(row.get(key)):
        vals.add(str(raw).strip().lower())
    for item in evidence:
        for raw in _as_list(item.get(key)):
            vals.add(str(raw).strip().lower())
    return {v for v in vals if v}


def _recency_score(row: Dict[str, Any], evidence: List[Dict[str, Any]], as_of_date: str) -> float:
    timestamps = [str(row.get("timestamp", ""))] + [str(e.get("timestamp", "")) for e in evidence]
    parsed = [_parse_dt(ts) for ts in timestamps if ts]
    parsed = [p for p in parsed if p is not None]
    if not parsed:
        return 0.0
    latest = max(parsed)
    anchor = _parse_dt(as_of_date + "T23:59:59Z") or dt.datetime.now(dt.timezone.utc)
    age_hours = max(0.0, (anchor - latest).total_seconds() / 3600.0)
    if age_hours <= 24:
        return 100.0
    if age_hours >= 96:
        return 0.0
    return round(100.0 * (1.0 - (age_hours - 24.0) / 72.0), 4)


def _theme_novelty_score(ticker: str, themes: set[str], history: Dict[str, Dict[str, float]]) -> float:
    if not themes:
        return 0.0
    prior = history.get(ticker, {})
    if not prior:
        return 85.0
    new_count = len([t for t in themes if t not in prior])
    avg_prior_age = sum(prior.get(t, 0.0) for t in themes) / max(1, len(themes))
    return max(0.0, min(100.0, 45.0 + new_count * 20.0 + avg_prior_age * 5.0))


def _low_contradiction_score(sentiments: List[float], row: Dict[str, Any], evidence: List[Dict[str, Any]]) -> float:
    texts = [str(row.get("catalyst", ""))] + [str(e.get("catalyst", "")) for e in evidence]
    text = " ".join(texts).lower()
    penalty = 0.0
    if sentiments and min(sentiments) < -0.2 and max(sentiments) > 0.2:
        penalty += 45.0
    if any(term in text for term in ("but ", "however", "mixed", "debate", "risk", "priced-for-perfection")):
        penalty += 20.0
    return max(0.0, 100.0 - penalty)


def _theme_leadership_score(ticker: str, themes: set[str], graph_row: Dict[str, Any], theme_nodes: Dict[str, Any]) -> float:
    if not themes:
        return 0.0
    evidence_count = _float(graph_row.get("evidence_count"), 0.0)
    theme_score = _float(graph_row.get("theme_emergence_score"), 0.0)
    linked_multi_ticker = 0
    for theme in themes:
        node = theme_nodes.get(theme, {}) if isinstance(theme_nodes.get(theme, {}), dict) else {}
        tickers = _as_list(node.get("tickers") or node.get("linked_tickers"))
        if len(tickers) >= 2:
            linked_multi_ticker += 1
    return max(0.0, min(100.0, theme_score * 0.55 + min(30.0, evidence_count * 5.0) + min(15.0, linked_multi_ticker * 7.5)))


def _load_prior_theme_history(*, base: Path, as_of_date: str, lookback_days: int) -> Dict[str, Dict[str, float]]:
    anchor = dt.date.fromisoformat(as_of_date)
    out: Dict[str, Dict[str, float]] = {}
    for age in range(1, lookback_days + 1):
        day = (anchor - dt.timedelta(days=age)).isoformat()
        graph = _load_json(base / day / "theme_emergence_graph.json") or {}
        for ticker, row in dict(graph.get("tickers", {}) or {}).items():
            bucket = out.setdefault(str(ticker).upper(), {})
            for theme in _as_list(row.get("theme_links")):
                bucket.setdefault(str(theme), float(age))
    return out


def _as_list(raw: Any) -> List[Any]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    return [raw]


def _float(raw: Any, default: float) -> float:
    try:
        return float(raw)
    except Exception:
        return default


def _parse_dt(raw: str) -> Optional[dt.datetime]:
    try:
        text = str(raw).replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except Exception:
        return None


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None
