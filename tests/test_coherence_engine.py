# tests/test_coherence_engine.py

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

from tradingagents.graph.coherence_engine import (
    build_coherence_snapshot,
    _compute_directional_alignment,
    _compute_conviction_strength,
    _compute_interaction_patterns,
    _compute_narrative_stability,
    _classify_directions,
)


def _make_composites(fundamental=60, macro=55, sentiment=50, momentum=55):
    """Factory helper to create composites dict."""
    return {"fundamental": fundamental, "macro": macro, "sentiment": sentiment, "momentum": momentum}


class TestDirectionalAlignment:
    """Test directional alignment scoring."""

    def test_four_agree_bullish(self):
        """All composites > 60 → alignment score 90."""
        composites = _make_composites(fundamental=75, macro=70, sentiment=65, momentum=80)
        directions = _classify_directions(composites)
        score = _compute_directional_alignment(composites, directions)
        assert score == 90

    def test_three_agree(self):
        """3 bullish, 1 neutral → 70."""
        composites = _make_composites(fundamental=75, macro=70, sentiment=50, momentum=80)
        directions = _classify_directions(composites)
        score = _compute_directional_alignment(composites, directions)
        assert score == 70

    def test_two_two_split(self):
        """2 bullish, 2 bearish → 50."""
        composites = _make_composites(fundamental=75, macro=30, sentiment=65, momentum=35)
        directions = _classify_directions(composites)
        score = _compute_directional_alignment(composites, directions)
        assert score == 50

    def test_mixed_no_majority(self):
        """1 bullish, 1 bearish, 2 neutral → 35."""
        composites = _make_composites(fundamental=75, macro=30, sentiment=50, momentum=45)
        directions = _classify_directions(composites)
        score = _compute_directional_alignment(composites, directions)
        assert score == 35

    def test_extreme_bonus(self):
        """All > 75 → 90 + 10 = 100."""
        composites = _make_composites(fundamental=80, macro=85, sentiment=78, momentum=90)
        directions = _classify_directions(composites)
        score = _compute_directional_alignment(composites, directions)
        assert score == 100


class TestConvictionStrength:
    """Test conviction strength scoring."""

    def test_tight_spread(self):
        """All at 60 → spread=0, score clamped to min 95."""
        composites = _make_composites(fundamental=60, macro=60, sentiment=60, momentum=60)
        score = _compute_conviction_strength(composites)
        assert score == 95

    def test_wide_spread(self):
        """20 to 80, spread=60 → 100-90=10."""
        composites = _make_composites(fundamental=80, macro=20, sentiment=50, momentum=50)
        score = _compute_conviction_strength(composites)
        assert score == 10

    def test_high_conviction_bull_bonus(self):
        """All > 65 → spread 5 → 100-8=92, +10 = 100 (capped)."""
        composites = _make_composites(fundamental=70, macro=68, sentiment=66, momentum=70)
        score = _compute_conviction_strength(composites)
        assert score == 100

    def test_high_conviction_bear_bonus(self):
        """All < 35 → spread small, +10 bonus."""
        composites = _make_composites(fundamental=25, macro=30, sentiment=20, momentum=28)
        score = _compute_conviction_strength(composites)
        # spread = 30-20=10, score = 100-15=85, +10 bonus = 95 (capped at 95)
        assert score == 95


