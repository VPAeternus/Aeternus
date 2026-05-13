import json
from pathlib import Path
from unittest.mock import Mock, MagicMock

import pandas as pd

from tradingagents.graph.paper_execution import (
    build_hedge_order_intent,
    build_exit_execution_plan,
    build_rebalance_execution_plan,
    build_portfolio_plan,
    close_position_with_adapter,
    evaluate_execution_readiness,
    evaluate_pretrade_risk,
    execute_plan_with_adapter,
    fetch_alpaca_orders_snapshot,
    fetch_alpaca_positions_snapshot,
    refresh_positions_market_snapshot,
    reconcile_live_execution,
    suppress_v3_residual_order,
)
from tradingagents.graph.track_record import TrackRecord


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def test_build_portfolio_plan_includes_broker_compatible_order_fields(tmp_path):
    analysis_path = tmp_path / "results" / "AAPL" / "2026-02-06" / "analysis_report.json"
    _write_json(
        analysis_path,
        {
            "aeternus_score": {
                "rating_id": "rid-aapl",
                "price_at_rating": 200.0,
            }
        },
    )
    summary = {
        "run_id": "2026-02-06-batch",
        "date": "2026-02-06",
        "items": [
            {
                "queue_id": "q:AAPL",
                "symbol": "AAPL",
                "status": "SUCCESS",
                "recommendation": "BUY",
                "aeternus_score": 82.0,
                "confidence": 4,
                "lane": "CORE",
                "research_playbook": "HYBRID_COMPOUNDER",
                "dominant_signal_family": "news_catalyst",
                "analysis_report_path": str(analysis_path),
            }
        ],
    }

    plan = build_portfolio_plan(
        batch_summary=summary,
        capital_usd=100000.0,
        max_positions=5,
    )

    assert plan["orders"]
    order = plan["orders"][0]
    assert order["order_type"] == "MARKET"
    assert order["time_in_force"] == "DAY"
    assert order["execution_mode"] == "paper"
    assert order["client_order_id"]
    assert order["idempotency_key"] == order["order_intent_id"]


def test_build_hedge_order_intent_returns_hedge_order(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.graph.paper_execution._fetch_reference_price_from_market",
        lambda symbol, analysis_date="": 500.0 if symbol == "SPY" else None,
    )

    order = build_hedge_order_intent(
        plan_id="plan-hedge",
        run_date="2026-02-06",
        capital_usd=100000.0,
        portfolio_snapshot={
            "gross_exposure_usd": 100000.0,
            "current_hedge_pct": 0.0,
        },
        hedge_signal={"mode": "BEAR", "market_regime": "BEAR"},
        hedge_decision={
            "status": "EXECUTED",
            "instrument": "SPY",
            "final_target_hedge_pct": 50.0,
            "delta_hedge_pct": 50.0,
            "delta_notional_usd": 50000.0,
            "reason": "defensive",
        },
        enforce_whole_shares=True,
    )

    assert order is not None
    assert order["intent_category"] == "HEDGE"
    assert order["symbol"] == "SPY"
    assert order["side"] == "SELL"
    assert order["target_notional_usd"] == 50000.0
    assert order["target_quantity"] == 100.0
    assert order["quantity_policy"] == "WHOLE_SHARES"


def test_execute_plan_with_adapter_is_idempotent_by_order_intent(tmp_path, monkeypatch):
    # Mock yfinance to avoid rate limiting
    mock_ticker = MagicMock()
    mock_ticker.info = {
        "averageVolume": 50_000_000,  # 50M shares
        "regularMarketPrice": 150.0,   # 50M * $150 = $7.5B ADV
        "marketCap": 3_000_000_000,    # $3B market cap
    }
    
    def mock_yf_ticker(symbol):
        return mock_ticker
    
    monkeypatch.setattr("tradingagents.graph.liquidity_gate.yf.Ticker", mock_yf_ticker)
    
    plan = {
        "plan_id": "plan-123",
        "date": "2026-02-06",
        "orders": [
            {
                "order_intent_id": "intent-1",
                "client_order_id": "cid-1",
                "idempotency_key": "intent-1",
                "symbol": "AAPL",
                "side": "BUY",
                "order_type": "MARKET",
                "time_in_force": "DAY",
                "execution_mode": "paper",
                "reference_price": 100.0,
                "target_quantity": 10.0,
                "queue_id": "q:AAPL",
                "rating_id": "rid-1",
                "lane": "CORE",
                "research_playbook": "HYBRID_COMPOUNDER",
                "dominant_signal_family": "news_catalyst",
            }
        ],
    }
    orders_path = tmp_path / "orders.json"
    positions_path = tmp_path / "positions.json"

    first = execute_plan_with_adapter(
        plan=plan,
        execution_mode="paper",
        orders_path=str(orders_path),
        positions_path=str(positions_path),
        fill_price_slippage_bps=0.0,
    )
    second = execute_plan_with_adapter(
        plan=plan,
        execution_mode="paper",
        orders_path=str(orders_path),
        positions_path=str(positions_path),
        fill_price_slippage_bps=0.0,
    )

    assert first["executed_orders"] == 1
    assert second["executed_orders"] == 0
    assert second["skipped_duplicate_orders"] == 1

    history = json.loads(orders_path.read_text())
    assert len(history) == 1
    assert history[0]["order_intent_id"] == "intent-1"


