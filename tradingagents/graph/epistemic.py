# tradingagents/graph/epistemic.py
"""
Epistemic transparency engine — pure Python, no LLM calls, no network I/O.
Produces a structured confidence and sensitivity report from scored pillar metrics.
"""

from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _coverage_to_tier(cov: float) -> str:
    """Map a data_coverage float [0,1] to a confidence tier string."""
    if cov >= 0.8:
        return "HIGH"
    if cov >= 0.4:
        return "MEDIUM"
    return "LOW"


def _build_fundamental_confidence(metrics: dict) -> dict:
    cov = metrics.get("data_coverage", 0.0)
    notes: List[str] = []
    piotroski = metrics.get("piotroski", {})
    missing = piotroski.get("missing_criteria", 0)
    if missing > 3:
        notes.append(f"{missing} of 9 Piotroski criteria unavailable")
    if cov < 0.4:
        notes.append("Limited fundamental data")
    return {"level": _coverage_to_tier(cov), "data_coverage": cov, "notes": notes}


def _build_sentiment_confidence(metrics: dict) -> dict:
    cov = metrics.get("data_coverage", 0.0)
    notes: List[str] = []
    buzz = metrics.get("buzz", {})
    total_articles = buzz.get("total_articles", None)
    source_quality = buzz.get("source_quality", None)
    if total_articles is not None and total_articles < 5:
        notes.append(f"Very few articles ({total_articles})")
    if source_quality == "low":
        notes.append("Low-quality sentiment sources")
    return {"level": _coverage_to_tier(cov), "data_coverage": cov, "notes": notes}


def _build_macro_confidence(metrics: dict) -> dict:
    cov = metrics.get("data_coverage", 0.0)
    notes: List[str] = []
    fred_available = metrics.get("fred_available", False)
    subscores = metrics.get("subscores", {})
    if not fred_available:
        notes.append("FRED data unavailable")
    if len(subscores) < 4:
        notes.append("Incomplete macro indicators")
    return {"level": _coverage_to_tier(cov), "data_coverage": cov, "notes": notes}


def _build_momentum_confidence(metrics: dict) -> dict:
    cov = metrics.get("data_coverage", 0.0)
    notes: List[str] = []
    days = metrics.get("days_of_history", None)
    if days is not None and days < 60:
        notes.append(f"Limited price history ({days} days)")
    return {"level": _coverage_to_tier(cov), "data_coverage": cov, "notes": notes}


def _build_options_confidence(metrics) -> dict:
    if metrics is None:
        return {"level": "LOW", "data_coverage": 0.0, "notes": ["No options data"]}
    cov = metrics.get("data_coverage", 0.0)
    notes: List[str] = []
    expirations = metrics.get("expirations_analyzed", None)
    if expirations is not None and expirations < 2:
        notes.append(f"Only {expirations} expiration(s) analyzed")
    return {"level": _coverage_to_tier(cov), "data_coverage": cov, "notes": notes}


def _compute_sensitivity(weights: dict) -> dict:
    return {pillar: round(w * 10, 1) for pillar, w in weights.items()}


def _detect_conflicts(coherence_snapshot) -> list:
    if not coherence_snapshot:
        return []
    directions = coherence_snapshot.get("pillar_directions", {})
    if not directions:
        return []
    pillars = list(directions.keys())
    conflicts = []
    for i in range(len(pillars)):
        for j in range(i + 1, len(pillars)):
            p1, p2 = pillars[i], pillars[j]
            d1, d2 = directions[p1], directions[p2]
            if d1 == "NEUTRAL" or d2 == "NEUTRAL":
                continue
            if d1 != d2:
                conflicts.append({
                    "pillars": [p1, p2],
                    "description": f"{p1} is {d1} while {p2} is {d2}",
                })
    return conflicts


