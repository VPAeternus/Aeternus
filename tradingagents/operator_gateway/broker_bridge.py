"""Broker adapter bridge for mirror-intent confirm flow."""

from __future__ import annotations

from typing import Dict, Any

from tradingagents.broker_adapters import AlpacaBrokerAdapter, BaseBrokerAdapter, MockBrokerAdapter


class BrokerAdapterDisabledError(RuntimeError):
    """Raised when mirror confirmation is attempted without broker adapter configured."""


def build_broker_adapter(config: Dict[str, Any]) -> BaseBrokerAdapter:
    adapter_name = str(config.get("operator_gateway_broker_adapter", "disabled")).strip().lower()
    if adapter_name in {"", "disabled", "none", "off"}:
        raise BrokerAdapterDisabledError("BROKER_ADAPTER_DISABLED")
    if adapter_name == "mock":
        return MockBrokerAdapter()
    if adapter_name == "alpaca":
        return AlpacaBrokerAdapter()
    raise BrokerAdapterDisabledError(f"BROKER_ADAPTER_UNSUPPORTED:{adapter_name}")