def test_close_position_with_adapter_updates_linked_rating_ids(tmp_path):
    positions_path = tmp_path / "positions.json"
    closed_path = tmp_path / "closed.json"
    _write_json(
        positions_path,
        {
            "updated_at": "2026-02-06T00:00:00+00:00",
            "open_positions": {
                "AAPL": {
                    "symbol": "AAPL",
                    "net_quantity": 5.0,
                    "avg_price": 100.0,
                    "market_value_usd": 500.0,
                    "direction": "LONG",
                    "rating_ids": ["rid-1", "rid-2"],
                    "lane": "CORE",
                    "research_playbook": "HYBRID_COMPOUNDER",
                }
            },
        },
    )
    mock_track_record = Mock()
    mock_track_record.update_outcome.return_value = True

    event = close_position_with_adapter(
        symbol="AAPL",
        close_price=110.0,
        close_date="2026-02-07",
        execution_mode="paper",
        positions_path=str(positions_path),
        closed_trades_path=str(closed_path),
        track_record=mock_track_record,
    )

    assert event["symbol"] == "AAPL"
    assert event["pnl_usd"] == 50.0
    assert event["updated_rating_ids"] == ["rid-1", "rid-2"]
    assert mock_track_record.update_outcome.call_count == 2

    positions = json.loads(positions_path.read_text())
    assert "AAPL" not in positions["open_positions"]


def test_execute_plan_with_adapter_live_queues_without_fills(tmp_path):
    plan = {
        "plan_id": "plan-live",
        "date": "2026-02-06",
        "orders": [
            {
                "order_intent_id": "intent-live-1",
                "client_order_id": "cid-live-1",
                "idempotency_key": "intent-live-1",
                "symbol": "AAPL",
                "side": "BUY",
                "order_type": "MARKET",
                "time_in_force": "DAY",
                "execution_mode": "live",
                "reference_price": 100.0,
                "target_quantity": 10.0,
                "target_notional_usd": 1000.0,
                "queue_id": "q:AAPL",
                "rating_id": "rid-1",
                "lane": "CORE",
                "research_playbook": "HYBRID_COMPOUNDER",
                "dominant_signal_family": "news_catalyst",
            }
        ],
    }
    outbox_path = tmp_path / "live_outbox.json"
    positions_path = tmp_path / "positions.json"

    first = execute_plan_with_adapter(
        plan=plan,
        execution_mode="live",
        orders_path=str(outbox_path),
        positions_path=str(positions_path),
        fill_price_slippage_bps=0.0,
    )
    second = execute_plan_with_adapter(
        plan=plan,
        execution_mode="live",
        orders_path=str(outbox_path),
        positions_path=str(positions_path),
        fill_price_slippage_bps=0.0,
    )

    assert first["execution_mode"] == "live"
    assert first["executed_orders"] == 0
    assert first["submitted_orders"] == 1
    assert first["orders"][0]["status"] == "SUBMITTED"
    assert second["submitted_orders"] == 0
    assert second["skipped_duplicate_orders"] == 1


def test_evaluate_pretrade_risk_blocks_single_name_and_gross_limits(tmp_path):
    positions_path = tmp_path / "positions.json"
    _write_json(
        positions_path,
        {
            "updated_at": "2026-02-06T00:00:00+00:00",
            "open_positions": {},
        },
    )
    plan = {
        "plan_id": "plan-1",
        "date": "2026-02-06",
        "capital_usd": 100000.0,
        "orders": [
            {
                "order_intent_id": "o1",
                "symbol": "AAPL",
                "side": "BUY",
                "target_notional_usd": 26000.0,
            },
            {
                "order_intent_id": "o2",
                "symbol": "MSFT",
                "side": "BUY",
                "target_notional_usd": 21000.0,
            },
            {
                "order_intent_id": "o3",
                "symbol": "NVDA",
                "side": "BUY",
                "target_notional_usd": 21000.0,
            },
            {
                "order_intent_id": "o4",
                "symbol": "GOOGL",
                "side": "BUY",
                "target_notional_usd": 21000.0,
            },
            {
                "order_intent_id": "o5",
                "symbol": "META",
                "side": "BUY",
                "target_notional_usd": 21000.0,
            },
            {
                "order_intent_id": "o6",
                "symbol": "AMZN",
                "side": "BUY",
                "target_notional_usd": 21000.0,
            },
        ],
    }

    report = evaluate_pretrade_risk(
        plan=plan,
        positions_path=str(positions_path),
        max_gross_exposure_pct=1.0,
        max_single_position_pct=0.25,
        max_open_positions=12,
        max_new_orders_per_run=12,
        block_short_orders=True,
    )

    assert report["status"] == "PARTIAL_PASS"
    assert report["accepted_count"] == 4
    assert report["rejected_count"] == 2
    assert report["rejected_reason_counts"]["MAX_SINGLE_POSITION_EXCEEDED"] == 1
    assert report["rejected_reason_counts"]["MAX_GROSS_EXPOSURE_EXCEEDED"] == 1


def test_evaluate_pretrade_risk_blocks_short_orders_when_enabled(tmp_path):
    positions_path = tmp_path / "positions.json"
    _write_json(
        positions_path,
        {
            "updated_at": "2026-02-06T00:00:00+00:00",
            "open_positions": {},
        },
    )
    plan = {
        "plan_id": "plan-short",
        "date": "2026-02-06",
        "capital_usd": 50000.0,
        "orders": [
            {
                "order_intent_id": "s1",
                "symbol": "TSLA",
                "side": "SELL",
                "target_notional_usd": 10000.0,
            }
        ],
    }

    report = evaluate_pretrade_risk(
        plan=plan,
        positions_path=str(positions_path),
        max_gross_exposure_pct=1.0,
        max_single_position_pct=0.5,
        max_open_positions=12,
        max_new_orders_per_run=12,
        block_short_orders=True,
    )

    assert report["status"] == "REJECTED"
    assert report["accepted_count"] == 0
    assert report["rejected_count"] == 1
    assert report["rejected_reason_counts"]["SHORTS_BLOCKED"] == 1


