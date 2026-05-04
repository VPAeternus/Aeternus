"""Live serving adapter for the registry-driven fundamental SEC shadow signal."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import requests

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.research.fundamental_autoresearch.prepare import build_prepared_rows_from_cache
from tradingagents.research.fundamental_autoresearch.registry import get_active_strategy
from tradingagents.research.fundamental_autoresearch.score import score_feature_row_with_weights
from tradingagents.research.fundamental_autoresearch.sec_fetch import (
    companyfacts_cache_path,
    fill_sec_cache_for_universe,
    resolve_ticker_cik_map,
    submissions_cache_path,
)
from tradingagents.research.fundamental_autoresearch.sector_map import get_large_cap_v1_sector_map


def _cache_root(config: dict[str, Any] | None) -> Path:
    cfg = config or DEFAULT_CONFIG
    return Path(
        cfg.get(
            "dealflow_fundamental_factor_cache_root",
            Path("eval_results") / "fundamental_autoresearch" / "sec_cache",
        )
    )


def _registry_results_root(config: dict[str, Any] | None) -> Path:
    cfg = config or DEFAULT_CONFIG
    return Path(
        cfg.get(
            "dealflow_fundamental_factor_registry_results_root",
            Path("eval_results") / "fundamental_autoresearch",
        )
    )


def _freshness_hours_from_feature_cache(
    ticker: str,
    *,
    cache_root: str | Path,
    now_ts: float | None = None,
) -> float:
    now_ts = time.time() if now_ts is None else now_ts
    cache_root = Path(cache_root)
    paths = [
        submissions_cache_path(ticker, cache_root=cache_root),
        companyfacts_cache_path(ticker, cache_root=cache_root),
    ]
    mtimes = [path.stat().st_mtime for path in paths if path.exists()]
    if not mtimes:
        return 9999.0
    newest = max(mtimes)
    return round((now_ts - newest) / 3600.0, 4)


def _ensure_live_sec_cache(
    tickers: list[str],
    *,
    cache_root: str | Path,
    config: dict[str, Any] | None,
) -> None:
    cfg = config or DEFAULT_CONFIG
    stale_hours = float(cfg.get("dealflow_fundamental_factor_max_cache_age_hours", 24.0))
    stale_seconds = stale_hours * 3600.0
    now_ts = time.time()

    needed: list[str] = []
    for ticker in tickers:
        submissions_path = submissions_cache_path(ticker, cache_root=cache_root)
        companyfacts_path = companyfacts_cache_path(ticker, cache_root=cache_root)
        if not submissions_path.exists() or not companyfacts_path.exists():
            needed.append(ticker)
            continue
        newest = max(submissions_path.stat().st_mtime, companyfacts_path.stat().st_mtime)
        if (now_ts - newest) > stale_seconds:
            needed.append(ticker)

    if not needed:
        return

    user_agent = str(cfg.get("dealflow_sec_user_agent", DEFAULT_CONFIG["dealflow_sec_user_agent"]))
    timeout = int(cfg.get("dealflow_fundamental_factor_sec_timeout", 30))
    with requests.Session() as session:
        ticker_to_cik = resolve_ticker_cik_map(
            needed,
            cache_root=cache_root,
            session=session,
            user_agent=user_agent,
            timeout=timeout,
        )
        fill_sec_cache_for_universe(
            needed,
            ticker_to_cik=ticker_to_cik,
            cache_root=cache_root,
            session=session,
            user_agent=user_agent,
            continue_on_error=True,
            include_history=False,
            timeout=timeout,
        )


def _build_live_feature_rows(
    universe: list[dict[str, Any]],
    *,
    as_of_date: str,
    config: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    equities = [
        row for row in universe
        if str(row.get("asset_class", "")).strip().upper() == "EQUITY"
    ]
    tickers = sorted(
        {
            str(row.get("symbol", "")).upper().strip()
            for row in equities
            if str(row.get("symbol", "")).strip()
        }
    )
    if not tickers:
        return {}

    cache_root = _cache_root(config)
    _ensure_live_sec_cache(tickers, cache_root=cache_root, config=config)

    large_cap_sector_map = get_large_cap_v1_sector_map()
    sector_map = {ticker: str(large_cap_sector_map.get(ticker) or "Unknown") for ticker in tickers}
    rows = build_prepared_rows_from_cache(
        cache_root=cache_root,
        universe=tickers,
        sector_map=sector_map,
        include_history=False,
        latest_only=True,
    )
    return {
        str(row.get("ticker", "")).upper().strip(): row
        for row in rows
        if str(row.get("ticker", "")).strip()
    }


def collect_fundamental_signals(
    universe: list[dict[str, Any]],
    *,
    as_of_date: str,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    cfg = config or DEFAULT_CONFIG
    equities = [
        row for row in universe
        if str(row.get("asset_class", "")).strip().upper() == "EQUITY"
    ]
    symbols = [
        str(row.get("symbol", "")).upper().strip()
        for row in equities
        if str(row.get("symbol", "")).strip()
    ]
    if not symbols:
        return []

    active = get_active_strategy(
        results_root=_registry_results_root(cfg),
        preferred_statuses=("promoted", "shadow"),
    )
    if not active:
        return [
            {
                "symbol": symbol,
                "signal_family": "fundamental_factor_shadow",
                "raw_score": 0.0,
                "z_score": 0.0,
                "direction": "NEUTRAL",
                "evidence_count": 0,
                "freshness_hours": 9999.0,
                "source_status": "NOT_CONFIGURED",
                "source_name": "sec_autoresearch_shadow:unconfigured",
            }
            for symbol in symbols
        ]

    strategy_name = str(active.get("strategy", "") or active.get("score_version", "") or "unknown")
    weights = dict(active.get("weights", {}) or active.get("component_weights", {}) or {})
    source_prefix = f"sec_autoresearch_shadow:{strategy_name}"

    feature_rows = _build_live_feature_rows(
        universe=equities,
        as_of_date=as_of_date,
        config=cfg,
    )

    signals: list[dict[str, Any]] = []
    for symbol in symbols:
        row = feature_rows.get(symbol)
        if not row:
            signals.append(
                {
                    "symbol": symbol,
                    "signal_family": "fundamental_factor_shadow",
                    "raw_score": 0.0,
                    "z_score": 0.0,
                    "direction": "NEUTRAL",
                    "evidence_count": 0,
                    "freshness_hours": 9999.0,
                    "source_status": "NO_DATA",
                    "source_name": source_prefix,
                }
            )
            continue

        scored = score_feature_row_with_weights(
            row,
            component_weights=weights,
            strategy_name=strategy_name,
        )
        freshness_hours = _freshness_hours_from_feature_cache(
            symbol,
            cache_root=_cache_root(cfg),
        )
        component_scores = [
            float(scored.growth_score),
            float(scored.quality_score),
            float(scored.health_score),
            float(scored.capital_discipline_score),
            float(scored.valuation_score),
        ]
        evidence_count = sum(1 for value in component_scores if value > 0)
        direction = "BULLISH" if float(scored.fundamental_score) >= 50.0 else "BEARISH"
        signals.append(
            {
                "symbol": symbol,
                "signal_family": "fundamental_factor_shadow",
                "raw_score": float(scored.fundamental_score),
                "z_score": 0.0,
                "direction": direction,
                "evidence_count": evidence_count,
                "freshness_hours": freshness_hours,
                "source_status": "OK",
                "source_name": source_prefix,
            }
        )

    return signals
