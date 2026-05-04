import sys
import types

# Stub chromadb before it can be imported (pydantic v1 incompatible with Python 3.14)
if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []  # make it look like a package
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub

from unittest.mock import Mock, patch

from typer.testing import CliRunner

from cli.main import app
from cli.common import (
    build_pretrade_risk_context,
    format_portfolio_risk_hedge_markdown,
    run_hedging_cycle,
)

runner = CliRunner()


def test_run_hedging_cycle_logs_signal_and_applied_event():
    portfolio = {
        "gross_exposure_usd": 1000.0,
        "current_hedge_pct": 0.0,
        "tech_concentration_pct": 20.0,
    }
    market = {"spy_close": 100.0}
    signal = {
        "base_hedge_pct": 85.0,
        "s7_boost_pct": 0.0,
        "bear_trigger_active": True,
        "crash_trigger_active": False,
        "target_hedge_pct_pre_hysteresis": 85.0,
        "mode": "BEAR",
    }
    decision = {
        "final_target_hedge_pct": 85.0,
        "instrument": "SPY",
        "action": "INCREASE_HEDGE",
        "delta_hedge_pct": 85.0,
        "delta_notional_usd": 850.0,
        "reason": "test",
        "status": "EXECUTED",
    }
    order = {"id": "o1"}

    with patch("cli.common.build_portfolio_risk_snapshot", return_value=portfolio), patch(
        "cli.common.MarketRegimeProvider"
    ) as provider_cls, patch("cli.common.AdaptiveHedgeEngine") as engine_cls, patch(
        "cli.common.RatingAuditLog"
    ) as audit_cls:
        provider_cls.return_value.get_market_regime_snapshot.return_value = market
        engine_cls.return_value.evaluate.return_value = (signal, decision, order)
        audit = Mock()
        audit_cls.return_value = audit

        out_portfolio, out_market, out_signal, out_decision = run_hedging_cycle("rid-1")

        assert out_portfolio == portfolio
        assert out_market == market
        assert out_signal == signal
        assert out_decision == decision

        event_types = [call.args[0] for call in audit.log_event.call_args_list]
        assert "HEDGE_SIGNAL_GENERATED" in event_types
        assert "HEDGE_APPLIED" in event_types


def test_run_hedging_cycle_logs_skipped_event():
    portfolio = {
        "gross_exposure_usd": 1000.0,
        "current_hedge_pct": 20.0,
        "tech_concentration_pct": 20.0,
    }
    signal = {
        "base_hedge_pct": 85.0,
        "s7_boost_pct": 0.0,
        "bear_trigger_active": True,
        "crash_trigger_active": False,
        "target_hedge_pct_pre_hysteresis": 85.0,
        "mode": "BEAR",
    }
    decision = {
        "final_target_hedge_pct": 85.0,
        "instrument": "SPY",
        "action": "NO_CHANGE",
        "delta_hedge_pct": 0.0,
        "delta_notional_usd": 0.0,
        "reason": "hysteresis",
        "status": "SKIPPED_HYSTERESIS",
    }

    with patch("cli.common.build_portfolio_risk_snapshot", return_value=portfolio), patch(
        "cli.common.MarketRegimeProvider"
    ) as provider_cls, patch("cli.common.AdaptiveHedgeEngine") as engine_cls, patch(
        "cli.common.RatingAuditLog"
    ) as audit_cls:
        provider_cls.return_value.get_market_regime_snapshot.return_value = {}
        engine_cls.return_value.evaluate.return_value = (signal, decision, None)
        audit = Mock()
        audit_cls.return_value = audit

        run_hedging_cycle("rid-2")

        event_types = [call.args[0] for call in audit.log_event.call_args_list]
        assert "HEDGE_SIGNAL_GENERATED" in event_types
        assert "HEDGE_SKIPPED_HYSTERESIS" in event_types