def _compute_rating_proximity(aeternus_score: float, weights: dict, breakdown: dict) -> dict:
    boundaries = [
        (80, "Strong Buy/Buy"),
        (60, "Buy/Hold"),
        (40, "Hold/Sell"),
        (20, "Sell/Strong Sell"),
    ]
    nearest_val, nearest_label = min(
        boundaries, key=lambda b: abs(aeternus_score - b[0])
    )
    margin = abs(aeternus_score - nearest_val)

    # Find the non-coherence pillar whose score change would flip the rating first
    flip_pillar = None
    flip_delta = None
    for pillar, weight in weights.items():
        if pillar == "coherence":
            continue
        if weight <= 0:
            continue
        delta_needed = margin / weight
        if flip_delta is None or delta_needed < flip_delta:
            flip_delta = delta_needed
            flip_pillar = pillar

    if flip_pillar is not None and flip_delta is not None:
        flip_scenario = (
            f"If {flip_pillar} drops {flip_delta:.0f}pts, "
            f"score crosses {nearest_label} boundary"
        )
    else:
        flip_scenario = "Insufficient data to compute flip scenario"

    return {
        "current_score": aeternus_score,
        "nearest_boundary": float(nearest_val),
        "boundary_labels": nearest_label,
        "margin": round(margin, 2),
        "flip_scenario": flip_scenario,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_TIER_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

_PILLAR_BUILDERS = {
    "fundamental": _build_fundamental_confidence,
    "sentiment": _build_sentiment_confidence,
    "macro": _build_macro_confidence,
    "momentum": _build_momentum_confidence,
}

_FALLBACK = {"level": "LOW", "data_coverage": 0.0, "notes": ["Data unavailable"]}


def build_epistemic_report(
    fundamental_metrics,
    sentiment_metrics,
    macro_metrics,
    momentum_metrics,
    options_metrics,
    coherence_snapshot,
    weights: Dict[str, float],
    aeternus_score: float,
    breakdown: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build a structured epistemic transparency report from pillar metrics.

    Parameters
    ----------
    fundamental_metrics, sentiment_metrics, macro_metrics, momentum_metrics,
    options_metrics : dict or None
        Per-pillar computed metric dicts. May be None or empty.
    coherence_snapshot : dict or None
        Output of build_coherence_snapshot(); used for conflict detection.
    weights : dict
        Pillar weight map e.g. {"fundamental": 0.30, "coherence": 0.25, ...}.
    aeternus_score : float
        Composite Aeternus score [0, 100].
    breakdown : dict
        Per-pillar sub-scores e.g. {"fundamental": 75, "coherence": 60, ...}.

    Returns
    -------
    dict with keys: pillar_confidence, overall_confidence, weakest_pillar,
                    sensitivity, swing_pillar, conflicts, rating_proximity.
    """
    pillar_metrics_map = {
        "fundamental": fundamental_metrics or {},
        "sentiment": sentiment_metrics or {},
        "macro": macro_metrics or {},
        "momentum": momentum_metrics or {},
    }

    # Build per-pillar confidence dicts
    pillar_confidence: Dict[str, dict] = {}
    for pillar, builder in _PILLAR_BUILDERS.items():
        try:
            pillar_confidence[pillar] = builder(pillar_metrics_map[pillar])
        except Exception:
            pillar_confidence[pillar] = dict(_FALLBACK)

    try:
        pillar_confidence["options"] = _build_options_confidence(options_metrics)
    except Exception:
        pillar_confidence["options"] = dict(_FALLBACK)

    # Overall confidence = minimum tier across all pillars
    min_tier = min(
        _TIER_ORDER[pc["level"]] for pc in pillar_confidence.values()
    )
    overall_confidence = {v: k for k, v in _TIER_ORDER.items()}[min_tier]

    # Weakest pillar = lowest data_coverage
    weakest_pillar = min(
        pillar_confidence.keys(),
        key=lambda p: pillar_confidence[p]["data_coverage"],
    )

    # Sensitivity
    sensitivity = _compute_sensitivity(weights)

    # Swing pillar = highest sensitivity excluding coherence
    non_coherence = {p: s for p, s in sensitivity.items() if p != "coherence"}
    swing_pillar = max(non_coherence, key=lambda p: non_coherence[p]) if non_coherence else ""

    # Conflict detection
    conflicts = _detect_conflicts(coherence_snapshot)

    # Rating proximity
    rating_proximity = _compute_rating_proximity(aeternus_score, weights, breakdown)

    return {
        "pillar_confidence": pillar_confidence,
        "overall_confidence": overall_confidence,
        "weakest_pillar": weakest_pillar,
        "sensitivity": sensitivity,
        "swing_pillar": swing_pillar,
        "conflicts": conflicts,
        "rating_proximity": rating_proximity,
    }
