import math

import pandas as pd
import pytest

from support_break_short import (
    DEFAULT_R_MULTIPLES,
    DEFAULT_VARIANT,
    VARIANT_CHOICES,
    adaptive_profile_ok,
    adaptive_v2_check,
    adaptive_v2_profile_ok,
    build_candidates,
    build_trades,
    classify_vol_profile,
    classify_vol_regime,
    normalize_variant,
    old_r3_core_ok,
    passes_variant_filter,
    summarize,
    add_indicators,
    target_r_for_profile,
    variant_metrics,
)


def test_default_system_is_r3_v5_priority_with_3r_target():
    assert DEFAULT_VARIANT == "r3-v5-priority"
    assert DEFAULT_R_MULTIPLES == [3.0]
    assert "adaptive-v1" in VARIANT_CHOICES
    assert "adaptive-v2" in VARIANT_CHOICES
    assert "adaptive-v2-extreme-research" in VARIANT_CHOICES
    assert "r3-core" in VARIANT_CHOICES
    assert "r3-v5-a-plus" in VARIANT_CHOICES
    assert "r3-v5-fresh" in VARIANT_CHOICES
    assert normalize_variant("r3-v5-high-conviction") == "r3-v5-conviction"


def _high_vol_v2_row(**overrides):
    row = {
        "close": 100.0,
        "high": 103.0,
        "low": 99.0,
        "sma5": 100.0,
        "sma10": 99.2,
        "sma20": 97.0,
        "sma200": 90.0,
        "ret5": 0.02,
        "atr14": 4.0,
        "atr_pct": 0.04,
        "bearish_fvg": False,
        "bearish_fvg_count_3": 0.0,
        "bearish_fvg_count_5": 0.0,
    }
    row.update(overrides)
    return pd.Series(row)


def _run_high_vol_v2(row=None, **kwargs):
    params = {
        "variant": "adaptive-v2",
        "row": row if row is not None else _high_vol_v2_row(),
        "entry": 100.6,
        "stop": 102.0,
        "stop_source": "BREAK_HIGH",
        "fvg_age_bars": 1,
        "break_range_pct": 0.02,
        "support_distance_pct": -0.005,
        "bearish_fvg_count_since_support": 0,
        "bearish_fvg_sequence_max_since_support": 0,
        "bearish_fvg_gap_sum_since_support": 0.0,
        "bearish_fvg_gap_max_since_support": 0.0,
    }
    params.update(kwargs)
    return adaptive_v2_check(**params)


def test_saved_trade_rows_include_fvg_break_context():
    dates = pd.date_range("2025-01-01", periods=206, freq="D")
    rows = []
    for _ in range(200):
        rows.append(
            {
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1000.0,
            }
        )

    rows.extend(
        [
            {"open": 111.0, "high": 113.0, "low": 110.0, "close": 112.0, "volume": 1200.0},
            {"open": 112.0, "high": 112.5, "low": 108.0, "close": 111.0, "volume": 1000.0},
            {"open": 111.0, "high": 112.0, "low": 109.0, "close": 111.0, "volume": 1000.0},
            {"open": 110.0, "high": 112.0, "low": 108.0, "close": 109.0, "volume": 1500.0},
            {"open": 109.5, "high": 110.0, "low": 100.0, "close": 101.0, "volume": 1000.0},
            {"open": 101.0, "high": 101.5, "low": 99.0, "close": 100.0, "volume": 1000.0},
        ]
    )
    df = pd.DataFrame(rows, index=dates)

    trades = build_trades("TEST", df, r_multiple=3.0, variant="legacy")

    assert len(trades) == 1
    trade = trades[0]
    assert trade.fvg_form_date == dates[200]
    assert trade.fvg_age_bars == 3
    assert trade.fvg_age_calendar_days == 3
    assert trade.fvg_low == 110.0
    assert trade.fvg_gap_size == 9.0
    assert math.isclose(trade.fvg_gap_pct, 9.0 / 101.0)
    assert trade.broken_support == 110.0
    assert trade.break_high == 112.0
    assert trade.break_low == 108.0
    assert trade.break_close == 109.0
    assert math.isclose(trade.break_range_pct, 4.0 / 109.0)
    assert trade.stop_source == "BREAK_HIGH"
    assert math.isclose(trade.support_distance_pct, -1.0 / 109.0)
    assert trade.support_ratcheted_count == 0
    assert trade.atr14 > 0
    assert math.isclose(trade.risk_atr, (112.0 - 109.5) / trade.atr14)
    assert trade.volume_zscore_20 > 0
    assert trade.vol_profile == "MID_VOL"
    assert trade.vol_regime == "UNKNOWN_RELATIVE_VOL"
    assert trade.atr_pct > 0
    assert trade.bearish_fvg_count_3 == 0
    assert trade.bearish_fvg_count_5 == 0
    assert trade.bearish_fvg_count_since_support == 0
    assert trade.bearish_fvg_sequence_max_since_support == 0
    assert trade.last_bearish_fvg_age_bars == -1
    assert trade.bearish_fvg_gap_sum_since_support == 0
    assert trade.bearish_fvg_gap_max_since_support == 0
    assert not trade.bearish_fvg_after_support_before_break
    assert trade.risk == 2.5
    assert trade.pnl == 7.5
    assert trade.realized_R == 3.0
    assert trade.hold_days == 0
    assert trade.prior_sma5 > trade.prior_sma10 > trade.prior_sma20 > trade.prior_sma200
    assert math.isclose(trade.gap_pct, 0.5 / 109.0)