class TestInteractionPatterns:
    """Test interaction pattern detection."""

    def test_value_trap_fires(self):
        """fundamental=75, momentum=35, macro=40 → adjustment -15."""
        composites = _make_composites(fundamental=75, momentum=35, macro=40, sentiment=50)
        score, patterns = _compute_interaction_patterns(composites, None, None, None, None)
        pattern_names = [p["name"] for p in patterns]
        assert "VALUE_TRAP" in pattern_names

    def test_momentum_crowding_fires(self):
        """sentiment=75, momentum=75, fundamental=40."""
        composites = _make_composites(sentiment=75, momentum=75, fundamental=40, macro=50)
        score, patterns = _compute_interaction_patterns(composites, None, None, None, None)
        pattern_names = [p["name"] for p in patterns]
        assert "MOMENTUM_CROWDING" in pattern_names

    def test_contrarian_setup_fires(self):
        """sentiment=30, fundamental=70, macro=55."""
        composites = _make_composites(sentiment=30, fundamental=70, macro=55, momentum=50)
        score, patterns = _compute_interaction_patterns(composites, None, None, None, None)
        pattern_names = [p["name"] for p in patterns]
        assert "CONTRARIAN_SETUP" in pattern_names

    def test_rising_tide_fires(self):
        """fundamental=65, macro=65, momentum=65, sentiment=55."""
        composites = _make_composites(fundamental=65, macro=65, momentum=65, sentiment=55)
        score, patterns = _compute_interaction_patterns(composites, None, None, None, None)
        pattern_names = [p["name"] for p in patterns]
        assert "RISING_TIDE" in pattern_names

    def test_falling_knife_fires(self):
        """momentum=25, fundamental=35, sentiment=35."""
        composites = _make_composites(momentum=25, fundamental=35, sentiment=35, macro=50)
        score, patterns = _compute_interaction_patterns(composites, None, None, None, None)
        pattern_names = [p["name"] for p in patterns]
        assert "FALLING_KNIFE" in pattern_names

    def test_regime_transition_fires(self):
        """macro_sub with regime_fit=30 (< 35), momentum=60 (> 55)."""
        composites = _make_composites(fundamental=50, macro=50, sentiment=50, momentum=60)
        macro_sub = {"regime_fit": 30, "monetary_stress": 50, "rate_headwind": 50, "commodity_cycle": 50}
        score, patterns = _compute_interaction_patterns(composites, None, macro_sub, None, None)
        pattern_names = [p["name"] for p in patterns]
        assert "REGIME_TRANSITION" in pattern_names

    def test_quality_divergence_fires(self):
        """fundamental_sub quality=80 (> 75), sentiment=40 (< 45)."""
        composites = _make_composites(fundamental=60, macro=50, sentiment=40, momentum=50)
        fundamental_sub = {"quality": 80, "growth": 50, "health": 50, "valuation": 50}
        score, patterns = _compute_interaction_patterns(composites, fundamental_sub, None, None, None)
        pattern_names = [p["name"] for p in patterns]
        assert "QUALITY_DIVERGENCE" in pattern_names

    def test_smart_money_disagrees_fires(self):
        """fundamental=40, momentum=70, sentiment=70."""
        composites = _make_composites(fundamental=40, momentum=70, sentiment=70, macro=50)
        score, patterns = _compute_interaction_patterns(composites, None, None, None, None)
        pattern_names = [p["name"] for p in patterns]
        assert "SMART_MONEY_DISAGREES" in pattern_names

    def test_patterns_stack(self):
        """SMART_MONEY_DISAGREES + MOMENTUM_CROWDING can co-fire."""
        composites = _make_composites(fundamental=40, momentum=72, sentiment=75, macro=50)
        score, patterns = _compute_interaction_patterns(composites, None, None, None, None)
        pattern_names = [p["name"] for p in patterns]
        assert "SMART_MONEY_DISAGREES" in pattern_names
        assert "MOMENTUM_CROWDING" in pattern_names

    def test_no_patterns_neutral(self):
        """Composites all at 50 → no patterns fire."""
        composites = _make_composites(fundamental=50, macro=50, sentiment=50, momentum=50)
        score, patterns = _compute_interaction_patterns(composites, None, None, None, None)
        # Base score 50, no adjustments applied
        assert score == 50
        assert len(patterns) == 0

    def test_falling_knife_suppressed_by_low_coverage(self):
        """FALLING_KNIFE should NOT fire when sentiment_low_coverage neutralizes s to 50."""
        # Without flag: momentum=25, fundamental=35, sentiment=35 → FALLING_KNIFE fires
        composites = _make_composites(momentum=25, fundamental=35, sentiment=35, macro=50)
        _, patterns_no_flag = _compute_interaction_patterns(composites, None, None, None, None)
        assert "FALLING_KNIFE" in [p["name"] for p in patterns_no_flag]

        # With flag: s overridden to 50 → s < 40 no longer holds → FALLING_KNIFE blocked
        _, patterns_flagged = _compute_interaction_patterns(
            composites, None, None, None, None, sentiment_low_coverage=True,
        )
        assert "FALLING_KNIFE" not in [p["name"] for p in patterns_flagged]

    def test_contrarian_setup_suppressed_by_low_coverage(self):
        """CONTRARIAN_SETUP should NOT fire when sentiment_low_coverage neutralizes s to 50."""
        composites = _make_composites(sentiment=30, fundamental=70, macro=55, momentum=50)
        _, patterns_no_flag = _compute_interaction_patterns(composites, None, None, None, None)
        assert "CONTRARIAN_SETUP" in [p["name"] for p in patterns_no_flag]

        _, patterns_flagged = _compute_interaction_patterns(
            composites, None, None, None, None, sentiment_low_coverage=True,
        )
        assert "CONTRARIAN_SETUP" not in [p["name"] for p in patterns_flagged]


