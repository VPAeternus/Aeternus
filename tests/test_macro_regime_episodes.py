import pandas as pd

from tradingagents.backtesting.macro.regime_episodes import build_regime_episodes


def test_build_regime_episodes_closes_when_state_changes_and_measures_drawdown():
    rows = pd.DataFrame(
        [
            {"snapshot_date": "2026-01-02", "state": "A"},
            {"snapshot_date": "2026-01-09", "state": "A"},
            {"snapshot_date": "2026-01-16", "state": "B"},
            {"snapshot_date": "2026-01-23", "state": "B"},
            {"snapshot_date": "2026-01-30", "state": "A"},
        ]
    )
    prices = pd.DataFrame(
        {"SPY": [100.0, 90.0, 110.0, 105.0, 120.0]},
        index=pd.to_datetime(["2026-01-02", "2026-01-09", "2026-01-16", "2026-01-23", "2026-01-30"]),
    )

    episodes = build_regime_episodes(rows, prices, state_col="state", symbol="SPY")

    assert list(episodes["state"]) == ["A", "B", "A"]
    first = episodes.iloc[0]
    assert first["start_date"] == pd.Timestamp("2026-01-02")
    assert first["end_date"] == pd.Timestamp("2026-01-16")
    assert first["duration_weeks"] == 2
    assert first["entry_price"] == 100.0
    assert first["exit_price"] == 110.0
    assert round(first["episode_return"], 6) == 0.10
    assert round(first["max_drawdown_during_episode"], 6) == -0.10
    assert first["next_state"] == "B"


def test_build_regime_episodes_last_episode_exits_at_last_price():
    rows = pd.DataFrame(
        [
            {"snapshot_date": "2026-01-02", "state": "A"},
            {"snapshot_date": "2026-01-09", "state": "B"},
        ]
    )
    prices = pd.DataFrame({"SPY": [100.0, 95.0]}, index=pd.to_datetime(["2026-01-02", "2026-01-09"]))

    episodes = build_regime_episodes(rows, prices, state_col="state", symbol="SPY")

    last = episodes.iloc[-1]
    assert last["state"] == "B"
    assert pd.isna(last["next_state"])
    assert last["entry_price"] == 95.0
    assert last["exit_price"] == 95.0
    assert last["episode_return"] == 0.0
