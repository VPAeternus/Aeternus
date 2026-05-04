"""Deterministic market snapshot cache seeding for allocator simulations."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Iterable, Sequence

from .contracts import MarketSnapshot
from .repository import SQLiteAllocatorRepository


DEFAULT_MIXED_LIQUIDITY_SNAPSHOTS: Sequence[dict[str, float | int | str]] = (
    # High liquidity (core index + mega caps)
    {"symbol": "SPY", "price": 603.25, "adv30_notional_usd": 42_000_000_000.0, "vol20d_bps": 120.0, "spread_bps": 0.4, "source_latency_ms": 120},
    {"symbol": "QQQ", "price": 525.60, "adv30_notional_usd": 24_000_000_000.0, "vol20d_bps": 145.0, "spread_bps": 0.5, "source_latency_ms": 130},
    {"symbol": "AAPL", "price": 225.10, "adv30_notional_usd": 16_000_000_000.0, "vol20d_bps": 155.0, "spread_bps": 0.8, "source_latency_ms": 150},
    {"symbol": "NVDA", "price": 715.40, "adv30_notional_usd": 28_000_000_000.0, "vol20d_bps": 240.0, "spread_bps": 1.0, "source_latency_ms": 170},
    # Medium liquidity (satellite/thematic)
    {"symbol": "SMH", "price": 246.35, "adv30_notional_usd": 1_400_000_000.0, "vol20d_bps": 220.0, "spread_bps": 1.2, "source_latency_ms": 180},
    {"symbol": "XLE", "price": 89.20, "adv30_notional_usd": 950_000_000.0, "vol20d_bps": 180.0, "spread_bps": 1.4, "source_latency_ms": 180},
    {"symbol": "URA", "price": 29.10, "adv30_notional_usd": 320_000_000.0, "vol20d_bps": 260.0, "spread_bps": 2.3, "source_latency_ms": 210},
    # Low liquidity (impact-gate stress names)
    {"symbol": "REMX", "price": 43.85, "adv30_notional_usd": 48_000_000.0, "vol20d_bps": 310.0, "spread_bps": 4.8, "source_latency_ms": 260},
    {"symbol": "LIT", "price": 63.40, "adv30_notional_usd": 92_000_000.0, "vol20d_bps": 280.0, "spread_bps": 3.9, "source_latency_ms": 240},
    {"symbol": "XME", "price": 59.65, "adv30_notional_usd": 74_000_000.0, "vol20d_bps": 295.0, "spread_bps": 4.1, "source_latency_ms": 250},
)


def build_default_market_snapshots(
    *,
    as_of_utc: dt.datetime | None = None,
) -> list[MarketSnapshot]:
    """Build deterministic mixed-liquidity snapshots for simulator cache."""
    timestamp = _normalize_utc(as_of_utc or dt.datetime.now(dt.timezone.utc))
    snapshots: list[MarketSnapshot] = []
    for row in DEFAULT_MIXED_LIQUIDITY_SNAPSHOTS:
        snapshots.append(
            MarketSnapshot(
                symbol=str(row["symbol"]).upper(),
                snapshot_time_utc=timestamp,
                price=float(row["price"]),
                adv30_notional_usd=float(row["adv30_notional_usd"]),
                vol20d_bps=float(row["vol20d_bps"]),
                spread_bps=float(row["spread_bps"]),
                source_latency_ms=int(row["source_latency_ms"]),
            )
        )
    return snapshots


def seed_market_snapshot_cache(
    *,
    db_path: str | Path,
    snapshots: Iterable[MarketSnapshot] | None = None,
    as_of_utc: dt.datetime | None = None,
) -> dict[str, object]:
    """Seed/refresh market snapshot cache rows in allocator DB."""
    path = Path(db_path)
    repo = SQLiteAllocatorRepository(path)
    repo.initialize()
    effective_snapshots = list(snapshots or build_default_market_snapshots(as_of_utc=as_of_utc))
    for snapshot in effective_snapshots:
        repo.upsert_market_snapshot(snapshot)

    symbols = sorted({snapshot.symbol.upper() for snapshot in effective_snapshots})
    summary = _summarize_liquidity(effective_snapshots)
    return {
        "db_path": str(path),
        "as_of_utc": _normalize_utc(as_of_utc or dt.datetime.now(dt.timezone.utc)).isoformat(),
        "seeded_count": len(effective_snapshots),
        "symbols": symbols,
        "liquidity_mix": summary,
    }


def _summarize_liquidity(snapshots: Iterable[MarketSnapshot]) -> dict[str, int]:
    out = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for snapshot in snapshots:
        adv = float(snapshot.adv30_notional_usd or 0.0)
        if adv >= 1_000_000_000.0:
            out["HIGH"] += 1
        elif adv >= 100_000_000.0:
            out["MEDIUM"] += 1
        else:
            out["LOW"] += 1
    return out


def _normalize_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)

