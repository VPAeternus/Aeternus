"""Base broker adapter contract for mirror-confirmed order submission."""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class BrokerOrderRequest:
    """Canonical broker order request derived from allocator mirror intent."""

    intent_id: str
    symbol: str
    side: str
    target_notional_usd: float
    lane: str
    consent_id: str
    challenge_id: str
    requested_at_utc: dt.datetime


@dataclass(frozen=True)
class BrokerOrderResult:
    """Normalized broker order submission result."""

    accepted: bool
    adapter_name: str
    broker_order_id: str = ""
    submission_status: str = "REJECTED"
    message: str = ""
    submitted_at_utc: Optional[dt.datetime] = None


class BaseBrokerAdapter(ABC):
    """Abstract interface for broker-specific submission implementations."""

    adapter_name: str

    @abstractmethod
    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrderResult:
        raise NotImplementedError

