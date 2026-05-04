from tradingagents.context.event_state import get_event_state


def test_event_state_triggers_on_spy_and_vix_moves_without_macro_labels():
    payload = get_event_state(
        as_of_date="2026-03-22",
        config={
            "dealflow_trigger_vix_jump_pct": 15.0,
            "dealflow_trigger_spy_move_pct": 1.5,
        },
        market_shock_provider=lambda: (2.1, 18.5),
    )

    assert payload["as_of_date"] == "2026-03-22"
    assert payload["triggered"] is True
    assert payload["reasons"] == ["VIX jump 18.50%", "SPY move 2.10%"]
    assert payload["metrics"] == {
        "vix_jump_pct": 18.5,
        "spy_move_pct": 2.1,
    }


def test_event_state_returns_not_triggered_when_market_move_is_below_threshold():
    payload = get_event_state(
        as_of_date="2026-03-22",
        config={
            "dealflow_trigger_vix_jump_pct": 15.0,
            "dealflow_trigger_spy_move_pct": 1.5,
        },
        market_shock_provider=lambda: (0.8, 4.2),
    )

    assert payload["triggered"] is False
    assert payload["reasons"] == []
    assert payload["metrics"] == {
        "vix_jump_pct": 4.2,
        "spy_move_pct": 0.8,
    }
