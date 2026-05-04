"""Deterministic JSON canonicalization helpers for control-plane lineage."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


_FLOAT_QUANTUM = Decimal("0.000001")


class CanonicalizationError(ValueError):
    """Raised when an object cannot be canonically represented."""


def canonicalize(obj: Any) -> Any:
    """Normalize an object into a deterministic, JSON-safe representation."""
    if obj is None:
        return None
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, str):
        return obj
    if isinstance(obj, float):
        return _canonicalize_float(obj)
    if isinstance(obj, Decimal):
        return _canonicalize_decimal(obj)
    if isinstance(obj, datetime):
        return _canonicalize_datetime(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, time):
        if obj.tzinfo is None:
            return obj.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        return obj.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(obj, dict):
        return {
            str(key): canonicalize(obj[key])
            for key in sorted(obj.keys(), key=lambda value: str(value))
        }
    if isinstance(obj, (list, tuple)):
        return [canonicalize(item) for item in obj]
    if isinstance(obj, set):
        normalized = [canonicalize(item) for item in obj]
        normalized.sort(key=lambda value: json.dumps(value, separators=(",", ":"), sort_keys=True))
        return normalized

    if hasattr(obj, "isoformat") and callable(getattr(obj, "isoformat")):
        return str(obj.isoformat())

    raise CanonicalizationError(f"Unsupported type for canonicalization: {type(obj)!r}")


def canonical_dumps(obj: Any) -> str:
    """Render canonical JSON text with deterministic separators."""
    normalized = canonicalize(obj)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_hash(obj: Any) -> str:
    """Compute SHA-256 of canonical JSON bytes."""
    canonical_str = canonical_dumps(obj)
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()


def _canonicalize_float(value: float) -> float:
    if not math.isfinite(value):
        raise CanonicalizationError(f"Non-finite float is not allowed: {value!r}")
    quantized = Decimal(str(value)).quantize(_FLOAT_QUANTUM, rounding=ROUND_HALF_UP)
    return float(quantized)


def _canonicalize_decimal(value: Decimal) -> float:
    if not value.is_finite():
        raise CanonicalizationError(f"Non-finite Decimal is not allowed: {value!r}")
    quantized = value.quantize(_FLOAT_QUANTUM, rounding=ROUND_HALF_UP)
    return float(quantized)


def _canonicalize_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    # Keep microsecond precision if present; canonical UTC suffix is always Z.
    return value.isoformat().replace("+00:00", "Z")
