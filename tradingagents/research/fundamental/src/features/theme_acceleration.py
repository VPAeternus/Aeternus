from __future__ import annotations

from typing import Any

from src.features.common import clean


THEME_ACCELERATION_FLAG_FIELDS = [
    "filing_theme_growth_flag",
    "filing_theme_guidance_flag",
    "filing_theme_margin_flag",
    "filing_theme_customer_win_flag",
    "filing_theme_capacity_expansion_flag",
]

THEME_ACCELERATION_FIELDS = [
    *THEME_ACCELERATION_FLAG_FIELDS,
    "theme_acceleration_score",
]

THEME_ACCELERATION_WEIGHTS = {
    "filing_theme_growth_flag": 5,
    "filing_theme_guidance_flag": 5,
    "filing_theme_margin_flag": 3,
    "filing_theme_customer_win_flag": 3,
    "filing_theme_capacity_expansion_flag": 3,
}


def coerce_flag(raw: Any) -> int:
    if isinstance(raw, bool):
        return int(raw)
    text = clean(raw).lower()
    if text in {"1", "true", "yes", "y"}:
        return 1
    if text in {"0", "false", "no", "n", ""}:
        return 0
    try:
        return 1 if int(float(text)) != 0 else 0
    except Exception:
        raise ValueError(f"invalid theme acceleration flag: {raw!r}") from None


def has_theme_evidence(raw: Any) -> bool:
    if isinstance(raw, list):
        return any(clean(item) for item in raw)
    return bool(clean(raw))


def compute_theme_acceleration_score(payload: dict[str, Any]) -> int:
    """Compute deterministic filing-theme acceleration score.

    No evidence snippets means no acceleration score, even if flags are set.
    """
    if not has_theme_evidence(payload.get("theme_evidence")):
        return 0
    total = 0
    for field, weight in THEME_ACCELERATION_WEIGHTS.items():
        total += coerce_flag(payload.get(field)) * weight
    return min(15, int(total))


def normalized_theme_acceleration_fields(payload: dict[str, Any]) -> dict[str, int]:
    flags = {field: coerce_flag(payload.get(field)) for field in THEME_ACCELERATION_FLAG_FIELDS}
    return {**flags, "theme_acceleration_score": compute_theme_acceleration_score({**payload, **flags})}
