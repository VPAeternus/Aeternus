# tests/test_post_mortem_wire.py
"""Tests for S-078: Post-Mortem Auto-Generator wire-up into close_position_with_adapter."""

import json
import os
import sys
import types
import pytest
from unittest.mock import MagicMock, patch, mock_open

# Stub chromadb (Python 3.14 compat)
if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub


def _make_fake_trade(symbol="AAPL", close_id="cid-001"):
    return {
        "symbol": symbol,
        "close_id": close_id,
        "close_date": "2026-03-01",
        "return_pct": 5.0,
        "pnl_usd": 500.0,
        "status": "CLOSED",
        "avg_entry_price": 180.0,
        "close_price": 189.0,
    }


def _make_fake_attr(symbol="AAPL"):
    return {
        "ticker": symbol,
        "close_id": "cid-001",
        "close_date": "2026-03-01",
        "outcome": "WIN",
        "return_pct": 5.0,
        "pnl_usd": 500.0,
        "weight_regime": "NEUTRAL",
        "entry_score": 72.0,
        "entry_rating": "Buy",
        "pillar_summary": {"right_count": 3, "wrong_count": 1, "neutral_count": 1},
        "narrative": "=== POST-MORTEM: AAPL ===\nOutcome: WIN",
        "report_found": False,
    }


def test_close_position_saves_post_mortem_json(tmp_path, monkeypatch):
    """Post-mortem JSON is written to post_mortems dir when close_position succeeds."""
    from tradingagents.graph import paper_execution as pe

    fake_trade = _make_fake_trade()
    fake_attr = _make_fake_attr()

    # Mock adapter
    mock_adapter = MagicMock()
    mock_adapter.close_position.return_value = fake_trade
    monkeypatch.setattr(pe, "get_execution_adapter", lambda mode: mock_adapter)

    # Mock PostMortemEngine
    mock_pm_instance = MagicMock()
    mock_pm_instance.analyze_trade.return_value = fake_attr
    mock_pm_instance.generate_narrative.return_value = fake_attr["narrative"]
    mock_pme_cls = MagicMock(return_value=mock_pm_instance)

    # Redirect post-mortem output dir to tmp_path
    pm_dir = str(tmp_path / "post_mortems")

    with patch.dict("sys.modules", {"tradingagents.graph.post_mortem": MagicMock(PostMortemEngine=mock_pme_cls)}):
        with patch("glob.glob", return_value=[]):
            with patch("os.makedirs") as mock_makedirs:
                with patch("builtins.open", mock_open()) as mock_file:
                    result = pe.close_position_with_adapter(
                        symbol="AAPL",
                        close_price=189.0,
                        close_date="2026-03-01",
                    )

    assert result == fake_trade
    mock_pm_instance.analyze_trade.assert_called_once()
    mock_pm_instance.generate_narrative.assert_called_once_with(fake_attr)
    mock_makedirs.assert_called_once_with("eval_results/paper_execution/post_mortems", exist_ok=True)
    mock_file.assert_called()


def test_post_mortem_failure_does_not_crash_close(monkeypatch):
    """If PostMortemEngine constructor raises, close_position_with_adapter still returns trade."""
    from tradingagents.graph import paper_execution as pe

    fake_trade = _make_fake_trade(symbol="MSFT")

    mock_adapter = MagicMock()
    mock_adapter.close_position.return_value = fake_trade
    monkeypatch.setattr(pe, "get_execution_adapter", lambda mode: mock_adapter)

    exploding_pme = MagicMock(side_effect=RuntimeError("DB offline"))

    with patch.dict("sys.modules", {"tradingagents.graph.post_mortem": MagicMock(PostMortemEngine=exploding_pme)}):
        # Should NOT raise
        result = pe.close_position_with_adapter(
            symbol="MSFT",
            close_price=300.0,
            close_date="2026-03-01",
        )

    assert result == fake_trade


def test_post_mortem_with_report_found(monkeypatch):
    """When glob finds a report file, analyze_trade is called with report=dict (not None)."""
    from tradingagents.graph import paper_execution as pe

    fake_trade = _make_fake_trade(symbol="TSLA")
    fake_report = {"aeternus_score": {"aeternus_score": 68, "breakdown": {}, "weight_regime": "BULL"}}
    fake_attr = _make_fake_attr(symbol="TSLA")

    mock_adapter = MagicMock()
    mock_adapter.close_position.return_value = fake_trade
    monkeypatch.setattr(pe, "get_execution_adapter", lambda mode: mock_adapter)

    mock_pm_instance = MagicMock()
    mock_pm_instance.analyze_trade.return_value = fake_attr
    mock_pm_instance.generate_narrative.return_value = fake_attr["narrative"]
    mock_pme_cls = MagicMock(return_value=mock_pm_instance)

    report_path = "results/TSLA/2026-03-01/full_report.json"

    with patch.dict("sys.modules", {"tradingagents.graph.post_mortem": MagicMock(PostMortemEngine=mock_pme_cls)}):
        with patch("glob.glob", return_value=[report_path]):
            with patch("builtins.open", mock_open(read_data=json.dumps(fake_report))):
                with patch("os.makedirs"):
                    result = pe.close_position_with_adapter(
                        symbol="TSLA",
                        close_price=220.0,
                        close_date="2026-03-01",
                    )

    assert result == fake_trade
    call_kwargs = mock_pm_instance.analyze_trade.call_args
    # report should be the loaded dict, not None
    passed_report = call_kwargs[1].get("report") if call_kwargs[1] else call_kwargs[0][1]
    assert passed_report == fake_report


def test_post_mortem_without_report(monkeypatch):
    """When glob finds no report files, analyze_trade is called with report=None."""
    from tradingagents.graph import paper_execution as pe

    fake_trade = _make_fake_trade(symbol="NVDA")
    fake_attr = _make_fake_attr(symbol="NVDA")

    mock_adapter = MagicMock()
    mock_adapter.close_position.return_value = fake_trade
    monkeypatch.setattr(pe, "get_execution_adapter", lambda mode: mock_adapter)

    mock_pm_instance = MagicMock()
    mock_pm_instance.analyze_trade.return_value = fake_attr
    mock_pm_instance.generate_narrative.return_value = fake_attr["narrative"]
    mock_pme_cls = MagicMock(return_value=mock_pm_instance)

    with patch.dict("sys.modules", {"tradingagents.graph.post_mortem": MagicMock(PostMortemEngine=mock_pme_cls)}):
        with patch("glob.glob", return_value=[]):
            with patch("os.makedirs"):
                with patch("builtins.open", mock_open()):
                    result = pe.close_position_with_adapter(
                        symbol="NVDA",
                        close_price=500.0,
                        close_date="2026-03-01",
                    )

    assert result == fake_trade
    call_kwargs = mock_pm_instance.analyze_trade.call_args
    passed_report = call_kwargs[1].get("report") if call_kwargs[1] else call_kwargs[0][1]
    assert passed_report is None