def test_evaluate_pretrade_risk_allows_sell_to_reduce_existing_long(tmp_path):
    positions_path = tmp_path / "positions.json"
    _write_json(
        positions_path,
        {
            "updated_at": "2026-02-06T00:00:00+00:00",
            "open_positions": {
                "AAPL": {
                    "symbol": "AAPL",
                    "net_quantity": 100.0,
                    "avg_price": 100.0,
                    "market_value_usd": 10000.0,
                    "direction": "LONG",
                }
            },
        },
    )
    plan = {
        "plan_id": "plan-reduce",
        "date": "2026-02-06",
        "capital_usd": 50000.0,
        "orders": [
            {
                "order_intent_id": "reduce-1",
                "symbol": "AAPL",
                "side": "SELL",
                "target_notional_usd": 4000.0,
            }
        ],
    }

    report = evaluate_pretrade_risk(
        plan=plan,
        positions_path=str(positions_path),
        max_gross_exposure_pct=1.0,
        max_single_position_pct=0.5,
        max_open_positions=12,
        max_new_orders_per_run=12,
        block_short_orders=True,
    )

    assert report["status"] == "PASS"
    assert report["accepted_count"] == 1
    assert report["rejected_count"] == 0
    assert report["projected"]["gross_exposure_usd"] == 6000.0


def test_evaluate_pretrade_risk_blocks_sell_that_flips_to_short(tmp_path):
    positions_path = tmp_path / "positions.json"
    _write_json(
        positions_path,
        {
            "updated_at": "2026-02-06T00:00:00+00:00",
            "open_positions": {
                "AAPL": {
                    "symbol": "AAPL",
                    "net_quantity": 100.0,
                    "avg_price": 100.0,
                    "market_value_usd": 10000.0,
                    "direction": "LONG",
                }
            },
        },
    )
    plan = {
        "plan_id": "plan-flip-short",
        "date": "2026-02-06",
        "capital_usd": 50000.0,
        "orders": [
            {
                "order_intent_id": "flip-1",
                "symbol": "AAPL",
                "side": "SELL",
                "target_notional_usd": 12000.0,
            }
        ],
    }

    report = evaluate_pretrade_risk(
        plan=plan,
        positions_path=str(positions_path),
        max_gross_exposure_pct=1.0,
        max_single_position_pct=0.5,
        max_open_positions=12,
        max_new_orders_per_run=12,
        block_short_orders=True,
    )

    assert report["status"] == "REJECTED"
    assert report["accepted_count"] == 0
    assert report["rejected_count"] == 1
    assert report["rejected_reason_counts"]["SHORTS_BLOCKED"] == 1


def test_evaluate_pretrade_risk_allows_hedge_short_when_enabled(tmp_path):
    positions_path = tmp_path / "positions.json"
    _write_json(
        positions_path,
        {
            "updated_at": "2026-02-06T00:00:00+00:00",
            "open_positions": {},
        },
    )
    plan = {
        "plan_id": "plan-hedge-risk",
        "date": "2026-02-06",
        "capital_usd": 100000.0,
        "orders": [
            {
                "order_intent_id": "h1",
                "symbol": "SPY",
                "side": "SELL",
                "intent_category": "HEDGE",
                "target_notional_usd": 50000.0,
            }
        ],
    }

    report = evaluate_pretrade_risk(
        plan=plan,
        positions_path=str(positions_path),
        max_gross_exposure_pct=1.0,
        max_single_position_pct=0.25,
        max_open_positions=12,
        max_new_orders_per_run=12,
        block_short_orders=True,
        allow_hedge_short_orders=True,
        max_hedge_notional_pct=1.5,
    )

    assert report["status"] == "PASS"
    assert report["accepted_count"] == 1
    assert report["rejected_count"] == 0
    assert report["projected"]["hedge_notional_usd"] == 50000.0


def test_evaluate_pretrade_risk_rejects_oversized_hedge(tmp_path):
    positions_path = tmp_path / "positions.json"
    _write_json(
        positions_path,
        {
            "updated_at": "2026-02-06T00:00:00+00:00",
            "open_positions": {},
        },
    )
    plan = {
        "plan_id": "plan-hedge-oversized",
        "date": "2026-02-06",
        "capital_usd": 100000.0,
        "orders": [
            {
                "order_intent_id": "h2",
                "symbol": "SPY",
                "side": "SELL",
                "intent_category": "HEDGE",
                "target_notional_usd": 200000.0,
            }
        ],
    }

    report = evaluate_pretrade_risk(
        plan=plan,
        positions_path=str(positions_path),
        max_gross_exposure_pct=1.0,
        max_single_position_pct=0.25,
        max_open_positions=12,
        max_new_orders_per_run=12,
        block_short_orders=True,
        allow_hedge_short_orders=True,
        max_hedge_notional_pct=1.5,
    )

    assert report["status"] == "REJECTED"
    assert report["accepted_count"] == 0
    assert report["rejected_count"] == 1
    assert report["rejected_reason_counts"]["MAX_HEDGE_NOTIONAL_EXCEEDED"] == 1


def test_build_portfolio_plan_uses_market_price_fallback_when_report_price_missing(tmp_path, monkeypatch):
    analysis_path = tmp_path / "results" / "AAPL" / "2026-02-06" / "analysis_report.json"
    _write_json(
        analysis_path,
        {
            "aeternus_score": {
                "rating_id": "rid-aapl",
                "price_at_rating": None,
            }
        },
    )
    summary = {
        "run_id": "2026-02-06-batch",
        "date": "2026-02-06",
        "items": [
            {
                "queue_id": "q:AAPL",
                "symbol": "AAPL",
                "status": "SUCCESS",
                "recommendation": "BUY",
                "aeternus_score": 82.0,
                "confidence": 4,
                "lane": "CORE",
                "research_playbook": "HYBRID_COMPOUNDER",
                "dominant_signal_family": "news_catalyst",
                "analysis_report_path": str(analysis_path),
            }
        ],
    }

    frame = pd.DataFrame({"Close": [200.0, 202.5]})
    monkeypatch.setattr("tradingagents.graph.paper_execution.yf.download", lambda *args, **kwargs: frame)

    plan = build_portfolio_plan(
        batch_summary=summary,
        capital_usd=100000.0,
        max_positions=5,
    )

    # With weight capping fix, AAPL is capped at 25% (0.25 weight), so QQQ gets 75% as residual
    assert len(plan["orders"]) == 2
    aapl_order = [o for o in plan["orders"] if o["symbol"] == "AAPL"][0]
    assert aapl_order["reference_price"] == 202.5
    assert aapl_order["reference_price_source"] == "market_fallback"
    # Verify QQQ residual order exists
    qqq_orders = [o for o in plan["orders"] if o["symbol"] == "QQQ"]
    assert len(qqq_orders) == 1


