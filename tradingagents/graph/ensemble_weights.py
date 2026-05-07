# tradingagents/graph/ensemble_weights.py

"""Numerai-inspired 8-voice ensemble weight system.

Manages weights for quant pillars (70%) and debate voices (30%).
Weights are regime-adaptive and clamped to prevent any single model domination.
"""

import json
import logging
import math
import os
from datetime import datetime
from typing import Dict, Optional, Set

logger = logging.getLogger(__name__)

INITIAL_WEIGHTS: Dict[str, float] = {
    "fundamental":     0.22,
    "coherence":       0.15,
    "macro":           0.13,
    "momentum":        0.15,
    "research_debate": 0.15,
    "trader_verdict":  0.10,
    "risk_verdict":    0.10,
}

WEIGHT_CLAMPS: Dict[str, tuple] = {
    "fundamental":     (0.10, 0.35),
    "coherence":       (0.05, 0.25),
    "macro":           (0.05, 0.25),
    "momentum":        (0.05, 0.25),
    "research_debate": (0.03, 0.25),
    "trader_verdict":  (0.03, 0.20),
    "risk_verdict":    (0.03, 0.20),
}

REGIME_MODIFIERS: Dict[str, Dict[str, float]] = {
    "BULL":            {"momentum": +0.03, "trader_verdict": +0.02, "macro": -0.03, "coherence": -0.02},
    "BEAR":            {"coherence": +0.03, "macro": +0.03, "risk_verdict": +0.03, "momentum": -0.03, "trader_verdict": -0.03},
    "VOL_SHOCK":       {"macro": +0.08, "risk_verdict": +0.03, "momentum": -0.03, "trader_verdict": -0.03},
    "HIGH_VOL":        {"macro": +0.03, "coherence": +0.02, "risk_verdict": +0.02, "trader_verdict": -0.02, "momentum": -0.02},
    "RISK_OFF":        {"coherence": +0.03, "macro": +0.03, "risk_verdict": +0.03, "trader_verdict": -0.03, "momentum": -0.02},
    "INFLATION_SHOCK": {"macro": +0.08, "fundamental": -0.02, "trader_verdict": -0.02, "momentum": +0.01},
    "RATES_UPTREND":   {"fundamental": +0.03, "macro": +0.03, "momentum": -0.03},
    "EUPHORIA":        {"coherence": +0.05, "risk_verdict": +0.05, "momentum": -0.03, "trader_verdict": -0.02, "fundamental": -0.02},
}

DEFAULT_PATH = "eval_results/control/ensemble_weights.json"