def test_r3_v5_broad_filter_matches_accept_block():
    row = pd.Series(
        {
            "close": 100.0,
            "high": 101.25,
            "sma5": 100.5,
            "sma10": 99.0,
            "sma20": 95.0,
            "sma200": 87.0,
            "ret5": 0.01,
            "atr14": 1.0,
        }
    )

    assert passes_variant_filter(
        "r3-v5-broad", row, entry=100.01, stop=101.01, stop_source="BREAK_HIGH", fvg_age_bars=3, break_range_pct=0.02
    )
    assert not passes_variant_filter(
        "r3-v5-broad", row, entry=100.01, stop=101.01, stop_source="SUPPORT", fvg_age_bars=3, break_range_pct=0.02
    )
    assert not passes_variant_filter(
        "r3-v5-broad", row, entry=100.01, stop=101.6, stop_source="BREAK_HIGH", fvg_age_bars=3, break_range_pct=0.02
    )
    assert not passes_variant_filter(
        "r3-v5-broad", row, entry=100.01, stop=100.2, stop_source="BREAK_HIGH", fvg_age_bars=3, break_range_pct=0.02
    )
    assert not passes_variant_filter(
        "r3-v5-broad", row, entry=100.01, stop=103.0, stop_source="BREAK_HIGH", fvg_age_bars=3, break_range_pct=0.02
    )

    too_far_above_sma10 = row.copy()
    too_far_above_sma10["close"] = 101.0
    too_far_above_sma10["sma10"] = 99.0
    assert not passes_variant_filter(
        "r3-v5-broad", too_far_above_sma10, entry=101.01, stop=102.01, stop_source="BREAK_HIGH", fvg_age_bars=3, break_range_pct=0.02
    )

    weak_sma_spread = row.copy()
    weak_sma_spread["sma20"] = 94.0
    assert not passes_variant_filter(
        "r3-v5-broad", weak_sma_spread, entry=100.01, stop=101.01, stop_source="BREAK_HIGH", fvg_age_bars=3, break_range_pct=0.02
    )


def test_r3_v5_priority_and_conviction_add_gap_thresholds():
    row = pd.Series(
        {
            "close": 100.0,
            "sma5": 100.5,
            "sma10": 99.0,
            "sma20": 95.0,
            "sma200": 87.0,
            "ret5": 0.01,
            "atr14": 1.0,
        }
    )

    assert passes_variant_filter(
        "r3-v5-priority", row, entry=100.25, stop=101.25, stop_source="BREAK_HIGH", fvg_age_bars=3, break_range_pct=0.02
    )
    assert not passes_variant_filter(
        "r3-v5-priority", row, entry=100.24, stop=101.24, stop_source="BREAK_HIGH", fvg_age_bars=3, break_range_pct=0.02
    )
    assert passes_variant_filter(
        "r3-v5-conviction", row, entry=100.50, stop=101.50, stop_source="BREAK_HIGH", fvg_age_bars=3, break_range_pct=0.02
    )
    assert not passes_variant_filter(
        "r3-v5-conviction", row, entry=100.49, stop=101.49, stop_source="BREAK_HIGH", fvg_age_bars=3, break_range_pct=0.02
    )
    assert passes_variant_filter(
        "r3-v5-high-conviction", row, entry=100.50, stop=101.50, stop_source="BREAK_HIGH", fvg_age_bars=3, break_range_pct=0.02
    )
    assert passes_variant_filter(
        "r3-v5-a-plus", row, entry=100.50, stop=101.50, stop_source="BREAK_HIGH", fvg_age_bars=3, break_range_pct=0.02
    )
    assert not passes_variant_filter(
        "r3-v5-a-plus", row, entry=100.50, stop=101.50, stop_source="BREAK_HIGH", fvg_age_bars=3, break_range_pct=0.019
    )
    assert passes_variant_filter(
        "r3-v5-fresh", row, entry=100.50, stop=101.50, stop_source="BREAK_HIGH", fvg_age_bars=1, break_range_pct=0.02
    )
    assert not passes_variant_filter(
        "r3-v5-fresh", row, entry=100.50, stop=101.50, stop_source="BREAK_HIGH", fvg_age_bars=2, break_range_pct=0.02
    )


