import pytest

from tradingagents.evidence.pipeline import (
    _derive_status,
    _runtime_alert_or_raise,
)


def test_derive_status_requires_complete_regime_coverage_for_complete():
    assert (
        _derive_status(
            sample_days=250,
            windows_count=4,
            walkforward_status="COMPLETE",
            regime_slices=6,
            complete_regime_coverage=True,
        )
        == "COMPLETE"
    )
    assert (
        _derive_status(
            sample_days=250,
            windows_count=4,
            walkforward_status="COMPLETE",
            regime_slices=6,
            complete_regime_coverage=False,
        )
        == "PARTIAL_DATA"
    )


def test_runtime_alert_soft_cap_and_hard_cap_behavior():
    assert (
        _runtime_alert_or_raise(
            runtime_seconds=12.0,
            soft_cap_seconds=10.0,
            hard_cap_seconds=20.0,
        )
        == "SOFT_CAP_EXCEEDED"
    )
    with pytest.raises(TimeoutError):
        _runtime_alert_or_raise(
            runtime_seconds=21.0,
            soft_cap_seconds=10.0,
            hard_cap_seconds=20.0,
        )
