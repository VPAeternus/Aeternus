"""Portfolio construction and paper execution helpers for Step 2 wiring."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Protocol, Sequence, Tuple

import requests
import yfinance as yf

from .track_record import TrackRecord
from tradingagents.broker_adapters.alpaca import AlpacaBrokerAdapter
from tradingagents.dealflow.control_io import read_json_locked, write_json_locked
from tradingagents.dealflow.hypothesis_ledger import append_ledger_row, make_ledger_row
from tradingagents.default_config import DEFAULT_CONFIG

logger = logging.getLogger(__name__)


SUCCESS_STATUSES = {"SUCCESS", "SUCCESS_CACHED"}
EXECUTION_MODE_PAPER = "paper"
EXECUTION_MODE_LIVE = "live"
EXECUTION_MODE_ALPACA_PAPER = "alpaca-paper"
EXECUTION_MODE_ALPACA_LIVE = "alpaca-live"
TERMINAL_BROKER_STATUSES = {"FILLED", "CANCELED", "REJECTED", "EXPIRED", "REPLACED"}
INTENT_CATEGORY_HEDGE = "HEDGE"


class ExecutionAdapter(Protocol):
    """Execution adapter interface for future broker integrations."""

    mode: str

    def execute_plan(
        self,
        plan: Dict[str, Any],
        orders_path: str,
        positions_path: str,
        fill_price_slippage_bps: float,
    ) -> Dict[str, Any]:
        ...

    def close_position(
        self,
        symbol: str,
        close_price: float,
        close_date: str,
        positions_path: str,
        closed_trades_path: str,
        track_record: Optional[TrackRecord],
    ) -> Dict[str, Any]:
        ...


class PaperExecutionAdapter:
    """Paper execution adapter with broker-compatible method signatures."""

    mode = EXECUTION_MODE_PAPER

    def execute_plan(
        self,
        plan: Dict[str, Any],
        orders_path: str,
        positions_path: str,
        fill_price_slippage_bps: float,
    ) -> Dict[str, Any]:
        return execute_paper_plan(
            plan=plan,
            orders_path=orders_path,
            positions_path=positions_path,
            fill_price_slippage_bps=fill_price_slippage_bps,
        )

    def close_position(
        self,
        symbol: str,
        close_price: float,
        close_date: str,
        positions_path: str,
        closed_trades_path: str,
        track_record: Optional[TrackRecord],
    ) -> Dict[str, Any]:
        return close_paper_position(
            symbol=symbol,
            close_price=close_price,
            close_date=close_date,
            positions_path=positions_path,
            closed_trades_path=closed_trades_path,
            track_record=track_record,
        )


class LiveExecutionAdapter:
    """Safe live adapter scaffold: queue intents, do not place broker orders yet."""

    mode = EXECUTION_MODE_LIVE

    def execute_plan(
        self,
        plan: Dict[str, Any],
        orders_path: str,
        positions_path: str,
        fill_price_slippage_bps: float,
    ) -> Dict[str, Any]:
        return execute_live_plan(
            plan=plan,
            outbox_path=orders_path,
        )

    def close_position(
        self,
        symbol: str,
        close_price: float,
        close_date: str,
        positions_path: str,
        closed_trades_path: str,
        track_record: Optional[TrackRecord],
    ) -> Dict[str, Any]:
        return close_alpaca_position(
            symbol=symbol,
            mode=EXECUTION_MODE_ALPACA_PAPER,
        )


class AlpacaExecutionAdapter:
    """Alpaca adapter for direct order submission (paper/live)."""

    def __init__(self, mode: str):
        self.mode = _normalize_execution_mode(mode)
        self.is_paper = self.mode == EXECUTION_MODE_ALPACA_PAPER

    def execute_plan(
        self,
        plan: Dict[str, Any],
        orders_path: str,
        positions_path: str,
        fill_price_slippage_bps: float,
    ) -> Dict[str, Any]:
        del positions_path, fill_price_slippage_bps  # Not used for broker submission.
        return execute_alpaca_plan(
            plan=plan,
            outbox_path=orders_path,
            mode=self.mode,
        )

    def close_position(
        self,
        symbol: str,
        close_price: float,
        close_date: str,
        positions_path: str,
        closed_trades_path: str,
        track_record: Optional[TrackRecord],
    ) -> Dict[str, Any]:
        return close_alpaca_position(
            symbol=symbol,
            mode=self.mode,
        )


def get_execution_adapter(mode: str = EXECUTION_MODE_PAPER) -> ExecutionAdapter:
    """Resolve execution adapter by mode."""
    normalized = _normalize_execution_mode(mode)
    if normalized == EXECUTION_MODE_PAPER:
        return PaperExecutionAdapter()
    if normalized == EXECUTION_MODE_LIVE:
        return LiveExecutionAdapter()
    if normalized in {EXECUTION_MODE_ALPACA_PAPER, EXECUTION_MODE_ALPACA_LIVE}:
        return AlpacaExecutionAdapter(mode=normalized)
    raise ValueError(f"Unsupported execution mode: {mode}")


def build_portfolio_plan(
    batch_summary: Dict[str, Any],
    capital_usd: float,
    max_positions: int,
    min_score: float = 55.0,
    min_confidence: int = 3,
    long_only: bool = True,
    max_weight_per_position: float = 0.25,
    enforce_whole_shares: bool = False,
    ledger_base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Create deterministic order intents from analyze-batch outcomes."""
    run_date = str(batch_summary.get("date", ""))
    run_id = str(batch_summary.get("run_id", ""))
    plan_id = str(uuid.uuid4())
    items = list(batch_summary.get("items", []))
    eligible: List[Dict[str, Any]] = []
    considered_symbols: List[str] = []
    considered_seen: set[str] = set()

    for item in items:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "")).upper()
        if status not in SUCCESS_STATUSES:
            continue
        recommendation = str(item.get("recommendation", "UNKNOWN")).upper()
        side = _recommendation_to_side(recommendation, long_only=long_only)
        if side == "SKIP":
            continue
        symbol = str(item.get("symbol", "")).upper().strip()
        if symbol and symbol not in considered_seen:
            considered_seen.add(symbol)
            considered_symbols.append(symbol)

        score = float(item.get("aeternus_score") or 0.0)
        confidence = int(item.get("confidence") or 0)
        if score < float(min_score) or confidence < int(min_confidence):
            continue

        analysis_path = item.get("analysis_report_path")
        analysis = _load_json(Path(analysis_path)) if analysis_path else {}
        rating_id = _extract_rating_id(analysis)
        ref_price = _extract_reference_price(item=item, analysis=analysis)
        reference_price_source = "analysis_report"
        if ref_price is None or ref_price <= 0:
            ref_price = _fetch_reference_price_from_market(
                symbol=str(item.get("symbol", "")),
                analysis_date=str(batch_summary.get("date", "")),
            )
            reference_price_source = "market_fallback"
        if ref_price is None or ref_price <= 0:
            continue

        lane = str(item.get("lane", "CORE")).upper()
        playbook = str(item.get("research_playbook", "N/A"))
        dominant_family = str(item.get("dominant_signal_family", "unknown"))
        raw_weight_signal = max(0.0, score - 50.0) * max(1.0, float(confidence))

        # Extract pillar breakdown and weight regime for IC tracking
        _score_block = analysis.get("aeternus_score", {}) if isinstance(analysis, dict) else {}
        pillar_breakdown = _score_block.get("breakdown", {}) if isinstance(_score_block, dict) else {}
        weight_regime = str(_score_block.get("weight_regime", "")) if isinstance(_score_block, dict) else ""

        eligible.append(
            {
                "queue_id": str(item.get("queue_id", "")),
                "symbol": symbol,
                "side": side,
                "recommendation": recommendation,
                "aeternus_score": score,
                "confidence": confidence,
                "lane": lane,
                "research_playbook": playbook,
                "dominant_signal_family": dominant_family,
                "rating_id": rating_id,
                "reference_price": float(ref_price),
                "reference_price_source": reference_price_source,
                "weight_signal": float(raw_weight_signal),
                "entry_pillar_breakdown": dict(pillar_breakdown),
                "entry_weight_regime": weight_regime,
            }
        )

    eligible.sort(
        key=lambda row: (
            -float(row.get("aeternus_score", 0.0)),
            -float(row.get("confidence", 0.0)),
            str(row.get("symbol", "")),
        )
    )
    selected = eligible[: max(0, int(max_positions))]
    weights, alloc_meta = _conviction_weights(
        rows=selected,
        max_weight_per_position=float(max_weight_per_position),
    )

    # ── Kelly sizing from track record ──────────────────────────────────
    kelly_fraction = 1.0  # default: full deployment (no track record)
    kelly_stats: Dict[str, Any] = {}
    try:
        from tradingagents.graph.equity_curve import EquityCurveEngine
        from tradingagents.capital_allocator.kelly import compute_kelly_fraction, apply_kelly_sizing

        ec = EquityCurveEngine()
        curve = ec.build()
        stats = curve.get("stats", {})
        tc = stats.get("trade_count", 0)
        if tc >= 10:
            kf = compute_kelly_fraction(
                win_rate=stats.get("win_rate", 0.0),
                avg_win_pct=stats.get("avg_win_pct", 0.0),
                avg_loss_pct=stats.get("avg_loss_pct", 0.0),
                trade_count=tc,
                fractional=0.25,
            )
            if kf > 0:
                kelly_fraction = min(kf, 1.0)
                weight_dict = {selected[i]["symbol"]: w for i, w in enumerate(weights)}
                scaled = apply_kelly_sizing(weight_dict, kelly_fraction)
                weights = [scaled.get(selected[i]["symbol"], w) for i, w in enumerate(weights)]
        kelly_stats = {
            "kelly_fraction": kelly_fraction,
            "trade_count": tc,
            "win_rate": stats.get("win_rate", 0.0),
        }
    except Exception:
        pass
    alloc_meta["kelly"] = kelly_stats

    orders: List[Dict[str, Any]] = []
    for idx, (row, weight) in enumerate(zip(selected, weights), start=1):
        raw_notional = float(capital_usd) * float(weight)
        ref_price = float(row["reference_price"])
        raw_quantity = raw_notional / ref_price if ref_price > 0 else 0.0
        quantity = _coerce_order_quantity(
            raw_qty=raw_quantity,
            whole_shares=bool(enforce_whole_shares),
        )
        if quantity <= 0.0:
            continue
        notional = float(quantity) * ref_price
        target_weight = notional / float(capital_usd) if capital_usd > 0 else 0.0
        order_intent_id = str(uuid.uuid4())
        side = str(row["side"]).upper()
        sym = row["symbol"]
        client_order_id = _build_client_order_id(
            plan_id=plan_id,
            symbol=sym,
            ordinal=idx,
        )
        order = {
            "order_intent_id": order_intent_id,
            "client_order_id": client_order_id,
            "idempotency_key": order_intent_id,
            "symbol": sym,
            "side": side,
            "order_type": "MARKET",
            "time_in_force": "DAY",
            "execution_mode": EXECUTION_MODE_PAPER,
            "target_weight": float(round(target_weight, 6)),
            "target_notional_usd": float(round(notional, 2)),
            "reference_price": float(round(ref_price, 6)),
            "reference_price_source": str(row.get("reference_price_source", "analysis_report")),
            "target_quantity": float(round(quantity, 6)),
            "quantity_policy": "WHOLE_SHARES" if enforce_whole_shares else "FRACTIONAL_OK",
            "aeternus_score": float(round(row["aeternus_score"], 4)),
            "confidence": int(row["confidence"]),
            "lane": row["lane"],
            "research_playbook": row["research_playbook"],
            "dominant_signal_family": row["dominant_signal_family"],
            "queue_id": row["queue_id"],
            "rating_id": row.get("rating_id"),
            "entry_pillar_breakdown": row.get("entry_pillar_breakdown", {}),
            "entry_weight_regime": row.get("entry_weight_regime", ""),
            "cc_eligible": quantity >= 100.0,
            # ── Conviction allocation metadata ──
            "conviction_tier": alloc_meta.get("tiers", {}).get(sym, "UNKNOWN"),
            "base_weight": alloc_meta.get("pre_adj_weights", {}).get(sym, 0.0),
            "vol_adjusted_weight": weight,
            "final_weight": float(round(target_weight, 6)),
            "vol_20d_annualized": alloc_meta.get("vol_data", {}).get(sym, 0.0),
            "correlation_max": alloc_meta.get("max_correlations", {}).get(sym, 0.0),
        }
        orders.append(order)

    # ── V3 residual: deploy remaining capital to QQQ ──────────────────────
    core_notional = sum(o["target_notional_usd"] for o in orders)
    residual_usd = max(0.0, float(capital_usd) - core_notional)
    v3_ticker = str(DEFAULT_CONFIG.get("v3_trade_instrument", "QQQ")).upper().strip() or "QQQ"

    # Leverage-adjusted sizing: for leveraged instruments (TQQQ etc.),
    # deploy only residual/effective_leverage to get equivalent QQQ exposure.
    # Empirical effective leverage ~2.1x (not 3x) due to volatility drag.
    v3_effective_lev = float(DEFAULT_CONFIG.get("v3_effective_leverage", 2.1))
    v3_sizing_usd = residual_usd / v3_effective_lev if (v3_ticker != "QQQ" and v3_effective_lev > 1.0) else residual_usd

    if residual_usd > 0:
        v3_ref_price = _fetch_reference_price_from_market(v3_ticker, run_date)
        if v3_ref_price and v3_ref_price > 0:
            v3_qty_raw = v3_sizing_usd / v3_ref_price
            v3_qty = _coerce_order_quantity(v3_qty_raw, whole_shares=bool(enforce_whole_shares))
            if v3_qty > 0:
                v3_notional = v3_qty * v3_ref_price
                orders.append({
                    "order_intent_id": str(uuid.uuid4()),
                    "client_order_id": _build_client_order_id(plan_id, v3_ticker, len(orders) + 1),
                    "idempotency_key": str(uuid.uuid4()),
                    "symbol": v3_ticker,
                    "side": "BUY",
                    "order_type": "MARKET",
                    "time_in_force": "DAY",
                    "execution_mode": EXECUTION_MODE_PAPER,
                    "target_weight": round(v3_notional / float(capital_usd), 6) if capital_usd > 0 else 0.0,
                    "target_notional_usd": round(v3_notional, 2),
                    "reference_price": round(v3_ref_price, 6),
                    "reference_price_source": "market_fallback",
                    "target_quantity": round(v3_qty, 6),
                    "quantity_policy": "WHOLE_SHARES" if enforce_whole_shares else "FRACTIONAL_OK",
                    "aeternus_score": 0.0,
                    "confidence": 0,
                    "lane": "MOMENTUM",
                    "research_playbook": "V3_INDEX",
                    "dominant_signal_family": "v3_benchmark",
                    "queue_id": "",
                    "rating_id": None,
                    "cc_eligible": v3_qty >= 100.0,
                    "entry_pillar_breakdown": {},
                    "entry_weight_regime": "",
                    "v3_underlying": "QQQ",
                    "v3_effective_leverage": v3_effective_lev if v3_ticker != "QQQ" else 1.0,
                })

    # ── Allocation summary ─────────────────────────────────────────────────
    conviction_total = sum(w for w in weights)
    tier_dist: Dict[str, int] = {}
    for tier_label in alloc_meta.get("tiers", {}).values():
        tier_dist[tier_label] = tier_dist.get(tier_label, 0) + 1

    allocation_summary = {
        "total_conviction_pct": round(conviction_total * 100.0, 2),
        "v3_remainder_pct": round((1.0 - conviction_total) * 100.0, 2),
        "tier_distribution": tier_dist,
        "avg_pairwise_correlation": alloc_meta.get("avg_pairwise_correlation", 0.0),
        "effective_positions": alloc_meta.get("effective_positions", float(len(selected))),
        "kelly": alloc_meta.get("kelly", {}),
    }
    if ledger_base_dir is not None:
        kept_symbols = [
            str(order.get("symbol", "")).upper().strip()
            for order in orders
            if str(order.get("queue_id", "")).strip()
        ]
        kept_set = set(kept_symbols)
        portfolio_inclusion_row = make_ledger_row(
            run_id=run_id,
            source_date=run_date,
            lane="shared",
            stage_id="portfolio_inclusion_cut",
            rule_snapshot={
                "max_positions": int(max_positions),
                "min_score": float(min_score),
                "min_confidence": int(min_confidence),
                "long_only": bool(long_only),
                "max_weight_per_position": float(max_weight_per_position),
            },
            kept_symbols=kept_symbols,
            dropped_symbols=[
                symbol for symbol in considered_symbols if symbol not in kept_set
            ],
            base_dir=Path(ledger_base_dir),
        )
        append_ledger_row(
            base_dir=Path(ledger_base_dir),
            lane="shared",
            row=portfolio_inclusion_row,
        )

    return {
        "plan_id": plan_id,
        "created_at": _now_iso(),
        "date": run_date,
        "source_run_id": run_id,
        "source_summary_path": batch_summary.get("summary_path"),
        "capital_usd": float(capital_usd),
        "max_positions": int(max_positions),
        "min_score": float(min_score),
        "min_confidence": int(min_confidence),
        "long_only": bool(long_only),
        "max_weight_per_position": float(max_weight_per_position),
        "candidates_considered": len(eligible),
        "allocation_summary": allocation_summary,
        "v3_residual_usd": round(residual_usd, 2),
        "v3_sizing_usd": round(v3_sizing_usd, 2),
        "v3_cash_reserve_usd": round(residual_usd - v3_sizing_usd, 2),
        "v3_ticker": v3_ticker,
        "v3_underlying": "QQQ",
        "v3_effective_leverage": v3_effective_lev if v3_ticker != "QQQ" else 1.0,
        "orders": orders,
    }


