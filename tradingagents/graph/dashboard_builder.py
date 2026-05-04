"""Dashboard data aggregator for the `aeternus dashboard` command.

Pure Python — no LLM calls, no network I/O, no HTML generation.
Wraps every data load in try/except so the dashboard never crashes.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _load_json(path: str, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default if default is not None else {}


def _check_drawdown_state_from_guard(positions_path: str, hwm_path: str) -> tuple[float, str]:
    """Return (drawdown_pct, status_label) via the canonical drawdown_guard module."""
    try:
        from tradingagents.graph.drawdown_guard import check_drawdown_state
        dd = check_drawdown_state(positions_path=positions_path, hwm_path=hwm_path)
        return dd["drawdown_pct"], dd["status"]
    except Exception:
        return 0.0, "OK"


def _build_positions(positions_path: str) -> List[Dict[str, Any]]:
    """Return list of position dicts sorted by notional descending."""
    try:
        data = _load_json(positions_path, {})
        open_positions = data.get("open_positions", {}) if isinstance(data, dict) else {}
    except Exception:
        return []

    rows: List[Dict[str, Any]] = []
    for symbol, pos in open_positions.items():
        if not isinstance(pos, dict):
            continue
        try:
            net_qty = float(pos.get("net_quantity", 0) or 0)
            avg_price = float(pos.get("avg_price", 0) or 0)
            mark_price = float(pos.get("last_mark_price", 0) or 0)
            if mark_price <= 0:
                mark_price = avg_price

            direction = "LONG" if net_qty >= 0 else "SHORT"
            lane = pos.get("lane", "CORE")
            notional = abs(net_qty) * mark_price

            if avg_price > 0 and mark_price > 0:
                side_scalar = 1.0 if net_qty >= 0 else -1.0
                pnl_pct = ((mark_price - avg_price) / avg_price) * side_scalar * 100.0
                pnl_usd = abs(net_qty) * (mark_price - avg_price) * side_scalar
            else:
                pnl_pct = 0.0
                pnl_usd = 0.0

            opened_at_raw = pos.get("opened_at", "")
            hold_days = 0
            if opened_at_raw:
                try:
                    opened_dt = datetime.fromisoformat(opened_at_raw.replace("Z", "+00:00"))
                    hold_days = (datetime.now(timezone.utc) - opened_dt).days
                except Exception:
                    hold_days = 0

            rows.append({
                "symbol": symbol,
                "direction": direction,
                "lane": lane,
                "net_quantity": round(net_qty, 4),
                "avg_price": round(avg_price, 4),
                "mark_price": round(mark_price, 4),
                "notional": round(notional, 2),
                "pnl_pct": round(pnl_pct, 2),
                "pnl_usd": round(pnl_usd, 2),
                "sector": pos.get("sector", "Unknown"),
                "opened_at": opened_at_raw[:10] if opened_at_raw else "",
                "hold_days": hold_days,
            })
        except Exception:
            continue

    rows.sort(key=lambda r: r["notional"], reverse=True)
    return rows


def _build_performance(closed_trades_path: str, hwm_initial: float) -> Dict[str, Any]:
    """Build performance section from closed_trades.json."""
    try:
        trades = _load_json(closed_trades_path, [])
        if not isinstance(trades, list):
            trades = []
    except Exception:
        trades = []

    # Parse each trade
    parsed: List[Dict[str, Any]] = []
    for t in trades:
        if not isinstance(t, dict):
            continue
        try:
            symbol = t.get("symbol", "")
            closed_at_raw = t.get("closed_at", "")
            close_date = t.get("close_date", closed_at_raw[:10] if closed_at_raw else "")
            pnl_usd = float(t.get("pnl_usd", 0) or 0)
            return_pct = float(t.get("return_pct", 0) or 0)
            avg_entry = float(t.get("avg_entry_price", 0) or 0)
            close_price = float(t.get("close_price", 0) or 0)

            # Compute hold days from entry (not available directly, approximate from rating_ids or skip)
            hold_days = 0

            # Exit reason from rating_ids heuristic
            rating_ids = t.get("rating_ids", [])
            exit_reason = "N/A"
            for rid in (rating_ids or []):
                rid_str = str(rid)
                if "STOP" in rid_str:
                    exit_reason = "Stop Loss"
                elif "TAKE" in rid_str:
                    exit_reason = "Take Profit"
                elif "PHASE" in rid_str:
                    exit_reason = "Phase Signal"
                elif "MOMENTUM" in rid_str:
                    exit_reason = "Momentum Exit"

            parsed.append({
                "symbol": symbol,
                "entry_date": "",
                "exit_date": close_date,
                "closed_at_raw": closed_at_raw,
                "hold_days": hold_days,
                "pnl_pct": round(return_pct, 2),
                "pnl_usd": round(pnl_usd, 2),
                "exit_reason": exit_reason,
                "is_win": pnl_usd > 0,
            })
        except Exception:
            continue

    # Sort by closed_at descending for recent-first
    parsed.sort(key=lambda t: t.get("closed_at_raw", ""), reverse=True)
    recent_10 = parsed[:10]

    # Deduplicate by symbol for recent table (show last close per symbol)
    seen_symbols: set = set()
    recent_unique: List[Dict[str, Any]] = []
    for t in recent_10:
        if t["symbol"] not in seen_symbols:
            seen_unique = {k: v for k, v in t.items() if k != "closed_at_raw" and k != "is_win"}
            recent_unique.append(recent_unique_row := {
                "symbol": t["symbol"],
                "entry_date": t["entry_date"],
                "exit_date": t["exit_date"],
                "hold_days": t["hold_days"],
                "pnl_pct": t["pnl_pct"],
                "pnl_usd": t["pnl_usd"],
                "exit_reason": t["exit_reason"],
            })
            seen_symbols.add(t["symbol"])

    # Lane breakdown — use all parsed trades
    lane_stats: Dict[str, Dict[str, Any]] = {}
    for t in parsed:
        # We don't have lane in closed_trades directly — default to CORE
        lane = "CORE"
        if lane not in lane_stats:
            lane_stats[lane] = {"trades": 0, "wins": 0, "total_pnl_pct": 0.0}
        lane_stats[lane]["trades"] += 1
        if t["is_win"]:
            lane_stats[lane]["wins"] += 1
        lane_stats[lane]["total_pnl_pct"] += t["pnl_pct"]

    by_lane: Dict[str, Dict[str, Any]] = {}
    for lane, s in lane_stats.items():
        trade_count = s["trades"]
        by_lane[lane] = {
            "trades": trade_count,
            "win_rate": round(s["wins"] / trade_count, 4) if trade_count > 0 else 0.0,
            "avg_pnl_pct": round(s["total_pnl_pct"] / trade_count, 2) if trade_count > 0 else 0.0,
        }

    # Equity history: cumulative PnL per close date, sorted
    # Re-sort by date ascending for the chart
    date_pnl: Dict[str, float] = {}
    for t in parsed:
        d = t["exit_date"]
        if d:
            date_pnl[d] = date_pnl.get(d, 0.0) + t["pnl_usd"]

    cumulative = hwm_initial
    equity_history: List[Dict[str, Any]] = []
    for date_str in sorted(date_pnl.keys()):
        cumulative += date_pnl[date_str]
        equity_history.append({"date": date_str, "equity": round(cumulative, 2)})

    # Overall stats
    total_trades = len(parsed)
    wins = sum(1 for t in parsed if t["is_win"])
    win_rate = wins / total_trades if total_trades > 0 else 0.0

    return {
        "closed_trades": recent_unique,
        "by_lane": by_lane,
        "equity_history": equity_history,
        "total_closed": total_trades,
        "win_rate": round(win_rate, 4),
    }


def _build_risk(
    hwm_data: Dict[str, Any],
    positions: List[Dict[str, Any]],
    drawdown_pct: float,
    drawdown_status: str,
) -> Dict[str, Any]:
    """Build risk section."""
    # Concentration flags
    concentration_flags: List[str] = []
    gross_exposure = sum(p["notional"] for p in positions)
    if gross_exposure > 0:
        for p in positions:
            weight = p["notional"] / gross_exposure
            if weight > 0.15:
                concentration_flags.append(
                    f"{p['symbol']}: {weight:.0%} of gross exposure (>15% limit)"
                )

    # Pending exits count (from adaptive position review)
    pending_exits = 0
    try:
        from tradingagents.graph.position_review import review_positions
        pos_data = _load_json("eval_results/paper_execution/positions.json", {})
        open_pos = pos_data.get("open_positions", {}) if isinstance(pos_data, dict) else {}
        if open_pos:
            reviews = review_positions(positions=open_pos)
            pending_exits = sum(1 for r in reviews if r.get("recommendation") == "EXIT")
    except Exception:
        pass

    drawdown_guard = {
        "drawdown_pct": round(drawdown_pct, 2),
        "status": drawdown_status,
        "hwm": hwm_data.get("high_water_mark", 0),
        "halted_at": hwm_data.get("halted_at", ""),
    }

    return {
        "drawdown_guard": drawdown_guard,
        "concentration_flags": concentration_flags,
        "pending_exits": pending_exits,
    }


def _build_signals(deal_flow_dir: str) -> Dict[str, Any]:
    """Load top deal flow queue signals from the most recent queue date."""
    top_queue: List[Dict[str, Any]] = []
    causal_candidates = 0

    try:
        df_path = Path(deal_flow_dir)
        if not df_path.exists():
            return {"top_queue": [], "causal_candidates": 0}

        # Find most recent date directory
        date_dirs = sorted(
            [d for d in df_path.iterdir() if d.is_dir()],
            key=lambda d: d.name,
            reverse=True,
        )
        if not date_dirs:
            return {"top_queue": [], "causal_candidates": 0}

        latest_dir = date_dirs[0]

        # Load research_queue.json
        queue_path = latest_dir / "research_queue.json"
        if queue_path.exists():
            queue_data = _load_json(str(queue_path), {})
            items = queue_data.get("items", []) if isinstance(queue_data, dict) else []
            # Sort by deal_flow_score desc, take top 5
            items_sorted = sorted(
                [i for i in items if isinstance(i, dict)],
                key=lambda i: float(i.get("deal_flow_score", 0) or 0),
                reverse=True,
            )
            for item in items_sorted[:5]:
                top_queue.append({
                    "symbol": item.get("symbol", ""),
                    "score": round(float(item.get("deal_flow_score", 0) or 0), 1),
                    "direction": item.get("direction", item.get("expected_direction", "LONG")),
                    "family": item.get("lane", item.get("sector", "N/A")),
                })

        # Causal candidates from cashtag_events or causal_candidates file
        causal_path = latest_dir / "causal_candidates.json"
        if causal_path.exists():
            causal_data = _load_json(str(causal_path), [])
            if isinstance(causal_data, list):
                causal_candidates = len(causal_data)
            elif isinstance(causal_data, dict):
                causal_candidates = causal_data.get("count", 0)
    except Exception:
        pass

    return {"top_queue": top_queue, "causal_candidates": causal_candidates}


def build_dashboard_data(
    positions_path: str = "eval_results/paper_execution/positions.json",
    orders_path: str = "eval_results/paper_execution/orders.json",
    hwm_path: str = "eval_results/control/hwm.json",
    closed_trades_path: str = "eval_results/paper_execution/closed_trades.json",
    deal_flow_dir: str = "eval_results/deal_flow/",
) -> Dict[str, Any]:
    """Aggregate all dashboard data. Never raises — all loads wrapped in try/except.

    Returns a structured dict with summary, positions, performance, risk, signals.
    """
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    # --- HWM / drawdown ---
    hwm_data = _load_json(hwm_path, {})
    hwm = float(hwm_data.get("high_water_mark", 0) or 0)
    initial_capital = 200_000.0  # default if HWM unavailable

    # --- Equity curve for sharpe proxy ---
    sharpe_proxy = 0.0
    try:
        from tradingagents.graph.equity_curve import EquityCurveEngine
        engine = EquityCurveEngine(
            initial_capital=initial_capital,
            closed_trades_path=closed_trades_path,
            positions_path=positions_path,
        )
        curve = engine.build()
        current_nav = curve["current_nav"]
        stats = curve.get("stats", {})
        sharpe_val = stats.get("sharpe_ratio", 0)
        if isinstance(sharpe_val, (int, float)):
            sharpe_proxy = float(sharpe_val)
        total_closed_via_engine = stats.get("trade_count", 0)
        win_rate_via_engine = float(stats.get("win_rate", 0) or 0)
    except Exception:
        current_nav = initial_capital
        total_closed_via_engine = 0
        win_rate_via_engine = 0.0

    # --- Positions ---
    positions = _build_positions(positions_path)
    gross_exposure = sum(p["notional"] for p in positions)
    long_exp = sum(p["notional"] for p in positions if p["direction"] == "LONG")
    short_exp = sum(p["notional"] for p in positions if p["direction"] == "SHORT")
    net_exposure = long_exp - short_exp

    # --- Drawdown (canonical monitor — OK / WARNING / ALERT) ---
    drawdown_pct, drawdown_status = _check_drawdown_state_from_guard(positions_path, hwm_path)

    # --- Performance ---
    perf = _build_performance(closed_trades_path, initial_capital)
    total_closed = perf["total_closed"] or total_closed_via_engine
    win_rate = perf["win_rate"] or win_rate_via_engine

    # --- Risk ---
    risk = _build_risk(hwm_data, positions, drawdown_pct, drawdown_status)

    # --- Signals ---
    signals = _build_signals(deal_flow_dir)

    # --- Summary ---
    summary = {
        "equity": round(current_nav, 2),
        "hwm": round(hwm, 2) if hwm > 0 else round(current_nav, 2),
        "drawdown_pct": round(drawdown_pct, 2),
        "drawdown_status": drawdown_status,
        "total_positions": len(positions),
        "gross_exposure": round(gross_exposure, 2),
        "net_exposure": round(net_exposure, 2),
        "win_rate": round(win_rate, 4),
        "total_closed_trades": total_closed,
        "sharpe_proxy": round(sharpe_proxy, 2),
    }

    return {
        "generated_at": now.isoformat(),
        "date": date_str,
        "summary": summary,
        "positions": positions,
        "performance": {
            "closed_trades": perf["closed_trades"],
            "by_lane": perf["by_lane"],
            "equity_history": perf["equity_history"],
        },
        "risk": risk,
        "signals": signals,
    }
