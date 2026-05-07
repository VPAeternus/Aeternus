"""Regime transition detector — persists regime state and detects changes.

Two functions, no class. Uses _classify_market_regime from hedging.py
and MarketRegimeProvider for market data.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


def _load_json(path: str, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default if default is not None else {}


def _save_json(path: str, payload: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2))


def check_regime_transition(
    state_path: str = "eval_results/control/regime_state.json",
) -> Dict[str, Any]:
    """Check for regime change since last run.

    Fetches current market data, classifies regime, compares to persisted
    previous regime. Persists new state.

    Returns dict with: current_regime, previous_regime, transition_detected,
    transition_type, days_in_current_regime, spy_deviation_pct, vix, alert.
    """
    state = _load_json(state_path, {})
    previous_regime = state.get("current_regime", "")
    regime_since = state.get("regime_since", "")

    # Fetch current market data
    try:
        from tradingagents.graph.market_regime import MarketRegimeProvider
        from tradingagents.graph.hedging import _classify_market_regime

        provider = MarketRegimeProvider()
        snapshot = provider.get_market_regime_snapshot()
    except Exception:
        snapshot = None

    if snapshot is None:
        return {
            "current_regime": previous_regime or "UNKNOWN",
            "previous_regime": previous_regime,
            "transition_detected": False,
            "transition_type": "",
            "days_in_current_regime": _days_since(regime_since),
            "spy_deviation_pct": None,
            "vix": None,
            "alert": "",
            "data_available": False,
        }

    spy_close = float(snapshot["spy_close"])
    spy_sma200 = float(snapshot["spy_sma200"])
    vix_close = float(snapshot["vix_close"])

    # Classify current regime
    current_regime = _classify_market_regime(
        spy_close=spy_close,
        spy_sma200=spy_sma200,
        vix_close=vix_close,
        crash_trigger_active=False,  # Crash detection requires more data; keep advisory simple
    )

    spy_deviation_pct = (
        ((spy_close - spy_sma200) / spy_sma200 * 100.0) if spy_sma200 > 0 else 0.0
    )

    # Detect transition
    transition_detected = bool(previous_regime and previous_regime != current_regime)
    transition_type = (
        f"{previous_regime}\u2192{current_regime}" if transition_detected else ""
    )

    # Calculate days in current regime
    today = datetime.now().strftime("%Y-%m-%d")
    if transition_detected or not regime_since:
        regime_since = today
        days_in_regime = 0
    else:
        days_in_regime = _days_since(regime_since)

    # Build alert
    alert = _build_transition_alert(
        current_regime=current_regime,
        previous_regime=previous_regime,
        transition_detected=transition_detected,
        days_in_regime=days_in_regime,
    )

    # Persist new state
    new_state = {
        "current_regime": current_regime,
        "previous_regime": previous_regime if transition_detected else state.get("previous_regime", ""),
        "regime_since": regime_since,
        "last_checked": datetime.now().isoformat(),
        "spy_close": spy_close,
        "spy_sma200": spy_sma200,
        "vix_close": vix_close,
        "spy_deviation_pct": round(spy_deviation_pct, 2),
    }
    _save_json(state_path, new_state)

    return {
        "current_regime": current_regime,
        "previous_regime": previous_regime,
        "transition_detected": transition_detected,
        "transition_type": transition_type,
        "days_in_current_regime": days_in_regime,
        "spy_deviation_pct": round(spy_deviation_pct, 2),
        "vix": round(vix_close, 2),
        "alert": alert,
        "data_available": True,
    }


def _build_transition_alert(
    current_regime: str,
    previous_regime: str,
    transition_detected: bool,
    days_in_regime: int,
) -> str:
    """Build alert string. Empty if no actionable alert."""
    if transition_detected:
        if current_regime == "CRASH":
            return "CRASH REGIME: Capital preservation mode."
        if previous_regime == "BULL" and current_regime in ("BEAR", "BEAR_STRESS"):
            return f"REGIME CHANGE: {previous_regime}\u2192{current_regime}. Review all positions."
        if previous_regime in ("BEAR", "BEAR_STRESS") and current_regime == "BULL":
            return f"REGIME CHANGE: {previous_regime}\u2192{current_regime}. Evaluate adding risk."
        return f"REGIME CHANGE: {previous_regime}\u2192{current_regime}."

    if days_in_regime > 60:
        return (
            f"Sustained {current_regime} {days_in_regime} days "
            f"\u2014 assumptions may be stale."
        )

    return ""


def _days_since(date_str: str) -> int:
    """Return days since an ISO date string. 0 if invalid or empty."""
    if not date_str:
        return 0
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return max(0, (datetime.now() - d).days)
    except (ValueError, TypeError):
        return 0


def build_regime_alert(
    state_path: str = "eval_results/control/regime_state.json",
) -> str:
    """Build formatted regime alert for risk discussion. Empty if no transition."""
    result = check_regime_transition(state_path=state_path)
    alert = result.get("alert", "")
    if not alert:
        return ""

    lines = ["=== REGIME MONITOR ==="]
    lines.append(alert)
    lines.append(
        f"Current: {result['current_regime']} | "
        f"Days: {result['days_in_current_regime']} | "
        f"VIX: {result['vix']}"
    )
    if result.get("spy_deviation_pct") is not None:
        lines.append(f"SPY vs SMA200: {result['spy_deviation_pct']:+.1f}%")
    return "\n".join(lines)
