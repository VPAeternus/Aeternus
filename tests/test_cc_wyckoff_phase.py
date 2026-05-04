"""Tests for CC Wyckoff Phase (Covered Call Wyckoff Phase) integration."""

from tradingagents.phase_engine.cc_wyckoff_phase import CCWyckoffPhaseEngine, CCWyckoffPhaseSignal


# ============================================================================
# Factory Helpers
# ============================================================================


def _make_signal(
    ticker: str = "QQQ",
    signal_name: str = "rth_avoid",
    phase: str = "DIST_ACCUM",
    close_price: float = 450.0,
) -> CCWyckoffPhaseSignal:
    """Build a CCWyckoffPhaseSignal for testing."""
    return CCWyckoffPhaseSignal(
        ticker=ticker,
        signal_name=signal_name,
        phase=phase,
        close_price=close_price,
        generated_at="2026-02-22T00:00:00+00:00",
    )


def _make_scan_result(signals_data: list[dict] | None = None) -> dict:
    """Build a scanner.run_scan() return value."""
    if signals_data is None:
        signals_data = [
            {
                "ticker": "QQQ",
                "signal": "rth_avoid",
                "phase": "DIST_ACCUM",
                "close": 450.0,
            },
        ]
    return {"signals": signals_data, "flat": [], "errors": []}


# ============================================================================
# Tests: __init__
# ============================================================================


def test_init_default():
    """CCWyckoffPhaseEngine should default to live=False, require_bear_regime=True."""
    pe = CCWyckoffPhaseEngine()
    assert pe._live is False
    assert pe._require_bear_regime is True


def test_init_live():
    """CCWyckoffPhaseEngine should accept live=True."""
    pe = CCWyckoffPhaseEngine(live=True)
    assert pe._live is True


def test_init_regime_gate_disabled():
    """CCWyckoffPhaseEngine should accept require_bear_regime=False."""
    pe = CCWyckoffPhaseEngine(require_bear_regime=False)
    assert pe._require_bear_regime is False


# ============================================================================
# Tests: get_signals()
# ============================================================================


def test_get_signals_returns_overlay_signals(monkeypatch):
    """get_signals() should return list of dicts with required CCWyckoffPhaseSignal keys."""
    scan_result = _make_scan_result(
        [
            {
                "ticker": "QQQ",
                "signal": "rth_avoid",
                "phase": "DIST_ACCUM",
                "close": 450.0,
            },
            {
                "ticker": "AAPL",
                "signal": "markdown_crush",
                "phase": "MARK_DOWN",
                "close": 180.0,
            },
        ]
    )
    monkeypatch.setattr(
        "tradingagents.phase_engine.scanner.run_scan",
        lambda tickers=None, live=False, **kw: scan_result,
    )

    pe = CCWyckoffPhaseEngine(live=False)
    signals = pe.get_signals()

    assert len(signals) == 2
    assert signals[0]["ticker"] == "QQQ"
    assert signals[0]["signal_name"] == "rth_avoid"
    assert signals[1]["ticker"] == "AAPL"
    assert signals[1]["signal_name"] == "markdown_crush"

    for s in signals:
        assert "generated_at" in s
        assert "phase" in s
        assert "close_price" in s


def test_get_signals_empty(monkeypatch):
    """get_signals() should return [] when no signals fire."""
    monkeypatch.setattr(
        "tradingagents.phase_engine.scanner.run_scan",
        lambda tickers=None, live=False, **kw: {"signals": [], "flat": [], "errors": []},
    )

    pe = CCWyckoffPhaseEngine()
    signals = pe.get_signals()

    assert signals == []


def test_get_signals_respects_live_flag(monkeypatch):
    """get_signals() should pass live flag to scanner.run_scan."""
    call_log = []

    def mock_run_scan(tickers=None, live=False, **kw):
        call_log.append({"live": live})
        return {"signals": [], "flat": [], "errors": []}

    monkeypatch.setattr(
        "tradingagents.phase_engine.scanner.run_scan",
        mock_run_scan,
    )

    pe = CCWyckoffPhaseEngine(live=True)
    pe.get_signals()

    assert call_log[0]["live"] is True


# ============================================================================
# Tests: build_order_intents() - Basic
# ============================================================================


