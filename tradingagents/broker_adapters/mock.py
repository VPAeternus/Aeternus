"""Mock broker adapter for deterministic non-live handshake testing."""

from __future__ import annotations

import datetime as dt
import uuid

from .base import BaseBrokerAdapter, BrokerOrderRequest, BrokerOrderResult


class MockBrokerAdapter(BaseBrokerAdapter):
    """In-process mock adapter that acknowledges submissions deterministically."""

    adapter_name = "mock"

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrderResult:
        now = request.requested_at_utc
        if now.tzinfo is None:
            now = now.replace(tzinfo=dt.timezone.utc)
        else:
            now = now.astimezone(dt.timezone.utc)
        broker_order_id = f"mock-{request.intent_id[:8]}-{uuid.uuid4().hex[:8]}"
        return BrokerOrderResult(
            accepted=True,
            adapter_name=self.adapter_name,
            broker_order_id=broker_order_id,
            submission_status="SUBMITTED",
            message="Mock adapter accepted order.",
            submitted_at_utc=now,
        )