def test_suppress_v3_residual_order_parks_cash():
    plan = {
        "v3_residual_usd": 75000.0,
        "v3_sizing_usd": 75000.0,
        "v3_cash_reserve_usd": 0.0,
        "orders": [
            {"symbol": "AAPL", "dominant_signal_family": "news_catalyst"},
            {"symbol": "QQQ", "dominant_signal_family": "v3_benchmark", "target_notional_usd": 75000.0},
        ],
    }

    removed = suppress_v3_residual_order(plan, "S7 hedge active")

    assert removed["symbol"] == "QQQ"
    assert [o["symbol"] for o in plan["orders"]] == ["AAPL"]
    assert plan["v3_sizing_usd"] == 0.0
    assert plan["v3_cash_reserve_usd"] == 75000.0
    assert plan["v3_suppressed"] is True
    assert plan["v3_suppression_reason"] == "S7 hedge active"


def test_build_portfolio_plan_enforces_whole_shares_when_requested(tmp_path):
    analysis_path = tmp_path / "results" / "META" / "2026-02-06" / "analysis_report.json"
    _write_json(
        analysis_path,
        {
            "aeternus_score": {
                "rating_id": "rid-meta",
                "price_at_rating": 661.46,
            }
        },
    )
    summary = {
        "run_id": "2026-02-06-batch",
        "date": "2026-02-06",
        "items": [
            {
                "queue_id": "q:META",
                "symbol": "META",
                "status": "SUCCESS",
                "recommendation": "BUY",
                "aeternus_score": 82.0,
                "confidence": 4,
                "lane": "CORE",
                "research_playbook": "HYBRID_COMPOUNDER",
                "dominant_signal_family": "news_catalyst",
                "analysis_report_path": str(analysis_path),
            }
        ],
    }

    plan = build_portfolio_plan(
        batch_summary=summary,
        capital_usd=100000.0,
        max_positions=5,
        enforce_whole_shares=True,
    )

    # With weight capping fix, META is capped at 25%, QQQ gets 75% residual
    assert len(plan["orders"]) == 2
    meta_order = [o for o in plan["orders"] if o["symbol"] == "META"][0]
    assert meta_order["quantity_policy"] == "WHOLE_SHARES"
    # META gets ~25% of 100k = ~25k, at 661.46 = ~37-38 shares (whole share capped)
    assert meta_order["target_quantity"] == 37.0  # floor(25000 / 661.46)
    # QQQ gets remaining residual
    qqq_orders = [o for o in plan["orders"] if o["symbol"] == "QQQ"]
    assert len(qqq_orders) == 1
    assert qqq_orders[0]["lane"] == "MOMENTUM"


def test_build_rebalance_execution_plan_skips_orders_within_tolerance(tmp_path):
    positions_path = tmp_path / "positions.json"
    _write_json(
        positions_path,
        {
            "updated_at": "2026-02-06T00:00:00+00:00",
            "open_positions": {
                "AAPL": {
                    "symbol": "AAPL",
                    "net_quantity": 100.0,
                    "avg_price": 100.0,
                    "market_value_usd": 10000.0,
                    "direction": "LONG",
                    "rating_ids": ["rid-1"],
                }
            },
        },
    )
    plan = {
        "plan_id": "plan-1",
        "date": "2026-02-06",
        "orders": [
            {
                "order_intent_id": "intent-aapl",
                "symbol": "AAPL",
                "side": "BUY",
                "target_notional_usd": 10000.0,
                "target_quantity": 100.0,
                "reference_price": 100.0,
            }
        ],
    }

    rebalance_plan = build_rebalance_execution_plan(
        plan=plan,
        positions_path=str(positions_path),
        min_rebalance_notional_usd=100.0,
        close_missing_positions=False,
    )

    assert rebalance_plan["orders"] == []
    assert rebalance_plan["rebalance"]["input_orders"] == 1
    assert rebalance_plan["rebalance"]["output_orders"] == 0
    assert rebalance_plan["rebalance"]["skipped_within_tolerance"] == 1


def test_build_rebalance_execution_plan_outputs_delta_order(tmp_path):
    positions_path = tmp_path / "positions.json"
    _write_json(
        positions_path,
        {
            "updated_at": "2026-02-06T00:00:00+00:00",
            "open_positions": {
                "AAPL": {
                    "symbol": "AAPL",
                    "net_quantity": 80.0,
                    "avg_price": 100.0,
                    "market_value_usd": 8000.0,
                    "direction": "LONG",
                    "rating_ids": ["rid-1"],
                }
            },
        },
    )
    plan = {
        "plan_id": "plan-1",
        "date": "2026-02-06",
        "orders": [
            {
                "order_intent_id": "intent-aapl",
                "symbol": "AAPL",
                "side": "BUY",
                "target_notional_usd": 10000.0,
                "target_quantity": 100.0,
                "reference_price": 100.0,
            }
        ],
    }

    rebalance_plan = build_rebalance_execution_plan(
        plan=plan,
        positions_path=str(positions_path),
        min_rebalance_notional_usd=100.0,
        close_missing_positions=False,
    )

    assert len(rebalance_plan["orders"]) == 1
    order = rebalance_plan["orders"][0]
    assert order["side"] == "BUY"
    assert order["target_notional_usd"] == 2000.0
    assert order["target_quantity"] == 20.0