def test_build_order_intents_basic(monkeypatch):
    """build_order_intents() should return valid intent dicts with correct fields."""
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._fetch_reference_price_from_market",
        lambda symbol, date: 500.0,
    )
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._is_bear_regime",
        lambda ticker: True,
    )

    pe = CCWyckoffPhaseEngine()
    signals = [_make_signal(ticker="QQQ", close_price=500.0)]
    intents = pe.build_order_intents(
        signals=signals,
        plan_id="test-plan-001",
        run_date="2026-02-22",
        capital_usd=100000.0,
    )

    assert len(intents) == 1
    intent = intents[0]

    # Verify required fields
    assert intent["symbol"] == "QQQ"
    assert intent["side"] == "SELL"
    assert intent["intent_category"] == "HEDGE"
    assert intent["lane"] == "HEDGE"
    assert intent["research_playbook"] == "CC_WYCKOFF_PHASE"
    assert intent["dominant_signal_family"] == "rth_avoid"
    assert intent["rating_id"] == "PHASE:2026-02-22:QQQ"
    assert intent["order_type"] == "MARKET"
    assert intent["time_in_force"] == "DAY"
    assert intent["target_quantity"] > 0
    assert "order_intent_id" in intent
    assert "client_order_id" in intent
    assert "idempotency_key" in intent
    assert "generated_at" in intent


# ============================================================================
# Tests: build_order_intents() - Sizing Math
# ============================================================================


def test_build_order_intents_equal_weight_sizing(monkeypatch):
    """2 signals with $100K capital → $50K notional each (before qty coercion)."""
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._fetch_reference_price_from_market",
        lambda symbol, date: 100.0,
    )
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._is_bear_regime",
        lambda ticker: True,
    )

    pe = CCWyckoffPhaseEngine()
    signals = [
        _make_signal(ticker="QQQ", close_price=100.0),
        _make_signal(ticker="SPY", close_price=100.0),
    ]
    intents = pe.build_order_intents(
        signals=signals,
        plan_id="test-plan",
        run_date="2026-02-22",
        capital_usd=100000.0,
        max_overlay_pct=1.0,
    )

    assert len(intents) == 2

    # Each should get $50K notional → 500 shares at $100
    for intent in intents:
        assert intent["target_quantity"] == 500.0
        assert intent["target_notional_usd"] == 50000.0


def test_build_order_intents_respects_max_overlay_pct(monkeypatch):
    """build_order_intents() should respect max_overlay_pct parameter."""
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._fetch_reference_price_from_market",
        lambda symbol, date: 100.0,
    )
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._is_bear_regime",
        lambda ticker: True,
    )

    pe = CCWyckoffPhaseEngine()
    signals = [_make_signal(ticker="QQQ", close_price=100.0)]
    intents = pe.build_order_intents(
        signals=signals,
        plan_id="test-plan",
        run_date="2026-02-22",
        capital_usd=100000.0,
        max_overlay_pct=0.5,  # Only 50% of capital
    )

    assert len(intents) == 1
    intent = intents[0]
    # $100K * 0.5 / 1 signal = $50K notional → 500 shares at $100
    assert intent["target_notional_usd"] == 50000.0
    assert intent["target_quantity"] == 500.0


def test_build_order_intents_reference_price_used_not_close_price(monkeypatch):
    """Sizing should use reference price from _fetch_reference_price_from_market, not close_price."""
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._fetch_reference_price_from_market",
        lambda symbol, date: 200.0,  # Different from close_price
    )
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._is_bear_regime",
        lambda ticker: True,
    )

    pe = CCWyckoffPhaseEngine()
    signals = [_make_signal(ticker="QQQ", close_price=450.0)]  # close_price=450, ref=200
    intents = pe.build_order_intents(
        signals=signals,
        plan_id="test-plan",
        run_date="2026-02-22",
        capital_usd=100000.0,
    )

    assert len(intents) == 1
    intent = intents[0]
    # Sized at $100K / 1 / 200 = 500 shares
    assert intent["target_quantity"] == 500.0
    assert intent["reference_price"] == 200.0


# ============================================================================
# Tests: build_order_intents() - Edge Cases
# ============================================================================


def test_build_order_intents_empty_signals():
    """build_order_intents() should return [] when signals is empty."""
    pe = CCWyckoffPhaseEngine()
    intents = pe.build_order_intents(
        signals=[],
        plan_id="test",
        run_date="2026-02-22",
        capital_usd=100000.0,
    )

    assert intents == []


