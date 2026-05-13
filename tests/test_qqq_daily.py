import numpy as np
import pandas as pd

from tradingagents.phase_engine.qqq_daily import build_qqq_daily_report


def _frame(n=260, vix=18.0):
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = np.full(n, 100.0)
    df = pd.DataFrame(
        {
            "date": dates,
            "open": close + 1.0,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "volume": np.full(n, 1000.0),
            "vix": np.full(n, vix),
        }
    )
    df["sma3"] = df["close"].rolling(3).mean().fillna(100.0)
    df["sma10"] = df["close"].rolling(10).mean().fillna(100.0)
    df["sma20"] = df["close"].rolling(20).mean().fillna(100.0)
    df["sma50"] = df["close"].rolling(50).mean().fillna(100.0)
    df["sma200"] = df["close"].rolling(200).mean().fillna(100.0)
    df["vix_sma10"] = df["vix"].rolling(10).mean().fillna(vix)
    df["vix_sma20"] = df["vix"].rolling(20).mean().fillna(vix)
    df["vol_sma20"] = df["volume"].rolling(20).mean().fillna(1000.0)
    df["adr_14"] = 4.0
    df["adr_pct"] = 4.0
    df["fvg_bull"] = 0.0
    df["fvg_bear"] = 0.0
    df["fvg_ratio"] = 0.0
    return df


def test_build_qqq_daily_report_aligns_s7_hedge_and_suppresses_overnight():
    qqq = _frame(vix=18.0)
    spy = _frame(vix=22.0)
    i = len(qqq) - 1

    # QQQ gate active and S2 active for CC day.
    qqq.loc[i, "close"] = 80.0
    qqq.loc[i, "sma200"] = 90.0
    qqq.loc[i, "volume"] = 1.0
    # Earlier completed S2 sample so historical bucket stats have a closed next-RTH trade.
    qqq.loc[i - 2, "volume"] = 1.0
    qqq.loc[i - 1, "open"] = 101.0
    qqq.loc[i - 1, "close"] = 100.0

    # SPY S7 active on the same completed signal bar.
    spy.loc[i, "close"] = 80.0
    spy.loc[i, "sma3"] = 79.0
    spy.loc[i, "sma20"] = 90.0
    spy.loc[i, "sma50"] = 95.0
    spy.loc[i, "sma200"] = 100.0
    spy.loc[i, "vix"] = 22.0

    report = build_qqq_daily_report(qqq_df=qqq, spy_df=spy)

    assert report["as_of"] == str(qqq.loc[i, "date"].date())
    assert report["s7_hedge"]["active"] is True
    assert report["s7_hedge"]["hedge_gate_symbol"] == "QQQ"
    assert report["s7_hedge"]["s7_source_symbol"] == "SPY"
    assert report["v3"]["overnight_raw"] is True
    assert report["v3"]["overnight"] is False
    assert report["v3"]["overnight_suppressed_by_s7_hedge"] is True
    assert report["ccwyckoff"]["bucket"] == "S2"
    assert report["ccwyckoff"]["signal"] == "rth_avoid"
    assert report["actions"]["overnight"] == "SUPPRESSED_BY_S7_HEDGE"
    assert report["returns"]["ccwyckoff"]["buckets"]["rth_avoid"]["trades"] >= 1


def test_build_qqq_daily_report_can_select_as_of_date():
    qqq = _frame(vix=18.0)
    spy = _frame(vix=18.0)
    target = str(qqq.loc[220, "date"].date())

    report = build_qqq_daily_report(as_of=target, qqq_df=qqq, spy_df=spy)

    assert report["as_of"] == target
    assert report["applies_to"] == "next_session_after_as_of_close"
    assert report["returns"]["v3"]["date_end"] == target
    assert report["returns"]["ccwyckoff"]["date_end"] == target


def test_build_qqq_daily_report_sorts_unordered_inputs():
    qqq = _frame(vix=18.0).sample(frac=1.0, random_state=7).reset_index(drop=True)
    spy = _frame(vix=18.0).sample(frac=1.0, random_state=11).reset_index(drop=True)
    target = "2024-11-04"

    report = build_qqq_daily_report(as_of=target, qqq_df=qqq, spy_df=spy)

    assert report["as_of"] == target
    assert report["returns"]["v3"]["date_end"] == target
