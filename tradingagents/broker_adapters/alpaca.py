"""Alpaca broker adapter for mirror-confirm order submission."""

from __future__ import annotations

import datetime as dt
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

import requests

from .base import BaseBrokerAdapter, BrokerOrderRequest, BrokerOrderResult

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_RETRY_DELAYS = [0.5, 1.0, 2.0]
_MAX_RETRIES = 3


def _resolve_alpaca_credentials() -> Tuple[str, str, str, float]:
    """Resolve Alpaca base URL, key ID, secret, and timeout from env vars.

    Uses paper trading URL by default; respects ALPACA_API_BASE_URL override.
    Credential resolution matches the pattern in paper_execution.py.
    """
    explicit_base = str(os.getenv("ALPACA_API_BASE_URL", "")).strip()
    if explicit_base:
        base_url = explicit_base
    else:
        base_url = str(
            os.getenv("ALPACA_PAPER_API_BASE_URL", "https://paper-api.alpaca.markets")
        ).strip()

    api_key_id = str(
        os.getenv("APCA_API_KEY_ID", "") or os.getenv("ALPACA_API_KEY_ID", "")
    ).strip()
    api_secret_key = str(
        os.getenv("APCA_API_SECRET_KEY", "") or os.getenv("ALPACA_API_SECRET_KEY", "")
    ).strip()
    timeout = max(1.0, float(os.getenv("ALPACA_REQUEST_TIMEOUT_SECONDS", "15")))

    # Strip trailing /v2 if present (normalize base URL)
    base = base_url.rstrip("/")
    if base.lower().endswith("/v2"):
        base = base[:-3]

    return base, api_key_id, api_secret_key, timeout