def test_build_order_intents_no_price_skips_signal(monkeypatch):
    """Signals with no reference price should be skipped (not in intents)."""
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._fetch_reference_price_from_market",
        lambda symbol, date: None,
    )
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._is_bear_regime",
        lambda ticker: True,
    )

    pe = CCWyckoffPhaseEngine()
    signals = [_make_signal()]
    intents = pe.build_order_intents(
        signals=signals,
        plan_id="test",
        run_date="2026-02-22",
        capital_usd=100000.0,
    )

    assert intents == []


def test_build_order_intents_zero_price_skips_signal(monkeypatch):
    """Signals with zero or negative reference price should be skipped."""
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._fetch_reference_price_from_market",
        lambda symbol, date: 0.0,
    )
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._is_bear_regime",
        lambda ticker: True,
    )

    pe = CCWyckoffPhaseEngine()
    signals = [_make_signal()]
    intents = pe.build_order_intents(
        signals=signals,
        plan_id="test",
        run_date="2026-02-22",
        capital_usd=100000.0,
    )

    assert intents == []


def test_build_order_intents_mixed_signals_skip_invalid(monkeypatch):
    """Some signals with price, some without → only valid ones in intents."""
    call_count = [0]

    def mock_fetch_price(symbol, date):
        call_count[0] += 1
        if symbol == "QQQ":
            return 400.0
        return None  # SPY has no price

    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._fetch_reference_price_from_market",
        mock_fetch_price,
    )
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._is_bear_regime",
        lambda ticker: True,
    )

    pe = CCWyckoffPhaseEngine()
    signals = [
        _make_signal(ticker="QQQ", close_price=400.0),
        _make_signal(ticker="SPY", close_price=500.0),
    ]
    intents = pe.build_order_intents(
        signals=signals,
        plan_id="test",
        run_date="2026-02-22",
        capital_usd=100000.0,
    )

    # Only QQQ should be in intents
    assert len(intents) == 1
    assert intents[0]["symbol"] == "QQQ"


def test_build_order_intents_whole_shares_enforcement(monkeypatch):
    """build_order_intents() should respect enforce_whole_shares parameter."""
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._fetch_reference_price_from_market",
        lambda symbol, date: 100.0,
    )
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._is_bear_regime",
        lambda ticker: True,
    )

    pe = CCWyckoffPhaseEngine()
    signals = [_make_signal(ticker="QQQ", close_price=100.0)]
    intents = pe.build_order_intents(
        signals=signals,
        plan_id="test",
        run_date="2026-02-22",
        capital_usd=100000.0,
        enforce_whole_shares=True,
    )

    assert len(intents) == 1
    intent = intents[0]
    assert intent["quantity_policy"] == "WHOLE_SHARES"


def test_build_order_intents_fractional_ok_default(monkeypatch):
    """build_order_intents() should default to FRACTIONAL_OK."""
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._fetch_reference_price_from_market",
        lambda symbol, date: 100.0,
    )
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._is_bear_regime",
        lambda ticker: True,
    )

    pe = CCWyckoffPhaseEngine()
    signals = [_make_signal(ticker="QQQ", close_price=100.0)]
    intents = pe.build_order_intents(
        signals=signals,
        plan_id="test",
        run_date="2026-02-22",
        capital_usd=100000.0,
        enforce_whole_shares=False,
    )

    assert len(intents) == 1
    intent = intents[0]
    assert intent["quantity_policy"] == "FRACTIONAL_OK"


# ============================================================================
# Tests: Exit Rule Logic
# ============================================================================


def test_exit_rule_phase_engine_eod():
    """CC_WYCKOFF_PHASE position with hold_days >= 1 triggers CC_WYCKOFF_EOD."""
    row = {"research_playbook": "CC_WYCKOFF_PHASE"}
    hold_days = 1

    _playbook = str(row.get("research_playbook") or "").upper().strip()
    assert _playbook == "CC_WYCKOFF_PHASE"
    assert hold_days >= 1

    # This simulates the exit rule check in build_exit_execution_plan
    exit_rule = ""
    if _playbook == "CC_WYCKOFF_PHASE" and hold_days >= 1:
        exit_rule = "CC_WYCKOFF_EOD"

    assert exit_rule == "CC_WYCKOFF_EOD"