def test_reconcile_live_execution_applies_fill_once_idempotently(tmp_path):
    outbox_path = tmp_path / "live_outbox.json"
    positions_path = tmp_path / "positions.json"
    fills_path = tmp_path / "fills.json"
    _write_json(
        outbox_path,
        [
            {
                "order_intent_id": "intent-1",
                "client_order_id": "cid-1",
                "symbol": "AAPL",
                "side": "BUY",
                "target_quantity": 10.0,
                "reference_price": 100.0,
                "status": "SUBMITTED",
                "lane": "CORE",
                "research_playbook": "HYBRID_COMPOUNDER",
                "rating_id": "rid-1",
            }
        ],
    )

    snapshot = {
        "orders": [
            {
                "order_intent_id": "intent-1",
                "status": "FILLED",
                "filled_quantity": 10.0,
                "avg_fill_price": 101.5,
                "broker_order_id": "broker-1",
            }
        ]
    }

    first = reconcile_live_execution(
        broker_snapshot=snapshot,
        outbox_path=str(outbox_path),
        positions_path=str(positions_path),
        fills_path=str(fills_path),
    )
    second = reconcile_live_execution(
        broker_snapshot=snapshot,
        outbox_path=str(outbox_path),
        positions_path=str(positions_path),
        fills_path=str(fills_path),
    )

    assert first["fills_applied"] == 1
    assert first["status_updates"] == 1
    assert second["fills_applied"] == 0

    positions = json.loads(positions_path.read_text())
    aapl = positions["open_positions"]["AAPL"]
    assert aapl["net_quantity"] == 10.0
    assert aapl["avg_price"] == 101.5

    fills = json.loads(fills_path.read_text())
    assert len(fills) == 1
    assert fills[0]["order_intent_id"] == "intent-1"


def test_reconcile_live_execution_applies_partial_fill_delta_only(tmp_path):
    outbox_path = tmp_path / "live_outbox.json"
    positions_path = tmp_path / "positions.json"
    fills_path = tmp_path / "fills.json"
    _write_json(
        outbox_path,
        [
            {
                "order_intent_id": "intent-2",
                "client_order_id": "cid-2",
                "symbol": "TSLA",
                "side": "BUY",
                "target_quantity": 10.0,
                "reference_price": 200.0,
                "status": "SUBMITTED",
                "lane": "MOMENTUM",
                "research_playbook": "MOMENTUM_BREAKOUT",
                "rating_id": "rid-2",
            }
        ],
    )

    partial_snapshot = {
        "orders": [
            {
                "order_intent_id": "intent-2",
                "status": "PARTIALLY_FILLED",
                "filled_quantity": 4.0,
                "avg_fill_price": 200.0,
            }
        ]
    }
    final_snapshot = {
        "orders": [
            {
                "order_intent_id": "intent-2",
                "status": "FILLED",
                "filled_quantity": 10.0,
                "avg_fill_price": 202.0,
            }
        ]
    }

    first = reconcile_live_execution(
        broker_snapshot=partial_snapshot,
        outbox_path=str(outbox_path),
        positions_path=str(positions_path),
        fills_path=str(fills_path),
    )
    second = reconcile_live_execution(
        broker_snapshot=final_snapshot,
        outbox_path=str(outbox_path),
        positions_path=str(positions_path),
        fills_path=str(fills_path),
    )

    assert first["fills_applied"] == 1
    assert second["fills_applied"] == 1

    positions = json.loads(positions_path.read_text())
    tsla = positions["open_positions"]["TSLA"]
    assert tsla["net_quantity"] == 10.0
    assert round(tsla["avg_price"], 4) == 201.2

    outbox = json.loads(outbox_path.read_text())
    assert outbox[0]["applied_filled_quantity"] == 10.0
    assert outbox[0]["status"] == "FILLED"

    fills = json.loads(fills_path.read_text())
    assert len(fills) == 2
    assert fills[0]["filled_quantity"] == 4.0
    assert fills[1]["filled_quantity"] == 6.0


def test_reconcile_live_execution_normalizes_partial_status(tmp_path):
    outbox_path = tmp_path / "live_outbox.json"
    positions_path = tmp_path / "positions.json"
    fills_path = tmp_path / "fills.json"
    _write_json(
        outbox_path,
        [
            {
                "order_intent_id": "intent-partial-status",
                "client_order_id": "cid-partial-status",
                "symbol": "AAPL",
                "side": "BUY",
                "target_quantity": 5.0,
                "reference_price": 100.0,
                "status": "SUBMITTED",
            }
        ],
    )
    snapshot = {
        "orders": [
            {
                "order_intent_id": "intent-partial-status",
                "status": "partially filled",
                "filled_quantity": 2.0,
                "avg_fill_price": 101.0,
            }
        ]
    }

    report = reconcile_live_execution(
        broker_snapshot=snapshot,
        outbox_path=str(outbox_path),
        positions_path=str(positions_path),
        fills_path=str(fills_path),
    )

    assert report["fills_applied"] == 1
    outbox = json.loads(outbox_path.read_text())
    assert outbox[0]["status"] == "PARTIALLY_FILLED"
    assert outbox[0]["broker_status_normalized"] == "PARTIALLY_FILLED"


def test_reconcile_live_execution_treats_replaced_as_terminal(tmp_path):
    outbox_path = tmp_path / "live_outbox.json"
    positions_path = tmp_path / "positions.json"
    fills_path = tmp_path / "fills.json"
    _write_json(
        outbox_path,
        [
            {
                "order_intent_id": "intent-replaced",
                "client_order_id": "cid-replaced",
                "symbol": "AAPL",
                "side": "BUY",
                "target_quantity": 5.0,
                "reference_price": 100.0,
                "status": "SUBMITTED",
            }
        ],
    )
    snapshot = {
        "orders": [
            {
                "order_intent_id": "intent-replaced",
                "status": "replaced",
                "filled_quantity": 0.0,
            }
        ]
    }

    report = reconcile_live_execution(
        broker_snapshot=snapshot,
        outbox_path=str(outbox_path),
        positions_path=str(positions_path),
        fills_path=str(fills_path),
    )

    assert report["status_updates"] == 1
    outbox = json.loads(outbox_path.read_text())
    assert outbox[0]["status"] == "REPLACED"
    assert outbox[0]["terminal_at"]