def build_hedge_order_intent(
    plan_id: str,
    run_date: str,
    capital_usd: float,
    portfolio_snapshot: Dict[str, Any],
    hedge_signal: Dict[str, Any],
    hedge_decision: Dict[str, Any],
    enforce_whole_shares: bool = False,
) -> Optional[Dict[str, Any]]:
    """Convert a hedge decision into a portfolio-plan intent.

    The resulting intent represents the *target hedge notional*, so when
    `build_rebalance_execution_plan` is enabled it naturally generates the
    correct delta against current hedge exposure.
    """
    if str(hedge_decision.get("status") or "").upper() != "EXECUTED":
        return None

    instrument = str(hedge_decision.get("instrument") or "").upper().strip()
    if instrument not in {"SPY", "QQQ"}:
        return None

    gross = float(portfolio_snapshot.get("gross_exposure_usd", 0.0) or 0.0)
    if gross <= 0.0:
        return None

    target_hedge_pct = _clamp_float(
        float(hedge_decision.get("final_target_hedge_pct", 0.0) or 0.0),
        0.0,
        150.0,
    )
    target_notional = gross * (target_hedge_pct / 100.0)
    reference_price = _fetch_reference_price_from_market(
        symbol=instrument,
        analysis_date=str(run_date or ""),
    )
    if reference_price is None or reference_price <= 0.0:
        return None

    target_quantity = target_notional / float(reference_price) if reference_price > 0.0 else 0.0
    target_quantity = _coerce_order_quantity(
        raw_qty=target_quantity,
        whole_shares=bool(enforce_whole_shares),
    )
    if target_notional > 0.0 and target_quantity <= 0.0:
        return None

    side = "SELL" if target_notional > 0.0 else "BUY"
    intent_id = str(uuid.uuid4())
    weight = (target_notional / float(capital_usd)) if float(capital_usd) > 0 else 0.0
    return {
        "order_intent_id": intent_id,
        "client_order_id": _build_client_order_id(plan_id=plan_id, symbol=instrument, ordinal=999),
        "idempotency_key": intent_id,
        "symbol": instrument,
        "side": side,
        "order_type": "MARKET",
        "time_in_force": "DAY",
        "execution_mode": EXECUTION_MODE_PAPER,
        "target_weight": float(round(weight, 6)),
        "target_notional_usd": float(round(target_notional, 2)),
        "reference_price": float(round(float(reference_price), 6)),
        "reference_price_source": "market_fallback",
        "target_quantity": float(round(target_quantity, 6)),
        "quantity_policy": "WHOLE_SHARES" if enforce_whole_shares else "FRACTIONAL_OK",
        "aeternus_score": 0.0,
        "confidence": 0,
        "lane": "HEDGE",
        "research_playbook": "HEDGE_OVERLAY",
        "dominant_signal_family": "hedging_overlay",
        "queue_id": "",
        "rating_id": f"HEDGE:{str(run_date or _today_date())}",
        "intent_category": INTENT_CATEGORY_HEDGE,
        "hedge_mode": str(hedge_signal.get("mode") or "BULL"),
        "hedge_market_regime": str(hedge_signal.get("market_regime") or "UNKNOWN"),
        "hedge_target_pct": float(round(target_hedge_pct, 4)),
        "hedge_delta_pct": float(round(float(hedge_decision.get("delta_hedge_pct", 0.0) or 0.0), 4)),
        "hedge_delta_notional_usd": float(
            round(float(hedge_decision.get("delta_notional_usd", 0.0) or 0.0), 2)
        ),
        "hedge_reason": str(hedge_decision.get("reason") or ""),
        "hedge_status": str(hedge_decision.get("status") or "UNKNOWN"),
    }


def execute_paper_plan(
    plan: Dict[str, Any],
    orders_path: str = "eval_results/paper_execution/orders.json",
    positions_path: str = "eval_results/paper_execution/positions.json",
    fill_price_slippage_bps: float = 0.0,
) -> Dict[str, Any]:
    """Fill order intents into paper ledgers and update open positions."""
    orders_file = Path(orders_path)
    positions_file = Path(positions_path)
    orders_history = _load_json(orders_file, default=[])
    if not isinstance(orders_history, list):
        orders_history = []
    positions_state = _load_json(positions_file, default={})
    open_positions = dict(positions_state.get("open_positions", {}))
    existing_intent_ids = {
        str(order.get("order_intent_id", "")).strip()
        for order in orders_history
        if isinstance(order, dict)
    }

    created_orders: List[Dict[str, Any]] = []
    skipped_duplicates: List[str] = []
    auto_close_events: List[Dict[str, Any]] = []

    # --- Drawdown Health Monitor (informational only — hedge engine handles protection) ---
    try:
        from tradingagents.graph.drawdown_guard import check_drawdown_state, update_hwm_equity
        _dd = check_drawdown_state(positions_path=str(positions_file))
        if _dd["drawdown_pct"] > 0:
            logger.info("DRAWDOWN MONITOR: status=%s dd=%.2f%% equity=%.0f hwm=%.0f",
                        _dd["status"], _dd["drawdown_pct"],
                        _dd["current_equity"], _dd["high_water_mark"])
    except Exception:
        pass  # Never crash execution

    # --- ADV / Liquidity Gate ---
    try:
        from tradingagents.graph.liquidity_gate import filter_orders_by_liquidity
        _min_adv = float(plan.get("min_adv_usd") or DEFAULT_CONFIG.get("execution_min_adv_usd", 10_000_000))
        _min_cap = float(plan.get("min_market_cap") or DEFAULT_CONFIG.get("execution_min_market_cap", 100_000_000))
        _orders_all = list(plan.get("orders", []))
        _passed, _rejected = filter_orders_by_liquidity(_orders_all, min_adv_usd=_min_adv, min_market_cap=_min_cap)
        if _rejected:
            logger.warning("LIQUIDITY GATE: rejected %d orders: %s",
                            len(_rejected), [r["symbol"] for r in _rejected])
            plan = dict(plan)
            plan["orders"] = _passed
            plan["liquidity_rejected"] = _rejected
    except Exception:
        pass  # Never crash execution over liquidity gate

    for intent in plan.get("orders", []):
        if not isinstance(intent, dict):
            continue
        order_intent_id = str(intent.get("order_intent_id", "")).strip()
        if order_intent_id and order_intent_id in existing_intent_ids:
            skipped_duplicates.append(order_intent_id)
            continue
        side = str(intent.get("side", "BUY")).upper()
        ref_price = float(intent.get("reference_price", 0.0) or 0.0)
        quantity = float(intent.get("target_quantity", 0.0) or 0.0)
        symbol = str(intent.get("symbol", "")).upper().strip()
        if not symbol or ref_price <= 0 or quantity <= 0:
            continue

        fill_price = _apply_slippage(
            reference_price=ref_price,
            side=side,
            bps=float(fill_price_slippage_bps),
        )
        signed_qty = quantity if side == "BUY" else -quantity
        signed_notional = signed_qty * fill_price

        order = {
            "execution_id": str(uuid.uuid4()),
            "broker_order_id": f"paper-{uuid.uuid4().hex[:12]}",
            "executed_at": _now_iso(),
            "plan_id": plan.get("plan_id"),
            "date": plan.get("date"),
            "order_intent_id": order_intent_id,
            "client_order_id": intent.get("client_order_id"),
            "idempotency_key": intent.get("idempotency_key") or order_intent_id,
            "symbol": symbol,
            "side": side,
            "order_type": str(intent.get("order_type") or "MARKET"),
            "time_in_force": str(intent.get("time_in_force") or "DAY"),
            "execution_mode": str(intent.get("execution_mode") or EXECUTION_MODE_PAPER),
            "filled_quantity": float(round(quantity, 6)),
            "filled_price": float(round(fill_price, 6)),
            "filled_notional_usd": float(round(abs(signed_notional), 2)),
            "signed_quantity": float(round(signed_qty, 6)),
            "queue_id": intent.get("queue_id"),
            "rating_id": intent.get("rating_id"),
            "lane": intent.get("lane"),
            "research_playbook": intent.get("research_playbook"),
            "dominant_signal_family": intent.get("dominant_signal_family"),
            "intent_category": intent.get("intent_category"),
            "hedge_mode": intent.get("hedge_mode"),
            "hedge_market_regime": intent.get("hedge_market_regime"),
            "hedge_target_pct": intent.get("hedge_target_pct"),
            "hedge_delta_pct": intent.get("hedge_delta_pct"),
            "hedge_delta_notional_usd": intent.get("hedge_delta_notional_usd"),
            "hedge_reason": intent.get("hedge_reason"),
            "exit_rule": intent.get("exit_rule"),
            "exit_reason": intent.get("exit_reason"),
            "aeternus_score": intent.get("aeternus_score"),
            "reference_price": intent.get("reference_price"),
            "reference_price_source": intent.get("reference_price_source"),
            "status": "FILLED",
        }
        created_orders.append(order)
        orders_history.append(order)
        if order_intent_id:
            existing_intent_ids.add(order_intent_id)
        # Snapshot position BEFORE fill to capture close metadata
        pre_fill_position = dict(open_positions.get(symbol, {})) if symbol in open_positions else None
        _apply_fill_to_position(open_positions=open_positions, order=order)

        # Detect position closure (symbol removed by _apply_fill_to_position)
        if pre_fill_position and symbol not in open_positions:
            avg_entry = float(pre_fill_position.get("avg_price", 0) or 0)
            net_qty = float(pre_fill_position.get("net_quantity", 0) or 0)
            pnl = (fill_price - avg_entry) * net_qty if avg_entry > 0 else 0.0
            ret_pct = 0.0
            if avg_entry > 0:
                side_scalar = 1.0 if net_qty > 0 else -1.0
                ret_pct = (((fill_price - avg_entry) / avg_entry) * side_scalar) * 100.0

            opened_at = pre_fill_position.get("opened_at", "")
            hold_days = 0
            if opened_at:
                try:
                    from datetime import datetime as _dt
                    _opened = _dt.fromisoformat(opened_at.replace("Z", "+00:00"))
                    hold_days = max(0, (_dt.now(_opened.tzinfo) - _opened).days)
                except Exception:
                    pass

            close_event = {
                "close_id": str(uuid.uuid4()),
                "closed_at": _now_iso(),
                "symbol": symbol,
                "close_date": plan.get("date", ""),
                "close_price": float(round(fill_price, 6)),
                "net_quantity": float(round(net_qty, 6)),
                "avg_entry_price": float(round(avg_entry, 6)),
                "pnl_usd": float(round(pnl, 2)),
                "return_pct": float(round(ret_pct, 4)),
                "rating_ids": pre_fill_position.get("rating_ids", []),
                "exit_rule": order.get("exit_rule") or "UNKNOWN",
                "exit_reason": order.get("exit_reason") or "",
                "entry_aeternus_score": float(pre_fill_position.get("entry_aeternus_score", 0) or 0),
                "entry_pillar_breakdown": dict(pre_fill_position.get("entry_pillar_breakdown", {})),
                "entry_weight_regime": str(pre_fill_position.get("entry_weight_regime", "")),
                "hold_days": hold_days,
                "lane": pre_fill_position.get("lane") or order.get("lane") or "",
                "research_playbook": pre_fill_position.get("research_playbook") or order.get("research_playbook") or "",
            }
            auto_close_events.append(close_event)

    # Persist auto-close events to closed_trades.json
    if auto_close_events:
        closed_trades_path = Path(orders_path).parent / "closed_trades.json"
        closed_history = _load_json(closed_trades_path, default=[])
        if not isinstance(closed_history, list):
            closed_history = []
        closed_history.extend(auto_close_events)
        _save_json(closed_trades_path, closed_history)

    positions_state = {
        "updated_at": _now_iso(),
        "open_positions": open_positions,
        "source_plan_id": plan.get("plan_id"),
        "source_date": plan.get("date"),
    }
    _save_json(orders_file, orders_history)
    _save_json(positions_file, positions_state)

    # Update HWM with current equity
    try:
        from tradingagents.graph.drawdown_guard import compute_portfolio_equity, update_hwm_equity
        _equity = compute_portfolio_equity(positions_path=str(positions_file))
        if _equity > 0:
            update_hwm_equity(_equity)
    except Exception:
        pass

    return {
        "plan_id": plan.get("plan_id"),
        "date": plan.get("date"),
        "execution_mode": EXECUTION_MODE_PAPER,
        "executed_orders": len(created_orders),
        "skipped_duplicate_orders": len(skipped_duplicates),
        "orders_path": str(orders_file),
        "positions_path": str(positions_file),
        "skipped_duplicate_intent_ids": skipped_duplicates,
        "orders": created_orders,
    }


def execute_live_plan(
    plan: Dict[str, Any],
    outbox_path: str = "eval_results/live_execution/outbox.json",
) -> Dict[str, Any]:
    """Queue live intents into an outbox without broker side effects."""
    outbox_file = Path(outbox_path)
    outbox_history = _load_json(outbox_file, default=[])
    if not isinstance(outbox_history, list):
        outbox_history = []
    existing_intent_ids = {
        str(order.get("order_intent_id", "")).strip()
        for order in outbox_history
        if isinstance(order, dict)
    }

    submitted_orders: List[Dict[str, Any]] = []
    skipped_duplicates: List[str] = []
    for intent in plan.get("orders", []):
        if not isinstance(intent, dict):
            continue
        order_intent_id = str(intent.get("order_intent_id", "")).strip()
        if order_intent_id and order_intent_id in existing_intent_ids:
            skipped_duplicates.append(order_intent_id)
            continue

        symbol = str(intent.get("symbol", "")).upper().strip()
        side = str(intent.get("side", "BUY")).upper()
        if not symbol or side not in {"BUY", "SELL"}:
            continue
        target_qty = float(intent.get("target_quantity", 0.0) or 0.0)
        if target_qty <= 0.0:
            continue

        submission = {
            "submission_id": str(uuid.uuid4()),
            "submitted_at": _now_iso(),
            "plan_id": plan.get("plan_id"),
            "date": plan.get("date"),
            "order_intent_id": order_intent_id,
            "client_order_id": intent.get("client_order_id"),
            "idempotency_key": intent.get("idempotency_key") or order_intent_id,
            "symbol": symbol,
            "side": side,
            "order_type": str(intent.get("order_type") or "MARKET"),
            "time_in_force": str(intent.get("time_in_force") or "DAY"),
            "execution_mode": EXECUTION_MODE_LIVE,
            "target_quantity": float(round(target_qty, 6)),
            "target_notional_usd": float(round(_extract_order_notional_usd(intent), 2)),
            "reference_price": float(round(float(intent.get("reference_price", 0.0) or 0.0), 6)),
            "queue_id": intent.get("queue_id"),
            "rating_id": intent.get("rating_id"),
            "lane": intent.get("lane"),
            "research_playbook": intent.get("research_playbook"),
            "dominant_signal_family": intent.get("dominant_signal_family"),
            "intent_category": intent.get("intent_category"),
            "hedge_mode": intent.get("hedge_mode"),
            "hedge_market_regime": intent.get("hedge_market_regime"),
            "hedge_target_pct": intent.get("hedge_target_pct"),
            "hedge_delta_pct": intent.get("hedge_delta_pct"),
            "hedge_delta_notional_usd": intent.get("hedge_delta_notional_usd"),
            "hedge_reason": intent.get("hedge_reason"),
            "status": "SUBMITTED",
            "note": "LIVE_STUB_QUEUE_ONLY",
        }
        submitted_orders.append(submission)
        outbox_history.append(submission)
        if order_intent_id:
            existing_intent_ids.add(order_intent_id)

    _save_json(outbox_file, outbox_history)

    return {
        "plan_id": plan.get("plan_id"),
        "date": plan.get("date"),
        "execution_mode": EXECUTION_MODE_LIVE,
        "executed_orders": 0,
        "submitted_orders": len(submitted_orders),
        "skipped_duplicate_orders": len(skipped_duplicates),
        "orders_path": str(outbox_file),
        "positions_path": "",
        "skipped_duplicate_intent_ids": skipped_duplicates,
        "orders": submitted_orders,
        "warnings": ["LIVE_STUB_QUEUE_ONLY"],
    }


