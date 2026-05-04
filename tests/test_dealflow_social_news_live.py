"""Tests for social_news collector — manual X-feed merged artifact only."""

from __future__ import annotations

import json
from typing import Any, Dict

from tradingagents.dealflow.sources.social_news import collect_social_news_signals


def _universe_row(symbol: str) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "asset_class": "Equity",
        "sector": "Technology",
        "liquidity_score": 90.0,
        "aliases": [symbol.lower()],
    }


def _write_merged(path, payload: Dict[str, Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def test_manual_x_feed_primary_scoring(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_merged(
        tmp_path / "eval_results" / "x_feed" / "2026-03-04" / "merged.json",
        {
            "AAPL": {
                "ticker": "AAPL",
                "sentiment": 0.5,
                "mentions_estimate": 4,
                "velocity_trend": "rising",
                "catalyst": "iPhone demand and AI device cycle",
            }
        },
    )

    signals = collect_social_news_signals(
        [_universe_row("AAPL")],
        as_of_date="2026-03-04",
        max_symbol_calls=1,
        config={},
    )

    assert len(signals) == 2
    social = [s for s in signals if s["signal_family"] == "social_momentum"][0]
    news = [s for s in signals if s["signal_family"] == "news_catalyst"][0]

    assert round(social["raw_score"], 2) == 82.0
    assert round(news["raw_score"], 2) == 75.0
    assert social["source_name"] == "manual_x_feed"
    assert news["source_name"] == "manual_x_feed"
    assert social["source_status"] == "OK"
    assert news["source_status"] == "OK"
    assert social["evidence_count"] == 4
    assert news["evidence_count"] == 4


def test_no_data_when_symbol_absent_from_manual_x_feed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_merged(
        tmp_path / "eval_results" / "x_feed" / "2026-03-04" / "merged.json",
        {
            "AAPL": {
                "ticker": "AAPL",
                "sentiment": 0.4,
                "mentions_estimate": 3,
                "velocity_trend": "stable",
                "catalyst": "Earnings follow-through",
            }
        },
    )

    signals = collect_social_news_signals(
        [_universe_row("XYZ")],
        as_of_date="2026-03-04",
        max_symbol_calls=1,
        config={},
    )

    assert len(signals) == 2
    assert all(s["source_status"] == "NO_DATA" for s in signals)
    assert all(s["raw_score"] == 0.0 for s in signals)
    assert all(s["evidence_count"] == 0 for s in signals)
    assert all(s["direction"] == "NEUTRAL" for s in signals)
