"""Scout audit report builder/persistence."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, Optional


def build_and_write_scout_audit(
    *,
    as_of_date: str,
    breakout_result: Dict[str, Any],
    iv_result: Dict[str, Any],
    insider_result: Dict[str, Any],
    technical_ignition_result: Optional[Dict[str, Any]] = None,
    thirteenf_result: Optional[Dict[str, Any]] = None,
    out_root: Path | str = Path("eval_results") / "deal_flow",
) -> Dict[str, Any]:
    """Build and persist compact daily scout audit for backtesting."""
    technical_ignition_payload = dict(technical_ignition_result or {})
    thirteenf_payload = dict(thirteenf_result or {})
    combined_signals = list(technical_ignition_payload.get("signals", []) or [])
    audit: Dict[str, Any] = {
        "date": as_of_date,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "breakout": {
            "count": len(breakout_result.get("alerts", [])),
            "alerts": [
                {"ticker": a["ticker"], "score": a.get("score"), "near_high": round(a.get("near_high", 0), 4)}
                for a in breakout_result.get("alerts", [])
            ],
        },
        "iv": {
            "force_queue": [e.get("ticker") for e in iv_result.get("force_queue", [])],
            "akg_enriched": iv_result.get("akg_enriched", []),
        },
        "insider": {
            "buy_clusters": [
                {"ticker": c.get("ticker"), "score": c.get("cluster_score"), "distinct_insiders": c.get("distinct_insiders")}
                for c in insider_result.get("buy_clusters", [])
            ],
            "sell_clusters": [
                {"ticker": c.get("ticker"), "score": c.get("cluster_score"), "distinct_insiders": c.get("distinct_insiders")}
                for c in insider_result.get("sell_clusters", [])
            ],
        },
        "technical_ignition": {
            "promoted_count": int(technical_ignition_payload.get("promoted_count", 0) or 0),
            "promoted_symbols": list(technical_ignition_payload.get("promoted_symbols", []) or []),
            "promoted": list(technical_ignition_payload.get("promoted", []) or []),
            "stale_count": int(technical_ignition_payload.get("stale_count", 0) or 0),
            "stale_symbols": list(technical_ignition_payload.get("stale_symbols", []) or []),
            "stale": list(technical_ignition_payload.get("stale", []) or []),
        },
        "thirteenf_watchlist": {
            "candidate_count": int(thirteenf_payload.get("candidate_count", 0) or 0),
            "symbols": list(thirteenf_payload.get("symbols", []) or []),
            "candidates": list(thirteenf_payload.get("candidates", []) or []),
            "policy_id": thirteenf_payload.get("policy_id", ""),
        },
        "signals": combined_signals,
    }
    audit = json.loads(json.dumps(audit, default=str))
    out_dir = Path(out_root) / as_of_date
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "scout_audit.json").write_text(json.dumps(audit, indent=2))
    return audit
