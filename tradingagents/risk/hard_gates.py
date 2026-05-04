"""Quantitative risk hard gates for pre-trade evaluation.

These gates supplement the LLM-based risk debate with deterministic,
non-overridable checks on position concentration, sector exposure,
and portfolio-level correlation risk.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def evaluate_hard_gates(
    plan: Dict[str, Any],
    open_positions: Dict[str, Any],
    capital_usd: float,
    *,
    max_sector_pct: float = 0.40,
    max_correlated_group_pct: float = 0.50,
    max_single_name_pct: float = 0.25,
    sector_map: Optional[Dict[str, str]] = None,
    correlation_groups: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    """Evaluate quantitative risk hard gates on a portfolio plan.

    Args:
        plan: Portfolio plan with ``orders`` list.
        open_positions: Current open positions dict (symbol -> row).
        capital_usd: Total portfolio capital for percentage calculations.
        max_sector_pct: Maximum exposure to any single sector as fraction
            of capital. Default 40%.
        max_correlated_group_pct: Maximum combined exposure for a
            correlated symbol group. Default 50%.
        max_single_name_pct: Maximum single-name concentration as
            fraction of capital. Default 25%.
        sector_map: Optional mapping of symbol -> sector string.
            If None, sector checks are skipped.
        correlation_groups: Optional mapping of group_name -> [symbols].
            If None, correlation checks are skipped.

    Returns:
        Dict with ``status``, ``accepted_orders``, ``rejected_orders``,
        and per-gate check results.
    """
    if capital_usd <= 0:
        return {
            "status": "SKIPPED",
            "reason": "capital_usd_zero",
            "accepted_orders": plan.get("orders", []),
            "rejected_orders": [],
            "gates": {},
        }

    # Build current exposure by symbol
    current_exposure: Dict[str, float] = {}
    for symbol, row in (open_positions or {}).items():
        if not isinstance(row, dict):
            continue
        ticker = str(symbol).upper().strip()
        notional = abs(float(row.get("market_value_usd", 0.0) or 0.0))
        current_exposure[ticker] = notional

    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    projected_exposure = dict(current_exposure)
    gate_results: Dict[str, Any] = {}

    for order in plan.get("orders", []):
        if not isinstance(order, dict):
            continue
        symbol = str(order.get("symbol", "")).upper().strip()
        order_id = str(order.get("order_intent_id", "")).strip()
        order_notional = _extract_notional(order)
        side = str(order.get("side", "BUY")).upper()
        reject_reason = ""

        if not symbol:
            accepted.append(order)
            continue

        # Project exposure after this order
        current = projected_exposure.get(symbol, 0.0)
        if side == "BUY":
            projected = current + order_notional
        else:
            projected = max(0.0, current - order_notional)

        # Gate 1: Single-name concentration
        name_pct = projected / capital_usd
        if name_pct > max_single_name_pct + 1e-9:
            reject_reason = "SINGLE_NAME_CONCENTRATION"

        # Gate 2: Sector concentration
        if not reject_reason and sector_map:
            sector = sector_map.get(symbol)
            if sector:
                sector_total = sum(
                    exp for sym, exp in projected_exposure.items()
                    if sector_map.get(sym) == sector and sym != symbol
                ) + projected
                sector_pct = sector_total / capital_usd
                if sector_pct > max_sector_pct + 1e-9:
                    reject_reason = "SECTOR_CONCENTRATION"

        # Gate 3: Correlated group limit
        if not reject_reason and correlation_groups:
            for group_name, group_symbols in correlation_groups.items():
                if symbol not in group_symbols:
                    continue
                group_total = sum(
                    projected_exposure.get(s, 0.0)
                    for s in group_symbols
                    if s != symbol
                ) + projected
                group_pct = group_total / capital_usd
                if group_pct > max_correlated_group_pct + 1e-9:
                    reject_reason = f"CORRELATED_GROUP:{group_name}"
                    break

        if reject_reason:
            rejected.append({
                "order_intent_id": order_id,
                "symbol": symbol,
                "side": side,
                "attempted_notional_usd": round(order_notional, 2),
                "reason": reject_reason,
            })
            logger.warning(
                "Hard gate rejected %s %s: %s (notional=$%.2f)",
                side, symbol, reject_reason, order_notional,
            )
        else:
            accepted.append(order)
            projected_exposure[symbol] = projected

    status = "PASS"
    if not accepted and rejected:
        status = "REJECTED"
    elif accepted and rejected:
        status = "PARTIAL_PASS"
    elif not plan.get("orders"):
        status = "NO_ORDERS"

    gate_results["single_name"] = {
        "limit_pct": max_single_name_pct,
        "checked": True,
    }
    gate_results["sector"] = {
        "limit_pct": max_sector_pct,
        "checked": sector_map is not None,
    }
    gate_results["correlation"] = {
        "limit_pct": max_correlated_group_pct,
        "checked": correlation_groups is not None,
    }

    return {
        "status": status,
        "capital_usd": round(capital_usd, 2),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "accepted_orders": accepted,
        "rejected_orders": rejected,
        "gates": gate_results,
    }


def _extract_notional(order: Dict[str, Any]) -> float:
    """Extract order notional from target_notional_usd or qty * price."""
    raw = order.get("target_notional_usd")
    try:
        if raw is not None:
            value = abs(float(raw))
            if value > 0:
                return value
    except (TypeError, ValueError):
        pass
    try:
        qty = abs(float(order.get("target_quantity", 0) or 0))
        px = abs(float(order.get("reference_price", 0) or 0))
    except (TypeError, ValueError):
        return 0.0
    return qty * px if qty > 0 and px > 0 else 0.0
