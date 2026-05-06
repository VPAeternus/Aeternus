"""Collect-stage artifact persistence for DealFlowPipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from tradingagents.dealflow.deep_selection_integrity import build_deep_selection_integrity_report
from tradingagents.dealflow.evidence_integrity import build_evidence_integrity_report, summarize_evidence_integrity
from tradingagents.dealflow.shortlist_integrity import build_shortlist_integrity_report


def write_collect_artifacts(
    *,
    as_of_date: str,
    normalized_signals: List[Dict],
    shortlist: Dict[str, Any],
    research_queue: Dict[str, Any],
    cashtag_events: List[Dict],
    momentum_board: Dict[str, object],
    connector_health: List[Dict[str, Any]],
    family_contribution_report: Dict[str, Any],
    manual_merge: Dict[str, Any],
    all_scored_candidates: Optional[List[Dict]] = None,
    deal_flow_root: Path | str = Path("eval_results") / "deal_flow",
    x_feed_root: Path | str = Path("eval_results") / "x_feed",
) -> None:
    """Persist collect-stage JSON artifacts and optional X-feed provenance."""
    root = Path(deal_flow_root)
    base = root / as_of_date
    base.mkdir(parents=True, exist_ok=True)

    (base / "signals_raw.json").write_text(json.dumps(normalized_signals, indent=2))
    (base / "connector_health.json").write_text(json.dumps(connector_health, indent=2))
    (base / "family_contributions.json").write_text(json.dumps(family_contribution_report, indent=2))
    (base / "cashtag_events.json").write_text(json.dumps(cashtag_events, indent=2))
    (base / "momentum_board.json").write_text(json.dumps(momentum_board, indent=2))
    (base / "manual_merge.json").write_text(json.dumps(manual_merge, indent=2))
    (base / "shortlist_top20.json").write_text(json.dumps(shortlist, indent=2))
    (base / "research_queue.json").write_text(json.dumps(research_queue, indent=2))

    scored_slim = []
    if all_scored_candidates:
        shortlist_syms = {str(c.get("symbol", "")).upper() for c in shortlist.get("candidates", [])}
        for c in sorted(all_scored_candidates, key=lambda x: -_safe_float(x.get("momentum_score", 0))):
            scored_slim.append({
                "symbol": c.get("symbol"),
                "lane": c.get("lane"),
                "status": c.get("status"),
                "core_score": c.get("core_score"),
                "momentum_score": c.get("momentum_score"),
                "asymmetry_score": c.get("asymmetry_score"),
                "active_families": c.get("active_families"),
                "evidence_count": c.get("evidence_count"),
                "sector": c.get("sector"),
                "in_shortlist": str(c.get("symbol", "")).upper() in shortlist_syms,
            })
    (base / "all_scored_candidates.json").write_text(json.dumps(scored_slim, indent=2))

    latest_path = root / "latest_research_queue.json"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(json.dumps(research_queue, indent=2))

    _write_integrity_artifacts(
        as_of_date=as_of_date,
        base=base,
        normalized_signals=normalized_signals,
        shortlist=shortlist,
        research_queue=research_queue,
        connector_health=connector_health,
        all_scored_candidates=list(all_scored_candidates or []),
    )
    (base / "shortlist_top20.json").write_text(json.dumps(shortlist, indent=2))
    _write_x_feed_provenance(
        as_of_date=as_of_date,
        base=base,
        x_feed_root=Path(x_feed_root),
        shortlist=shortlist,
    )


def _write_integrity_artifacts(*, as_of_date: str, base: Path, normalized_signals: List[Dict], shortlist: Dict[str, Any], research_queue: Dict[str, Any], connector_health: List[Dict[str, Any]], all_scored_candidates: List[Dict[str, Any]]) -> None:
    try:
        evidence = build_evidence_integrity_report(
            candidates=all_scored_candidates,
            signals=normalized_signals,
            connector_health=connector_health,
            rule_snapshot={"min_signal_families": 3, "min_evidence_count": 5},
        )
        (base / "evidence_integrity.json").write_text(json.dumps(evidence, indent=2))
        shortlist["evidence_integrity_summary"] = summarize_evidence_integrity(evidence)
    except Exception:
        pass
    try:
        report = build_shortlist_integrity_report(
            as_of_date=as_of_date,
            all_scored_candidates=all_scored_candidates,
            shortlist=shortlist,
            research_queue=research_queue,
        )
        (base / "shortlist_integrity.json").write_text(json.dumps(report, indent=2))
    except Exception:
        pass
    try:
        report = build_deep_selection_integrity_report(
            as_of_date=as_of_date,
            shortlist=shortlist,
            research_queue=research_queue,
        )
        (base / "deep_selection_integrity.json").write_text(json.dumps(report, indent=2))
    except Exception:
        pass
    shadows = [row for row in normalized_signals if str(row.get("signal_family", "")) == "fundamental_factor_shadow"]
    if shadows:
        selected_symbols = {
            str(item.get("symbol", "")).upper().strip()
            for item in research_queue.get("items", [])
            if item.get("selected_for_deep")
        }
        shadow_symbols = {str(row.get("symbol", "")).upper().strip() for row in shadows}
        strategy_name = ""
        source_name = str(shadows[0].get("source_name", "")) if shadows else ""
        if ":" in source_name:
            strategy_name = source_name.split(":", 1)[1]
        payload = {
            "strategy_name": strategy_name,
            "coverage_summary": {
                "signal_count": len(shadows),
                "selected_for_deep_overlap_count": len(selected_symbols & shadow_symbols),
            },
            "signals": shadows,
        }
        shortlist["fundamental_shadow_summary"] = {"coverage_summary": dict(payload["coverage_summary"])}
        (base / "fundamental_factor_shadow.json").write_text(json.dumps(payload, indent=2))


def _safe_float(raw: Any) -> float:
    try:
        return float(raw)
    except Exception:
        return 0.0


def _write_x_feed_provenance(*, as_of_date: str, base: Path, x_feed_root: Path, shortlist: Dict[str, Any]) -> None:
    grok_cache_path = x_feed_root / as_of_date / "merged.json"
    if not grok_cache_path.is_file():
        return
    try:
        grok_data = json.loads(grok_cache_path.read_text())
        candidate_map = {str(c.get("symbol", "")).upper(): c for c in shortlist.get("candidates", [])}
        provenance_tickers = []
        for sym, grok_fields in grok_data.items():
            cand = candidate_map.get(sym)
            provenance_tickers.append({
                "symbol": sym,
                "grok_sentiment": grok_fields.get("sentiment"),
                "grok_mentions_estimate": grok_fields.get("mentions_estimate"),
                "grok_catalyst": grok_fields.get("catalyst"),
                "grok_velocity_trend": grok_fields.get("velocity_trend"),
                "grok_pass_number": grok_fields.get("pass_number"),
                "grok_source_pass_type": grok_fields.get("source_pass_type"),
                "in_shortlist": cand is not None,
                "pipeline_rank": cand.get("rank") if cand else None,
                "pipeline_lane": cand.get("lane") if cand else None,
                "pipeline_core_score": cand.get("core_score") if cand else None,
                "pipeline_momentum_score": cand.get("momentum_score") if cand else None,
                "pipeline_asymmetry_score": cand.get("asymmetry_score") if cand else None,
            })
        provenance = {
            "date": as_of_date,
            "source": "grok_manual_deep_research",
            "tickers_ingested": len(grok_data),
            "tickers_in_shortlist": sum(1 for t in provenance_tickers if t["in_shortlist"]),
            "tickers": provenance_tickers,
        }
        (base / "grok_provenance.json").write_text(json.dumps(provenance, indent=2))
    except Exception:
        pass
