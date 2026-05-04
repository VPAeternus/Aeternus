"""Read-only first-universe filter reporting and health checks."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Set


def build_universe_filter_report(
    *,
    as_of_date: str,
    universe: Sequence[Dict[str, Any]],
    tier_map: Dict[str, str],
    universe_ledger: Dict[str, Any],
    manual_symbols: Sequence[str],
    x_feed_merged_symbols: Sequence[str],
    scout_audit: Dict[str, Any],
    fvg_recall: Dict[str, Any],
    fma_recall: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a read-only first-universe filter audit report."""
    kept_symbols = _normalize_symbols([row.get("symbol") for row in universe])
    tier_counts = dict(Counter(tier_map.values()))
    manual_set = set(_normalize_symbols(manual_symbols))
    x_feed_set = set(_normalize_symbols(x_feed_merged_symbols))
    fvg_set = set(_normalize_symbols((fvg_recall or {}).get("selected_symbols", [])))
    fma_set = set(_normalize_symbols((fma_recall or {}).get("selected_symbols", [])))
    technical_set = fvg_set | fma_set
    scout_sets = _extract_scout_sets(scout_audit)
    scout_symbol_set = scout_sets["all"]

    source_counts = {
        "manual_symbols": len(manual_set),
        "x_feed_merged_symbols": len(x_feed_set),
        "breakout_alerts": len(scout_sets["breakout"]),
        "iv_force_queue": len(scout_sets["iv"]),
        "insider_buy_clusters": len(scout_sets["insider_buy"]),
        "insider_sell_clusters": len(scout_sets["insider_sell"]),
        "scout_signal_symbols": len(scout_sets["signal_symbols"]),
        "fvg_recall_selected": len(fvg_set),
        "fma_recall_selected": len(fma_set),
    }

    overlap_counts = {
        "fvg_fma_overlap": len(fvg_set & fma_set),
        "manual_technical_overlap": len(manual_set & technical_set),
        "scout_technical_overlap": len(scout_symbol_set & technical_set),
    }

    health_checks = _build_health_checks(
        universe_size=len(kept_symbols),
        tier_counts=tier_counts,
        x_feed_count=len(x_feed_set),
        technical_count=len(technical_set),
        scout_activity_count=(
            len(scout_sets["breakout"])
            + len(scout_sets["iv"])
            + len(scout_sets["insider_buy"])
            + len(scout_sets["insider_sell"])
            + len(scout_sets["signal_symbols"])
        ),
    )

    return {
        "as_of_date": as_of_date,
        "universe_size": len(kept_symbols),
        "kept_symbols_count": len(kept_symbols),
        "tier_counts": tier_counts,
        "source_counts": source_counts,
        "overlap_counts": overlap_counts,
        "health_checks": health_checks,
        "overall_ready": all(bool(check.get("pass")) for check in health_checks.values()),
        "rule_snapshot": dict((universe_ledger or {}).get("rule_snapshot", {})),
        "sample_symbols": {
            "kept": kept_symbols[:10],
            "manual": sorted(manual_set)[:10],
            "scout": sorted(scout_symbol_set)[:10],
            "technical": sorted(technical_set)[:10],
        },
        "artifact_paths": {
            "x_feed_merged": str(
                Path("eval_results") / "x_feed" / as_of_date / "merged.json"
            ),
            "scout_audit": str(
                Path("eval_results") / "deal_flow" / as_of_date / "scout_audit.json"
            ),
            "fvg_recall": str(
                Path("eval_results") / "deal_flow" / as_of_date / "fvg_recall.json"
            ),
            "fma_recall": str(
                Path("eval_results") / "deal_flow" / as_of_date / "fma_recall.json"
            ),
        },
    }


def summarize_universe_filter(report: Dict[str, Any]) -> Dict[str, Any]:
    """Return a compact summary for CLI rendering and pipeline payloads."""
    payload = dict(report or {})
    return {
        "universe_size": int(payload.get("universe_size", 0) or 0),
        "tier_counts": dict(payload.get("tier_counts") or {}),
        "source_counts": dict(payload.get("source_counts") or {}),
        "overlap_counts": dict(payload.get("overlap_counts") or {}),
        "health_checks": dict(payload.get("health_checks") or {}),
        "overall_ready": bool(payload.get("overall_ready")),
    }


def load_universe_filter_report(as_of_date: str) -> Dict[str, Any]:
    """Load a persisted universe filter report for a given date."""
    path = (
        Path("eval_results") / "deal_flow" / as_of_date / "universe_filter.json"
    )
    if not path.exists():
        raise FileNotFoundError(f"Universe filter artifact not found: {path}")
    import json

    return json.loads(path.read_text())


def _build_health_checks(
    *,
    universe_size: int,
    tier_counts: Dict[str, int],
    x_feed_count: int,
    technical_count: int,
    scout_activity_count: int,
) -> Dict[str, Dict[str, Any]]:
    return {
        "universe_nonzero": {
            "pass": universe_size > 0,
            "observed": universe_size,
            "required": ">0",
        },
        "tier_diversity_ok": {
            "pass": len([name for name, count in tier_counts.items() if int(count or 0) > 0]) >= 2,
            "observed": len([name for name, count in tier_counts.items() if int(count or 0) > 0]),
            "required": ">=2",
        },
        "technical_recall_present": {
            "pass": technical_count > 0,
            "observed": technical_count,
            "required": ">0",
        },
        "manual_xfeed_present": {
            "pass": x_feed_count > 0,
            "observed": x_feed_count,
            "required": ">0",
        },
        "scout_activity_present": {
            "pass": scout_activity_count > 0,
            "observed": scout_activity_count,
            "required": ">0",
        },
    }


def _extract_scout_sets(scout_audit: Dict[str, Any]) -> Dict[str, Set[str]]:
    payload = dict(scout_audit or {})
    breakout = {
        _normalize_symbol(row.get("ticker"))
        for row in list((payload.get("breakout") or {}).get("alerts") or [])
        if _normalize_symbol(row.get("ticker"))
    }
    iv_force_queue = {
        _normalize_symbol(symbol)
        for symbol in list((payload.get("iv") or {}).get("force_queue") or [])
        if _normalize_symbol(symbol)
    }
    insider_buy = {
        _normalize_symbol(row.get("ticker"))
        for row in list((payload.get("insider") or {}).get("buy_clusters") or [])
        if _normalize_symbol(row.get("ticker"))
    }
    insider_sell = {
        _normalize_symbol(row.get("ticker"))
        for row in list((payload.get("insider") or {}).get("sell_clusters") or [])
        if _normalize_symbol(row.get("ticker"))
    }
    signal_symbols = {
        _normalize_symbol(row.get("symbol"))
        for row in list(payload.get("signals") or [])
        if _normalize_symbol(row.get("symbol"))
    }
    return {
        "breakout": breakout,
        "iv": iv_force_queue,
        "insider_buy": insider_buy,
        "insider_sell": insider_sell,
        "signal_symbols": signal_symbols,
        "all": breakout | iv_force_queue | insider_buy | insider_sell | signal_symbols,
    }


def _normalize_symbol(raw: Any) -> str:
    symbol = str(raw or "").upper().strip()
    if symbol.startswith("$"):
        symbol = symbol[1:]
    return symbol.replace(".", "-")


def _normalize_symbols(values: Iterable[Any]) -> List[str]:
    seen: Set[str] = set()
    normalized: List[str] = []
    for raw in values:
        symbol = _normalize_symbol(raw)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(symbol)
    return normalized
