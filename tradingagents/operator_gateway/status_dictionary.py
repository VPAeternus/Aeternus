"""Humanized allocator status dictionary for concise user-facing copy."""

from __future__ import annotations

from typing import Dict


STATUS_DICTIONARY_VERSION = "2026-02-08.v1"


_STATUS_MESSAGE: Dict[str, str] = {
    "VALIDATED": "Ready to mirror.",
    "VALIDATED_WAIT_FUNDING": "Waiting for cash to settle before mirroring.",
    "SUBMITTED": "Order sent to broker.",
    "FILLED": "Mirrored successfully.",
    "REJECTED_IMPACT_VETO": "Too much market traffic right now. We are waiting for a safer entry.",
    "REJECTED_COVARIANCE_VETO": "Keeping your portfolio balanced across themes.",
    "REJECTED_COVARIANCE_UNMODELED_SYMBOL": "Skipping an unmodeled symbol to protect balance.",
    "REJECTED_LIABILITY_HURDLE": "Not enough edge after costs. Waiting for a better opportunity.",
    "REJECTED_PRICE_SLIP": "Price moved too far from what you approved.",
    "REJECTED_FUNDING": "Insufficient available buying power for this move.",
    "EXPIRED_INTENT": "This mirror window expired. Review the latest model move.",
    "EXPIRED_FUNDING_WINDOW": "Funding arrived too late for this mirror window.",
    "PROPOSED": "Queued for allocator validation.",
}


_REASON_CODE_MESSAGE: Dict[str, str] = {
    "SCHEDULE_UNKNOWN": "Aeternus timing is temporarily unavailable.",
    "SYSTEM_HALT_ACTIVE": "Safety pause is active. Monitoring continues.",
    "SNAPSHOT_STALE": "Data is out of date. Mirroring is paused.",
    "SNAPSHOT_INVALID": "Current data cannot be verified. Mirroring is paused.",
    "MIRROR_CONFIRMED": "Follow confirmed.",
    "CONFLICT_INTENT_CHANGED": "Market conditions updated. Please review the latest mirror window.",
    "CONFLICT_PREVIEW_HASH_MISMATCH": "The reviewed move changed. Please refresh before following.",
    "CHALLENGE_EXPIRED": "Mirror window expired. Please review the latest model move.",
    "CHALLENGE_ALREADY_USED": "This mirror window was already used.",
    "LEGAL_CONSENT_REQUIRED": "Accept the service agreement before following model moves.",
    "BROKER_ADAPTER_DISABLED": "Broker connection is not configured yet.",
}


def humanize_allocator_status(
    *,
    status: str = "",
    reason_code: str = "",
    reason: str = "",
) -> str:
    """Return concise UI-safe messaging for intent state."""
    code = str(reason_code or "").strip().upper()
    state = str(status or "").strip().upper()
    if code and code in _REASON_CODE_MESSAGE:
        return _REASON_CODE_MESSAGE[code]
    if state and state in _STATUS_MESSAGE:
        return _STATUS_MESSAGE[state]
    if reason:
        return str(reason).strip()
    return "Awaiting update."


def status_dictionary_snapshot() -> Dict[str, object]:
    """Expose dictionary for UI/localization tooling."""
    return {
        "version": STATUS_DICTIONARY_VERSION,
        "status_messages": dict(_STATUS_MESSAGE),
        "reason_code_messages": dict(_REASON_CODE_MESSAGE),
    }
