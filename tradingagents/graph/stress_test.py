"""Portfolio stress test — CVaR and named scenario analysis.

Extends build_portfolio_risk_snapshot() with:
- CVaR (Conditional Value at Risk) at 95% confidence
- Named scenario stress tests (sector-level shocks)
- Concentration metrics

Single module, two functions — no class.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

# ── Named scenarios (hardcoded sector shocks — no API calls) ──────────────────

SCENARIOS: Dict[str, Dict[str, float]] = {
    "COVID crash": {
        "Technology": -30.0, "Healthcare": -10.0, "Energy": -50.0,
        "Financials": -35.0, "_other": -25.0,
    },
    "2022 rate hike": {
        "Technology": -25.0, "Financials": -15.0, "Healthcare": -5.0,
        "Energy": 20.0, "_other": -15.0,
    },
    "Flash crash": {"_other": -5.0},
    "Tech sell-off": {"Technology": -15.0, "_other": -5.0},
}

# Sector keyword matching (mirrors hedging.py _is_tech_sector pattern)
_SECTOR_KEYWORDS: Dict[str, List[str]] = {
    "Technology": ["technology", "communication", "semiconductor", "software", "internet"],
    "Healthcare": ["healthcare", "health", "biotech", "pharma"],
    "Energy": ["energy", "oil", "gas"],
    "Financials": ["financial", "banking", "insurance"],
}


def _classify_sector(sector_str: str) -> str:
    """Map a free-form sector string to a canonical name for scenario matching."""
    if not sector_str:
        return "_other"
    lower = sector_str.lower()
    for canonical, keywords in _SECTOR_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return canonical
    return "_other"


def _load_json(path: str, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default if default is not None else {}


def compute_stress_metrics(
    positions_path: str = "eval_results/paper_execution/positions.json",
    lookback_days: int = 252,
) -> Dict[str, Any]:
    """Compute CVaR, named scenario impacts, and concentration metrics.

    Returns dict with: portfolio_var_95, portfolio_cvar_95, portfolio_beta,
    max_drawdown_pct, current_drawdown_pct, scenario_results, concentration,
    positions_analyzed, warnings.
    """
    import yfinance as yf

    positions_data = _load_json(positions_path, {})
    open_positions = (
        positions_data.get("open_positions", {})
        if isinstance(positions_data, dict)
        else {}
    )

    warnings: List[str] = []
    if not open_positions:
        return {
            "timestamp": datetime.now().isoformat(),
            "portfolio_var_95": 0.0,
            "portfolio_cvar_95": 0.0,
            "portfolio_beta": 1.0,
            "max_drawdown_pct": 0.0,
            "current_drawdown_pct": 0.0,
            "scenario_results": {},
            "concentration": {"top_position_pct": 0.0, "top_3_pct": 0.0},
            "positions_analyzed": 0,
            "warnings": ["No open positions found."],
        }

    # Build position list with notional and sector
    pos_list: List[Dict[str, Any]] = []
    total_notional = 0.0
    for symbol, pos in open_positions.items():
        if not isinstance(pos, dict):
            continue
        net_qty = float(pos.get("net_quantity", 0) or 0)
        mark = float(pos.get("last_mark_price", pos.get("avg_price", 0)) or 0)
        notional = abs(net_qty * mark)
        if notional <= 0:
            continue
        sector = _classify_sector(str(pos.get("sector", "")))
        pos_list.append({
            "symbol": symbol,
            "notional": notional,
            "sector": sector,
            "direction": 1 if net_qty > 0 else -1,
        })
        total_notional += notional

    if not pos_list:
        return {
            "timestamp": datetime.now().isoformat(),
            "portfolio_var_95": 0.0,
            "portfolio_cvar_95": 0.0,
            "portfolio_beta": 1.0,
            "max_drawdown_pct": 0.0,
            "current_drawdown_pct": 0.0,
            "scenario_results": {},
            "concentration": {"top_position_pct": 0.0, "top_3_pct": 0.0},
            "positions_analyzed": 0,
            "warnings": ["No positions with valid notional."],
        }

    # Concentration
    notionals_sorted = sorted([p["notional"] for p in pos_list], reverse=True)
    top_1_pct = (notionals_sorted[0] / total_notional * 100.0) if total_notional > 0 else 0.0
    top_3_pct = (
        sum(notionals_sorted[:3]) / total_notional * 100.0
        if total_notional > 0
        else 0.0
    )

    # Fetch historical returns for portfolio-level VaR/CVaR
    symbols = [p["symbol"] for p in pos_list]
    weights = np.array([p["notional"] * p["direction"] / total_notional for p in pos_list])

    try:
        data = yf.download(
            symbols if len(symbols) > 1 else symbols[0],
            period=f"{lookback_days}d",
            interval="1d",
            progress=False,
        )
        if data is None or data.empty:
            raise ValueError("No price data")

        # Extract close prices
        if isinstance(data.columns, pd.MultiIndex):
            closes = data["Close"]
        else:
            closes = data[["Close"]].rename(columns={"Close": symbols[0]})

        if isinstance(closes, pd.Series):
            closes = closes.to_frame(name=symbols[0])

        daily_returns = closes.pct_change().dropna()

        # Align weights to available symbols
        available = [s for s in symbols if s in daily_returns.columns]
        if not available:
            raise ValueError("No price history for any position")

        excluded = set(symbols) - set(available)
        for s in excluded:
            warnings.append(f"No price history for {s} — excluded from VaR/CVaR.")

        w = np.array([
            pos_list[symbols.index(s)]["notional"] * pos_list[symbols.index(s)]["direction"] / total_notional
            for s in available
        ])
        returns_matrix = daily_returns[available].values
        portfolio_returns = returns_matrix @ w

        var_95 = float(np.percentile(portfolio_returns, 5)) * -100.0
        var_95 = max(var_95, 0.0)

        # CVaR = mean of returns below VaR threshold
        threshold = np.percentile(portfolio_returns, 5)
        tail_returns = portfolio_returns[portfolio_returns <= threshold]
        cvar_95 = float(np.mean(tail_returns)) * -100.0 if len(tail_returns) > 0 else var_95

        # Max drawdown from portfolio return series
        cum = np.cumprod(1 + portfolio_returns)
        running_max = np.maximum.accumulate(cum)
        drawdowns = (cum - running_max) / running_max
        max_dd = float(np.min(drawdowns)) * -100.0
        current_dd = float(drawdowns[-1]) * -100.0 if len(drawdowns) > 0 else 0.0

        # Beta vs SPY
        try:
            spy_data = yf.download("SPY", period=f"{lookback_days}d", interval="1d", progress=False)
            if isinstance(spy_data.columns, pd.MultiIndex):
                spy_close = spy_data[("Close", "SPY")]
            else:
                spy_close = spy_data["Close"]
            spy_returns = spy_close.pct_change().dropna().values[-len(portfolio_returns):]
            min_len = min(len(portfolio_returns), len(spy_returns))
            if min_len > 10:
                cov = np.cov(portfolio_returns[-min_len:], spy_returns[-min_len:])
                beta = float(cov[0, 1] / cov[1, 1]) if cov[1, 1] != 0 else 1.0
            else:
                beta = 1.0
        except Exception:
            beta = 1.0

    except Exception as exc:
        warnings.append(f"Price fetch failed: {exc}. Using fallback estimates.")
        var_95 = 2.5
        cvar_95 = 3.5
        max_dd = 0.0
        current_dd = 0.0
        beta = 1.0

    # Named scenario analysis
    scenario_results: Dict[str, Dict[str, Any]] = {}
    if len(pos_list) >= 2:
        for scenario_name, shocks in SCENARIOS.items():
            impact_usd = 0.0
            worst_symbol = ""
            worst_impact = 0.0
            for p in pos_list:
                shock_pct = shocks.get(p["sector"], shocks.get("_other", 0.0))
                pos_impact = p["notional"] * p["direction"] * (shock_pct / 100.0)
                impact_usd += pos_impact
                if abs(pos_impact) > abs(worst_impact):
                    worst_impact = pos_impact
                    worst_symbol = p["symbol"]
            impact_pct = (impact_usd / total_notional * 100.0) if total_notional > 0 else 0.0
            scenario_results[scenario_name] = {
                "impact_pct": round(impact_pct, 2),
                "impact_usd": round(impact_usd, 2),
                "worst_position": worst_symbol,
                "worst_position_impact_usd": round(worst_impact, 2),
            }

    return {
        "timestamp": datetime.now().isoformat(),
        "portfolio_var_95": round(var_95, 2),
        "portfolio_cvar_95": round(cvar_95, 2),
        "portfolio_beta": round(beta, 3),
        "max_drawdown_pct": round(max_dd, 2),
        "current_drawdown_pct": round(current_dd, 2),
        "scenario_results": scenario_results,
        "concentration": {
            "top_position_pct": round(top_1_pct, 1),
            "top_3_pct": round(top_3_pct, 1),
        },
        "positions_analyzed": len(pos_list),
        "warnings": warnings,
    }


def build_stress_brief(
    positions_path: str = "eval_results/paper_execution/positions.json",
) -> str:
    """Build formatted stress brief for injection into risk discussion prompts."""
    metrics = compute_stress_metrics(positions_path=positions_path)

    if metrics["positions_analyzed"] == 0:
        return ""

    lines = ["=== STRESS TEST ==="]
    lines.append(
        f"VaR(95%): {metrics['portfolio_var_95']:.1f}% | "
        f"CVaR(95%): {metrics['portfolio_cvar_95']:.1f}% | "
        f"Beta: {metrics['portfolio_beta']:.2f}"
    )
    lines.append(
        f"Max DD: {metrics['max_drawdown_pct']:.1f}% | "
        f"Current DD: {metrics['current_drawdown_pct']:.1f}%"
    )
    lines.append(
        f"Concentration: Top-1 {metrics['concentration']['top_position_pct']:.0f}% | "
        f"Top-3 {metrics['concentration']['top_3_pct']:.0f}%"
    )

    scenarios = metrics.get("scenario_results", {})
    if scenarios:
        lines.append("Scenario impacts:")
        for name, result in scenarios.items():
            lines.append(
                f"  {name}: {result['impact_pct']:+.1f}% "
                f"(worst: {result['worst_position']} ${result['worst_position_impact_usd']:+,.0f})"
            )

    for w in metrics.get("warnings", []):
        lines.append(f"  WARNING: {w}")

    return "\n".join(lines)


# pandas import at module level would fail if not installed; import lazily above
try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore[assignment]
