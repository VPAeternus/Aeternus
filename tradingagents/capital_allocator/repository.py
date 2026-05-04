"""SQLite WAL repository for Capital Allocator v1 intents and receipts."""

from __future__ import annotations

import datetime as dt
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional, Sequence

from tradingagents.dealflow.canonical_json import canonical_hash

from .contracts import (
    AllocationIntent,
    AssetClassId,
    ExecutionMode,
    FundingSourceStatus,
    IntentStatus,
    Lane,
    MarketSnapshot,
    ValuationMethodology,
)


ACTIVE_RESERVATION_STATES = (
    IntentStatus.PROPOSED.value,
    IntentStatus.VALIDATED.value,
    IntentStatus.VALIDATED_WAIT_FUNDING.value,
    IntentStatus.SUBMITTED.value,
)


class MirrorIntentError(RuntimeError):
    """Raised when mirror challenge/confirm transitions fail deterministic checks."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = str(code or "").upper().strip()


class SQLiteAllocatorRepository:
    """Persistence layer for outbox intents, validations, order trail, and receipts."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            self._apply_pragmas(conn)
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
                CREATE TABLE IF NOT EXISTS allocator_intents (
                  intent_id TEXT PRIMARY KEY,
                  run_id TEXT NOT NULL,
                  lane TEXT NOT NULL,
                  symbol TEXT NOT NULL,
                  asset_id TEXT NOT NULL DEFAULT '',
                  asset_class_id TEXT NOT NULL DEFAULT 'LISTED_EQUITY',
                  valuation_methodology TEXT NOT NULL DEFAULT 'MARK_TO_MARKET',
                  execution_mode TEXT NOT NULL DEFAULT 'LIVE',
                  side TEXT NOT NULL,
                  target_notional_usd REAL NOT NULL,
                  correlation_group_tag TEXT NOT NULL DEFAULT 'UNCLASSIFIED',
                  funding_source_status TEXT NOT NULL DEFAULT 'UNFUNDED',
                  funding_available_at_utc TEXT,
                  funding_reservation_id TEXT,
                  snapshot_id TEXT NOT NULL,
                  snapshot_hash_canonical TEXT NOT NULL,
                  snapshot_hash_raw TEXT NOT NULL DEFAULT '',
                  last_valuation_at_utc TEXT,
                  expected_edge_bps REAL NOT NULL DEFAULT 0.0,
                  adjusted_edge_bps REAL NOT NULL DEFAULT 0.0,
                  max_slippage_bps REAL NOT NULL DEFAULT 150.0,
                  created_at_utc TEXT NOT NULL,
                  expires_at_utc TEXT NOT NULL,
                  status TEXT NOT NULL,
                  idempotency_key TEXT NOT NULL UNIQUE,
                  reason_code TEXT NOT NULL DEFAULT '',
                  reason TEXT NOT NULL DEFAULT '',
                  updated_at_utc TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_allocator_intents_status_created
                  ON allocator_intents(status, created_at_utc);

                CREATE INDEX IF NOT EXISTS idx_allocator_intents_symbol
                  ON allocator_intents(symbol, created_at_utc);

                CREATE UNIQUE INDEX IF NOT EXISTS idx_allocator_active_funding_reservation
                  ON allocator_intents(funding_reservation_id)
                  WHERE funding_reservation_id IS NOT NULL
                    AND status IN ('PROPOSED', 'VALIDATED', 'VALIDATED_WAIT_FUNDING', 'SUBMITTED');

                CREATE TABLE IF NOT EXISTS allocator_validations (
                  intent_id TEXT PRIMARY KEY REFERENCES allocator_intents(intent_id),
                  validated_at_utc TEXT NOT NULL,
                  max_slippage_bps REAL NOT NULL,
                  validation_price REAL NOT NULL,
                  price_source_latency_ms INTEGER NOT NULL,
                  rejection_code TEXT NOT NULL DEFAULT '',
                  rejection_reason TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS allocator_orders (
                  order_id TEXT PRIMARY KEY,
                  intent_id TEXT NOT NULL REFERENCES allocator_intents(intent_id),
                  broker_order_id TEXT,
                  submitted_at_utc TEXT,
                  submit_price REAL,
                  status TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_allocator_orders_intent
                  ON allocator_orders(intent_id, submitted_at_utc);

                CREATE TABLE IF NOT EXISTS allocator_fills (
                  fill_id TEXT PRIMARY KEY,
                  order_id TEXT NOT NULL REFERENCES allocator_orders(order_id),
                  broker_fill_id TEXT,
                  tax_lot_id TEXT,
                  fill_time_utc TEXT NOT NULL,
                  qty REAL NOT NULL,
                  price REAL NOT NULL,
                  fee_usd REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_allocator_fills_order
                  ON allocator_fills(order_id, fill_time_utc);

                CREATE TABLE IF NOT EXISTS allocator_receipts (
                  receipt_id TEXT PRIMARY KEY,
                  intent_id TEXT NOT NULL REFERENCES allocator_intents(intent_id),
                  terminal_status TEXT NOT NULL,
                  reason_code TEXT NOT NULL,
                  reason TEXT NOT NULL DEFAULT '',
                  decided_at_utc TEXT NOT NULL,
                  price_at_validation REAL,
                  price_at_submit REAL,
                  price_delta_bps REAL,
                  price_source_latency_ms INTEGER
                );

                CREATE INDEX IF NOT EXISTS idx_allocator_receipts_intent
                  ON allocator_receipts(intent_id, decided_at_utc);

                CREATE TABLE IF NOT EXISTS mirror_challenges (
                  challenge_id TEXT PRIMARY KEY,
                  intent_id TEXT NOT NULL REFERENCES allocator_intents(intent_id),
                  preview_hash TEXT NOT NULL,
                  status_at_issue TEXT NOT NULL,
                  issued_at_utc TEXT NOT NULL,
                  expires_at_utc TEXT NOT NULL,
                  used_at_utc TEXT,
                  used_by TEXT NOT NULL DEFAULT '',
                  created_by TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_mirror_challenges_intent
                  ON mirror_challenges(intent_id, issued_at_utc);

                CREATE TABLE IF NOT EXISTS user_consent_log (
                  consent_id TEXT PRIMARY KEY,
                  intent_id TEXT NOT NULL REFERENCES allocator_intents(intent_id),
                  challenge_id TEXT NOT NULL REFERENCES mirror_challenges(challenge_id),
                  user_id TEXT NOT NULL DEFAULT '',
                  timestamp_utc TEXT NOT NULL,
                  interaction_type TEXT NOT NULL DEFAULT 'HOLD_TO_FOLLOW',
                  legal_version TEXT NOT NULL DEFAULT '',
                  consent_hash TEXT NOT NULL,
                  preview_hash TEXT NOT NULL,
                  client_preview_hash TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_user_consent_intent
                  ON user_consent_log(intent_id, timestamp_utc);

                CREATE TABLE IF NOT EXISTS market_snapshot (
                  symbol TEXT PRIMARY KEY,
                  snapshot_time_utc TEXT NOT NULL,
                  price REAL NOT NULL,
                  adv30_notional_usd REAL,
                  vol20d_bps REAL,
                  spread_bps REAL NOT NULL DEFAULT 0.0,
                  source_latency_ms INTEGER NOT NULL DEFAULT 0,
                  updated_at_utc TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS portfolio_metrics (
                  key TEXT PRIMARY KEY,
                  value_real REAL NOT NULL,
                  updated_at TEXT NOT NULL
                );
                """
            )
            # Backward-compatible migrations for previously initialized DB files.
            self._ensure_column(conn, "allocator_intents", "asset_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(
                conn,
                "allocator_intents",
                "asset_class_id",
                "TEXT NOT NULL DEFAULT 'LISTED_EQUITY'",
            )
            self._ensure_column(
                conn,
                "allocator_intents",
                "valuation_methodology",
                "TEXT NOT NULL DEFAULT 'MARK_TO_MARKET'",
            )
            self._ensure_column(
                conn,
                "allocator_intents",
                "execution_mode",
                "TEXT NOT NULL DEFAULT 'LIVE'",
            )
            self._ensure_column(conn, "allocator_intents", "last_valuation_at_utc", "TEXT")
            self._ensure_column(conn, "allocator_fills", "broker_fill_id", "TEXT")
            self._ensure_column(conn, "allocator_fills", "tax_lot_id", "TEXT")

    def insert_intent(self, intent: AllocationIntent) -> AllocationIntent:
        timestamp = _utc_iso(dt.datetime.now(dt.timezone.utc))
        with self.connection() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO allocator_intents (
                      intent_id, run_id, lane, symbol, asset_id, asset_class_id,
                      valuation_methodology, execution_mode, side, target_notional_usd,
                      correlation_group_tag, funding_source_status, funding_available_at_utc,
                      funding_reservation_id, snapshot_id, snapshot_hash_canonical, snapshot_hash_raw,
                      last_valuation_at_utc,
                      expected_edge_bps, adjusted_edge_bps, max_slippage_bps,
                      created_at_utc, expires_at_utc, status, idempotency_key,
                      reason_code, reason, updated_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        intent.intent_id,
                        intent.run_id,
                        intent.lane.value,
                        intent.symbol.upper(),
                        intent.asset_id,
                        intent.asset_class_id.value,
                        intent.valuation_methodology.value,
                        intent.execution_mode.value,
                        intent.side.upper(),
                        float(intent.target_notional_usd),
                        intent.correlation_group_tag or "UNCLASSIFIED",
                        intent.funding_source_status.value,
                        _utc_iso_or_none(intent.funding_available_at_utc),
                        intent.funding_reservation_id,
                        intent.snapshot_id,
                        intent.snapshot_hash_canonical,
                        intent.snapshot_hash_raw,
                        _utc_iso_or_none(intent.last_valuation_at_utc),
                        float(intent.expected_edge_bps),
                        float(intent.adjusted_edge_bps),
                        float(intent.max_slippage_bps),
                        _utc_iso(intent.created_at_utc),
                        _utc_iso(intent.expires_at_utc),
                        intent.status.value,
                        intent.idempotency_key,
                        intent.reason_code,
                        intent.reason,
                        timestamp,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                existing = self.get_intent_by_idempotency(intent.idempotency_key, conn=conn)
                if existing is not None:
                    return existing
                raise RuntimeError(f"Unable to insert intent {intent.intent_id}: {exc}") from exc
        return intent

    def get_intent(self, intent_id: str, *, conn: Optional[sqlite3.Connection] = None) -> Optional[AllocationIntent]:
        query = "SELECT * FROM allocator_intents WHERE intent_id = ?"
        if conn is not None:
            row = conn.execute(query, (intent_id,)).fetchone()
            return _row_to_intent(row) if row else None
        with self.connection() as owned_conn:
            row = owned_conn.execute(query, (intent_id,)).fetchone()
            return _row_to_intent(row) if row else None

    def get_intent_by_idempotency(
        self,
        idempotency_key: str,
        *,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Optional[AllocationIntent]:
        query = "SELECT * FROM allocator_intents WHERE idempotency_key = ?"
        if conn is not None:
            row = conn.execute(query, (idempotency_key,)).fetchone()
            return _row_to_intent(row) if row else None
        with self.connection() as owned_conn:
            row = owned_conn.execute(query, (idempotency_key,)).fetchone()
            return _row_to_intent(row) if row else None

    def list_intents(
        self,
        *,
        status: Optional[IntentStatus] = None,
        limit: int = 500,
    ) -> list[AllocationIntent]:
        with self.connection() as conn:
            if status is None:
                rows = conn.execute(
                    "SELECT * FROM allocator_intents ORDER BY created_at_utc DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM allocator_intents WHERE status = ? ORDER BY created_at_utc DESC LIMIT ?",
                    (status.value, int(limit)),
                ).fetchall()
        return [_row_to_intent(row) for row in rows]

    def fetch_proposed(self, *, now_utc: dt.datetime, limit: int = 500) -> list[AllocationIntent]:
        _ = now_utc  # retained for protocol compatibility and future filtering.
        return self.list_intents(status=IntentStatus.PROPOSED, limit=limit)

    def fetch_validated_ready(self, *, now_utc: dt.datetime, limit: int = 500) -> list[AllocationIntent]:
        now_iso = _utc_iso(now_utc)
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM allocator_intents
                WHERE status = 'VALIDATED'
                  AND expires_at_utc >= ?
                  AND (
                        funding_source_status != 'PENDING_SALE_PROCEEDS'
                        OR funding_available_at_utc IS NULL
                        OR funding_available_at_utc <= ?
                      )
                ORDER BY created_at_utc ASC
                LIMIT ?
                """,
                (now_iso, now_iso, int(limit)),
            ).fetchall()
        return [_row_to_intent(row) for row in rows]

    def update_status(
        self,
        intent_id: str,
        *,
        status: IntentStatus,
        reason_code: str = "",
        reason: str = "",
    ) -> None:
        updated_at = _utc_iso(dt.datetime.now(dt.timezone.utc))
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE allocator_intents
                SET status = ?, reason_code = ?, reason = ?, updated_at_utc = ?
                WHERE intent_id = ?
                """,
                (status.value, reason_code, reason, updated_at, intent_id),
            )

    def update_expectations(
        self,
        intent_id: str,
        *,
        expected_edge_bps: float,
        adjusted_edge_bps: float,
    ) -> None:
        updated_at = _utc_iso(dt.datetime.now(dt.timezone.utc))
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE allocator_intents
                SET expected_edge_bps = ?, adjusted_edge_bps = ?, updated_at_utc = ?
                WHERE intent_id = ?
                """,
                (float(expected_edge_bps), float(adjusted_edge_bps), updated_at, intent_id),
            )

    def save_validation(
        self,
        *,
        intent_id: str,
        validated_at_utc: dt.datetime,
        max_slippage_bps: float,
        validation_price: float,
        price_source_latency_ms: int,
        rejection_code: str = "",
        rejection_reason: str = "",
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO allocator_validations (
                  intent_id, validated_at_utc, max_slippage_bps,
                  validation_price, price_source_latency_ms, rejection_code, rejection_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(intent_id) DO UPDATE SET
                  validated_at_utc = excluded.validated_at_utc,
                  max_slippage_bps = excluded.max_slippage_bps,
                  validation_price = excluded.validation_price,
                  price_source_latency_ms = excluded.price_source_latency_ms,
                  rejection_code = excluded.rejection_code,
                  rejection_reason = excluded.rejection_reason
                """,
                (
                    intent_id,
                    _utc_iso(validated_at_utc),
                    float(max_slippage_bps),
                    float(validation_price),
                    int(price_source_latency_ms),
                    rejection_code,
                    rejection_reason,
                ),
            )

    def create_mirror_challenge(
        self,
        *,
        intent_id: str,
        now_utc: dt.datetime,
        ttl_seconds: float = 300.0,
        created_by: str = "operator-ui",
        allowed_statuses: Optional[Sequence[IntentStatus]] = None,
    ) -> dict:
        now = _as_utc(now_utc)
        allowed = {
            status.value
            for status in (
                allowed_statuses
                if allowed_statuses is not None
                else (IntentStatus.VALIDATED, IntentStatus.VALIDATED_WAIT_FUNDING)
            )
        }
        expires_at = now + dt.timedelta(seconds=max(1.0, float(ttl_seconds)))
        with self.connection() as conn:
            intent = self.get_intent(intent_id, conn=conn)
            if intent is None:
                raise MirrorIntentError("INTENT_NOT_FOUND", f"Intent not found: {intent_id}")
            if intent.status.value not in allowed:
                raise MirrorIntentError(
                    "INTENT_NOT_READY",
                    f"Intent {intent_id} status {intent.status.value} is not mirror-confirmable.",
                )
            if intent.expires_at_utc <= now:
                raise MirrorIntentError(
                    "EXPIRED_INTENT",
                    f"Intent {intent_id} expired at {intent.expires_at_utc.isoformat()}",
                )
            challenge_id = str(uuid.uuid4())
            preview_hash = canonical_hash(_mirror_preview_payload(intent))
            conn.execute(
                """
                INSERT INTO mirror_challenges (
                  challenge_id, intent_id, preview_hash, status_at_issue,
                  issued_at_utc, expires_at_utc, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    challenge_id,
                    intent.intent_id,
                    preview_hash,
                    intent.status.value,
                    _utc_iso(now),
                    _utc_iso(expires_at),
                    str(created_by or ""),
                ),
            )
        return {
            "intent_id": intent_id,
            "challenge_id": challenge_id,
            "preview_hash": preview_hash,
            "issued_at_utc": _utc_iso(now),
            "expires_at_utc": _utc_iso(expires_at),
            "status": intent.status.value,
            "symbol": intent.symbol,
            "side": intent.side,
            "target_notional_usd": float(intent.target_notional_usd),
        }

    def confirm_mirror_intent(
        self,
        *,
        intent_id: str,
        challenge_id: str,
        client_preview_hash: str,
        user_id: str,
        interaction_type: str,
        legal_version: str,
        now_utc: dt.datetime,
        allowed_statuses: Optional[Sequence[IntentStatus]] = None,
    ) -> dict:
        now = _as_utc(now_utc)
        allowed = {
            status.value
            for status in (
                allowed_statuses
                if allowed_statuses is not None
                else (IntentStatus.VALIDATED, IntentStatus.VALIDATED_WAIT_FUNDING)
            )
        }
        with self.connection() as conn:
            intent = self.get_intent(intent_id, conn=conn)
            if intent is None:
                raise MirrorIntentError("INTENT_NOT_FOUND", f"Intent not found: {intent_id}")

            challenge = conn.execute(
                """
                SELECT challenge_id, intent_id, preview_hash, status_at_issue, issued_at_utc,
                       expires_at_utc, used_at_utc
                FROM mirror_challenges
                WHERE challenge_id = ? AND intent_id = ?
                """,
                (challenge_id, intent.intent_id),
            ).fetchone()
            if challenge is None:
                raise MirrorIntentError("CHALLENGE_NOT_FOUND", f"Challenge not found: {challenge_id}")
            if str(challenge["used_at_utc"] or ""):
                raise MirrorIntentError("CHALLENGE_ALREADY_USED", "Challenge already consumed.")
            if _parse_utc(str(challenge["expires_at_utc"])) <= now:
                raise MirrorIntentError("CHALLENGE_EXPIRED", "Challenge expired. Refresh mirror preview.")
            if str(intent.status.value) != str(challenge["status_at_issue"]):
                raise MirrorIntentError(
                    "CONFLICT_INTENT_CHANGED",
                    "Intent changed since preview. Refresh and review latest move.",
                )
            if intent.status.value not in allowed:
                raise MirrorIntentError(
                    "INTENT_NOT_READY",
                    f"Intent {intent.intent_id} status {intent.status.value} is not mirror-confirmable.",
                )
            if intent.expires_at_utc <= now:
                conn.execute(
                    """
                    UPDATE allocator_intents
                    SET status = ?, reason_code = ?, reason = ?, updated_at_utc = ?
                    WHERE intent_id = ?
                    """,
                    (
                        IntentStatus.EXPIRED_INTENT.value,
                        IntentStatus.EXPIRED_INTENT.value,
                        "Intent expired before mirror confirmation.",
                        _utc_iso(now),
                        intent.intent_id,
                    ),
                )
                raise MirrorIntentError("EXPIRED_INTENT", "Intent expired before mirror confirmation.")
            server_preview_hash = str(challenge["preview_hash"] or "")
            if str(client_preview_hash or "") != server_preview_hash:
                raise MirrorIntentError(
                    "CONFLICT_PREVIEW_HASH_MISMATCH",
                    "Preview hash mismatch. Refresh mirror preview.",
                )

            consent_id = str(uuid.uuid4())
            consent_payload = {
                "consent_id": consent_id,
                "intent_id": intent.intent_id,
                "challenge_id": challenge_id,
                "user_id": str(user_id or ""),
                "timestamp_utc": _utc_iso(now),
                "interaction_type": str(interaction_type or "HOLD_TO_FOLLOW"),
                "legal_version": str(legal_version or ""),
                "preview_hash": server_preview_hash,
            }
            consent_hash = canonical_hash(consent_payload)
            conn.execute(
                """
                INSERT INTO user_consent_log (
                  consent_id, intent_id, challenge_id, user_id, timestamp_utc,
                  interaction_type, legal_version, consent_hash, preview_hash, client_preview_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    consent_id,
                    intent.intent_id,
                    challenge_id,
                    str(user_id or ""),
                    _utc_iso(now),
                    str(interaction_type or "HOLD_TO_FOLLOW"),
                    str(legal_version or ""),
                    consent_hash,
                    server_preview_hash,
                    str(client_preview_hash or ""),
                ),
            )
            conn.execute(
                """
                UPDATE mirror_challenges
                SET used_at_utc = ?, used_by = ?
                WHERE challenge_id = ? AND intent_id = ?
                """,
                (
                    _utc_iso(now),
                    str(user_id or ""),
                    challenge_id,
                    intent.intent_id,
                ),
            )
            conn.execute(
                """
                UPDATE allocator_intents
                SET status = ?, reason_code = ?, reason = ?, updated_at_utc = ?
                WHERE intent_id = ?
                """,
                (
                    IntentStatus.SUBMITTED.value,
                    "MIRROR_CONFIRMED",
                    "Mirror follow confirmed by user consent.",
                    _utc_iso(now),
                    intent.intent_id,
                ),
            )

            order_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO allocator_orders (
                  order_id, intent_id, status, submitted_at_utc, submit_price
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    intent.intent_id,
                    IntentStatus.SUBMITTED.value,
                    _utc_iso(now),
                    None,
                ),
            )
        return {
            "intent_id": intent_id,
            "challenge_id": challenge_id,
            "consent_id": consent_id,
            "consent_hash": consent_hash,
            "status_before": intent.status.value,
            "status_after": IntentStatus.SUBMITTED.value,
            "confirmed_at_utc": _utc_iso(now),
            "order_id": order_id,
            "reason_code": "MIRROR_CONFIRMED",
        }

    def save_terminal_receipt(
        self,
        *,
        intent_id: str,
        terminal_status: IntentStatus,
        reason_code: str,
        reason: str,
        decided_at_utc: dt.datetime,
        price_at_validation: Optional[float] = None,
        price_at_submit: Optional[float] = None,
        price_delta_bps: Optional[float] = None,
        price_source_latency_ms: Optional[int] = None,
    ) -> str:
        receipt_id = str(uuid.uuid4())
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO allocator_receipts (
                  receipt_id, intent_id, terminal_status, reason_code, reason,
                  decided_at_utc, price_at_validation, price_at_submit,
                  price_delta_bps, price_source_latency_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    intent_id,
                    terminal_status.value,
                    reason_code,
                    reason,
                    _utc_iso(decided_at_utc),
                    price_at_validation,
                    price_at_submit,
                    price_delta_bps,
                    price_source_latency_ms,
                ),
            )
        return receipt_id

    def list_receipts(self, *, intent_id: Optional[str] = None) -> list[sqlite3.Row]:
        with self.connection() as conn:
            if intent_id:
                rows = conn.execute(
                    "SELECT * FROM allocator_receipts WHERE intent_id = ? ORDER BY decided_at_utc ASC",
                    (intent_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM allocator_receipts ORDER BY decided_at_utc ASC"
                ).fetchall()
        return rows

    def upsert_market_snapshot(self, snapshot: MarketSnapshot) -> None:
        now_iso = _utc_iso(dt.datetime.now(dt.timezone.utc))
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO market_snapshot (
                  symbol, snapshot_time_utc, price, adv30_notional_usd, vol20d_bps,
                  spread_bps, source_latency_ms, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                  snapshot_time_utc = excluded.snapshot_time_utc,
                  price = excluded.price,
                  adv30_notional_usd = excluded.adv30_notional_usd,
                  vol20d_bps = excluded.vol20d_bps,
                  spread_bps = excluded.spread_bps,
                  source_latency_ms = excluded.source_latency_ms,
                  updated_at_utc = excluded.updated_at_utc
                """,
                (
                    snapshot.symbol.upper(),
                    _utc_iso(snapshot.snapshot_time_utc),
                    float(snapshot.price),
                    snapshot.adv30_notional_usd,
                    snapshot.vol20d_bps,
                    float(snapshot.spread_bps),
                    int(snapshot.source_latency_ms),
                    now_iso,
                ),
            )

    def get_market_snapshot(self, symbol: str) -> Optional[MarketSnapshot]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM market_snapshot WHERE symbol = ?",
                (str(symbol).upper(),),
            ).fetchone()
        if row is None:
            return None
        return MarketSnapshot(
            symbol=str(row["symbol"]),
            snapshot_time_utc=_parse_utc(str(row["snapshot_time_utc"])),
            price=float(row["price"]),
            adv30_notional_usd=(
                float(row["adv30_notional_usd"]) if row["adv30_notional_usd"] is not None else None
            ),
            vol20d_bps=float(row["vol20d_bps"]) if row["vol20d_bps"] is not None else None,
            spread_bps=float(row["spread_bps"]),
            source_latency_ms=int(row["source_latency_ms"]),
        )

    def read_high_water_mark(self) -> Optional[float]:
        """Read the persisted portfolio high-water mark NAV."""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT value_real FROM portfolio_metrics WHERE key = 'high_water_mark'"
            ).fetchone()
            return float(row["value_real"]) if row else None

    def update_high_water_mark(self, nav_usd: float) -> None:
        """Update the high-water mark if nav_usd exceeds current value."""
        with self.connection() as conn:
            current = conn.execute(
                "SELECT value_real FROM portfolio_metrics WHERE key = 'high_water_mark'"
            ).fetchone()
            if current is None or float(nav_usd) > float(current["value_real"]):
                conn.execute(
                    """INSERT INTO portfolio_metrics (key, value_real, updated_at)
                       VALUES ('high_water_mark', ?, ?)
                       ON CONFLICT(key) DO UPDATE SET value_real=excluded.value_real,
                       updated_at=excluded.updated_at""",
                    (float(nav_usd), dt.datetime.utcnow().isoformat()),
                )

    def insert_fill(
        self,
        *,
        fill_id: str,
        order_id: str,
        fill_time_utc: dt.datetime,
        qty: float,
        price: float,
        fee_usd: float,
        broker_fill_id: Optional[str] = None,
        tax_lot_id: Optional[str] = None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO allocator_fills (
                  fill_id, order_id, broker_fill_id, tax_lot_id, fill_time_utc, qty, price, fee_usd
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fill_id,
                    order_id,
                    broker_fill_id,
                    tax_lot_id,
                    _utc_iso(fill_time_utc),
                    float(qty),
                    float(price),
                    float(fee_usd),
                ),
            )

    def mark_order_submitted(
        self,
        *,
        order_id: str,
        broker_order_id: Optional[str],
        submitted_at_utc: dt.datetime,
        status: str = IntentStatus.SUBMITTED.value,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE allocator_orders
                SET broker_order_id = ?, submitted_at_utc = ?, status = ?
                WHERE order_id = ?
                """,
                (
                    broker_order_id,
                    _utc_iso(submitted_at_utc),
                    str(status or IntentStatus.SUBMITTED.value),
                    order_id,
                ),
            )

    @staticmethod
    def _apply_pragmas(conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=5000;")

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        names = {str(row[1]) for row in rows}
        if column in names:
            return
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _row_to_intent(row: sqlite3.Row) -> AllocationIntent:
    return AllocationIntent(
        intent_id=str(row["intent_id"]),
        run_id=str(row["run_id"]),
        lane=_parse_enum(Lane, row["lane"], Lane.CORE),
        symbol=str(row["symbol"]),
        asset_id=str(row["asset_id"] or ""),
        asset_class_id=_parse_enum(AssetClassId, row["asset_class_id"], AssetClassId.LISTED_EQUITY),
        valuation_methodology=_parse_enum(
            ValuationMethodology,
            row["valuation_methodology"],
            ValuationMethodology.MARK_TO_MARKET,
        ),
        execution_mode=_parse_enum(ExecutionMode, row["execution_mode"], ExecutionMode.LIVE),
        side=str(row["side"]),
        target_notional_usd=float(row["target_notional_usd"]),
        correlation_group_tag=str(row["correlation_group_tag"]),
        funding_source_status=_parse_enum(
            FundingSourceStatus,
            row["funding_source_status"],
            FundingSourceStatus.UNFUNDED,
        ),
        funding_available_at_utc=_parse_utc_or_none(row["funding_available_at_utc"]),
        funding_reservation_id=row["funding_reservation_id"],
        snapshot_id=str(row["snapshot_id"]),
        snapshot_hash_canonical=str(row["snapshot_hash_canonical"]),
        snapshot_hash_raw=str(row["snapshot_hash_raw"] or ""),
        last_valuation_at_utc=_parse_utc_or_none(row["last_valuation_at_utc"]),
        max_slippage_bps=float(row["max_slippage_bps"]),
        created_at_utc=_parse_utc(str(row["created_at_utc"])),
        expires_at_utc=_parse_utc(str(row["expires_at_utc"])),
        status=_parse_enum(IntentStatus, row["status"], IntentStatus.PROPOSED),
        idempotency_key=str(row["idempotency_key"]),
        expected_edge_bps=float(row["expected_edge_bps"]),
        adjusted_edge_bps=float(row["adjusted_edge_bps"]),
        reason_code=str(row["reason_code"] or ""),
        reason=str(row["reason"] or ""),
    )


def _utc_iso(value: dt.datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    else:
        value = value.astimezone(dt.timezone.utc)
    return value.isoformat()


def _utc_iso_or_none(value: Optional[dt.datetime]) -> Optional[str]:
    if value is None:
        return None
    return _utc_iso(value)


def _parse_utc(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    else:
        parsed = parsed.astimezone(dt.timezone.utc)
    return parsed


def _parse_utc_or_none(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    return _parse_utc(str(value))


def _parse_enum(enum_cls, raw_value, default):
    if raw_value is None:
        return default
    try:
        return enum_cls(str(raw_value))
    except Exception:
        return default


def _as_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _mirror_preview_payload(intent: AllocationIntent) -> dict:
    return {
        "intent_id": intent.intent_id,
        "lane": intent.lane.value,
        "symbol": intent.symbol,
        "side": intent.side,
        "target_notional_usd": float(intent.target_notional_usd),
        "correlation_group_tag": intent.correlation_group_tag,
        "funding_source_status": intent.funding_source_status.value,
        "snapshot_id": intent.snapshot_id,
        "snapshot_hash_canonical": intent.snapshot_hash_canonical,
        "max_slippage_bps": float(intent.max_slippage_bps),
        "expires_at_utc": _utc_iso(intent.expires_at_utc),
    }
