"""File-backed manual regime override for allocator simulation control.

Also provides VIX-to-RegimeShock bridge for automatic regime detection.
"""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Any, Optional

from tradingagents.dealflow.control_io import read_json_locked, write_json_locked

from .contracts import RegimeShock

logger = logging.getLogger(__name__)


def write_regime_override(
    *,
    path: str | Path,
    regime: RegimeShock,
    reason: str = "",
    source: str = "manual",
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    now_utc = _to_utc(now or dt.datetime.now(dt.timezone.utc))
    payload = {
        "regime": regime.value,
        "source": str(source or "manual"),
        "reason": str(reason or ""),
        "updated_at_utc": now_utc.isoformat(),
    }
    write_json_locked(Path(path), payload)
    return payload


def read_regime_override(path: str | Path) -> dict[str, Any]:
    payload = read_json_locked(Path(path))
    return payload if isinstance(payload, dict) else {}


def resolve_regime(
    *,
    path: str | Path,
    default: RegimeShock = RegimeShock.NORMAL,
) -> RegimeShock:
    payload = read_regime_override(path)
    raw = str(payload.get("regime") or "").strip().upper()
    if not raw:
        return default
    try:
        return RegimeShock(raw)
    except Exception:
        return default


def vix_to_regime_shock(vix_close: float) -> RegimeShock:
    """Map a raw VIX level to the allocator's RegimeShock severity ladder.

    Thresholds are aligned with the hedging engine's ``_classify_market_regime``
    so that both systems escalate consistently:

        VIX < 20   → NORMAL   (benign)
        20 ≤ VIX < 30 → STRESS (elevated vol, tighten concentration)
        30 ≤ VIX < 40 → SHOCK  (severe, reduce exposure)
        VIX ≥ 40   → CRISIS  (extreme, minimal new risk)
    """
    vix = float(vix_close)
    if vix >= 40.0:
        return RegimeShock.CRISIS
    if vix >= 30.0:
        return RegimeShock.SHOCK
    if vix >= 20.0:
        return RegimeShock.STRESS
    return RegimeShock.NORMAL


def hedging_regime_to_shock(hedging_regime: str) -> RegimeShock:
    """Map a hedging engine regime string to RegimeShock.

    The hedging engine produces 8 named regime labels; this collapses
    them onto the 4-level severity ladder used by the capital allocator.
    """
    regime = str(hedging_regime or "").upper().strip()
    _MAP = {
        "NEUTRAL": RegimeShock.NORMAL,
        "EUPHORIA": RegimeShock.NORMAL,
        "RISK_OFF": RegimeShock.STRESS,
        "HIGH_VOLATILITY": RegimeShock.STRESS,
        "BEAR": RegimeShock.SHOCK,
        "BEAR_STRESS": RegimeShock.SHOCK,
        "VOLATILITY_SHOCK": RegimeShock.SHOCK,
        "CRASH": RegimeShock.CRISIS,
    }
    return _MAP.get(regime, RegimeShock.NORMAL)


def auto_update_regime_from_vix(
    *,
    vix_close: float,
    override_path: str | Path,
    source: str = "vix_auto",
) -> dict[str, Any]:
    """Compute RegimeShock from VIX and persist to the override file.

    Call this from ``workflow-run`` so the allocator automatically
    reflects current market conditions instead of defaulting to NORMAL.
    """
    regime = vix_to_regime_shock(vix_close)
    result = write_regime_override(
        path=override_path,
        regime=regime,
        reason=f"VIX={vix_close:.2f}",
        source=source,
    )
    logger.info(
        "Regime auto-updated: %s (VIX=%.2f, path=%s)",
        regime.value, vix_close, override_path,
    )
    return result


def regime_update_step(override_path: str | Path) -> dict[str, Any]:
    """Fetch current VIX from MarketRegimeProvider and persist the regime override.

    Returns a result dict with keys ``"ok"``, ``"vix_close"``, ``"regime"``,
    and optionally ``"error"`` on failure.
    """
    try:
        from tradingagents.graph.market_regime import MarketRegimeProvider
    except Exception as exc:
        logger.error("regime_update_step: could not import MarketRegimeProvider: %s", exc)
        return {"ok": False, "error": f"import_failed: {exc}"}

    try:
        snapshot = MarketRegimeProvider().get_market_regime_snapshot()
    except Exception as exc:
        logger.error("regime_update_step: MarketRegimeProvider failed: %s", exc)
        return {"ok": False, "error": f"market_regime_snapshot_failed: {exc}"}

    if snapshot is None:
        return {"ok": False, "error": "market_regime_snapshot_returned_none"}

    vix_close = float(snapshot.get("vix_close", 0.0) or 0.0)
    if vix_close <= 0.0:
        return {"ok": False, "error": "invalid_vix_close", "vix_close": vix_close}

    try:
        written = auto_update_regime_from_vix(vix_close=vix_close, override_path=override_path)
    except Exception as exc:
        logger.error("regime_update_step: auto_update_regime_from_vix failed: %s", exc)
        return {"ok": False, "vix_close": vix_close, "error": f"write_failed: {exc}"}

    return {
        "ok": True,
        "vix_close": vix_close,
        "regime": written.get("regime"),
    }


def _to_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)

