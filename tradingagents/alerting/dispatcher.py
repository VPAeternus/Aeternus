"""Push alert dispatcher with webhook support (Slack, Discord, generic HTTP)."""

import logging
import requests
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class WebhookChannel:
    """Delivers alerts to a webhook URL (Slack, Discord, or generic HTTP POST)."""

    def __init__(self, url: str, name: str = "webhook", timeout: float = 10.0):
        self.url = url
        self.name = name
        self.timeout = timeout

    def send(self, message: str, severity: str = "INFO", metadata: Optional[Dict] = None) -> bool:
        """Send alert. Returns True on success."""
        # For Slack-compatible webhooks, use {"text": message}
        # For generic, use {"message": message, "severity": severity, **metadata}
        payload = {
            "text": f"[{severity}] {message}",  # Slack-compatible
            "message": message,
            "severity": severity,
            **(metadata or {}),
        }
        try:
            resp = requests.post(self.url, json=payload, timeout=self.timeout)
            ok = resp.status_code in {200, 201, 204}
            if not ok:
                logger.warning("Alert delivery failed to %s: %d", self.name, resp.status_code)
            return ok
        except Exception as exc:
            logger.error("Alert delivery error to %s: %s", self.name, exc)
            return False


class AlertDispatcher:
    """Routes alerts to configured channels."""

    def __init__(self, channels: Optional[List[WebhookChannel]] = None, config: Optional[Dict] = None):
        self.channels = list(channels or [])
        if not self.channels and config:
            # Auto-configure from config
            url = str(config.get("alerting_webhook_url", "") or "").strip()
            if url:
                self.channels.append(WebhookChannel(url=url, name="primary"))

    def alert(self, message: str, severity: str = "INFO", metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """Send alert to all channels. Returns delivery summary."""
        results = {}
        for ch in self.channels:
            results[ch.name] = ch.send(message, severity=severity, metadata=metadata)
        if not self.channels:
            logger.debug("No alert channels configured, message dropped: %s", message[:100])
        return {"delivered": sum(1 for v in results.values() if v), "total": len(results), "channels": results}

    def circuit_breaker_tripped(self, breaches: list, nlv: float) -> Dict[str, Any]:
        msg = f"CIRCUIT BREAKER TRIPPED (NLV=${nlv:,.2f}): {'; '.join(breaches)}"
        return self.alert(msg, severity="CRITICAL", metadata={"event": "circuit_breaker", "nlv": nlv})

    def system_halt_activated(self, reason: str, set_by: str) -> Dict[str, Any]:
        msg = f"SYSTEM HALT activated by {set_by}: {reason}"
        return self.alert(msg, severity="WARNING", metadata={"event": "system_halt"})

    def order_filled(self, symbol: str, side: str, qty: float, price: float) -> Dict[str, Any]:
        msg = f"Order filled: {side} {qty} {symbol} @ ${price:.2f}"
        return self.alert(msg, severity="INFO", metadata={"event": "order_fill", "symbol": symbol})

    def reconciliation_mismatch(self, drift_usd: float, details: str) -> Dict[str, Any]:
        msg = f"Reconciliation mismatch: drift=${drift_usd:,.2f} — {details}"
        return self.alert(msg, severity="WARNING", metadata={"event": "recon_mismatch"})

    def pnl_threshold_alert(self, symbol: str, unrealized_pnl_usd: float, unrealized_return_pct: float, threshold_pct: float) -> Dict[str, Any]:
        msg = (
            f"P&L threshold breach: {symbol} unrealized loss={unrealized_return_pct:.2f}% "
            f"(${unrealized_pnl_usd:,.2f}) exceeds -{threshold_pct * 100:.1f}% threshold"
        )
        return self.alert(msg, severity="WARNING", metadata={
            "event": "pnl_threshold",
            "symbol": symbol,
            "unrealized_pnl_usd": unrealized_pnl_usd,
            "unrealized_return_pct": unrealized_return_pct,
        })

    def latency_alert(self, operation: str, elapsed_seconds: float, threshold_seconds: float) -> Dict[str, Any]:
        msg = f"Execution latency warning: {operation} took {elapsed_seconds:.1f}s (threshold={threshold_seconds:.0f}s)"
        return self.alert(msg, severity="WARNING", metadata={
            "event": "latency_warning",
            "operation": operation,
            "elapsed_seconds": elapsed_seconds,
            "threshold_seconds": threshold_seconds,
        })