def test_reconcile_live_execution_closes_position_and_updates_outcomes(tmp_path):
    outbox_path = tmp_path / "live_outbox.json"
    positions_path = tmp_path / "positions.json"
    fills_path = tmp_path / "fills.json"
    closed_path = tmp_path / "closed_trades.json"
    track_path = tmp_path / "track_record.json"

    _write_json(
        outbox_path,
        [
            {
                "order_intent_id": "intent-close-1",
                "client_order_id": "cid-close-1",
                "symbol": "AAPL",
                "side": "SELL",
                "target_quantity": 10.0,
                "reference_price": 110.0,
                "status": "SUBMITTED",
                "lane": "CORE",
                "research_playbook": "HYBRID_COMPOUNDER",
                "rating_id": "rid-close-1",
            }
        ],
    )
    _write_json(
        positions_path,
        {
            "updated_at": "2026-02-07T00:00:00+00:00",
            "open_positions": {
                "AAPL": {
                    "symbol": "AAPL",
                    "net_quantity": 10.0,
                    "avg_price": 100.0,
                    "market_value_usd": 1000.0,
                    "direction": "LONG",
                    "rating_ids": ["rid-close-1"],
                    "lane": "CORE",
                    "research_playbook": "HYBRID_COMPOUNDER",
                }
            },
        },
    )
    _write_json(
        track_path,
        [
            {
                "rating_id": "rid-close-1",
                "ticker": "AAPL",
                "rating": "Buy",
                "price_at_rating": 100.0,
                "status": "OPEN",
            }
        ],
    )

    snapshot = {
        "orders": [
            {
                "order_intent_id": "intent-close-1",
                "status": "FILLED",
                "filled_quantity": 10.0,
                "avg_fill_price": 110.0,
                "broker_order_id": "broker-close-1",
            }
        ]
    }
    tr = TrackRecord(path=str(track_path))
    first = reconcile_live_execution(
        broker_snapshot=snapshot,
        outbox_path=str(outbox_path),
        positions_path=str(positions_path),
        fills_path=str(fills_path),
        closed_trades_path=str(closed_path),
        track_record=tr,
    )
    second = reconcile_live_execution(
        broker_snapshot=snapshot,
        outbox_path=str(outbox_path),
        positions_path=str(positions_path),
        fills_path=str(fills_path),
        closed_trades_path=str(closed_path),
        track_record=tr,
    )

    assert first["fills_applied"] == 1
    assert first["closed_positions"] == 1
    assert first["outcomes_updated"] == 1
    assert first["closed_symbols"] == ["AAPL"]
    assert second["fills_applied"] == 0
    assert second["closed_positions"] == 0
    assert second["outcomes_updated"] == 0

    positions = json.loads(positions_path.read_text())
    assert positions["open_positions"] == {}

    closed = json.loads(closed_path.read_text())
    assert len(closed) == 1
    assert closed[0]["symbol"] == "AAPL"
    assert closed[0]["close_source"] == "LIVE_RECONCILIATION"
    assert closed[0]["close_price"] == 110.0
    assert closed[0]["pnl_usd"] == 100.0
    assert closed[0]["updated_rating_ids"] == ["rid-close-1"]

    track = json.loads(track_path.read_text())
    assert track[0]["status"] == "CLOSED"
    assert track[0]["close_price"] == 110.0


def test_execute_plan_with_adapter_alpaca_submits_and_skips_duplicates(tmp_path, monkeypatch):
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("ALPACA_PAPER_API_BASE_URL", "https://paper-api.alpaca.markets")

    class _Response:
        status_code = 200

        @staticmethod
        def json():
            return {"id": "broker-order-1", "status": "new", "qty": "10", "filled_qty": "0"}

        text = ""

    post_calls = []

    def _fake_post(url, headers, json, timeout):
        post_calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _Response()

    monkeypatch.setattr("tradingagents.graph.paper_execution.requests.post", _fake_post)

    plan = {
        "plan_id": "plan-alpaca",
        "date": "2026-02-06",
        "orders": [
            {
                "order_intent_id": "intent-1",
                "client_order_id": "cid-1",
                "symbol": "AAPL",
                "side": "BUY",
                "target_quantity": 10.0,
                "target_notional_usd": 1000.0,
                "reference_price": 100.0,
                "lane": "CORE",
                "research_playbook": "HYBRID_COMPOUNDER",
            }
        ],
    }
    outbox_path = tmp_path / "outbox.json"
    positions_path = tmp_path / "positions.json"

    first = execute_plan_with_adapter(
        plan=plan,
        execution_mode="alpaca-paper",
        orders_path=str(outbox_path),
        positions_path=str(positions_path),
        fill_price_slippage_bps=0.0,
    )
    second = execute_plan_with_adapter(
        plan=plan,
        execution_mode="alpaca-paper",
        orders_path=str(outbox_path),
        positions_path=str(positions_path),
        fill_price_slippage_bps=0.0,
    )

    assert first["submitted_orders"] == 1
    assert second["submitted_orders"] == 0
    assert second["skipped_duplicate_orders"] == 1
    assert len(post_calls) == 1


