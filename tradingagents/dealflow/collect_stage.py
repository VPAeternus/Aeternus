"""Collection stage orchestration for dealflow pipeline."""

from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .akg_universe import build_universe_from_akg, get_last_universe_ledger
from .akg_writeback import writeback_scores_to_akg, writeback_signals_to_akg
from .contracts import DealFlowShortlist, EventTriggerResult, ResearchQueue
from .manual_watchlist import list_active_ideas
from .ranking import rank_candidates
from .scoring import detect_needles, score_candidates
from .sources import (
    collect_insider_cluster_signals,
    collect_price_momentum_signals,
    collect_sector_rotation_signals,
    collect_social_news_signals,
)


def _load_json_file(path: Path) -> Any:
    try:
        import json
        return json.loads(path.read_text())
    except Exception:
        return None


def run_collect_stage(
    pipeline: Any,
    *,
    as_of_date: str,
    trigger: str,
    top_k: int,
    akg_available: bool,
    akg_cls: Any,
) -> Tuple[DealFlowShortlist, ResearchQueue, List[dict], EventTriggerResult]:
    # Bootstrap if discover() wasn't called
    universe = getattr(pipeline, "_last_universe", None)
    if universe is None:
        watchlist_path = pipeline._watchlist_path()
        manual_ideas = list_active_ideas(as_of_date=as_of_date, path=watchlist_path)
        manual_symbols_set = {
            str(idea.get("symbol", "")).upper().strip()
            for idea in manual_ideas
            if str(idea.get("symbol", "")).strip()
        }
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
        fvg_recall_symbols = _load_json_file(Path("eval_results") / "deal_flow" / as_of_date / "fvg_recall.json") or {}
        fma_recall_symbols = _load_json_file(Path("eval_results") / "deal_flow" / as_of_date / "fma_recall.json") or {}
        universe = build_universe_from_akg(
            extra_symbols=manual_symbols,
            config=pipeline.config,
            fvg_recall_symbols=list(fvg_recall_symbols.get("selected_symbols", []) or []),
            fma_recall_symbols=list(fma_recall_symbols.get("selected_symbols", []) or []),
        )
        pipeline._last_universe_ledger = pipeline._resolve_universe_ledger(
            universe,
            get_last_universe_ledger(),
        )
        pipeline._last_manual_ideas = manual_ideas
        pipeline._last_manual_symbols = manual_symbols
    elif not hasattr(pipeline, "_last_universe_ledger"):
        pipeline._last_universe_ledger = pipeline._resolve_universe_ledger(universe, {})

    event_state = getattr(pipeline, "_last_event_state", None)
    if event_state is None:
        event_state = pipeline._evaluate_event_trigger(as_of_date)
        if trigger == "event" and not event_state["triggered"]:
            event_state["reasons"].append("Event thresholds not met; producing snapshot anyway.")

    manual_ideas = getattr(pipeline, "_last_manual_ideas", [])

    connector_health: List[Dict[str, Any]] = []
    cashtag_events: List[Dict] = []
    signals = []

    # Parallel execution of independent connectors.
    connector_tasks = []
    connector_tasks.extend([
        ("social_news", collect_social_news_signals, (universe,), {
            "as_of_date": as_of_date,
            "max_symbol_calls": int(pipeline.config.get("dealflow_social_max_symbol_calls", 35)),
            "config": pipeline.config,
        }),
        ("price_momentum", collect_price_momentum_signals, (universe,), {}),
        ("sector_rotation", collect_sector_rotation_signals, (universe,), {}),
    ])


    if bool(pipeline.config.get("dealflow_insider_cluster_enabled", True)):
        connector_tasks.append(("insider_cluster", collect_insider_cluster_signals, (universe,), {
            "as_of_date": as_of_date,
            "config": pipeline.config,
        }))

    # Execute all connectors in parallel.
    parallel_results: Dict[str, Tuple[List[Dict], Dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {}
        for task_name, collector, args, kwargs in connector_tasks:
            future = executor.submit(pipeline._collect_connector_signals, task_name, collector, *args, **kwargs)
            futures[future] = task_name

        for future in futures:
            task_name = futures[future]
            try:
                sig_list, health = future.result()
                parallel_results[task_name] = (sig_list, health)
            except Exception as exc:
                # If a connector fails, its health entry captures the error.
                parallel_results[task_name] = ([], pipeline._build_connector_health_entry(
                    connector_name=task_name,
                    signals=[],
                    latency_ms=0.0,
                    error_message=str(exc),
                ))

    # Collect results in deterministic order and build health entries.
    for task_name, collector, args, kwargs in connector_tasks:
        if task_name in parallel_results:
            sig_list, health = parallel_results[task_name]
            connector_health.append(health)
            signals.extend(sig_list)

    # --- S-080/S-081: Write pipeline signals to AKG, then inject emergence back ---
    if akg_available and akg_cls is not None:
        try:
            _akg = akg_cls.load()

            # S-080: write pipeline signals to AKG nodes
            _n = writeback_signals_to_akg(_akg, signals, as_of_date)
            _akg.save()
            if _n:
                print(f"[pipeline] AKG signal writeback: {_n} enrichments written")

            # Inject emergence signals — closes the scout→tier→pipeline feedback loop.
            # S-081: evidence_count uses real n_signal_sources instead of hard-coded 2.
            for planet in _akg.get_emerging_planets(min_tier="ATMOSPHERE", top_k=100):
                signals.append({
                    "symbol": planet["id"],
                    "signal_family": "emergence",
                    "raw_score": round(float(planet.get("emergence_score", 0)) * 100, 2),
                    "z_score": 0.0,
                    "direction": "BEARISH" if float(planet.get("cashtag_sentiment") or 0) < -0.2 else "BULLISH",
                    "evidence_count": max(1, int(planet.get("n_signal_sources", 0))),
                    "freshness_hours": 0.0,
                    "source_status": "OK",
                    "source_name": "akg_emergence",
                })
        except Exception as exc:
            import sys as _sys
            print(f"[pipeline] AKG writeback/emergence error: {exc}", file=_sys.stderr)

    normalized_signals, candidates = score_candidates(
        universe=universe,
        signals=signals,
        min_signal_families=int(pipeline.config.get("dealflow_min_signal_families", 3)),
        min_evidence_count=5,
        momentum_lane_threshold=float(pipeline.config.get("dealflow_momentum_lane_threshold", 68.0)),
        momentum_lane_price_override_threshold=float(
            pipeline.config.get("dealflow_momentum_lane_price_override_threshold", 82.0)
        ),
        momentum_lane_social_confirmation_threshold=float(
            pipeline.config.get("dealflow_momentum_lane_social_confirmation_threshold", 60.0)
        ),
        momentum_lane_floor_ratio=float(
            pipeline.config.get("dealflow_momentum_lane_floor_ratio", 0.20)
        ),
        momentum_lane_promotion_min_score=float(
            pipeline.config.get("dealflow_momentum_lane_promotion_min_score", 62.0)
        ),
        momentum_lane_promotion_min_price_score=float(
            pipeline.config.get("dealflow_momentum_lane_promotion_min_price_score", 70.0)
        ),
    )
    # --- Needle bypass: detect extreme-signal LOW_DATA candidates ---
    needle_candidates = detect_needles(normalized_signals, candidates)
    if needle_candidates:
        iv_fq = getattr(pipeline, "_iv_force_queue", None) or []
        pipeline._iv_force_queue = iv_fq + needle_candidates
        print(f"[pipeline] Needle bypass: {len(needle_candidates)} candidates")

    # --- S-080b: Write composite scores + source provenance to AKG ---
    if akg_available and akg_cls is not None:
        try:
            _akg_scores = akg_cls.load()
            _ns = writeback_scores_to_akg(
                _akg_scores, candidates, normalized_signals, as_of_date,
            )
            _akg_scores.save()
            if _ns:
                print(f"[pipeline] AKG score writeback: {_ns} nodes updated")
        except Exception as exc:
            import sys as _sys
            print(f"[pipeline] AKG score writeback error: {exc}", file=_sys.stderr)

    symbol_source_tags = pipeline._build_symbol_source_tags(normalized_signals)
    for candidate in candidates:
        symbol = str(candidate.get("symbol", "")).upper().strip()
        candidate["source_detail"] = pipeline._infer_source_detail(
            candidate,
            explicit_tags=symbol_source_tags.get(symbol, set()),
        )
        try:
            from tradingagents.phase_engine.accel_screener import get_accel_signal
            accel = get_accel_signal(symbol)
            candidate["accel_signal"] = accel.tag
            candidate["accel_description"] = accel.description
        except Exception:
            candidate["accel_signal"] = "NEUTRAL"
            candidate["accel_description"] = ""

    ranked_auto = rank_candidates(
        candidates,
        top_k=top_k,
        max_sector_count=int(pipeline.config.get("dealflow_max_sector_count", 5)),
        core_quota=int(pipeline.config.get("dealflow_core_quota", 18)),
        momentum_quota=int(pipeline.config.get("dealflow_momentum_quota", 12)),
    )
    ranked, manual_merge = pipeline._apply_manual_merge_policy(
        ranked_auto=ranked_auto,
        candidates=candidates,
        manual_ideas=manual_ideas,
        top_k=top_k,
    )

    run_id = f"{as_of_date}-{dt.datetime.now().strftime('%H%M%S')}-{trigger}"
    shortlist: DealFlowShortlist = {
        "run_id": run_id,
        "date": as_of_date,
        "trigger": trigger,
        "top_k": top_k,
        "candidates": ranked,
        "event_triggered": event_state["triggered"],
        "event_reasons": event_state["reasons"],
        "manual_included_count": int(manual_merge.get("included", 0)),
        "manual_symbols": list(manual_merge.get("manual_symbols", [])),
        "manual_merge_summary": {
            "requested": int(manual_merge.get("requested", 0)),
            "included": int(manual_merge.get("included", 0)),
            "reinforced": int(manual_merge.get("reinforced", 0)),
            "rejected": int(manual_merge.get("rejected", 0)),
        },
    }
    shortlist["connector_health_summary"] = pipeline._summarize_connector_health(connector_health)

    research_queue = pipeline._build_research_queue(
        shortlist,
        ledger_base_dir=Path("eval_results") / "deal_flow" / as_of_date,
    )
    momentum_board = pipeline._build_momentum_board(shortlist)
    family_contribution_report = pipeline._build_family_contribution_report(shortlist)
    shortlist["family_contribution_summary"] = family_contribution_report.get("aggregate", {})
    pipeline._persist(
        as_of_date=as_of_date,
        normalized_signals=normalized_signals,
        shortlist=shortlist,
        research_queue=research_queue,
        cashtag_events=cashtag_events,
        momentum_board=momentum_board,
        connector_health=connector_health,
        family_contribution_report=family_contribution_report,
        manual_merge=manual_merge,
        all_scored_candidates=candidates,
    )

    return shortlist, research_queue, normalized_signals, event_state
