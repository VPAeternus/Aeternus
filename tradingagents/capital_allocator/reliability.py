"""Reliability, calibration, and adjusted return math for allocator decisions."""

from __future__ import annotations

import math
from typing import Iterable, Sequence

from .contracts import (
    LANE_PARAMS,
    SHOCK_MULTIPLIER,
    DecisionObservation,
    Lane,
    RegimeShock,
)


class ReliabilityEngine:
    """Deterministic reliability engine for lane/family/regime confidence."""

    def __init__(self, r0: float = 0.35, n0: float = 40.0, n0_regime: float = 25.0):
        self.r0 = float(r0)
        self.n0 = float(n0)
        self.n0_regime = float(n0_regime)

    def hybrid_weight(self, observation: DecisionObservation, lane: Lane) -> float:
        """Apply lane-specific hybrid half-life across time and decision count."""
        params = LANE_PARAMS[lane]
        return (2.0 ** (-float(observation.age_days) / params.h_days)) * (
            2.0 ** (-float(observation.age_decisions) / params.h_decisions)
        )

    def effective_scale(self, lane: Lane, shock: RegimeShock) -> float:
        """Flatten score confidence under shock via lane-specific sensitivity."""
        params = LANE_PARAMS[lane]
        u_t = SHOCK_MULTIPLIER[shock]
        return params.s_base * (1.0 + params.k_shock * (u_t - 1.0))

    @staticmethod
    def calibrated_probability(score: float, scale: float) -> float:
        """Map score to calibrated probability using deterministic logistic transform."""
        bounded_scale = max(float(scale), 1e-9)
        z_value = (float(score) - 50.0) / bounded_scale
        return 1.0 / (1.0 + math.exp(-z_value))

    def lane_family_reliability(
        self,
        lane: Lane,
        shock: RegimeShock,
        observations: Iterable[DecisionObservation],
    ) -> tuple[float, float]:
        """Compute depth-shrunk lane-family reliability and effective sample depth."""
        rows = list(observations)
        if not rows:
            return self.r0, 0.0

        scale = self.effective_scale(lane, shock)
        weight_sum = 0.0
        weighted_hits = 0.0
        weighted_brier = 0.0
        score_values: list[float] = []
        edge_values: list[float] = []
        weights: list[float] = []

        for row in rows:
            weight = self.hybrid_weight(row, lane)
            outcome = 1.0 if float(row.edge_bps) > 0.0 else 0.0
            probability = self.calibrated_probability(float(row.score), scale)
            weight_sum += weight
            weighted_hits += weight * outcome
            weighted_brier += weight * ((probability - outcome) ** 2.0)
            score_values.append(float(row.score))
            edge_values.append(float(row.edge_bps))
            weights.append(weight)

        if weight_sum <= 0:
            return self.r0, 0.0

        hit_rate = weighted_hits / weight_sum
        brier_score = weighted_brier / weight_sum
        calibration_term = 1.0 - min(brier_score / 0.25, 1.0)
        information_coeff = max(
            0.0,
            (self._weighted_spearman(score_values, edge_values, weights) + 1.0) / 2.0,
        )
        empirical = (0.5 * hit_rate) + (0.3 * calibration_term) + (0.2 * information_coeff)

        alpha = weight_sum / (weight_sum + self.n0)
        reliability = self.r0 + alpha * (empirical - self.r0)
        return _clamp(reliability, 0.0, 1.0), weight_sum

    def regime_reliability(self, r_global: float, r_regime_raw: float, n_eff_regime: float) -> float:
        """Regime reliability with deterministic depth shrinkage toward global signal."""
        shrink = float(n_eff_regime) / (float(n_eff_regime) + self.n0_regime)
        value = float(r_global) + shrink * (float(r_regime_raw) - float(r_global))
        return _clamp(value, 0.0, 1.0)

    @staticmethod
    def expected_adjusted_return_bps(
        e_raw_bps: float,
        r_lane_family: float,
        r_regime: float,
        r_data: float,
    ) -> float:
        """Compute E_adj in bps under reliability and data quality modifiers."""
        return float(e_raw_bps) * float(r_lane_family) * float(r_regime) * float(r_data)

    def _weighted_spearman(
        self,
        x_values: Sequence[float],
        y_values: Sequence[float],
        weights: Sequence[float],
    ) -> float:
        if len(x_values) < 2 or len(y_values) < 2 or len(weights) < 2:
            return 0.0
        x_rank = _rank_with_ties(x_values)
        y_rank = _rank_with_ties(y_values)
        return _weighted_pearson(x_rank, y_rank, weights)


def _rank_with_ties(values: Sequence[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda row: row[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        # Average rank for tied values.
        average_rank = (i + j + 2) / 2.0
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = average_rank
        i = j + 1
    return ranks


def _weighted_pearson(x_values: Sequence[float], y_values: Sequence[float], weights: Sequence[float]) -> float:
    weight_sum = max(float(sum(weights)), 1e-9)
    x_mean = sum(w * x for w, x in zip(weights, x_values)) / weight_sum
    y_mean = sum(w * y for w, y in zip(weights, y_values)) / weight_sum
    covariance = sum(
        w * (x - x_mean) * (y - y_mean) for w, x, y in zip(weights, x_values, y_values)
    ) / weight_sum
    x_var = sum(w * ((x - x_mean) ** 2.0) for w, x in zip(weights, x_values)) / weight_sum
    y_var = sum(w * ((y - y_mean) ** 2.0) for w, y in zip(weights, y_values)) / weight_sum
    if x_var <= 0 or y_var <= 0:
        return 0.0
    return covariance / math.sqrt(x_var * y_var)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))

