"""Deal Flow Intelligence orchestration pipeline."""

from __future__ import annotations

import datetime as dt
import contextlib
import io
import json
import time
from statistics import median
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import yfinance as yf

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.context import get_event_state

from .contracts import DealFlowShortlist, EventTriggerResult, ResearchQueue, ResearchQueueItem
from .hypothesis_ledger import append_ledger_row, make_ledger_row
from .manual_watchlist import list_active_ideas, validate_symbol_liquidity
from .negative_constraints import check_symbol_theme_suppression
from .ranking import rank_candidates
from .scoring import CORE_SCORE_WEIGHTS, detect_needles, score_candidates
from .sources import (
    collect_price_momentum_signals,
    collect_sector_rotation_signals,
    collect_smart_money_signals,
    collect_social_news_signals,
    collect_insider_cluster_signals,
    scan_breakout_discovery,
    scan_thirteenf_watchlist,
)
from .themes import select_research_playbook, why_now_text
from .akg_universe import (
    build_universe_from_akg,
    get_last_universe_ledger,
    get_last_universe_tier_map,
)
from .discovery_delta import build_discovery_delta
from .fma_recall import _build_fma_feature_frame, score_fma_cross_section
from .fvg_recall import _build_feature_frame, _extract_ohlcv_frame
from .scout_compiler import run_scout_compiler_sidecar
from .scout_quality import build_scout_quality_daily, persist_scout_quality_daily
from .universe_filter import build_universe_filter_report, summarize_universe_filter


# ---------------------------------------------------------------------------
# Feature flags (module-level for test patching)
# ---------------------------------------------------------------------------
try:
    from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph as _AKG
    _AKG_AVAILABLE = True
except Exception:
    _AKG = None
    _AKG_AVAILABLE = False

_SEC_CATALYST_AVAILABLE = False  # sec_catalyst.py was removed; flag kept for test compatibility


def _coerce_liquidity_score(raw: Any) -> Optional[float]:
    """Return a numeric liquidity score or None when the AKG value is missing."""
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if pd.isna(value):
        return None
    return value


