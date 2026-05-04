# tests/test_ensemble_weights.py

import json
import os
import tempfile
import pytest

from tradingagents.graph.ensemble_weights import (
    EnsembleWeightStore,
    INITIAL_WEIGHTS,
    WEIGHT_CLAMPS,
    REGIME_MODIFIERS,
)


def test_initial_weights_sum_to_one():
    assert abs(sum(INITIAL_WEIGHTS.values()) - 1.0) < 1e-9


def test_all_models_have_clamps():
    for model in INITIAL_WEIGHTS:
        assert model in WEIGHT_CLAMPS, f"Missing clamp for {model}"


def test_load_defaults():
    store = EnsembleWeightStore.load("/nonexistent/path.json")
    assert store.base_weights == INITIAL_WEIGHTS
    assert store.evolution_count == 0


def test_save_and_load_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "weights.json")
        store = EnsembleWeightStore()
        store.base_weights["fundamental"] = 0.25
        store.save(path)

        loaded = EnsembleWeightStore.load(path)
        assert loaded.base_weights["fundamental"] == 0.25

        with open(path) as f:
            data = json.load(f)
        assert data["version"] == 1
        assert "weight_clamps" in data


def test_effective_weights_all_active_neutral():
    """All 8 models active, NEUTRAL regime: weights should sum to 1.0."""
    store = EnsembleWeightStore()
    active = set(INITIAL_WEIGHTS.keys())
    w = store.get_effective_weights("NEUTRAL", active)
    assert abs(sum(w.values()) - 1.0) < 1e-6
    assert len(w) == 8


def test_effective_weights_sum_all_regimes():
    """Weights should sum to 1.0 for every regime with all models active."""
    store = EnsembleWeightStore()
    active = set(INITIAL_WEIGHTS.keys())
    regimes = list(REGIME_MODIFIERS.keys()) + ["NEUTRAL", "UNKNOWN_REGIME"]
    for regime in regimes:
        w = store.get_effective_weights(regime, active)
        assert abs(sum(w.values()) - 1.0) < 1e-6, f"Failed for regime {regime}: sum={sum(w.values())}"


def test_inactive_models_excluded():
    """Inactive debate voices should not appear in output, weight redistributed."""
    store = EnsembleWeightStore()
    quant_only = {"fundamental", "coherence", "macro", "sentiment", "momentum"}
    w = store.get_effective_weights("NEUTRAL", quant_only)
    assert len(w) == 5
    assert "research_debate" not in w
    assert abs(sum(w.values()) - 1.0) < 1e-6


def test_clamps_respected():
    """No model exceeds its clamp bounds."""
    store = EnsembleWeightStore()
    active = set(INITIAL_WEIGHTS.keys())
    for regime in list(REGIME_MODIFIERS.keys()) + ["NEUTRAL"]:
        w = store.get_effective_weights(regime, active)
        for model, weight in w.items():
            lo, hi = WEIGHT_CLAMPS[model]
            assert weight >= lo - 1e-6, f"{regime}/{model}: {weight} < {lo}"
            assert weight <= hi + 1e-6, f"{regime}/{model}: {weight} > {hi}"


def test_single_active_model():
    """Edge case: only one model active should get weight 1.0."""
    store = EnsembleWeightStore()
    w = store.get_effective_weights("NEUTRAL", {"fundamental"})
    assert abs(w["fundamental"] - 1.0) < 1e-6


def test_regime_modifiers_shift_weights():
    """VOL_SHOCK should boost macro relative to NEUTRAL."""
    store = EnsembleWeightStore()
    active = set(INITIAL_WEIGHTS.keys())
    neutral = store.get_effective_weights("NEUTRAL", active)
    vol_shock = store.get_effective_weights("VOL_SHOCK", active)
    assert vol_shock["macro"] > neutral["macro"]


def test_update_weights_applies_small_bounded_shift():
    store = EnsembleWeightStore()
    before = dict(store.base_weights)
    result = store.update_weights({"fundamental": 0.08, "macro": -0.04})
    assert abs(sum(result.values()) - 1.0) < 1e-6
    assert result["fundamental"] > before["fundamental"]
    assert result["macro"] < before["macro"]


def test_update_weights_unchanged_when_no_valid_ic():
    store = EnsembleWeightStore()
    before = dict(store.base_weights)
    result = store.update_weights({})
    assert result == before
