"""Implementation shortfall monitor — tracks slippage between theoretical and actual prices.

Computes the gap between reference_price (what the analysis assumed) and
filled_price (what was actually achieved) across all executed orders.
This is the single most important metric for detecting backtest-to-live
alpha leakage.

Pure computation on local order records. No API calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def _load_json(path: str, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default if default is not None else {}


def compute_impl_shortfall(
    orders_path: str = "eval_results/paper_execution/orders.json",
) -> Dict[str, Any]:
    """Compute implementation shortfall statistics from executed orders.

    For each filled order that has a reference_price, computes:
        slippage_bps = (filled_price - reference_price) / reference_price * 10000
        (positive = paid more than expected, negative = got a better price)
        For SELL orders, sign is flipped (positive = sold lower than expected).

    Returns:
        order_count: total filled orders analyzed
        mean_slippage_bps: average slippage in basis points
        median_slippage_bps: median slippage
        std_slippage_bps: standard deviation
        worst_slippage: {symbol, date, slippage_bps}
        by_side: {BUY: {mean, count}, SELL: {mean, count}}
        by_lane: {CORE: {mean, count}, HEDGE: {mean, count}, ...}
        cumulative_drag_bps: sum of all slippage (total cost)
        details: [{symbol, date, side, reference_price, filled_price, slippage_bps}]
    """
    orders = _load_json(orders_path, [])
    if not isinstance(orders, list):
        orders = []

    details: List[Dict[str, Any]] = []
    for o in orders:
        if not isinstance(o, dict):
            continue
        if o.get("status") != "FILLED":
            continue

        ref_price = o.get("reference_price")
        fill_price = o.get("filled_price")
        if ref_price is None or fill_price is None:
            continue

        ref_price = float(ref_price)
        fill_price = float(fill_price)
        if ref_price <= 0:
            continue

        side = str(o.get("side", "")).upper()
        raw_slip_bps = (fill_price - ref_price) / ref_price * 10000.0

        # For sells: slippage is adverse if we sold LOWER than expected
        if side == "SELL":
            slippage_bps = -raw_slip_bps  # positive = adverse
        else:
            slippage_bps = raw_slip_bps  # positive = adverse (paid more)

        details.append({
            "symbol": o.get("symbol", ""),
            "date": o.get("date", ""),
            "side": side,
            "lane": o.get("lane", ""),
            "reference_price": round(ref_price, 4),
            "filled_price": round(fill_price, 4),
            "slippage_bps": round(slippage_bps, 2),
        })

    if not details:
        return {
            "order_count": 0,
            "mean_slippage_bps": 0.0,
            "median_slippage_bps": 0.0,
            "std_slippage_bps": 0.0,
            "worst_slippage": None,
            "by_side": {},
            "by_lane": {},
            "cumulative_drag_bps": 0.0,
            "details": [],
        }

    slippages = [d["slippage_bps"] for d in details]
    n = len(slippages)
    mean_slip = sum(slippages) / n
    sorted_slips = sorted(slippages)
    median_slip = sorted_slips[n // 2] if n % 2 == 1 else (sorted_slips[n // 2 - 1] + sorted_slips[n // 2]) / 2
    variance = sum((s - mean_slip) ** 2 for s in slippages) / n
    std_slip = variance ** 0.5

    # Worst slippage (most adverse)
    worst = max(details, key=lambda d: d["slippage_bps"])

    # By side
    by_side: Dict[str, Dict[str, Any]] = {}
    for side_label in ("BUY", "SELL"):
        side_slips = [d["slippage_bps"] for d in details if d["side"] == side_label]
        if side_slips:
            by_side[side_label] = {
                "mean_bps": round(sum(side_slips) / len(side_slips), 2),
                "count": len(side_slips),
            }

    # By lane
    by_lane: Dict[str, Dict[str, Any]] = {}
    lanes = {d["lane"] for d in details if d["lane"]}
    for lane in sorted(lanes):
        lane_slips = [d["slippage_bps"] for d in details if d["lane"] == lane]
        if lane_slips:
            by_lane[lane] = {
                "mean_bps": round(sum(lane_slips) / len(lane_slips), 2),
                "count": len(lane_slips),
            }

    return {
        "order_count": n,
        "mean_slippage_bps": round(mean_slip, 2),
        "median_slippage_bps": round(median_slip, 2),
        "std_slippage_bps": round(std_slip, 2),
        "worst_slippage": {
            "symbol": worst["symbol"],
            "date": worst["date"],
            "slippage_bps": worst["slippage_bps"],
        },
        "by_side": by_side,
        "by_lane": by_lane,
        "cumulative_drag_bps": round(sum(slippages), 2),
        "details": details,
    }


def build_shortfall_brief(
    orders_path: str = "eval_results/paper_execution/orders.json",
) -> str:
    """Build formatted implementation shortfall brief."""
    data = compute_impl_shortfall(orders_path=orders_path)

    if data["order_count"] == 0:
        return ""

    lines = ["=== IMPLEMENTATION SHORTFALL ==="]
    lines.append(
        f"Orders analyzed: {data['order_count']} | "
        f"Mean slippage: {data['mean_slippage_bps']:+.1f} bps | "
        f"Std: {data['std_slippage_bps']:.1f} bps"
    )
    lines.append(f"Cumulative drag: {data['cumulative_drag_bps']:+.1f} bps")

    worst = data.get("worst_slippage")
    if worst:
        lines.append(
            f"Worst: {worst['symbol']} on {worst['date']} "
            f"({worst['slippage_bps']:+.1f} bps)"
        )

    for side, info in data.get("by_side", {}).items():
        lines.append(f"  {side}: {info['mean_bps']:+.1f} bps avg ({info['count']} orders)")

    # Alert if mean slippage is concerning (>5 bps)
    if abs(data["mean_slippage_bps"]) > 5.0:
        lines.append(
            f"  WARNING: Mean slippage exceeds 5 bps threshold. "
            f"Review execution quality."
        )

    return "\n".join(lines)