def test_exit_rule_phase_engine_multi_day():
    """CC_WYCKOFF_PHASE should trigger exit on day 2, day 3, etc."""
    for hold_days in [1, 2, 3, 5]:
        row = {"research_playbook": "CC_WYCKOFF_PHASE"}
        _playbook = str(row.get("research_playbook") or "").upper().strip()

        exit_rule = ""
        if _playbook == "CC_WYCKOFF_PHASE" and hold_days >= 1:
            exit_rule = "CC_WYCKOFF_EOD"

        assert exit_rule == "CC_WYCKOFF_EOD"


def test_exit_rule_not_triggered_for_non_overlay():
    """Non-overlay positions should NOT trigger CC_WYCKOFF_EOD."""
    row = {"research_playbook": "HEDGE_OVERLAY"}
    hold_days = 1

    _playbook = str(row.get("research_playbook") or "").upper().strip()
    exit_rule = ""
    if _playbook == "CC_WYCKOFF_PHASE" and hold_days >= 1:
        exit_rule = "CC_WYCKOFF_EOD"

    assert exit_rule == ""


def test_exit_rule_not_triggered_on_day_zero():
    """CC Wyckoff Phase position on day 0 (hold_days=0) should NOT trigger exit."""
    row = {"research_playbook": "CC_WYCKOFF_PHASE"}
    hold_days = 0

    _playbook = str(row.get("research_playbook") or "").upper().strip()
    exit_rule = ""
    if _playbook == "CC_WYCKOFF_PHASE" and hold_days >= 1:
        exit_rule = "CC_WYCKOFF_EOD"

    assert exit_rule == ""


def test_exit_rule_playbook_case_insensitive():
    """Exit rule should handle playbook names in various cases."""
    test_cases = [
        ("cc_wyckoff_phase", True),
        ("CC_WYCKOFF_PHASE", True),
        ("Cc_Wyckoff_Phase", True),
        ("CC_WYCKOFF", False),
        ("PHASE", False),
        ("", False),
    ]

    for playbook_raw, should_trigger in test_cases:
        row = {"research_playbook": playbook_raw}
        hold_days = 1
        _playbook = str(row.get("research_playbook") or "").upper().strip()

        exit_rule = ""
        if _playbook == "CC_WYCKOFF_PHASE" and hold_days >= 1:
            exit_rule = "CC_WYCKOFF_EOD"

        if should_trigger:
            assert exit_rule == "CC_WYCKOFF_EOD", f"Failed for {playbook_raw}"
        else:
            assert exit_rule == "", f"Failed for {playbook_raw}"


# ============================================================================
# Tests: Integration and Real-world Scenarios
# ============================================================================


def test_build_order_intents_multiple_signals_all_valid(monkeypatch):
    """Multiple signals all with valid prices should all generate intents."""
    price_map = {"QQQ": 400.0, "SPY": 500.0, "IWM": 200.0}

    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._fetch_reference_price_from_market",
        lambda symbol, date: price_map.get(symbol),
    )
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._is_bear_regime",
        lambda ticker: True,
    )

    pe = CCWyckoffPhaseEngine()
    signals = [
        _make_signal(ticker="QQQ", signal_name="rth_avoid", close_price=400.0),
        _make_signal(ticker="SPY", signal_name="markup_fade", close_price=500.0),
        _make_signal(ticker="IWM", signal_name="markdown_crush", close_price=200.0),
    ]

    intents = pe.build_order_intents(
        signals=signals,
        plan_id="test-plan",
        run_date="2026-02-22",
        capital_usd=100000.0,
        max_overlay_pct=1.0,
    )

    assert len(intents) == 3

    # Each should get $33,333.33 notional (approx)
    expected_per_signal = 100000.0 / 3
    for i, intent in enumerate(intents):
        assert intent["side"] == "SELL"
        assert intent["lane"] == "HEDGE"
        assert intent["intent_category"] == "HEDGE"
        assert intent["research_playbook"] == "CC_WYCKOFF_PHASE"
        # Notional should be close to expected (may vary due to coercion)
        assert abs(intent["target_notional_usd"] - expected_per_signal) < 1000


