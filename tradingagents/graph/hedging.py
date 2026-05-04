"""Adaptive hedging engine — bear-only SMA200 regime hedge with S7 boost.

Architecture:
  Bull (SPY > SMA200): 0% hedge. V3 Index Overlay manages long exposure.
  Bear (SPY < SMA200): 85% short SPY base hedge.
  Bear + S7 signal:    150% short SPY (85% base + 75% S7 boost, capped at 150%).
  Crash trigger:       150% (net short).

Backtest (QQQ 2006-2026, 0% neutral, 85% bear, +75% S7 boost):
  CAGR 24.7% | Sharpe 1.470 | MaxDD -17.0% | $100K → $8.5M
  GFC: +7.8% | COVID: +14.9% | 2022: -12.1% | Tariffs: -7.3%
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .contracts import (
    HedgeDecision,
    HedgeOrder,
    HedgeSignal,
    MarketRegimeSnapshot,
    PortfolioRiskSnapshot,
)

# ── Hedge sizing constants ────────────────────────────────────────────────────
BEAR_BASE_HEDGE_PCT = 85.0       # Short SPY at 85% of gross when SPY < SMA200
S7_BOOST_PCT = 75.0              # Additional short on S7a/S7b signal days
MAX_HEDGE_PCT = 150.0            # Cap — never exceed 150% short


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _now_iso() -> str:
    return datetime.now().isoformat()


def _today_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _classify_market_regime(
    spy_close: float,
    spy_sma200: float,
    vix_close: float,
    crash_trigger_active: bool,
) -> str:
    """Map observed market conditions to deterministic regime buckets."""
    if crash_trigger_active:
        return "CRASH"
    if spy_close < spy_sma200 and vix_close >= 25.0:
        return "BEAR_STRESS"
    if spy_close < spy_sma200:
        return "BEAR"
    return "BULL"


def _rating_direction(rating: str) -> int:
    if not rating:
        return 0
    text = str(rating).lower()
    if "sell" in text:
        return -1
    if "buy" in text:
        return 1
    return 0


def _is_tech_sector(sector: str) -> bool:
    if not sector:
        return False
    text = str(sector).lower()
    return (
        "technology" in text
        or "communication" in text
        or "semiconductor" in text
        or "software" in text
        or "internet" in text
    )


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def build_portfolio_risk_snapshot(
    track_record_path: str = "eval_results/track_record.json",
    hedge_state_path: str = "eval_results/hedge_state.json",
    positions_path: str = "eval_results/paper_execution/positions.json",
) -> PortfolioRiskSnapshot:
    """Build a deterministic portfolio risk snapshot from local paper records."""

    track_path = Path(track_record_path)
    state_path = Path(hedge_state_path)

    history: List[Dict] = _load_json(track_path, [])
    state: Dict = _load_json(state_path, {})
    positions_payload: Dict = _load_json(Path(positions_path), {})
    open_positions: Dict = positions_payload.get("open_positions", {}) if isinstance(positions_payload, dict) else {}

    open_entries = [h for h in history if str(h.get("status", "OPEN")).upper() != "CLOSED"]
    rating_sector: Dict[str, str] = {
        str(h.get("rating_id", "")): str(h.get("sector", ""))
        for h in history
        if isinstance(h, dict)
    }

    gross = 0.0
    net = 0.0
    tech_notional = 0.0
    mark_to_market_returns: List[float] = []

    if isinstance(open_positions, dict) and open_positions:
        for symbol, row in open_positions.items():
            if not isinstance(row, dict):
                continue
            net_qty = float(row.get("net_quantity", 0.0) or 0.0)
            mark_price = float(row.get("last_mark_price", row.get("avg_price", 0.0)) or 0.0)
            market_value = float(row.get("market_value_usd", abs(net_qty) * mark_price) or 0.0)
            direction = 1 if net_qty >= 0 else -1
            notional = abs(market_value)

            gross += notional
            net += direction * notional

            inferred_sector = ""
            rating_ids = row.get("rating_ids", []) or []
            if isinstance(rating_ids, list):
                for rid in rating_ids:
                    inferred_sector = rating_sector.get(str(rid), "")
                    if inferred_sector:
                        break
            if not inferred_sector and symbol in {"QQQ", "SMH", "XLK"}:
                inferred_sector = "Technology"

            if _is_tech_sector(inferred_sector):
                tech_notional += notional

            unrealized_pct = row.get("unrealized_return_pct")
            if unrealized_pct is not None:
                try:
                    mark_to_market_returns.append(float(unrealized_pct) / 100.0)
                except (TypeError, ValueError):
                    pass
    else:
        for entry in open_entries:
            entry_price = entry.get("price_at_rating")
            try:
                notional = float(entry_price)
            except (TypeError, ValueError):
                notional = 0.0

            direction = _rating_direction(str(entry.get("rating", "")))
            gross += abs(notional)
            net += notional * direction

            if _is_tech_sector(str(entry.get("sector", ""))):
                tech_notional += abs(notional)

            close_price = entry.get("close_price")
            if notional > 0 and close_price is not None:
                try:
                    close_val = float(close_price)
                    mark_to_market_returns.append((close_val - notional) / notional)
                except (TypeError, ValueError):
                    pass

    tech_conc = (tech_notional / gross * 100.0) if gross > 0 else 0.0

    if tech_conc >= 60.0:
        beta = 1.25
    elif tech_conc >= 40.0:
        beta = 1.15
    else:
        beta = 1.0

    if mark_to_market_returns:
        abs_avg = sum(abs(x) for x in mark_to_market_returns) / len(mark_to_market_returns)
        var95 = _clamp(abs_avg * 1.65 * 100.0, 0.0, 10.0)
        worst = min(mark_to_market_returns)
        drawdown = _clamp(max(0.0, -worst) * 100.0, 0.0, 100.0)
    elif gross > 0:
        var95 = 2.5
        drawdown = 0.0
    else:
        var95 = 0.0
        drawdown = 0.0

    current_hedge = float(state.get("current_hedge_pct", 0.0) or 0.0)

    return {
        "timestamp": _now_iso(),
        "gross_exposure_usd": float(gross),
        "net_exposure_usd": float(net),
        "portfolio_beta_60d": float(beta),
        "var_95_1d_pct_nav": float(var95),
        "drawdown_20d_pct": float(drawdown),
        "tech_concentration_pct": float(tech_conc),
        "current_hedge_pct": float(current_hedge),
    }


class AdaptiveHedgeEngine:
    """Bear-only hedge engine: 0% in bull, 85% base in bear, 150% on S7 signal days.

    The SMA200 crossover is the single gate. Above SMA200, V3 Index Overlay
    manages long exposure — no hedge needed. Below SMA200, short SPY at 85%
    of gross, boosted to 150% when S7a/S7b weak-regime signals fire.
    """

    def __init__(
        self,
        state_path: str = "eval_results/hedge_state.json",
        orders_path: str = "eval_results/hedge_orders.json",
    ):
        self.state_path = Path(state_path)
        self.orders_path = Path(orders_path)
        if not self.state_path.exists():
            _save_json(
                self.state_path,
                {
                    "current_hedge_pct": 0.0,
                    "last_rebalance_date": None,
                    "last_updated": _now_iso(),
                },
            )
        if not self.orders_path.exists():
            _save_json(self.orders_path, [])

    def compute_hedge_signal(
        self,
        portfolio_snapshot: PortfolioRiskSnapshot,
        market_snapshot: Optional[MarketRegimeSnapshot],
        s7_active: bool = False,
    ) -> HedgeSignal:
        beta = float(portfolio_snapshot.get("portfolio_beta_60d", 1.0))
        var95 = float(portfolio_snapshot.get("var_95_1d_pct_nav", 0.0))
        drawdown = float(portfolio_snapshot.get("drawdown_20d_pct", 0.0))

        if market_snapshot is None:
            return {
                "base_hedge_pct": 0.0,
                "s7_boost_pct": 0.0,
                "bear_trigger_active": False,
                "crash_trigger_active": False,
                "target_hedge_pct_pre_hysteresis": 0.0,
                "mode": "BULL",
                "market_regime": "UNKNOWN",
                "risk_metrics": {
                    "portfolio_beta_60d": float(beta),
                    "var_95_1d_pct_nav": float(var95),
                    "drawdown_20d_pct": float(drawdown),
                    "vix_close": None,
                },
                "data_sufficient": False,
            }

        spy_close = float(market_snapshot["spy_close"])
        spy_sma200 = float(market_snapshot["spy_sma200"])
        spy_sma200_5d_ago = float(market_snapshot["spy_sma200_5d_ago"])
        vix_close = float(market_snapshot["vix_close"])

        if spy_sma200 == 0.0 or spy_sma200_5d_ago == 0.0:
            return {
                "base_hedge_pct": 0.0,
                "s7_boost_pct": 0.0,
                "bear_trigger_active": False,
                "crash_trigger_active": False,
                "target_hedge_pct_pre_hysteresis": 0.0,
                "mode": "BULL",
                "market_regime": "UNKNOWN",
                "risk_metrics": {
                    "portfolio_beta_60d": float(beta),
                    "var_95_1d_pct_nav": float(var95),
                    "drawdown_20d_pct": float(drawdown),
                    "vix_close": float(vix_close),
                },
                "data_sufficient": False,
            }

        bear_trigger_active = spy_close < spy_sma200

        # ── Bull regime: 0% hedge ──
        if not bear_trigger_active:
            regime = _classify_market_regime(spy_close, spy_sma200, vix_close, False)
            return {
                "base_hedge_pct": 0.0,
                "s7_boost_pct": 0.0,
                "bear_trigger_active": False,
                "crash_trigger_active": False,
                "target_hedge_pct_pre_hysteresis": 0.0,
                "mode": "BULL",
                "market_regime": regime,
                "risk_metrics": {
                    "portfolio_beta_60d": float(beta),
                    "var_95_1d_pct_nav": float(var95),
                    "drawdown_20d_pct": float(drawdown),
                    "vix_close": float(vix_close),
                },
                "data_sufficient": True,
            }

        # ── Bear regime: 85% base + optional S7 boost ──
        sma200_slope_pct_5d = ((spy_sma200 - spy_sma200_5d_ago) / spy_sma200_5d_ago) * 100.0
        crash_trigger_active = all([
            sma200_slope_pct_5d < -0.10,
            beta > 1.05,
            var95 > 3.0,
            drawdown > 5.0,
        ])

        regime = _classify_market_regime(spy_close, spy_sma200, vix_close, crash_trigger_active)

        if crash_trigger_active:
            target = MAX_HEDGE_PCT
            mode = "CRASH"
            boost = 0.0
        else:
            base = BEAR_BASE_HEDGE_PCT
            boost = S7_BOOST_PCT if s7_active else 0.0
            target = min(MAX_HEDGE_PCT, base + boost)
            mode = "BEAR_S7_BOOST" if s7_active else "BEAR"

        return {
            "base_hedge_pct": float(BEAR_BASE_HEDGE_PCT),
            "s7_boost_pct": float(boost),
            "bear_trigger_active": True,
            "crash_trigger_active": bool(crash_trigger_active),
            "target_hedge_pct_pre_hysteresis": float(target),
            "mode": mode,
            "market_regime": regime,
            "risk_metrics": {
                "portfolio_beta_60d": float(beta),
                "var_95_1d_pct_nav": float(var95),
                "drawdown_20d_pct": float(drawdown),
                "vix_close": float(vix_close),
            },
            "data_sufficient": True,
        }

    def decide_hedge(
        self,
        signal: HedgeSignal,
        portfolio_snapshot: PortfolioRiskSnapshot,
    ) -> HedgeDecision:
        gross = float(portfolio_snapshot.get("gross_exposure_usd", 0.0))
        current = float(portfolio_snapshot.get("current_hedge_pct", 0.0))
        target = float(signal.get("target_hedge_pct_pre_hysteresis", 0.0))

        instrument = "QQQ" if float(portfolio_snapshot.get("tech_concentration_pct", 0.0)) >= 50.0 else "SPY"

        if gross <= 0.0:
            return {
                "final_target_hedge_pct": 0.0,
                "instrument": instrument,
                "action": "NO_CHANGE",
                "delta_hedge_pct": 0.0,
                "delta_notional_usd": 0.0,
                "reason": "No open positions available for hedge sizing.",
                "status": "NO_POSITIONS",
            }

        if not signal.get("data_sufficient", True):
            return {
                "final_target_hedge_pct": 0.0,
                "instrument": instrument,
                "action": "NO_CHANGE",
                "delta_hedge_pct": 0.0,
                "delta_notional_usd": 0.0,
                "reason": "Market regime data is insufficient; hedge update skipped.",
                "status": "DATA_INSUFFICIENT",
            }

        delta = target - current

        # Cooldown: one rebalance per day unless emergency override.
        state = _load_json(self.state_path, {})
        last_rebalance_date = state.get("last_rebalance_date")
        today = _today_date()
        emergency = signal.get("crash_trigger_active", False)
        if last_rebalance_date == today and not emergency:
            return {
                "final_target_hedge_pct": float(current),
                "instrument": instrument,
                "action": "NO_CHANGE",
                "delta_hedge_pct": 0.0,
                "delta_notional_usd": 0.0,
                "reason": "Hedge rebalance cooldown active for current trading day.",
                "status": "SKIPPED_HYSTERESIS",
            }

        if abs(delta) < 5.0:
            return {
                "final_target_hedge_pct": float(current),
                "instrument": instrument,
                "action": "NO_CHANGE",
                "delta_hedge_pct": 0.0,
                "delta_notional_usd": 0.0,
                "reason": "Hedge delta below hysteresis threshold (5%).",
                "status": "SKIPPED_HYSTERESIS",
            }

        action = "INCREASE_HEDGE" if delta > 0 else "DECREASE_HEDGE"
        delta_notional = gross * (delta / 100.0)

        return {
            "final_target_hedge_pct": float(target),
            "instrument": instrument,
            "action": action,
            "delta_hedge_pct": float(delta),
            "delta_notional_usd": float(delta_notional),
            "reason": (
                f"Hedge target updated: {signal.get('mode', 'UNKNOWN')} regime "
                f"({signal.get('market_regime', 'UNKNOWN')})."
            ),
            "status": "EXECUTED",
        }

    def persist_state_and_orders(
        self,
        signal: HedgeSignal,
        decision: HedgeDecision,
        portfolio_snapshot: PortfolioRiskSnapshot,
    ) -> Optional[HedgeOrder]:
        state = _load_json(self.state_path, {})
        current = float(portfolio_snapshot.get("current_hedge_pct", 0.0))
        order_record: Optional[HedgeOrder] = None

        if decision["status"] == "EXECUTED":
            state["current_hedge_pct"] = float(decision["final_target_hedge_pct"])
            state["last_rebalance_date"] = _today_date()
            state["last_updated"] = _now_iso()

            order_record = {
                "timestamp": _now_iso(),
                "instrument": decision["instrument"],
                "action": decision["action"],
                "delta_hedge_pct": float(decision["delta_hedge_pct"]),
                "delta_notional_usd": float(decision["delta_notional_usd"]),
                "previous_hedge_pct": float(current),
                "target_hedge_pct": float(decision["final_target_hedge_pct"]),
                "mode": signal["mode"],
                "reason": decision["reason"],
            }

            orders = _load_json(self.orders_path, [])
            orders.append(order_record)
            _save_json(self.orders_path, orders)
        else:
            state.setdefault("current_hedge_pct", current)
            state.setdefault("last_rebalance_date", None)
            state["last_updated"] = _now_iso()

        _save_json(self.state_path, state)
        return order_record

    def evaluate(
        self,
        portfolio_snapshot: PortfolioRiskSnapshot,
        market_snapshot: Optional[MarketRegimeSnapshot],
        s7_active: bool = False,
    ) -> Tuple[HedgeSignal, HedgeDecision, Optional[HedgeOrder]]:
        signal = self.compute_hedge_signal(portfolio_snapshot, market_snapshot, s7_active=s7_active)
        decision = self.decide_hedge(signal, portfolio_snapshot)
        order = self.persist_state_and_orders(signal, decision, portfolio_snapshot)
        return signal, decision, order