def test_r3_v5_broad_restores_old_core():
    row = pd.Series(
        {
            "close": 100.0,
            "sma5": 100.5,
            "sma10": 99.0,
            "sma20": 95.0,
            "sma200": 87.0,
            "ret5": 0.02,
            "atr14": 1.0,
        }
    )

    assert not passes_variant_filter(
        "r3-v5-broad", row, entry=100.01, stop=101.01, stop_source="BREAK_HIGH", fvg_age_bars=3, break_range_pct=0.02
    )

    no_stack = row.copy()
    no_stack["ret5"] = 0.01
    no_stack["sma20"] = 100.0
    assert not passes_variant_filter(
        "r3-v5-broad", no_stack, entry=100.01, stop=101.01, stop_source="BREAK_HIGH", fvg_age_bars=3, break_range_pct=0.02
    )
    core_row = row.copy()
    core_row["ret5"] = 0.01
    assert passes_variant_filter(
        "r3-core", core_row, entry=100.01, stop=101.01, stop_source="SUPPORT", fvg_age_bars=99, break_range_pct=0.0
    )


def test_summary_uses_realized_r_not_raw_pnl():
    dates = pd.date_range("2025-01-01", periods=206, freq="D")
    rows = [{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0} for _ in range(200)]
    rows.extend(
        [
            {"open": 111.0, "high": 113.0, "low": 110.0, "close": 112.0, "volume": 1200.0},
            {"open": 112.0, "high": 112.5, "low": 108.0, "close": 111.0, "volume": 1000.0},
            {"open": 111.0, "high": 112.0, "low": 109.0, "close": 111.0, "volume": 1000.0},
            {"open": 110.0, "high": 112.0, "low": 108.0, "close": 109.0, "volume": 1500.0},
            {"open": 109.5, "high": 110.0, "low": 100.0, "close": 101.0, "volume": 1000.0},
            {"open": 101.0, "high": 101.5, "low": 99.0, "close": 100.0, "volume": 1000.0},
        ]
    )
    trades = build_trades("TEST", pd.DataFrame(rows, index=dates), r_multiple=3.0, variant="legacy")
    stats = summarize(trades)

    assert stats["trades"] == 1
    assert stats["total_R"] == 3.0
    assert stats["avg_R"] == 3.0
    assert stats["pf_R"] == float("inf")
    assert stats["target_rate"] == 1.0
    assert stats["avg_hold_days"] == 0.0
    assert stats["target_3R_count"] == 1
    assert stats["target_4R_count"] == 0
    assert stats["avg_effective_r"] == 3.0


def test_add_indicators_validates_required_ohlcv_columns():
    df = pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0]})

    with pytest.raises(ValueError, match="missing required columns: \\['volume'\\]"):
        add_indicators(df)


def test_add_indicators_handles_zero_volume_std_with_mask():
    dates = pd.date_range("2025-01-01", periods=25, freq="D")
    df = pd.DataFrame(
        {
            "open": [100.0] * 25,
            "high": [101.0] * 25,
            "low": [99.0] * 25,
            "close": [100.0] * 25,
            "volume": [1000.0] * 25,
        },
        index=dates,
    )

    out = add_indicators(df)

    assert out["volume_zscore_20"].isna().all()
    assert "atr_pct" in out.columns
    assert "atr_pct_252_median" in out.columns
    assert "bullish_fvg" in out.columns
    assert "bearish_fvg" in out.columns
    assert "bearish_fvg_count_3" in out.columns
    assert "bearish_fvg_count_5" in out.columns