def test_build_pretrade_risk_context_uses_non_persistent_path():
    portfolio = {
        "gross_exposure_usd": 1000.0,
        "net_exposure_usd": 1000.0,
        "portfolio_beta_60d": 1.1,
        "var_95_1d_pct_nav": 2.8,
        "drawdown_20d_pct": 4.0,
        "tech_concentration_pct": 40.0,
        "current_hedge_pct": 10.0,
    }
    market = {
        "spy_close": 500.0,
        "spy_sma20": 498.0,
        "spy_sma200": 470.0,
        "spy_sma200_5d_ago": 468.0,
        "spy_deviation_pct": 0.4,
        "vix_close": 19.0,
    }
    signal = {
        "base_hedge_pct": 85.0,
        "s7_boost_pct": 0.0,
        "bear_trigger_active": True,
        "crash_trigger_active": False,
        "target_hedge_pct_pre_hysteresis": 85.0,
        "mode": "BEAR",
        "market_regime": "BEAR",
        "data_sufficient": True,
    }
    decision = {
        "final_target_hedge_pct": 85.0,
        "instrument": "SPY",
        "action": "INCREASE_HEDGE",
        "delta_hedge_pct": 75.0,
        "delta_notional_usd": 750.0,
        "reason": "test",
        "status": "EXECUTED",
    }

    with patch("cli.common.build_portfolio_risk_snapshot", return_value=portfolio), patch(
        "cli.common.MarketRegimeProvider"
    ) as provider_cls, patch("cli.common.AdaptiveHedgeEngine") as engine_cls:
        provider_cls.return_value.get_market_regime_snapshot.return_value = market
        engine = Mock()
        engine.compute_hedge_signal.return_value = signal
        engine.decide_hedge.return_value = decision
        engine_cls.return_value = engine

        out_portfolio, out_market, out_signal, out_decision, brief = build_pretrade_risk_context()

        assert out_portfolio == portfolio
        assert out_market == market
        assert out_signal == signal
        assert out_decision == decision
        assert "Portfolio Risk Snapshot" in brief
        assert "Hedge Recommendation" in brief
        engine.compute_hedge_signal.assert_called_once()
        engine.decide_hedge.assert_called_once()
        engine.evaluate.assert_not_called()


def test_format_portfolio_risk_hedge_markdown_includes_core_fields():
    md = format_portfolio_risk_hedge_markdown(
        {
            "gross_exposure_usd": 100000.0,
            "net_exposure_usd": 85000.0,
            "portfolio_beta_60d": 1.2,
            "var_95_1d_pct_nav": 3.1,
            "drawdown_20d_pct": 6.0,
            "tech_concentration_pct": 55.0,
            "current_hedge_pct": 30.0,
        },
        {"spy_close": 500.0, "spy_sma20": 495.0, "spy_sma200": 470.0, "spy_deviation_pct": 1.0, "vix_close": 24.0},
        {"market_regime": "BEAR_STRESS", "mode": "BEAR"},
        {"action": "INCREASE_HEDGE", "instrument": "QQQ", "final_target_hedge_pct": 65.0, "delta_hedge_pct": 35.0, "delta_notional_usd": 35000.0, "status": "EXECUTED", "reason": "defensive"},
    )
    assert "Portfolio Risk Snapshot" in md
    assert "Market Regime Snapshot" in md
    assert "Hedge Recommendation" in md
    assert "INCREASE_HEDGE" in md
    assert "QQQ" in md


def test_hedge_evaluate_command_json_output():
    with patch(
        "cli.common.run_hedging_cycle",
        return_value=(
            {"gross_exposure_usd": 100000.0},
            {"spy_close": 500.0},
            {"market_regime": "BULL", "mode": "BULL"},
            {"status": "EXECUTED", "action": "INCREASE_HEDGE", "instrument": "SPY"},
        ),
    ):
        result = runner.invoke(app, ["hedge-evaluate", "--format", "json"])

    assert result.exit_code == 0
    assert '"hedge_decision"' in result.stdout
    assert '"instrument": "SPY"' in result.stdout


def test_hedge_status_command_json_output(tmp_path):
    state_path = tmp_path / "hedge_state.json"
    orders_path = tmp_path / "hedge_orders.json"
    state_path.write_text(
        '{"current_hedge_pct": 35.0, "last_rebalance_date": "2026-02-07", "last_updated": "2026-02-07T00:00:00Z"}'
    )
    orders_path.write_text(
        '[{"timestamp":"2026-02-07T00:00:00Z","instrument":"SPY","action":"INCREASE_HEDGE","delta_hedge_pct":10.0,"delta_notional_usd":10000.0,"reason":"test"}]'
    )

    result = runner.invoke(
        app,
        [
            "hedge-status",
            "--state-path",
            str(state_path),
            "--orders-path",
            str(orders_path),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    assert '"orders_count": 1' in result.stdout
    assert '"current_hedge_pct": 35.0' in result.stdout
