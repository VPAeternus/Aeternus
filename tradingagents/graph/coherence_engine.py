# tradingagents/graph/coherence_engine.py

import statistics
from typing import Any, Dict, List, Optional, Tuple


def build_coherence_snapshot(
    pillar_composites: Dict[str, int],
    fundamental_sub: Optional[Dict[str, int]] = None,
    macro_sub: Optional[Dict[str, int]] = None,
    sentiment_sub: Optional[Dict[str, int]] = None,
    momentum_sub: Optional[Dict[str, int]] = None,
    sentiment_low_coverage: bool = False,
) -> dict:
    """Compute cross-pillar coherence meta-analysis from pillar scores."""
    directions = _classify_directions(pillar_composites)
    alignment = _compute_directional_alignment(pillar_composites, directions)
    conviction = _compute_conviction_strength(pillar_composites)
    interaction_score, detected = _compute_interaction_patterns(
        pillar_composites, fundamental_sub, macro_sub, sentiment_sub, momentum_sub,
        sentiment_low_coverage=sentiment_low_coverage,
    )
    stability = _compute_narrative_stability(pillar_composites)

    composite = round(
        alignment * 0.30
        + conviction * 0.25
        + interaction_score * 0.30
        + stability * 0.15
    )
    composite = max(0, min(100, composite))

    # Majority direction
    bull = sum(1 for d in directions.values() if d == "BULLISH")
    bear = sum(1 for d in directions.values() if d == "BEARISH")
    if bull > bear:
        direction = "BULLISH"
    elif bear > bull:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    return {
        "subscores": {
            "directional_alignment": alignment,
            "conviction_strength": conviction,
            "interaction_patterns": interaction_score,
            "narrative_stability": stability,
        },
        "detected_patterns": detected,
        "composite_score": composite,
        "direction": direction,
        "pillar_directions": directions,
    }


def _classify_directions(composites: Dict[str, int]) -> Dict[str, str]:
    result = {}
    for pillar, score in composites.items():
        if score > 60:
            result[pillar] = "BULLISH"
        elif score < 40:
            result[pillar] = "BEARISH"
        else:
            result[pillar] = "NEUTRAL"
    return result


def _compute_directional_alignment(
    composites: Dict[str, int], directions: Dict[str, str]
) -> int:
    counts: Dict[str, int] = {}
    for d in directions.values():
        counts[d] = counts.get(d, 0) + 1

    max_count = max(counts.values())
    total = len(directions)

    if max_count == total:
        score = 90
    elif max_count == total - 1:
        score = 70
    else:
        bull_count = counts.get("BULLISH", 0)
        bear_count = counts.get("BEARISH", 0)
        neutral_count = counts.get("NEUTRAL", 0)
        if bull_count == 2 and bear_count == 2 and neutral_count == 0:
            score = 50
        else:
            score = 35

    # Bonus +10 if ALL 4 composites are extreme (>75 or all <25)
    vals = list(composites.values())
    if all(v > 75 for v in vals) or all(v < 25 for v in vals):
        score += 10

    return min(100, score)


def _compute_conviction_strength(composites: Dict[str, int]) -> int:
    vals = list(composites.values())
    spread = max(vals) - min(vals)
    score = max(10, min(95, 100 - round(spread * 1.5)))

    if all(v > 65 for v in vals):
        score = min(100, score + 10)
    elif all(v < 35 for v in vals):
        score = min(100, score + 10)

    return score


