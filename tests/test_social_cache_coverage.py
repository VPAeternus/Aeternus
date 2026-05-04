"""Tests: manual merged X-feed symbols outside liquidity top-K still get social/news signals."""

import json

from tradingagents.dealflow.sources.social_news import collect_social_news_signals


def _make_universe(*syms_with_liq):
    return [{"symbol": s, "liquidity_score": liq} for s, liq in syms_with_liq]


_MERGED = {
    "AAPL": {"ticker": "AAPL", "sentiment": 0.6, "mentions_estimate": 5, "velocity_trend": "rising", "catalyst": "iPhone demand"},
    "MSFT": {"ticker": "MSFT", "sentiment": 0.3, "mentions_estimate": 2, "velocity_trend": "stable", "catalyst": None},
    "AXTI": {"ticker": "AXTI", "sentiment": 0.8, "mentions_estimate": 6, "velocity_trend": "rising", "catalyst": "SiC contract win"},
}


def _write_merged(tmp_path):
    path = tmp_path / "eval_results" / "x_feed" / "2026-03-04" / "merged.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_MERGED))


class TestMergedSymbolsOutsideTopK:
    def test_merged_low_liquidity_gets_signals(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_merged(tmp_path)
        universe = _make_universe(("AAPL", 100.0), ("MSFT", 90.0), ("AXTI", 5.0))

        signals = collect_social_news_signals(universe, "2026-03-04", max_symbol_calls=2)

        axti_sigs = [s for s in signals if s["symbol"] == "AXTI"]
        assert len(axti_sigs) == 2
        assert {s["signal_family"] for s in axti_sigs} == {"social_momentum", "news_catalyst"}
        assert all(s["source_status"] == "OK" for s in axti_sigs)

    def test_merged_symbol_not_in_universe_excluded(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_merged(tmp_path)
        universe = _make_universe(("AAPL", 100.0))

        signals = collect_social_news_signals(universe, "2026-03-04", max_symbol_calls=5)

        syms = {s["symbol"] for s in signals}
        assert "AXTI" not in syms
        assert "AAPL" in syms

    def test_top_k_processed_normally(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_merged(tmp_path)
        universe = _make_universe(("AAPL", 100.0), ("MSFT", 90.0))

        signals = collect_social_news_signals(universe, "2026-03-04", max_symbol_calls=2)

        aapl_sigs = [s for s in signals if s["symbol"] == "AAPL"]
        assert len(aapl_sigs) == 2
        assert all(s["source_status"] == "OK" for s in aapl_sigs)

    def test_missing_manual_x_feed_does_not_extend_symbol_list(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        universe = _make_universe(("AAPL", 100.0), ("MSFT", 90.0), ("AXTI", 5.0))

        signals = collect_social_news_signals(universe, "2026-03-04", max_symbol_calls=2)

        syms = {s["symbol"] for s in signals}
        assert "AXTI" not in syms
        assert "AAPL" in syms
        assert "MSFT" in syms
