import datetime as dt

from tradingagents.capital_allocator.market_snapshot_seed import (
    build_default_market_snapshots,
    seed_market_snapshot_cache,
)
from tradingagents.capital_allocator.repository import SQLiteAllocatorRepository


def test_build_default_market_snapshots_has_mixed_liquidity():
    snapshots = build_default_market_snapshots(
        as_of_utc=dt.datetime(2026, 2, 8, 15, 0, tzinfo=dt.timezone.utc)
    )
    assert len(snapshots) >= 8

    high = sum(1 for row in snapshots if float(row.adv30_notional_usd or 0.0) >= 1_000_000_000.0)
    medium = sum(
        1 for row in snapshots if 100_000_000.0 <= float(row.adv30_notional_usd or 0.0) < 1_000_000_000.0
    )
    low = sum(1 for row in snapshots if float(row.adv30_notional_usd or 0.0) < 100_000_000.0)

    assert high >= 2
    assert medium >= 1
    assert low >= 1


def test_seed_market_snapshot_cache_writes_rows(tmp_path):
    db_path = tmp_path / "capital_allocator.db"
    summary = seed_market_snapshot_cache(
        db_path=db_path,
        as_of_utc=dt.datetime(2026, 2, 8, 15, 0, tzinfo=dt.timezone.utc),
    )
    assert summary["seeded_count"] >= 8
    assert summary["liquidity_mix"]["LOW"] >= 1

    repo = SQLiteAllocatorRepository(db_path)
    repo.initialize()
    spy = repo.get_market_snapshot("SPY")
    remx = repo.get_market_snapshot("REMX")
    assert spy is not None
    assert remx is not None
    assert spy.adv30_notional_usd and spy.adv30_notional_usd > remx.adv30_notional_usd

