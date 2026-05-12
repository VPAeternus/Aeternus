import json
from datetime import datetime

from tradingagents.graph.hedging import (
    AdaptiveHedgeEngine,
    BEAR_BASE_HEDGE_PCT,
    S7_BOOST_PCT,
    S7_ONLY_HEDGE_PCT,
    MAX_HEDGE_PCT,
)


def _portfolio(
    gross=1000.0,
    current=0.0,
    beta=1.0,
    var=2.0,
    drawdown=0.0,
    tech=0.0,
):
    return {
        "timestamp": datetime.now().isoformat(),
        "gross_exposure_usd": gross,
        "net_exposure_usd": gross,
        "portfolio_beta_60d": beta,
        "var_95_1d_pct_nav": var,
        "drawdown_20d_pct": drawdown,
        "tech_concentration_pct": tech,
        "current_hedge_pct": current,
    }


def _market(
    spy_close,
    spy_sma200=90.0,
    spy_sma200_5d_ago=89.0,
    vix=17.0,
    qqq_close=None,
    qqq_sma200=None,
    qqq_sma200_5d_ago=None,
):
    qqq_close = spy_close if qqq_close is None else qqq_close
    qqq_sma200 = spy_sma200 if qqq_sma200 is None else qqq_sma200
    qqq_sma200_5d_ago = spy_sma200_5d_ago if qqq_sma200_5d_ago is None else qqq_sma200_5d_ago
    return {
        "timestamp": datetime.now().isoformat(),
        "spy_close": spy_close,
        "spy_sma20": 100.0,
        "spy_sma200": spy_sma200,
        "spy_sma200_5d_ago": spy_sma200_5d_ago,
        "spy_deviation_pct": 0.0,
        "qqq_close": qqq_close,
        "qqq_sma20": 100.0,
        "qqq_sma200": qqq_sma200,
        "qqq_sma200_5d_ago": qqq_sma200_5d_ago,
        "qqq_deviation_pct": 0.0,
        "vix_close": vix,
    }


# ── Bull regime: 0% hedge ────────────────────────────────────────────────────

def test_bull_regime_zero_hedge(tmp_path):
    engine = AdaptiveHedgeEngine(
        state_path=str(tmp_path / "hedge_state.json"),
        orders_path=str(tmp_path / "hedge_orders.json"),
    )
    p = _portfolio()
    # spy_close=95 > spy_sma200=90 → bull
    signal = engine.compute_hedge_signal(p, _market(spy_close=95.0))
    assert signal["bear_trigger_active"] is False
    assert signal["target_hedge_pct_pre_hysteresis"] == 0.0
    assert signal["mode"] == "BULL"
    assert signal["market_regime"] == "BULL"


def test_bull_high_vix_still_zero_hedge(tmp_path):
    engine = AdaptiveHedgeEngine(
        state_path=str(tmp_path / "hedge_state.json"),
        orders_path=str(tmp_path / "hedge_orders.json"),
    )
    p = _portfolio()
    # Above SMA200 but high VIX → still bull, 0% hedge
    signal = engine.compute_hedge_signal(p, _market(spy_close=95.0, vix=35.0))
    assert signal["target_hedge_pct_pre_hysteresis"] == 0.0
    assert signal["mode"] == "BULL"


def test_default_s7_only_policy_has_no_plain_bear_hedge(tmp_path):
    engine = AdaptiveHedgeEngine(
        state_path=str(tmp_path / "hedge_state.json"),
        orders_path=str(tmp_path / "hedge_orders.json"),
    )
    p = _portfolio()
    signal = engine.compute_hedge_signal(p, _market(spy_close=80.0), s7_active=False)
    assert signal["bear_trigger_active"] is True
    assert signal["target_hedge_pct_pre_hysteresis"] == 0.0
    assert signal["mode"] == "S7_STANDBY"


def test_default_s7_only_policy_targets_100_pct_when_s7_active(tmp_path):
    engine = AdaptiveHedgeEngine(
        state_path=str(tmp_path / "hedge_state.json"),
        orders_path=str(tmp_path / "hedge_orders.json"),
    )
    p = _portfolio()
    signal = engine.compute_hedge_signal(p, _market(spy_close=80.0), s7_active=True)
    assert signal["target_hedge_pct_pre_hysteresis"] == 100.0
    assert signal["s7_boost_pct"] == 100.0
    assert signal["mode"] == "S7_HEDGE"
    assert signal["hedge_gate_symbol"] == "QQQ"
    assert signal["s7_source_symbol"] == "SPY"