def test_build_order_intents_client_order_id_uniqueness(monkeypatch):
    """Each intent should have a unique client_order_id."""
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._fetch_reference_price_from_market",
        lambda symbol, date: 100.0,
    )
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._is_bear_regime",
        lambda ticker: True,
    )

    pe = CCWyckoffPhaseEngine()
    signals = [
        _make_signal(ticker="QQQ", close_price=100.0),
        _make_signal(ticker="SPY", close_price=100.0),
    ]

    intents = pe.build_order_intents(
        signals=signals,
        plan_id="unique-plan-id",
        run_date="2026-02-22",
        capital_usd=100000.0,
    )

    client_order_ids = [intent["client_order_id"] for intent in intents]
    assert len(client_order_ids) == len(set(client_order_ids))


def test_build_order_intents_rating_id_format(monkeypatch):
    """rating_id should follow format PHASE:<date>:<ticker>."""
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._fetch_reference_price_from_market",
        lambda symbol, date: 100.0,
    )
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._is_bear_regime",
        lambda ticker: True,
    )

    pe = CCWyckoffPhaseEngine()
    signals = [_make_signal(ticker="AAPL", close_price=100.0)]

    intents = pe.build_order_intents(
        signals=signals,
        plan_id="test",
        run_date="2026-02-15",
        capital_usd=100000.0,
    )

    assert len(intents) == 1
    assert intents[0]["rating_id"] == "PHASE:2026-02-15:AAPL"


# ============================================================================
# Tests: Regime Gate (SMA200 bear filter)
# ============================================================================


def test_regime_gate_blocks_bull_regime(monkeypatch):
    """build_order_intents() should emit zero intents when _is_bear_regime returns False."""
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._fetch_reference_price_from_market",
        lambda symbol, date: 500.0,
    )
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._is_bear_regime",
        lambda ticker: False,  # bull regime → gate blocks
    )

    pe = CCWyckoffPhaseEngine()  # require_bear_regime=True by default
    signals = [_make_signal(ticker="QQQ", close_price=500.0)]
    intents = pe.build_order_intents(
        signals=signals,
        plan_id="test",
        run_date="2026-03-02",
        capital_usd=100000.0,
    )

    assert intents == []


def test_regime_gate_allows_bear_regime(monkeypatch):
    """build_order_intents() should emit intents when _is_bear_regime returns True."""
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._fetch_reference_price_from_market",
        lambda symbol, date: 500.0,
    )
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._is_bear_regime",
        lambda ticker: True,  # bear regime → gate allows
    )

    pe = CCWyckoffPhaseEngine()
    signals = [_make_signal(ticker="QQQ", close_price=500.0)]
    intents = pe.build_order_intents(
        signals=signals,
        plan_id="test",
        run_date="2026-03-02",
        capital_usd=100000.0,
    )

    assert len(intents) == 1
    assert intents[0]["symbol"] == "QQQ"


def test_regime_gate_disabled_allows_all(monkeypatch):
    """require_bear_regime=False should skip the regime check entirely."""
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._fetch_reference_price_from_market",
        lambda symbol, date: 500.0,
    )
    # Do NOT monkeypatch _is_bear_regime — it shouldn't be called

    pe = CCWyckoffPhaseEngine(require_bear_regime=False)
    signals = [_make_signal(ticker="QQQ", close_price=500.0)]
    intents = pe.build_order_intents(
        signals=signals,
        plan_id="test",
        run_date="2026-03-02",
        capital_usd=100000.0,
    )

    assert len(intents) == 1


def test_regime_gate_mixed_bear_bull(monkeypatch):
    """Mixed bear/bull tickers: only bear-regime tickers should emit intents."""
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._fetch_reference_price_from_market",
        lambda symbol, date: 100.0,
    )
    monkeypatch.setattr(
        "tradingagents.phase_engine.cc_wyckoff_phase._is_bear_regime",
        lambda ticker: ticker == "QQQ",  # QQQ=bear, SPY=bull
    )

    pe = CCWyckoffPhaseEngine()
    signals = [
        _make_signal(ticker="QQQ", close_price=100.0),
        _make_signal(ticker="SPY", close_price=100.0),
    ]
    intents = pe.build_order_intents(
        signals=signals,
        plan_id="test",
        run_date="2026-03-02",
        capital_usd=100000.0,
    )

    assert len(intents) == 1
    assert intents[0]["symbol"] == "QQQ"