def execute_alpaca_plan(
    plan: Dict[str, Any],
    outbox_path: str = "eval_results/live_execution/outbox.json",
    mode: str = EXECUTION_MODE_ALPACA_PAPER,
) -> Dict[str, Any]:
    """Submit intents to Alpaca and persist broker submissions in outbox."""
    normalized_mode = _normalize_execution_mode(mode)
    base_url, api_key_id, api_secret_key, timeout = _resolve_alpaca_credentials(normalized_mode)
    enforce_whole_shares = _env_bool("ALPACA_ENFORCE_WHOLE_SHARES", True)
    if not api_key_id or not api_secret_key:
        raise ValueError(
            "Alpaca credentials missing. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY."
        )

    skip_market_hours_check = _env_bool("SKIP_MARKET_HOURS_CHECK", False)
    if not skip_market_hours_check:
        headers = _alpaca_headers(api_key_id=api_key_id, api_secret_key=api_secret_key)
        clock_payload, clock_error = _alpaca_get_json(
            base_url=base_url,
            endpoint="/v2/clock",
            headers=headers,
            timeout_seconds=timeout,
        )
        if clock_error is None and not bool((clock_payload or {}).get("is_open", True)):
            return {
                "plan_id": plan.get("plan_id"),
                "date": plan.get("date"),
                "execution_mode": normalized_mode,
                "market_closed": True,
                "executed_orders": 0,
                "submitted_orders": 0,
                "failed_orders": 0,
                "skipped_duplicate_orders": 0,
                "orders_path": str(outbox_path),
                "positions_path": "",
                "skipped_duplicate_intent_ids": [],
                "orders": [],
                "failed": [],
            }

    outbox_file = Path(outbox_path)
    outbox_history = _load_json(outbox_file, default=[])
    if not isinstance(outbox_history, list):
        outbox_history = []
    existing_intent_ids = {
        str(order.get("order_intent_id", "")).strip()
        for order in outbox_history
        if isinstance(order, dict)
    }

    submitted_orders: List[Dict[str, Any]] = []
    failed_orders: List[Dict[str, Any]] = []
    skipped_duplicates: List[str] = []

    for intent in plan.get("orders", []):
        if not isinstance(intent, dict):
            continue
        order_intent_id = str(intent.get("order_intent_id", "")).strip()
        if order_intent_id and order_intent_id in existing_intent_ids:
            skipped_duplicates.append(order_intent_id)
            continue

        symbol = str(intent.get("symbol", "")).upper().strip()
        side = str(intent.get("side", "BUY")).upper()
        if not symbol or side not in {"BUY", "SELL"}:
            continue

        raw_target_qty = float(intent.get("target_quantity", 0.0) or 0.0)
        if raw_target_qty <= 0.0:
            continue
        target_qty = _coerce_order_quantity(
            raw_qty=raw_target_qty,
            whole_shares=enforce_whole_shares,
        )
        if target_qty <= 0.0:
            failed_orders.append(
                {
                    "order_intent_id": order_intent_id,
                    "symbol": symbol,
                    "side": side,
                    "error": "WHOLE_SHARE_ROUND_DOWN_TO_ZERO",
                }
            )
            continue

        client_order_id = str(intent.get("client_order_id") or "")
        if not client_order_id:
            client_order_id = f"ag-{order_intent_id or uuid.uuid4().hex}"
        client_order_id = client_order_id[:48]

        payload = {
            "symbol": symbol,
            "qty": _format_qty(target_qty),
            "side": side.lower(),
            "type": str(intent.get("order_type") or "MARKET").lower(),
            "time_in_force": str(intent.get("time_in_force") or "DAY").lower(),
            "client_order_id": client_order_id,
        }

        try:
            response_payload = _submit_alpaca_order(
                base_url=base_url,
                api_key_id=api_key_id,
                api_secret_key=api_secret_key,
                payload=payload,
                timeout_seconds=timeout,
            )
        except Exception as exc:
            failed_orders.append(
                {
                    "order_intent_id": order_intent_id,
                    "symbol": symbol,
                    "side": side,
                    "error": str(exc),
                }
            )
            logger.warning(
                "Alpaca order failed: %s %s intent_id=%s error=%s",
                side,
                symbol,
                order_intent_id,
                str(exc),
            )
            continue

        broker_status = _normalize_broker_status(
            str(response_payload.get("status") or "SUBMITTED")
        )
        broker_order_id = str(response_payload.get("id") or "")
        ref_price = float(intent.get("reference_price", 0.0) or 0.0)
        if ref_price > 0.0:
            target_notional_usd = target_qty * ref_price
        else:
            target_notional_usd = _extract_order_notional_usd(intent)

        submission = {
            "submission_id": str(uuid.uuid4()),
            "submitted_at": _now_iso(),
            "plan_id": plan.get("plan_id"),
            "date": plan.get("date"),
            "order_intent_id": order_intent_id,
            "client_order_id": client_order_id,
            "idempotency_key": intent.get("idempotency_key") or order_intent_id,
            "symbol": symbol,
            "side": side,
            "order_type": str(intent.get("order_type") or "MARKET"),
            "time_in_force": str(intent.get("time_in_force") or "DAY"),
            "execution_mode": normalized_mode,
            "target_quantity": float(round(target_qty, 6)),
            "target_notional_usd": float(round(target_notional_usd, 2)),
            "reference_price": float(round(ref_price, 6)),
            "quantity_policy": "WHOLE_SHARES" if enforce_whole_shares else "FRACTIONAL_OK",
            "queue_id": intent.get("queue_id"),
            "rating_id": intent.get("rating_id"),
            "lane": intent.get("lane"),
            "research_playbook": intent.get("research_playbook"),
            "dominant_signal_family": intent.get("dominant_signal_family"),
            "intent_category": intent.get("intent_category"),
            "hedge_mode": intent.get("hedge_mode"),
            "hedge_market_regime": intent.get("hedge_market_regime"),
            "hedge_target_pct": intent.get("hedge_target_pct"),
            "hedge_delta_pct": intent.get("hedge_delta_pct"),
            "hedge_delta_notional_usd": intent.get("hedge_delta_notional_usd"),
            "hedge_reason": intent.get("hedge_reason"),
            "status": broker_status or "SUBMITTED",
            "broker_order_id": broker_order_id,
            "broker_status_raw": str(response_payload.get("status") or ""),
            "broker_snapshot": {
                "submitted_qty": response_payload.get("qty"),
                "filled_qty": response_payload.get("filled_qty"),
                "filled_avg_price": response_payload.get("filled_avg_price"),
            },
            "note": "ALPACA_ORDER_SUBMITTED",
        }
        submitted_orders.append(submission)
        outbox_history.append(submission)
        if order_intent_id:
            existing_intent_ids.add(order_intent_id)
        logger.info(
            "Alpaca order submitted: %s %s qty=%s broker_order_id=%s status=%s mode=%s",
            side,
            symbol,
            _format_qty(target_qty),
            broker_order_id,
            broker_status,
            normalized_mode,
        )

    _save_json(outbox_file, outbox_history)

    return {
        "plan_id": plan.get("plan_id"),
        "date": plan.get("date"),
        "execution_mode": normalized_mode,
        "executed_orders": 0,
        "submitted_orders": len(submitted_orders),
        "failed_orders": len(failed_orders),
        "skipped_duplicate_orders": len(skipped_duplicates),
        "orders_path": str(outbox_file),
        "positions_path": "",
        "skipped_duplicate_intent_ids": skipped_duplicates,
        "orders": submitted_orders,
        "failed": failed_orders,
    }


def fetch_alpaca_orders_snapshot(
    out_path: str,
    mode: str = EXECUTION_MODE_ALPACA_PAPER,
    status: str = "all",
    limit: int = 500,
) -> Dict[str, Any]:
    """Fetch broker orders from Alpaca and persist snapshot for reconciliation."""
    normalized_mode = _normalize_execution_mode(mode)
    base_url, api_key_id, api_secret_key, timeout = _resolve_alpaca_credentials(normalized_mode)
    if not api_key_id or not api_secret_key:
        raise ValueError(
            "Alpaca credentials missing. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY."
        )

    params = {
        "status": str(status or "all").lower(),
        "limit": max(1, min(int(limit), 500)),
        "direction": "desc",
        "nested": "true",
    }
    raw_payload, fetch_error = _get_broker_adapter().get_json(
        endpoint="/v2/orders",
        method="GET",
        params=params,
        base_url_override=base_url,
    )
    if fetch_error:
        raise ValueError(f"Alpaca orders fetch failed: {fetch_error}")

    payload = raw_payload if isinstance(raw_payload, list) else []
    snapshot = {
        "source": "alpaca",
        "mode": normalized_mode,
        "fetched_at": _now_iso(),
        "base_url": base_url,
        "status": str(status or "all").lower(),
        "limit": int(params["limit"]),
        "orders": payload,
    }
    target = Path(out_path)
    _save_json(target, snapshot)
    return snapshot


def fetch_alpaca_positions_snapshot(
    out_path: str,
    mode: str = EXECUTION_MODE_ALPACA_PAPER,
) -> Dict[str, Any]:
    """Fetch broker positions from Alpaca and persist snapshot."""
    normalized_mode = _normalize_execution_mode(mode)
    base_url, api_key_id, api_secret_key, timeout = _resolve_alpaca_credentials(normalized_mode)
    if not api_key_id or not api_secret_key:
        raise ValueError(
            "Alpaca credentials missing. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY."
        )

    raw_payload, fetch_error = _get_broker_adapter().get_json(
        endpoint="/v2/positions",
        method="GET",
        base_url_override=base_url,
    )
    if fetch_error:
        raise ValueError(f"Alpaca positions fetch failed: {fetch_error}")

    payload = raw_payload if isinstance(raw_payload, list) else []

    snapshot = {
        "source": "alpaca",
        "mode": normalized_mode,
        "fetched_at": _now_iso(),
        "base_url": base_url,
        "positions": payload,
    }
    target = Path(out_path)
    _save_json(target, snapshot)
    return snapshot


def cancel_alpaca_order(
    broker_order_id: str,
    mode: str = EXECUTION_MODE_ALPACA_PAPER,
) -> Dict[str, Any]:
    """Cancel a broker order on Alpaca."""
    order_id = str(broker_order_id or "").strip()
    if not order_id:
        raise ValueError("broker_order_id is required")

    normalized_mode = _normalize_execution_mode(mode)
    base_url, api_key_id, api_secret_key, timeout = _resolve_alpaca_credentials(normalized_mode)
    if not api_key_id or not api_secret_key:
        raise ValueError(
            "Alpaca credentials missing. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY."
        )

    cancel_data, cancel_error = _get_broker_adapter().get_json(
        endpoint=f"/v2/orders/{order_id}",
        method="DELETE",
        base_url_override=base_url,
    )
    if cancel_error:
        raise ValueError(f"Alpaca order cancel failed: {cancel_error}")
    return {
        "broker_order_id": order_id,
        "mode": normalized_mode,
        "canceled": True,
    }


def close_alpaca_position(
    symbol: str,
    mode: str = EXECUTION_MODE_ALPACA_PAPER,
    qty: Optional[float] = None,
) -> Dict[str, Any]:
    """Close a single position on Alpaca via DELETE /v2/positions/{symbol}.

    Args:
        symbol: Ticker to close.
        mode: Execution mode (alpaca-paper or alpaca-live).
        qty: If provided, close only this many shares (partial close).
            If None, liquidates the entire position.

    Returns:
        Alpaca order response dict with ``closed: True`` on success.
    """
    ticker = str(symbol or "").upper().strip()
    if not ticker:
        raise ValueError("symbol is required")

    normalized_mode = _normalize_execution_mode(mode)
    base_url, api_key_id, api_secret_key, timeout = _resolve_alpaca_credentials(normalized_mode)
    if not api_key_id or not api_secret_key:
        raise ValueError("Alpaca credentials missing.")

    close_params: Dict[str, str] = {}
    if qty is not None:
        close_params["qty"] = _format_qty(float(qty))

    body, close_error = _get_broker_adapter().get_json(
        endpoint=f"/v2/positions/{ticker}",
        method="DELETE",
        params=close_params if close_params else None,
        base_url_override=base_url,
    )
    if close_error:
        raise ValueError(f"Alpaca close position failed for {ticker}: {close_error}")
    logger.info("Closed position %s on %s", ticker, normalized_mode)
    return {
        "symbol": ticker,
        "mode": normalized_mode,
        "closed": True,
        "order": body or {},
    }


def cancel_all_open_orders(
    mode: str = EXECUTION_MODE_ALPACA_PAPER,
) -> Dict[str, Any]:
    """Cancel every open order on Alpaca. Used for panic liquidation."""
    normalized_mode = _normalize_execution_mode(mode)
    base_url, api_key_id, api_secret_key, timeout = _resolve_alpaca_credentials(normalized_mode)
    if not api_key_id or not api_secret_key:
        raise ValueError("Alpaca credentials missing.")

    canceled_data, cancel_all_error = _get_broker_adapter().get_json(
        endpoint="/v2/orders",
        method="DELETE",
        base_url_override=base_url,
    )
    if cancel_all_error:
        raise ValueError(f"Alpaca cancel-all failed: {cancel_all_error}")
    return {
        "mode": normalized_mode,
        "canceled_all": True,
        "canceled_orders": canceled_data if isinstance(canceled_data, list) else [],
    }


def close_all_positions(
    mode: str = EXECUTION_MODE_ALPACA_PAPER,
    cancel_orders_first: bool = True,
) -> Dict[str, Any]:
    """Liquidate every position on Alpaca. Emergency use only.

    Optionally cancels all open orders first (default True) to prevent
    new fills from racing against the liquidation.
    """
    normalized_mode = _normalize_execution_mode(mode)
    base_url, api_key_id, api_secret_key, timeout = _resolve_alpaca_credentials(normalized_mode)
    if not api_key_id or not api_secret_key:
        raise ValueError("Alpaca credentials missing.")

    cancel_result = None
    if cancel_orders_first:
        cancel_result = cancel_all_open_orders(mode=normalized_mode)

    close_all_data, close_all_error = _get_broker_adapter().get_json(
        endpoint="/v2/positions",
        method="DELETE",
        params={"cancel_orders": "true"},
        base_url_override=base_url,
    )
    if close_all_error:
        raise ValueError(f"Alpaca close-all-positions failed: {close_all_error}")

    closed = []
    errors = []
    body = close_all_data or []
    if isinstance(body, list):
        for item in body:
            if not isinstance(item, dict):
                continue
            status_code = item.get("status")
            if status_code == 200:
                closed.append(item.get("body", item))
            else:
                errors.append(item)

    return {
        "mode": normalized_mode,
        "liquidated": True,
        "positions_closed": len(closed),
        "positions_failed": len(errors),
        "closed": closed,
        "errors": errors,
        "cancel_result": cancel_result,
    }


