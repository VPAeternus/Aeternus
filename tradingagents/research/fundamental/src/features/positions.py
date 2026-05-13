from __future__ import annotations

from typing import Any

from tradingagents.research.fundamental.src.features.common import to_float


def build_position_row(decision: dict[str, Any], current_price: float | None = None) -> dict[str, Any]:
    entry = to_float(decision.get("decision_price")) or to_float(decision.get("actual_entry_price")) or 0
    price = current_price if current_price is not None else entry
    unrealized = ((price / entry) - 1) * 100 if entry else ""
    return {
        "ticker": decision.get("ticker", ""),
        "quarter": decision.get("quarter", ""),
        "position_open_date": decision.get("decision_date", ""),
        "position_close_date": "",
        "entry_price": entry,
        "actual_entry_date": decision.get("actual_entry_date", decision.get("decision_date", "")),
        "actual_entry_price": entry,
        "current_price": price,
        "position_size": decision.get("position_size", ""),
        "cost_basis": entry,
        "unrealized_return_pct": round(unrealized, 4) if unrealized != "" else "",
        "realized_return_pct": "",
        "return_since_signal_pct": decision.get("return_since_signal_pct", ""),
        "return_since_purchase_pct": round(unrealized, 4) if unrealized != "" else "",
        "days_since_signal": decision.get("days_since_signal", ""),
        "days_since_purchase": decision.get("days_since_purchase", ""),
        "status": "active",
        "exit_reason": "",
    }
