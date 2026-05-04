from typing import Any, Dict, Optional


CANONICAL_SHADOW_STRATEGY = "health_0p5__inv_growth_0p1__inv_quality_0p4"
DEFAULT_GATE_STATUS = "PASSED"
DEFAULT_RECOMMENDED_STATUS = "shadow"


def _label_for_score(score: float) -> tuple[str, str]:
    if score >= 70:
        return (
            "UNDERAPPRECIATED_RESILIENCE",
            "Canonical health-led shadow signal sees resilience with less crowded growth/quality expectations.",
        )
    if score <= 40:
        return (
            "CROWDING_RISK",
            "Canonical health-led shadow signal sees visible growth/quality expectations crowding out resilience.",
        )
    return (
        "BALANCED",
        "Canonical health-led shadow signal is mixed; use as advisory context only.",
    )


def compute_shadow_fundamental_signal(
    fundamental_sub: Optional[Dict[str, int]],
    *,
    gate_status: str = DEFAULT_GATE_STATUS,
    recommended_status: str = DEFAULT_RECOMMENDED_STATUS,
) -> Dict[str, Any]:
    if not fundamental_sub:
        return {
            "strategy": CANONICAL_SHADOW_STRATEGY,
            "score": None,
            "label": None,
            "notes": None,
            "gate_status": gate_status,
            "recommended_status": recommended_status,
        }

    score = round(
        (fundamental_sub["health"] * 0.5)
        + ((100 - fundamental_sub["quality"]) * 0.4)
        + ((100 - fundamental_sub["growth"]) * 0.1),
        2,
    )
    label, notes = _label_for_score(score)
    return {
        "strategy": CANONICAL_SHADOW_STRATEGY,
        "score": score,
        "label": label,
        "notes": notes,
        "gate_status": gate_status,
        "recommended_status": recommended_status,
    }
