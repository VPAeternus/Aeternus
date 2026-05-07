"""Alpaca client helpers split from graph.paper_execution."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from tradingagents.broker_adapters.alpaca import AlpacaBrokerAdapter

from .constants import EXECUTION_MODE_ALPACA_LIVE
from .modes import normalize_execution_mode


RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def normalize_alpaca_base_url(raw_url: str) -> str:
    text = str(raw_url or "").strip().rstrip("/")
    if text.lower().endswith("/v2"):
        text = text[:-3]
    return text


def resolve_alpaca_credentials(mode: str) -> tuple[str, str, str, float]:
    normalized_mode = normalize_execution_mode(mode)
    explicit_base = str(os.getenv("ALPACA_API_BASE_URL", "")).strip()
    if explicit_base:
        base_url = explicit_base
    elif normalized_mode == EXECUTION_MODE_ALPACA_LIVE:
        base_url = str(
            os.getenv("ALPACA_LIVE_API_BASE_URL", "https://api.alpaca.markets")
        ).strip()
    else:
        base_url = str(
            os.getenv(
                "ALPACA_PAPER_API_BASE_URL", "https://paper-api.alpaca.markets"
            )
        ).strip()

    api_key_id = str(
        os.getenv("APCA_API_KEY_ID", "") or os.getenv("ALPACA_API_KEY_ID", "")
    ).strip()
    api_secret_key = str(
        os.getenv("APCA_API_SECRET_KEY", "") or os.getenv("ALPACA_API_SECRET_KEY", "")
    ).strip()
    timeout = max(
        1.0,
        float(os.getenv("ALPACA_REQUEST_TIMEOUT_SECONDS", "15")),
    )
    return normalize_alpaca_base_url(base_url), api_key_id, api_secret_key, timeout


def alpaca_headers(api_key_id: str, api_secret_key: str) -> Dict[str, str]:
    return {
        "APCA-API-KEY-ID": api_key_id,
        "APCA-API-SECRET-KEY": api_secret_key,
        "Accept": "application/json",
    }


def get_broker_adapter() -> AlpacaBrokerAdapter:
    """Return a module-level singleton AlpacaBrokerAdapter."""
    if not hasattr(get_broker_adapter, "_instance"):
        get_broker_adapter._instance = AlpacaBrokerAdapter()  # type: ignore[attr-defined]
    return get_broker_adapter._instance  # type: ignore[attr-defined]


def alpaca_get_json(
    base_url: str,
    endpoint: str,
    headers: Dict[str, str],
    timeout_seconds: float,
    params: Optional[Dict[str, Any]] = None,
    max_retries: int = 3,
) -> tuple[Any, Optional[str]]:
    """Delegate to AlpacaBrokerAdapter.get_json(). Preserves (payload, error) signature."""
    return get_broker_adapter().get_json(
        endpoint=endpoint,
        method="GET",
        params=params,
        base_url_override=base_url,
        max_retries=max_retries,
    )


def submit_alpaca_order(
    base_url: str,
    api_key_id: str,
    api_secret_key: str,
    payload: Dict[str, Any],
    timeout_seconds: float,
    max_retries: int = 3,
) -> Dict[str, Any]:
    """Delegate to AlpacaBrokerAdapter.get_json(). Raises ValueError on failure."""
    data, error = get_broker_adapter().get_json(
        endpoint="/v2/orders",
        method="POST",
        json_body=payload,
        base_url_override=base_url,
        max_retries=max_retries,
    )
    if error:
        raise ValueError(f"Alpaca order submit failed: {error}")
    if not isinstance(data, dict):
        raise ValueError("Alpaca order submit returned invalid payload.")
    return data


def format_qty(quantity: float) -> str:
    text = f"{float(quantity):.6f}".rstrip("0").rstrip(".")
    return text if text else "0"
