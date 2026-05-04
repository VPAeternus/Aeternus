# tests/test_epistemic.py

import sys
import types
import pytest

# Stub chromadb before it can be imported (pydantic v1 incompatible with Python 3.14)
if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub

from tradingagents.graph.epistemic import (
    build_epistemic_report,
    _coverage_to_tier,
    _build_fundamental_confidence,
    _build_sentiment_confidence,
    _build_macro_confidence,
    _build_momentum_confidence,
    _build_options_confidence,
    _compute_sensitivity,
    _detect_conflicts,
    _compute_rating_proximity,
)


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def _fundamental_metrics(data_coverage=0.8, fscore=7, missing=1):
    return {
        "data_coverage": data_coverage,
        "piotroski": {"fscore": fscore, "missing_criteria": missing},
        "ratios": {"roe": 15},
        "balance": {},
        "cashflow": {},
        "income": {},
    }


def _sentiment_metrics(data_coverage=0.8, articles=20, quality="medium"):
    return {
        "data_coverage": data_coverage,
        "buzz": {"total_articles": articles, "source_quality": quality},
        "composite_score": 65,
    }


def _macro_metrics(data_coverage=0.9, fred=True):
    return {
        "data_coverage": data_coverage,
        "fred_available": fred,
        "regime": "NEUTRAL",
        "subscores": {
            "regime_fit": 60,
            "monetary_stress": 50,
            "rate_headwind": 45,
            "commodity_cycle": 55,
        },
    }


def _momentum_metrics(data_coverage=0.85, days=250):
    return {
        "data_coverage": data_coverage,
        "days_of_history": days,
        "subscores": {
            "trend_strength": 70,
            "momentum_health": 60,
            "regime_quality": 55,
            "volume_confirmation": 50,
        },
    }


def _options_metrics(data_coverage=0.6, expirations=2):
    return {
        "data_coverage": data_coverage,
        "expirations_analyzed": expirations,
        "sentiment_score": 55,
    }


def _coherence_snapshot(directions=None):
    if directions is None:
        directions = {
            "fundamental": "BULLISH",
            "macro": "NEUTRAL",
            "sentiment": "BULLISH",
            "momentum": "NEUTRAL",
        }
    return {
        "pillar_directions": directions,
        "composite_score": 60,
        "subscores": {},
    }


def _weights():
    return {
        "fundamental": 0.30,
        "coherence": 0.25,
        "macro": 0.20,
        "sentiment": 0.15,
        "momentum": 0.10,
    }


def _breakdown():
    return {
        "fundamental": 75,
        "coherence": 60,
        "macro": 55,
        "sentiment": 70,
        "momentum": 65,
    }


# ---------------------------------------------------------------------------
# TestCoverageTier
# ---------------------------------------------------------------------------

class TestCoverageTier:
    def test_full_coverage_is_high(self):
        assert _coverage_to_tier(1.0) == "HIGH"

    def test_boundary_08_is_high(self):
        assert _coverage_to_tier(0.8) == "HIGH"

    def test_mid_coverage_is_medium(self):
        assert _coverage_to_tier(0.5) == "MEDIUM"

    def test_boundary_04_is_medium(self):
        assert _coverage_to_tier(0.4) == "MEDIUM"

    def test_low_coverage_is_low(self):
        assert _coverage_to_tier(0.2) == "LOW"


# ---------------------------------------------------------------------------
# TestPillarConfidence
# ---------------------------------------------------------------------------