def _alpaca_headers(api_key_id: str, api_secret_key: str) -> Dict[str, str]:
    return {
        "APCA-API-KEY-ID": api_key_id,
        "APCA-API-SECRET-KEY": api_secret_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _compute_qty(notional_usd: float) -> Optional[float]:
    """Convert target notional to a notional-based order (fractional shares via notional field)."""
    val = max(0.0, float(notional_usd))
    if val <= 0.0:
        return None
    return round(val, 2)


class AlpacaBrokerAdapter(BaseBrokerAdapter):
    """Alpaca paper/live broker adapter for operator-supervised mirror-confirm execution."""

    adapter_name = "alpaca"

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrderResult:
        """Submit a notional order to Alpaca and return a normalized result.

        Uses notional ordering so the caller does not need to compute share counts.
        Retries on 429/500/502/503/504 with 0.5/1/2s backoff.
        """
        now_utc = request.requested_at_utc
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=dt.timezone.utc)
        else:
            now_utc = now_utc.astimezone(dt.timezone.utc)

        base_url, api_key_id, api_secret_key, timeout = _resolve_alpaca_credentials()
        if not api_key_id or not api_secret_key:
            logger.error("AlpacaBrokerAdapter: credentials missing.")
            return BrokerOrderResult(
                accepted=False,
                adapter_name=self.adapter_name,
                submission_status="REJECTED",
                message="Alpaca credentials missing. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY.",
                submitted_at_utc=now_utc,
            )

        notional = _compute_qty(request.target_notional_usd)
        if notional is None or notional <= 0.0:
            logger.error(
                "AlpacaBrokerAdapter: invalid notional %.2f for intent %s",
                request.target_notional_usd,
                request.intent_id,
            )
            return BrokerOrderResult(
                accepted=False,
                adapter_name=self.adapter_name,
                submission_status="REJECTED",
                message=f"Invalid target_notional_usd: {request.target_notional_usd}",
                submitted_at_utc=now_utc,
            )

        side = str(request.side or "").lower().strip()
        if side not in {"buy", "sell"}:
            return BrokerOrderResult(
                accepted=False,
                adapter_name=self.adapter_name,
                submission_status="REJECTED",
                message=f"Invalid order side: {request.side!r}",
                submitted_at_utc=now_utc,
            )

        client_order_id = f"mirror-{request.intent_id[:12]}-{request.consent_id[:8]}"[:48]
        payload: Dict[str, Any] = {
            "symbol": str(request.symbol).upper().strip(),
            "notional": str(notional),
            "side": side,
            "type": "market",
            "time_in_force": "day",
            "client_order_id": client_order_id,
        }

        url = f"{base_url}/v2/orders"
        headers = _alpaca_headers(api_key_id, api_secret_key)

        last_error: Optional[str] = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = requests.post(
                    url, headers=headers, json=payload, timeout=timeout
                )
            except requests.exceptions.RequestException as exc:
                last_error = str(exc)
                logger.warning(
                    "AlpacaBrokerAdapter: request error attempt %d/%d: %s",
                    attempt + 1,
                    _MAX_RETRIES,
                    last_error,
                )
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)])
                    continue
                return BrokerOrderResult(
                    accepted=False,
                    adapter_name=self.adapter_name,
                    submission_status="REJECTED",
                    message=f"Network error: {last_error}",
                    submitted_at_utc=now_utc,
                )

            if response.status_code in {200, 201}:
                try:
                    data = response.json()
                except ValueError:
                    data = {}
                broker_order_id = str(data.get("id", "")).strip()
                alpaca_status = str(data.get("status", "submitted")).strip()
                logger.info(
                    "AlpacaBrokerAdapter: accepted order %s status=%s for %s %s $%.2f",
                    broker_order_id,
                    alpaca_status,
                    side,
                    request.symbol,
                    notional,
                )
                return BrokerOrderResult(
                    accepted=True,
                    adapter_name=self.adapter_name,
                    broker_order_id=broker_order_id,
                    submission_status="SUBMITTED",
                    message=f"Alpaca accepted: status={alpaca_status}",
                    submitted_at_utc=now_utc,
                )

            if response.status_code in _RETRYABLE_STATUS_CODES and attempt < _MAX_RETRIES - 1:
                last_error = f"{response.status_code}: {response.text[:300]}"
                logger.warning(
                    "AlpacaBrokerAdapter: retryable %s attempt %d/%d",
                    response.status_code,
                    attempt + 1,
                    _MAX_RETRIES,
                )
                time.sleep(_RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)])
                continue

            detail = response.text[:500]
            logger.error(
                "AlpacaBrokerAdapter: order rejected (%s): %s", response.status_code, detail
            )
            return BrokerOrderResult(
                accepted=False,
                adapter_name=self.adapter_name,
                submission_status="REJECTED",
                message=f"Alpaca rejected ({response.status_code}): {detail}",
                submitted_at_utc=now_utc,
            )

        return BrokerOrderResult(
            accepted=False,
            adapter_name=self.adapter_name,
            submission_status="REJECTED",
            message=f"Alpaca order failed after {_MAX_RETRIES} retries: {last_error}",
            submitted_at_utc=now_utc,
        )

    def cancel_order(self, broker_order_id: str) -> Dict[str, Any]:
        """Cancel an open Alpaca order by broker order ID.

        Returns a dict with keys: broker_order_id, canceled (bool), message.
        Retries on 429/500/502/503/504 with 0.5/1/2s backoff.
        """
        order_id = str(broker_order_id or "").strip()
        if not order_id:
            raise ValueError("broker_order_id is required")

        base_url, api_key_id, api_secret_key, timeout = _resolve_alpaca_credentials()
        if not api_key_id or not api_secret_key:
            raise ValueError(
                "Alpaca credentials missing. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY."
            )

        headers = {
            "APCA-API-KEY-ID": api_key_id,
            "APCA-API-SECRET-KEY": api_secret_key,
            "Accept": "application/json",
        }
        url = f"{base_url}/v2/orders/{order_id}"

        last_error: Optional[str] = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = requests.delete(url, headers=headers, timeout=timeout)
            except requests.exceptions.RequestException as exc:
                last_error = str(exc)
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)])
                    continue
                raise ValueError(
                    f"Alpaca cancel_order network error after {_MAX_RETRIES} retries: {last_error}"
                ) from exc

            if response.status_code in {200, 204}:
                logger.info("AlpacaBrokerAdapter: canceled order %s", order_id)
                return {"broker_order_id": order_id, "canceled": True, "message": "Order canceled."}

            if response.status_code in _RETRYABLE_STATUS_CODES and attempt < _MAX_RETRIES - 1:
                last_error = f"{response.status_code}: {response.text[:300]}"
                time.sleep(_RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)])
                continue

            detail = response.text[:500]
            raise ValueError(
                f"Alpaca cancel_order failed ({response.status_code}): {detail}"
            )

        raise ValueError(
            f"Alpaca cancel_order failed after {_MAX_RETRIES} retries: {last_error}"
        )

    def get_positions(self) -> Dict[str, Any]:
        """Fetch open positions from Alpaca.

        Returns dict with key ``positions`` (list of Alpaca position objects).
        """
        base_url, api_key_id, api_secret_key, timeout = _resolve_alpaca_credentials()
        if not api_key_id or not api_secret_key:
            raise ValueError(
                "Alpaca credentials missing. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY."
            )

        headers = {
            "APCA-API-KEY-ID": api_key_id,
            "APCA-API-SECRET-KEY": api_secret_key,
            "Accept": "application/json",
        }
        url = f"{base_url}/v2/positions"
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.status_code != 200:
            detail = response.text[:500]
            raise ValueError(f"Alpaca get_positions failed ({response.status_code}): {detail}")
        return {"positions": response.json()}

    def get_account(self) -> Dict[str, Any]:
        """Fetch Alpaca account details.

        Returns the raw Alpaca account payload dict.
        """
        base_url, api_key_id, api_secret_key, timeout = _resolve_alpaca_credentials()
        if not api_key_id or not api_secret_key:
            raise ValueError(
                "Alpaca credentials missing. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY."
            )

        headers = {
            "APCA-API-KEY-ID": api_key_id,
            "APCA-API-SECRET-KEY": api_secret_key,
            "Accept": "application/json",
        }
        url = f"{base_url}/v2/account"
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.status_code != 200:
            detail = response.text[:500]
            raise ValueError(f"Alpaca get_account failed ({response.status_code}): {detail}")
        return response.json()

    def get_json(
        self,
        endpoint: str,
        method: str = "GET",
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        base_url_override: Optional[str] = None,
        max_retries: int = 3,
    ) -> Tuple[Optional[Any], Optional[str]]:
        """Generic Alpaca API call. Returns (payload, error_string).

        endpoint: e.g. "/v2/clock", "/v2/orders", "/v2/account"
        base_url_override: use this base URL instead of the env-resolved one
            (allows paper vs live routing from paper_execution.py callers).
        Matches the (payload, error) return signature used by _alpaca_get_json
        in paper_execution.py.
        """
        resolved_base, api_key_id, api_secret_key, timeout = _resolve_alpaca_credentials()
        if not api_key_id or not api_secret_key:
            return None, "Alpaca credentials missing. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY."

        base = (str(base_url_override).rstrip("/") if base_url_override else resolved_base)
        headers = _alpaca_headers(api_key_id, api_secret_key)
        url = f"{base}/{str(endpoint).lstrip('/')}"
        delays = [0.5, 1.0, 2.0]
        last_error: Optional[str] = None
        for attempt in range(max_retries):
            try:
                if method.upper() == "GET":
                    resp = requests.get(url, headers=headers, params=params, timeout=timeout)
                elif method.upper() == "POST":
                    resp = requests.post(
                        url, headers=headers, json=json_body, timeout=timeout
                    )
                elif method.upper() == "DELETE":
                    resp = requests.delete(
                        url, headers=headers, params=params, timeout=timeout
                    )
                else:
                    return None, f"Unsupported method: {method}"
            except requests.exceptions.RequestException as exc:
                last_error = str(exc)
                if attempt < max_retries - 1:
                    time.sleep(delays[min(attempt, len(delays) - 1)])
                    continue
                return None, last_error

            if resp.status_code in (200, 201, 207):
                try:
                    return resp.json(), None
                except ValueError:
                    return None, "Invalid JSON payload"
            if resp.status_code == 204:
                return None, None  # No-content success
            if resp.status_code in _RETRYABLE_STATUS_CODES and attempt < max_retries - 1:
                last_error = f"{resp.status_code}: {resp.text[:300]}"
                time.sleep(delays[min(attempt, len(delays) - 1)])
                continue
            return None, f"{resp.status_code}: {resp.text[:300]}"

        return None, last_error