def test_default_s7_only_policy_uses_qqq_gate_not_spy_gate(tmp_path):
    engine = AdaptiveHedgeEngine(
        state_path=str(tmp_path / "hedge_state.json"),
        orders_path=str(tmp_path / "hedge_orders.json"),
    )
    p = _portfolio()

    spy_bear_qqq_bull = engine.compute_hedge_signal(
        p,
        _market(spy_close=80.0, spy_sma200=90.0, qqq_close=100.0, qqq_sma200=90.0),
        s7_active=True,
    )
    assert spy_bear_qqq_bull["bear_trigger_active"] is False
    assert spy_bear_qqq_bull["target_hedge_pct_pre_hysteresis"] == 0.0
    assert spy_bear_qqq_bull["mode"] == "BULL"

    spy_bull_qqq_bear = engine.compute_hedge_signal(
        p,
        _market(spy_close=100.0, spy_sma200=90.0, qqq_close=80.0, qqq_sma200=90.0),
        s7_active=True,
    )
    assert spy_bull_qqq_bear["bear_trigger_active"] is True
    assert spy_bull_qqq_bear["target_hedge_pct_pre_hysteresis"] == S7_ONLY_HEDGE_PCT
    assert spy_bull_qqq_bear["mode"] == "S7_HEDGE"


# ── Bear regime: configurable policy ─────────────────────────────────────────

def test_legacy_bear_base_policy_still_available_for_ab_test(tmp_path):
    engine = AdaptiveHedgeEngine(
        state_path=str(tmp_path / "hedge_state.json"),
        orders_path=str(tmp_path / "hedge_orders.json"),
        hedge_policy="bear_base",
    )
    p = _portfolio()
    # spy_close=80 < spy_sma200=90 → bear
    signal = engine.compute_hedge_signal(p, _market(spy_close=80.0))
    assert signal["bear_trigger_active"] is True
    assert signal["target_hedge_pct_pre_hysteresis"] == BEAR_BASE_HEDGE_PCT
    assert signal["mode"] == "BEAR"


def test_env_can_select_legacy_policy_for_ab_test(tmp_path, monkeypatch):
    monkeypatch.setenv("AETERNUS_HEDGE_POLICY", "bear_base")
    engine = AdaptiveHedgeEngine(
        state_path=str(tmp_path / "hedge_state.json"),
        orders_path=str(tmp_path / "hedge_orders.json"),
    )
    signal = engine.compute_hedge_signal(_portfolio(), _market(spy_close=80.0))
    assert signal["target_hedge_pct_pre_hysteresis"] == BEAR_BASE_HEDGE_PCT
    assert signal["mode"] == "BEAR"


def test_legacy_bear_stress_regime(tmp_path):
    engine = AdaptiveHedgeEngine(
        state_path=str(tmp_path / "hedge_state.json"),
        orders_path=str(tmp_path / "hedge_orders.json"),
        hedge_policy="bear_base",
    )
    p = _portfolio()
    signal = engine.compute_hedge_signal(p, _market(spy_close=80.0, vix=30.0))
    assert signal["market_regime"] == "BEAR_STRESS"
    assert signal["target_hedge_pct_pre_hysteresis"] == BEAR_BASE_HEDGE_PCT


# ── S7 hedge: 100% default ───────────────────────────────────────────────────

def test_s7_only_policy_uses_100_pct_s7_hedge(tmp_path):
    engine = AdaptiveHedgeEngine(
        state_path=str(tmp_path / "hedge_state.json"),
        orders_path=str(tmp_path / "hedge_orders.json"),
    )
    p = _portfolio()
    signal = engine.compute_hedge_signal(p, _market(spy_close=80.0), s7_active=True)
    assert signal["s7_boost_pct"] == S7_ONLY_HEDGE_PCT
    assert signal["target_hedge_pct_pre_hysteresis"] == S7_ONLY_HEDGE_PCT
    assert signal["mode"] == "S7_HEDGE"


