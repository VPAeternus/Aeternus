"""Fill-related scalar helpers split from graph.paper_execution."""

from __future__ import annotations


def apply_slippage(reference_price: float, side: str, bps: float) -> float:
    slip = max(0.0, float(bps)) / 10000.0
    if str(side).upper() == "BUY":
        return reference_price * (1.0 + slip)
    return reference_price * (1.0 - slip)


def recommendation_to_side(recommendation: str, long_only: bool) -> str:
    rec = str(recommendation or "").upper()
    if "BUY" in rec:
        return "BUY"
    if "SELL" in rec:
        return "SKIP" if long_only else "SELL"
    return "SKIP"


def coerce_order_quantity(raw_qty: float, whole_shares: bool) -> float:
    qty = max(0.0, float(raw_qty))
    if whole_shares:
        return float(int(qty))
    return qty