def _coerce_float(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if pd.isna(value):
        return None
    return value


def _load_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _load_open_position_symbols() -> List[str]:
    payload = _load_json_file(Path("eval_results") / "paper_execution" / "positions.json") or {}
    open_positions = dict(payload.get("open_positions", {}) or {})
    return sorted(
        str(symbol or "").upper().strip()
        for symbol, row in open_positions.items()
        if str(symbol or "").strip() and isinstance(row, dict)
    )



# ---------------------------------------------------------------------------
# S-080: AKG signal writeback — maps pipeline signal dicts to enrich_node_*
# ---------------------------------------------------------------------------
_DIRECTION_MAP = {"BULLISH": "bullish", "BEARISH": "bearish", "NEUTRAL": "neutral"}
_REGIME_MAP = {"BULLISH": "risk_on", "BEARISH": "risk_off", "NEUTRAL": "neutral"}


def writeback_scores_to_akg(
    akg,
    candidates: List[Dict],
    normalized_signals: List[Dict],
    as_of_date: str,
) -> int:
    """Write composite scores and source provenance to AKG nodes after scoring.

    This enables hindsight accuracy testing: compare pipeline_core_score at
    scoring time against actual returns measured later.

    Returns the number of nodes updated.
    """
    # Build per-symbol source provenance from normalized signals.
    source_tags: Dict[str, set] = {}
    for sig in normalized_signals:
        if str(sig.get("source_status", "")) != "OK":
            continue
        sym = str(sig.get("symbol", "")).upper().strip()
        src = str(sig.get("source_name", "")).strip()
        if sym and src:
            source_tags.setdefault(sym, set()).add(src)

    count = 0
    for cand in candidates:
        ticker = str(cand.get("symbol", "")).upper().strip()
        if not ticker or ticker not in akg._nodes:
            continue
        node = akg._nodes[ticker]
        node["pipeline_core_score"] = round(float(cand.get("core_score", 0)), 4)
        node["pipeline_momentum_score"] = round(float(cand.get("momentum_score", 0)), 4)
        node["pipeline_asymmetry_score"] = round(float(cand.get("asymmetry_score", 0)), 4)
        node["pipeline_lane"] = str(cand.get("lane", "CORE"))
        node["pipeline_scored_at"] = as_of_date
        # Source provenance — join all source_name tags for this symbol.
        tags = source_tags.get(ticker, set())
        if tags:
            node["pipeline_source_tags"] = sorted(tags)
        count += 1
    return count


def writeback_signals_to_akg(akg, signals: List[Dict], as_of_date: str) -> int:
    """Write pipeline signal dicts back to AKG nodes via enrich_node_* methods.

    Returns the number of enrichments written.
    """
    social_news_pairs: Dict[str, Dict[str, float]] = {}
    write_count = 0

    for sig in signals:
        if sig.get("source_status") != "OK":
            continue
        ticker = str(sig.get("symbol", "")).upper().strip()
        if not ticker:
            continue
        family = sig.get("signal_family", "")
        score = float(sig.get("raw_score", 0))
        direction = str(sig.get("direction", "NEUTRAL"))

        if family == "price_momentum":
            akg.enrich_node_price_momentum(ticker, score, rs_spy=0.0, as_of_date=as_of_date)
            write_count += 1
        elif family == "smart_money":
            akg.enrich_node_smart_money(ticker, score, direction=_DIRECTION_MAP.get(direction, "neutral"), as_of_date=as_of_date)
            write_count += 1
        elif family == "insider_cluster":
            buyer = int(sig.get("cluster_size") or sig.get("evidence_count", 0))
            akg.enrich_node_insider_cluster(ticker, score, buyer_count=buyer, as_of_date=as_of_date)
            write_count += 1
        elif family == "social_momentum":
            social_news_pairs.setdefault(ticker, {"social": 0.0, "news": 0.0})["social"] = score
        elif family == "news_catalyst":
            social_news_pairs.setdefault(ticker, {"social": 0.0, "news": 0.0})["news"] = score
        elif family == "sector_rotation":
            akg.enrich_node_sector_rotation(ticker, score, as_of_date=as_of_date)
            write_count += 1
        elif family == "macro_regime_fit":
            akg.enrich_node_macro_regime(ticker, score, regime_tag=_REGIME_MAP.get(direction, "neutral"), as_of_date=as_of_date)
            write_count += 1

    for sn_ticker, sn_scores in social_news_pairs.items():
        akg.enrich_node_social_news(sn_ticker, social_score=sn_scores["social"], news_catalyst_score=sn_scores["news"], as_of_date=as_of_date)
        write_count += 1

    return write_count


class DealFlowPipeline:
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or DEFAULT_CONFIG

    def run(
        self,
        as_of_date: str,
        trigger: str,
        top_k: int,
    ) -> Tuple[DealFlowShortlist, ResearchQueue, List[dict], EventTriggerResult]:
        self.discover(as_of_date=as_of_date, trigger=trigger)
        return self.collect(as_of_date=as_of_date, trigger=trigger, top_k=top_k)

    # ------------------------------------------------------------------
    # Stage 1: Discovery — scouts, watchlist, universe build
    # ------------------------------------------------------------------

    def discover(self, as_of_date: str, trigger: str) -> Dict[str, Any]:
        """Run all scouts and build universe.  Stores results as instance attrs.

        Returns a summary dict (scout counts, universe size).
        """
        event_state = self._evaluate_event_trigger(as_of_date)
        if trigger == "event" and not event_state["triggered"]:
            event_state["reasons"].append("Event thresholds not met; producing snapshot anyway.")

        watchlist_path = self._watchlist_path()
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
                lookback_days=int(self.config.get("dealflow_manual_x_feed_carryforward_days", 0)),
            )
            if x_feed_merged:
                manual_symbols_set |= set(x_feed_merged.keys())
        except Exception:
            pass

        manual_symbols = sorted(manual_symbols_set)
        fvg_recall = self._build_fvg_recall_channel(as_of_date=as_of_date)
        fvg_recall_symbols = list(fvg_recall.get("selected_symbols", []))
        fvg_recall_artifact = dict(fvg_recall.get("artifact", {}) or {})
        fma_recall = self._build_fma_recall_channel(as_of_date=as_of_date)
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
        self._iv_force_queue = []

        insider_summary: Dict[str, Any] = {}
        try:
            from tradingagents.dealflow.sources.insider_cluster import scan_insider_sweep
            _insider_akg = _AKG.load() if _AKG_AVAILABLE and _AKG is not None else None
            _insider_result = scan_insider_sweep(
                sweep_date=as_of_date,
                window_days=int(self.config.get("dealflow_insider_sweep_window_days", 30)),
                config=self.config,
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
        if bool(self.config.get("dealflow_technical_ignition_enabled", True)):
            try:
                from tradingagents.dealflow.sources.technical_ignition_scout import scan_technical_ignition_setups
                technical_ignition_result = scan_technical_ignition_setups(
                    as_of_date=as_of_date,
                    db_path=self.config.get("dealflow_technical_signal_db_path"),
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
        if bool(self.config.get("dealflow_thirteenf_watchlist_enabled", True)):
            try:
                thirteenf_result = scan_thirteenf_watchlist(
                    as_of_date=as_of_date,
                    max_filings_per_manager=int(self.config.get("dealflow_thirteenf_max_filings_per_manager", 6)),
                    min_value_usd=float(self.config.get("dealflow_thirteenf_min_value_usd", 10_000_000.0)),
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
            "config": self.config,
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
        self._last_universe = universe
        self._last_universe_ledger = self._resolve_universe_ledger(
            universe,
            get_last_universe_ledger(),
        )
        self._last_event_state = event_state
        self._last_manual_symbols = manual_symbols
        self._last_manual_ideas = manual_ideas
        self._last_fvg_recall = fvg_recall
        self._last_fma_recall = fma_recall

        # Scout audit — persist what scouts found for backtesting
        try:
            scout_audit = self._build_scout_audit(
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
                universe_ledger=dict(self._last_universe_ledger or {}),
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
        self._last_universe_filter = universe_filter_report
        self._last_universe_filter_summary = universe_filter_summary

        try:
            discovery_delta = build_discovery_delta(
                as_of_date=as_of_date,
                scout_audit=scout_audit,
                fvg_recall=fvg_recall_artifact,
                fma_recall=fma_recall_artifact,
            )
            (out_dir / "discovery_delta.json").write_text(json.dumps(discovery_delta, indent=2))
        except Exception:
            discovery_delta = {
                "coverage_summary": {"signal_count": 0, "record_count": 0},
                "cohorts": {"scout_only": [], "technical_only": [], "multi_channel": []},
                "top_delta_symbols": [],
            }
        self._last_discovery_delta = discovery_delta

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
        self._last_scenario_sidecar_summary = scenario_sidecar_summary
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
        self._last_scout_quality_summary = scout_quality_summary

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

    # ------------------------------------------------------------------
    # Scout audit — lightweight daily record for backtesting
    # ------------------------------------------------------------------

    def _build_scout_audit(
        self,
        as_of_date: str,
        breakout_result: Dict[str, Any],
        iv_result: Dict[str, Any],
        insider_result: Dict[str, Any],
        technical_ignition_result: Optional[Dict[str, Any]] = None,
        thirteenf_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build a compact audit dict from scout return values."""
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
        # Persist
        out_dir = Path("eval_results") / "deal_flow" / as_of_date
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "scout_audit.json").write_text(json.dumps(audit, indent=2))
        self._last_scout_audit = audit
        return audit

    def _has_recent_yahoo_history(self, symbol: str) -> bool:
        normalized = self._normalize_symbol(symbol)
        if not normalized:
            return True
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                frame = yf.download(
                    normalized,
                    period="1mo",
                    interval="1d",
                    auto_adjust=False,
                    progress=False,
                    threads=False,
                )
        except Exception:
            # Unknown fetch failures should not trigger destructive pruning.
            return True
        extracted = _extract_ohlcv_frame(frame, normalized)
        return extracted is not None and not extracted.empty

    def _prune_invalid_recall_symbols(self, akg: Any, symbols: List[str]) -> List[str]:
        normalized = [self._normalize_symbol(symbol) for symbol in symbols]
        normalized = [symbol for symbol in normalized if symbol]
        if not normalized or akg is None or not hasattr(akg, "remove_nodes"):
            return []
        try:
            removed = int(akg.remove_nodes(normalized) or 0)
            if removed > 0 and hasattr(akg, "save"):
                akg.save()
        except Exception:
            return []
        return normalized if removed > 0 else []

    def _prepare_recall_market_data(
        self,
        *,
        akg: Any,
        candidate_symbols: List[str],
        as_of_date: str,
    ) -> Dict[str, Any]:
        deduped = sorted(dict.fromkeys(self._normalize_symbol(symbol) for symbol in candidate_symbols if symbol))
        if not deduped:
            return {
                "benchmark_frame": None,
                "candidate_symbols": [],
                "invalid_symbols_removed": [],
                "symbol_frames": {},
            }

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            history = yf.download(
                deduped + ["QQQ"],
                start="1999-01-01",
                end=as_of_date,
                interval="1d",
                auto_adjust=False,
                progress=False,
                group_by="ticker",
                threads=False,
            )

        benchmark_frame = _extract_ohlcv_frame(history, "QQQ")
        symbol_frames: Dict[str, pd.DataFrame] = {}
        missing_symbols: List[str] = []
        for symbol in deduped:
            frame = _extract_ohlcv_frame(history, symbol)
            if frame is None or frame.empty:
                missing_symbols.append(symbol)
                continue
            symbol_frames[symbol] = frame

        confirmed_missing = [symbol for symbol in missing_symbols if not self._has_recent_yahoo_history(symbol)]
        invalid_symbols_removed = self._prune_invalid_recall_symbols(akg, confirmed_missing)

        return {
            "benchmark_frame": benchmark_frame,
            "candidate_symbols": sorted(symbol_frames.keys()),
            "invalid_symbols_removed": invalid_symbols_removed,
            "symbol_frames": symbol_frames,
        }

    def _preflight_akg_liquidity(self, as_of_date: str) -> Dict[str, Any]:
        min_coverage = float(self.config.get("dealflow_liquidity_preflight_min_coverage", 0.80))
        max_age_days = int(self.config.get("dealflow_liquidity_preflight_max_age_days", 1))
        refresh_enabled = bool(self.config.get("dealflow_liquidity_preflight_refresh_enabled", True))
        report: Dict[str, Any] = {
            "date": as_of_date,
            "company_count": 0,
            "fresh_count": 0,
            "coverage": 0.0,
            "max_age_days": max_age_days,
            "min_coverage": min_coverage,
            "refresh_attempted": False,
            "refresh_result": {},
            "status": "UNKNOWN",
        }

        def _compute() -> Dict[str, Any]:
            from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
            akg = AeternusKnowledgeGraph.load()
            company_nodes = [n for n in akg._nodes.values() if n.get("node_type") == "company"]
            fresh = 0
            try:
                as_of = dt.datetime.strptime(as_of_date, "%Y-%m-%d").date()
            except Exception:
                as_of = dt.date.today()
            for node in company_nodes:
                if _coerce_liquidity_score(node.get("liquidity_score")) is None:
                    continue
                cached = str(node.get("liquidity_cached_at") or "").strip()
                try:
                    cached_date = dt.datetime.strptime(cached, "%Y-%m-%d").date()
                except Exception:
                    continue
                if (as_of - cached_date).days <= max_age_days:
                    fresh += 1
            total = len(company_nodes)
            coverage = (fresh / total) if total else 1.0
            return {"company_count": total, "fresh_count": fresh, "coverage": coverage}

        try:
            report.update(_compute())
            if report["coverage"] < min_coverage and refresh_enabled:
                report["refresh_attempted"] = True
                from tradingagents.dealflow.sources.universe_seeder import refresh_liquidity
                report["refresh_result"] = dict(refresh_liquidity())
                report.update(_compute())
            report["status"] = "OK" if report["coverage"] >= min_coverage else "LOW_COVERAGE"
        except Exception as exc:
            report["status"] = "ERROR"
            report["error"] = str(exc)
        return report

    def _build_fvg_recall_channel(self, as_of_date: str) -> Dict[str, Any]:
        liquidity_preflight = self._preflight_akg_liquidity(as_of_date)
        if not bool(self.config.get("dealflow_fvg_recall_enabled", True)):
            return {
                "selected_symbols": [],
                "artifact": {
                    "date": as_of_date,
                    "selected_symbols": [],
                    "quota": 0,
                    "rule_snapshot": {"enabled": False},
                },
            }

        quota = int(self.config.get("dealflow_fvg_recall_quota", 30))
        min_rs20 = float(self.config.get("dealflow_fvg_recall_min_rs20", 0.03))
        min_liquidity_score = float(self.config.get("dealflow_fvg_recall_min_liquidity_score", 30.0))
        selected_rows: List[Dict[str, Any]] = []

        try:
            from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph

            akg = AeternusKnowledgeGraph.load()
            candidate_symbols: List[str] = []
            for node in akg._nodes.values():
                if node.get("node_type") != "company":
                    continue
                symbol = self._normalize_symbol(node.get("id", ""))
                if not symbol:
                    continue
                asset_class = str(node.get("asset_class") or "Equity")
                liquidity_score = _coerce_liquidity_score(node.get("liquidity_score"))
                if (
                    asset_class != "Equity"
                    or liquidity_score is None
                    or liquidity_score < min_liquidity_score
                ):
                    continue
                candidate_symbols.append(symbol)

            candidate_symbols = sorted(dict.fromkeys(candidate_symbols))
            invalid_symbols_removed: List[str] = []
            if candidate_symbols:
                market_data = self._prepare_recall_market_data(
                    akg=akg,
                    candidate_symbols=candidate_symbols,
                    as_of_date=as_of_date,
                )
                benchmark_frame = market_data.get("benchmark_frame")
                invalid_symbols_removed = list(market_data.get("invalid_symbols_removed") or [])
                for symbol in market_data.get("candidate_symbols", []):
                    frame = market_data.get("symbol_frames", {}).get(symbol)
                    if frame is None or frame.empty or benchmark_frame is None or benchmark_frame.empty:
                        continue
                    features = _build_feature_frame(frame, benchmark_frame=benchmark_frame, atr_floor=0.25)
                    if features.empty:
                        continue
                    row = features.iloc[-1]
                    if not bool(row.get("bullish_fvg_present", False)):
                        continue
                    if float(row.get("relative_strength_20d", 0.0) or 0.0) < min_rs20:
                        continue
                    if not bool(row.get("sma50_above_sma200", False)):
                        continue
                    selected_rows.append(
                        {
                            "symbol": symbol,
                            "score": float(row.get("score", 0.0) or 0.0),
                            "relative_strength_20d": float(row.get("relative_strength_20d", 0.0) or 0.0),
                            "sma50_above_sma200": bool(row.get("sma50_above_sma200", False)),
                            "bullish_fvg_present": True,
                        }
                    )
        except Exception:
            selected_rows = []

        selected_rows.sort(key=lambda row: (-float(row.get("score", 0.0)), str(row.get("symbol", ""))))
        selected_rows = selected_rows[: max(0, quota)]
        artifact = {
            "date": as_of_date,
            "selected_symbols": [row["symbol"] for row in selected_rows],
            "quota": quota,
            "rows": selected_rows,
            "invalid_symbols_removed": invalid_symbols_removed if "invalid_symbols_removed" in locals() else [],
            "liquidity_preflight": liquidity_preflight,
            "rule_snapshot": {
                "enabled": True,
                "quota": quota,
                "min_rs20": min_rs20,
                "min_liquidity_score": min_liquidity_score,
                "required_confirmation": [
                    "bullish_fvg_present",
                    "relative_strength_20d",
                    "sma50_above_sma200",
                ],
            },
        }

        return {
            "selected_symbols": list(artifact["selected_symbols"]),
            "artifact": artifact,
        }

    def _build_fma_recall_channel(self, as_of_date: str) -> Dict[str, Any]:
        liquidity_preflight = self._preflight_akg_liquidity(as_of_date)
        if not bool(self.config.get("dealflow_fma_recall_enabled", True)):
            return {
                "selected_symbols": [],
                "artifact": {
                    "date": as_of_date,
                    "selected_symbols": [],
                    "quota": 0,
                    "rule_snapshot": {"enabled": False},
                },
            }

        quota = int(self.config.get("dealflow_fma_recall_quota", 20))
        min_score = float(self.config.get("dealflow_fma_recall_min_score", 60.0))
        min_liquidity_score = float(self.config.get("dealflow_fvg_recall_min_liquidity_score", 30.0))
        snapshots: List[Dict[str, Any]] = []

        try:
            from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph

            akg = AeternusKnowledgeGraph.load()
            candidate_symbols: List[str] = []
            for node in akg._nodes.values():
                if node.get("node_type") != "company":
                    continue
                symbol = self._normalize_symbol(node.get("id", ""))
                if not symbol:
                    continue
                asset_class = str(node.get("asset_class") or "Equity")
                liquidity_score = _coerce_liquidity_score(node.get("liquidity_score"))
                if (
                    asset_class != "Equity"
                    or liquidity_score is None
                    or liquidity_score < min_liquidity_score
                ):
                    continue
                candidate_symbols.append(symbol)

            candidate_symbols = sorted(dict.fromkeys(candidate_symbols))
            invalid_symbols_removed: List[str] = []
            if candidate_symbols:
                market_data = self._prepare_recall_market_data(
                    akg=akg,
                    candidate_symbols=candidate_symbols,
                    as_of_date=as_of_date,
                )
                benchmark_frame = market_data.get("benchmark_frame")
                invalid_symbols_removed = list(market_data.get("invalid_symbols_removed") or [])
                for symbol in market_data.get("candidate_symbols", []):
                    frame = market_data.get("symbol_frames", {}).get(symbol)
                    if frame is None or frame.empty or benchmark_frame is None or benchmark_frame.empty:
                        continue
                    features = _build_fma_feature_frame(frame, benchmark_frame=benchmark_frame, variant="fma_live")
                    if features.empty:
                        continue
                    row = features.iloc[-1]
                    if not bool(row.get("valid", False)):
                        continue
                    snapshots.append(
                        {
                            "ticker": symbol,
                            "variant": "fma_live",
                            "valid": True,
                            "velocity_60d": float(row.get("velocity_60d", 0.0) or 0.0),
                            "accel_value": float(row.get("accel_value", 0.0) or 0.0),
                            "mass_ratio": float(row.get("mass_ratio", 0.0) or 0.0),
                            "force_value": float(row.get("force_value", 0.0) or 0.0),
                            "relative_strength_60d": float(row.get("relative_strength_60d", 0.0) or 0.0),
                        }
                    )
        except Exception:
            snapshots = []

        scores = score_fma_cross_section(snapshots, variant="fma_live")
        selected_rows: List[Dict[str, Any]] = []
        for snapshot in snapshots:
            symbol = str(snapshot.get("ticker", "")).upper().strip()
            score = float(scores.get(symbol, 0.0) or 0.0)
            if score < min_score:
                continue
            selected_rows.append(
                {
                    "symbol": symbol,
                    "score": score,
                    "velocity_60d": float(snapshot.get("velocity_60d", 0.0) or 0.0),
                    "accel_value": float(snapshot.get("accel_value", 0.0) or 0.0),
                    "mass_ratio": float(snapshot.get("mass_ratio", 0.0) or 0.0),
                    "force_value": float(snapshot.get("force_value", 0.0) or 0.0),
                    "relative_strength_60d": float(snapshot.get("relative_strength_60d", 0.0) or 0.0),
                }
            )

        selected_rows.sort(key=lambda row: (-float(row.get("score", 0.0)), str(row.get("symbol", ""))))
        selected_rows = selected_rows[: max(0, quota)]
        artifact = {
            "date": as_of_date,
            "selected_symbols": [row["symbol"] for row in selected_rows],
            "quota": quota,
            "rows": selected_rows,
            "invalid_symbols_removed": invalid_symbols_removed if "invalid_symbols_removed" in locals() else [],
            "liquidity_preflight": liquidity_preflight,
            "rule_snapshot": {
                "enabled": True,
                "quota": quota,
                "min_score": min_score,
                "min_liquidity_score": min_liquidity_score,
                "required_confirmation": ["fma_live_score"],
            },
        }

        return {
            "selected_symbols": list(artifact["selected_symbols"]),
            "artifact": artifact,
        }

    # ------------------------------------------------------------------
    # Stage 2: Collection — connectors, scoring, ranking, persist
    # ------------------------------------------------------------------

    def collect(
        self,
        as_of_date: str,
        trigger: str,
        top_k: int,
    ) -> Tuple[DealFlowShortlist, ResearchQueue, List[dict], EventTriggerResult]:
        """Run collectors, score, rank, persist.  Returns same tuple as run().

        If discover() was not called first, bootstraps universe and event state
        from AKG/disk so collect() works standalone.
        """
        # Bootstrap if discover() wasn't called
        universe = getattr(self, "_last_universe", None)
        if universe is None:
            watchlist_path = self._watchlist_path()
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
                    lookback_days=int(self.config.get("dealflow_manual_x_feed_carryforward_days", 0)),
                )
                if x_feed_merged:
                    manual_symbols_set |= set(x_feed_merged.keys())
            except Exception:
                pass
            manual_symbols = sorted(manual_symbols_set)
            universe = build_universe_from_akg(
                extra_symbols=manual_symbols,
                config=self.config,
            )
            self._last_universe_ledger = self._resolve_universe_ledger(
                universe,
                get_last_universe_ledger(),
            )
            self._last_manual_ideas = manual_ideas
            self._last_manual_symbols = manual_symbols
        elif not hasattr(self, "_last_universe_ledger"):
            self._last_universe_ledger = self._resolve_universe_ledger(universe, {})

        event_state = getattr(self, "_last_event_state", None)
        if event_state is None:
            event_state = self._evaluate_event_trigger(as_of_date)
            if trigger == "event" and not event_state["triggered"]:
                event_state["reasons"].append("Event thresholds not met; producing snapshot anyway.")

        manual_ideas = getattr(self, "_last_manual_ideas", [])

        connector_health: List[Dict[str, Any]] = []
        cashtag_events: List[Dict] = []
        signals = []

        # Parallel execution of independent connectors.
        connector_tasks = []
        connector_tasks.extend([
            ("social_news", collect_social_news_signals, (universe,), {
                "as_of_date": as_of_date,
                "max_symbol_calls": int(self.config.get("dealflow_social_max_symbol_calls", 35)),
                "config": self.config,
            }),
            ("price_momentum", collect_price_momentum_signals, (universe,), {}),
            ("smart_money", collect_smart_money_signals, (universe,), {
                "as_of_date": as_of_date,
                "config": self.config,
            }),
            ("sector_rotation", collect_sector_rotation_signals, (universe,), {}),
        ])


        if bool(self.config.get("dealflow_insider_cluster_enabled", True)):
            connector_tasks.append(("insider_cluster", collect_insider_cluster_signals, (universe,), {
                "as_of_date": as_of_date,
                "config": self.config,
            }))

        # Execute all connectors in parallel.
        parallel_results: Dict[str, Tuple[List[Dict], Dict[str, Any]]] = {}
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {}
            for task_name, collector, args, kwargs in connector_tasks:
                future = executor.submit(self._collect_connector_signals, task_name, collector, *args, **kwargs)
                futures[future] = task_name

            for future in futures:
                task_name = futures[future]
                try:
                    sig_list, health = future.result()
                    parallel_results[task_name] = (sig_list, health)
                except Exception as exc:
                    # If a connector fails, its health entry captures the error.
                    parallel_results[task_name] = ([], self._build_connector_health_entry(
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
        if _AKG_AVAILABLE and _AKG is not None:
            try:
                _akg = _AKG.load()

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
            min_signal_families=int(self.config.get("dealflow_min_signal_families", 3)),
            min_evidence_count=5,
            momentum_lane_threshold=float(self.config.get("dealflow_momentum_lane_threshold", 68.0)),
            momentum_lane_price_override_threshold=float(
                self.config.get("dealflow_momentum_lane_price_override_threshold", 82.0)
            ),
            momentum_lane_social_confirmation_threshold=float(
                self.config.get("dealflow_momentum_lane_social_confirmation_threshold", 60.0)
            ),
            momentum_lane_floor_ratio=float(
                self.config.get("dealflow_momentum_lane_floor_ratio", 0.20)
            ),
            momentum_lane_promotion_min_score=float(
                self.config.get("dealflow_momentum_lane_promotion_min_score", 62.0)
            ),
            momentum_lane_promotion_min_price_score=float(
                self.config.get("dealflow_momentum_lane_promotion_min_price_score", 70.0)
            ),
        )
        # --- Needle bypass: detect extreme-signal LOW_DATA candidates ---
        needle_candidates = detect_needles(normalized_signals, candidates)
        if needle_candidates:
            iv_fq = getattr(self, "_iv_force_queue", None) or []
            self._iv_force_queue = iv_fq + needle_candidates
            print(f"[pipeline] Needle bypass: {len(needle_candidates)} candidates")

        # --- S-080b: Write composite scores + source provenance to AKG ---
        if _AKG_AVAILABLE and _AKG is not None:
            try:
                _akg_scores = _AKG.load()
                _ns = writeback_scores_to_akg(
                    _akg_scores, candidates, normalized_signals, as_of_date,
                )
                _akg_scores.save()
                if _ns:
                    print(f"[pipeline] AKG score writeback: {_ns} nodes updated")
            except Exception as exc:
                import sys as _sys
                print(f"[pipeline] AKG score writeback error: {exc}", file=_sys.stderr)

        symbol_source_tags = self._build_symbol_source_tags(normalized_signals)
        for candidate in candidates:
            symbol = str(candidate.get("symbol", "")).upper().strip()
            candidate["source_detail"] = self._infer_source_detail(
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
            max_sector_count=int(self.config.get("dealflow_max_sector_count", 5)),
            core_quota=int(self.config.get("dealflow_core_quota", 18)),
            momentum_quota=int(self.config.get("dealflow_momentum_quota", 12)),
        )
        ranked, manual_merge = self._apply_manual_merge_policy(
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
        shortlist["connector_health_summary"] = self._summarize_connector_health(connector_health)

        research_queue = self._build_research_queue(
            shortlist,
            ledger_base_dir=Path("eval_results") / "deal_flow" / as_of_date,
        )
        momentum_board = self._build_momentum_board(shortlist)
        family_contribution_report = self._build_family_contribution_report(shortlist)
        shortlist["family_contribution_summary"] = family_contribution_report.get("aggregate", {})
        self._persist(
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

    def _collect_connector_signals(self, name: str, collector, *args, **kwargs) -> Tuple[List[Dict], Dict[str, Any]]:
        start = time.perf_counter()
        error_message = ""
        signals: List[Dict] = []
        timeout_seconds = float(self.config.get("dealflow_connector_timeout_seconds", 45.0))
        max_attempts = max(1, int(self.config.get("dealflow_connector_max_attempts", 2)))
        for attempt in range(1, max_attempts + 1):
            try:
                payload = self._run_connector_with_timeout(
                    collector,
                    timeout_seconds=timeout_seconds,
                    args=args,
                    kwargs=kwargs,
                )
                signals = list(payload)
                error_message = ""
                break
            except Exception as exc:
                signals = []
                error_message = str(exc)
                if attempt < max_attempts:
                    # Small backoff for transient connector failures (DNS/rate spikes/timeouts).
                    time.sleep(min(0.5, 0.15 * attempt))
        latency_ms = (time.perf_counter() - start) * 1000.0
        health = self._build_connector_health_entry(
            connector_name=name,
            signals=signals,
            latency_ms=latency_ms,
            error_message=error_message,
        )
        return signals, health

    def _run_connector_with_timeout(
        self,
        collector,
        timeout_seconds: float,
        args: tuple,
        kwargs: Dict[str, Any],
    ):
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(collector, *args, **kwargs)
            try:
                return future.result(timeout=max(0.01, float(timeout_seconds)))
            except FuturesTimeoutError as exc:
                future.cancel()
                raise TimeoutError(
                    f"Connector timed out after {float(timeout_seconds):.1f}s"
                ) from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _build_connector_health_entry(
        self,
        connector_name: str,
        signals: List[Dict],
        latency_ms: float,
        error_message: str = "",
        status_override: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        status_counts = {"OK": 0, "NO_DATA": 0, "ERROR": 0, "NOT_CONFIGURED": 0}
        evidence_total = 0
        freshness_ok: List[float] = []
        sources: set[str] = set()
        families: set[str] = set()

        for sig in signals:
            status = str(sig.get("source_status", "NO_DATA"))
            if status not in status_counts:
                status = "NO_DATA"
            status_counts[status] += 1
            evidence_total += int(sig.get("evidence_count", 0) or 0)

            source_name = str(sig.get("source_name", "") or "").strip()
            if source_name:
                sources.add(source_name)
            family = str(sig.get("signal_family", "") or "").strip()
            if family:
                families.add(family)

            if status == "OK":
                freshness_ok.append(float(sig.get("freshness_hours", 9999.0) or 9999.0))

        final_status = "NO_DATA"
        if status_override in {"OK", "NO_DATA", "ERROR", "NOT_CONFIGURED"}:
            final_status = status_override
        elif error_message:
            final_status = "ERROR"
        elif status_counts["OK"] > 0:
            final_status = "OK"
        elif status_counts["ERROR"] > 0:
            final_status = "ERROR"
        elif status_counts["NOT_CONFIGURED"] > 0 and status_counts["NO_DATA"] == 0:
            final_status = "NOT_CONFIGURED"

        signal_count = len(signals)
        ok_coverage_pct = 0.0
        if signal_count > 0:
            ok_coverage_pct = (status_counts["OK"] / float(signal_count)) * 100.0

        entry: Dict[str, Any] = {
            "connector": connector_name,
            "status": final_status,
            "latency_ms": float(round(latency_ms, 2)),
            "signal_count": signal_count,
            "status_counts": status_counts,
            "ok_coverage_pct": float(round(ok_coverage_pct, 2)),
            "evidence_total": int(evidence_total),
            "freshness_min_hours": float(round(min(freshness_ok), 4)) if freshness_ok else None,
            "freshness_median_hours": float(round(median(freshness_ok), 4)) if freshness_ok else None,
            "source_names": sorted(sources),
            "signal_families": sorted(families),
            "error": error_message if final_status == "ERROR" else "",
        }
        if metadata:
            entry.update(metadata)
        return entry

    def _summarize_connector_health(self, connector_health: List[Dict[str, Any]]) -> Dict[str, Any]:
        total = len(connector_health)
        status_totals = {"OK": 0, "NO_DATA": 0, "ERROR": 0, "NOT_CONFIGURED": 0}
        for row in connector_health:
            status = str(row.get("status", "NO_DATA"))
            if status not in status_totals:
                status = "NO_DATA"
            status_totals[status] += 1
        return {
            "connectors_total": total,
            "status_totals": status_totals,
            "degraded": status_totals["ERROR"] > 0,
            "not_configured": status_totals["NOT_CONFIGURED"],
        }

    def _build_family_contribution_report(self, shortlist: DealFlowShortlist) -> Dict[str, Any]:
        candidates = shortlist.get("candidates", [])
        rows: List[Dict[str, Any]] = []

        for candidate in candidates:
            subs = dict(candidate.get("subscores", {}))
            core_contrib = self._core_contributions(subs)
            momentum_contrib = {
                "price_momentum": float(round(0.60 * float(subs.get("price_momentum", 50.0)), 4)),
                "social_momentum": float(round(0.30 * float(subs.get("social_momentum", 50.0)), 4)),
                "news_catalyst": float(round(0.10 * float(subs.get("news_catalyst", 50.0)), 4)),
            }
            momentum_score = float(candidate.get("momentum_score", 0.0))
            asymmetry_contrib = {
                "momentum_score": float(round(0.70 * momentum_score, 4)),
                "macro_regime_fit": float(round(0.10 * float(subs.get("macro_regime_fit", 50.0)), 4)),
                "smart_money": float(round(0.10 * float(subs.get("smart_money", 50.0)), 4)),
                "liquidity_tradability": float(round(0.10 * float(subs.get("liquidity_tradability", 50.0)), 4)),
            }
            rows.append(
                {
                    "symbol": candidate.get("symbol"),
                    "rank": candidate.get("rank"),
                    "lane": candidate.get("lane"),
                    "core_score": float(candidate.get("core_score", candidate.get("deal_flow_score", 0.0))),
                    "momentum_score": momentum_score,
                    "asymmetry_score": float(candidate.get("asymmetry_score", 0.0)),
                    "core_contributions": core_contrib,
                    "momentum_contributions": momentum_contrib,
                    "asymmetry_contributions": asymmetry_contrib,
                }
            )

        return {
            "run_id": shortlist.get("run_id"),
            "date": shortlist.get("date"),
            "core_weight_model": dict(CORE_SCORE_WEIGHTS),
            "momentum_weight_model": {"price_momentum": 0.60, "social_momentum": 0.30, "news_catalyst": 0.10},
            "asymmetry_weight_model": {
                "momentum_score": 0.70,
                "macro_regime_fit": 0.10,
                "smart_money": 0.10,
                "liquidity_tradability": 0.10,
            },
            "candidates": rows,
            "aggregate": {
                "ALL": self._aggregate_contributions(rows, None),
                "CORE": self._aggregate_contributions(rows, "CORE"),
                "MOMENTUM": self._aggregate_contributions(rows, "MOMENTUM"),
            },
        }

    def _aggregate_contributions(self, rows: List[Dict[str, Any]], lane: Optional[str]) -> Dict[str, Any]:
        selected = rows if lane is None else [r for r in rows if str(r.get("lane")) == lane]
        if not selected:
            return {
                "count": 0,
                "avg_core_contributions": {},
                "avg_momentum_contributions": {},
                "avg_asymmetry_contributions": {},
            }
        return {
            "count": len(selected),
            "avg_core_contributions": self._average_nested(selected, "core_contributions"),
            "avg_momentum_contributions": self._average_nested(selected, "momentum_contributions"),
            "avg_asymmetry_contributions": self._average_nested(selected, "asymmetry_contributions"),
        }

    def _average_nested(self, rows: List[Dict[str, Any]], field: str) -> Dict[str, float]:
        totals: Dict[str, float] = {}
        for row in rows:
            data = row.get(field, {}) or {}
            for key, value in data.items():
                totals[key] = totals.get(key, 0.0) + float(value)
        return {k: float(round(v / float(len(rows)), 4)) for k, v in totals.items()}

    def _core_contributions(self, subscores: Dict[str, float]) -> Dict[str, float]:
        weighted_parts: List[Tuple[str, float, float]] = []
        for family, weight in CORE_SCORE_WEIGHTS.items():
            score = subscores.get(family)
            if score is None:
                continue
            weighted_parts.append((family, float(weight), float(score)))

        total_weight = sum(weight for _, weight, _ in weighted_parts)
        if total_weight <= 0:
            return {}
        return {
            family: float(round((weight * score) / total_weight, 4))
            for family, weight, score in weighted_parts
        }

    def evaluate_event_trigger(self, as_of_date: str) -> EventTriggerResult:
        return self._evaluate_event_trigger(as_of_date)

    def _build_research_queue(
        self,
        shortlist: DealFlowShortlist,
        ledger_base_dir: Optional[Path] = None,
    ) -> ResearchQueue:
        deep_k = int(self.config.get("dealflow_deep_k", 8))
        initial_deep_k = deep_k
        deep_core_quota = int(self.config.get("dealflow_deep_core_quota", 4))
        deep_momentum_quota = int(self.config.get("dealflow_deep_momentum_quota", 4))

        items: List[ResearchQueueItem] = []
        suppressed_queue_ids = set()
        for candidate in shortlist["candidates"]:
            triage_score = self._triage_score(candidate)
            symbol = candidate["symbol"]
            queue_item_id = f"{shortlist['run_id']}:{symbol}"
            lane = str(candidate.get("lane", "CORE"))
            momentum_score = float(candidate.get("momentum_score", 0.0))
            asymmetry_score = float(candidate.get("asymmetry_score", 0.0))
            trend_tags = list(candidate.get("trend_tags", []))

            item: ResearchQueueItem = {
                "queue_id": queue_item_id,
                "symbol": symbol,
                "asset_class": candidate.get("asset_class", "Unknown"),
                "sector": self._normalized_sector_label(candidate.get("sector")),
                "lane": lane if lane in {"CORE", "MOMENTUM"} else "CORE",
                "upside_3m_score": float(candidate.get("upside_3m_score", 0.0)),
                "emergence_proxy_score": float(candidate.get("emergence_proxy_score", 0.0)),
                "narrative_ignition_score": float(candidate.get("narrative_ignition_score", 0.0)),
                "fundamentals_acceleration_score": float(candidate.get("fundamentals_acceleration_score", 0.0)),
                "relative_strength_score": float(candidate.get("relative_strength_score", 0.0)),
                "lane_candidates": list(candidate.get("lane_candidates", [])),
                "deal_flow_score": float(candidate.get("deal_flow_score", 0.0)),
                "momentum_score": momentum_score,
                "asymmetry_score": asymmetry_score,
                "subscores": dict(candidate.get("subscores", {})),
                "thesis_tags": self._thesis_tags(candidate),
                "risk_tags": list(candidate.get("risk_tags", [])),
                "evidence": {
                    "active_families": float(candidate.get("active_families", 0)),
                    "evidence_count": float(candidate.get("evidence_count", 0)),
                    "freshness_hours": float(candidate.get("freshness_hours", 9999.0)),
                },
                "why_now": why_now_text(
                    lane=lane,
                    momentum_score=momentum_score,
                    asymmetry_score=asymmetry_score,
                    trend_tags=trend_tags,
                ),
                "source": str(candidate.get("source", "AUTO")).upper(),
                "source_detail": str(candidate.get("source_detail", "AUTO_MODEL")),
                "manual_note": str(candidate.get("manual_note", "")),
                "research_playbook": select_research_playbook(
                    lane=lane,
                    momentum_score=momentum_score,
                ),
                "triage_score": float(round(triage_score, 4)),
                "selected_for_deep": False,
            }
            suppressed, constraint = check_symbol_theme_suppression(
                symbol=str(symbol),
                thesis_tags=item["thesis_tags"],
                config=self.config,
            )
            if suppressed:
                suppressed_queue_ids.add(queue_item_id)
                tags = list(item.get("risk_tags", []))
                reason = "Operator negative constraint"
                if isinstance(constraint, dict):
                    details = str(constraint.get("constraint_id") or "").strip()
                    if details:
                        reason = f"{reason} ({details})"
                if reason not in tags:
                    tags.append(reason)
                item["risk_tags"] = tags
            items.append(item)

        items.sort(key=lambda i: -float(i["triage_score"]))
        selected_ids = self._select_for_deep(
            items=[item for item in items if item["queue_id"] not in suppressed_queue_ids],
            deep_k=deep_k,
            core_quota=deep_core_quota,
            momentum_quota=deep_momentum_quota,
        )
        selected_ids = self._ensure_manual_deep_selection(
            items=[item for item in items if item["queue_id"] not in suppressed_queue_ids],
            selected_ids=selected_ids,
            deep_k=deep_k,
        )

        reserve_quota = int(self.config.get("dealflow_deep_reserve_quota", 4))
        if bool(self.config.get("dealflow_iv_force_queue_enabled", False)):
            items, selected_ids = self._inject_force_queue_candidates(
                items=items,
                selected_ids=selected_ids,
                deep_k=deep_k,
                reserve_quota=reserve_quota,
                run_id=shortlist["run_id"],
            )

        pre_inject_count = len(selected_ids)
        items, selected_ids = self._inject_held_positions(
            items=items,
            selected_ids=selected_ids,
            run_id=shortlist["run_id"],
        )
        # Grow deep_k so portfolio positions don't displace new discovery
        deep_k += len(selected_ids) - pre_inject_count

        selected_id_set = set(selected_ids)
        for item in items:
            item["selected_for_deep"] = item["queue_id"] in selected_id_set

        if ledger_base_dir is not None:
            deep_selection_rule_snapshot = {
                "deep_k": int(initial_deep_k),
                "final_deep_k": int(deep_k),
                "core_quota": int(deep_core_quota),
                "momentum_quota": int(deep_momentum_quota),
                "reserve_quota": int(reserve_quota),
            }
            deep_selected_symbols = [
                str(item.get("symbol", "")).upper().strip()
                for item in items
                if item["queue_id"] in selected_id_set
            ]
            deep_dropped_symbols = [
                str(item.get("symbol", "")).upper().strip()
                for item in items
                if item["queue_id"] not in selected_id_set
            ]
            deep_drop_metadata = self._build_deep_selection_drop_metadata(
                items=items,
                selected_id_set=selected_id_set,
                suppressed_queue_ids=suppressed_queue_ids,
                deep_selection_rule_snapshot=deep_selection_rule_snapshot,
            )
            deep_selection_row = make_ledger_row(
                run_id=str(shortlist.get("run_id", "")),
                source_date=str(shortlist.get("date", "")),
                lane="shared",
                stage_id="deep_selection_cut",
                rule_snapshot=deep_selection_rule_snapshot,
                kept_symbols=deep_selected_symbols,
                dropped_symbols=deep_dropped_symbols,
                base_dir=Path(ledger_base_dir),
                drop_metadata_by_symbol=deep_drop_metadata,
            )
            append_ledger_row(
                base_dir=Path(ledger_base_dir),
                lane="shared",
                row=deep_selection_row,
            )

        return {
            "run_id": shortlist["run_id"],
            "date": shortlist["date"],
            "canonical_sector_map": {
                str(item["symbol"]): self._normalized_sector_label(item.get("sector"))
                for item in shortlist["candidates"]
            },
            "items": items,
            "deep_k": deep_k,
            "selected_queue_ids": selected_ids,
            "source_artifact": f"eval_results/deal_flow/{shortlist['date']}/shortlist_top20.json",
        }

    def _select_for_deep(
        self,
        items: List[ResearchQueueItem],
        deep_k: int,
        core_quota: int,
        momentum_quota: int,
    ) -> List[str]:
        if not items or deep_k <= 0:
            return []

        core = [i for i in items if i.get("lane") == "CORE"]
        momentum = [i for i in items if i.get("lane") == "MOMENTUM"]
        core.sort(key=lambda i: -float(i.get("triage_score", 0.0)))
        momentum.sort(key=lambda i: -float(i.get("triage_score", 0.0)))

        selected: List[ResearchQueueItem] = []
        selected.extend(core[: min(core_quota, deep_k)])
        remaining_slots = deep_k - len(selected)
        selected.extend(momentum[: min(momentum_quota, remaining_slots)])

        # Fallback to best remaining candidates regardless of lane.
        if len(selected) < deep_k:
            selected_ids = {i["queue_id"] for i in selected}
            remaining = [i for i in items if i["queue_id"] not in selected_ids]
            remaining.sort(key=lambda i: -float(i.get("triage_score", 0.0)))
            selected.extend(remaining[: deep_k - len(selected)])

        return [i["queue_id"] for i in selected[:deep_k]]

    def _ensure_manual_deep_selection(
        self,
        items: List[ResearchQueueItem],
        selected_ids: List[str],
        deep_k: int,
    ) -> List[str]:
        manual_items = [
            item
            for item in items
            if str(item.get("source", "AUTO")).upper() == "MANUAL"
        ]
        if not manual_items or deep_k <= 0:
            return selected_ids

        selected_set = set(selected_ids)
        if any(item["queue_id"] in selected_set for item in manual_items):
            return selected_ids

        manual_items.sort(key=lambda i: -float(i.get("triage_score", 0.0)))
        selected_manual = manual_items[0]

        selected_rows = [item for item in items if item["queue_id"] in selected_set]
        removable = [
            item
            for item in selected_rows
            if str(item.get("source", "AUTO")).upper() != "MANUAL"
        ]
        if removable:
            removable.sort(key=lambda i: float(i.get("triage_score", 0.0)))
            selected_set.discard(removable[0]["queue_id"])
        elif len(selected_set) >= deep_k:
            # All selected items are manual already, nothing to change.
            return selected_ids

        selected_set.add(selected_manual["queue_id"])
        ordered = [
            item["queue_id"]
            for item in sorted(items, key=lambda i: -float(i.get("triage_score", 0.0)))
            if item["queue_id"] in selected_set
        ]
        return ordered[:deep_k]

    def _inject_force_queue_candidates(
        self,
        items: List[ResearchQueueItem],
        selected_ids: List[str],
        deep_k: int,
        reserve_quota: int,
        run_id: str,
    ) -> Tuple[List[ResearchQueueItem], List[str]]:
        """Inject IV force-queue candidates into the research queue reserve slots.

        Reserve slots = reserve_quota - manual_count. IV candidates fill remaining
        reserve slots without displacing any auto-ranked selections.
        """
        force_queue = getattr(self, "_iv_force_queue", None) or []
        # Disk fallback: read persisted IV force_queue when discover() wasn't called
        if not force_queue:
            try:
                fq_date = run_id.split("-", 3)  # YYYY-MM-DD-...
                if len(fq_date) >= 3:
                    fq_date_str = "-".join(fq_date[:3])
                    fq_path = Path("eval_results") / "deal_flow" / fq_date_str / "iv_force_queue.json"
                    if fq_path.is_file():
                        force_queue = json.loads(fq_path.read_text())
            except Exception:
                pass
        if not force_queue or reserve_quota <= 0:
            return items, selected_ids

        # Count manual items already selected for deep analysis.
        selected_set = set(selected_ids)
        manual_count = sum(
            1 for item in items
            if item["queue_id"] in selected_set
            and str(item.get("source", "")).upper() == "MANUAL"
        )
        available_reserve = max(0, reserve_quota - manual_count)
        if available_reserve <= 0:
            return items, selected_ids

        # Build a lookup of existing scored candidates for score reuse.
        existing_map = {
            str(item.get("symbol", "")).upper(): item for item in items
        }

        injected = 0
        for fq_entry in force_queue:
            if injected >= available_reserve:
                break
            symbol = str(fq_entry.get("symbol", "")).upper().strip()
            if not symbol:
                continue
            queue_id = f"{run_id}:{symbol}"
            # Skip if this symbol is already in the queue.
            if symbol in existing_map:
                existing = existing_map[symbol]
                if existing["queue_id"] not in selected_set:
                    existing["selected_for_deep"] = True
                    selected_ids.append(existing["queue_id"])
                    selected_set.add(existing["queue_id"])
                    injected += 1
                continue

            # Synthesize a stub item for symbols not already in the queue.
            stub = self._synthesize_manual_candidate(symbol, lane_preference="CORE")
            item: ResearchQueueItem = {
                "queue_id": queue_id,
                "symbol": symbol,
                "asset_class": stub.get("asset_class", "Equity"),
                "sector": self._normalized_sector_label(stub.get("sector")),
                "lane": "RESERVE",
                "deal_flow_score": float(stub.get("deal_flow_score", 50.0)),
                "momentum_score": float(stub.get("momentum_score", 50.0)),
                "asymmetry_score": float(stub.get("asymmetry_score", 50.0)),
                "subscores": {},
                "thesis_tags": ["iv-force-queue"],
                "risk_tags": ["IV force-queue override"],
                "evidence": {
                    "active_families": 0,
                    "evidence_count": 0,
                    "freshness_hours": 0.0,
                },
                "why_now": f"IV divergence detected — earnings play force-queued",
                "source": "IV_FORCE_QUEUE",
                "source_detail": "IV_SCANNER",
                "manual_note": str(fq_entry.get("reason", "")),
                "research_playbook": "iv_force_queue",
                "triage_score": 0.0,
                "selected_for_deep": True,
            }
            items.append(item)
            selected_ids.append(queue_id)
            selected_set.add(queue_id)
            existing_map[symbol] = item
            injected += 1

        return items, selected_ids

    # ETFs / leveraged index products that never need deep analysis
    _SKIP_DEEP_ANALYSIS = frozenset({
        "QQQ", "TQQQ", "SQQQ", "SPY", "VOO", "IVV", "IWM",
        "DIA", "VTI", "SPXL", "SPXS", "UPRO", "SH", "SSO",
    })

    def _inject_held_positions(
        self,
        items: List[ResearchQueueItem],
        selected_ids: List[str],
        run_id: str,
    ) -> Tuple[List[ResearchQueueItem], List[str]]:
        """Ensure held equity positions are always selected for deep analysis.

        Reads positions.json and guarantees every open equity position enters
        the research queue as selected — so scores refresh every pipeline run.
        Skips ETFs and leveraged index products (no thesis to rescore).
        """
        positions_path = Path("eval_results/paper_execution/positions.json")
        if not positions_path.exists():
            return items, selected_ids
        try:
            held = json.loads(positions_path.read_text()).get("open_positions", {})
        except Exception:
            return items, selected_ids
        if not held:
            return items, selected_ids

        selected_set = set(selected_ids)
        existing_map = {str(item.get("symbol", "")).upper(): item for item in items}

        for symbol in held:
            symbol = symbol.upper().strip()
            if not symbol:
                continue

            # Skip ETFs / leveraged index products — no thesis to rescore
            if symbol in self._SKIP_DEEP_ANALYSIS:
                continue
            existing_item = existing_map.get(symbol)
            if existing_item and existing_item.get("asset_class") in {"ETF", "CommodityProxy"}:
                continue

            queue_id = f"{run_id}:{symbol}"

            # Already in queue — just ensure it's selected
            if symbol in existing_map:
                existing = existing_map[symbol]
                if existing["queue_id"] not in selected_set:
                    selected_ids.append(existing["queue_id"])
                    selected_set.add(existing["queue_id"])
                continue

            # Not in queue — synthesize a stub item
            stub = self._synthesize_manual_candidate(symbol, lane_preference="CORE")
            # Check asset_class from AKG lookup — skip ETFs
            if stub.get("asset_class") in {"ETF", "CommodityProxy"}:
                continue
            item: ResearchQueueItem = {
                "queue_id": queue_id,
                "symbol": symbol,
                "asset_class": stub.get("asset_class", "Equity"),
                "sector": self._normalized_sector_label(stub.get("sector")),
                "lane": "PORTFOLIO",
                "deal_flow_score": float(stub.get("deal_flow_score", 50.0)),
                "momentum_score": float(stub.get("momentum_score", 50.0)),
                "asymmetry_score": float(stub.get("asymmetry_score", 50.0)),
                "subscores": {},
                "thesis_tags": ["held-position"],
                "risk_tags": ["held-position-rescore"],
                "evidence": {
                    "active_families": 0,
                    "evidence_count": 0,
                    "freshness_hours": 0.0,
                },
                "why_now": "Held position — mandatory score refresh",
                "source": "PORTFOLIO",
                "source_detail": "positions.json",
                "manual_note": "",
                "research_playbook": None,
                "triage_score": 0.0,
                "selected_for_deep": True,
            }
            items.append(item)
            selected_ids.append(queue_id)
            selected_set.add(queue_id)

        return items, selected_ids

    def _build_momentum_board(self, shortlist: DealFlowShortlist) -> Dict[str, object]:
        momentum_rows = [
            {
                "symbol": c.get("symbol"),
                "lane": c.get("lane"),
                "momentum_score": c.get("momentum_score"),
                "asymmetry_score": c.get("asymmetry_score"),
                "risk_tags": c.get("risk_tags", []),
                "trend_tags": c.get("trend_tags", []),
            }
            for c in shortlist.get("candidates", [])
            if c.get("lane") == "MOMENTUM"
        ]
        momentum_rows.sort(key=lambda c: -float(c.get("asymmetry_score", 0.0)))
        return {
            "run_id": shortlist.get("run_id"),
            "date": shortlist.get("date"),
            "count": len(momentum_rows),
            "rows": momentum_rows,
        }

    def _triage_score(self, candidate: Dict) -> float:
        subs = candidate.get("subscores", {})
        lane = str(candidate.get("lane", "CORE"))
        core = float(candidate.get("core_score", candidate.get("deal_flow_score", 0.0)))
        momentum = float(candidate.get("momentum_score", 0.0))
        asymmetry = float(candidate.get("asymmetry_score", 0.0))
        news = float(subs.get("news_catalyst", 50.0))
        macro = float(subs.get("macro_regime_fit", 50.0))
        freshness = float(candidate.get("freshness_hours", 9999.0))

        freshness_bonus = max(0.0, 10.0 - min(10.0, freshness / 12.0))
        if lane == "MOMENTUM":
            return 0.40 * momentum + 0.30 * asymmetry + 0.20 * news + 0.10 * macro + freshness_bonus
        return 0.55 * core + 0.25 * news + 0.20 * macro + freshness_bonus

    def _thesis_tags(self, candidate: Dict) -> List[str]:
        subs = candidate.get("subscores", {})
        tags: List[str] = []

        if float(subs.get("social_momentum", 0.0)) >= 70.0:
            tags.append("social-momentum")
        if float(subs.get("price_momentum", 0.0)) >= 70.0:
            tags.append("price-momentum")
        if float(subs.get("macro_regime_fit", 0.0)) >= 65.0:
            tags.append("macro-tailwind")
        if float(subs.get("news_catalyst", 0.0)) >= 70.0:
            tags.append("news-catalyst")
        if candidate.get("asset_class") in {"ETF", "CommodityProxy"}:
            tags.append("macro-hedge")
        if candidate.get("lane") == "MOMENTUM":
            tags.append("asymmetric-upside")

        if not tags:
            tags.append("balanced")
        return tags

    def _resolve_universe_ledger(
        self,
        universe: List[Any] | Tuple[Any, ...] | None,
        snapshot: Dict[str, Any] | None,
    ) -> Dict[str, Any]:
        kept_symbols = self._universe_symbols(universe)
        snapshot = dict(snapshot or {})
        snapshot_kept = self._universe_symbols(snapshot.get("kept_symbols", []))
        if set(snapshot_kept) == set(kept_symbols):
            kept_symbols = snapshot_kept
        else:
            snapshot = {}

        candidate_drop_symbols = self._universe_symbols(snapshot.get("candidate_drop_symbols", []))
        haystack_drop_symbols = self._universe_symbols(snapshot.get("haystack_drop_symbols", []))
        rule_snapshot = dict(snapshot.get("rule_snapshot", {}))
        rule_snapshot.setdefault(
            "filter_enabled",
            bool(self.config.get("dealflow_universe_filter_enabled", True)),
        )
        rule_snapshot.setdefault("kept_count", len(kept_symbols))
        rule_snapshot.setdefault("candidate_drop_count", len(candidate_drop_symbols))
        rule_snapshot.setdefault("haystack_drop_count", len(haystack_drop_symbols))

        return {
            "kept_symbols": kept_symbols,
            "candidate_drop_symbols": candidate_drop_symbols,
            "haystack_drop_symbols": haystack_drop_symbols,
            "rule_snapshot": rule_snapshot,
        }

    def _universe_symbols(self, universe: Any) -> List[str]:
        symbols: List[str] = []
        seen: set[str] = set()
        if not isinstance(universe, (list, tuple)):
            return symbols
        for entry in universe:
            if isinstance(entry, dict):
                symbol = str(entry.get("symbol", "")).upper().strip()
            else:
                symbol = str(entry).upper().strip()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            symbols.append(symbol)
        return symbols

    def _build_universe_drop_metadata(
        self,
        *,
        stage_id: str,
        dropped_symbols: List[str],
        universe_ledger: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        metadata: Dict[str, Dict[str, Any]] = {}
        rule_snapshot = dict(universe_ledger.get("rule_snapshot", {}))
        tier_map = dict(getattr(self, "_last_universe_tier_map", {}) or {})

        for symbol in self._universe_symbols(dropped_symbols):
            in_tier_map = symbol in tier_map
            tier_label = str(tier_map.get(symbol, "")).strip() or None
            if stage_id == "universe_gate_haystack":
                if in_tier_map:
                    reason_code = "UNIVERSE_TIER_PRESENT_BUT_EXCLUDED"
                    reason_text = "Symbol mapped to a universe tier but still absent from filtered universe."
                else:
                    reason_code = "UNIVERSE_NOT_IN_ACTIVE_TIERS"
                    reason_text = "Symbol was not mapped into any active universe tier in this cycle."
            else:
                reason_code = "UNIVERSE_CANDIDATE_GATE_EXCLUDED"
                reason_text = "Symbol failed universe candidate gate and did not enter the filtered universe."
            metadata[symbol] = {
                "reason_code": reason_code,
                "reason_text": reason_text,
                "threshold": dict(rule_snapshot),
                "observed_value": {
                    "in_filtered_universe": False,
                    "in_tier_map": bool(in_tier_map),
                    "tier": tier_label,
                },
                "delta_to_pass": 1,
            }
        return metadata

    def _build_evidence_gate_drop_metadata(
        self,
        *,
        all_scored_candidates: List[Dict[str, Any]],
        min_signal_families: int,
        min_evidence_count: int,
    ) -> Dict[str, Dict[str, Any]]:
        metadata: Dict[str, Dict[str, Any]] = {}
        for candidate in all_scored_candidates:
            symbol = self._normalize_symbol(candidate.get("symbol", ""))
            if not symbol:
                continue
            status = str(candidate.get("status", "")).upper().strip()
            if status != "LOW_DATA":
                continue
            active_families = int(candidate.get("active_families", 0) or 0)
            evidence_count = int(candidate.get("evidence_count", 0) or 0)
            family_gap = max(0, int(min_signal_families) - active_families)
            evidence_gap = max(0, int(min_evidence_count) - evidence_count)

            if family_gap > 0 and evidence_gap > 0:
                reason_code = "EVIDENCE_GATE_FAMILIES_AND_COUNT_BELOW_MIN"
                reason_text = "Signal-family coverage and evidence count were both below gate minimums."
                delta_to_pass: Any = {
                    "signal_families": family_gap,
                    "evidence_count": evidence_gap,
                }
            elif family_gap > 0:
                reason_code = "EVIDENCE_GATE_SIGNAL_FAMILIES_BELOW_MIN"
                reason_text = "Signal-family coverage was below minimum."
                delta_to_pass = family_gap
            else:
                reason_code = "EVIDENCE_GATE_EVIDENCE_COUNT_BELOW_MIN"
                reason_text = "Evidence count was below minimum."
                delta_to_pass = evidence_gap

            metadata[symbol] = {
                "reason_code": reason_code,
                "reason_text": reason_text,
                "threshold": {
                    "min_signal_families": int(min_signal_families),
                    "min_evidence_count": int(min_evidence_count),
                },
                "observed_value": {
                    "active_families": active_families,
                    "evidence_count": evidence_count,
                    "status": status,
                },
                "delta_to_pass": delta_to_pass,
            }
        return metadata

    def _build_shortlist_drop_metadata(
        self,
        *,
        all_scored_candidates: List[Dict[str, Any]],
        dropped_symbols: List[str],
        top_k: int,
        rule_snapshot: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        metadata: Dict[str, Dict[str, Any]] = {}
        dropped_set = set(self._universe_symbols(dropped_symbols))
        candidate_map: Dict[str, Dict[str, Any]] = {}
        active_rows: List[Dict[str, Any]] = []

        for candidate in all_scored_candidates:
            symbol = self._normalize_symbol(candidate.get("symbol", ""))
            if not symbol:
                continue
            candidate_map[symbol] = dict(candidate)
            status = str(candidate.get("status", "")).upper().strip()
            if status != "ACTIVE":
                continue
            active_rows.append(
                {
                    "symbol": symbol,
                    "momentum_score": _coerce_float(candidate.get("momentum_score")),
                    "core_score": _coerce_float(candidate.get("core_score")),
                    "lane": str(candidate.get("lane", "")).upper().strip(),
                }
            )

        active_rows.sort(
            key=lambda row: (
                -(row["momentum_score"] if row["momentum_score"] is not None else -1e9),
                -(row["core_score"] if row["core_score"] is not None else -1e9),
                str(row["symbol"]),
            )
        )
        rank_by_symbol = {row["symbol"]: idx for idx, row in enumerate(active_rows, start=1)}

        for symbol in dropped_set:
            candidate = dict(candidate_map.get(symbol, {}))
            status = str(candidate.get("status", "")).upper().strip()
            momentum_score = _coerce_float(candidate.get("momentum_score"))
            core_score = _coerce_float(candidate.get("core_score"))
            lane = str(candidate.get("lane", "")).upper().strip()
            rank = rank_by_symbol.get(symbol)

            if status and status != "ACTIVE":
                reason_code = "UPSTREAM_EVIDENCE_GATE_LOW_DATA"
                reason_text = "Symbol did not meet evidence gate and remained in LOW_DATA state."
                threshold = {"required_status": "ACTIVE"}
                observed_value = {
                    "status": status,
                    "active_families": int(candidate.get("active_families", 0) or 0),
                    "evidence_count": int(candidate.get("evidence_count", 0) or 0),
                }
                delta_to_pass = 1
            elif rank is not None and int(top_k) > 0 and rank > int(top_k):
                reason_code = "RANK_BELOW_SHORTLIST_CUT"
                reason_text = "Active rank was below shortlist top_k cutoff."
                threshold = {"top_k": int(top_k)}
                observed_value = {
                    "rank": int(rank),
                    "momentum_score": momentum_score,
                    "core_score": core_score,
                    "lane": lane,
                }
                delta_to_pass = int(rank) - int(top_k)
            elif rank is not None:
                reason_code = "SHORTLIST_POLICY_EXCLUSION"
                reason_text = "Rank was competitive but shortlist policy/quotas excluded the symbol."
                threshold = dict(rule_snapshot)
                observed_value = {
                    "rank": int(rank),
                    "momentum_score": momentum_score,
                    "core_score": core_score,
                    "lane": lane,
                }
                delta_to_pass = 1
            else:
                reason_code = "SHORTLIST_INPUT_MISSING"
                reason_text = "Symbol was absent from active ranking inputs at shortlist stage."
                threshold = dict(rule_snapshot)
                observed_value = {"status": status or None}
                delta_to_pass = 1

            metadata[symbol] = {
                "reason_code": reason_code,
                "reason_text": reason_text,
                "threshold": threshold,
                "observed_value": observed_value,
                "delta_to_pass": delta_to_pass,
            }
        return metadata

    def _build_deep_selection_drop_metadata(
        self,
        *,
        items: List[ResearchQueueItem],
        selected_id_set: set[str],
        suppressed_queue_ids: set[str],
        deep_selection_rule_snapshot: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        metadata: Dict[str, Dict[str, Any]] = {}

        eligible = [
            item for item in items
            if str(item.get("queue_id", "")).strip() and item.get("queue_id") not in suppressed_queue_ids
        ]
        eligible.sort(
            key=lambda row: (
                -float(row.get("triage_score", 0.0)),
                self._normalize_symbol(row.get("symbol", "")),
            )
        )
        rank_by_queue_id = {
            str(item.get("queue_id")): idx
            for idx, item in enumerate(eligible, start=1)
            if str(item.get("queue_id", "")).strip()
        }
        final_deep_k = int(deep_selection_rule_snapshot.get("final_deep_k", 0) or 0)

        for item in items:
            queue_id = str(item.get("queue_id", "")).strip()
            if not queue_id or queue_id in selected_id_set:
                continue
            symbol = self._normalize_symbol(item.get("symbol", ""))
            if not symbol:
                continue
            lane = str(item.get("lane", "")).upper().strip()
            triage_score = _coerce_float(item.get("triage_score"))
            rank = rank_by_queue_id.get(queue_id)

            if queue_id in suppressed_queue_ids:
                reason_code = "NEGATIVE_CONSTRAINT_SUPPRESSED"
                reason_text = "Operator negative constraints suppressed deep-selection eligibility."
                threshold = {"constraint_pass_required": True}
                observed_value = {
                    "suppressed": True,
                    "lane": lane,
                    "triage_score": triage_score,
                }
                delta_to_pass = 1
            elif rank is not None and final_deep_k > 0 and rank > final_deep_k:
                reason_code = "TRIAGE_RANK_BELOW_DEEP_CUT"
                reason_text = "Triage rank was below final deep-selection cutoff."
                threshold = {"final_deep_k": final_deep_k}
                observed_value = {
                    "triage_rank": int(rank),
                    "triage_score": triage_score,
                    "lane": lane,
                }
                delta_to_pass = int(rank) - final_deep_k
            elif rank is not None:
                reason_code = "DEEP_SELECTION_POLICY_EXCLUSION"
                reason_text = "Symbol was not selected after deep-selection quota/policy balancing."
                threshold = dict(deep_selection_rule_snapshot)
                observed_value = {
                    "triage_rank": int(rank),
                    "triage_score": triage_score,
                    "lane": lane,
                }
                delta_to_pass = 1
            else:
                reason_code = "DEEP_SELECTION_RANK_UNAVAILABLE"
                reason_text = "Deep-selection rank could not be resolved for this queue item."
                threshold = dict(deep_selection_rule_snapshot)
                observed_value = {
                    "triage_score": triage_score,
                    "lane": lane,
                }
                delta_to_pass = 1

            metadata[symbol] = {
                "reason_code": reason_code,
                "reason_text": reason_text,
                "threshold": threshold,
                "observed_value": observed_value,
                "delta_to_pass": delta_to_pass,
            }
        return metadata

    def _persist(
        self,
        as_of_date: str,
        normalized_signals: List[Dict],
        shortlist: DealFlowShortlist,
        research_queue: ResearchQueue,
        cashtag_events: List[Dict],
        momentum_board: Dict[str, object],
        connector_health: List[Dict[str, Any]],
        family_contribution_report: Dict[str, Any],
        manual_merge: Dict[str, Any],
        all_scored_candidates: Optional[List[Dict]] = None,
    ) -> None:
        base = Path("eval_results") / "deal_flow" / as_of_date
        base.mkdir(parents=True, exist_ok=True)
        universe_ledger = self._resolve_universe_ledger(
            getattr(self, "_last_universe", []),
            getattr(self, "_last_universe_ledger", {}),
        )
        for stage_id, dropped_symbols in (
            ("universe_gate_edge", list(universe_ledger.get("candidate_drop_symbols", []))),
            ("universe_gate_haystack", list(universe_ledger.get("haystack_drop_symbols", []))),
        ):
            universe_drop_metadata = self._build_universe_drop_metadata(
                stage_id=stage_id,
                dropped_symbols=list(dropped_symbols),
                universe_ledger=universe_ledger,
            )
            universe_row = make_ledger_row(
                run_id=str(shortlist.get("run_id", "")),
                source_date=as_of_date,
                lane="shared",
                stage_id=stage_id,
                rule_snapshot=dict(universe_ledger.get("rule_snapshot", {})),
                kept_symbols=list(universe_ledger.get("kept_symbols", [])),
                dropped_symbols=dropped_symbols,
                base_dir=base,
                drop_metadata_by_symbol=universe_drop_metadata,
            )
            append_ledger_row(base_dir=base, lane="shared", row=universe_row)

        min_signal_families = int(self.config.get("dealflow_min_signal_families", 3))
        min_evidence_count = 5
        active_symbols = [
            str(candidate.get("symbol", "")).upper().strip()
            for candidate in (all_scored_candidates or [])
            if str(candidate.get("status", "ACTIVE")).upper() == "ACTIVE"
        ]
        low_data_symbols = [
            str(candidate.get("symbol", "")).upper().strip()
            for candidate in (all_scored_candidates or [])
            if str(candidate.get("status", "")).upper() == "LOW_DATA"
        ]
        evidence_drop_metadata = self._build_evidence_gate_drop_metadata(
            all_scored_candidates=list(all_scored_candidates or []),
            min_signal_families=min_signal_families,
            min_evidence_count=min_evidence_count,
        )
        evidence_gate_row = make_ledger_row(
            run_id=str(shortlist.get("run_id", "")),
            source_date=as_of_date,
            lane="shared",
            stage_id="evidence_gate",
            rule_snapshot={
                "min_signal_families": min_signal_families,
                "min_evidence_count": min_evidence_count,
            },
            kept_symbols=active_symbols,
            dropped_symbols=low_data_symbols,
            base_dir=base,
            drop_metadata_by_symbol=evidence_drop_metadata,
        )
        append_ledger_row(base_dir=base, lane="shared", row=evidence_gate_row)
        shortlisted_symbols = {
            str(candidate.get("symbol", "")).upper().strip()
            for candidate in shortlist.get("candidates", [])
            if str(candidate.get("symbol", "")).strip()
        }
        dropped_symbols = [
            str(candidate.get("symbol", "")).upper().strip()
            for candidate in (all_scored_candidates or [])
            if str(candidate.get("symbol", "")).upper().strip() not in shortlisted_symbols
        ]
        shortlist_rule_snapshot = {
            "top_k": int(shortlist.get("top_k", 0) or 0),
            "core_quota": int(self.config.get("dealflow_core_quota", 18)),
            "momentum_quota": int(self.config.get("dealflow_momentum_quota", 12)),
            "manual_merge_summary": dict(shortlist.get("manual_merge_summary", {})),
        }
        shortlist_drop_metadata = self._build_shortlist_drop_metadata(
            all_scored_candidates=list(all_scored_candidates or []),
            dropped_symbols=dropped_symbols,
            top_k=int(shortlist.get("top_k", 0) or 0),
            rule_snapshot=shortlist_rule_snapshot,
        )
        shortlist_cut_row = make_ledger_row(
            run_id=str(shortlist.get("run_id", "")),
            source_date=as_of_date,
            lane="shared",
            stage_id="shortlist_cut",
            rule_snapshot=shortlist_rule_snapshot,
            kept_symbols=[
                str(candidate.get("symbol", "")).upper().strip()
                for candidate in shortlist.get("candidates", [])
            ],
            dropped_symbols=dropped_symbols,
            base_dir=base,
            drop_metadata_by_symbol=shortlist_drop_metadata,
        )
        append_ledger_row(base_dir=base, lane="shared", row=shortlist_cut_row)

        (base / "signals_raw.json").write_text(json.dumps(normalized_signals, indent=2))
        (base / "connector_health.json").write_text(json.dumps(connector_health, indent=2))
        (base / "family_contributions.json").write_text(json.dumps(family_contribution_report, indent=2))
        (base / "cashtag_events.json").write_text(json.dumps(cashtag_events, indent=2))
        (base / "momentum_board.json").write_text(json.dumps(momentum_board, indent=2))
        (base / "manual_merge.json").write_text(json.dumps(manual_merge, indent=2))
        (base / "shortlist_top20.json").write_text(json.dumps(shortlist, indent=2))
        (base / "research_queue.json").write_text(json.dumps(research_queue, indent=2))
        # Full scored candidate list — all symbols that passed the evidence gate,
        # not just the top-k shortlist. Enables hindsight on the ranking cutoff.
        if all_scored_candidates:
            scored_slim = []
            shortlist_syms = {
                str(c.get("symbol", "")).upper() for c in shortlist.get("candidates", [])
            }
            for c in sorted(all_scored_candidates, key=lambda x: -float(x.get("momentum_score", 0))):
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

        latest_path = Path("eval_results") / "deal_flow" / "latest_research_queue.json"
        latest_path.parent.mkdir(parents=True, exist_ok=True)
        latest_path.write_text(json.dumps(research_queue, indent=2))

        # Grok provenance — join manual X-feed input with pipeline scores for backtest.
        grok_cache_path = Path("eval_results") / "x_feed" / as_of_date / "merged.json"
        if grok_cache_path.is_file():
            try:
                grok_data = json.loads(grok_cache_path.read_text())
                candidate_map = {
                    str(c.get("symbol", "")).upper(): c
                    for c in shortlist.get("candidates", [])
                }
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

    def _evaluate_event_trigger(self, as_of_date: str) -> EventTriggerResult:
        payload = get_event_state(
            as_of_date=as_of_date,
            config=self.config,
            market_shock_provider=self._market_shock_metrics,
        )
        return {
            "triggered": bool(payload.get("triggered")),
            "reasons": list(payload.get("reasons", []) or []),
            "metrics": dict(payload.get("metrics", {}) or {}),
        }

    def _market_shock_metrics(self) -> Tuple[Optional[float], Optional[float]]:
        try:
            frame = yf.download(["SPY", "^VIX"], period="10d", interval="1d", progress=False)
        except Exception:
            return None, None

        try:
            if frame.empty:
                return None, None

            spy = _extract_close(frame, "SPY")
            vix = _extract_close(frame, "^VIX")
            if len(spy) < 2 or len(vix) < 2:
                return None, None

            spy_move = ((spy.iloc[-1] - spy.iloc[-2]) / spy.iloc[-2]) * 100.0
            vix_jump = ((vix.iloc[-1] - vix.iloc[-2]) / vix.iloc[-2]) * 100.0
            return float(spy_move), float(vix_jump)
        except Exception:
            return None, None

    def _apply_manual_merge_policy(
        self,
        ranked_auto: List[Dict[str, Any]],
        candidates: List[Dict[str, Any]],
        manual_ideas: List[Dict[str, Any]],
        top_k: int,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        shortlist: List[Dict[str, Any]] = [dict(row) for row in ranked_auto[:top_k]]
        candidate_map = {
            str(row.get("symbol", "")).upper().strip(): dict(row) for row in candidates
        }
        selected_symbols = {
            str(row.get("symbol", "")).upper().strip() for row in shortlist if row.get("symbol")
        }

        for row in shortlist:
            row["source"] = str(row.get("source", "AUTO")).upper()
            row["manual_note"] = str(row.get("manual_note", ""))
            row["manual_priority"] = int(row.get("manual_priority", 0) or 0)

        min_slots = int(self.config.get("dealflow_manual_slots_min", 2))
        max_slots = int(self.config.get("dealflow_manual_slots_max", 4))
        target_slots = int(self.config.get("dealflow_manual_slots_target", 3))
        target_slots = max(min_slots, min(max_slots, target_slots))
        min_adv = float(self.config.get("dealflow_manual_min_adv_usd", 50_000_000))
        force_insert = bool(self.config.get("dealflow_manual_force_insert", True))
        max_sector_count = int(self.config.get("dealflow_max_sector_count", 5))
        max_asset_class_count = int(self.config.get("dealflow_max_asset_class_count", 8))

        decisions: List[Dict[str, Any]] = []
        include_candidates: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        reinforced = 0
        rejected = 0

        ordered_manual = sorted(
            [dict(idea) for idea in manual_ideas],
            key=lambda i: (
                -int(i.get("priority", 0) or 0),
                str(i.get("created_at", "")),
                str(i.get("symbol", "")),
            ),
        )

        for idea in ordered_manual:
            symbol = str(idea.get("symbol", "")).upper().strip()
            lane_pref = str(idea.get("lane_preference", "CORE")).upper()
            note = str(idea.get("note", ""))
            priority = int(idea.get("priority", 3) or 3)

            if not symbol:
                rejected += 1
                decisions.append(
                    self._manual_decision_row(
                        symbol="",
                        action="REJECTED",
                        reason="Missing symbol.",
                        priority=priority,
                        lane_preference=lane_pref,
                        note=note,
                    )
                )
                continue

            if symbol in selected_symbols:
                reinforced += 1
                self._mark_manual_reinforced(shortlist, symbol=symbol, note=note, priority=priority)
                decisions.append(
                    self._manual_decision_row(
                        symbol=symbol,
                        action="REINFORCED",
                        reason="Already present in auto shortlist; marked as manual reinforced.",
                        priority=priority,
                        lane_preference=lane_pref,
                        note=note,
                    )
                )
                continue

            candidate = candidate_map.get(symbol)
            if not candidate:
                candidate = self._synthesize_manual_candidate(
                    symbol=symbol,
                    lane_preference=lane_pref,
                )

            if str(candidate.get("status", "LOW_DATA")) != "ACTIVE":
                candidate = dict(candidate)
                candidate["status"] = "ACTIVE"
                tags = list(candidate.get("risk_tags", []))
                if "Manual override (low data)" not in tags:
                    tags.append("Manual override (low data)")
                candidate["risk_tags"] = tags
            else:
                candidate = dict(candidate)

            if lane_pref in {"CORE", "MOMENTUM"}:
                candidate["lane"] = lane_pref

            liquid_ok, adv = validate_symbol_liquidity(symbol=symbol, min_adv_usd=min_adv)
            if not liquid_ok:
                if not force_insert:
                    rejected += 1
                    decisions.append(
                        self._manual_decision_row(
                            symbol=symbol,
                            action="REJECTED",
                            reason=f"Liquidity gate failed (ADV={adv:.2f}, min={min_adv:.2f}).",
                            priority=priority,
                            lane_preference=lane_pref,
                            note=note,
                            lane=str(candidate.get("lane", "CORE")),
                        )
                    )
                    continue
                tags = list(candidate.get("risk_tags", []))
                if adv <= 0.0:
                    if "Manual liquidity unchecked" not in tags:
                        tags.append("Manual liquidity unchecked")
                else:
                    if "Manual liquidity override" not in tags:
                        tags.append("Manual liquidity override")
                candidate["risk_tags"] = tags

            include_candidates.append((idea, candidate))

        include_candidates.sort(
            key=lambda pair: (
                -int(pair[0].get("priority", 0) or 0),
                -self._manual_candidate_rank_score(pair[1], str(pair[0].get("lane_preference", "CORE"))),
                str(pair[1].get("symbol", "")),
            )
        )

        included = 0
        include_slots = min(len(include_candidates), target_slots)
        for idea, base_candidate in include_candidates:
            if included >= include_slots:
                break

            candidate = dict(base_candidate)
            symbol = str(candidate.get("symbol", "")).upper().strip()
            priority = int(idea.get("priority", 3) or 3)
            lane_pref = str(idea.get("lane_preference", "CORE")).upper()
            note = str(idea.get("note", ""))
            candidate["source"] = "MANUAL"
            candidate["source_detail"] = "MANUAL_WATCHLIST"
            candidate["manual_note"] = note
            candidate["manual_priority"] = priority
            risk_tags = list(candidate.get("risk_tags", []))
            if "Manual watchlist" not in risk_tags:
                risk_tags.append("Manual watchlist")
            candidate["risk_tags"] = risk_tags

            replace_idx = self._find_lowest_auto_index(shortlist)
            if replace_idx is None and len(shortlist) >= top_k:
                rejected += 1
                decisions.append(
                    self._manual_decision_row(
                        symbol=symbol,
                        action="REJECTED",
                        reason="No replaceable auto slot available.",
                        priority=priority,
                        lane_preference=lane_pref,
                        note=note,
                        lane=str(candidate.get("lane", "CORE")),
                    )
                )
                continue

            if not self._respects_diversification_caps(
                shortlist=shortlist,
                candidate=candidate,
                replace_idx=replace_idx,
                max_sector_count=max_sector_count,
                max_asset_class_count=max_asset_class_count,
            ):
                if not force_insert:
                    rejected += 1
                    decisions.append(
                        self._manual_decision_row(
                            symbol=symbol,
                            action="REJECTED",
                            reason="Diversification caps rejected insertion.",
                            priority=priority,
                            lane_preference=lane_pref,
                            note=note,
                            lane=str(candidate.get("lane", "CORE")),
                        )
                    )
                    continue
                tags = list(candidate.get("risk_tags", []))
                if "Manual cap override" not in tags:
                    tags.append("Manual cap override")
                candidate["risk_tags"] = tags

            replaced_symbol = None
            if replace_idx is not None and replace_idx < len(shortlist):
                replaced_symbol = str(shortlist[replace_idx].get("symbol", ""))
                shortlist.pop(replace_idx)
                selected_symbols.discard(replaced_symbol.upper().strip())
            shortlist.append(candidate)
            selected_symbols.add(symbol)
            included += 1

            reason = "Inserted via manual slot."
            if replaced_symbol:
                reason = f"Inserted via manual slot, replaced {replaced_symbol}."
            if "Manual cap override" in list(candidate.get("risk_tags", [])):
                reason += " Diversification cap override applied."
            if "Manual liquidity override" in list(candidate.get("risk_tags", [])):
                reason += " Liquidity override applied."
            if "Manual liquidity unchecked" in list(candidate.get("risk_tags", [])):
                reason += " Liquidity check unavailable."
            decisions.append(
                self._manual_decision_row(
                    symbol=symbol,
                    action="INCLUDED",
                    reason=reason,
                    priority=priority,
                    lane_preference=lane_pref,
                    note=note,
                    lane=str(candidate.get("lane", "CORE")),
                )
            )

        # Keep deterministic rank ordering after manual overlay.
        shortlist.sort(
            key=lambda row: (
                -self._candidate_rank_score(row),
                float(row.get("freshness_hours", 9999.0)),
                str(row.get("symbol", "")),
            )
        )
        shortlist = shortlist[:top_k]
        for idx, row in enumerate(shortlist, start=1):
            row["rank"] = idx

        rank_map = {
            str(row.get("symbol", "")).upper().strip(): int(row.get("rank", 0) or 0)
            for row in shortlist
        }
        for row in decisions:
            symbol = str(row.get("symbol", "")).upper().strip()
            row["selected_rank"] = rank_map.get(symbol)
        manual_symbols = sorted(
            {
                str(row.get("symbol", "")).upper().strip()
                for row in shortlist
                if str(row.get("source", "AUTO")).upper() == "MANUAL"
            }
        )
        summary = {
            "requested": len(ordered_manual),
            "included": included,
            "reinforced": reinforced,
            "rejected": rejected,
            "manual_symbols": manual_symbols,
            "decisions": decisions,
        }
        return shortlist, summary

    def _mark_manual_reinforced(
        self,
        shortlist: List[Dict[str, Any]],
        symbol: str,
        note: str,
        priority: int,
    ) -> None:
        target = symbol.upper().strip()
        for row in shortlist:
            row_symbol = str(row.get("symbol", "")).upper().strip()
            if row_symbol != target:
                continue
            row["source"] = "MANUAL"
            row["source_detail"] = "MANUAL_REINFORCED"
            row["manual_note"] = note
            row["manual_priority"] = int(max(priority, int(row.get("manual_priority", 0) or 0)))
            tags = list(row.get("risk_tags", []))
            if "Manual watchlist" not in tags:
                tags.append("Manual watchlist")
            if "Manual reinforced" not in tags:
                tags.append("Manual reinforced")
            row["risk_tags"] = tags
            return

    def _respects_diversification_caps(
        self,
        shortlist: List[Dict[str, Any]],
        candidate: Dict[str, Any],
        replace_idx: Optional[int],
        max_sector_count: int,
        max_asset_class_count: int,
    ) -> bool:
        trial: List[Dict[str, Any]] = []
        for idx, row in enumerate(shortlist):
            if replace_idx is not None and idx == replace_idx:
                continue
            trial.append(row)
        trial.append(candidate)

        sector_counts: Dict[str, int] = {}
        asset_counts: Dict[str, int] = {}
        for row in trial:
            sector = str(row.get("sector", "Unknown"))
            asset = str(row.get("asset_class", "Unknown"))
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
            asset_counts[asset] = asset_counts.get(asset, 0) + 1
            if sector_counts[sector] > max_sector_count:
                return False
            if asset_counts[asset] > max_asset_class_count:
                return False
        return True

    def _find_lowest_auto_index(self, shortlist: List[Dict[str, Any]]) -> Optional[int]:
        candidates: List[Tuple[int, float]] = []
        for idx, row in enumerate(shortlist):
            source = str(row.get("source", "AUTO")).upper()
            if source != "AUTO":
                continue
            candidates.append((idx, self._candidate_rank_score(row)))
        if not candidates:
            return None
        return min(candidates, key=lambda row: row[1])[0]

    def _candidate_rank_score(self, candidate: Dict[str, Any]) -> float:
        lane = str(candidate.get("lane", "CORE")).upper()
        if lane == "MOMENTUM":
            return float(candidate.get("asymmetry_score", candidate.get("deal_flow_score", 0.0)))
        return float(candidate.get("core_score", candidate.get("deal_flow_score", 0.0)))

    def _manual_candidate_rank_score(self, candidate: Dict[str, Any], lane_preference: str) -> float:
        lane = str(lane_preference or "").upper()
        if lane == "MOMENTUM":
            return float(candidate.get("asymmetry_score", candidate.get("momentum_score", 0.0)))
        if lane == "CORE":
            return float(candidate.get("core_score", candidate.get("deal_flow_score", 0.0)))
        return self._candidate_rank_score(candidate)

    def _manual_decision_row(
        self,
        symbol: str,
        action: str,
        reason: str,
        priority: int,
        lane_preference: str,
        note: str,
        lane: str = "CORE",
    ) -> Dict[str, Any]:
        return {
            "symbol": symbol,
            "action": action,
            "reason": reason,
            "priority": int(priority),
            "lane_preference": lane_preference if lane_preference in {"CORE", "MOMENTUM"} else "CORE",
            "note": note,
            "lane": lane if lane in {"CORE", "MOMENTUM"} else "CORE",
            "selected_rank": None,
        }

    def _infer_source_detail(self, candidate: Dict[str, Any], explicit_tags: Optional[set[str]] = None) -> str:
        source = str(candidate.get("source", "AUTO")).upper()
        if source == "MANUAL":
            return str(candidate.get("source_detail", "MANUAL_WATCHLIST"))

        subs = candidate.get("subscores", {}) if isinstance(candidate.get("subscores", {}), dict) else {}
        ranked = sorted(subs.items(), key=lambda kv: -float(kv[1]))
        labels: List[str] = list(sorted(explicit_tags or set()))
        for family, _ in ranked[:4]:
            if family in {"social_momentum", "news_catalyst"}:
                labels.append("WEB_NEWS")
            elif family == "smart_money":
                labels.append("SEC_CONGRESS")
            elif family == "price_momentum":
                labels.append("PRICE_ACTION")
            elif family == "macro_regime_fit":
                labels.append("MACRO")
        deduped: List[str] = []
        for label in labels:
            if label not in deduped:
                deduped.append(label)
        return "+".join(deduped[:3]) if deduped else "AUTO_MODEL"

    def _build_symbol_source_tags(self, signals: List[Dict[str, Any]]) -> Dict[str, set[str]]:
        symbol_tags: Dict[str, set[str]] = {}
        for signal in signals:
            if str(signal.get("source_status", "")).upper() != "OK":
                continue
            symbol = str(signal.get("symbol", "")).upper().strip()
            if not symbol:
                continue
            source_name = str(signal.get("source_name", "")).lower()
            tags = symbol_tags.setdefault(symbol, set())
            if "x_api" in source_name or "xai" in source_name or "cashtag" in source_name:
                tags.add("X_FEED")
            if "sec13f" in source_name or "congress" in source_name or "smart" in source_name:
                tags.add("SEC_CONGRESS")
            if "insider" in source_name:
                tags.add("INSIDER")
            if "google" in source_name or "news" in source_name:
                tags.add("WEB_NEWS")
        return symbol_tags

    def _watchlist_path(self) -> Path:
        configured = str(self.config.get("dealflow_manual_watchlist_path", "")).strip()
        if configured:
            return Path(configured)
        return Path("eval_results") / "deal_flow" / "manual_watchlist.json"

    def _synthesize_manual_candidate(self, symbol: str, lane_preference: str) -> Dict[str, Any]:
        lane = "MOMENTUM" if str(lane_preference).upper() == "MOMENTUM" else "CORE"
        normalized_symbol = self._normalize_symbol(symbol)
        inferred_asset_class = "Equity"
        inferred_sector = "Unclassified Equity"
        try:
            from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
            _akg = AeternusKnowledgeGraph.load()
            if normalized_symbol in _akg._nodes:
                node = _akg._nodes[normalized_symbol]
                inferred_asset_class = node.get("asset_class") or "Equity"
                inferred_sector = node.get("sector_gics") or "Unclassified Equity"
        except Exception:
            pass
        if not inferred_sector or inferred_sector == "Unclassified Equity":
            if inferred_asset_class == "CommodityProxy":
                inferred_sector = "Commodities"
            elif inferred_asset_class == "ETF":
                inferred_sector = "ETF"
        return {
            "symbol": normalized_symbol,
            "asset_class": inferred_asset_class,
            "sector": self._normalized_sector_label(inferred_sector),
            "liquidity_score": 50.0,
            "subscores": {},
            "deal_flow_score": 50.0,
            "core_score": 50.0,
            "momentum_score": 50.0,
            "asymmetry_score": 50.0,
            "active_families": 0,
            "evidence_count": 0,
            "freshness_hours": 9999.0,
            "status": "ACTIVE",
            "risk_tags": ["Manual override (no auto coverage)"],
            "trend_tags": [],
            "lane": lane,
            "source": "MANUAL",
            "source_detail": "MANUAL_WATCHLIST",
            "manual_note": "",
            "manual_priority": 0,
            "reason": "Manual watchlist override.",
        }

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        return str(symbol or "").upper().strip().replace(".", "-")

    @staticmethod
    def _normalized_sector_label(raw: Any) -> str:
        text = str(raw or "").strip()
        if not text or text.lower() in {"unknown", "n/a", "none", "nan"}:
            return "Unclassified Equity"
        return text


def _extract_close(frame: pd.DataFrame, symbol: str):
    if frame is None or frame.empty:
        return pd.Series(dtype=float)

    if isinstance(frame.columns, pd.MultiIndex):
        if ("Close", symbol) in frame.columns:
            return pd.to_numeric(frame[("Close", symbol)], errors="coerce").dropna()
        if (symbol, "Close") in frame.columns:
            return pd.to_numeric(frame[(symbol, "Close")], errors="coerce").dropna()
        if symbol in frame.columns.get_level_values(0):
            sub = frame[symbol]
            if "Close" in sub.columns:
                return pd.to_numeric(sub["Close"], errors="coerce").dropna()
        return pd.Series(dtype=float)

    if "Close" in frame.columns:
        return pd.to_numeric(frame["Close"], errors="coerce").dropna()

    return pd.Series(dtype=float)


def _is_first_friday(date_obj: dt.date) -> bool:
    return date_obj.weekday() == 4 and 1 <= date_obj.day <= 7


def _is_second_wednesday(date_obj: dt.date) -> bool:
    return date_obj.weekday() == 2 and 8 <= date_obj.day <= 14


def _is_last_business_day(date_obj: dt.date) -> bool:
    if date_obj.weekday() >= 5:
        return False

    next_day = date_obj + dt.timedelta(days=1)
    while next_day.month == date_obj.month:
        if next_day.weekday() < 5:
            return False
        next_day += dt.timedelta(days=1)
    return True
