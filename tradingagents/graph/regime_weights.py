# tradingagents/graph/regime_weights.py

from typing import Dict

REGIME_WEIGHTS: Dict[str, Dict[str, float]] = {
    "NEUTRAL":          {"fundamental": 0.30, "coherence": 0.25, "macro": 0.20, "sentiment": 0.15, "momentum": 0.10},
    "BULL":             {"fundamental": 0.30, "coherence": 0.25, "macro": 0.15, "sentiment": 0.15, "momentum": 0.15},
    "BEAR":             {"fundamental": 0.25, "coherence": 0.30, "macro": 0.25, "sentiment": 0.10, "momentum": 0.10},
    "VOL_SHOCK":        {"fundamental": 0.20, "coherence": 0.20, "macro": 0.35, "sentiment": 0.10, "momentum": 0.15},
    "HIGH_VOL":         {"fundamental": 0.25, "coherence": 0.25, "macro": 0.25, "sentiment": 0.10, "momentum": 0.15},
    "RISK_OFF":         {"fundamental": 0.25, "coherence": 0.30, "macro": 0.25, "sentiment": 0.10, "momentum": 0.10},
    "INFLATION_SHOCK":  {"fundamental": 0.20, "coherence": 0.20, "macro": 0.35, "sentiment": 0.10, "momentum": 0.15},
    "RATES_UPTREND":    {"fundamental": 0.30, "coherence": 0.25, "macro": 0.25, "sentiment": 0.10, "momentum": 0.10},
    "EUPHORIA":         {"fundamental": 0.20, "coherence": 0.35, "macro": 0.15, "sentiment": 0.15, "momentum": 0.15},
}

DEFAULT_WEIGHTS: Dict[str, float] = REGIME_WEIGHTS["NEUTRAL"]


def get_weights(regime: str) -> Dict[str, float]:
    """Return pillar weights for the given regime, defaulting to NEUTRAL."""
    return REGIME_WEIGHTS.get(regime, DEFAULT_WEIGHTS)
