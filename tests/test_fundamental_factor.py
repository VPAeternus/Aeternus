from pathlib import Path

from tradingagents.dealflow.sources.fundamental_factor import collect_fundamental_signals


def _universe():
    return [
        {
            "symbol": "AAPL",
            "asset_class": "Equity",
            "sector": "Technology",
            "liquidity_score": 90.0,
            "aliases": [],
        },
        {
            "symbol": "MSFT",
            "asset_class": "Equity",
            "sector": "Technology",
            "liquidity_score": 88.0,
            "aliases": [],
        },
    ]


def test_collect_fundamental_signals_uses_shadow_registry_strategy(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "tradingagents.dealflow.sources.fundamental_factor.get_active_strategy",
        lambda **_: {
            "strategy": "health_0p5__inv_growth_0p1__inv_quality_0p4",
            "weights": {
                "growth": -0.1,
                "quality": -0.4,
                "health": 0.5,
                "capital_discipline": 0.0,
                "valuation": 0.0,
            },
            "resolved_status": "shadow",
            "registry_run_date": "2026-03-09",
        },
    )
    monkeypatch.setattr(
        "tradingagents.dealflow.sources.fundamental_factor._build_live_feature_rows",
        lambda **_: {
            "AAPL": {
                "ticker": "AAPL",
                "effective_market_date": "2026-03-09",
                "data_coverage_score": 1.0,
                "revenue_growth_yoy_pct": 8.0,
                "fcf_growth_yoy_pct": 6.0,
                "equity_change_pct": 2.0,
                "revenue_growth_acceleration_pct": 1.0,
                "fcf_growth_acceleration_pct": 1.0,
                "gross_margin": 0.45,
                "operating_margin": 0.28,
                "margin_change_pct": 1.5,
                "quality_valuation_tension": 0.4,
                "debt_to_equity": 0.8,
                "current_ratio": 1.3,
                "liquidity_stress_score": 0.0,
                "leverage_stress_score": 0.0,
                "share_count_change_pct": -1.0,
                "ev_to_sales": 6.0,
                "earnings_yield": 0.04,
            },
            "MSFT": {
                "ticker": "MSFT",
                "effective_market_date": "2026-03-09",
                "data_coverage_score": 1.0,
                "revenue_growth_yoy_pct": 6.0,
                "fcf_growth_yoy_pct": 4.0,
                "equity_change_pct": 1.0,
                "revenue_growth_acceleration_pct": 0.0,
                "fcf_growth_acceleration_pct": 0.0,
                "gross_margin": 0.42,
                "operating_margin": 0.25,
                "margin_change_pct": 1.0,
                "quality_valuation_tension": 0.5,
                "debt_to_equity": 0.7,
                "current_ratio": 1.2,
                "liquidity_stress_score": 0.0,
                "leverage_stress_score": 0.0,
                "share_count_change_pct": -0.5,
                "ev_to_sales": 7.0,
                "earnings_yield": 0.035,
            },
        },
    )
    monkeypatch.setattr(
        "tradingagents.dealflow.sources.fundamental_factor._freshness_hours_from_feature_cache",
        lambda *_, **__: 12.0,
    )

    signals = collect_fundamental_signals(
        _universe(),
        as_of_date="2026-03-09",
        config={"dealflow_fundamental_factor_registry_results_root": str(tmp_path)},
    )

    assert len(signals) == 2
    assert {signal["signal_family"] for signal in signals} == {"fundamental_factor_shadow"}
    assert all(signal["source_status"] == "OK" for signal in signals)
    assert all("health_0p5__inv_growth_0p1__inv_quality_0p4" in signal["source_name"] for signal in signals)


def test_collect_fundamental_signals_degrades_when_registry_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "tradingagents.dealflow.sources.fundamental_factor.get_active_strategy",
        lambda **_: None,
    )

    signals = collect_fundamental_signals(
        _universe(),
        as_of_date="2026-03-09",
        config={"dealflow_fundamental_factor_registry_results_root": str(tmp_path)},
    )

    assert len(signals) == 2
    assert all(signal["source_status"] == "NOT_CONFIGURED" for signal in signals)
    assert {signal["signal_family"] for signal in signals} == {"fundamental_factor_shadow"}
