"""Weekly X account discovery from deal-flow artifacts."""

from __future__ import annotations

import datetime as dt
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


def run_x_account_discovery(
    as_of_date: str,
    config: Dict[str, Any],
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    root = Path(base_dir or Path("eval_results") / "deal_flow")
    as_of = _parse_date(as_of_date) or dt.datetime.now().date()
    lookback_days = int(config.get("dealflow_x_tuner_lookback_days", 30))
    seed_handles = _parse_handles(config.get("dealflow_x_influencer_handles", ""))
    seed_set = set(seed_handles)

    events = _load_recent_events(root=root, as_of=as_of, lookback_days=max(7, lookback_days))
    symbol_edge_map = _load_symbol_edge_map(root=root, as_of=as_of, lookback_days=max(7, lookback_days))

    author_rows: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "posts": 0,
            "engagement_total": 0.0,
            "cashtag_hits": 0,
            "symbols": set(),
            "urls": [],
        }
    )
    for event in events:
        author = str(event.get("author") or "").strip().lstrip("@")
        if not author:
            continue
        cashtags = list(event.get("cashtags") or [])
        row = author_rows[author]
        row["posts"] += 1
        row["engagement_total"] += float(event.get("engagement", 0.0) or 0.0)
        row["cashtag_hits"] += len(cashtags)
        row["symbols"].update(str(sym).upper().strip() for sym in cashtags if str(sym).strip())
        url = str(event.get("url") or "").strip()
        if url and len(row["urls"]) < 5:
            row["urls"].append(url)

    min_quality = float(config.get("dealflow_x_discovery_min_quality", 55))
    min_posts = int(config.get("dealflow_x_discovery_min_posts", 3))
    max_accounts = int(config.get("dealflow_x_discovery_max_new_accounts", 25))

    candidates: List[Dict[str, Any]] = []
    for author, row in author_rows.items():
        posts = int(row["posts"])
        if posts < min_posts:
            continue
        if author in seed_set:
            continue

        avg_engagement = float(row["engagement_total"]) / float(max(1, posts))
        cashtag_yield = float(row["cashtag_hits"]) / float(max(1, posts))
        quality = _quality_score(avg_engagement=avg_engagement, posts=posts)
        if quality < min_quality:
            continue

        symbol_edges = [
            float(symbol_edge_map[sym])
            for sym in sorted(row["symbols"])
            if sym in symbol_edge_map
        ]
        downstream_edge = (
            round(sum(symbol_edges) / float(len(symbol_edges)), 4) if symbol_edges else None
        )
        edge_score = 50.0
        if downstream_edge is not None:
            edge_score = _clamp(50.0 + 8.0 * float(downstream_edge), 0.0, 100.0)

        yield_score = _clamp(100.0 * cashtag_yield, 0.0, 100.0)
        composite = round(0.55 * quality + 0.25 * yield_score + 0.20 * edge_score, 4)
        candidates.append(
            {
                "handle": author,
                "posts": posts,
                "avg_engagement": round(avg_engagement, 4),
                "quality_score": round(quality, 4),
                "cashtag_yield": round(cashtag_yield, 4),
                "downstream_edge_pct": downstream_edge,
                "composite_score": composite,
                "sample_urls": list(row["urls"]),
                "symbols": sorted(row["symbols"]),
            }
        )

    candidates.sort(
        key=lambda row: (
            -float(row.get("composite_score", 0.0)),
            -float(row.get("quality_score", 0.0)),
            -float(row.get("posts", 0)),
            str(row.get("handle", "")),
        )
    )
    candidates = candidates[: max(0, max_accounts)]

    payload = {
        "as_of_date": as_of.isoformat(),
        "lookback_days": int(max(7, lookback_days)),
        "seed_handle_count": len(seed_handles),
        "events_analyzed": len(events),
        "symbol_edge_coverage": len(symbol_edge_map),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "candidates": candidates,
    }
    return payload


def persist_x_account_candidates(
    payload: Dict[str, Any],
    as_of_date: str,
    base_dir: Optional[Path] = None,
) -> Path:
    root = Path(base_dir or Path("eval_results") / "deal_flow")
    dated = root / str(as_of_date)
    dated.mkdir(parents=True, exist_ok=True)
    out_path = dated / "x_account_candidates.json"
    out_path.write_text(json.dumps(payload, indent=2))
    return out_path


def _load_recent_events(root: Path, as_of: dt.date, lookback_days: int) -> List[Dict[str, Any]]:
    floor = as_of - dt.timedelta(days=max(0, lookback_days))
    rows: List[Dict[str, Any]] = []
    if not root.exists():
        return rows

    for date_dir in sorted(root.iterdir()):
        if not date_dir.is_dir():
            continue
        day = _parse_date(date_dir.name)
        if day is None or day < floor or day > as_of:
            continue
        path = date_dir / "cashtag_events.json"
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text())
        except Exception:
            continue
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    rows.append(item)
    return rows


def _load_symbol_edge_map(root: Path, as_of: dt.date, lookback_days: int) -> Dict[str, float]:
    floor = as_of - dt.timedelta(days=max(0, lookback_days))
    edge_rows: Dict[str, List[float]] = defaultdict(list)
    if not root.exists():
        return {}

    for date_dir in sorted(root.iterdir()):
        if not date_dir.is_dir():
            continue
        day = _parse_date(date_dir.name)
        if day is None or day < floor or day > as_of:
            continue
        path = date_dir / "batch_analyze_latest.json"
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text())
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        for item in payload.get("items", []):
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol", "")).upper().strip()
            if not symbol:
                continue
            hz = item.get("realized_horizons", {})
            if not isinstance(hz, dict):
                continue
            block20 = hz.get("20d") if isinstance(hz.get("20d"), dict) else None
            block5 = hz.get("5d") if isinstance(hz.get("5d"), dict) else None
            block = None
            if block20 and str(block20.get("status")) == "READY":
                block = block20
            elif block5 and str(block5.get("status")) == "READY":
                block = block5
            if not block:
                continue
            edge = block.get("strategy_edge_vs_benchmark_pct")
            if isinstance(edge, (int, float)):
                edge_rows[symbol].append(float(edge))

    out: Dict[str, float] = {}
    for symbol, vals in edge_rows.items():
        if vals:
            out[symbol] = round(sum(vals) / float(len(vals)), 4)
    return out


def _parse_handles(raw: Any) -> List[str]:
    if isinstance(raw, str):
        parts = [p.strip().lstrip("@") for p in raw.split(",")]
    elif isinstance(raw, (list, tuple, set)):
        parts = [str(p).strip().lstrip("@") for p in raw]
    else:
        parts = []
    seen: Set[str] = set()
    out: List[str] = []
    for part in parts:
        if not part or part in seen:
            continue
        seen.add(part)
        out.append(part)
    return out


def _quality_score(avg_engagement: float, posts: int) -> float:
    # Engagement-adjusted quality score bounded to [0, 100].
    engagement_component = min(75.0, math.log1p(max(0.0, avg_engagement)) * 12.0)
    post_component = min(25.0, math.log1p(max(0, posts)) * 8.0)
    return _clamp(engagement_component + post_component, 0.0, 100.0)


def _parse_date(raw: Any) -> Optional[dt.date]:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return dt.datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))