class TestPillarConfidence:
    def test_fundamental_good_data(self):
        result = _build_fundamental_confidence(_fundamental_metrics())
        assert result["level"] == "HIGH"
        assert result["data_coverage"] == 0.8
        assert result["notes"] == []

    def test_fundamental_degraded_missing_criteria(self):
        result = _build_fundamental_confidence(_fundamental_metrics(missing=5))
        assert any("Piotroski" in n for n in result["notes"])

    def test_fundamental_low_coverage_note(self):
        result = _build_fundamental_confidence(_fundamental_metrics(data_coverage=0.3))
        assert any("Limited fundamental data" in n for n in result["notes"])

    def test_sentiment_good_data(self):
        result = _build_sentiment_confidence(_sentiment_metrics())
        assert result["level"] == "HIGH"
        assert result["notes"] == []

    def test_sentiment_few_articles_note(self):
        result = _build_sentiment_confidence(_sentiment_metrics(articles=3))
        assert any("Very few articles" in n for n in result["notes"])

    def test_sentiment_low_quality_note(self):
        result = _build_sentiment_confidence(_sentiment_metrics(quality="low"))
        assert any("Low-quality" in n for n in result["notes"])

    def test_macro_good_data(self):
        result = _build_macro_confidence(_macro_metrics())
        assert result["level"] == "HIGH"
        assert result["notes"] == []

    def test_macro_no_fred_note(self):
        result = _build_macro_confidence(_macro_metrics(fred=False))
        assert any("FRED" in n for n in result["notes"])

    def test_momentum_good_data(self):
        result = _build_momentum_confidence(_momentum_metrics())
        assert result["level"] == "HIGH"
        assert result["notes"] == []

    def test_momentum_short_history_note(self):
        result = _build_momentum_confidence(_momentum_metrics(days=30))
        assert any("Limited price history" in n for n in result["notes"])


# ---------------------------------------------------------------------------
# TestSensitivity
# ---------------------------------------------------------------------------