def test_execute_plan_with_adapter_alpaca_rounds_quantity_to_whole_shares(tmp_path, monkeypatch):
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("ALPACA_PAPER_API_BASE_URL", "https://paper-api.alpaca.markets")
    monkeypatch.setenv("ALPACA_ENFORCE_WHOLE_SHARES", "true")

    class _Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"id": "broker-order-2", "status": "new", "qty": "37", "filled_qty": "0"}

    post_payloads = []

    def _fake_post(url, headers, json, timeout):
        post_payloads.append(json)
        return _Response()

    monkeypatch.setattr("tradingagents.graph.paper_execution.requests.post", _fake_post)

    plan = {
        "plan_id": "plan-alpaca-qty",
        "date": "2026-02-06",
        "orders": [
            {
                "order_intent_id": "intent-qty",
                "client_order_id": "cid-qty",
                "symbol": "META",
                "side": "BUY",
                "target_quantity": 37.795179,
                "target_notional_usd": 25000.0,
                "reference_price": 661.46,
            }
        ],
    }

    outbox_path = tmp_path / "outbox.json"
    result = execute_plan_with_adapter(
        plan=plan,
        execution_mode="alpaca-paper",
        orders_path=str(outbox_path),
        positions_path=str(tmp_path / "positions.json"),
        fill_price_slippage_bps=0.0,
    )

    assert result["submitted_orders"] == 1
    assert post_payloads[0]["qty"] == "37"
    outbox = json.loads(outbox_path.read_text())
    assert outbox[0]["target_quantity"] == 37.0
    assert outbox[0]["quantity_policy"] == "WHOLE_SHARES"


def test_execute_plan_with_adapter_alpaca_whole_share_round_to_zero_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("ALPACA_PAPER_API_BASE_URL", "https://paper-api.alpaca.markets")
    monkeypatch.setenv("ALPACA_ENFORCE_WHOLE_SHARES", "true")

    post_calls = []

    def _fake_post(url, headers, json, timeout):
        post_calls.append(json)
        raise AssertionError("should not submit when rounded quantity is zero")

    monkeypatch.setattr("tradingagents.graph.paper_execution.requests.post", _fake_post)

    plan = {
        "plan_id": "plan-alpaca-zero",
        "date": "2026-02-06",
        "orders": [
            {
                "order_intent_id": "intent-zero",
                "symbol": "AAPL",
                "side": "BUY",
                "target_quantity": 0.6,
                "reference_price": 100.0,
            }
        ],
    }

    result = execute_plan_with_adapter(
        plan=plan,
        execution_mode="alpaca-paper",
        orders_path=str(tmp_path / "outbox.json"),
        positions_path=str(tmp_path / "positions.json"),
        fill_price_slippage_bps=0.0,
    )

    assert result["submitted_orders"] == 0
    assert result["failed_orders"] == 1
    assert result["failed"][0]["error"] == "WHOLE_SHARE_ROUND_DOWN_TO_ZERO"
    assert post_calls == []


def test_fetch_alpaca_orders_snapshot_writes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("ALPACA_API_BASE_URL", "https://paper-api.alpaca.markets/v2")

    class _Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return [{"id": "ord-1", "status": "filled"}]

    def _fake_get(url, headers, params, timeout):
        assert url == "https://paper-api.alpaca.markets/v2/orders"
        assert params["status"] == "all"
        return _Response()

    monkeypatch.setattr("tradingagents.graph.paper_execution.requests.get", _fake_get)
    out = tmp_path / "broker_orders_latest.json"
    snapshot = fetch_alpaca_orders_snapshot(out_path=str(out), mode="alpaca-paper", status="all", limit=200)
    assert snapshot["source"] == "alpaca"
    assert len(snapshot["orders"]) == 1
    disk = json.loads(out.read_text())
    assert disk["source"] == "alpaca"


def test_fetch_alpaca_positions_snapshot_writes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("ALPACA_API_BASE_URL", "https://paper-api.alpaca.markets/v2")

    class _Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return [{"symbol": "AAPL", "qty": "10"}]

    def _fake_get(url, headers, timeout, params=None):
        assert url == "https://paper-api.alpaca.markets/v2/positions"
        return _Response()

    monkeypatch.setattr("tradingagents.graph.paper_execution.requests.get", _fake_get)
    out = tmp_path / "broker_positions_latest.json"
    snapshot = fetch_alpaca_positions_snapshot(out_path=str(out), mode="alpaca-paper")
    assert snapshot["source"] == "alpaca"
    assert len(snapshot["positions"]) == 1
    disk = json.loads(out.read_text())
    assert disk["source"] == "alpaca"


def test_refresh_positions_market_snapshot_updates_market_values(tmp_path, monkeypatch):
    positions_path = tmp_path / "positions.json"
    _write_json(
        positions_path,
        {
            "updated_at": "2026-02-06T00:00:00+00:00",
            "open_positions": {
                "AAPL": {
                    "symbol": "AAPL",
                    "net_quantity": 10.0,
                    "avg_price": 100.0,
                    "market_value_usd": 1000.0,
                    "direction": "LONG",
                }
            },
        },
    )

    monkeypatch.setattr(
        "tradingagents.graph.paper_execution._fetch_reference_price_from_market",
        lambda symbol, analysis_date="": 110.0 if symbol == "AAPL" else None,
    )

    report = refresh_positions_market_snapshot(positions_path=str(positions_path))

    assert report["refreshed_count"] == 1
    assert report["unavailable_count"] == 0
    updated = json.loads(positions_path.read_text())
    aapl = updated["open_positions"]["AAPL"]
    assert aapl["last_mark_price"] == 110.0
    assert aapl["market_value_usd"] == 1100.0
    assert aapl["unrealized_pnl_usd"] == 100.0
    assert aapl["unrealized_return_pct"] == 10.0