def submit_alpaca_order(
    symbol: str,
    side: str,
    quantity: float,
    mode: str = EXECUTION_MODE_ALPACA_PAPER,
    order_type: str = "market",
    time_in_force: str = "day",
    client_order_id: Optional[str] = None,
    limit_price: Optional[float] = None,
) -> Dict[str, Any]:
    """Submit one direct order to Alpaca and return broker response payload."""
    ticker = str(symbol or "").upper().strip()
    side_text = str(side or "").lower().strip()
    if side_text not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    qty = max(0.0, float(quantity))
    if qty <= 0.0:
        raise ValueError("quantity must be positive")

    normalized_mode = _normalize_execution_mode(mode)
    base_url, api_key_id, api_secret_key, timeout = _resolve_alpaca_credentials(normalized_mode)
    if not api_key_id or not api_secret_key:
        raise ValueError(
            "Alpaca credentials missing. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY."
        )

    payload: Dict[str, Any] = {
        "symbol": ticker,
        "qty": _format_qty(qty),
        "side": side_text,
        "type": str(order_type or "market").lower().strip(),
        "time_in_force": str(time_in_force or "day").lower().strip(),
    }
    if client_order_id:
        payload["client_order_id"] = str(client_order_id)[:48]
    if payload["type"] == "limit":
        px = float(limit_price or 0.0)
        if px <= 0.0:
            raise ValueError("limit_price must be positive for limit orders")
        payload["limit_price"] = str(round(px, 4))

    response = _submit_alpaca_order(
        base_url=base_url,
        api_key_id=api_key_id,
        api_secret_key=api_secret_key,
        payload=payload,
        timeout_seconds=timeout,
    )
    response["mode"] = normalized_mode
    return response


def reconcile_live_execution(
    broker_snapshot: Any,
    outbox_path: str = "eval_results/live_execution/outbox.json",
    positions_path: str = "eval_results/paper_execution/positions.json",
    fills_path: str = "eval_results/live_execution/fills.json",
    closed_trades_path: str = "eval_results/live_execution/closed_trades.json",
    track_record: Optional[TrackRecord] = None,
) -> Dict[str, Any]:
    """Reconcile broker order states into local outbox, positions, fills, and closed outcomes."""
    now_iso = _now_iso()
    outbox_file = Path(outbox_path)
    positions_file = Path(positions_path)
    fills_file = Path(fills_path)
    closed_file = Path(closed_trades_path)

    outbox_history = _load_json(outbox_file, default=[])
    if not isinstance(outbox_history, list):
        outbox_history = []

    fills_history = _load_json(fills_file, default=[])
    if not isinstance(fills_history, list):
        fills_history = []
    closed_history = _load_json(closed_file, default=[])
    if not isinstance(closed_history, list):
        closed_history = []

    positions_state = load_open_positions(positions_path=str(positions_file))
    open_positions = positions_state.get("open_positions", {})
    if not isinstance(open_positions, dict):
        open_positions = {}
    tr = track_record or TrackRecord()

    broker_orders = _extract_broker_orders(broker_snapshot)
    broker_by_intent: Dict[str, Dict[str, Any]] = {}
    broker_by_client: Dict[str, Dict[str, Any]] = {}
    for row in broker_orders:
        if not isinstance(row, dict):
            continue
        intent_id = str(
            row.get("order_intent_id")
            or row.get("idempotency_key")
            or row.get("client_order_id")
            or ""
        ).strip()
        client_id = str(row.get("client_order_id") or "").strip()
        if intent_id and intent_id not in broker_by_intent:
            broker_by_intent[intent_id] = row
        if client_id and client_id not in broker_by_client:
            broker_by_client[client_id] = row

    matched_orders = 0
    unmatched_orders = 0
    status_updates = 0
    fills_applied = 0
    filled_notional_usd = 0.0
    status_updated_intents: List[str] = []
    filled_order_intents: List[str] = []
    positions_touched: List[str] = []
    applied_fills: List[Dict[str, Any]] = []
    closed_events: List[Dict[str, Any]] = []
    closed_symbols: List[str] = []
    outcomes_updated = 0

    for entry in outbox_history:
        if not isinstance(entry, dict):
            continue

        order_intent_id = str(entry.get("order_intent_id") or "").strip()
        client_order_id = str(entry.get("client_order_id") or "").strip()
        broker_row = None
        if order_intent_id:
            broker_row = broker_by_intent.get(order_intent_id)
        if broker_row is None and client_order_id:
            broker_row = broker_by_client.get(client_order_id)

        if broker_row is None:
            unmatched_orders += 1
            continue
        matched_orders += 1

        raw_status = str(
            broker_row.get("status")
            or broker_row.get("order_status")
            or broker_row.get("state")
            or ""
        ).strip()
        normalized_status = _normalize_broker_status(raw_status)
        previous_status = str(entry.get("status") or "SUBMITTED").upper().strip()

        if normalized_status and normalized_status != previous_status:
            entry["status"] = normalized_status
            entry["status_updated_at"] = now_iso
            status_updates += 1
            if order_intent_id:
                status_updated_intents.append(order_intent_id)

        broker_order_id = broker_row.get("broker_order_id") or broker_row.get("order_id") or broker_row.get("id")
        if broker_order_id:
            entry["broker_order_id"] = str(broker_order_id)
        if raw_status:
            entry["broker_status_raw"] = raw_status
        if normalized_status:
            entry["broker_status_normalized"] = normalized_status
        if normalized_status in TERMINAL_BROKER_STATUSES and not entry.get("terminal_at"):
            entry["terminal_at"] = now_iso

        filled_total = _safe_float(
            broker_row.get("filled_quantity")
            or broker_row.get("filled_qty")
            or broker_row.get("executed_quantity")
            or broker_row.get("cumulative_filled_quantity")
            or broker_row.get("cum_qty")
            or 0.0
        )
        target_quantity = max(_safe_float(entry.get("target_quantity")), 0.0)
        if filled_total <= 0.0 and normalized_status == "FILLED" and target_quantity > 0.0:
            filled_total = target_quantity
        if target_quantity > 0.0:
            filled_total = min(max(0.0, filled_total), target_quantity)
        else:
            filled_total = max(0.0, filled_total)

        applied_quantity = max(_safe_float(entry.get("applied_filled_quantity")), 0.0)
        delta_quantity = max(0.0, filled_total - applied_quantity)

        if delta_quantity > 1e-9:
            fill_price = _safe_float(
                broker_row.get("avg_fill_price")
                or broker_row.get("average_fill_price")
                or broker_row.get("fill_price")
                or broker_row.get("price")
                or entry.get("reference_price")
            )
            if fill_price > 0.0:
                side = str(entry.get("side") or "BUY").upper().strip()
                signed_qty = delta_quantity if side == "BUY" else -delta_quantity
                symbol = str(entry.get("symbol") or "").upper().strip()
                previous_position = open_positions.get(symbol, {})
                if not isinstance(previous_position, dict):
                    previous_position = {}
                old_qty = _safe_float(previous_position.get("net_quantity"))
                old_avg = _safe_float(previous_position.get("avg_price"))
                rating_ids = _as_string_list(previous_position.get("rating_ids"))
                rating_id = entry.get("rating_id")
                if rating_id:
                    rid = str(rating_id)
                    if rid not in rating_ids:
                        rating_ids.append(rid)
                projected_qty = old_qty + signed_qty
                synthetic_fill = {
                    "symbol": symbol,
                    "signed_quantity": float(round(signed_qty, 6)),
                    "filled_price": float(round(fill_price, 6)),
                    "rating_id": entry.get("rating_id"),
                    "lane": entry.get("lane"),
                    "research_playbook": entry.get("research_playbook"),
                    "intent_category": entry.get("intent_category"),
                    "exit_rule": entry.get("exit_rule"),
                    "exit_reason": entry.get("exit_reason"),
                }
                _apply_fill_to_position(open_positions=open_positions, order=synthetic_fill)

                fill_event = {
                    "fill_id": str(uuid.uuid4()),
                    "applied_at": now_iso,
                    "order_intent_id": order_intent_id,
                    "client_order_id": client_order_id,
                    "broker_order_id": entry.get("broker_order_id"),
                    "symbol": symbol,
                    "side": side,
                    "filled_quantity": float(round(delta_quantity, 6)),
                    "filled_price": float(round(fill_price, 6)),
                    "filled_notional_usd": float(round(abs(delta_quantity * fill_price), 2)),
                    "lane": entry.get("lane"),
                    "research_playbook": entry.get("research_playbook"),
                    "rating_id": entry.get("rating_id"),
                    "intent_category": entry.get("intent_category"),
                    "exit_rule": entry.get("exit_rule"),
                    "exit_reason": entry.get("exit_reason"),
                    "status": normalized_status or previous_status,
                }
                fills_history.append(fill_event)
                applied_fills.append(fill_event)
                fills_applied += 1
                filled_notional_usd += abs(delta_quantity * fill_price)
                if symbol and symbol not in positions_touched:
                    positions_touched.append(symbol)

                entry["applied_filled_quantity"] = float(round(applied_quantity + delta_quantity, 6))
                entry["last_fill_applied_at"] = now_iso
                if order_intent_id:
                    filled_order_intents.append(order_intent_id)

                crossed_zero = (old_qty > 0 > projected_qty) or (old_qty < 0 < projected_qty)
                fully_closed = abs(projected_qty) <= 1e-9
                should_close = old_qty != 0.0 and (fully_closed or crossed_zero)
                if should_close and old_avg > 0.0 and symbol:
                    side_scalar = 1.0 if old_qty > 0 else -1.0
                    ret_pct = (((fill_price - old_avg) / old_avg) * side_scalar) * 100.0
                    pnl = (fill_price - old_avg) * old_qty
                    close_date = now_iso[:10]

                    updated_rating_ids: List[str] = []
                    for rid in rating_ids:
                        if tr.update_outcome(
                            rating_id=rid,
                            close_price=float(round(fill_price, 6)),
                            date=close_date,
                        ):
                            updated_rating_ids.append(rid)
                    outcomes_updated += len(updated_rating_ids)

                    close_event = {
                        "close_id": str(uuid.uuid4()),
                        "closed_at": now_iso,
                        "close_source": "LIVE_RECONCILIATION",
                        "symbol": symbol,
                        "close_date": close_date,
                        "close_price": float(round(fill_price, 6)),
                        "net_quantity": float(round(old_qty, 6)),
                        "avg_entry_price": float(round(old_avg, 6)),
                        "pnl_usd": float(round(pnl, 2)),
                        "return_pct": float(round(ret_pct, 4)),
                        "rating_ids": rating_ids,
                        "updated_rating_ids": updated_rating_ids,
                        "order_intent_id": order_intent_id,
                        "client_order_id": client_order_id,
                        "broker_order_id": entry.get("broker_order_id"),
                        "lane": entry.get("lane"),
                        "research_playbook": entry.get("research_playbook"),
                        "intent_category": entry.get("intent_category"),
                        "exit_rule": entry.get("exit_rule"),
                        "exit_reason": entry.get("exit_reason"),
                    }
                    closed_history.append(close_event)
                    closed_events.append(close_event)
                    if symbol not in closed_symbols:
                        closed_symbols.append(symbol)
            else:
                entry["fill_apply_error"] = "MISSING_FILL_PRICE"

    positions_state["open_positions"] = open_positions
    positions_state["updated_at"] = now_iso
    _save_json(outbox_file, outbox_history)
    _save_json(fills_file, fills_history)
    _save_json(closed_file, closed_history)
    _save_json(positions_file, positions_state)

    logger.info(
        "Reconciliation complete: matched=%d unmatched=%d fills_applied=%d "
        "filled_notional_usd=%.2f closed_positions=%d",
        matched_orders,
        unmatched_orders,
        fills_applied,
        filled_notional_usd,
        len(closed_events),
    )

    return {
        "reconciled_at": now_iso,
        "execution_mode": EXECUTION_MODE_LIVE,
        "outbox_path": str(outbox_file),
        "positions_path": str(positions_file),
        "fills_path": str(fills_file),
        "outbox_orders": int(len(outbox_history)),
        "broker_orders_seen": int(len(broker_orders)),
        "matched_orders": int(matched_orders),
        "unmatched_orders": int(unmatched_orders),
        "status_updates": int(status_updates),
        "fills_applied": int(fills_applied),
        "filled_notional_usd": float(round(filled_notional_usd, 2)),
        "closed_positions": int(len(closed_events)),
        "outcomes_updated": int(outcomes_updated),
        "closed_symbols": closed_symbols,
        "closed_trades_path": str(closed_file),
        "status_counts": _count_outbox_statuses(outbox_history),
        "positions_touched": positions_touched,
        "status_updated_order_intent_ids": _dedupe_list(status_updated_intents),
        "filled_order_intent_ids": _dedupe_list(filled_order_intents),
        "fills": applied_fills,
        "closed_trades": closed_events,
    }


def load_open_positions(
    positions_path: str = "eval_results/paper_execution/positions.json",
) -> Dict[str, Any]:
    positions = _load_json(Path(positions_path), default={})
    if not isinstance(positions, dict):
        return {"updated_at": "", "open_positions": {}}
    if "open_positions" not in positions:
        positions["open_positions"] = {}
    return positions


def refresh_positions_market_snapshot(
    positions_path: str = "eval_results/paper_execution/positions.json",
) -> Dict[str, Any]:
    """Refresh open-position market values and unrealized PnL from latest market prices."""
    positions_file = Path(positions_path)
    positions_state = _load_json(positions_file, default={})
    open_positions = positions_state.get("open_positions", {})
    if not isinstance(open_positions, dict):
        open_positions = {}

    now_iso = _now_iso()
    refreshed_symbols: List[str] = []
    unavailable_symbols: List[str] = []
    errors: List[Dict[str, str]] = []

    for symbol, row in open_positions.items():
        if not isinstance(row, dict):
            continue
        ticker = str(symbol or "").upper().strip()
        if not ticker:
            continue

        net_qty = float(row.get("net_quantity", 0.0) or 0.0)
        avg_price = float(row.get("avg_price", 0.0) or 0.0)
        if net_qty == 0.0 or avg_price <= 0.0:
            continue

        latest_price = _fetch_reference_price_from_market(symbol=ticker, analysis_date="")
        if latest_price is None or latest_price <= 0.0:
            unavailable_symbols.append(ticker)
            continue

        market_value = abs(net_qty) * latest_price
        side_scalar = 1.0 if net_qty > 0 else -1.0
        unrealized_pnl = (latest_price - avg_price) * net_qty
        unrealized_return_pct = (
            ((latest_price - avg_price) / avg_price) * side_scalar * 100.0
            if avg_price > 0
            else 0.0
        )

        row["last_mark_price"] = float(round(latest_price, 6))
        if net_qty > 0:
            prev_high = float(row.get("high_watermark_price", latest_price) or latest_price)
            row["high_watermark_price"] = float(round(max(prev_high, latest_price), 6))
        elif net_qty < 0:
            prev_low = float(row.get("low_watermark_price", latest_price) or latest_price)
            row["low_watermark_price"] = float(round(min(prev_low, latest_price), 6))
        row["market_value_usd"] = float(round(market_value, 2))
        row["unrealized_pnl_usd"] = float(round(unrealized_pnl, 2))
        row["unrealized_return_pct"] = float(round(unrealized_return_pct, 4))
        row["mark_to_market_at"] = now_iso
        refreshed_symbols.append(ticker)

    positions_state["open_positions"] = open_positions
    positions_state["updated_at"] = now_iso
    _save_json(positions_file, positions_state)

    return {
        "refreshed_at": now_iso,
        "positions_path": str(positions_file),
        "open_positions": int(len([s for s, r in open_positions.items() if isinstance(r, dict)])),
        "refreshed_count": int(len(refreshed_symbols)),
        "unavailable_count": int(len(unavailable_symbols)),
        "refreshed_symbols": refreshed_symbols,
        "unavailable_symbols": unavailable_symbols,
        "errors": errors,
    }