class EnsembleWeightStore:
    """Loads, applies, and persists ensemble weights."""

    def __init__(self, base_weights: Optional[Dict[str, float]] = None):
        self.base_weights = dict(base_weights or INITIAL_WEIGHTS)
        self.evolution_count = 0
        self.performance_history: list = []
        self.updated_at = datetime.now().isoformat()

    @classmethod
    def load(cls, path: Optional[str] = None) -> "EnsembleWeightStore":
        """Load from disk or return defaults."""
        path = path or DEFAULT_PATH
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                store = cls(base_weights=data.get("base_weights", INITIAL_WEIGHTS))
                store.evolution_count = data.get("evolution_count", 0)
                store.performance_history = data.get("performance_history", [])
                store.updated_at = data.get("updated_at", datetime.now().isoformat())
                return store
            except Exception:
                logger.warning("Failed to load ensemble weights from %s, using defaults", path)
        return cls()

    def save(self, path: Optional[str] = None) -> None:
        """Write to disk."""
        path = path or DEFAULT_PATH
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {
            "version": 1,
            "base_weights": self.base_weights,
            "weight_clamps": {k: list(v) for k, v in WEIGHT_CLAMPS.items()},
            "evolution_count": self.evolution_count,
            "performance_history": self.performance_history,
            "updated_at": datetime.now().isoformat(),
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def get_effective_weights(
        self, regime: str, active_models: Set[str]
    ) -> Dict[str, float]:
        """Compute effective weights for a regime and set of active models.

        1. Start with base weights
        2. Apply regime modifier deltas
        3. Zero out inactive models
        4. Redistribute zeroed weight proportionally
        5. Apply clamps (redistribute excess)
        6. Renormalize to sum = 1.0
        """
        # 1. Start with base
        weights = dict(self.base_weights)

        # 2. Apply regime modifiers
        modifiers = REGIME_MODIFIERS.get(regime, {})
        for model, delta in modifiers.items():
            if model in weights:
                weights[model] += delta

        # 3. Zero out inactive models and collect their weight
        inactive_weight = 0.0
        for model in list(weights):
            if model not in active_models:
                inactive_weight += weights[model]
                weights[model] = 0.0

        # 4. Redistribute zeroed weight proportionally to active models
        active_total = sum(weights[m] for m in active_models if weights.get(m, 0) > 0)
        if active_total > 0 and inactive_weight > 0:
            for model in active_models:
                if weights.get(model, 0) > 0:
                    weights[model] += inactive_weight * (weights[model] / active_total)

        # 5. Apply clamps — iterate until stable (max 3 passes)
        for _ in range(3):
            excess = 0.0
            unclamped = []
            for model in active_models:
                lo, hi = WEIGHT_CLAMPS.get(model, (0.0, 1.0))
                if weights.get(model, 0) < lo:
                    excess += lo - weights[model]
                    weights[model] = lo
                elif weights[model] > hi:
                    excess -= weights[model] - hi
                    weights[model] = hi
                else:
                    unclamped.append(model)

            if abs(excess) > 1e-9 and unclamped:
                unclamped_total = sum(weights[m] for m in unclamped)
                if unclamped_total > 0:
                    for model in unclamped:
                        weights[model] += excess * (weights[model] / unclamped_total)

        # 6. Renormalize to sum = 1.0
        total = sum(weights[m] for m in active_models)
        if total > 0:
            for model in active_models:
                weights[model] = weights[model] / total

        # Remove inactive models from output
        return {m: round(weights[m], 6) for m in active_models}

    def update_weights(self, per_model_ic: Dict[str, float]) -> Dict[str, float]:
        """Conservative hindsight-driven weight evolution.

        Applies small clamped multiplicative nudges from valid IC inputs,
        then normalizes and records the update in performance history.
        """
        valid = {
            str(model): float(ic)
            for model, ic in dict(per_model_ic or {}).items()
            if model in self.base_weights and ic is not None and math.isfinite(float(ic))
        }
        if not valid:
            logger.info("update_weights skipped: no valid IC inputs")
            return dict(self.base_weights)

        updated = dict(self.base_weights)
        for model, ic in valid.items():
            lo, hi = WEIGHT_CLAMPS.get(model, (0.0, 1.0))
            multiplier = 1.0 + max(-0.25, min(0.25, float(ic)))
            updated[model] = max(lo, min(hi, updated[model] * multiplier))

        total = sum(updated.values())
        if total > 0:
            updated = {model: weight / total for model, weight in updated.items()}
            normalized_total = sum(updated.values())
            if normalized_total > 0:
                largest_model = max(updated, key=updated.get)
                updated[largest_model] += 1.0 - normalized_total

        rounded = {model: round(weight, 6) for model, weight in updated.items()}
        rounded_total = sum(rounded.values())
        if rounded_total > 0:
            largest_model = max(rounded, key=rounded.get)
            rounded[largest_model] = round(rounded[largest_model] + (1.0 - rounded_total), 6)
        self.base_weights = rounded
        self.evolution_count += 1
        self.updated_at = datetime.now().isoformat()
        self.performance_history.append(
            {
                "updated_at": self.updated_at,
                "per_model_ic": valid,
                "base_weights": dict(self.base_weights),
            }
        )
        self.performance_history = self.performance_history[-20:]
        return dict(self.base_weights)
