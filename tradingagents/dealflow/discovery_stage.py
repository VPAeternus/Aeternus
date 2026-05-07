"""Discovery stage orchestration for dealflow pipeline."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from .akg_universe import build_universe_from_akg, get_last_universe_ledger, get_last_universe_tier_map
from .discovery_reports import empty_discovery_delta, write_discovery_delta_report, write_theme_heatmap_report
from .manual_watchlist import list_active_ideas
from .scout_compiler import run_scout_compiler_sidecar
from .scout_quality import build_scout_quality_daily, persist_scout_quality_daily
from .sources import scan_thirteenf_watchlist
from .universe_filter import build_universe_filter_report, summarize_universe_filter


def _load_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _load_open_position_symbols() -> List[str]:
    try:
        payload = json.loads((Path("eval_results") / "paper_execution" / "positions.json").read_text())
    except Exception:
        payload = {}
    open_positions = dict(payload.get("open_positions", {}) or {})
    return sorted(
        str(symbol).upper().strip()
        for symbol, row in open_positions.items()
        if str(symbol).strip() and float(dict(row or {}).get("quantity", 0.0) or 0.0) > 0
    )


def run_discovery_stage(
    pipeline: Any,
    *,
    as_of_date: str,
    trigger: str,
    akg_available: bool,
    akg_cls: Any,
) -> Dict[str, Any]:
    event_state = pipeline._evaluate_event_trigger(as_of_date)
    if trigger == "event" and not event_state["triggered"]:
        event_state["reasons"].append("Event thresholds not met; producing snapshot anyway.")

    watchlist_path = pipeline._watchlist_path()
    manual_ideas = list_active_ideas(as_of_date=as_of_date, path=watchlist_path)
    manual_symbols_set = {
        str(idea.get("symbol", "")).upper().strip()
        for idea in manual_ideas
        if str(idea.get("symbol", "")).strip()
    }
    x_feed_merged: Dict[str, Any] = {}
    technical_ignition_result: Dict[str, Any] = {}

    # Include x-feed social tickers in universe
    try:
        from tradingagents.dealflow.sources.x_feed_manual import load_recent_merged
        x_feed_merged = load_recent_merged(
            as_of_date,
            lookback_days=int(pipeline.config.get("dealflow_manual_x_feed_carryforward_days", 0)),
        )
        if x_feed_merged:
            manual_symbols_set |= set(x_feed_merged.keys())
    except Exception:
        pass

    manual_symbols = sorted(manual_symbols_set)
    fvg_recall = pipeline._build_fvg_recall_channel(as_of_date=as_of_date)
    fvg_recall_symbols = list(fvg_recall.get("selected_symbols", []))
    fvg_recall_artifact = dict(fvg_recall.get("artifact", {}) or {})
    fma_recall = pipeline._build_fma_recall_channel(as_of_date=as_of_date)
    fma_recall_symbols = list(fma_recall.get("selected_symbols", []))
    fma_recall_artifact = dict(fma_recall.get("artifact", {}) or {})
    out_dir = Path("eval_results") / "deal_flow" / as_of_date
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "fvg_recall.json").write_text(json.dumps(fvg_recall_artifact, indent=2))
    (out_dir / "fma_recall.json").write_text(json.dumps(fma_recall_artifact, indent=2))

    # --- Pre-connector scouts (write to AKG BEFORE universe is built) ---
    _breakout_result: Dict[str, Any] = {}
    _insider_result: Dict[str, Any] = {}
    breakout_count = 0
    try:
        from tradingagents.dealflow.sources.breakout_scanner import scan_breakout_discovery
        _breakout_result = scan_breakout_discovery(trade_date=as_of_date)
        breakout_count = _breakout_result.get("count", 0)
        if breakout_count:
            print(f"[pipeline] breakout discovery: {breakout_count} symbols advanced in AKG")
    except Exception as exc:
        import sys as _sys
        print(f"[pipeline] breakout discovery error: {exc}", file=_sys.stderr)

    _iv_results: Dict[str, Any] = {"force_queue": [], "akg_enriched": []}
    iv_count = 0
    pipeline._iv_force_queue = []

    insider_summary: Dict[str, Any] = {}
    try:
        from tradingagents.dealflow.sources.insider_cluster import scan_insider_sweep
        _insider_akg = akg_cls.load() if akg_available and akg_cls is not None else None
        _insider_result = scan_insider_sweep(
            sweep_date=as_of_date,
            window_days=int(pipeline.config.get("dealflow_insider_sweep_window_days", 30)),
            config=pipeline.config,
            akg=_insider_akg,
        )
        if _insider_akg is not None and not _insider_result.get("skipped"):
            _insider_akg.save()
        if not _insider_result.get("skipped"):
            _new = _insider_result.get("new_transactions", 0)
            _buys = len(_insider_result.get("buy_clusters", []))
            _sells = len(_insider_result.get("sell_clusters", []))
            insider_summary = {"new_txns": _new, "buy_clusters": _buys, "sell_clusters": _sells}
            print(f"[pipeline] insider sweep: {_new} new txns, {_buys} buy clusters, {_sells} sell clusters")
    except Exception as exc:
        import sys as _sys
        print(f"[pipeline] insider sweep error: {exc}", file=_sys.stderr)

    technical_ignition_symbols: List[str] = []
    if bool(pipeline.config.get("dealflow_technical_ignition_enabled", True)):
        try:
            from tradingagents.dealflow.sources.technical_ignition_scout import scan_technical_ignition_setups
            technical_ignition_result = scan_technical_ignition_setups(
                as_of_date=as_of_date,
                db_path=pipeline.config.get("dealflow_technical_signal_db_path"),
            )
            technical_ignition_symbols = list(technical_ignition_result.get("promoted_symbols", []) or [])
            if technical_ignition_symbols:
                print(
                    f"[pipeline] technical ignition scout: {len(technical_ignition_symbols)} promoted "
                    f"({', '.join(technical_ignition_symbols[:5])})"
                )
        except Exception as exc:
            import sys as _sys
            print(f"[pipeline] technical ignition scout error: {exc}", file=_sys.stderr)

    thirteenf_result: Dict[str, Any] = {}
    thirteenf_symbols: List[str] = []
    if bool(pipeline.config.get("dealflow_thirteenf_watchlist_enabled", True)):
        try:
            thirteenf_result = scan_thirteenf_watchlist(
                as_of_date=as_of_date,
                max_filings_per_manager=int(pipeline.config.get("dealflow_thirteenf_max_filings_per_manager", 6)),
                min_value_usd=float(pipeline.config.get("dealflow_thirteenf_min_value_usd", 10_000_000.0)),
            )
            thirteenf_symbols = list(thirteenf_result.get("symbols", []) or [])
            if thirteenf_symbols:
                print(
                    f"[pipeline] 13F watchlist scout: {len(thirteenf_symbols)} symbols "
                    f"({', '.join(thirteenf_symbols[:5])})"
                )
        except Exception as exc:
            import sys as _sys
            print(f"[pipeline] 13F watchlist scout error: {exc}", file=_sys.stderr)

    # --- Build universe AFTER scouts have updated AKG ---
    universe_kwargs = {
        "extra_symbols": sorted(set(manual_symbols) | set(thirteenf_symbols)),
        "fvg_recall_symbols": fvg_recall_symbols,
        "fma_recall_symbols": fma_recall_symbols,
        "config": pipeline.config,
    }
    if technical_ignition_symbols:
        universe_kwargs["technical_ignition_symbols"] = technical_ignition_symbols
    universe = build_universe_from_akg(**universe_kwargs)

    tier_map = get_last_universe_tier_map()
    if tier_map:
        from collections import Counter
        tier_counts = Counter(tier_map.values())
        print(f"[pipeline] filtered universe: {len(universe)} symbols "
              f"(T1={tier_counts.get('T1_ANCHOR', 0)} T2={tier_counts.get('T2_NEIGHBOR', 0)} "
              f"T3={tier_counts.get('T3_SCOUT', 0)} T3D={tier_counts.get('T3D_TECHNICAL_IGNITION', 0)} "
              f"T4={tier_counts.get('T4_DARK', 0)} MANUAL={tier_counts.get('MANUAL', 0)})")

    # Store results for collect() to consume
    pipeline._last_universe = universe
    pipeline._last_universe_ledger = pipeline._resolve_universe_ledger(
        universe,
        get_last_universe_ledger(),
    )
    pipeline._last_event_state = event_state
    pipeline._last_manual_symbols = manual_symbols
    pipeline._last_manual_ideas = manual_ideas
    pipeline._last_fvg_recall = fvg_recall
    pipeline._last_fma_recall = fma_recall

    # Scout audit — persist what scouts found for backtesting
    try:
        scout_audit = pipeline._build_scout_audit(
            as_of_date,
            _breakout_result,
            _iv_results,
            _insider_result,
            technical_ignition_result,
            thirteenf_result,
        )
    except Exception:
        scout_audit = {}
    try:
        universe_filter_report = build_universe_filter_report(
            as_of_date=as_of_date,
            universe=universe,
            tier_map=dict(tier_map or {}),
            universe_ledger=dict(pipeline._last_universe_ledger or {}),
            manual_symbols=manual_symbols,
            x_feed_merged_symbols=list(dict(x_feed_merged or {}).keys()),
            scout_audit=scout_audit,
            fvg_recall=fvg_recall_artifact,
            fma_recall=fma_recall_artifact,
        )
        universe_filter_summary = summarize_universe_filter(universe_filter_report)
        (out_dir / "universe_filter.json").write_text(json.dumps(universe_filter_report, indent=2))
    except Exception:
        universe_filter_report = {}
        universe_filter_summary = {}
    pipeline._last_universe_filter = universe_filter_report
    pipeline._last_universe_filter_summary = universe_filter_summary

    try:
        _heatmap_akg = akg_cls.load() if akg_available and akg_cls is not None else None
        write_theme_heatmap_report(_heatmap_akg, as_of_date=as_of_date)
    except Exception:
        pass

    try:
        discovery_delta = write_discovery_delta_report(
            as_of_date=as_of_date,
            out_dir=out_dir,
            scout_audit=scout_audit,
            fvg_recall=fvg_recall_artifact,
            fma_recall=fma_recall_artifact,
        )
    except Exception:
        discovery_delta = empty_discovery_delta()
    pipeline._last_discovery_delta = discovery_delta

    scenario_sidecar_summary: Dict[str, Any] = {
        "event_card_count": 0,
        "complete_count": 0,
        "partial_count": 0,
        "missing_count": 0,
        "writeback_candidate_count": 0,
    }
    try:
        scenario_sidecar_summary = run_scout_compiler_sidecar(
            as_of_date=as_of_date,
            scout_audit=scout_audit,
            discovery_delta=discovery_delta,
            universe_filter=universe_filter_report or {"symbols": [str(row.get("symbol", "")).upper().strip() for row in universe]},
            x_feed_merged=x_feed_merged,
            macro_cache={},
            holdings=_load_open_position_symbols(),
        )
    except Exception:
        scenario_sidecar_summary = {
            "event_card_count": 0,
            "complete_count": 0,
            "partial_count": 0,
            "missing_count": 0,
            "writeback_candidate_count": 0,
            "error": "sidecar_failed",
        }
    pipeline._last_scenario_sidecar_summary = scenario_sidecar_summary
    scout_quality_summary: Dict[str, Any] = {"row_count": 0}
    try:
        sidecar_base = Path("eval_results") / "deal_flow" / as_of_date
        event_cards = _load_json_file(sidecar_base / "event_cards.json") or []
        coverage_precheck = _load_json_file(sidecar_base / "coverage_precheck.json") or {}
        scout_quality_payload = build_scout_quality_daily(
            as_of_date=as_of_date,
            scout_audit=scout_audit,
            event_cards=event_cards,
            coverage_precheck=coverage_precheck,
        )
        scout_quality_summary = persist_scout_quality_daily(
            as_of_date=as_of_date,
            payload=scout_quality_payload,
        )
    except Exception:
        scout_quality_summary = {"row_count": 0, "error": "scout_quality_failed"}
    pipeline._last_scout_quality_summary = scout_quality_summary

    return {
        "universe_size": len(universe),
        "breakout_count": breakout_count,
        "iv_force_queue_count": iv_count,
        "technical_ignition_count": len(technical_ignition_symbols),
        "technical_ignition_symbols": technical_ignition_symbols,
        "insider_summary": insider_summary,
        "manual_symbols": manual_symbols,
        "fvg_recall_symbols": fvg_recall_symbols,
        "fma_recall_symbols": fma_recall_symbols,
        "universe_filter": universe_filter_summary,
        "universe_filter_summary": universe_filter_summary,
        "discovery_delta": discovery_delta,
        "discovery_delta_summary": dict(discovery_delta.get("coverage_summary", {})),
        "scenario_sidecar_summary": scenario_sidecar_summary,
        "scout_quality_summary": scout_quality_summary,
        "event_state": event_state,
    }
