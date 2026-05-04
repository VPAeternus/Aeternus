import datetime as dt

from tradingagents.evidence.regimes import (
    CPI_MAX_FFILL_TRADING_DAYS,
    DGS10_MAX_FFILL_TRADING_DAYS,
    build_regime_report,
    classify_regime,
    normalize_macro_series,
)


def test_regime_precedence_favors_vol_shock_over_bear():
    regime, triggers = classify_regime(
        {
            "spy_close": 390.0,
            "spy_sma20": 405.0,
            "spy_sma200": 420.0,
            "vix_close": 36.0,
            "spy_return_1d_pct": -4.2,
        }
    )
    assert regime == "VOL_SHOCK"
    assert triggers


def test_vix_boundary_separates_high_vol_from_vol_shock():
    common = {
        "spy_close": 460.0,
        "spy_sma20": 455.0,
        "spy_sma200": 440.0,
        "spy_deviation_pct": 1.2,
        "spy_return_1d_pct": -1.0,
    }

    regime_high_vol, _ = classify_regime({**common, "vix_close": 49.0})
    regime_vol_shock, _ = classify_regime({**common, "vix_close": 50.0})

    assert regime_high_vol == "HIGH_VOL"
    assert regime_vol_shock == "VOL_SHOCK"


def test_risk_off_requires_explicit_vix_and_supporting_stress():
    no_vix_regime, _ = classify_regime(
        {
            "spy_close": 410.0,
            "spy_sma20": 395.0,
            "spy_sma200": 405.0,
            "spy_deviation_pct": -4.0,
            "spy_return_1d_pct": -1.2,
        }
    )

    with_vix_regime, _ = classify_regime(
        {
            "spy_close": 410.0,
            "spy_sma20": 420.0,
            "spy_sma200": 405.0,
            "spy_deviation_pct": -4.0,
            "spy_return_1d_pct": -1.2,
            "vix_close": 26.0,
        }
    )

    assert no_vix_regime == "NEUTRAL"
    assert with_vix_regime == "RISK_OFF"


def test_macro_normalization_forward_fill_and_alignment():
    normalized = normalize_macro_series(
        trading_dates=["2026-01-02", "2026-01-15", "2026-02-03", "2026-03-03"],
        dgs10_daily={
            "2026-01-02": 4.10,
            "2026-02-03": 4.35,
        },
        cpi_monthly={
            "2025-12": 3.0,
            "2026-01": 3.2,
            "2026-02": 3.4,
        },
    )

    assert normalized["2026-01-15"]["dgs10"] == 4.10
    assert normalized["2026-02-03"]["dgs10"] == 4.35
    assert normalized["2026-01-15"]["cpi_yoy"] == 3.2
    assert normalized["2026-03-03"]["cpi_yoy"] == 3.4
    assert normalized["2026-03-03"]["stale_macro"] is False


def test_macro_normalization_marks_stale_after_ffill_limits():
    start = dt.date(2026, 1, 1)
    dates = [(start + dt.timedelta(days=idx)).isoformat() for idx in range(70)]

    normalized = normalize_macro_series(
        trading_dates=dates,
        dgs10_daily={
            dates[0]: 4.1,
        },
        cpi_monthly={
            "2026-01": 3.0,
        },
    )

    dgs_stale_day = dates[DGS10_MAX_FFILL_TRADING_DAYS + 1]
    cpi_stale_day = dates[CPI_MAX_FFILL_TRADING_DAYS + 1]
    assert normalized[dgs_stale_day]["dgs10"] is None
    assert normalized[dgs_stale_day]["dgs10_stale"] is True
    assert normalized[cpi_stale_day]["cpi_yoy"] is None
    assert normalized[cpi_stale_day]["cpi_stale"] is True
    assert normalized[cpi_stale_day]["stale_macro"] is True


def test_stale_macro_without_market_signal_falls_back_to_neutral():
    regime, triggers = classify_regime(
        {
            "dgs10_stale": True,
            "cpi_stale": True,
            "stale_macro": True,
        }
    )
    assert regime == "NEUTRAL"
    assert triggers == ["STALE_MACRO"]


def test_build_regime_report_labels_vol_shock_fixture():
    report = build_regime_report(
        market_snapshots={
            "2020-03-12": {
                "spy_close": 248.0,
                "spy_sma20": 292.0,
                "spy_sma200": 301.0,
                "spy_deviation_pct": -15.1,
                "vix_close": 75.0,
            },
            "2020-03-13": {
                "spy_close": 250.0,
                "spy_sma20": 290.0,
                "spy_sma200": 300.0,
                "spy_deviation_pct": -13.8,
                "vix_close": 57.0,
            },
            "2020-03-16": {
                "spy_close": 238.0,
                "spy_sma20": 285.0,
                "spy_sma200": 299.0,
                "spy_deviation_pct": -16.5,
                "vix_close": 82.0,
            },
            "2020-03-17": {
                "spy_close": 252.0,
                "spy_sma20": 281.0,
                "spy_sma200": 298.5,
                "spy_deviation_pct": -10.3,
                "vix_close": 75.0,
            },
        }
    )

    labels = {row["date"]: row["regime"] for row in report["date_labels"]}
    assert labels["2020-03-16"] == "VOL_SHOCK"
    assert report["counts"]["VOL_SHOCK"] >= 1
    assert report["macro_normalization"]["dgs10_max_ffill_trading_days"] == DGS10_MAX_FFILL_TRADING_DAYS
    assert report["macro_normalization"]["cpi_max_ffill_trading_days"] == CPI_MAX_FFILL_TRADING_DAYS