def test_classify_vol_profile_uses_break_day_atr_pct():
    assert classify_vol_profile(pd.Series({"atr_pct": 0.010})) == "LOW_VOL"
    assert classify_vol_profile(pd.Series({"atr_pct": 0.020})) == "MID_VOL"
    assert classify_vol_profile(pd.Series({"atr_pct": 0.040})) == "HIGH_VOL"
    assert classify_vol_profile(pd.Series({"atr_pct": 0.080})) == "EXTREME_VOL"
    assert classify_vol_profile(pd.Series({"atr_pct": float("nan")})) == "UNKNOWN_VOL"


def test_classify_vol_regime_uses_atr_pct_ratio_to_252_median():
    assert classify_vol_regime(pd.Series({"atr_pct": 0.02, "atr_pct_252_median": 0.02})) == "NORMAL_RELATIVE_VOL"
    assert classify_vol_regime(pd.Series({"atr_pct": 0.04, "atr_pct_252_median": 0.02})) == "ELEVATED_RELATIVE_VOL"
    assert classify_vol_regime(pd.Series({"atr_pct": 0.01, "atr_pct_252_median": 0.02})) == "QUIET_RELATIVE_VOL"
    assert classify_vol_regime(pd.Series({"atr_pct": float("nan"), "atr_pct_252_median": 0.02})) == "UNKNOWN_RELATIVE_VOL"


def test_adaptive_high_vol_can_accept_without_old_r3_core_stack():
    row = pd.Series(
        {
            "close": 100.0,
            "sma5": 100.0,
            "sma10": 99.0,
            "sma20": 102.0,
            "sma200": 90.0,
            "ret5": 0.025,
            "atr14": 4.0,
            "atr_pct": 0.04,
            "bearish_fvg_count_3": 1.0,
            "bearish_fvg_count_5": 1.0,
        }
    )
    entry = 100.8
    stop = 103.0
    metrics = variant_metrics(row, entry, stop)

    assert not old_r3_core_ok(row, metrics)
    assert not passes_variant_filter(
        "r3-v5-priority",
        row,
        entry=entry,
        stop=stop,
        stop_source="BREAK_HIGH",
        fvg_age_bars=3,
        break_range_pct=0.03,
    )
    assert adaptive_profile_ok(
        row=row,
        entry=entry,
        stop=stop,
        stop_source="BREAK_HIGH",
        fvg_age_bars=3,
        break_range_pct=0.03,
    ) == (True, "HIGH_VOL")
    assert target_r_for_profile("HIGH_VOL", row) == 3.0


def test_adaptive_v2_rejects_extreme_vol_and_requires_shallow_break():
    row = pd.Series(
        {
            "close": 100.0,
            "sma5": 100.0,
            "sma10": 100.5,
            "sma20": 105.0,
            "sma200": 90.0,
            "ret5": 0.01,
            "atr14": 7.0,
            "atr_pct": 0.07,
            "bearish_fvg_count_3": 1.0,
            "bearish_fvg_count_5": 1.0,
            "bearish_fvg_count_since_support": 1,
        }
    )

    assert adaptive_v2_profile_ok(
        row=row,
        entry=100.8,
        stop=102.0,
        stop_source="BREAK_HIGH",
        fvg_age_bars=1,
        break_range_pct=0.05,
        support_distance_pct=-0.005,
    ) == (False, "EXTREME_VOL")

    high_vol = row.copy()
    high_vol["atr14"] = 4.0
    high_vol["atr_pct"] = 0.04
    assert adaptive_v2_profile_ok(
        row=high_vol,
        entry=100.8,
        stop=102.0,
        stop_source="BREAK_HIGH",
        fvg_age_bars=1,
        break_range_pct=0.05,
        support_distance_pct=-0.02,
    ) == (False, "HIGH_VOL")


def test_adaptive_v2_uses_passed_bearish_sequence_context():
    result = _run_high_vol_v2(
        bearish_fvg_sequence_max_since_support=2,
        break_range_pct=0.01,
    )

    assert result.passed
    assert result.vol_profile == "HIGH_VOL"
    assert result.bearish_confirmation_source == "BEARISH_FVG_SEQUENCE"
    assert result.has_bearish_fvg_sequence
    assert not result.has_range_displacement


def test_adaptive_v2_records_single_bearish_fvg_since_support_source():
    result = _run_high_vol_v2(
        bearish_fvg_count_since_support=1,
        bearish_fvg_sequence_max_since_support=1,
        break_range_pct=0.01,
    )

    assert result.passed
    assert result.bearish_confirmation_source == "BEARISH_FVG_SINCE_SUPPORT"
    assert result.has_bearish_fvg_since_support


