"""Morning Brief Generator.

Aggregates portfolio state, risk metrics, pending catalysts, and deal flow signals
into a structured briefing. Pure Python — no LLM calls, no external API calls.

Output: dict with all brief sections, suitable for Rich terminal rendering or HTML generation.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _load_json(path: str, default: Any = None) -> Any:
    """Read JSON file, return default on any failure."""
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default if default is not None else {}


def _compute_pnl_pct(avg_price: float, mark_price: float, net_qty: float) -> float:
    """Compute P&L % for a position."""
    if avg_price <= 0 or mark_price <= 0:
        return 0.0
    side_scalar = 1.0 if net_qty > 0 else -1.0
    return ((mark_price - avg_price) / avg_price) * side_scalar * 100.0


def build_morning_brief(
    positions_path: str = "eval_results/paper_execution/positions.json",
    orders_path: str = "eval_results/paper_execution/orders.json",
    hwm_path: str = "eval_results/control/hwm.json",
    deal_flow_path: str = "eval_results/deal_flow/",
    track_record_path: str = "eval_results/track_record.json",
) -> dict:
    """
    Build comprehensive morning briefing data.

    Returns dict with sections: generated_at, date, portfolio, performance, risk,
    catalysts, deal_flow.
    """
    now = datetime.now(timezone.utc)
    generated_at = now.isoformat()
    date_str = now.strftime("%Y-%m-%d")

    brief: Dict[str, Any] = {
        "generated_at": generated_at,
        "date": date_str,
        "portfolio": {},
        "performance": {},
        "risk": {},
        "deal_flow": {},
    }

    # ─── PORTFOLIO SECTION ──────────────────────────────────────────────────

    positions_data = _load_json(positions_path, {})
    open_positions = (
        positions_data.get("open_positions", {})
        if isinstance(positions_data, dict)
        else {}
    )

    hwm_data = _load_json(hwm_path, {})
    hwm = float(hwm_data.get("high_water_mark", 0) or 0)
    current_equity = 0.0

    # Try to estimate current equity from positions
    total_notional = 0.0
    total_long_notional = 0.0
    total_short_notional = 0.0
    top_positions: List[Dict[str, Any]] = []

    for symbol, pos in open_positions.items():
        if not isinstance(pos, dict):
            continue
        net_qty = float(pos.get("net_quantity", 0) or 0)
        avg_price = float(pos.get("avg_price", 0) or 0)
        mark_price = float(pos.get("last_mark_price", 0) or 0)
        notional = abs(net_qty) * (mark_price if mark_price > 0 else avg_price)

        total_notional += notional
        if net_qty > 0:
            total_long_notional += notional
        else:
            total_short_notional += notional

        pnl_pct = _compute_pnl_pct(avg_price, mark_price, net_qty)
        direction = "LONG" if net_qty > 0 else "SHORT"

        top_positions.append(
            {
                "symbol": symbol,
                "direction": direction,
                "pnl_pct": round(pnl_pct, 2),
                "notional": round(notional, 2),
                "net_qty": net_qty,
                "avg_price": round(avg_price, 2),
                "mark_price": round(mark_price, 2),
            }
        )

    # Sort by notional, take top 5
    top_positions.sort(key=lambda x: -x["notional"])
    top_positions = top_positions[:5]

    # Drawdown state — canonical monitor (OK / WARNING / ALERT)
    try:
        from tradingagents.graph.drawdown_guard import check_drawdown_state
        _dd = check_drawdown_state(positions_path=positions_path, hwm_path=hwm_path)
        current_equity = _dd["current_equity"] or total_notional
        current_drawdown_pct = _dd["drawdown_pct"]
        drawdown_status = _dd["status"]
    except Exception:
        current_equity = total_notional
        current_drawdown_pct = 0.0
        drawdown_status = "OK"

    brief["portfolio"] = {
        "equity": round(current_equity, 2),
        "hwm": round(hwm, 2),
        "drawdown_pct": round(current_drawdown_pct, 2),
        "drawdown_status": drawdown_status,
        "open_positions": len(open_positions),
        "gross_exposure": round(total_long_notional + total_short_notional, 2),
        "net_exposure": round(total_long_notional - total_short_notional, 2),
        "long_exposure": round(total_long_notional, 2),
        "short_exposure": round(total_short_notional, 2),
        "top_positions": top_positions,
    }

    # ─── PERFORMANCE SECTION ────────────────────────────────────────────────

    track_record = _load_json(track_record_path, [])
    if not isinstance(track_record, list):
        track_record = []

    # Filter to closed trades
    closed_trades = [t for t in track_record if isinstance(t, dict) and t.get("status") == "CLOSED"]
    total_trades = len(track_record)
    closed_count = len(closed_trades)

    # Compute win rate and returns
    wins = 0
    losses = 0
    win_pnls = []
    loss_pnls = []
    recent_closes = []

    for trade in closed_trades:
        price_at = float(trade.get("price_at_rating", 0) or 0)
        price_close = float(trade.get("close_price", 0) or 0)
        if price_at > 0 and price_close > 0:
            pnl_pct = ((price_close - price_at) / price_at) * 100.0
            if pnl_pct > 0:
                wins += 1
                win_pnls.append(pnl_pct)
            else:
                losses += 1
                loss_pnls.append(pnl_pct)

            recent_closes.append(
                {
                    "symbol": trade.get("ticker", "?"),
                    "pnl_pct": round(pnl_pct, 2),
                    "closed_at": trade.get("date", "N/A"),
                }
            )

    # Recent 3 closes
    recent_closes.sort(key=lambda x: x["closed_at"], reverse=True)
    recent_closes = recent_closes[:3]

    win_rate = wins / (wins + losses) if (wins + losses) > 0 else 0.0
    avg_win_pct = sum(win_pnls) / len(win_pnls) if win_pnls else 0.0
    avg_loss_pct = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0.0

    brief["performance"] = {
        "total_trades": total_trades,
        "closed_trades": closed_count,
        "win_rate": round(win_rate, 4),
        "avg_win_pct": round(avg_win_pct, 2),
        "avg_loss_pct": round(avg_loss_pct, 2),
        "recent_closes": recent_closes,
    }

    # ─── RISK SECTION ───────────────────────────────────────────────────────

    concentration_flags = []
    gross = total_long_notional + total_short_notional
    if gross > 0:
        for pos in top_positions:
            weight = pos["notional"] / gross
            if weight > 0.15:
                concentration_flags.append(f"{pos['symbol']}: {weight:.0%} of portfolio")

    stress_brief = ""
    try:
        from tradingagents.graph.stress_test import build_stress_brief

        stress_brief = build_stress_brief(positions_path=positions_path) or ""
    except Exception:
        pass  # Graceful fallback

    brief["risk"] = {
        "concentration_flags": concentration_flags,
        "drawdown_status": brief["portfolio"]["drawdown_status"],
        "stress_brief": stress_brief,
    }

    # ─── DEAL FLOW SECTION ──────────────────────────────────────────────────

    latest_queue_date = ""
    top_signals: List[Dict[str, Any]] = []

    try:
        # Find latest research queue file
        deal_flow_dir = Path(deal_flow_path)
        if deal_flow_dir.exists():
            queue_files = sorted(deal_flow_dir.glob("*/research_queue.json"), reverse=True)
            if queue_files:
                latest_queue_path = queue_files[0]
                latest_queue_date = latest_queue_path.parent.name

                queue_data = _load_json(str(latest_queue_path), {})
                if isinstance(queue_data, dict):
                    items = queue_data.get("items", [])
                    for item in items[:5]:
                        if isinstance(item, dict):
                            top_signals.append(
                                {
                                    "symbol": item.get("symbol", "?"),
                                    "score": round(float(item.get("deal_flow_score", 0) or 0), 1),
                                    "family": item.get("lane", "UNKNOWN"),
                                    "direction": "BUY",  # Implied from queue presence
                                }
                            )
    except Exception:
        pass  # Graceful fallback

    brief["deal_flow"] = {
        "latest_queue_date": latest_queue_date,
        "top_signals": top_signals,
    }

    # ─── GEX REGIME SECTION ────────────────────────────────────────────────

    gex_state = _load_json("eval_results/control/gex_regime_state.json", {})
    gex_updated = gex_state.get("gex_updated_at", "") or gex_state.get("data_freshness", "")
    gex_age_days = 999
    if gex_updated:
        try:
            gex_dt = datetime.strptime(gex_updated[:10], "%Y-%m-%d")
            gex_age_days = (now.replace(tzinfo=None) - gex_dt).days
        except Exception:
            pass
    brief["gex_regime"] = {
        "data": gex_state,
        "age_days": gex_age_days,
        "stale": gex_age_days > 1,
        "refresh_command": "aeternus x-feed --generate --pass 15",
    }

    # ─── POSITION HEALTH SECTION ─────────────────────────────────────────
    try:
        from tradingagents.graph.position_review import review_positions

        akg = None
        try:
            from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
            akg = AeternusKnowledgeGraph.load()
        except Exception:
            pass

        reviews = review_positions(
            positions=open_positions,
            akg=akg,
            pipeline_candidates=top_signals,
        )
        action_counts: Dict[str, int] = {}
        alerts: List[str] = []
        for r in reviews:
            action_counts[r["recommendation"]] = action_counts.get(r["recommendation"], 0) + 1
            if r["recommendation"] != "HOLD":
                alerts.append(f"{r['symbol']}: {r['recommendation']} — {r['reason']}")

        brief["position_health"] = {
            "total_held": len(open_positions),
            "actions": action_counts,
            "alerts": alerts,
        }
    except Exception:
        brief["position_health"] = {"total_held": len(open_positions), "actions": {}, "alerts": []}

    return brief
