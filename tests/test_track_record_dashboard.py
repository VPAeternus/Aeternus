"""Tests for track_record_dashboard.py"""
import json
import math
from pathlib import Path

import pytest

from tradingagents.graph.track_record_dashboard import (
    _render_html,
    compute_track_record_stats,
    generate_dashboard,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_entry(
    ticker="AAPL",
    trade_date="2025-01-10",
    rating="Strong Buy",
    price_at_rating=150.0,
    close_price=None,
    close_date=None,
    status=None,
    score=72.5,
):
    entry = {
        "ticker": ticker,
        "trade_date": trade_date,
        "rating": rating,
        "price_at_rating": price_at_rating,
        "aeternus_score": {"aeternus_score": score, "rating": rating},
        "rating_id": f"{ticker}-{trade_date}",
    }
    if close_price is not None:
        entry["close_price"] = close_price
        entry["close_date"] = close_date or "2025-02-10"
        entry["status"] = "CLOSED"
    elif status:
        entry["status"] = status
    return entry


# ---------------------------------------------------------------------------
# compute_track_record_stats
# ---------------------------------------------------------------------------

def test_compute_stats_empty():
    stats = compute_track_record_stats([])
    assert stats["total_analyses"] == 0
    assert stats["closed_count"] == 0
    assert stats["win_rate"] == 0.0
    assert stats["avg_return"] == 0.0
    assert stats["sharpe_ratio"] is None
    assert stats["date_start"] is None
    assert stats["date_end"] is None
    assert stats["cumulative_returns"] == []


def test_compute_stats_with_closed_trades():
    history = [
        _make_entry("AAPL", price_at_rating=100.0, close_price=110.0),  # +10% win
        _make_entry("MSFT", price_at_rating=200.0, close_price=190.0),  # -5% loss
        _make_entry("GOOG", price_at_rating=50.0),                       # open, no close
    ]
    stats = compute_track_record_stats(history)
    assert stats["total_analyses"] == 3
    assert stats["closed_count"] == 2
    # AAPL +10%, MSFT -5% → avg = 2.5%
    assert abs(stats["avg_return"] - 0.025) < 1e-9
    # Only AAPL is a win (Buy, positive return)
    assert stats["win_rate"] == pytest.approx(0.5)


def test_compute_stats_sell_rating_win():
    """A SELL rating with negative return should count as a win."""
    entry = _make_entry("XYZ", rating="Sell", price_at_rating=100.0, close_price=80.0)
    stats = compute_track_record_stats([entry])
    assert stats["closed_count"] == 1
    assert stats["win_rate"] == pytest.approx(1.0)
    assert stats["avg_return"] == pytest.approx(-0.20)


def test_compute_stats_sharpe():
    """Sharpe = mean/std * sqrt(252) for 2+ closed trades."""
    # returns: +10%, -10%  → mean=0, std>0, sharpe=0
    history = [
        _make_entry("A", price_at_rating=100.0, close_price=110.0),
        _make_entry("B", price_at_rating=100.0, close_price=90.0, rating="Hold"),
    ]
    stats = compute_track_record_stats(history)
    assert stats["sharpe_ratio"] is not None
    assert abs(stats["sharpe_ratio"]) < 1e-6  # mean = 0 → sharpe = 0

    # With only one closed trade: N/A
    stats_one = compute_track_record_stats([history[0]])
    assert stats_one["sharpe_ratio"] is None


def test_compute_stats_sharpe_positive():
    """All positive returns → positive Sharpe."""
    history = [
        _make_entry("A", price_at_rating=100.0, close_price=120.0),  # +20%
        _make_entry("B", price_at_rating=100.0, close_price=115.0),  # +15%
        _make_entry("C", price_at_rating=100.0, close_price=110.0),  # +10%
    ]
    stats = compute_track_record_stats(history)
    assert stats["sharpe_ratio"] is not None
    assert stats["sharpe_ratio"] > 0


def test_compute_stats_cumulative_returns_order():
    """Cumulative returns are sorted by trade_date."""
    history = [
        _make_entry("B", trade_date="2025-03-01", price_at_rating=100.0, close_price=110.0),
        _make_entry("A", trade_date="2025-01-01", price_at_rating=100.0, close_price=120.0),
    ]
    stats = compute_track_record_stats(history)
    cum = stats["cumulative_returns"]
    assert len(cum) == 2
    assert cum[0]["ticker"] == "A"   # earlier date first
    assert cum[1]["ticker"] == "B"
    # After A: (1.20 - 1) * 100 = 20%, after B: compound 1.20 * 1.10 - 1 = 32%
    assert abs(cum[0]["cumulative_return"] - 20.0) < 0.01
    assert abs(cum[1]["cumulative_return"] - 32.0) < 0.01


# ---------------------------------------------------------------------------
# _render_html
# ---------------------------------------------------------------------------

def test_render_html_empty_state():
    stats = compute_track_record_stats([])
    html = _render_html(stats, [], None)
    assert "No trades recorded yet" in html
    assert "chart.js" not in html.lower()  # no chart when empty


def test_render_html_contains_chartjs_when_entries():
    history = [_make_entry(price_at_rating=100.0, close_price=115.0)]
    stats = compute_track_record_stats(history)
    html = _render_html(stats, history, None)
    assert "cdn.jsdelivr.net/npm/chart.js" in html


def test_render_html_stats_displayed():
    history = [_make_entry(price_at_rating=100.0, close_price=110.0)]
    stats = compute_track_record_stats(history)
    html = _render_html(stats, history, None)
    assert "Total Analyses" in html
    assert "Win Rate" in html
    assert "Sharpe" in html
    assert "AAPL" in html


def test_render_html_spy_block():
    history = [_make_entry(price_at_rating=100.0, close_price=110.0)]
    stats = compute_track_record_stats(history)
    spy_data = {"spy_return": 0.05, "spy_series": [{"date": "2025-01-10", "cumulative_return": 5.0}]}
    html = _render_html(stats, history, spy_data)
    assert "SPY Return" in html
    assert "Alpha vs SPY" in html


# ---------------------------------------------------------------------------
# generate_dashboard (integration — file I/O, no API calls)
# ---------------------------------------------------------------------------

def test_generate_dashboard_creates_html(tmp_path):
    track_record = [_make_entry(price_at_rating=100.0, close_price=120.0)]
    tr_path = tmp_path / "track_record.json"
    tr_path.write_text(json.dumps(track_record))
    out_path = tmp_path / "out" / "dashboard.html"

    result = generate_dashboard(
        track_record_path=str(tr_path),
        output_path=str(out_path),
        spy_benchmark=False,
    )
    assert result == str(out_path)
    assert out_path.exists()
    html = out_path.read_text()
    assert "<!DOCTYPE html>" in html
    assert "Aeternus Track Record" in html
    assert "AAPL" in html


def test_generate_dashboard_empty_state(tmp_path):
    tr_path = tmp_path / "track_record.json"
    tr_path.write_text("[]")
    out_path = tmp_path / "dashboard.html"

    generate_dashboard(
        track_record_path=str(tr_path),
        output_path=str(out_path),
        spy_benchmark=False,
    )
    html = out_path.read_text()
    assert "No trades recorded yet" in html


def test_generate_dashboard_missing_file(tmp_path):
    """Missing track record file should produce empty-state dashboard, not crash."""
    out_path = tmp_path / "dashboard.html"
    result = generate_dashboard(
        track_record_path=str(tmp_path / "nonexistent.json"),
        output_path=str(out_path),
        spy_benchmark=False,
    )
    assert out_path.exists()
    html = out_path.read_text()
    assert "No trades recorded yet" in html


def test_generate_dashboard_no_spy(tmp_path, monkeypatch):
    """spy_benchmark=False must not call yfinance."""
    import tradingagents.graph.track_record_dashboard as mod

    called = []

    def fake_get_spy(*args, **kwargs):
        called.append(True)
        return None

    monkeypatch.setattr(mod, "_get_spy_data", fake_get_spy)

    track_record = [_make_entry(price_at_rating=100.0, close_price=110.0)]
    tr_path = tmp_path / "track_record.json"
    tr_path.write_text(json.dumps(track_record))
    out_path = tmp_path / "dashboard.html"

    generate_dashboard(
        track_record_path=str(tr_path),
        output_path=str(out_path),
        spy_benchmark=False,
    )
    assert not called, "_get_spy_data should not be called when spy_benchmark=False"


def test_html_contains_chartjs(tmp_path):
    track_record = [_make_entry(price_at_rating=100.0, close_price=130.0)]
    tr_path = tmp_path / "track_record.json"
    tr_path.write_text(json.dumps(track_record))
    out_path = tmp_path / "dashboard.html"

    generate_dashboard(
        track_record_path=str(tr_path),
        output_path=str(out_path),
        spy_benchmark=False,
    )
    html = out_path.read_text()
    assert "cdn.jsdelivr.net/npm/chart.js" in html


def test_generate_dashboard_creates_parent_dirs(tmp_path):
    """Output path with nested directories that don't exist must be created."""
    tr_path = tmp_path / "track_record.json"
    tr_path.write_text("[]")
    out_path = tmp_path / "a" / "b" / "c" / "report.html"

    generate_dashboard(
        track_record_path=str(tr_path),
        output_path=str(out_path),
        spy_benchmark=False,
    )
    assert out_path.exists()
