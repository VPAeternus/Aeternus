import pandas as pd

from tradingagents.backtesting.thirteenf.core import (
    build_13f_backtest_events,
    next_trading_day,
    score_manager_quality,
)


def _prices():
    dates = pd.bdate_range("2024-02-15", periods=220)
    return pd.DataFrame(
        {
            "AAA": [100 + i for i in range(len(dates))],
            "BBB": [50 + 0.2 * i for i in range(len(dates))],
            "SPY": [100 + 0.1 * i for i in range(len(dates))],
        },
        index=dates,
    )


def test_next_trading_day_after_public_filing_date():
    prices = _prices()
    assert next_trading_day(prices, "AAA", "2024-02-16").isoformat() == "2024-02-19"


def test_build_13f_events_uses_horizons_and_hold_until_exit():
    rows = [
        {
            "manager_id": "m1",
            "manager_name": "Manager One",
            "filing_date": "2024-02-16",
            "report_date": "2023-12-31",
            "ticker": "AAA",
            "shares": 100,
            "previous_shares": 0,
            "market_value": 10000,
            "is_initial_observation": False,
            "is_new_position": True,
        },
        {
            "manager_id": "m1",
            "manager_name": "Manager One",
            "filing_date": "2024-05-16",
            "report_date": "2024-03-31",
            "ticker": "AAA",
            "shares": 20,
            "previous_shares": 100,
            "market_value": 2500,
        },
    ]
    events = build_13f_backtest_events(rows, _prices(), actions={"new"})
    assert len(events) == 1
    event = events[0]
    assert event["action"] == "new"
    assert event["tradable_date"] == "2024-02-19"
    assert event["forward_return_30d"] is not None
    assert event["forward_return_60d"] is not None
    assert event["forward_return_90d"] is not None
    assert event["forward_return_120d"] is not None
    assert event["forward_return_150d"] is not None
    assert event["excess_return_180d"] is not None
    assert event["hold_exit_date"] == "2024-05-17"
    assert event["hold_duration_days"] is not None
    assert event["hold_until_exit_return"] is not None
    assert event["hold_until_exit_excess_return"] is not None
    assert event["hold_until_exit_cagr"] is not None
    assert event["hold_until_exit_max_drawdown"] is not None


def test_manager_quality_scores_prior_completed_events():
    events = [
        {"manager_id": "good", "manager_name": "Good", "excess_return_30d": 0.02, "excess_return_60d": 0.04, "excess_return_90d": 0.08},
        {"manager_id": "good", "manager_name": "Good", "excess_return_30d": 0.01, "excess_return_60d": 0.03, "excess_return_90d": 0.06},
        {"manager_id": "bad", "manager_name": "Bad", "excess_return_30d": -0.01, "excess_return_60d": -0.02, "excess_return_90d": -0.04},
    ]
    scores = score_manager_quality(events)
    assert scores[0]["manager_id"] == "good"
    assert scores[0]["hit_rate_90d"] == 1.0
    assert scores[0]["manager_quality_score"] > scores[1]["manager_quality_score"]