class TestSensitivity:
    def test_weight_times_ten(self):
        sensitivity = _compute_sensitivity(_weights())
        assert sensitivity["fundamental"] == pytest.approx(3.0)
        assert sensitivity["coherence"] == pytest.approx(2.5)
        assert sensitivity["macro"] == pytest.approx(2.0)
        assert sensitivity["sentiment"] == pytest.approx(1.5)
        assert sensitivity["momentum"] == pytest.approx(1.0)

    def test_swing_pillar_is_highest_non_coherence(self):
        w = _weights()
        sensitivity = _compute_sensitivity(w)
        non_coherence = {p: s for p, s in sensitivity.items() if p != "coherence"}
        swing = max(non_coherence, key=lambda p: non_coherence[p])
        assert swing == "fundamental"

    def test_all_same_weights(self):
        w = {"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25}
        sensitivity = _compute_sensitivity(w)
        assert all(v == pytest.approx(2.5) for v in sensitivity.values())


# ---------------------------------------------------------------------------
# TestConflictDetection
# ---------------------------------------------------------------------------

class TestConflictDetection:
    def test_all_agree_no_conflicts(self):
        snap = _coherence_snapshot({
            "fundamental": "BULLISH",
            "sentiment": "BULLISH",
            "macro": "BULLISH",
            "momentum": "BULLISH",
        })
        assert _detect_conflicts(snap) == []

    def test_single_bull_bear_conflict(self):
        snap = _coherence_snapshot({
            "fundamental": "BULLISH",
            "macro": "BEARISH",
        })
        conflicts = _detect_conflicts(snap)
        assert len(conflicts) == 1
        assert set(conflicts[0]["pillars"]) == {"fundamental", "macro"}

    def test_two_conflicts(self):
        snap = _coherence_snapshot({
            "fundamental": "BULLISH",
            "macro": "BEARISH",
            "sentiment": "BULLISH",
            "momentum": "BEARISH",
        })
        conflicts = _detect_conflicts(snap)
        # fundamental vs macro, fundamental vs momentum, sentiment vs macro, sentiment vs momentum
        assert len(conflicts) == 4

    def test_neutral_pillars_ignored(self):
        snap = _coherence_snapshot({
            "fundamental": "BULLISH",
            "macro": "NEUTRAL",
            "sentiment": "NEUTRAL",
            "momentum": "BEARISH",
        })
        conflicts = _detect_conflicts(snap)
        assert len(conflicts) == 1
        assert set(conflicts[0]["pillars"]) == {"fundamental", "momentum"}


# ---------------------------------------------------------------------------
# TestRatingProximity
# ---------------------------------------------------------------------------

class TestRatingProximity:
    def test_score_near_80_boundary(self):
        result = _compute_rating_proximity(79.0, _weights(), _breakdown())
        assert result["nearest_boundary"] == 80.0
        assert result["boundary_labels"] == "Strong Buy/Buy"
        assert result["margin"] == pytest.approx(1.0)

    def test_score_mid_range(self):
        result = _compute_rating_proximity(50.0, _weights(), _breakdown())
        # 50 is equidistant from 60 and 40; min() picks first → 60
        assert result["nearest_boundary"] in (60.0, 40.0)
        assert result["current_score"] == 50.0

    def test_score_near_60_boundary(self):
        result = _compute_rating_proximity(61.0, _weights(), _breakdown())
        assert result["nearest_boundary"] == 60.0
        assert result["boundary_labels"] == "Buy/Hold"
        assert result["margin"] == pytest.approx(1.0)

    def test_flip_scenario_contains_pillar_name(self):
        result = _compute_rating_proximity(79.0, _weights(), _breakdown())
        flip = result["flip_scenario"]
        # Should contain a known non-coherence pillar name
        assert any(p in flip for p in ["fundamental", "macro", "sentiment", "momentum"])


# ---------------------------------------------------------------------------
# TestBuildEpistemicReport
# ---------------------------------------------------------------------------

class TestBuildEpistemicReport:
    def test_full_inputs_all_keys_present(self):
        report = build_epistemic_report(
            fundamental_metrics=_fundamental_metrics(),
            sentiment_metrics=_sentiment_metrics(),
            macro_metrics=_macro_metrics(),
            momentum_metrics=_momentum_metrics(),
            options_metrics=_options_metrics(),
            coherence_snapshot=_coherence_snapshot(),
            weights=_weights(),
            aeternus_score=72.0,
            breakdown=_breakdown(),
        )
        assert "pillar_confidence" in report
        assert "overall_confidence" in report
        assert "weakest_pillar" in report
        assert "sensitivity" in report
        assert "swing_pillar" in report
        assert "conflicts" in report
        assert "rating_proximity" in report
        # Check all 5 pillars present
        for pillar in ("fundamental", "sentiment", "macro", "momentum", "options"):
            assert pillar in report["pillar_confidence"]

    def test_missing_all_metrics_graceful(self):
        report = build_epistemic_report(
            fundamental_metrics=None,
            sentiment_metrics=None,
            macro_metrics=None,
            momentum_metrics=None,
            options_metrics=None,
            coherence_snapshot=None,
            weights=_weights(),
            aeternus_score=50.0,
            breakdown=_breakdown(),
        )
        assert report["overall_confidence"] in ("HIGH", "MEDIUM", "LOW")
        assert report["pillar_confidence"]["options"]["level"] == "LOW"
        assert "No options data" in report["pillar_confidence"]["options"]["notes"]

    def test_overall_confidence_is_minimum(self):
        # Force options to LOW coverage → overall should be LOW
        report = build_epistemic_report(
            fundamental_metrics=_fundamental_metrics(data_coverage=0.9),
            sentiment_metrics=_sentiment_metrics(data_coverage=0.9),
            macro_metrics=_macro_metrics(data_coverage=0.9),
            momentum_metrics=_momentum_metrics(data_coverage=0.9),
            options_metrics=_options_metrics(data_coverage=0.1),
            coherence_snapshot=_coherence_snapshot(),
            weights=_weights(),
            aeternus_score=70.0,
            breakdown=_breakdown(),
        )
        assert report["overall_confidence"] == "LOW"

    def test_weakest_pillar_is_correct(self):
        # options has lowest data_coverage = 0.1
        report = build_epistemic_report(
            fundamental_metrics=_fundamental_metrics(data_coverage=0.9),
            sentiment_metrics=_sentiment_metrics(data_coverage=0.8),
            macro_metrics=_macro_metrics(data_coverage=0.85),
            momentum_metrics=_momentum_metrics(data_coverage=0.75),
            options_metrics=_options_metrics(data_coverage=0.1),
            coherence_snapshot=_coherence_snapshot(),
            weights=_weights(),
            aeternus_score=70.0,
            breakdown=_breakdown(),
        )
        assert report["weakest_pillar"] == "options"
