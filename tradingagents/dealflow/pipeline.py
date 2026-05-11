"""Deal Flow Intelligence orchestration pipeline."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import yfinance as yf

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.context import get_event_state

from .collect_stage import run_collect_stage
from .contracts import EventTriggerResult
from .discovery_stage import run_discovery_stage
from .recall_channels import (
    build_fma_recall_channel,
    build_fvg_recall_channel,
    has_recent_yahoo_history,
    preflight_akg_liquidity,
    prepare_recall_market_data,
    prune_invalid_recall_symbols,
)
from .scout_audit_report import build_and_write_scout_audit


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


def collect_macro_signals(*args, **kwargs) -> List[Dict[str, Any]]:
    """Compatibility stub for removed macro collector; kept for legacy tests/patches."""
    return []


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


class DealFlowPipeline:
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or DEFAULT_CONFIG

    def run(
        self,
        as_of_date: str,
        trigger: str,
        top_k: int,
    ) -> Tuple[Dict[str, Any], Dict[str, Any], List[dict], EventTriggerResult]:
        self.discover(as_of_date=as_of_date, trigger=trigger)
        return self.collect(as_of_date=as_of_date, trigger=trigger, top_k=top_k)

    # ------------------------------------------------------------------
    # Stage 1: Discovery — scouts, watchlist, universe build
    # ------------------------------------------------------------------

    def discover(self, as_of_date: str, trigger: str) -> Dict[str, Any]:
        """Run all scouts and build universe. Stores results as instance attrs."""
        return run_discovery_stage(
            self,
            as_of_date=as_of_date,
            trigger=trigger,
            akg_available=_AKG_AVAILABLE,
            akg_cls=_AKG,
        )

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
        **_legacy_kwargs: Any,
    ) -> Dict[str, Any]:
        """Build a compact audit dict from scout return values."""
        audit = build_and_write_scout_audit(
            as_of_date=as_of_date,
            breakout_result=breakout_result,
            iv_result=iv_result,
            insider_result=insider_result,
            technical_ignition_result=technical_ignition_result,
            thirteenf_result=thirteenf_result,
        )
        self._last_scout_audit = audit
        return audit

    def _has_recent_yahoo_history(self, symbol: str) -> bool:
        return has_recent_yahoo_history(symbol)

    def _prune_invalid_recall_symbols(self, akg: Any, symbols: List[str]) -> List[str]:
        return prune_invalid_recall_symbols(akg, symbols)

    def _prepare_recall_market_data(
        self,
        *,
        akg: Any,
        candidate_symbols: List[str],
        as_of_date: str,
    ) -> Dict[str, Any]:
        return prepare_recall_market_data(
            akg=akg,
            candidate_symbols=candidate_symbols,
            as_of_date=as_of_date,
        )

    def _preflight_akg_liquidity(self, as_of_date: str) -> Dict[str, Any]:
        return preflight_akg_liquidity(as_of_date, self.config)

    def _build_fvg_recall_channel(self, as_of_date: str) -> Dict[str, Any]:
        return build_fvg_recall_channel(as_of_date, self.config)

    def _build_fma_recall_channel(self, as_of_date: str) -> Dict[str, Any]:
        return build_fma_recall_channel(as_of_date, self.config)

    # ------------------------------------------------------------------
    # Stage 2: Collection — persist scout-only ticker totals
    # ------------------------------------------------------------------

    def collect(
        self,
        as_of_date: str,
        trigger: str,
        top_k: int,
    ) -> Tuple[Dict[str, Any], Dict[str, Any], List[dict], EventTriggerResult]:
        """Persist scout-only ticker totals. Returns same tuple as run()."""
        return run_collect_stage(
            self,
            as_of_date=as_of_date,
            trigger=trigger,
            top_k=top_k,
            akg_available=_AKG_AVAILABLE,
            akg_cls=_AKG,
            deps={},
        )

    def evaluate_event_trigger(self, as_of_date: str) -> EventTriggerResult:
        return self._evaluate_event_trigger(as_of_date)

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

    def _watchlist_path(self) -> Path:
        configured = str(self.config.get("dealflow_manual_watchlist_path", "")).strip()
        if configured:
            return Path(configured)
        return Path("eval_results") / "deal_flow" / "manual_watchlist.json"

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
