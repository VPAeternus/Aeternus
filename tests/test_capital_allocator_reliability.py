import math

from tradingagents.capital_allocator.contracts import DecisionObservation, Lane, RegimeShock
from tradingagents.capital_allocator.reliability import ReliabilityEngine


def test_hybrid_weight_is_lane_specific():
    engine = ReliabilityEngine()
    obs = DecisionObservation(score=70.0, edge_bps=120.0, age_days=90.0, age_decisions=10.0)

    core_weight = engine.hybrid_weight(obs, Lane.CORE)
    momentum_weight = engine.hybrid_weight(obs, Lane.MOMENTUM)

    assert core_weight > momentum_weight


def test_effective_scale_flattens_under_crisis():
    engine = ReliabilityEngine()
    normal_scale = engine.effective_scale(Lane.MOMENTUM, RegimeShock.NORMAL)
    crisis_scale = engine.effective_scale(Lane.MOMENTUM, RegimeShock.CRISIS)
    assert crisis_scale > normal_scale


def test_lane_family_reliability_shrinks_with_low_depth():
    engine = ReliabilityEngine(r0=0.35, n0=40.0)
    observations = [
        DecisionObservation(score=80.0, edge_bps=150.0, age_days=2.0, age_decisions=1.0),
    ]
    reliability, n_eff = engine.lane_family_reliability(
        Lane.MOMENTUM,
        RegimeShock.NORMAL,
        observations,
    )
    assert n_eff > 0
    assert reliability >= 0.35
    assert reliability < 0.95


def test_lane_family_reliability_rewards_rank_quality():
    engine = ReliabilityEngine()
    good = [
        DecisionObservation(score=90.0, edge_bps=200.0, age_days=2.0, age_decisions=1.0),
        DecisionObservation(score=75.0, edge_bps=80.0, age_days=2.0, age_decisions=1.0),
        DecisionObservation(score=55.0, edge_bps=-20.0, age_days=2.0, age_decisions=1.0),
    ]
    bad = [
        DecisionObservation(score=90.0, edge_bps=-200.0, age_days=2.0, age_decisions=1.0),
        DecisionObservation(score=75.0, edge_bps=-80.0, age_days=2.0, age_decisions=1.0),
        DecisionObservation(score=55.0, edge_bps=20.0, age_days=2.0, age_decisions=1.0),
    ]
    good_r, _ = engine.lane_family_reliability(Lane.CORE, RegimeShock.NORMAL, good)
    bad_r, _ = engine.lane_family_reliability(Lane.CORE, RegimeShock.NORMAL, bad)
    assert good_r > bad_r


def test_expected_adjusted_return_bps():
    value = ReliabilityEngine.expected_adjusted_return_bps(
        e_raw_bps=120.0,
        r_lane_family=0.5,
        r_regime=0.8,
        r_data=0.9,
    )
    assert math.isclose(value, 43.2, rel_tol=1e-9)

