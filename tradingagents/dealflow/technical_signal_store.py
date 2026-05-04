"""SQLite store for cached technical universe, history, and signal state."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence


class SQLiteTechnicalSignalStore:
    """Persistence layer for the technical signal cache."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS universe_membership_current (
                  source_index TEXT NOT NULL,
                  ticker TEXT NOT NULL,
                  company_name TEXT NOT NULL DEFAULT '',
                  sector TEXT NOT NULL DEFAULT '',
                  as_of_date TEXT NOT NULL,
                  fetched_at_utc TEXT NOT NULL,
                  PRIMARY KEY (source_index, ticker)
                );

                CREATE TABLE IF NOT EXISTS market_history_daily (
                  ticker TEXT NOT NULL,
                  date TEXT NOT NULL,
                  open REAL NOT NULL,
                  high REAL NOT NULL,
                  low REAL NOT NULL,
                  close REAL NOT NULL,
                  volume REAL NOT NULL,
                  source TEXT NOT NULL DEFAULT 'yfinance',
                  updated_at_utc TEXT NOT NULL,
                  PRIMARY KEY (ticker, date)
                );

                CREATE TABLE IF NOT EXISTS signal_kama_fvg_daily (
                  ticker TEXT NOT NULL,
                  date TEXT NOT NULL,
                  fast_kama REAL,
                  slow_kama REAL,
                  kama_spread_pct REAL,
                  cross_up INTEGER NOT NULL DEFAULT 0,
                  bullish_state INTEGER NOT NULL DEFAULT 0,
                  bullish_fvg_regime_active INTEGER NOT NULL DEFAULT 0,
                  bullish_fvg_streak INTEGER NOT NULL DEFAULT 0,
                  bullish_fvg_regime_age_bars INTEGER NOT NULL DEFAULT 0,
                  buy_zone INTEGER NOT NULL DEFAULT 0,
                  buy_zone_reason TEXT NOT NULL DEFAULT '',
                  score REAL NOT NULL DEFAULT 0.0,
                  computed_at_utc TEXT NOT NULL,
                  PRIMARY KEY (ticker, date)
                );

                CREATE TABLE IF NOT EXISTS buy_zone_state_current (
                  ticker TEXT PRIMARY KEY,
                  as_of_date TEXT NOT NULL,
                  in_buy_zone INTEGER NOT NULL DEFAULT 0,
                  status_label TEXT NOT NULL DEFAULT 'NOT_IN_BUY_ZONE',
                  reason TEXT NOT NULL DEFAULT '',
                  last_cross_up_date TEXT,
                  bullish_fvg_regime_active INTEGER NOT NULL DEFAULT 0,
                  bullish_fvg_streak INTEGER NOT NULL DEFAULT 0,
                  bullish_fvg_regime_age_bars INTEGER NOT NULL DEFAULT 0,
                  fast_kama REAL,
                  slow_kama REAL,
                  score REAL NOT NULL DEFAULT 0.0,
                  updated_at_utc TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS yahoo_symbol_status (
                  ticker TEXT PRIMARY KEY,
                  is_invalid INTEGER NOT NULL DEFAULT 0,
                  invalid_reason TEXT NOT NULL DEFAULT '',
                  no_data_before_date TEXT,
                  checked_through_date TEXT,
                  updated_at_utc TEXT NOT NULL
                );
                """
            )

    def upsert_universe_membership_current(self, rows: Sequence[dict[str, Any]]) -> None:
        if not rows:
            return
        with self.connection() as conn:
            conn.executemany(
                """
                INSERT INTO universe_membership_current (
                  source_index, ticker, company_name, sector, as_of_date, fetched_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_index, ticker) DO UPDATE SET
                  company_name = excluded.company_name,
                  sector = excluded.sector,
                  as_of_date = excluded.as_of_date,
                  fetched_at_utc = excluded.fetched_at_utc
                """,
                [
                    (
                        str(row.get("source_index", "")).upper().strip(),
                        str(row.get("ticker", "")).upper().strip(),
                        str(row.get("company_name", "")).strip(),
                        str(row.get("sector", "")).strip(),
                        str(row.get("as_of_date", "")).strip(),
                        str(row.get("fetched_at_utc", "")).strip(),
                    )
                    for row in rows
                ],
            )

    def list_universe_membership_current(self, *, exclude_invalid: bool = False) -> list[dict[str, Any]]:
        with self.connection() as conn:
            if exclude_invalid:
                rows = conn.execute(
                    """
                    SELECT source_index, ticker, company_name, sector, as_of_date, fetched_at_utc
                    FROM universe_membership_current
                    WHERE ticker NOT IN (
                      SELECT ticker FROM yahoo_symbol_status WHERE is_invalid = 1
                    )
                    ORDER BY ticker, source_index
                    """
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT source_index, ticker, company_name, sector, as_of_date, fetched_at_utc
                    FROM universe_membership_current
                    ORDER BY ticker, source_index
                    """
                ).fetchall()
        return [dict(row) for row in rows]

    def purge_tickers(self, tickers: Sequence[str]) -> None:
        normalized = sorted(
            {
                str(ticker or "").upper().strip()
                for ticker in tickers
                if str(ticker or "").strip()
            }
        )
        if not normalized:
            return
        placeholders = ",".join("?" for _ in normalized)
        with self.connection() as conn:
            conn.execute(
                f"DELETE FROM universe_membership_current WHERE ticker IN ({placeholders})",
                tuple(normalized),
            )
            conn.execute(
                f"DELETE FROM market_history_daily WHERE ticker IN ({placeholders})",
                tuple(normalized),
            )
            conn.execute(
                f"DELETE FROM signal_kama_fvg_daily WHERE ticker IN ({placeholders})",
                tuple(normalized),
            )
            conn.execute(
                f"DELETE FROM buy_zone_state_current WHERE ticker IN ({placeholders})",
                tuple(normalized),
            )

    def upsert_market_history(self, rows: Sequence[dict[str, Any]]) -> None:
        if not rows:
            return
        with self.connection() as conn:
            conn.executemany(
                """
                INSERT INTO market_history_daily (
                  ticker, date, open, high, low, close, volume, source, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, date) DO UPDATE SET
                  open = excluded.open,
                  high = excluded.high,
                  low = excluded.low,
                  close = excluded.close,
                  volume = excluded.volume,
                  source = excluded.source,
                  updated_at_utc = excluded.updated_at_utc
                """,
                [
                    (
                        str(row.get("ticker", "")).upper().strip(),
                        str(row.get("date", "")).strip(),
                        float(row.get("open", 0.0) or 0.0),
                        float(row.get("high", 0.0) or 0.0),
                        float(row.get("low", 0.0) or 0.0),
                        float(row.get("close", 0.0) or 0.0),
                        float(row.get("volume", 0.0) or 0.0),
                        str(row.get("source", "yfinance")).strip(),
                        str(row.get("updated_at_utc", "")).strip(),
                    )
                    for row in rows
                ],
            )

    def latest_market_history_date(self, ticker: str) -> str | None:
        normalized = str(ticker or "").upper().strip()
        if not normalized:
            return None
        with self.connection() as conn:
            row = conn.execute(
                "SELECT MAX(date) FROM market_history_daily WHERE ticker = ?",
                (normalized,),
            ).fetchone()
        value = row[0] if row else None
        return str(value) if value else None

    def earliest_market_history_date(self, ticker: str) -> str | None:
        normalized = str(ticker or "").upper().strip()
        if not normalized:
            return None
        with self.connection() as conn:
            row = conn.execute(
                "SELECT MIN(date) FROM market_history_daily WHERE ticker = ?",
                (normalized,),
            ).fetchone()
        value = row[0] if row else None
        return str(value) if value else None

    def load_market_history(self, ticker: str) -> list[dict[str, Any]]:
        normalized = str(ticker or "").upper().strip()
        if not normalized:
            return []
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT ticker, date, open, high, low, close, volume, source, updated_at_utc
                FROM market_history_daily
                WHERE ticker = ?
                ORDER BY date
                """,
                (normalized,),
            ).fetchall()
        return [dict(row) for row in rows]

    def replace_signal_rows(self, ticker: str, from_date: str, rows: Sequence[dict[str, Any]]) -> None:
        normalized = str(ticker or "").upper().strip()
        if not normalized:
            return
        with self.connection() as conn:
            conn.execute(
                "DELETE FROM signal_kama_fvg_daily WHERE ticker = ? AND date >= ?",
                (normalized, str(from_date).strip()),
            )
            if rows:
                conn.executemany(
                    """
                    INSERT INTO signal_kama_fvg_daily (
                      ticker, date, fast_kama, slow_kama, kama_spread_pct, cross_up, bullish_state,
                      bullish_fvg_regime_active, bullish_fvg_streak, bullish_fvg_regime_age_bars,
                      buy_zone, buy_zone_reason, score, computed_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            str(row.get("ticker", "")).upper().strip(),
                            str(row.get("date", "")).strip(),
                            _float_or_none(row.get("fast_kama")),
                            _float_or_none(row.get("slow_kama")),
                            _float_or_none(row.get("kama_spread_pct")),
                            int(bool(row.get("cross_up", False))),
                            int(bool(row.get("bullish_state", False))),
                            int(bool(row.get("bullish_fvg_regime_active", False))),
                            int(row.get("bullish_fvg_streak", 0) or 0),
                            int(row.get("bullish_fvg_regime_age_bars", 0) or 0),
                            int(bool(row.get("buy_zone", False))),
                            str(row.get("buy_zone_reason", "")).strip(),
                            float(row.get("score", 0.0) or 0.0),
                            str(row.get("computed_at_utc", "")).strip(),
                        )
                        for row in rows
                    ],
                )

    def load_signal_rows(self, ticker: str) -> list[dict[str, Any]]:
        normalized = str(ticker or "").upper().strip()
        if not normalized:
            return []
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT ticker, date, fast_kama, slow_kama, kama_spread_pct, cross_up, bullish_state,
                       bullish_fvg_regime_active, bullish_fvg_streak, bullish_fvg_regime_age_bars,
                       buy_zone, buy_zone_reason, score, computed_at_utc
                FROM signal_kama_fvg_daily
                WHERE ticker = ?
                ORDER BY date
                """,
                (normalized,),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_buy_zone_state(self, rows: Sequence[dict[str, Any]]) -> None:
        if not rows:
            return
        with self.connection() as conn:
            conn.executemany(
                """
                INSERT INTO buy_zone_state_current (
                  ticker, as_of_date, in_buy_zone, status_label, reason, last_cross_up_date,
                  bullish_fvg_regime_active, bullish_fvg_streak, bullish_fvg_regime_age_bars,
                  fast_kama, slow_kama, score, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                  as_of_date = excluded.as_of_date,
                  in_buy_zone = excluded.in_buy_zone,
                  status_label = excluded.status_label,
                  reason = excluded.reason,
                  last_cross_up_date = excluded.last_cross_up_date,
                  bullish_fvg_regime_active = excluded.bullish_fvg_regime_active,
                  bullish_fvg_streak = excluded.bullish_fvg_streak,
                  bullish_fvg_regime_age_bars = excluded.bullish_fvg_regime_age_bars,
                  fast_kama = excluded.fast_kama,
                  slow_kama = excluded.slow_kama,
                  score = excluded.score,
                  updated_at_utc = excluded.updated_at_utc
                """,
                [
                    (
                        str(row.get("ticker", "")).upper().strip(),
                        str(row.get("as_of_date", "")).strip(),
                        int(row.get("in_buy_zone", 0) or 0),
                        str(row.get("status_label", "NOT_IN_BUY_ZONE")).strip(),
                        str(row.get("reason", "")).strip(),
                        str(row.get("last_cross_up_date", "")).strip() or None,
                        int(row.get("bullish_fvg_regime_active", 0) or 0),
                        int(row.get("bullish_fvg_streak", 0) or 0),
                        int(row.get("bullish_fvg_regime_age_bars", 0) or 0),
                        _float_or_none(row.get("fast_kama")),
                        _float_or_none(row.get("slow_kama")),
                        float(row.get("score", 0.0) or 0.0),
                        str(row.get("updated_at_utc", "")).strip(),
                    )
                    for row in rows
                ],
            )

    def get_buy_zone_state(self, ticker: str) -> dict[str, Any] | None:
        normalized = str(ticker or "").upper().strip()
        if not normalized:
            return None
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT ticker, as_of_date, in_buy_zone, status_label, reason, last_cross_up_date,
                       bullish_fvg_regime_active, bullish_fvg_streak, bullish_fvg_regime_age_bars,
                       fast_kama, slow_kama, score, updated_at_utc
                FROM buy_zone_state_current
                WHERE ticker = ?
                """,
                (normalized,),
            ).fetchone()
        return dict(row) if row else None

    def list_buy_zone_states(self, status_labels: Sequence[str] | None = None) -> list[dict[str, Any]]:
        with self.connection() as conn:
            if status_labels:
                normalized = [str(label).strip().upper() for label in status_labels if str(label).strip()]
                placeholders = ",".join("?" for _ in normalized)
                rows = conn.execute(
                    f"""
                    SELECT ticker, as_of_date, in_buy_zone, status_label, reason, last_cross_up_date,
                           bullish_fvg_regime_active, bullish_fvg_streak, bullish_fvg_regime_age_bars,
                           fast_kama, slow_kama, score, updated_at_utc
                    FROM buy_zone_state_current
                    WHERE UPPER(status_label) IN ({placeholders})
                    ORDER BY score DESC, ticker
                    """,
                    tuple(normalized),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT ticker, as_of_date, in_buy_zone, status_label, reason, last_cross_up_date,
                           bullish_fvg_regime_active, bullish_fvg_streak, bullish_fvg_regime_age_bars,
                           fast_kama, slow_kama, score, updated_at_utc
                    FROM buy_zone_state_current
                    ORDER BY score DESC, ticker
                    """
                ).fetchall()
        return [dict(row) for row in rows]

    def upsert_yahoo_symbol_status(self, rows: Sequence[dict[str, Any]]) -> None:
        if not rows:
            return
        with self.connection() as conn:
            conn.executemany(
                """
                INSERT INTO yahoo_symbol_status (
                  ticker, is_invalid, invalid_reason, no_data_before_date,
                  checked_through_date, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                  is_invalid = excluded.is_invalid,
                  invalid_reason = excluded.invalid_reason,
                  no_data_before_date = excluded.no_data_before_date,
                  checked_through_date = excluded.checked_through_date,
                  updated_at_utc = excluded.updated_at_utc
                """,
                [
                    (
                        str(row.get("ticker", "")).upper().strip(),
                        int(bool(row.get("is_invalid", False))),
                        str(row.get("invalid_reason", "")).strip(),
                        str(row.get("no_data_before_date", "")).strip() or None,
                        str(row.get("checked_through_date", "")).strip() or None,
                        str(row.get("updated_at_utc", "")).strip(),
                    )
                    for row in rows
                    if str(row.get("ticker", "")).strip()
                ],
            )

    def get_yahoo_symbol_status(self, ticker: str) -> dict[str, Any] | None:
        normalized = str(ticker or "").upper().strip()
        if not normalized:
            return None
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT ticker, is_invalid, invalid_reason, no_data_before_date,
                       checked_through_date, updated_at_utc
                FROM yahoo_symbol_status
                WHERE ticker = ?
                """,
                (normalized,),
            ).fetchone()
        return dict(row) if row else None

    def list_invalid_yahoo_tickers(self) -> list[str]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT ticker
                FROM yahoo_symbol_status
                WHERE is_invalid = 1
                ORDER BY ticker
                """
            ).fetchall()
        return [str(row[0]) for row in rows]


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)
