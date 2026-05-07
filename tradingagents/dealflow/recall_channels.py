"""FVG/FMA recall channel builders for dealflow discovery."""

from __future__ import annotations

import contextlib
import datetime as dt
import io
from typing import Any, Dict, List, Optional

import pandas as pd
import yfinance as yf

from .fma_recall import _build_fma_feature_frame, score_fma_cross_section
from .fvg_recall import _build_feature_frame, _extract_ohlcv_frame


def coerce_liquidity_score(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value:
        return None
    return value


def normalize_symbol(symbol: Any) -> str:
    return str(symbol or "").upper().strip()


def has_recent_yahoo_history(symbol: str) -> bool:
    normalized = normalize_symbol(symbol)
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
        return True
    extracted = _extract_ohlcv_frame(frame, normalized)
    return extracted is not None and not extracted.empty


def prune_invalid_recall_symbols(akg: Any, symbols: List[str]) -> List[str]:
    normalized = [normalize_symbol(symbol) for symbol in symbols]
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


def prepare_recall_market_data(
    *,
    akg: Any,
    candidate_symbols: List[str],
    as_of_date: str,
) -> Dict[str, Any]:
    deduped = sorted(dict.fromkeys(normalize_symbol(symbol) for symbol in candidate_symbols if symbol))
    if not deduped:
        return {"benchmark_frame": None, "candidate_symbols": [], "invalid_symbols_removed": [], "symbol_frames": {}}

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

    confirmed_missing = [symbol for symbol in missing_symbols if not has_recent_yahoo_history(symbol)]
    invalid_symbols_removed = prune_invalid_recall_symbols(akg, confirmed_missing)

    return {
        "benchmark_frame": benchmark_frame,
        "candidate_symbols": sorted(symbol_frames.keys()),
        "invalid_symbols_removed": invalid_symbols_removed,
        "symbol_frames": symbol_frames,
    }


def preflight_akg_liquidity(as_of_date: str, config: Dict[str, Any]) -> Dict[str, Any]:
    min_coverage = float(config.get("dealflow_liquidity_preflight_min_coverage", 0.80))
    max_age_days = int(config.get("dealflow_liquidity_preflight_max_age_days", 1))
    refresh_enabled = bool(config.get("dealflow_liquidity_preflight_refresh_enabled", True))
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
            if coerce_liquidity_score(node.get("liquidity_score")) is None:
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


def _candidate_symbols_from_akg(akg: Any, min_liquidity_score: float) -> List[str]:
    candidate_symbols: List[str] = []
    for node in akg._nodes.values():
        if node.get("node_type") != "company":
            continue
        symbol = normalize_symbol(node.get("id", ""))
        if not symbol:
            continue
        asset_class = str(node.get("asset_class") or "Equity")
        liquidity_score = coerce_liquidity_score(node.get("liquidity_score"))
        if asset_class != "Equity" or liquidity_score is None or liquidity_score < min_liquidity_score:
            continue
        candidate_symbols.append(symbol)
    return sorted(dict.fromkeys(candidate_symbols))


def build_fvg_recall_channel(as_of_date: str, config: Dict[str, Any]) -> Dict[str, Any]:
    liquidity_preflight = preflight_akg_liquidity(as_of_date, config)
    if not bool(config.get("dealflow_fvg_recall_enabled", True)):
        return {"selected_symbols": [], "artifact": {"date": as_of_date, "selected_symbols": [], "quota": 0, "rule_snapshot": {"enabled": False}}}

    quota = int(config.get("dealflow_fvg_recall_quota", 30))
    min_rs20 = float(config.get("dealflow_fvg_recall_min_rs20", 0.03))
    min_liquidity_score = float(config.get("dealflow_fvg_recall_min_liquidity_score", 30.0))
    selected_rows: List[Dict[str, Any]] = []

    try:
        from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
        akg = AeternusKnowledgeGraph.load()
        candidate_symbols = _candidate_symbols_from_akg(akg, min_liquidity_score)
        invalid_symbols_removed: List[str] = []
        if candidate_symbols:
            market_data = prepare_recall_market_data(akg=akg, candidate_symbols=candidate_symbols, as_of_date=as_of_date)
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
                selected_rows.append({"symbol": symbol, "score": float(row.get("score", 0.0) or 0.0), "relative_strength_20d": float(row.get("relative_strength_20d", 0.0) or 0.0), "sma50_above_sma200": bool(row.get("sma50_above_sma200", False)), "bullish_fvg_present": True})
    except Exception:
        selected_rows = []

    selected_rows.sort(key=lambda row: (-float(row.get("score", 0.0)), str(row.get("symbol", ""))))
    selected_rows = selected_rows[: max(0, quota)]
    artifact = {"date": as_of_date, "selected_symbols": [row["symbol"] for row in selected_rows], "quota": quota, "rows": selected_rows, "invalid_symbols_removed": invalid_symbols_removed if "invalid_symbols_removed" in locals() else [], "liquidity_preflight": liquidity_preflight, "rule_snapshot": {"enabled": True, "quota": quota, "min_rs20": min_rs20, "min_liquidity_score": min_liquidity_score, "required_confirmation": ["bullish_fvg_present", "relative_strength_20d", "sma50_above_sma200"]}}
    return {"selected_symbols": list(artifact["selected_symbols"]), "artifact": artifact}


def build_fma_recall_channel(as_of_date: str, config: Dict[str, Any]) -> Dict[str, Any]:
    liquidity_preflight = preflight_akg_liquidity(as_of_date, config)
    if not bool(config.get("dealflow_fma_recall_enabled", True)):
        return {"selected_symbols": [], "artifact": {"date": as_of_date, "selected_symbols": [], "quota": 0, "rule_snapshot": {"enabled": False}}}

    quota = int(config.get("dealflow_fma_recall_quota", 20))
    min_score = float(config.get("dealflow_fma_recall_min_score", 60.0))
    min_liquidity_score = float(config.get("dealflow_fvg_recall_min_liquidity_score", 30.0))
    snapshots: List[Dict[str, Any]] = []

    try:
        from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
        akg = AeternusKnowledgeGraph.load()
        candidate_symbols = _candidate_symbols_from_akg(akg, min_liquidity_score)
        invalid_symbols_removed: List[str] = []
        if candidate_symbols:
            market_data = prepare_recall_market_data(akg=akg, candidate_symbols=candidate_symbols, as_of_date=as_of_date)
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
                snapshots.append({"ticker": symbol, "variant": "fma_live", "valid": True, "velocity_60d": float(row.get("velocity_60d", 0.0) or 0.0), "accel_value": float(row.get("accel_value", 0.0) or 0.0), "mass_ratio": float(row.get("mass_ratio", 0.0) or 0.0), "force_value": float(row.get("force_value", 0.0) or 0.0), "relative_strength_60d": float(row.get("relative_strength_60d", 0.0) or 0.0)})
    except Exception:
        snapshots = []

    scores = score_fma_cross_section(snapshots, variant="fma_live")
    selected_rows: List[Dict[str, Any]] = []
    for snapshot in snapshots:
        symbol = str(snapshot.get("ticker", "")).upper().strip()
        score = float(scores.get(symbol, 0.0) or 0.0)
        if score < min_score:
            continue
        selected_rows.append({"symbol": symbol, "score": score, "velocity_60d": float(snapshot.get("velocity_60d", 0.0) or 0.0), "accel_value": float(snapshot.get("accel_value", 0.0) or 0.0), "mass_ratio": float(snapshot.get("mass_ratio", 0.0) or 0.0), "force_value": float(snapshot.get("force_value", 0.0) or 0.0), "relative_strength_60d": float(snapshot.get("relative_strength_60d", 0.0) or 0.0)})

    selected_rows.sort(key=lambda row: (-float(row.get("score", 0.0)), str(row.get("symbol", ""))))
    selected_rows = selected_rows[: max(0, quota)]
    artifact = {"date": as_of_date, "selected_symbols": [row["symbol"] for row in selected_rows], "quota": quota, "rows": selected_rows, "invalid_symbols_removed": invalid_symbols_removed if "invalid_symbols_removed" in locals() else [], "liquidity_preflight": liquidity_preflight, "rule_snapshot": {"enabled": True, "quota": quota, "min_score": min_score, "min_liquidity_score": min_liquidity_score, "required_confirmation": ["fma_live_score"]}}
    return {"selected_symbols": list(artifact["selected_symbols"]), "artifact": artifact}