class TestNarrativeStability:
    """Test narrative stability scoring."""

    def test_low_stddev_high_score(self):
        """All composites close: 60, 62, 58, 61 → low std_dev → high score."""
        composites = _make_composites(fundamental=60, macro=62, sentiment=58, momentum=61)
        score = _compute_narrative_stability(composites)
        # std_dev ≈ 1.5, score ≈ 90 - 4.5 ≈ 85 (clamped to min 10, max 90)
        assert score > 80

    def test_high_stddev_low_score(self):
        """Composites spread: 20, 80, 30, 70 → high std_dev → low score."""
        composites = _make_composites(fundamental=20, macro=80, sentiment=30, momentum=70)
        score = _compute_narrative_stability(composites)
        # std_dev ≈ 28.4, score ≈ 90 - 85.2 = low value (clamped to min 10)
        assert score < 30


class TestBuildCoherenceSnapshot:
    """Integration tests for build_coherence_snapshot."""

    def test_integration_bullish(self):
        """Realistic bullish scenario."""
        composites = _make_composites(fundamental=72, macro=65, sentiment=60, momentum=68)
        result = build_coherence_snapshot(composites)

        assert "subscores" in result
        assert len(result["subscores"]) == 4
        assert set(result["subscores"].keys()) == {
            "directional_alignment",
            "conviction_strength",
            "interaction_patterns",
            "narrative_stability",
        }

        assert "composite_score" in result
        assert isinstance(result["composite_score"], int)
        assert 0 <= result["composite_score"] <= 100

        assert "direction" in result
        assert result["direction"] == "BULLISH"

        assert "pillar_directions" in result
        assert len(result["pillar_directions"]) == 4

    def test_integration_mixed(self):
        """Mixed scenario."""
        composites = _make_composites(fundamental=75, macro=35, sentiment=55, momentum=45)
        result = build_coherence_snapshot(composites)

        assert isinstance(result["composite_score"], int)
        assert 0 <= result["composite_score"] <= 100
        assert "detected_patterns" in result
        assert isinstance(result["detected_patterns"], list)

    def test_integration_low_coverage_neutralizes(self):
        """sentiment_low_coverage=True prevents sentiment-dependent patterns in snapshot."""
        composites = _make_composites(momentum=25, fundamental=35, sentiment=35, macro=50)
        result_normal = build_coherence_snapshot(pillar_composites=composites)
        result_flagged = build_coherence_snapshot(
            pillar_composites=composites, sentiment_low_coverage=True,
        )
        normal_names = [p["name"] for p in result_normal["detected_patterns"]]
        flagged_names = [p["name"] for p in result_flagged["detected_patterns"]]
        assert "FALLING_KNIFE" in normal_names
        assert "FALLING_KNIFE" not in flagged_names
