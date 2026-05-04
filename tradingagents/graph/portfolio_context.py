"""
Portfolio context builder for risk debate prompts.

Pure Python — no LLM calls, no network I/O.
Aggregates open positions, calibration data, and drawdown state
into a formatted string injected into risk debater prompts.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


def _load_json(path: str, default: Any = None) -> Any:
    """Read JSON file, return default on any failure."""
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default if default is not None else {}


def _format_positions_summary(open_positions: Dict[str, Any]) -> str:
    """Build position count, gross exposure, sector breakdown from open positions dict."""
    if not open_positions:
        return "No open positions."

    # Try to load AKG for thesis summaries
    _akg = None
    try:
        from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
        _akg = AeternusKnowledgeGraph()
    except Exception:
        pass

    lines = []
    total_long = 0.0
    total_short = 0.0
    sector_exposure: Dict[str, float] = {}
    position_details = []

    for symbol, pos in sorted(open_positions.items()):
        if not isinstance(pos, dict):
            continue
        net_qty = float(pos.get("net_quantity", 0) or 0)
        avg_price = float(pos.get("avg_price", 0) or 0)
        mark_price = float(pos.get("last_mark_price", 0) or 0)
        notional = abs(net_qty) * (mark_price if mark_price > 0 else avg_price)

        if net_qty > 0:
            total_long += notional
        else:
            total_short += notional

        # P&L
        if avg_price > 0 and mark_price > 0:
            side_scalar = 1.0 if net_qty > 0 else -1.0
            pnl_pct = ((mark_price - avg_price) / avg_price) * side_scalar * 100.0
            pnl_str = f"{pnl_pct:+.1f}%"
        else:
            pnl_str = "N/A"

        direction = "LONG" if net_qty > 0 else "SHORT"
        thesis = ""
        if _akg is not None:
            try:
                node = _akg._nodes.get(symbol, {})
                thesis = node.get("last_thesis_summary", "")
            except Exception:
                pass
        thesis_str = f" — {thesis}" if thesis else ""
        position_details.append(
            f"  {symbol}: {direction} ${notional:,.0f} ({pnl_str}){thesis_str}"
        )

        # Sector tracking (from position metadata if available)
        sector = pos.get("sector", "Unknown")
        sector_exposure[sector] = sector_exposure.get(sector, 0) + notional

    gross = total_long + total_short
    net = total_long - total_short

    lines.append(f"Positions: {len(open_positions)} open")
    lines.append(f"Gross exposure: ${gross:,.0f} | Net: ${net:,.0f}")
    lines.extend(position_details)

    # Concentration flags
    if gross > 0:
        for symbol, pos in open_positions.items():
            if not isinstance(pos, dict):
                continue
            net_qty = float(pos.get("net_quantity", 0) or 0)
            mark = float(pos.get("last_mark_price", 0) or pos.get("avg_price", 0) or 0)
            pos_notional = abs(net_qty) * mark
            weight = pos_notional / gross
            if weight > 0.15:
                lines.append(f"  WARNING: {symbol} is {weight:.0%} of portfolio (>15% concentration)")

    # Sector breakdown
    if sector_exposure and gross > 0:
        lines.append("Sector breakdown:")
        for sector, exp in sorted(sector_exposure.items(), key=lambda x: -x[1]):
            lines.append(f"  {sector}: ${exp:,.0f} ({exp / gross:.0%})")

    return "\n".join(lines)


def _format_calibration(calibration: Dict[str, Any]) -> str:
    """Format calibration report into a concise string."""
    if not calibration or not calibration.get("sample_sufficient"):
        closed = calibration.get("closed_decisions", 0) if calibration else 0
        return f"Calibration: insufficient data ({closed} closed decisions, need 30+)"

    lines = ["Calibration feedback:"]

    biases = calibration.get("systematic_biases", [])
    if biases:
        lines.append("  Systematic biases detected:")
        for bias in biases:
            lines.append(f"    - {bias}")
    else:
        lines.append("  No systematic biases detected.")

    sector_acc = calibration.get("accuracy_by_sector", {})
    if sector_acc:
        worst = min(sector_acc.items(), key=lambda x: x[1])
        best = max(sector_acc.items(), key=lambda x: x[1])
        lines.append(f"  Best sector: {best[0]} ({best[1]:.0%})")
        lines.append(f"  Worst sector: {worst[0]} ({worst[1]:.0%})")

    return "\n".join(lines)


def _format_drawdown(hwm_data: Dict[str, Any]) -> str:
    """Format HWM/drawdown state. Drawdown mode activates at 5% from HWM."""
    if not hwm_data:
        return "Drawdown state: no HWM data available."

    hwm = float(hwm_data.get("high_water_mark", 0) or 0)
    current = float(hwm_data.get("current_equity", 0) or hwm_data.get("portfolio_value", 0) or 0)

    if hwm <= 0 or current <= 0:
        return "Drawdown state: no equity data available."

    drawdown_pct = ((hwm - current) / hwm) * 100.0 if current < hwm else 0.0
    drawdown_active = drawdown_pct >= 5.0

    lines = [f"Portfolio equity: ${current:,.0f} | HWM: ${hwm:,.0f}"]
    lines.append(f"Current drawdown: {drawdown_pct:.1f}%")
    if drawdown_active:
        lines.append("DRAWDOWN MODE ACTIVE — portfolio has drawn down 5%+ from HWM. Capital preservation priority.")

    return "\n".join(lines)


def build_portfolio_context(
    execution_mode: str = "paper",
    market_regime: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Build a compact portfolio context string for risk debater prompts.

    Sources:
    - Open positions from paper or live execution state
    - Calibration report from track record
    - HWM/drawdown state from control plane

    Args:
        execution_mode: "paper" or "alpaca-paper" / "alpaca-live"
        market_regime: Market regime dict from state, if available

    Returns:
        Formatted string for injection into risk debate prompts.
    """
    # Determine positions path
    mode = str(execution_mode or "paper").lower().strip()
    if "live" in mode and "paper" not in mode:
        positions_path = "eval_results/live_execution/positions_shadow.json"
    elif "alpaca" in mode:
        positions_path = "eval_results/live_execution/positions_shadow.json"
    else:
        positions_path = "eval_results/paper_execution/positions.json"

    # Load positions
    positions_data = _load_json(positions_path, default={})
    open_positions = positions_data.get("open_positions", {}) if isinstance(positions_data, dict) else {}

    # Load calibration
    from tradingagents.graph.calibration import build_calibration_report
    calibration = build_calibration_report()

    # Load HWM
    hwm_data = _load_json("eval_results/control/hwm.json", default={})

    # Build sections
    sections = []
    sections.append("=== PORTFOLIO CONTEXT FOR RISK DEBATE ===")
    sections.append("")
    sections.append(_format_positions_summary(open_positions))
    sections.append("")
    sections.append(_format_calibration(calibration))
    sections.append("")
    sections.append(_format_drawdown(hwm_data))

    # Regime context
    if market_regime:
        regime_label = market_regime.get("regime", "unknown")
        vix = market_regime.get("vix")
        sections.append("")
        regime_line = f"Market regime: {regime_label}"
        if vix is not None:
            regime_line += f" (VIX: {vix:.1f})"
        sections.append(regime_line)

    # Correlation guard
    try:
        from tradingagents.graph.correlation_guard import build_correlation_brief
        position_symbols = list(open_positions.keys())
        corr_brief = build_correlation_brief(position_symbols)
        if corr_brief:
            sections.append("")
            sections.append(corr_brief)
    except Exception:
        pass  # Never crash the risk debate over correlation data

    # Supply chain concentration narrative
    try:
        from tradingagents.graph.supply_chain_narrative import build_portfolio_narrative
        narrative = build_portfolio_narrative(open_positions)
        if narrative:
            sections.append("")
            sections.append(narrative)
    except Exception:
        pass  # Never crash the risk debate over supply chain data

    # Agent credibility brief
    try:
        from tradingagents.graph.credibility_ledger import CredibilityLedger
        regime_label = (market_regime or {}).get("regime", "NEUTRAL")
        ledger = CredibilityLedger()
        credibility_brief = ledger.build_credibility_brief(regime=regime_label)
        if credibility_brief:
            sections.append("")
            sections.append(credibility_brief)
    except Exception:
        pass  # Never crash the risk debate over credibility data

    # Stress test brief
    try:
        from tradingagents.graph.stress_test import build_stress_brief
        stress_brief = build_stress_brief(positions_path=positions_path)
        if stress_brief:
            sections.append("")
            sections.append(stress_brief)
    except Exception:
        pass  # Never crash the risk debate over stress test data

    # Geopolitical alert brief
    try:
        from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
        _geo_akg = AeternusKnowledgeGraph()
        geo_events = _geo_akg.get_recent_causal_events(max_age_hours=48)
        if geo_events:
            geo_lines = ["=== GEOPOLITICAL ALERTS (last 48h) ==="]
            for ev in geo_events:
                event_type = ev.get("event_type", "UNKNOWN")
                source = ev.get("source", "unknown")
                direction = ev.get("direction", "")
                magnitude = ev.get("magnitude", 0)
                ticker = ev.get("ticker", "")
                date = ev.get("event_date", "")

                if source == "commodity_shock_scout":
                    cluster = ev.get("cluster_name", ticker)
                    instruments = ev.get("triggered_instruments", [])
                    vol_z = ev.get("volume_z_max", 0)
                    geo_lines.append(
                        f"COMMODITY SHOCK: {cluster} ({direction}, "
                        f"confidence {magnitude:.0%}, vol-Z {vol_z:.1f}) "
                        f"— triggered by {', '.join(instruments) if instruments else 'N/A'} [{date}]"
                    )
                elif source == "dod_contract_scout":
                    sector = ev.get("contract_sector", ticker)
                    z_score = ev.get("z_score", 0)
                    recipients = ev.get("top_recipients", [])
                    geo_lines.append(
                        f"DOD AWARD SPIKE: {sector} (Z={z_score:.1f}, "
                        f"confidence {magnitude:.0%}) "
                        f"— top recipients: {', '.join(recipients[:2]) if recipients else 'N/A'} [{date}]"
                    )
                else:
                    geo_lines.append(
                        f"{event_type}: {ticker} ({direction}, confidence {magnitude:.0%}) [{date}]"
                    )
            geo_lines.append(
                "RISK IMPACT: Geopolitical shocks trigger broad risk-off selling across "
                "all sectors except defense and safe-haven (gold, treasuries). "
                "Evaluate ENTIRE portfolio for drawdown risk, not just directly affected names. "
                "Consider: position sizing reduction, hedge acceleration, and cash raise priority."
            )
            sections.append("")
            sections.append("\n".join(geo_lines))
    except Exception:
        pass  # Never crash the risk debate over geopolitical data

    # Regime transition alert
    try:
        from tradingagents.graph.regime_monitor import build_regime_alert
        regime_alert = build_regime_alert()
        if regime_alert:
            sections.append("")
            sections.append(regime_alert)
    except Exception:
        pass  # Never crash the risk debate over regime data

    sections.append("")
    sections.append("=== END PORTFOLIO CONTEXT ===")

    return "\n".join(sections)
