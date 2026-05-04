"""Tests for the Position Re-Analysis Engine (S-051).

All file I/O is mocked via tmp_path — zero live network calls or real disk writes.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from tradingagents.graph.paper_execution import evaluate_position_reanalysis


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_position(
    ticker: str,
    net_quantity: float = 10.0,
    avg_price: float = 100.0,
    opened_at: Optional[str] = None,
    entry_aeternus_score: Optional[float] = None,
) -> Dict[str, Any]:
    if opened_at is None:
        # Default: 10 days ago
        opened_at = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=10)).isoformat()
    pos = {
        "net_quantity": net_quantity,
        "avg_price": avg_price,
        "last_mark_price": avg_price * 1.05,
        "opened_at": opened_at,
    }
    if entry_aeternus_score is not None:
        pos["entry_aeternus_score"] = entry_aeternus_score
    return pos


def _make_positions_file(tmp_path: Path, positions: Dict[str, Any]) -> Path:
    """Write a positions JSON file and return its path."""
    data = {"open_positions": positions}
    p = tmp_path / "positions.json"
    p.write_text(json.dumps(data))
    return p


def _make_analysis_report(
    tmp_path: Path,
    ticker: str,
    date_str: str,
    aeternus_score: float,
    final_trade_decision: str = "BUY AAPL",
) -> Path:
    """Write a mock analysis_report.json and return its path."""
    report_dir = tmp_path / "results" / ticker / date_str
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "aeternus_score": {"aeternus_score": aeternus_score},
        "final_trade_decision": final_trade_decision,
    }
    p = report_dir / "analysis_report.json"
    p.write_text(json.dumps(report))
    return p


def _today() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


def _cfg(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base = {
        "reanalysis_min_hold_days": 5,
        "reanalysis_exit_score_threshold": 40.0,
        "reanalysis_exit_score_drop_pct": 0.30,
        "paper_positions_path": "",
        "live_positions_shadow_path": "",
    }
    if overrides:
        base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Test 1: SCORE_DETERIORATION — current score below absolute threshold
# ---------------------------------------------------------------------------

def test_score_deterioration(tmp_path):
    """Score below threshold triggers SCORE_DETERIORATION exit."""
    ticker = "AAPL"
    pos_path = _make_positions_file(tmp_path, {ticker: _make_position(ticker, entry_aeternus_score=70.0)})
    _make_analysis_report(tmp_path, ticker, _today(), aeternus_score=35.0)

    result = evaluate_position_reanalysis(
        execution_mode="paper",
        positions_path=str(pos_path),
        results_dir=str(tmp_path / "results"),
        config=_cfg(),
    )

    exits = result["exit_recommendations"]
    assert len(exits) == 1
    assert exits[0]["ticker"] == ticker
    assert exits[0]["exit_rule"] == "SCORE_DETERIORATION"
    assert exits[0]["recommendation"] == "EXIT"
    assert exits[0]["current_score"] == pytest.approx(35.0)


# ---------------------------------------------------------------------------
# Test 2: THESIS_WEAKENED — score dropped > 30% from entry
# ---------------------------------------------------------------------------

def test_thesis_weakened(tmp_path):
    """Score dropped 40% from entry triggers THESIS_WEAKENED."""
    ticker = "MSFT"
    # entry=70, current=42 → drop = (70-42)/70 = 0.40 > 0.30
    pos_path = _make_positions_file(tmp_path, {ticker: _make_position(ticker, entry_aeternus_score=70.0)})
    _make_analysis_report(tmp_path, ticker, _today(), aeternus_score=42.0)

    result = evaluate_position_reanalysis(
        execution_mode="paper",
        positions_path=str(pos_path),
        results_dir=str(tmp_path / "results"),
        config=_cfg(),
    )

    exits = result["exit_recommendations"]
    assert len(exits) == 1
    assert exits[0]["ticker"] == ticker
    assert exits[0]["exit_rule"] == "THESIS_WEAKENED"
    assert exits[0]["entry_score"] == pytest.approx(70.0)


# ---------------------------------------------------------------------------
# Test 3: THESIS_REVERSED — analysis now says SELL but position is long
# ---------------------------------------------------------------------------

def test_thesis_reversed(tmp_path):
    """Final trade decision flipped to SELL on a long position triggers THESIS_REVERSED."""
    ticker = "NVDA"
    # score above threshold, no big drop — but decision reversed
    pos_path = _make_positions_file(tmp_path, {ticker: _make_position(ticker, entry_aeternus_score=75.0)})
    _make_analysis_report(tmp_path, ticker, _today(), aeternus_score=68.0, final_trade_decision="SELL NVDA")

    result = evaluate_position_reanalysis(
        execution_mode="paper",
        positions_path=str(pos_path),
        results_dir=str(tmp_path / "results"),
        config=_cfg(),
    )

    exits = result["exit_recommendations"]
    assert len(exits) == 1
    assert exits[0]["ticker"] == ticker
    assert exits[0]["exit_rule"] == "THESIS_REVERSED"


# ---------------------------------------------------------------------------
# Test 4: Position held < min_hold_days is skipped entirely
# ---------------------------------------------------------------------------

def test_skips_positions_below_min_hold_days(tmp_path):
    """Positions held fewer than min_hold_days are not evaluated."""
    ticker = "TSLA"
    recent_open = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).isoformat()
    pos_path = _make_positions_file(tmp_path, {ticker: _make_position(ticker, opened_at=recent_open)})
    _make_analysis_report(tmp_path, ticker, _today(), aeternus_score=20.0)  # would trigger if evaluated

    result = evaluate_position_reanalysis(
        execution_mode="paper",
        positions_path=str(pos_path),
        results_dir=str(tmp_path / "results"),
        config=_cfg({"reanalysis_min_hold_days": 5}),
    )

    assert result["positions_evaluated"] == 0
    assert result["exit_recommendations"] == []
    assert result["needs_reanalysis"] == []
    assert result["hold"] == []


# ---------------------------------------------------------------------------
# Test 5: NEEDS_REANALYSIS — no fresh report found for today
# ---------------------------------------------------------------------------

def test_needs_reanalysis_when_no_report(tmp_path):
    """Position held long enough but no fresh analysis → flagged as NEEDS_REANALYSIS."""
    ticker = "META"
    pos_path = _make_positions_file(tmp_path, {ticker: _make_position(ticker)})
    # Deliberately do NOT write any analysis report

    result = evaluate_position_reanalysis(
        execution_mode="paper",
        positions_path=str(pos_path),
        results_dir=str(tmp_path / "results"),
        config=_cfg(),
    )

    needs = result["needs_reanalysis"]
    assert len(needs) == 1
    assert needs[0]["ticker"] == ticker
    assert needs[0]["recommendation"] == "NEEDS_REANALYSIS"
    assert needs[0]["hold_days"] >= 5


# ---------------------------------------------------------------------------
# Test 6: HOLD — score is fine, no reversal, no big drop
# ---------------------------------------------------------------------------

def test_hold_when_thesis_intact(tmp_path):
    """Position with good score and no reversal stays in hold list."""
    ticker = "AMZN"
    pos_path = _make_positions_file(tmp_path, {ticker: _make_position(ticker, entry_aeternus_score=70.0)})
    _make_analysis_report(tmp_path, ticker, _today(), aeternus_score=65.0, final_trade_decision="BUY AMZN")

    result = evaluate_position_reanalysis(
        execution_mode="paper",
        positions_path=str(pos_path),
        results_dir=str(tmp_path / "results"),
        config=_cfg(),
    )

    assert result["exit_recommendations"] == []
    assert result["needs_reanalysis"] == []
    holds = result["hold"]
    assert len(holds) == 1
    assert holds[0]["ticker"] == ticker
    assert holds[0]["recommendation"] == "HOLD"


# ---------------------------------------------------------------------------
# Test 7: Mixed portfolio — multiple tickers in various states
# ---------------------------------------------------------------------------

def test_mixed_portfolio(tmp_path):
    """Mixed portfolio correctly buckets positions into all three categories."""
    today = _today()
    recent = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).isoformat()

    positions = {
        "EXIT_TICKER": _make_position("EXIT_TICKER", entry_aeternus_score=70.0),
        "STALE_TICKER": _make_position("STALE_TICKER"),
        "HOLD_TICKER": _make_position("HOLD_TICKER", entry_aeternus_score=70.0),
        "YOUNG_TICKER": _make_position("YOUNG_TICKER", opened_at=recent),
    }
    pos_path = _make_positions_file(tmp_path, positions)

    # Exit: score below threshold
    _make_analysis_report(tmp_path, "EXIT_TICKER", today, aeternus_score=30.0)
    # STALE_TICKER: no report → needs reanalysis
    # Hold: score fine
    _make_analysis_report(tmp_path, "HOLD_TICKER", today, aeternus_score=65.0, final_trade_decision="BUY HOLD_TICKER")
    # YOUNG_TICKER: skipped (< min_hold_days)

    result = evaluate_position_reanalysis(
        execution_mode="paper",
        positions_path=str(pos_path),
        results_dir=str(tmp_path / "results"),
        config=_cfg(),
    )

    assert result["positions_evaluated"] == 3  # YOUNG_TICKER excluded
    assert len(result["exit_recommendations"]) == 1
    assert result["exit_recommendations"][0]["ticker"] == "EXIT_TICKER"
    assert len(result["needs_reanalysis"]) == 1
    assert result["needs_reanalysis"][0]["ticker"] == "STALE_TICKER"
    assert len(result["hold"]) == 1
    assert result["hold"][0]["ticker"] == "HOLD_TICKER"


# ---------------------------------------------------------------------------
# Test 8: Positions file missing → returns empty result gracefully
# ---------------------------------------------------------------------------

def test_missing_positions_file(tmp_path):
    """Missing positions file returns zero evaluated positions without crashing."""
    result = evaluate_position_reanalysis(
        execution_mode="paper",
        positions_path=str(tmp_path / "nonexistent_positions.json"),
        results_dir=str(tmp_path / "results"),
        config=_cfg(),
    )

    assert result["positions_evaluated"] == 0
    assert result["exit_recommendations"] == []
    assert result["needs_reanalysis"] == []
    assert result["hold"] == []


# ---------------------------------------------------------------------------
# Test 9: Corrupt analysis report does not crash — falls back to HOLD
# ---------------------------------------------------------------------------

def test_corrupt_report_graceful_degradation(tmp_path):
    """Malformed analysis_report.json does not crash; position defaults to HOLD."""
    ticker = "GOOG"
    pos_path = _make_positions_file(tmp_path, {ticker: _make_position(ticker)})
    report_dir = tmp_path / "results" / ticker / _today()
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "analysis_report.json").write_text("not valid json {{{{")

    result = evaluate_position_reanalysis(
        execution_mode="paper",
        positions_path=str(pos_path),
        results_dir=str(tmp_path / "results"),
        config=_cfg(),
    )

    assert result["exit_recommendations"] == []
    assert result["needs_reanalysis"] == []
    holds = result["hold"]
    assert len(holds) == 1
    assert holds[0]["ticker"] == ticker