def evaluate_position_reanalysis(
    execution_mode: str = "paper",
    positions_path: str = "",
    results_dir: str = "results",
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Evaluate open positions for score-based exit signals.

    For each position held > min_hold_days:
    1. Check if a fresh analysis exists for today in results/{ticker}/{today}/analysis_report.json
    2. If no fresh analysis: flag as "needs re-analysis"
    3. If fresh analysis exists: compare current score vs entry score
    4. Exit signals:
       - Score below reanalysis_exit_score_threshold → SCORE_DETERIORATION
       - Score dropped by reanalysis_exit_score_drop_pct from entry → THESIS_WEAKENED
       - Decision flipped from BUY to SELL → THESIS_REVERSED

    Returns:
        Dict with keys: positions_evaluated, needs_reanalysis (list), exit_recommendations (list), hold (list)
    """
    cfg = config if config is not None else DEFAULT_CONFIG
    normalized_mode = _normalize_execution_mode(execution_mode)

    if not positions_path:
        if normalized_mode in (EXECUTION_MODE_PAPER, EXECUTION_MODE_ALPACA_PAPER):
            positions_path = str(cfg.get("paper_positions_path", "eval_results/paper_execution/positions.json"))
        else:
            positions_path = str(cfg.get("live_positions_shadow_path", "eval_results/live_execution/positions_shadow.json"))

    min_hold_days = int(cfg.get("reanalysis_min_hold_days", 5))
    exit_score_threshold = float(cfg.get("reanalysis_exit_score_threshold", 40.0))
    exit_score_drop_pct = float(cfg.get("reanalysis_exit_score_drop_pct", 0.30))

    positions = load_open_positions(positions_path=positions_path)
    open_positions = positions.get("open_positions", {})
    if not isinstance(open_positions, dict):
        open_positions = {}

    today_str = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")

    needs_reanalysis: List[Dict[str, Any]] = []
    exit_recommendations: List[Dict[str, Any]] = []
    hold: List[Dict[str, Any]] = []

    sorted_rows = sorted(
        [(str(k).upper().strip(), v) for k, v in open_positions.items() if isinstance(v, dict)],
        key=lambda item: item[0],
    )
    for ticker, row in sorted_rows:
        net_qty = float(row.get("net_quantity", 0.0) or 0.0)
        avg_price = float(row.get("avg_price", 0.0) or 0.0)
        if net_qty == 0.0 or avg_price <= 0.0:
            continue

        opened_at = _parse_iso(row.get("opened_at")) or _parse_iso(row.get("updated_at"))
        now_dt = dt.datetime.now(dt.timezone.utc)
        hold_days = (now_dt.date() - opened_at.date()).days if opened_at else 0
        entry_date = opened_at.date().isoformat() if opened_at else ""

        if hold_days < min_hold_days:
            continue

        report_path = Path(results_dir) / ticker / today_str / "analysis_report.json"
        if not report_path.exists():
            needs_reanalysis.append({
                "ticker": ticker,
                "entry_date": entry_date,
                "hold_days": int(hold_days),
                "recommendation": "NEEDS_REANALYSIS",
            })
            continue

        try:
            rpt = json.loads(report_path.read_text())
        except Exception:
            hold.append({"ticker": ticker, "entry_date": entry_date, "current_score": None, "recommendation": "HOLD"})
            continue

        current_score = float(rpt.get("aeternus_score", {}).get("aeternus_score", 0) or 0)
        entry_score = float(row.get("entry_aeternus_score", 0) or 0)

        exit_reason = ""
        exit_rule = ""

        if current_score > 0 and current_score < exit_score_threshold:
            exit_reason = f"Score deterioration ({current_score:.1f} < {exit_score_threshold:.1f} threshold)"
            exit_rule = "SCORE_DETERIORATION"
        elif entry_score > 0 and current_score > 0:
            drop = (entry_score - current_score) / entry_score
            if drop >= exit_score_drop_pct:
                exit_reason = f"Thesis weakened (score {entry_score:.1f} → {current_score:.1f}, -{drop*100:.0f}%)"
                exit_rule = "THESIS_WEAKENED"

        if not exit_rule:
            ftd = str(rpt.get("final_trade_decision", "")).strip().upper()
            if ftd.startswith("SELL") and net_qty > 0:
                exit_reason = "Thesis reversed (analysis now says SELL, position is long)"
                exit_rule = "THESIS_REVERSED"

        if exit_rule:
            score_change_pct = (
                round((current_score - entry_score) / entry_score * 100, 1)
                if entry_score > 0
                else None
            )
            exit_recommendations.append({
                "ticker": ticker,
                "entry_date": entry_date,
                "entry_score": entry_score if entry_score > 0 else None,
                "current_score": current_score if current_score > 0 else None,
                "score_change_pct": score_change_pct,
                "recommendation": "EXIT",
                "exit_reason": exit_reason,
                "exit_rule": exit_rule,
            })
        else:
            hold.append({
                "ticker": ticker,
                "entry_date": entry_date,
                "current_score": current_score if current_score > 0 else None,
                "recommendation": "HOLD",
            })

    return {
        "positions_evaluated": len(needs_reanalysis) + len(exit_recommendations) + len(hold),
        "needs_reanalysis": needs_reanalysis,
        "exit_recommendations": exit_recommendations,
        "hold": hold,
    }


def build_exit_execution_plan(
    execution_mode: str,
    positions_path: str = "eval_results/paper_execution/positions.json",
    outbox_path: str = "eval_results/live_execution/outbox.json",
    min_position_notional_usd: float = 250.0,
    max_exit_orders_per_run: int = 6,
    enforce_whole_shares: bool = True,
    as_of: Optional[str] = None,
    # Deprecated — kept for call-site compatibility, ignored
    stop_loss_pct: float = 0.0,
    take_profit_pct: float = 0.0,
    max_hold_days: int = 0,
    trailing_stop_pct: float = 0.0,
) -> Dict[str, Any]:
    """Build deterministic exit intents from open positions and adaptive review."""
    normalized_mode = _normalize_execution_mode(execution_mode)
    now_dt = _parse_iso_or_now(as_of)
    now_iso = now_dt.isoformat()

    min_position_notional_usd = max(0.0, float(min_position_notional_usd))
    max_exit_orders_per_run = max(1, int(max_exit_orders_per_run))

    positions = load_open_positions(positions_path=positions_path)
    open_positions = positions.get("open_positions", {})
    if not isinstance(open_positions, dict):
        open_positions = {}

    outbox_history = _load_json(Path(outbox_path), default=[])
    if not isinstance(outbox_history, list):
        outbox_history = []

    active_exit_keys = set()
    for row in outbox_history:
        if not isinstance(row, dict):
            continue
        status = _normalize_broker_status(str(row.get("status") or ""))
        if status in TERMINAL_BROKER_STATUSES:
            continue
        category = str(row.get("intent_category") or "").upper().strip()
        if category != "EXIT":
            continue
        symbol = str(row.get("symbol") or "").upper().strip()
        side = str(row.get("side") or "").upper().strip()
        if symbol and side:
            active_exit_keys.add((symbol, side))

    signals: List[Dict[str, Any]] = []
    generated_orders: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    sorted_rows = sorted(
        [(str(k).upper().strip(), v) for k, v in open_positions.items() if isinstance(v, dict)],
        key=lambda item: item[0],
    )
    for symbol, row in sorted_rows:
        if len(generated_orders) >= max_exit_orders_per_run:
            skipped.append({"symbol": symbol, "reason": "MAX_EXIT_ORDERS_PER_RUN"})
            continue

        net_qty = float(row.get("net_quantity", 0.0) or 0.0)
        avg_price = float(row.get("avg_price", 0.0) or 0.0)
        if net_qty == 0.0 or avg_price <= 0.0:
            skipped.append({"symbol": symbol, "reason": "POSITION_NOT_OPEN"})
            continue

        side_to_close = "SELL" if net_qty > 0 else "BUY"
        if (symbol, side_to_close) in active_exit_keys:
            skipped.append({"symbol": symbol, "reason": "ACTIVE_EXIT_ORDER"})
            continue

        mark_price = float(row.get("last_mark_price", 0.0) or 0.0)
        if mark_price <= 0.0:
            fetched = _fetch_reference_price_from_market(symbol=symbol, analysis_date="")
            if fetched is None or fetched <= 0.0:
                skipped.append({"symbol": symbol, "reason": "MISSING_MARK_PRICE"})
                continue
            mark_price = float(fetched)

        notional = abs(net_qty) * mark_price
        if notional < min_position_notional_usd:
            skipped.append({"symbol": symbol, "reason": "POSITION_NOTIONAL_BELOW_MIN"})
            continue

        side_scalar = 1.0 if net_qty > 0 else -1.0
        pnl_pct = (((mark_price - avg_price) / avg_price) * side_scalar) * 100.0
        opened_at = _parse_iso(row.get("opened_at")) or _parse_iso(row.get("updated_at"))
        hold_days = (now_dt.date() - opened_at.date()).days if opened_at else 0

        exit_reason = ""
        exit_rule = ""
        # CC Wyckoff Phase: auto-close after 1 trading day
        _playbook = str(row.get("research_playbook") or "").upper().strip()
        if _playbook == "CC_WYCKOFF_PHASE" and hold_days >= 1:
            exit_reason = f"CC Wyckoff Phase EOD close ({hold_days}d)"
            exit_rule = "CC_WYCKOFF_EOD"
        elif _playbook == "REGIME_EXIT_OVERLAY":
            try:
                from tradingagents.phase_engine.cc_overbought import CCOverboughtEngine
                _re_engine = CCOverboughtEngine()
                _sig = _re_engine.get_signal(str(row.get("symbol") or ""))
                if _sig.get("state") == "cash":
                    exit_reason = f"Regime-exit signal: cash (regime={_sig.get('regime','?')}, accel_pct={_sig.get('accel_percentile', 0):.2f})"
                    exit_rule = "REGIME_EXIT_SIGNAL"
            except Exception:
                pass  # graceful degradation — keep position if signal unavailable
        elif _playbook == "PHASE_ENGINE_V3":
            try:
                from tradingagents.phase_engine.index_overlay import IndexOverlayEngine
                _io_engine = IndexOverlayEngine()
                _sig = _io_engine.get_signal_for_instrument(str(row.get("symbol") or ""))
                if _sig and not _sig.get("rth") and not _sig.get("overnight"):
                    exit_reason = f"Index overlay: no active v3 signal (leg={_sig.get('active_leg')}, vix={_sig.get('vix', 0):.1f})"
                    exit_rule = "INDEX_OVERLAY_NO_SIGNAL"
            except Exception:
                pass  # graceful degradation
        # Adaptive position review (thesis stress, score decay, opportunity cost)
        if not exit_rule:
            try:
                from tradingagents.graph.position_review import review_positions
                _single_pos = {symbol: row}
                _reviews = review_positions(positions=_single_pos)
                if _reviews and _reviews[0].get("recommendation") == "EXIT":
                    exit_reason = _reviews[0].get("reason", "Position review: EXIT")
                    exit_rule = "POSITION_REVIEW"
            except Exception:
                pass  # graceful degradation
        if not exit_rule:
            skipped.append({"symbol": symbol, "reason": "NO_EXIT_SIGNAL"})
            continue

        raw_qty = abs(net_qty)
        qty = _coerce_order_quantity(raw_qty=raw_qty, whole_shares=bool(enforce_whole_shares))
        if qty <= 0.0:
            skipped.append({"symbol": symbol, "reason": "WHOLE_SHARE_ROUND_DOWN_TO_ZERO"})
            continue

        exit_signal_id = str(uuid.uuid4())
        signal = {
            "exit_signal_id": exit_signal_id,
            "symbol": symbol,
            "rule": exit_rule,
            "reason": exit_reason,
            "side": side_to_close,
            "hold_days": int(hold_days),
            "unrealized_return_pct": float(round(pnl_pct, 4)),
            "mark_price": float(round(mark_price, 6)),
            "avg_price": float(round(avg_price, 6)),
            "position_notional_usd": float(round(notional, 2)),
        }
        signals.append(signal)

        order_intent_id = str(uuid.uuid4())
        client_order_id = _build_client_order_id(
            plan_id=exit_signal_id,
            symbol=symbol,
            ordinal=len(generated_orders) + 1,
        )
        order = {
            "order_intent_id": order_intent_id,
            "client_order_id": client_order_id,
            "idempotency_key": order_intent_id,
            "symbol": symbol,
            "side": side_to_close,
            "order_type": "MARKET",
            "time_in_force": "DAY",
            "execution_mode": normalized_mode,
            "target_weight": 0.0,
            "target_notional_usd": float(round(abs(qty) * mark_price, 2)),
            "reference_price": float(round(mark_price, 6)),
            "reference_price_source": "market_snapshot",
            "target_quantity": float(round(abs(qty), 6)),
            "quantity_policy": "WHOLE_SHARES" if enforce_whole_shares else "FRACTIONAL_OK",
            "aeternus_score": 0.0,
            "confidence": 0,
            "lane": row.get("lane"),
            "research_playbook": row.get("research_playbook"),
            "dominant_signal_family": "exit_rule",
            "queue_id": "",
            "rating_id": (_as_string_list(row.get("rating_ids")) or [""])[0],
            "intent_category": "EXIT",
            "exit_signal_id": exit_signal_id,
            "exit_rule": exit_rule,
            "exit_reason": exit_reason,
            "generated_at": now_iso,
        }
        generated_orders.append(order)

    plan_id = str(uuid.uuid4())
    return {
        "plan_id": plan_id,
        "date": now_dt.date().isoformat(),
        "created_at": now_iso,
        "execution_mode": normalized_mode,
        "positions_path": str(positions_path),
        "outbox_path": str(outbox_path),
        "signals": signals,
        "orders": generated_orders,
        "skipped": skipped,
        "rules": {
            "stop_loss_pct": float(stop_loss_pct),
            "take_profit_pct": float(take_profit_pct),
            "max_hold_days": int(max_hold_days),
            "trailing_stop_pct": float(trailing_stop_pct),
            "min_position_notional_usd": float(min_position_notional_usd),
            "max_exit_orders_per_run": int(max_exit_orders_per_run),
            "enforce_whole_shares": bool(enforce_whole_shares),
        },
    }


def evaluate_execution_readiness(
    broker: str,
    mode: str,
    outbox_path: str = "eval_results/live_execution/outbox.json",
    positions_path: str = "eval_results/paper_execution/positions.json",
    snapshot_path: Optional[str] = None,
    max_stale_submitted_minutes: int = 180,
    max_unmatched_open_orders: int = 10,
    max_position_drift_notional_usd: float = 2500.0,
    min_buying_power_usd: float = 1.0,
    max_gross_exposure_pct: float = 1.0,
) -> Dict[str, Any]:
    """Evaluate live execution safety checks for broker-connected operation."""
    now_dt = dt.datetime.now(dt.timezone.utc)
    now_iso = now_dt.isoformat()
    source = str(broker or "").strip().lower()
    normalized_mode = _normalize_execution_mode(mode)
    blockers: List[str] = []
    warnings: List[str] = []
    checks: Dict[str, Any] = {}

    if source != "alpaca":
        blockers.append(f"Unsupported broker: {broker}")
        return {
            "evaluated_at": now_iso,
            "broker": source,
            "mode": normalized_mode,
            "overall_ready": False,
            "checks": checks,
            "blockers": blockers,
            "warnings": warnings,
        }

    base_url, api_key_id, api_secret_key, timeout = _resolve_alpaca_credentials(normalized_mode)
    credentials_ok = bool(api_key_id and api_secret_key)
    checks["credentials"] = {
        "pass": credentials_ok,
        "has_key_id": bool(api_key_id),
        "has_secret": bool(api_secret_key),
    }
    if not credentials_ok:
        blockers.append("Missing Alpaca credentials (APCA_API_KEY_ID/APCA_API_SECRET_KEY).")
        return {
            "evaluated_at": now_iso,
            "broker": source,
            "mode": normalized_mode,
            "overall_ready": False,
            "checks": checks,
            "blockers": blockers,
            "warnings": warnings,
        }

    headers = _alpaca_headers(api_key_id=api_key_id, api_secret_key=api_secret_key)
    account_payload, account_error = _alpaca_get_json(
        base_url=base_url,
        endpoint="/v2/account",
        headers=headers,
        timeout_seconds=timeout,
    )
    if account_error:
        blockers.append(f"Account API check failed: {account_error}")
        checks["account"] = {"pass": False, "error": account_error}
    else:
        status = str(account_payload.get("status") or "").upper().strip()
        buying_power = _safe_float(account_payload.get("buying_power"))
        account_ok = status == "ACTIVE" and buying_power >= float(min_buying_power_usd)
        checks["account"] = {
            "pass": account_ok,
            "status": status,
            "buying_power_usd": float(round(buying_power, 2)),
            "min_buying_power_usd": float(min_buying_power_usd),
        }
        if status != "ACTIVE":
            blockers.append(f"Alpaca account not ACTIVE (status={status or 'UNKNOWN'}).")
        if buying_power < float(min_buying_power_usd):
            blockers.append(
                f"Buying power too low ({buying_power:.2f} < {float(min_buying_power_usd):.2f})."
            )

    clock_payload, clock_error = _alpaca_get_json(
        base_url=base_url,
        endpoint="/v2/clock",
        headers=headers,
        timeout_seconds=timeout,
    )
    if clock_error:
        warnings.append(f"Clock API unavailable: {clock_error}")
        checks["market_clock"] = {"pass": True, "is_open": None, "error": clock_error}
    else:
        is_open = bool(clock_payload.get("is_open"))
        checks["market_clock"] = {
            "pass": True,
            "is_open": is_open,
            "next_open": clock_payload.get("next_open"),
            "next_close": clock_payload.get("next_close"),
        }

    outbox_history = _load_json(Path(outbox_path), default=[])
    if not isinstance(outbox_history, list):
        outbox_history = []
    pending_rows = []
    stale_pending_rows = []
    max_stale_minutes = max(1, int(max_stale_submitted_minutes))
    for row in outbox_history:
        if not isinstance(row, dict):
            continue
        status = _normalize_broker_status(str(row.get("status") or "SUBMITTED"))
        if status in TERMINAL_BROKER_STATUSES:
            continue
        pending_rows.append(row)
        submitted_at = _parse_iso(row.get("submitted_at")) or _parse_iso(row.get("created_at"))
        if submitted_at is None:
            continue
        age_minutes = (now_dt - submitted_at).total_seconds() / 60.0
        if age_minutes >= max_stale_minutes:
            stale_pending_rows.append(row)
    stale_ok = len(stale_pending_rows) == 0
    checks["stale_pending_orders"] = {
        "pass": stale_ok,
        "pending_count": int(len(pending_rows)),
        "stale_count": int(len(stale_pending_rows)),
        "max_stale_submitted_minutes": int(max_stale_minutes),
    }
    if not stale_ok:
        blockers.append(
            f"Stale pending orders detected ({len(stale_pending_rows)} >= 1)."
        )

    broker_orders: List[Dict[str, Any]] = []
    snapshot_source = "none"
    if snapshot_path:
        snapshot_payload = _load_json(Path(snapshot_path), default={})
        broker_orders = _extract_broker_orders(snapshot_payload)
        snapshot_source = "file"
    if not broker_orders:
        orders_payload, orders_error = _alpaca_get_json(
            base_url=base_url,
            endpoint="/v2/orders",
            headers=headers,
            timeout_seconds=timeout,
            params={"status": "open", "limit": 500, "direction": "desc", "nested": "true"},
        )
        if orders_error:
            warnings.append(f"Open-orders API unavailable: {orders_error}")
        elif isinstance(orders_payload, list):
            broker_orders = [row for row in orders_payload if isinstance(row, dict)]
            snapshot_source = "api"

    broker_keys = set()
    for row in broker_orders:
        client_id = str(row.get("client_order_id") or "").strip()
        order_id = str(row.get("id") or row.get("order_id") or "").strip()
        if client_id:
            broker_keys.add(("client", client_id))
        if order_id:
            broker_keys.add(("broker", order_id))

    unmatched_count = 0
    for row in pending_rows:
        client_id = str(row.get("client_order_id") or "").strip()
        broker_id = str(row.get("broker_order_id") or "").strip()
        matched = (client_id and ("client", client_id) in broker_keys) or (
            broker_id and ("broker", broker_id) in broker_keys
        )
        if not matched:
            unmatched_count += 1

    unmatched_ok = unmatched_count <= int(max_unmatched_open_orders)
    checks["open_order_match"] = {
        "pass": unmatched_ok,
        "pending_count": int(len(pending_rows)),
        "broker_open_orders": int(len(broker_orders)),
        "unmatched_pending_count": int(unmatched_count),
        "max_unmatched_open_orders": int(max_unmatched_open_orders),
        "source": snapshot_source,
    }
    if not unmatched_ok:
        blockers.append(
            f"Unmatched pending orders exceed threshold ({unmatched_count} > {int(max_unmatched_open_orders)})."
        )

    broker_positions_payload, broker_positions_error = _alpaca_get_json(
        base_url=base_url,
        endpoint="/v2/positions",
        headers=headers,
        timeout_seconds=timeout,
    )
    drift_notional = 0.0
    shadow_positions = load_open_positions(positions_path=positions_path).get("open_positions", {})
    if not isinstance(shadow_positions, dict):
        shadow_positions = {}
    if broker_positions_error:
        warnings.append(f"Broker positions API unavailable: {broker_positions_error}")
        checks["position_drift"] = {
            "pass": True,
            "error": broker_positions_error,
            "drift_notional_usd": 0.0,
        }
    else:
        broker_map: Dict[str, float] = {}
        if isinstance(broker_positions_payload, list):
            for row in broker_positions_payload:
                if not isinstance(row, dict):
                    continue
                symbol = str(row.get("symbol") or "").upper().strip()
                qty = _safe_float(row.get("qty"))
                if symbol:
                    broker_map[symbol] = qty

        symbols = set(str(symbol).upper().strip() for symbol in shadow_positions) | set(broker_map)
        for symbol in symbols:
            shadow_row = shadow_positions.get(symbol)
            shadow_qty = _safe_float(shadow_row.get("net_quantity") if isinstance(shadow_row, dict) else 0.0)
            broker_qty = _safe_float(broker_map.get(symbol))
            qty_delta = abs(shadow_qty - broker_qty)
            mark_price = 0.0
            if isinstance(shadow_row, dict):
                mark_price = _safe_float(shadow_row.get("last_mark_price") or shadow_row.get("avg_price"))
            if mark_price <= 0.0:
                fetched = _fetch_reference_price_from_market(symbol=symbol, analysis_date="")
                mark_price = _safe_float(fetched)
            drift_notional += qty_delta * max(0.0, mark_price)

        drift_ok = drift_notional <= float(max_position_drift_notional_usd)
        checks["position_drift"] = {
            "pass": drift_ok,
            "drift_notional_usd": float(round(drift_notional, 2)),
            "max_position_drift_notional_usd": float(max_position_drift_notional_usd),
            "symbols_compared": int(len(symbols)),
        }
        if not drift_ok:
            blockers.append(
                "Position drift exceeds threshold "
                f"({drift_notional:.2f} > {float(max_position_drift_notional_usd):.2f})."
            )

    equity = _safe_float((account_payload or {}).get("equity"))
    if equity > 0.0:
        gross_exposure = sum(
            abs(_safe_float(row.get("market_value_usd")))
            for row in shadow_positions.values()
            if isinstance(row, dict)
        )
        gross_exposure_pct = gross_exposure / equity
        gross_leverage_ok = gross_exposure_pct <= float(max_gross_exposure_pct)
        checks["gross_leverage"] = {
            "pass": gross_leverage_ok,
            "gross_exposure_usd": float(round(gross_exposure, 2)),
            "equity_usd": float(round(equity, 2)),
            "gross_exposure_pct": float(round(gross_exposure_pct, 4)),
            "max_gross_exposure_pct": float(max_gross_exposure_pct),
        }
        if not gross_leverage_ok:
            blockers.append(
                f"Gross leverage exceeds limit "
                f"({gross_exposure_pct:.4f} > {float(max_gross_exposure_pct):.4f})."
            )

    overall_ready = len(blockers) == 0
    return {
        "evaluated_at": now_iso,
        "broker": source,
        "mode": normalized_mode,
        "overall_ready": bool(overall_ready),
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
    }


def close_paper_position(
    symbol: str,
    close_price: float,
    close_date: str,
    positions_path: str = "eval_results/paper_execution/positions.json",
    closed_trades_path: str = "eval_results/paper_execution/closed_trades.json",
    track_record: Optional[TrackRecord] = None,
    exit_rule: str = "",
    exit_reason: str = "",
) -> Dict[str, Any]:
    """Close an open paper position and propagate outcome to linked ratings."""
    ticker = str(symbol or "").upper().strip()
    if not ticker:
        raise ValueError("symbol is required")
    if float(close_price) <= 0:
        raise ValueError("close_price must be positive")

    positions_file = Path(positions_path)
    closed_file = Path(closed_trades_path)
    positions_state = _load_json(positions_file, default={})
    open_positions = dict(positions_state.get("open_positions", {}))
    existing = open_positions.get(ticker)
    if not isinstance(existing, dict):
        raise ValueError(f"no open position for {ticker}")

    net_qty = float(existing.get("net_quantity", 0.0) or 0.0)
    avg_price = float(existing.get("avg_price", 0.0) or 0.0)
    if net_qty == 0 or avg_price <= 0:
        raise ValueError(f"position for {ticker} is not open")

    pnl = (float(close_price) - avg_price) * net_qty
    ret_pct = 0.0
    if avg_price > 0:
        side_scalar = 1.0 if net_qty > 0 else -1.0
        ret_pct = (((float(close_price) - avg_price) / avg_price) * side_scalar) * 100.0

    rating_ids = _as_string_list(existing.get("rating_ids"))
    tr = track_record or TrackRecord()
    updated_rating_ids: List[str] = []
    for rating_id in rating_ids:
        if tr.update_outcome(rating_id=rating_id, close_price=float(close_price), date=close_date):
            updated_rating_ids.append(rating_id)

    closed_history = _load_json(closed_file, default=[])
    close_event = {
        "close_id": str(uuid.uuid4()),
        "closed_at": _now_iso(),
        "symbol": ticker,
        "close_date": close_date,
        "close_price": float(round(close_price, 6)),
        "net_quantity": float(round(net_qty, 6)),
        "avg_entry_price": float(round(avg_price, 6)),
        "pnl_usd": float(round(pnl, 2)),
        "return_pct": float(round(ret_pct, 4)),
        "rating_ids": rating_ids,
        "updated_rating_ids": updated_rating_ids,
        "exit_rule": exit_rule or "MANUAL",
        "exit_reason": exit_reason or "",
        "entry_aeternus_score": float(existing.get("entry_aeternus_score", 0) or 0),
        "entry_pillar_breakdown": dict(existing.get("entry_pillar_breakdown", {})),
        "entry_weight_regime": str(existing.get("entry_weight_regime", "")),
    }
    closed_history.append(close_event)

    open_positions.pop(ticker, None)
    positions_state["open_positions"] = open_positions
    positions_state["updated_at"] = _now_iso()
    _save_json(positions_file, positions_state)
    _save_json(closed_file, closed_history)

    logger.info(
        "Paper position closed: %s close_price=%.4f pnl_usd=%.2f return_pct=%.4f%%",
        ticker,
        float(close_price),
        float(round(pnl, 2)),
        float(round(ret_pct, 4)),
    )

    return close_event


def execute_plan_with_adapter(
    plan: Dict[str, Any],
    execution_mode: Literal["paper", "live", "alpaca-paper", "alpaca-live"] = EXECUTION_MODE_PAPER,
    orders_path: str = "eval_results/paper_execution/orders.json",
    positions_path: str = "eval_results/paper_execution/positions.json",
    fill_price_slippage_bps: float = 0.0,
) -> Dict[str, Any]:
    """Execute a plan via adapter abstraction (paper now, live later)."""
    adapter = get_execution_adapter(execution_mode)
    return adapter.execute_plan(
        plan=plan,
        orders_path=orders_path,
        positions_path=positions_path,
        fill_price_slippage_bps=fill_price_slippage_bps,
    )


def build_rebalance_execution_plan(
    plan: Dict[str, Any],
    positions_path: str = "eval_results/paper_execution/positions.json",
    min_rebalance_notional_usd: float = 100.0,
    close_missing_positions: bool = False,
) -> Dict[str, Any]:
    """Convert target-size intents into delta-size intents against current positions."""
    threshold = max(0.0, float(min_rebalance_notional_usd))
    base_orders = list(plan.get("orders", []))
    positions_state = load_open_positions(positions_path=positions_path)
    open_positions = positions_state.get("open_positions", {})
    if not isinstance(open_positions, dict):
        open_positions = {}

    rebalanced_orders: List[Dict[str, Any]] = []
    skipped_count = 0
    generated_close_count = 0
    symbols_in_plan: set[str] = set()

    for order in base_orders:
        if not isinstance(order, dict):
            continue
        symbol = str(order.get("symbol", "")).upper().strip()
        if not symbol:
            continue
        symbols_in_plan.add(symbol)
        ref_price = float(order.get("reference_price", 0.0) or 0.0)
        if ref_price <= 0.0:
            skipped_count += 1
            continue

        target_notional = _extract_order_notional_usd(order)
        target_side = str(order.get("side", "BUY")).upper()
        target_signed = target_notional if target_side == "BUY" else -target_notional
        current_signed = _current_signed_notional(open_positions.get(symbol))
        delta_signed = target_signed - current_signed
        delta_notional = abs(delta_signed)

        if delta_notional < threshold:
            skipped_count += 1
            continue

        delta_side = "BUY" if delta_signed > 0 else "SELL"
        delta_qty = delta_notional / ref_price if ref_price > 0 else 0.0
        if delta_qty <= 0.0:
            skipped_count += 1
            continue

        updated = dict(order)
        updated["side"] = delta_side
        updated["target_notional_usd"] = float(round(delta_notional, 2))
        updated["target_quantity"] = float(round(delta_qty, 6))
        updated["rebalance_delta_notional_usd"] = float(round(delta_notional, 2))
        updated["rebalance_target_signed_notional_usd"] = float(round(target_signed, 2))
        updated["rebalance_current_signed_notional_usd"] = float(round(current_signed, 2))
        rebalanced_orders.append(updated)

    if close_missing_positions:
        for symbol, row in open_positions.items():
            ticker = str(symbol).upper().strip()
            if not ticker or ticker in symbols_in_plan:
                continue
            if not isinstance(row, dict):
                continue
            net_qty = float(row.get("net_quantity", 0.0) or 0.0)
            if net_qty == 0.0:
                continue
            avg_price = float(row.get("avg_price", 0.0) or 0.0)
            if avg_price <= 0.0:
                continue
            close_notional = abs(net_qty) * avg_price
            if close_notional < threshold:
                continue
            side = "SELL" if net_qty > 0 else "BUY"
            intent_id = str(uuid.uuid4())
            close_order = {
                "order_intent_id": intent_id,
                "client_order_id": _build_client_order_id(
                    plan_id=str(plan.get("plan_id") or ""),
                    symbol=ticker,
                    ordinal=900 + generated_close_count + 1,
                ),
                "idempotency_key": intent_id,
                "symbol": ticker,
                "side": side,
                "order_type": "MARKET",
                "time_in_force": "DAY",
                "execution_mode": EXECUTION_MODE_PAPER,
                "target_weight": 0.0,
                "target_notional_usd": float(round(close_notional, 2)),
                "reference_price": float(round(avg_price, 6)),
                "reference_price_source": "position_avg_price",
                "target_quantity": float(round(abs(net_qty), 6)),
                "aeternus_score": 0.0,
                "confidence": 0,
                "lane": row.get("lane"),
                "research_playbook": "AUTO_CLOSE_MISSING",
                "dominant_signal_family": "rebalance",
                "queue_id": "",
                "rating_id": (_as_string_list(row.get("rating_ids")) or [""])[0],
                "rebalance_auto_close": True,
            }
            rebalanced_orders.append(close_order)
            generated_close_count += 1

    updated_plan = dict(plan)
    updated_plan["orders"] = rebalanced_orders
    updated_plan["rebalance"] = {
        "mode": "DELTA_TO_TARGET",
        "positions_path": str(positions_path),
        "min_rebalance_notional_usd": float(threshold),
        "close_missing_positions": bool(close_missing_positions),
        "input_orders": int(len(base_orders)),
        "output_orders": int(len(rebalanced_orders)),
        "skipped_within_tolerance": int(skipped_count),
        "generated_close_orders": int(generated_close_count),
    }
    return updated_plan


def evaluate_pretrade_risk(
    plan: Dict[str, Any],
    positions_path: str = "eval_results/paper_execution/positions.json",
    max_gross_exposure_pct: float = 1.0,
    max_single_position_pct: float = 0.25,
    max_open_positions: int = 12,
    max_new_orders_per_run: int = 12,
    block_short_orders: bool = True,
    max_hedge_notional_pct: float = 1.5,
    allow_hedge_short_orders: bool = True,
) -> Dict[str, Any]:
    """Evaluate deterministic pre-trade guardrails before execution."""
    # --- Stale data detection (P2-05) ---
    warnings: List[str] = []
    plan_date_str = str(plan.get("date") or "").strip()
    if plan_date_str:
        try:
            import datetime as _dt

            plan_date = _dt.datetime.fromisoformat(plan_date_str)
            if plan_date.tzinfo is None:
                plan_date = plan_date.replace(tzinfo=_dt.timezone.utc)
            now_utc = _dt.datetime.now(_dt.timezone.utc)
            staleness_hours = float((now_utc - plan_date).total_seconds()) / 3600.0
            max_staleness = float(
                DEFAULT_CONFIG.get("max_data_staleness_hours", 24)
            )
            if staleness_hours > max_staleness:
                warnings.append(
                    f"STALE_PLAN_DATE: plan date {plan_date_str!r} is "
                    f"{staleness_hours:.1f}h old (limit {max_staleness:.0f}h); "
                    "may be intentional for backtest"
                )
        except Exception:
            pass  # Malformed date — skip silently

    capital_usd = float(plan.get("capital_usd", 0.0) or 0.0)
    limits = {
        "max_gross_exposure_pct": float(max_gross_exposure_pct),
        "max_single_position_pct": float(max_single_position_pct),
        "max_open_positions": int(max_open_positions),
        "max_new_orders_per_run": int(max_new_orders_per_run),
        "block_short_orders": bool(block_short_orders),
        "max_hedge_notional_pct": float(max_hedge_notional_pct),
        "allow_hedge_short_orders": bool(allow_hedge_short_orders),
    }
    max_gross_usd = max(0.0, capital_usd * float(max_gross_exposure_pct))
    max_single_usd = max(0.0, capital_usd * float(max_single_position_pct))
    max_hedge_notional_usd = max(0.0, capital_usd * float(max_hedge_notional_pct))

    positions = load_open_positions(positions_path=positions_path)
    open_positions = positions.get("open_positions", {})
    if not isinstance(open_positions, dict):
        open_positions = {}
    current_symbol_signed = {
        str(symbol).upper().strip(): float(_current_signed_notional(row))
        for symbol, row in open_positions.items()
        if isinstance(row, dict)
    }
    current_symbol_exposure = {
        symbol: abs(value)
        for symbol, value in current_symbol_signed.items()
    }
    current_open_symbols = {symbol for symbol, value in current_symbol_exposure.items() if value > 1e-9}
    current_gross_usd = float(sum(current_symbol_exposure.values()))
    current_hedge_notional_usd = float(
        sum(
            abs(float(row.get("market_value_usd", 0.0) or 0.0))
            for row in open_positions.values()
            if isinstance(row, dict)
            and (
                str(row.get("lane", "")).upper().strip() == "HEDGE"
                or str(row.get("research_playbook", "")).upper().strip() == "HEDGE_OVERLAY"
            )
        )
    )

    projected_symbol_signed = dict(current_symbol_signed)
    projected_symbol_exposure = dict(current_symbol_exposure)
    projected_open_symbols = set(current_open_symbols)
    projected_gross_usd = float(current_gross_usd)
    projected_hedge_notional_usd = float(current_hedge_notional_usd)

    accepted_orders: List[Dict[str, Any]] = []
    rejected_orders: List[Dict[str, Any]] = []
    order_count = 0
    for order in plan.get("orders", []):
        if not isinstance(order, dict):
            continue
        order_count += 1
        symbol = str(order.get("symbol", "")).upper().strip()
        side = str(order.get("side", "BUY")).upper()
        order_id = str(order.get("order_intent_id", "")).strip()
        order_notional = _extract_order_notional_usd(order)
        category = str(order.get("intent_category", "")).upper().strip()
        is_hedge_order = category == INTENT_CATEGORY_HEDGE
        reject_reason = ""

        if order_count > int(max_new_orders_per_run):
            reject_reason = "MAX_NEW_ORDERS_PER_RUN"
        elif not symbol:
            reject_reason = "INVALID_SYMBOL"
        elif (
            bool(block_short_orders)
            and side == "SELL"
            and is_hedge_order
            and not bool(allow_hedge_short_orders)
        ):
            reject_reason = "SHORTS_BLOCKED"
        elif order_notional <= 0.0:
            reject_reason = "MISSING_ORDER_NOTIONAL"
        else:
            if is_hedge_order:
                if side == "SELL":
                    hedge_after = projected_hedge_notional_usd + order_notional
                else:
                    hedge_after = max(0.0, projected_hedge_notional_usd - order_notional)
                if max_hedge_notional_usd > 0.0 and hedge_after > (max_hedge_notional_usd + 1e-9):
                    reject_reason = "MAX_HEDGE_NOTIONAL_EXCEEDED"
                else:
                    accepted_orders.append(order)
                    projected_hedge_notional_usd = hedge_after
            else:
                current_signed = float(projected_symbol_signed.get(symbol, 0.0) or 0.0)
                order_signed = order_notional if side == "BUY" else -order_notional
                signed_after = current_signed + order_signed
                symbol_before = abs(current_signed)
                symbol_after = abs(signed_after)
                gross_after = projected_gross_usd - symbol_before + symbol_after

                open_symbols_after = set(projected_open_symbols)
                if symbol_after > 1e-9:
                    open_symbols_after.add(symbol)
                else:
                    open_symbols_after.discard(symbol)
                open_after = len(open_symbols_after)

                if bool(block_short_orders) and side == "SELL" and signed_after < -1e-9:
                    reject_reason = "SHORTS_BLOCKED"
                elif max_single_usd > 0.0 and symbol_after > (max_single_usd + 1e-9):
                    reject_reason = "MAX_SINGLE_POSITION_EXCEEDED"
                elif max_gross_usd > 0.0 and gross_after > (max_gross_usd + 1e-9):
                    reject_reason = "MAX_GROSS_EXPOSURE_EXCEEDED"
                elif open_after > int(max_open_positions):
                    reject_reason = "MAX_OPEN_POSITIONS_EXCEEDED"
                else:
                    accepted_orders.append(order)
                    projected_symbol_signed[symbol] = float(signed_after)
                    projected_symbol_exposure[symbol] = symbol_after
                    projected_gross_usd = gross_after
                    projected_open_symbols = open_symbols_after

        if reject_reason:
            rejected_orders.append(
                {
                    "order_intent_id": order_id,
                    "symbol": symbol,
                    "side": side,
                    "intent_category": category,
                    "attempted_notional_usd": float(round(order_notional, 2)),
                    "reason": reject_reason,
                }
            )

    status = "PASS"
    if order_count == 0:
        status = "NO_ORDERS"
    elif accepted_orders and rejected_orders:
        status = "PARTIAL_PASS"
    elif not accepted_orders and rejected_orders:
        status = "REJECTED"

    return {
        "status": status,
        "plan_id": str(plan.get("plan_id") or ""),
        "date": str(plan.get("date") or ""),
        "capital_usd": float(round(capital_usd, 2)),
        "limits": limits,
        "current": {
            "gross_exposure_usd": float(round(current_gross_usd, 2)),
            "open_positions": int(len(current_open_symbols)),
            "hedge_notional_usd": float(round(current_hedge_notional_usd, 2)),
        },
        "projected": {
            "gross_exposure_usd": float(round(projected_gross_usd, 2)),
            "open_positions": int(len(projected_open_symbols)),
            "hedge_notional_usd": float(round(projected_hedge_notional_usd, 2)),
        },
        "orders_considered": int(order_count),
        "accepted_count": int(len(accepted_orders)),
        "rejected_count": int(len(rejected_orders)),
        "accepted_order_intent_ids": [
            str(order.get("order_intent_id", "")).strip()
            for order in accepted_orders
            if str(order.get("order_intent_id", "")).strip()
        ],
        "accepted_orders": accepted_orders,
        "rejected_orders": rejected_orders,
        "rejected_reason_counts": _count_rejected_reasons(rejected_orders),
        "warnings": warnings,
    }


def close_position_with_adapter(
    symbol: str,
    close_price: float,
    close_date: str,
    execution_mode: Literal["paper", "live", "alpaca-paper", "alpaca-live"] = EXECUTION_MODE_PAPER,
    positions_path: str = "eval_results/paper_execution/positions.json",
    closed_trades_path: str = "eval_results/paper_execution/closed_trades.json",
    track_record: Optional[TrackRecord] = None,
) -> Dict[str, Any]:
    """Close a position via adapter abstraction (paper now, live later)."""
    adapter = get_execution_adapter(execution_mode)
    result = adapter.close_position(
        symbol=symbol,
        close_price=close_price,
        close_date=close_date,
        positions_path=positions_path,
        closed_trades_path=closed_trades_path,
        track_record=track_record,
    )

    # --- Post-Mortem Auto-Generator (S-078) ---
    try:
        import glob as _glob
        from tradingagents.graph.post_mortem import PostMortemEngine as _PME
        _pm = _PME()

        # Try to find analysis report for this symbol
        _report = None
        _symbol = result.get("symbol", symbol)
        _report_pattern = f"results/{_symbol}/*/analysis_report.json"
        _report_files = sorted(_glob.glob(_report_pattern))
        if _report_files:
            import json as _json_pm
            with open(_report_files[-1]) as _f:
                _report = _json_pm.load(_f)

        _attr = _pm.analyze_trade(trade=result, report=_report)
        _narrative = _pm.generate_narrative(_attr)

        # Save attribution
        import os as _os_pm
        _pm_dir = "eval_results/paper_execution/post_mortems"
        _os_pm.makedirs(_pm_dir, exist_ok=True)
        _close_id = result.get("close_id", "unknown")
        _pm_path = f"{_pm_dir}/{_symbol}_{_close_id}.json"
        import json as _json_pm2
        with open(_pm_path, "w") as _f_pm:
            _json_pm2.dump(_attr, _f_pm, indent=2, default=str)

        import logging as _log_pm
        _log_pm.getLogger(__name__).info("POST-MORTEM %s:\n%s", _symbol, _narrative)
    except Exception:
        pass  # Never crash execution

    return result


# ── Conviction tiers ─────────────────────────────────────────────────────────
_CONVICTION_TIERS = [
    # (low_score, high_score, low_weight, high_weight, label)
    (62.0, 66.0, 0.05, 0.10, "MARGINAL"),
    (66.0, 72.0, 0.10, 0.18, "MODERATE"),
    (72.0, 80.0, 0.18, 0.25, "HIGH"),
    (80.0, 200.0, 0.25, 0.25, "CONVICTION"),
]


def _tier_for_score(score: float) -> Tuple[float, str]:
    """Return (base_weight, tier_label) for a given aeternus_score."""
    for low, high, w_lo, w_hi, label in _CONVICTION_TIERS:
        if score < high or label == "CONVICTION":
            t = max(0.0, min(1.0, (score - low) / (high - low))) if high > low else 1.0
            return round(w_lo + t * (w_hi - w_lo), 6), label
    return 0.05, "MARGINAL"


def _fetch_price_matrix(
    symbols: List[str], lookback_days: int = 80,
) -> "Optional[Any]":
    """Download close prices for *symbols* over *lookback_days* calendar days.

    Returns a pandas DataFrame (columns = symbols) or None on failure.
    """
    try:
        import pandas as pd
        from datetime import datetime, timedelta

        end = datetime.now()
        start = end - timedelta(days=lookback_days)
        prices = yf.download(
            symbols, start=start, end=end,
            auto_adjust=True, progress=False,
        )
        if prices is None or prices.empty:
            return None
        if isinstance(prices.columns, pd.MultiIndex):
            prices = prices["Close"]
        elif "Close" in prices.columns:
            prices = prices[["Close"]]
        prices = prices.dropna(axis=1, how="all")
        return prices
    except Exception:
        return None


def _conviction_weights(
    rows: Sequence[Dict[str, Any]],
    max_weight_per_position: float = 0.25,
) -> Tuple[List[float], Dict[str, Any]]:
    """Conviction-tiered portfolio sizing.

    Returns (weights, metadata) where weights do NOT necessarily sum to 1.0.
    Unallocated capital goes to V3 benchmark (QQQ).
    """
    import numpy as np

    meta: Dict[str, Any] = {
        "tiers": {},
        "vol_data": {},
        "correlation_penalties": {},
        "pre_adj_weights": {},
        "post_adj_weights": {},
    }

    if not rows:
        return [], meta

    symbols = [str(r.get("symbol", "")).upper().strip() for r in rows]
    scores = [float(r.get("aeternus_score", 0.0)) for r in rows]
    n = len(rows)

    # ── 1. Base weights from conviction tiers ───────────────────────────────
    base_weights: List[float] = []
    for i, (sym, score) in enumerate(zip(symbols, scores)):
        bw, tier = _tier_for_score(score)
        base_weights.append(bw)
        meta["tiers"][sym] = tier
    meta["pre_adj_weights"] = dict(zip(symbols, base_weights))

    # ── 2. Fetch prices → vol & correlation ─────────────────────────────────
    prices = _fetch_price_matrix(symbols) if n > 0 else None
    vol_20d: Dict[str, float] = {}
    corr_matrix: Optional[Any] = None

    if prices is not None and not prices.empty:
        returns = prices.pct_change().dropna()
        if len(returns) >= 20:
            for sym in symbols:
                if sym in returns.columns:
                    tail = returns[sym].iloc[-20:]
                    ann_vol = float(tail.std() * np.sqrt(252))
                    if ann_vol > 0:
                        vol_20d[sym] = round(ann_vol, 6)
            available = [s for s in symbols if s in returns.columns]
            if len(available) >= 2:
                corr_matrix = returns[available].corr()

    meta["vol_data"] = dict(vol_20d)

    # ── 3. Volatility scaling (0.5x – 2.0x) ────────────────────────────────
    weights = list(base_weights)
    if vol_20d:
        ref_vol = float(np.median(list(vol_20d.values())))
        for i, sym in enumerate(symbols):
            if sym in vol_20d and vol_20d[sym] > 0:
                scale = ref_vol / vol_20d[sym]
                scale = max(0.5, min(2.0, scale))
                weights[i] = weights[i] * scale

    # ── 4. Correlation penalty (pairs > 0.70) ──────────────────────────────
    penalty_map: Dict[str, float] = {s: 1.0 for s in symbols}
    if corr_matrix is not None:
        for i_idx, s1 in enumerate(symbols):
            for j_idx, s2 in enumerate(symbols):
                if i_idx < j_idx and s1 in corr_matrix.columns and s2 in corr_matrix.columns:
                    c = float(corr_matrix.loc[s1, s2])
                    if not np.isnan(c) and c > 0.70:
                        p = 1.0 - 0.5 * (c - 0.70) / 0.30
                        p = max(0.70, min(1.0, p))
                        penalty_map[s1] = min(penalty_map[s1], p)
                        penalty_map[s2] = min(penalty_map[s2], p)
                        meta["correlation_penalties"][(s1, s2)] = round(c, 4)

    for i, sym in enumerate(symbols):
        weights[i] *= penalty_map[sym]

    # ── 5. Per-position cap (25%) ───────────────────────────────────────────
    cap = max(0.01, min(1.0, float(max_weight_per_position)))
    for i in range(n):
        weights[i] = min(weights[i], cap)

    # ── 6. Half-Kelly ceiling ───────────────────────────────────────────────
    for i, (sym, score) in enumerate(zip(symbols, scores)):
        edge = (score - 50.0) / 100.0
        v = vol_20d.get(sym)
        if v and v > 0 and edge > 0:
            variance = v * v
            half_kelly = edge / (2.0 * variance)
            if half_kelly < weights[i]:
                weights[i] = half_kelly

    # ── 7. Total cap at 1.0 (pro-rata reduce) ──────────────────────────────
    total = sum(weights)
    if total > 1.0:
        for i in range(n):
            weights[i] = weights[i] / total

    weights = [round(w, 6) for w in weights]
    meta["post_adj_weights"] = dict(zip(symbols, weights))

    # ── 8. Per-symbol max correlation for metadata ──────────────────────────
    max_corr_map: Dict[str, float] = {}
    if corr_matrix is not None:
        for sym in symbols:
            if sym in corr_matrix.columns:
                row_vals = corr_matrix.loc[sym].drop(sym, errors="ignore")
                if not row_vals.empty:
                    max_corr_map[sym] = round(float(row_vals.abs().max()), 4)
    meta["max_correlations"] = max_corr_map

    # ── 9. Effective bets (eigenvalue HHI) ──────────────────────────────────
    effective_bets = float(n)
    if corr_matrix is not None and len(corr_matrix) >= 2:
        try:
            eigenvalues = np.linalg.eigvalsh(corr_matrix.values)
            eigenvalues = np.maximum(eigenvalues, 0)
            ev_total = eigenvalues.sum()
            if ev_total > 0:
                ev_weights = eigenvalues / ev_total
                hhi = float((ev_weights ** 2).sum())
                effective_bets = 1.0 / hhi if hhi > 0 else float(n)
        except Exception:
            pass
    meta["effective_positions"] = round(effective_bets, 2)

    # ── 10. Average pairwise correlation ────────────────────────────────────
    if corr_matrix is not None and len(corr_matrix) >= 2:
        vals = []
        cols = list(corr_matrix.columns)
        for i_idx in range(len(cols)):
            for j_idx in range(i_idx + 1, len(cols)):
                v = float(corr_matrix.iloc[i_idx, j_idx])
                if not np.isnan(v):
                    vals.append(v)
        meta["avg_pairwise_correlation"] = round(float(np.mean(vals)), 4) if vals else 0.0
    else:
        meta["avg_pairwise_correlation"] = 0.0

    return weights, meta


def _apply_fill_to_position(open_positions: Dict[str, Any], order: Dict[str, Any]) -> None:
    symbol = str(order.get("symbol", "")).upper().strip()
    if not symbol:
        return
    signed_qty = float(order.get("signed_quantity", 0.0) or 0.0)
    fill_price = float(order.get("filled_price", 0.0) or 0.0)
    if signed_qty == 0 or fill_price <= 0:
        return

    current = dict(open_positions.get(symbol, {}))
    old_qty = float(current.get("net_quantity", 0.0) or 0.0)
    old_avg = float(current.get("avg_price", 0.0) or 0.0)
    new_qty = old_qty + signed_qty

    if old_qty == 0 or (old_qty > 0 and new_qty > 0 and signed_qty > 0) or (old_qty < 0 and new_qty < 0 and signed_qty < 0):
        total_abs = abs(old_qty) + abs(signed_qty)
        if total_abs > 0:
            avg_price = ((abs(old_qty) * old_avg) + (abs(signed_qty) * fill_price)) / total_abs
        else:
            avg_price = fill_price
    elif new_qty == 0:
        avg_price = 0.0
    elif (old_qty > 0 > new_qty) or (old_qty < 0 < new_qty):
        avg_price = fill_price
    else:
        avg_price = old_avg

    rating_ids = _as_string_list(current.get("rating_ids"))
    rating_id = order.get("rating_id")
    if rating_id:
        rid = str(rating_id)
        if rid not in rating_ids:
            rating_ids.append(rid)

    if new_qty == 0:
        open_positions.pop(symbol, None)
        return

    now_iso = _now_iso()
    existing_opened_at = str(current.get("opened_at") or "").strip()
    if existing_opened_at and old_qty * new_qty > 0:
        opened_at = existing_opened_at
    else:
        opened_at = now_iso

    if new_qty > 0:
        prev_high = float(current.get("high_watermark_price", fill_price) or fill_price)
        high_watermark_price = float(round(max(prev_high, fill_price), 6))
        low_watermark_price = None
    else:
        prev_low = float(current.get("low_watermark_price", fill_price) or fill_price)
        low_watermark_price = float(round(min(prev_low, fill_price), 6))
        high_watermark_price = None

    # Preserve entry_aeternus_score and pillar breakdown from first fill (new position)
    if old_qty == 0:
        entry_score = float(order.get("aeternus_score", 0) or 0)
        entry_pillar_breakdown = dict(order.get("entry_pillar_breakdown", {}))
        entry_weight_regime = str(order.get("entry_weight_regime", ""))
    else:
        entry_score = float(current.get("entry_aeternus_score", 0) or 0)
        entry_pillar_breakdown = dict(current.get("entry_pillar_breakdown", {}))
        entry_weight_regime = str(current.get("entry_weight_regime", ""))

    open_positions[symbol] = {
        "symbol": symbol,
        "net_quantity": float(round(new_qty, 6)),
        "avg_price": float(round(avg_price, 6)),
        "market_value_usd": float(round(abs(new_qty) * fill_price, 2)),
        "last_mark_price": float(round(fill_price, 6)),
        "opened_at": opened_at,
        "high_watermark_price": high_watermark_price,
        "low_watermark_price": low_watermark_price,
        "direction": "LONG" if new_qty > 0 else "SHORT",
        "rating_ids": rating_ids,
        "lane": order.get("lane"),
        "research_playbook": order.get("research_playbook"),
        "invalidation_conditions": order.get("invalidation_conditions") or current.get("invalidation_conditions", []),
        "original_conviction": float(order.get("confidence", 0) or order.get("original_conviction", 0) or current.get("original_conviction", 0) or 0),
        "entry_aeternus_score": entry_score,
        "entry_pillar_breakdown": entry_pillar_breakdown,
        "entry_weight_regime": entry_weight_regime,
        "updated_at": now_iso,
    }


def _recommendation_to_side(recommendation: str, long_only: bool) -> str:
    rec = str(recommendation or "").upper()
    if "BUY" in rec:
        return "BUY"
    if "SELL" in rec:
        return "SKIP" if long_only else "SELL"
    return "SKIP"


def _extract_reference_price(item: Dict[str, Any], analysis: Dict[str, Any]) -> Optional[float]:
    aet_score = analysis.get("aeternus_score", {}) if isinstance(analysis, dict) else {}
    if isinstance(aet_score, dict):
        value = aet_score.get("price_at_rating")
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            pass

    market_data = analysis.get("market_data", {}) if isinstance(analysis, dict) else {}
    if isinstance(market_data, dict):
        try:
            close = market_data.get("close")
            if close is not None:
                return float(close)
        except (TypeError, ValueError):
            pass

    return None


def _fetch_reference_price_from_market(symbol: str, analysis_date: str) -> Optional[float]:
    ticker = str(symbol or "").upper().strip()
    if not ticker:
        return None

    anchor_date = _parse_analysis_date(analysis_date)
    start = (anchor_date - dt.timedelta(days=7)).isoformat()
    end = (anchor_date + dt.timedelta(days=5)).isoformat()

    try:
        frame = yf.download(
            ticker,
            start=start,
            end=end,
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
        )
    except Exception:
        frame = None

    close = _extract_last_close_from_frame(frame)
    if close is not None and close > 0:
        return float(close)

    # Final fallback: latest month snapshot when date-window request is empty.
    try:
        hist = yf.Ticker(ticker).history(period="1mo", interval="1d", auto_adjust=False)
    except Exception:
        hist = None
    close = _extract_last_close_from_frame(hist)
    if close is not None and close > 0:
        return float(close)
    return None


def _extract_last_close_from_frame(frame: Any) -> Optional[float]:
    if frame is None:
        return None
    try:
        if getattr(frame, "empty", True):
            return None
        close_col = frame.get("Close")
        if close_col is None:
            return None
        # yfinance may return a Series or DataFrame depending on shape.
        if hasattr(close_col, "dropna"):
            close_non_null = close_col.dropna()
            if getattr(close_non_null, "empty", True):
                return None
            if hasattr(close_non_null, "iloc"):
                last = close_non_null.iloc[-1]
                if hasattr(last, "iloc"):
                    # DataFrame row: take the first value.
                    last = last.iloc[0]
                return float(last)
    except Exception:
        return None
    return None


def _parse_analysis_date(raw: str) -> dt.date:
    text = str(raw or "").strip()
    if not text:
        return dt.datetime.now(dt.timezone.utc).date()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return dt.datetime.now(dt.timezone.utc).date()


def _extract_rating_id(analysis: Dict[str, Any]) -> str:
    if not isinstance(analysis, dict):
        return ""
    aet_score = analysis.get("aeternus_score", {})
    if isinstance(aet_score, dict):
        return str(aet_score.get("rating_id") or "")
    return ""


def _apply_slippage(reference_price: float, side: str, bps: float) -> float:
    slip = max(0.0, float(bps)) / 10000.0
    if str(side).upper() == "BUY":
        return reference_price * (1.0 + slip)
    return reference_price * (1.0 - slip)


def _load_json(path: Path, default: Any = None) -> Any:
    return read_json_locked(path, default_factory=lambda: default)


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_locked(path, payload)


def _as_string_list(raw: Any) -> List[str]:
    if isinstance(raw, list):
        values = [str(v).strip() for v in raw if str(v).strip()]
    else:
        values = []
    seen: List[str] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _build_client_order_id(plan_id: str, symbol: str, ordinal: int) -> str:
    compact = str(plan_id).replace("-", "")[:10]
    ticker = str(symbol or "").upper().strip()[:8]
    return f"{compact}-{ticker}-{int(ordinal):03d}"


def _extract_order_notional_usd(order: Dict[str, Any]) -> float:
    raw_notional = order.get("target_notional_usd")
    try:
        if raw_notional is not None:
            value = abs(float(raw_notional))
            if value > 0.0:
                return value
    except (TypeError, ValueError):
        pass

    try:
        qty = abs(float(order.get("target_quantity", 0.0) or 0.0))
        px = abs(float(order.get("reference_price", 0.0) or 0.0))
    except (TypeError, ValueError):
        return 0.0
    if qty > 0.0 and px > 0.0:
        return qty * px
    return 0.0


def _clamp_float(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _current_signed_notional(position_row: Any) -> float:
    if not isinstance(position_row, dict):
        return 0.0
    market_value = abs(float(position_row.get("market_value_usd", 0.0) or 0.0))
    direction = str(position_row.get("direction", "")).upper()
    net_qty = float(position_row.get("net_quantity", 0.0) or 0.0)
    if direction == "SHORT" or net_qty < 0:
        return -market_value
    return market_value


def _count_rejected_reasons(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        reason = str(row.get("reason", "UNKNOWN")).upper()
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def _normalize_execution_mode(mode: str) -> str:
    text = str(mode or EXECUTION_MODE_PAPER).strip().lower().replace("_", "-")
    if text == "alpaca":
        return EXECUTION_MODE_ALPACA_PAPER
    return text


def _resolve_alpaca_credentials(mode: str) -> tuple[str, str, str, float]:
    normalized_mode = _normalize_execution_mode(mode)
    explicit_base = str(os.getenv("ALPACA_API_BASE_URL", "")).strip()
    if explicit_base:
        base_url = explicit_base
    elif normalized_mode == EXECUTION_MODE_ALPACA_LIVE:
        base_url = str(
            os.getenv("ALPACA_LIVE_API_BASE_URL", "https://api.alpaca.markets")
        ).strip()
    else:
        base_url = str(
            os.getenv(
                "ALPACA_PAPER_API_BASE_URL", "https://paper-api.alpaca.markets"
            )
        ).strip()

    api_key_id = str(
        os.getenv("APCA_API_KEY_ID", "") or os.getenv("ALPACA_API_KEY_ID", "")
    ).strip()
    api_secret_key = str(
        os.getenv("APCA_API_SECRET_KEY", "") or os.getenv("ALPACA_API_SECRET_KEY", "")
    ).strip()
    timeout = max(
        1.0,
        float(os.getenv("ALPACA_REQUEST_TIMEOUT_SECONDS", "15")),
    )
    return _normalize_alpaca_base_url(base_url), api_key_id, api_secret_key, timeout


def _alpaca_headers(api_key_id: str, api_secret_key: str) -> Dict[str, str]:
    return {
        "APCA-API-KEY-ID": api_key_id,
        "APCA-API-SECRET-KEY": api_secret_key,
        "Accept": "application/json",
    }


RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _get_broker_adapter() -> AlpacaBrokerAdapter:
    """Return a module-level singleton AlpacaBrokerAdapter."""
    if not hasattr(_get_broker_adapter, "_instance"):
        _get_broker_adapter._instance = AlpacaBrokerAdapter()  # type: ignore[attr-defined]
    return _get_broker_adapter._instance  # type: ignore[attr-defined]


def _alpaca_get_json(
    base_url: str,
    endpoint: str,
    headers: Dict[str, str],
    timeout_seconds: float,
    params: Optional[Dict[str, Any]] = None,
    max_retries: int = 3,
) -> tuple[Any, Optional[str]]:
    """Delegate to AlpacaBrokerAdapter.get_json(). Preserves (payload, error) signature."""
    return _get_broker_adapter().get_json(
        endpoint=endpoint,
        method="GET",
        params=params,
        base_url_override=base_url,
        max_retries=max_retries,
    )


def _submit_alpaca_order(
    base_url: str,
    api_key_id: str,
    api_secret_key: str,
    payload: Dict[str, Any],
    timeout_seconds: float,
    max_retries: int = 3,
) -> Dict[str, Any]:
    """Delegate to AlpacaBrokerAdapter.get_json(). Raises ValueError on failure."""
    data, error = _get_broker_adapter().get_json(
        endpoint="/v2/orders",
        method="POST",
        json_body=payload,
        base_url_override=base_url,
        max_retries=max_retries,
    )
    if error:
        raise ValueError(f"Alpaca order submit failed: {error}")
    if not isinstance(data, dict):
        raise ValueError("Alpaca order submit returned invalid payload.")
    return data


def _format_qty(quantity: float) -> str:
    text = f"{float(quantity):.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


def _normalize_alpaca_base_url(raw_url: str) -> str:
    text = str(raw_url or "").strip().rstrip("/")
    if text.lower().endswith("/v2"):
        text = text[:-3]
    return text


def _coerce_order_quantity(raw_qty: float, whole_shares: bool) -> float:
    qty = max(0.0, float(raw_qty))
    if whole_shares:
        return float(int(qty))
    return qty


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_iso(raw: Any) -> Optional[dt.datetime]:
    text = str(raw or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        value = dt.datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _parse_iso_or_now(raw: Any) -> dt.datetime:
    parsed = _parse_iso(raw)
    if parsed is not None:
        return parsed
    return dt.datetime.now(dt.timezone.utc)


def _extract_broker_orders(snapshot: Any) -> List[Dict[str, Any]]:
    if isinstance(snapshot, list):
        return [row for row in snapshot if isinstance(row, dict)]
    if isinstance(snapshot, dict):
        for key in ("orders", "results", "items", "data", "broker_orders"):
            value = snapshot.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def _normalize_broker_status(raw_status: str) -> str:
    status = str(raw_status or "").strip().upper().replace("-", "_").replace(" ", "_")
    if not status:
        return ""
    if "PARTIAL" in status:
        return "PARTIALLY_FILLED"
    if "FILLED" in status:
        return "FILLED"
    if "CANCEL" in status:
        return "CANCELED"
    if "REJECT" in status:
        return "REJECTED"
    if "REPLACE" in status:
        return "REPLACED"
    if "EXPIRE" in status or status == "DONE_FOR_DAY":
        return "EXPIRED"
    if status in {"NEW", "ACCEPTED", "PENDING_NEW", "SUBMITTED"}:
        return "SUBMITTED"
    return status


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _count_outbox_statuses(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "UNKNOWN").upper().strip()
        counts[status] = counts.get(status, 0) + 1
    return counts


def _dedupe_list(values: List[str]) -> List[str]:
    seen: List[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.append(text)
    return seen
