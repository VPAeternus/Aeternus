"""Tests for cc_csp_roll_monitor.py — all external calls mocked."""

import datetime
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tradingagents.graph.cc_csp_roll_monitor import (
    RollDecision,
    add_position,
    close_position,
    evaluate_position,
    load_positions,
    save_positions,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_calls_row(strike: float, bid: float, ask: float) -> pd.DataFrame:
    return pd.DataFrame([{"strike": strike, "bid": bid, "ask": ask}])


def _make_puts_row(strike: float, bid: float, ask: float) -> pd.DataFrame:
    return pd.DataFrame([{"strike": strike, "bid": bid, "ask": ask}])


def _mock_chain(calls_df: pd.DataFrame, puts_df: pd.DataFrame):
    """Build a fake option_chain() return value."""
    chain = SimpleNamespace(calls=calls_df, puts=puts_df)
    return chain


def _make_ticker_mock(price: float, chain):
    """Build a mock yf.Ticker that returns *price* and *chain*."""
    tkr = MagicMock()
    tkr.fast_info.last_price = price
    tkr.fast_info.previous_close = price
    tkr.option_chain.return_value = chain
    return tkr


def _cc_pos(strike=600.0, credit=3.50, expiry="2099-12-31") -> dict:
    return {
        "id": "test01",
        "type": "cc",
        "ticker": "QQQ",
        "strike": strike,
        "expiry": expiry,
        "credit_received": credit,
        "contracts": 1,
        "status": "active",
    }


def _csp_pos(strike=580.0, credit=2.80, expiry="2099-12-31") -> dict:
    return {
        "id": "test02",
        "type": "csp",
        "ticker": "QQQ",
        "strike": strike,
        "expiry": expiry,
        "credit_received": credit,
        "contracts": 1,
        "status": "active",
    }


# ---------------------------------------------------------------------------
# Test 1: CC HOLD OTM — price below strike
# ---------------------------------------------------------------------------
def test_cc_hold_otm():
    calls = _make_calls_row(600.0, bid=1.80, ask=2.00)
    puts = _make_puts_row(600.0, bid=0.10, ask=0.20)
    chain = _mock_chain(calls, puts)
    pos = _cc_pos(strike=600.0, credit=3.50)

    with (
        patch("tradingagents.graph.cc_csp_roll_monitor.yf.Ticker", return_value=_make_ticker_mock(594.0, chain)),
        patch("tradingagents.graph.cc_csp_roll_monitor._session_minutes_remaining", return_value=300),
    ):
        result = evaluate_position(pos)

    assert result.decision == RollDecision.CC_HOLD_OTM
    assert result.underlying_price == pytest.approx(594.0)
    assert result.option_mark == pytest.approx(1.90)
    assert result.pct_captured == pytest.approx((3.50 - 1.90) / 3.50, rel=1e-3)


# ---------------------------------------------------------------------------
# Test 2: CC CLOSE EARLY — ≥75% captured
# ---------------------------------------------------------------------------
def test_cc_close_early():
    # mark = 0.50, credit = 3.50 → 85.7% captured
    calls = _make_calls_row(600.0, bid=0.40, ask=0.60)
    puts = _make_puts_row(600.0, bid=0.10, ask=0.20)
    chain = _mock_chain(calls, puts)
    pos = _cc_pos(strike=600.0, credit=3.50)

    with (
        patch("tradingagents.graph.cc_csp_roll_monitor.yf.Ticker", return_value=_make_ticker_mock(595.0, chain)),
        patch("tradingagents.graph.cc_csp_roll_monitor._session_minutes_remaining", return_value=300),
    ):
        result = evaluate_position(pos)

    assert result.decision == RollDecision.CC_CLOSE_EARLY
    assert result.pct_captured >= 0.75


# ---------------------------------------------------------------------------
# Test 3: CC WATCH ITM — price above strike, extrinsic > 10% of credit
# ---------------------------------------------------------------------------
def test_cc_watch_itm():
    # S=605, K=600 → intrinsic=5.0, mark=5.80 → extrinsic=0.80 > 0.35 (10% of 3.50)
    calls = _make_calls_row(600.0, bid=5.60, ask=6.00)
    puts = _make_puts_row(600.0, bid=0.10, ask=0.20)
    chain = _mock_chain(calls, puts)
    pos = _cc_pos(strike=600.0, credit=3.50)

    with (
        patch("tradingagents.graph.cc_csp_roll_monitor.yf.Ticker", return_value=_make_ticker_mock(605.0, chain)),
        patch("tradingagents.graph.cc_csp_roll_monitor._session_minutes_remaining", return_value=300),
    ):
        result = evaluate_position(pos)

    assert result.decision == RollDecision.CC_WATCH_ITM
    assert result.intrinsic == pytest.approx(5.0)
    assert result.extrinsic > 0.10 * 3.50


# ---------------------------------------------------------------------------
# Test 4: CC ROLL UP — ITM, extrinsic < 10%, 120 min left
# ---------------------------------------------------------------------------
def test_cc_roll_up():
    # S=608.66, K=600, intrinsic=8.66, mark=8.70 → extrinsic=0.04 < 0.35
    # Roll target ≥ 608.66 * 1.02 = 620.83 → use strike 625
    calls = pd.DataFrame([
        {"strike": 600.0, "bid": 8.50, "ask": 8.90},
        {"strike": 625.0, "bid": 2.20, "ask": 2.40},
    ])
    puts = _make_puts_row(600.0, bid=0.10, ask=0.20)
    chain = _mock_chain(calls, puts)
    pos = _cc_pos(strike=600.0, credit=3.50)

    with (
        patch("tradingagents.graph.cc_csp_roll_monitor.yf.Ticker", return_value=_make_ticker_mock(608.66, chain)),
        patch("tradingagents.graph.cc_csp_roll_monitor._session_minutes_remaining", return_value=120),
    ):
        result = evaluate_position(pos)

    assert result.decision == RollDecision.CC_ROLL_UP
    assert result.roll_target_strike == 625.0
    assert result.roll_net_debit is not None  # buy at 8.90, sell at 2.20 → debit 6.70


# ---------------------------------------------------------------------------
# Test 5: CC ACCEPT ASSIGNMENT — ITM, 45 min to close
# ---------------------------------------------------------------------------
def test_cc_accept_assignment():
    calls = _make_calls_row(600.0, bid=8.50, ask=8.90)
    puts = _make_puts_row(600.0, bid=0.10, ask=0.20)
    chain = _mock_chain(calls, puts)
    pos = _cc_pos(strike=600.0, credit=3.50)

    with (
        patch("tradingagents.graph.cc_csp_roll_monitor.yf.Ticker", return_value=_make_ticker_mock(608.66, chain)),
        patch("tradingagents.graph.cc_csp_roll_monitor._session_minutes_remaining", return_value=45),
    ):
        result = evaluate_position(pos)

    assert result.decision == RollDecision.CC_ACCEPT_ASSIGNMENT
    assert "603.50" in result.rationale  # effective sale = 600 + 3.50


# ---------------------------------------------------------------------------
# Test 6: CSP HOLD OTM — price 10% above put strike
# ---------------------------------------------------------------------------
def test_csp_hold_otm():
    calls = _make_calls_row(580.0, bid=0.10, ask=0.20)
    puts = _make_puts_row(580.0, bid=1.20, ask=1.40)
    chain = _mock_chain(calls, puts)
    pos = _csp_pos(strike=580.0, credit=2.80)

    with (
        patch("tradingagents.graph.cc_csp_roll_monitor.yf.Ticker", return_value=_make_ticker_mock(638.0, chain)),
        patch("tradingagents.graph.cc_csp_roll_monitor._session_minutes_remaining", return_value=300),
    ):
        result = evaluate_position(pos)

    assert result.decision == RollDecision.CSP_HOLD_OTM


# ---------------------------------------------------------------------------
# Test 7: CSP CLOSE EARLY — 85% captured
# ---------------------------------------------------------------------------
def test_csp_close_early():
    # mark = 0.42, credit = 2.80 → 85% captured
    calls = _make_calls_row(580.0, bid=0.10, ask=0.20)
    puts = _make_puts_row(580.0, bid=0.35, ask=0.49)
    chain = _mock_chain(calls, puts)
    pos = _csp_pos(strike=580.0, credit=2.80)

    with (
        patch("tradingagents.graph.cc_csp_roll_monitor.yf.Ticker", return_value=_make_ticker_mock(600.0, chain)),
        patch("tradingagents.graph.cc_csp_roll_monitor._session_minutes_remaining", return_value=300),
    ):
        result = evaluate_position(pos)

    assert result.decision == RollDecision.CSP_CLOSE_EARLY
    assert result.pct_captured >= 0.80


# ---------------------------------------------------------------------------
# Test 8: CSP WATCH APPROACH — price within 1% above put strike
# ---------------------------------------------------------------------------
def test_csp_watch_approach():
    # strike=580, price=583.5 → within 1% (580 * 0.99 = 574.2 < 583.5 < 580 fails: 583.5 > 580 so NOT itm)
    # near_strike: K*0.99 < S < K → 574.2 < S < 580
    calls = _make_calls_row(580.0, bid=0.10, ask=0.20)
    puts = _make_puts_row(580.0, bid=1.80, ask=2.00)
    chain = _mock_chain(calls, puts)
    pos = _csp_pos(strike=580.0, credit=2.80)

    with (
        patch("tradingagents.graph.cc_csp_roll_monitor.yf.Ticker", return_value=_make_ticker_mock(577.0, chain)),
        patch("tradingagents.graph.cc_csp_roll_monitor._session_minutes_remaining", return_value=300),
    ):
        result = evaluate_position(pos)

    assert result.decision == RollDecision.CSP_WATCH_APPROACH


# ---------------------------------------------------------------------------
# Test 9: CSP ROLL DOWN — price below strike, 120 min left
# ---------------------------------------------------------------------------
def test_csp_roll_down():
    # S=572, K=580 → ITM. Roll target ≤ 572*0.95 = 543.4 → use 540
    calls = _make_calls_row(580.0, bid=0.10, ask=0.20)
    puts = pd.DataFrame([
        {"strike": 580.0, "bid": 8.50, "ask": 8.90},
        {"strike": 540.0, "bid": 1.80, "ask": 2.00},
    ])
    chain = _mock_chain(calls, puts)
    pos = _csp_pos(strike=580.0, credit=2.80)

    with (
        patch("tradingagents.graph.cc_csp_roll_monitor.yf.Ticker", return_value=_make_ticker_mock(572.0, chain)),
        patch("tradingagents.graph.cc_csp_roll_monitor._session_minutes_remaining", return_value=120),
    ):
        result = evaluate_position(pos)

    assert result.decision == RollDecision.CSP_ROLL_DOWN
    assert result.roll_target_strike == 540.0
    assert result.roll_net_debit is not None


# ---------------------------------------------------------------------------
# Test 10: Strike not in chain → DATA_UNAVAILABLE
# ---------------------------------------------------------------------------
def test_strike_not_in_chain():
    # Chain only has strike 605, but position strike is 600
    calls = _make_calls_row(605.0, bid=2.00, ask=2.20)
    puts = _make_puts_row(605.0, bid=2.00, ask=2.20)
    chain = _mock_chain(calls, puts)
    pos = _cc_pos(strike=600.0, credit=3.50)

    with (
        patch("tradingagents.graph.cc_csp_roll_monitor.yf.Ticker", return_value=_make_ticker_mock(608.0, chain)),
        patch("tradingagents.graph.cc_csp_roll_monitor._session_minutes_remaining", return_value=300),
    ):
        result = evaluate_position(pos)

    assert result.decision == RollDecision.DATA_UNAVAILABLE
    assert "600" in result.rationale


# ---------------------------------------------------------------------------
# Test 12: CC ROLL UP 0DTE — roll target is first OTM strike above S, not S×1.02
# ---------------------------------------------------------------------------
def test_cc_roll_up_0dte():
    # S=608.66, K=600, 0DTE → roll target = nearest strike ≥ 608.66 → use 609
    # NOT 625 (which is what S×1.02 = 620.83 would pick)
    today = datetime.date.today().isoformat()
    calls = pd.DataFrame([
        {"strike": 600.0, "bid": 8.50, "ask": 8.90},
        {"strike": 609.0, "bid": 1.80, "ask": 2.00},
        {"strike": 625.0, "bid": 0.05, "ask": 0.10},  # near-zero premium — wrong pick
    ])
    puts = _make_puts_row(600.0, bid=0.10, ask=0.20)
    chain = _mock_chain(calls, puts)
    pos = _cc_pos(strike=600.0, credit=3.50, expiry=today)

    with (
        patch("tradingagents.graph.cc_csp_roll_monitor.yf.Ticker", return_value=_make_ticker_mock(608.66, chain)),
        patch("tradingagents.graph.cc_csp_roll_monitor._session_minutes_remaining", return_value=120),
    ):
        result = evaluate_position(pos)

    assert result.decision == RollDecision.CC_ROLL_UP
    assert result.roll_target_strike == 609.0  # first OTM, not the 2% target of 625


# ---------------------------------------------------------------------------
# Test 13: CSP ROLL DOWN 0DTE — roll target is first OTM put below S, not S×0.95
# ---------------------------------------------------------------------------
def test_csp_roll_down_0dte():
    # S=572, K=580, 0DTE → roll target = nearest strike ≤ 572 → use 571
    # NOT 540 (which is what S×0.95 = 543.4 would pick)
    today = datetime.date.today().isoformat()
    calls = _make_calls_row(580.0, bid=0.10, ask=0.20)
    puts = pd.DataFrame([
        {"strike": 580.0, "bid": 8.50, "ask": 8.90},
        {"strike": 571.0, "bid": 1.60, "ask": 1.80},
        {"strike": 540.0, "bid": 0.05, "ask": 0.10},  # near-zero premium — wrong pick
    ])
    chain = _mock_chain(calls, puts)
    pos = _csp_pos(strike=580.0, credit=2.80, expiry=today)

    with (
        patch("tradingagents.graph.cc_csp_roll_monitor.yf.Ticker", return_value=_make_ticker_mock(572.0, chain)),
        patch("tradingagents.graph.cc_csp_roll_monitor._session_minutes_remaining", return_value=120),
    ):
        result = evaluate_position(pos)

    assert result.decision == RollDecision.CSP_ROLL_DOWN
    assert result.roll_target_strike == 571.0  # first OTM put, not the 5% target of 540


# ---------------------------------------------------------------------------
# Bonus: I/O round-trip
# ---------------------------------------------------------------------------
def test_position_io_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "options_positions.json"

        pos_id = add_position(
            {"type": "cc", "ticker": "QQQ", "strike": 600.0, "expiry": "2099-12-31",
             "credit_received": 3.50, "contracts": 1},
            path=path,
        )

        positions = load_positions(path=path)
        assert len(positions) == 1
        assert positions[0]["id"] == pos_id
        assert positions[0]["status"] == "active"

        ok = close_position(pos_id, path=path)
        assert ok is True

        positions = load_positions(path=path)
        assert positions[0]["status"] == "closed"