def test_adaptive_v2_counts_break_day_bearish_fvg_as_confirmation():
    result = _run_high_vol_v2(
        row=_high_vol_v2_row(bearish_fvg=True),
        bearish_fvg_count_since_support=0,
        bearish_fvg_sequence_max_since_support=0,
        break_range_pct=0.01,
    )

    assert result.passed
    assert result.bearish_confirmation_source == "BREAK_DAY_BEARISH_FVG"
    assert result.has_break_day_bearish_fvg


def test_adaptive_v2_allows_range_displacement_fallback():
    result = _run_high_vol_v2(
        bearish_fvg_count_since_support=0,
        bearish_fvg_sequence_max_since_support=0,
        break_range_pct=0.03,
    )

    assert result.passed
    assert result.bearish_confirmation_source == "RANGE_DISPLACEMENT"
    assert result.has_range_displacement


def test_adaptive_v2_rejects_high_vol_without_bearish_confirmation():
    result = _run_high_vol_v2(
        bearish_fvg_count_since_support=0,
        bearish_fvg_sequence_max_since_support=0,
        break_range_pct=0.01,
    )

    assert not result.passed
    assert result.reject_reasons == ["BEARISH_SEQUENCE"]
    assert result.bearish_confirmation_source == "NONE"


def test_adaptive_v2_extreme_research_routing_and_3r_only():
    row = _high_vol_v2_row(atr14=7.0, atr_pct=0.07, bearish_fvg=True)
    normal = adaptive_v2_check(
        variant="adaptive-v2",
        row=row,
        entry=100.8,
        stop=102.0,
        stop_source="BREAK_HIGH",
        fvg_age_bars=1,
        break_range_pct=0.06,
        support_distance_pct=-0.005,
    )
    assert not normal.passed
    assert normal.reject_reasons == ["EXTREME_VOL_DISABLED"]

    non_extreme = _run_high_vol_v2(variant="adaptive-v2-extreme-research")
    assert not non_extreme.passed
    assert non_extreme.reject_reasons == ["NOT_EXTREME_VOL"]

    assert target_r_for_profile("LOW_VOL", row) == 3.0
    assert target_r_for_profile("MID_VOL", row) == 3.0
    assert target_r_for_profile("HIGH_VOL", row) == 3.0
    assert target_r_for_profile("EXTREME_VOL", row) == 3.0


def test_adaptive_v2_unknown_profile_gets_named_reject_reason(monkeypatch):
    monkeypatch.setattr("support_break_short.classify_vol_profile", lambda row: "ODD_VOL")

    result = _run_high_vol_v2()

    assert not result.passed
    assert result.reject_reasons == ["UNKNOWN_VOL_PROFILE"]


def test_candidate_audit_records_reject_reasons():
    dates = pd.date_range("2025-01-01", periods=206, freq="D")
    rows = [{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0} for _ in range(200)]
    rows.extend(
        [
            {"open": 111.0, "high": 113.0, "low": 110.0, "close": 112.0, "volume": 1200.0},
            {"open": 112.0, "high": 112.5, "low": 108.0, "close": 111.0, "volume": 1000.0},
            {"open": 111.0, "high": 112.0, "low": 109.0, "close": 111.0, "volume": 1000.0},
            {"open": 110.0, "high": 112.0, "low": 108.0, "close": 109.0, "volume": 1500.0},
            {"open": 109.5, "high": 110.0, "low": 100.0, "close": 101.0, "volume": 1000.0},
            {"open": 101.0, "high": 101.5, "low": 99.0, "close": 100.0, "volume": 1000.0},
        ]
    )
    candidates = build_candidates("TEST", pd.DataFrame(rows, index=dates), variant="adaptive-v2")

    assert len(candidates) == 1
    assert candidates[0]["ticker"] == "TEST"
    assert "vol_profile" in candidates[0]
    assert "passed_variant" in candidates[0]
    assert "reject_reasons" in candidates[0]


def test_adaptive_v2_candidate_audit_has_named_reasons_not_profile_rule():
    row = _high_vol_v2_row()
    result = adaptive_v2_check(
        variant="adaptive-v2",
        row=row,
        entry=100.6,
        stop=102.0,
        stop_source="BREAK_HIGH",
        fvg_age_bars=1,
        break_range_pct=0.01,
        support_distance_pct=-0.005,
    )

    assert not result.passed
    assert "BEARISH_SEQUENCE" in result.reject_reasons
    assert "PROFILE_RULE" not in result.reject_reasons
