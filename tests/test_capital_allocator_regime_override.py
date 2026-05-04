import datetime as dt

from tradingagents.capital_allocator.contracts import RegimeShock
from tradingagents.capital_allocator.regime_override import (
    read_regime_override,
    resolve_regime,
    write_regime_override,
)


def test_write_and_resolve_regime_override(tmp_path):
    path = tmp_path / "allocator_regime_override.json"
    payload = write_regime_override(
        path=path,
        regime=RegimeShock.CRISIS,
        reason="shock test",
        source="operator",
        now=dt.datetime(2026, 2, 8, 15, 0, tzinfo=dt.timezone.utc),
    )
    assert payload["regime"] == RegimeShock.CRISIS.value

    loaded = read_regime_override(path)
    assert loaded["reason"] == "shock test"
    resolved = resolve_regime(path=path, default=RegimeShock.NORMAL)
    assert resolved == RegimeShock.CRISIS


def test_resolve_regime_override_defaults_on_invalid_value(tmp_path):
    path = tmp_path / "allocator_regime_override.json"
    path.write_text('{"regime":"NOT_A_REAL_REGIME"}')
    resolved = resolve_regime(path=path, default=RegimeShock.STRESS)
    assert resolved == RegimeShock.STRESS