def test_s7_no_boost_in_bull(tmp_path):
    engine = AdaptiveHedgeEngine(
        state_path=str(tmp_path / "hedge_state.json"),
        orders_path=str(tmp_path / "hedge_orders.json"),
    )
    p = _portfolio()
    # Bull regime — s7_active is irrelevant
    signal = engine.compute_hedge_signal(p, _market(spy_close=95.0), s7_active=True)
    assert signal["target_hedge_pct_pre_hysteresis"] == 0.0
    assert signal["mode"] == "BULL"


# ── Crash trigger: 150% cap ──────────────────────────────────────────────────

def test_legacy_crash_trigger_activates(tmp_path):
    engine = AdaptiveHedgeEngine(
        state_path=str(tmp_path / "hedge_state.json"),
        orders_path=str(tmp_path / "hedge_orders.json"),
        hedge_policy="bear_base",
    )
    p = _portfolio(beta=1.2, var=3.5, drawdown=6.0)
    signal = engine.compute_hedge_signal(
        p,
        _market(spy_close=80.0, spy_sma200=90.0, spy_sma200_5d_ago=91.0, vix=31.0),
    )
    assert signal["crash_trigger_active"] is True
    assert signal["mode"] == "CRASH"
    assert signal["target_hedge_pct_pre_hysteresis"] == MAX_HEDGE_PCT


def test_legacy_crash_trigger_blocked_when_one_condition_fails(tmp_path):
    engine = AdaptiveHedgeEngine(
        state_path=str(tmp_path / "hedge_state.json"),
        orders_path=str(tmp_path / "hedge_orders.json"),
        hedge_policy="bear_base",
    )
    # drawdown=4.0 < 5.0 threshold → crash blocked
    p = _portfolio(beta=1.2, var=3.5, drawdown=4.0)
    signal = engine.compute_hedge_signal(
        p,
        _market(spy_close=80.0, spy_sma200=90.0, spy_sma200_5d_ago=91.0, vix=31.0),
    )
    assert signal["crash_trigger_active"] is False
    assert signal["mode"] == "BEAR"


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_data_insufficient_returns_safe_noop(tmp_path):
    engine = AdaptiveHedgeEngine(
        state_path=str(tmp_path / "hedge_state.json"),
        orders_path=str(tmp_path / "hedge_orders.json"),
    )
    p = _portfolio(gross=1000.0)
    signal = engine.compute_hedge_signal(p, None)
    decision = engine.decide_hedge(signal, p)
    assert decision["status"] == "DATA_INSUFFICIENT"
    assert decision["action"] == "NO_CHANGE"


def test_no_positions_returns_no_positions_status(tmp_path):
    engine = AdaptiveHedgeEngine(
        state_path=str(tmp_path / "hedge_state.json"),
        orders_path=str(tmp_path / "hedge_orders.json"),
    )
    p = _portfolio(gross=0.0)
    signal = engine.compute_hedge_signal(p, _market(102.0))
    decision = engine.decide_hedge(signal, p)
    assert decision["status"] == "NO_POSITIONS"
    assert decision["final_target_hedge_pct"] == 0.0


def test_hysteresis_skip_under_5pct(tmp_path):
    engine = AdaptiveHedgeEngine(
        state_path=str(tmp_path / "hedge_state.json"),
        orders_path=str(tmp_path / "hedge_orders.json"),
    )
    p = _portfolio(current=82.0, gross=1000.0)
    signal = {
        "base_hedge_pct": 85.0,
        "s7_boost_pct": 0.0,
        "bear_trigger_active": True,
        "crash_trigger_active": False,
        "target_hedge_pct_pre_hysteresis": 85.0,
        "mode": "BEAR",
        "data_sufficient": True,
    }
    decision = engine.decide_hedge(signal, p)
    assert decision["status"] == "SKIPPED_HYSTERESIS"
    assert decision["action"] == "NO_CHANGE"


