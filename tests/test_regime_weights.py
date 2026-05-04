# tests/test_regime_weights.py

import sys
import types
import pytest

# Stub chromadb before it can be imported (pydantic v1 incompatible with Python 3.14)
if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []  # make it look like a package
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub

from tradingagents.graph.regime_weights import REGIME_WEIGHTS, DEFAULT_WEIGHTS, get_weights


class TestRegimeWeights:
    """Test regime weight definitions and access."""

    def test_all_regimes_sum_to_one(self):
        """All regimes sum to approximately 1.0."""
        for regime_name, weights in REGIME_WEIGHTS.items():
            total = sum(weights.values())
            assert abs(total - 1.0) < 0.001, f"Regime {regime_name} sum={total}"

    def test_default_is_neutral(self):
        """DEFAULT_WEIGHTS should equal NEUTRAL weights."""
        assert DEFAULT_WEIGHTS == REGIME_WEIGHTS["NEUTRAL"]

    def test_unknown_regime_returns_default(self):
        """Unknown regime should return DEFAULT_WEIGHTS."""
        result = get_weights("TOTALLY_UNKNOWN")
        assert result == DEFAULT_WEIGHTS

    def test_regime_weight_keys(self):
        """All regimes have exactly 5 keys."""
        expected_keys = {"fundamental", "coherence", "macro", "sentiment", "momentum"}
        for regime_name, weights in REGIME_WEIGHTS.items():
            assert set(weights.keys()) == expected_keys, f"Regime {regime_name} has wrong keys"

    def test_bear_regime_weights(self):
        """Verify BEAR specific weight values."""
        bear_weights = REGIME_WEIGHTS["BEAR"]
        assert bear_weights["fundamental"] == 0.25
        assert bear_weights["coherence"] == 0.30
        assert bear_weights["macro"] == 0.25
        assert bear_weights["sentiment"] == 0.10
        assert bear_weights["momentum"] == 0.10

    def test_euphoria_coherence_highest(self):
        """In EUPHORIA regime, coherence weight is highest."""
        euphoria_weights = REGIME_WEIGHTS["EUPHORIA"]
        coherence_weight = euphoria_weights["coherence"]
        other_weights = [
            euphoria_weights["fundamental"],
            euphoria_weights["macro"],
            euphoria_weights["sentiment"],
            euphoria_weights["momentum"],
        ]
        assert coherence_weight > max(other_weights)