def _compute_interaction_patterns(
    composites: Dict[str, int],
    fundamental_sub: Optional[Dict[str, int]],
    macro_sub: Optional[Dict[str, int]],
    sentiment_sub: Optional[Dict[str, int]],
    momentum_sub: Optional[Dict[str, int]],
    sentiment_low_coverage: bool = False,
) -> Tuple[int, List[Dict[str, Any]]]:
    f = composites.get("fundamental", 50)
    m = composites.get("macro", 50)
    s = composites.get("sentiment", 50)
    mo = composites.get("momentum", 50)

    # Neutralize sentiment in pattern evaluation when low coverage.
    # Low article count (< 5) produces ~30-39 scores that look bearish
    # but represent data absence, not real bearish signal.
    if sentiment_low_coverage:
        s = 50

    patterns = [
        {
            "name": "VALUE_TRAP",
            "conditions": [
                (f, ">", 70),
                (mo, "<", 40),
                (m, "<", 45),
            ],
            "adjustment": -15,
            "description": "Good numbers but market disagrees",
        },
        {
            "name": "MOMENTUM_CROWDING",
            "conditions": [
                (s, ">", 70),
                (mo, ">", 70),
                (f, "<", 50),
            ],
            "adjustment": -15,
            "description": "Hot trade with no fundamental backing",
        },
        {
            "name": "CONTRARIAN_SETUP",
            "conditions": [
                (s, "<", 35),
                (f, ">", 65),
                (m, ">", 50),
            ],
            "adjustment": +15,
            "description": "Hated stock with solid fundamentals",
        },
        {
            "name": "RISING_TIDE",
            "conditions": [
                (f, ">", 60),
                (m, ">", 60),
                (mo, ">", 60),
                (s, ">", 50),
            ],
            "adjustment": +20,
            "description": "All signals aligned bullish",
        },
        {
            "name": "FALLING_KNIFE",
            "conditions": [
                (mo, "<", 30),
                (f, "<", 40),
                (s, "<", 40),
            ],
            "adjustment": -20,
            "description": "Everything negative",
        },
        {
            "name": "REGIME_TRANSITION",
            "conditions": None,  # handled separately
            "adjustment": -10,
            "description": "Regime deteriorating but momentum hasn't caught up",
            "macro_sub_key": "regime_fit",
            "macro_sub_threshold": 35,
            "macro_sub_op": "<",
            "other_val": mo,
            "other_threshold": 55,
            "other_op": ">",
        },
        {
            "name": "QUALITY_DIVERGENCE",
            "conditions": None,  # handled separately
            "adjustment": +10,
            "description": "High quality ignored by market",
            "fundamental_sub_key": "quality",
            "fundamental_sub_threshold": 75,
            "fundamental_sub_op": ">",
            "other_val": s,
            "other_threshold": 45,
            "other_op": "<",
        },
        {
            "name": "SMART_MONEY_DISAGREES",
            "conditions": [
                (f, "<", 45),
                (mo, ">", 65),
                (s, ">", 65),
            ],
            "adjustment": -12,
            "description": "Momentum chasing with weak fundamentals",
        },
    ]

    score = 50
    detected: List[Dict[str, Any]] = []

    for pat in patterns:
        name = pat["name"]
        adj = pat["adjustment"]
        desc = pat["description"]

        if name == "REGIME_TRANSITION":
            regime_fit = (
                macro_sub.get(pat["macro_sub_key"])
                if macro_sub and pat["macro_sub_key"] in macro_sub
                else None
            )
            if regime_fit is None:
                continue
            cond1 = regime_fit < pat["macro_sub_threshold"]
            cond2 = pat["other_val"] > pat["other_threshold"]
            if cond1 and cond2:
                diffs = [
                    (pat["macro_sub_threshold"] - regime_fit) / 20,
                    (pat["other_val"] - pat["other_threshold"]) / 20,
                ]
                conf = min(1.0, sum(diffs) / len(diffs))
                score += adj
                detected.append({"name": name, "confidence": round(conf, 2), "adjustment": adj, "description": desc})
            continue

        if name == "QUALITY_DIVERGENCE":
            quality = (
                fundamental_sub.get(pat["fundamental_sub_key"])
                if fundamental_sub and pat["fundamental_sub_key"] in fundamental_sub
                else None
            )
            if quality is None:
                continue
            cond1 = quality > pat["fundamental_sub_threshold"]
            cond2 = pat["other_val"] < pat["other_threshold"]
            if cond1 and cond2:
                diffs = [
                    (quality - pat["fundamental_sub_threshold"]) / 20,
                    (pat["other_threshold"] - pat["other_val"]) / 20,
                ]
                conf = min(1.0, sum(diffs) / len(diffs))
                score += adj
                detected.append({"name": name, "confidence": round(conf, 2), "adjustment": adj, "description": desc})
            continue

        # Standard conditions
        conds = pat["conditions"]
        fires = True
        diffs = []
        for val, op, threshold in conds:
            if op == ">":
                if not (val > threshold):
                    fires = False
                    break
                diffs.append((val - threshold) / 20)
            elif op == "<":
                if not (val < threshold):
                    fires = False
                    break
                diffs.append((threshold - val) / 20)

        if fires:
            conf = min(1.0, sum(diffs) / len(diffs))
            score += adj
            detected.append({"name": name, "confidence": round(conf, 2), "adjustment": adj, "description": desc})

    score = max(0, min(100, score))
    return score, detected


def _compute_narrative_stability(composites: Dict[str, int]) -> int:
    vals = list(composites.values())
    std_dev = statistics.stdev(vals)
    score = max(10, min(90, round(90 - std_dev * 3)))
    return score
