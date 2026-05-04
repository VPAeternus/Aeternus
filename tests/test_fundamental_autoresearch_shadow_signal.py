from tradingagents.research.fundamental_autoresearch.shadow_signal import (
    CANONICAL_SHADOW_STRATEGY,
    compute_shadow_fundamental_signal,
)


def test_compute_shadow_fundamental_signal_uses_canonical_strategy_and_overlay_formula():
    fundamental_sub = {
        "quality": 80,
        "growth": 70,
        "health": 90,
        "valuation": 50,
    }

    payload = compute_shadow_fundamental_signal(
        fundamental_sub,
        gate_status="PASSED",
        recommended_status="shadow",
    )

    expected_score = round((90 * 0.5) + ((100 - 80) * 0.4) + ((100 - 70) * 0.1), 2)
    assert payload["strategy"] == CANONICAL_SHADOW_STRATEGY
    assert payload["score"] == expected_score
    assert payload["gate_status"] == "PASSED"
    assert payload["recommended_status"] == "shadow"
    assert payload["label"] in {"UNDERAPPRECIATED_RESILIENCE", "BALANCED", "CROWDING_RISK"}


def test_compute_shadow_fundamental_signal_returns_empty_when_no_fundamentals():
    payload = compute_shadow_fundamental_signal(None)

    assert payload["strategy"] == CANONICAL_SHADOW_STRATEGY
    assert payload["score"] is None
    assert payload["label"] is None
    assert payload["notes"] is None