def test_instrument_selection_qqq_for_tech_heavy(tmp_path):
    engine = AdaptiveHedgeEngine(
        state_path=str(tmp_path / "hedge_state.json"),
        orders_path=str(tmp_path / "hedge_orders.json"),
    )
    p = _portfolio(current=0.0, gross=1000.0, tech=60.0)
    signal = {
        "base_hedge_pct": 85.0,
        "s7_boost_pct": 0.0,
        "bear_trigger_active": True,
        "crash_trigger_active": False,
        "target_hedge_pct_pre_hysteresis": 85.0,
        "mode": "BEAR",
        "data_sufficient": True,
    }
    decision = engine.decide_hedge(signal, p)
    assert decision["status"] == "EXECUTED"
    assert decision["instrument"] == "QQQ"
    assert decision["action"] == "INCREASE_HEDGE"


def test_instrument_selection_spy_for_non_tech(tmp_path):
    engine = AdaptiveHedgeEngine(
        state_path=str(tmp_path / "hedge_state.json"),
        orders_path=str(tmp_path / "hedge_orders.json"),
    )
    p = _portfolio(current=0.0, gross=1000.0, tech=30.0)
    signal = {
        "base_hedge_pct": 85.0,
        "s7_boost_pct": 0.0,
        "bear_trigger_active": True,
        "crash_trigger_active": False,
        "target_hedge_pct_pre_hysteresis": 85.0,
        "mode": "BEAR",
        "data_sufficient": True,
    }
    decision = engine.decide_hedge(signal, p)
    assert decision["instrument"] == "SPY"


def test_cooldown_blocks_same_day_non_emergency(tmp_path):
    state_path = tmp_path / "hedge_state.json"
    orders_path = tmp_path / "hedge_orders.json"
    engine = AdaptiveHedgeEngine(
        state_path=str(state_path),
        orders_path=str(orders_path),
    )

    today = datetime.now().strftime("%Y-%m-%d")
    state_path.write_text(
        json.dumps({
            "current_hedge_pct": 20.0,
            "last_rebalance_date": today,
            "last_updated": datetime.now().isoformat(),
        })
    )

    p = _portfolio(current=20.0, gross=1000.0)
    signal = {
        "base_hedge_pct": 85.0,
        "s7_boost_pct": 0.0,
        "bear_trigger_active": True,
        "crash_trigger_active": False,
        "target_hedge_pct_pre_hysteresis": 85.0,
        "mode": "BEAR",
        "data_sufficient": True,
    }
    decision = engine.decide_hedge(signal, p)
    assert decision["status"] == "SKIPPED_HYSTERESIS"
    assert decision["action"] == "NO_CHANGE"


def test_legacy_evaluate_persists_state_and_order(tmp_path):
    state_path = tmp_path / "hedge_state.json"
    orders_path = tmp_path / "hedge_orders.json"
    engine = AdaptiveHedgeEngine(
        state_path=str(state_path),
        orders_path=str(orders_path),
        hedge_policy="bear_base",
    )

    # Legacy bear-base mode → should execute 85% hedge
    p = _portfolio(current=0.0, gross=1000.0, tech=40.0)
    signal, decision, order = engine.evaluate(p, _market(spy_close=80.0, vix=26.0))

    assert signal["target_hedge_pct_pre_hysteresis"] == BEAR_BASE_HEDGE_PCT
    assert decision["status"] == "EXECUTED"
    assert order is not None

    state = json.loads(state_path.read_text())
    orders = json.loads(orders_path.read_text())

    assert state["current_hedge_pct"] == decision["final_target_hedge_pct"]
    assert len(orders) == 1


def test_evaluate_with_s7_hedge(tmp_path):
    state_path = tmp_path / "hedge_state.json"
    orders_path = tmp_path / "hedge_orders.json"
    engine = AdaptiveHedgeEngine(
        state_path=str(state_path),
        orders_path=str(orders_path),
    )

    p = _portfolio(current=0.0, gross=1000.0, tech=60.0)
    signal, decision, order = engine.evaluate(p, _market(spy_close=80.0), s7_active=True)

    assert signal["target_hedge_pct_pre_hysteresis"] == S7_ONLY_HEDGE_PCT
    assert signal["mode"] == "S7_HEDGE"
    assert decision["status"] == "EXECUTED"
    assert order is not None


def test_constants_match_backtest_config():
    """Verify constants match default S7-only policy and legacy A/B policy."""
    assert S7_ONLY_HEDGE_PCT == 100.0
    assert BEAR_BASE_HEDGE_PCT == 85.0
    assert S7_BOOST_PCT == 75.0
    assert MAX_HEDGE_PCT == 150.0
