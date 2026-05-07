# tradingagents/graph/regime_weights.py

from typing import Dict

REGIME_WEIGHTS: Dict[str, Dict[str, float]] = {
    "NEUTRAL":          {"fundamental": 0.35, "coherence": 0.30, "macro": 0.23, "momentum": 0.12},
    "BULL":             {"fundamental": 0.35, "coherence": 0.29, "macro": 0.18, "momentum": 0.18},
    "BEAR":             {"fundamental": 0.28, "coherence": 0.34, "macro": 0.27, "momentum": 0.11},
    "VOL_SHOCK":        {"fundamental": 0.22, "coherence": 0.22, "macro": 0.39, "momentum": 0.17},
    "HIGH_VOL":         {"fundamental": 0.28, "coherence": 0.28, "macro": 0.28, "momentum": 0.16},
    "RISK_OFF":         {"fundamental": 0.28, "coherence": 0.34, "macro": 0.27, "momentum": 0.11},
    "INFLATION_SHOCK":  {"fundamental": 0.22, "coherence": 0.22, "macro": 0.39, "momentum": 0.17},
    "RATES_UPTREND":    {"fundamental": 0.33, "coherence": 0.28, "macro": 0.28, "momentum": 0.11},
    "EUPHORIA":         {"fundamental": 0.24, "coherence": 0.41, "macro": 0.18, "momentum": 0.17},
}

DEFAULT_WEIGHTS: Dict[str, float] = REGIME_WEIGHTS["NEUTRAL"]


def get_weights(regime: str) -> Dict[str, float]:
    """Return pillar weights for the given regime, defaulting to NEUTRAL."""
    return REGIME_WEIGHTS.get(regime, DEFAULT_WEIGHTS)