def test_build_exit_execution_plan_generates_position_review_exit(tmp_path):
    """Position with low entry score (below v3 hurdle 62) triggers adaptive EXIT."""
    positions_path = tmp_path / "positions.json"
    outbox_path = tmp_path / "outbox.json"
    _write_json(
        positions_path,
        {
            "updated_at": "2026-02-07T00:00:00+00:00",
            "open_positions": {
                "AAPL": {
                    "symbol": "AAPL",
                    "net_quantity": 10.0,
                    "avg_price": 100.0,
                    "last_mark_price": 89.0,
                    "market_value_usd": 890.0,
                    "opened_at": "2026-01-10T00:00:00+00:00",
                    "lane": "CORE",
                    "research_playbook": "HYBRID_COMPOUNDER",
                    "rating_ids": ["rid-aapl"],
                    "entry_aeternus_score": 55.0,
                }
            },
        },
    )
    _write_json(outbox_path, [])

    plan = build_exit_execution_plan(
        execution_mode="alpaca-paper",
        positions_path=str(positions_path),
        outbox_path=str(outbox_path),
        min_position_notional_usd=100.0,
        max_exit_orders_per_run=6,
        enforce_whole_shares=True,
        as_of="2026-02-07T12:00:00+00:00",
    )

    assert len(plan["signals"]) == 1
    assert len(plan["orders"]) == 1
    assert plan["signals"][0]["rule"] == "POSITION_REVIEW"
    assert plan["orders"][0]["side"] == "SELL"
    assert plan["orders"][0]["target_quantity"] == 10.0
    assert plan["orders"][0]["intent_category"] == "EXIT"


def test_build_exit_execution_plan_skips_when_active_exit_order_exists(tmp_path):
    positions_path = tmp_path / "positions.json"
    outbox_path = tmp_path / "outbox.json"
    _write_json(
        positions_path,
        {
            "updated_at": "2026-02-07T00:00:00+00:00",
            "open_positions": {
                "AAPL": {
                    "symbol": "AAPL",
                    "net_quantity": 10.0,
                    "avg_price": 100.0,
                    "last_mark_price": 89.0,
                }
            },
        },
    )
    _write_json(
        outbox_path,
        [
            {
                "symbol": "AAPL",
                "side": "SELL",
                "status": "SUBMITTED",
                "intent_category": "EXIT",
            }
        ],
    )

    plan = build_exit_execution_plan(
        execution_mode="alpaca-paper",
        positions_path=str(positions_path),
        outbox_path=str(outbox_path),
        enforce_whole_shares=True,
        as_of="2026-02-07T12:00:00+00:00",
    )

    assert plan["signals"] == []
    assert plan["orders"] == []
    assert any(row.get("reason") == "ACTIVE_EXIT_ORDER" for row in plan["skipped"])


def test_evaluate_execution_readiness_passes_when_all_checks_green(tmp_path, monkeypatch):
    outbox_path = tmp_path / "outbox.json"
    positions_path = tmp_path / "positions.json"
    _write_json(outbox_path, [])
    _write_json(
        positions_path,
        {
            "updated_at": "2026-02-07T00:00:00+00:00",
            "open_positions": {
                "AAPL": {
                    "symbol": "AAPL",
                    "net_quantity": 10.0,
                    "avg_price": 100.0,
                    "last_mark_price": 100.0,
                }
            },
        },
    )

    monkeypatch.setattr(
        "tradingagents.graph.paper_execution._resolve_alpaca_credentials",
        lambda mode: ("https://paper-api.alpaca.markets", "key", "secret", 10.0),
    )

    def _fake_get(base_url, endpoint, headers, timeout_seconds, params=None):
        if endpoint == "/v2/account":
            return {"status": "ACTIVE", "buying_power": "100000"}, None
        if endpoint == "/v2/clock":
            return {"is_open": False, "next_open": "2026-02-10T14:30:00Z"}, None
        if endpoint == "/v2/orders":
            return [], None
        if endpoint == "/v2/positions":
            return [{"symbol": "AAPL", "qty": "10"}], None
        return None, "unexpected endpoint"

    monkeypatch.setattr("tradingagents.graph.paper_execution._alpaca_get_json", _fake_get)

    report = evaluate_execution_readiness(
        broker="alpaca",
        mode="alpaca-paper",
        outbox_path=str(outbox_path),
        positions_path=str(positions_path),
        snapshot_path=None,
        max_stale_submitted_minutes=180,
        max_unmatched_open_orders=10,
        max_position_drift_notional_usd=2500.0,
        min_buying_power_usd=1.0,
    )

    assert report["overall_ready"] is True
    assert report["checks"]["credentials"]["pass"] is True
    assert report["checks"]["account"]["pass"] is True
    assert report["checks"]["position_drift"]["pass"] is True
    assert report["blockers"] == []


def test_evaluate_execution_readiness_blocks_stale_pending_orders(tmp_path, monkeypatch):
    outbox_path = tmp_path / "outbox.json"
    positions_path = tmp_path / "positions.json"
    _write_json(
        outbox_path,
        [
            {
                "order_intent_id": "intent-1",
                "symbol": "AAPL",
                "side": "BUY",
                "status": "SUBMITTED",
                "submitted_at": "2026-02-07T00:00:00+00:00",
            }
        ],
    )
    _write_json(
        positions_path,
        {"updated_at": "2026-02-07T00:00:00+00:00", "open_positions": {}},
    )

    monkeypatch.setattr(
        "tradingagents.graph.paper_execution._resolve_alpaca_credentials",
        lambda mode: ("https://paper-api.alpaca.markets", "key", "secret", 10.0),
    )

    def _fake_get(base_url, endpoint, headers, timeout_seconds, params=None):
        if endpoint == "/v2/account":
            return {"status": "ACTIVE", "buying_power": "100000"}, None
        if endpoint == "/v2/clock":
            return {"is_open": False}, None
        if endpoint == "/v2/orders":
            return [], None
        if endpoint == "/v2/positions":
            return [], None
        return None, "unexpected endpoint"

    monkeypatch.setattr("tradingagents.graph.paper_execution._alpaca_get_json", _fake_get)

    report = evaluate_execution_readiness(
        broker="alpaca",
        mode="alpaca-paper",
        outbox_path=str(outbox_path),
        positions_path=str(positions_path),
        snapshot_path=None,
        max_stale_submitted_minutes=1,
        max_unmatched_open_orders=10,
        max_position_drift_notional_usd=2500.0,
        min_buying_power_usd=1.0,
    )

    assert report["overall_ready"] is False
    assert report["checks"]["stale_pending_orders"]["pass"] is False
    assert any("Stale pending orders detected" in msg for msg in report["blockers"])
