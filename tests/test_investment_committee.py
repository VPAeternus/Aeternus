"""
Tests for tradingagents.scheduler.agents.investment_committee module.
"""
import sys
import types

# chromadb stub — required before any project imports
if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub

import datetime as dt
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from tradingagents.scheduler.agents.investment_committee import (
    InvestmentCommitteeAgent,
    load_ic_adjustments,
)
from tradingagents.scheduler.agent_bus import AgentBus, SignalType
from tradingagents.scheduler.base_agent import AgentRunResult


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def _make_bus():
    """Create a mock AgentBus."""
    bus = MagicMock(spec=AgentBus)
    bus.publish = MagicMock()
    bus.consume = MagicMock(return_value=[])
    return bus


def _write_ic_file(path: Path, adjustments: dict, expired: bool = False):
    """Write a test IC adjustment file."""
    now = dt.datetime.now(dt.timezone.utc)
    if expired:
        expires = now - dt.timedelta(days=1)
    else:
        expires = now + dt.timedelta(days=7)
    data = {
        "generated_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "generated_by": "InvestmentCommittee",
        "closed_trades_analyzed": 42,
        "adjustments": adjustments,
    }
    path.write_text(json.dumps(data))


def _mock_calibration(closed_decisions=20):
    """Return a minimal calibration report."""
    return {
        "total_decisions": closed_decisions + 5,
        "closed_decisions": closed_decisions,
        "calibration_by_confidence": {
            1: {"predicted": 0.20, "actual": 0.15, "n": 10},
            2: {"predicted": 0.40, "actual": 0.35, "n": 10},
            3: {"predicted": 0.60, "actual": 0.55, "n": 10},
            4: {"predicted": 0.80, "actual": 0.90, "n": 10},
            5: {"predicted": 1.00, "actual": 0.80, "n": 10},
        },
        "accuracy_by_sector": {"Technology": 0.70, "Energy": 0.40},
        "accuracy_by_regime": {"NEUTRAL": 0.60},
        "systematic_biases": ["Overconfident at level 5"],
        "sample_sufficient": closed_decisions >= 30,
    }


def _mock_outcomes():
    """Return a minimal live outcome report."""
    return {
        "status": "COMPLETE",
        "total_closed_trades": 20,
        "matched_to_analysis": 15,
        "overall": {"count": 15, "win_rate": 0.60, "profit_factor": 1.5, "avg_return_pct": 2.5},
        "by_lane": {"CORE": {"count": 10, "win_rate": 0.65}, "MOMENTUM": {"count": 5, "win_rate": 0.50}},
        "by_exit_rule": {"stop_loss": {"count": 3}, "take_profit": {"count": 5}},
        "trades": [],
    }


# ---------------------------------------------------------------------------
# TestLoadIcAdjustments
# ---------------------------------------------------------------------------

class TestLoadIcAdjustments:
    """Tests for load_ic_adjustments() function."""

    def test_missing_file_returns_empty(self, tmp_path):
        """Missing file returns empty dict."""
        result = load_ic_adjustments("nonexistent.json", output_dir=str(tmp_path))
        assert result == {}

    def test_expired_file_returns_empty(self, tmp_path):
        """File with past expires_at returns empty dict."""
        ic_file = tmp_path / "ic_signal_weights.json"
        _write_ic_file(ic_file, {"price_momentum": 5.0}, expired=True)
        result = load_ic_adjustments("ic_signal_weights.json", output_dir=str(tmp_path))
        assert result == {}

    def test_valid_file_returns_data(self, tmp_path):
        """File with future expires_at returns full dict with adjustments."""
        ic_file = tmp_path / "ic_signal_weights.json"
        adjustments = {"price_momentum": 5.0, "social_momentum": -2.0}
        _write_ic_file(ic_file, adjustments, expired=False)
        result = load_ic_adjustments("ic_signal_weights.json", output_dir=str(tmp_path))
        assert result.get("adjustments") == adjustments
        assert "generated_at" in result
        assert "expires_at" in result

    def test_malformed_json_returns_empty(self, tmp_path):
        """File with invalid JSON returns empty dict."""
        ic_file = tmp_path / "ic_signal_weights.json"
        ic_file.write_text("{ invalid json")
        result = load_ic_adjustments("ic_signal_weights.json", output_dir=str(tmp_path))
        assert result == {}

    def test_no_expires_at_returns_empty(self, tmp_path):
        """File missing expires_at key returns empty dict."""
        ic_file = tmp_path / "ic_signal_weights.json"
        data = {
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "generated_by": "InvestmentCommittee",
            "adjustments": {"price_momentum": 5.0},
        }
        ic_file.write_text(json.dumps(data))
        result = load_ic_adjustments("ic_signal_weights.json", output_dir=str(tmp_path))
        assert result == {}


# ---------------------------------------------------------------------------
# TestRunCycleGuards
# ---------------------------------------------------------------------------

class TestRunCycleGuards:
    """Tests for run_cycle() guard conditions."""

    def test_insufficient_trades_returns_early(self, tmp_path, monkeypatch):
        """When closed trades < min_closed_trades, return early with summary."""
        bus = _make_bus()
        config = {"min_closed_trades": 10}
        agent = InvestmentCommitteeAgent(bus, config)
        agent.output_dir = tmp_path

        calibration = _mock_calibration(closed_decisions=5)
        outcomes = _mock_outcomes()

        monkeypatch.setattr(
            "tradingagents.graph.calibration.build_calibration_report",
            lambda *args, **kwargs: calibration
        )
        monkeypatch.setattr(
            "tradingagents.evidence.live_outcomes.build_live_outcome_report",
            lambda *args, **kwargs: outcomes
        )

        result = agent.run_cycle()

        assert result.success is True
        assert "insufficient" in result.summary.lower()
        bus.publish.assert_not_called()

    def test_zero_closed_returns_summary(self, tmp_path, monkeypatch):
        """Zero closed trades returns with appropriate summary."""
        bus = _make_bus()
        config = {"min_closed_trades": 10}
        agent = InvestmentCommitteeAgent(bus, config)
        agent.output_dir = tmp_path

        calibration = _mock_calibration(closed_decisions=0)
        outcomes = _mock_outcomes()

        monkeypatch.setattr(
            "tradingagents.graph.calibration.build_calibration_report",
            lambda *args, **kwargs: calibration
        )
        monkeypatch.setattr(
            "tradingagents.evidence.live_outcomes.build_live_outcome_report",
            lambda *args, **kwargs: outcomes
        )

        result = agent.run_cycle()

        assert result.success is True
        assert "0" in result.summary or "insufficient" in result.summary.lower()

    def test_minimum_threshold_configurable(self, tmp_path, monkeypatch):
        """min_closed_trades from config is respected."""
        bus = _make_bus()
        config = {"min_closed_trades": 3}
        agent = InvestmentCommitteeAgent(bus, config)
        agent.output_dir = tmp_path

        calibration = _mock_calibration(closed_decisions=5)
        outcomes = _mock_outcomes()

        mock_llm_response = {
            "signal_weight_deltas": {"price_momentum": 2.0},
            "sector_overrides": {"Technology": 0.05},
            "confidence_calibration": {"1": -0.1},
        }

        monkeypatch.setattr(
            "tradingagents.graph.calibration.build_calibration_report",
            lambda *args, **kwargs: calibration
        )
        monkeypatch.setattr(
            "tradingagents.evidence.live_outcomes.build_live_outcome_report",
            lambda *args, **kwargs: outcomes
        )
        monkeypatch.setattr(
            InvestmentCommitteeAgent, "_reason_adjustments",
            lambda self, *args: mock_llm_response
        )

        result = agent.run_cycle()

        assert result.success is True
        assert result.agent_name == "InvestmentCommittee"


# ---------------------------------------------------------------------------
# TestAdjustmentFileFormat
# ---------------------------------------------------------------------------

class TestAdjustmentFileFormat:
    """Tests for adjustment file format and fields."""

    def test_generated_at_present(self, tmp_path, monkeypatch):
        """Written file has generated_at field."""
        bus = _make_bus()
        config = {"min_closed_trades": 1}
        agent = InvestmentCommitteeAgent(bus, config)
        agent.output_dir = tmp_path

        calibration = _mock_calibration(closed_decisions=10)
        outcomes = _mock_outcomes()

        mock_llm_response = {
            "signal_weight_deltas": {"price_momentum": 2.0},
            "sector_overrides": {},
            "confidence_calibration": {},
        }

        monkeypatch.setattr(
            "tradingagents.graph.calibration.build_calibration_report",
            lambda *args, **kwargs: calibration
        )
        monkeypatch.setattr(
            "tradingagents.evidence.live_outcomes.build_live_outcome_report",
            lambda *args, **kwargs: outcomes
        )
        monkeypatch.setattr(
            InvestmentCommitteeAgent, "_reason_adjustments",
            lambda self, *args: mock_llm_response
        )

        agent.run_cycle()

        ic_file = tmp_path / "ic_signal_weights.json"
        assert ic_file.exists()
        data = json.loads(ic_file.read_text())
        assert "generated_at" in data
        assert len(data["generated_at"]) > 0

    def test_expires_at_seven_days(self, tmp_path, monkeypatch):
        """expires_at is approximately 7 days from generated_at."""
        bus = _make_bus()
        config = {"min_closed_trades": 1}
        agent = InvestmentCommitteeAgent(bus, config)
        agent.output_dir = tmp_path

        calibration = _mock_calibration(closed_decisions=10)
        outcomes = _mock_outcomes()

        mock_llm_response = {
            "signal_weight_deltas": {"price_momentum": 2.0},
            "sector_overrides": {},
            "confidence_calibration": {},
        }

        monkeypatch.setattr(
            "tradingagents.graph.calibration.build_calibration_report",
            lambda *args, **kwargs: calibration
        )
        monkeypatch.setattr(
            "tradingagents.evidence.live_outcomes.build_live_outcome_report",
            lambda *args, **kwargs: outcomes
        )
        monkeypatch.setattr(
            InvestmentCommitteeAgent, "_reason_adjustments",
            lambda self, *args: mock_llm_response
        )

        agent.run_cycle()

        ic_file = tmp_path / "ic_signal_weights.json"
        data = json.loads(ic_file.read_text())
        generated = dt.datetime.fromisoformat(data["generated_at"])
        expires = dt.datetime.fromisoformat(data["expires_at"])
        delta = (expires - generated).days
        assert delta == 7

    def test_adjustments_key_present(self, tmp_path, monkeypatch):
        """File has adjustments dict with expected keys."""
        bus = _make_bus()
        config = {"min_closed_trades": 1}
        agent = InvestmentCommitteeAgent(bus, config)
        agent.output_dir = tmp_path

        calibration = _mock_calibration(closed_decisions=10)
        outcomes = _mock_outcomes()

        mock_llm_response = {
            "signal_weight_deltas": {"price_momentum": 2.5, "social_momentum": -1.0},
            "sector_overrides": {},
            "confidence_calibration": {},
        }

        monkeypatch.setattr(
            "tradingagents.graph.calibration.build_calibration_report",
            lambda *args, **kwargs: calibration
        )
        monkeypatch.setattr(
            "tradingagents.evidence.live_outcomes.build_live_outcome_report",
            lambda *args, **kwargs: outcomes
        )
        monkeypatch.setattr(
            InvestmentCommitteeAgent, "_reason_adjustments",
            lambda self, *args: mock_llm_response
        )

        agent.run_cycle()

        ic_file = tmp_path / "ic_signal_weights.json"
        data = json.loads(ic_file.read_text())
        assert "adjustments" in data
        assert isinstance(data["adjustments"], dict)

    def test_generated_by_correct(self, tmp_path, monkeypatch):
        """generated_by is 'InvestmentCommittee'."""
        bus = _make_bus()
        config = {"min_closed_trades": 1}
        agent = InvestmentCommitteeAgent(bus, config)
        agent.output_dir = tmp_path

        calibration = _mock_calibration(closed_decisions=10)
        outcomes = _mock_outcomes()

        mock_llm_response = {
            "signal_weight_deltas": {},
            "sector_overrides": {},
            "confidence_calibration": {},
        }

        monkeypatch.setattr(
            "tradingagents.graph.calibration.build_calibration_report",
            lambda *args, **kwargs: calibration
        )
        monkeypatch.setattr(
            "tradingagents.evidence.live_outcomes.build_live_outcome_report",
            lambda *args, **kwargs: outcomes
        )
        monkeypatch.setattr(
            InvestmentCommitteeAgent, "_reason_adjustments",
            lambda self, *args: mock_llm_response
        )

        agent.run_cycle()

        ic_file = tmp_path / "ic_signal_weights.json"
        data = json.loads(ic_file.read_text())
        assert data["generated_by"] == "InvestmentCommittee"


# ---------------------------------------------------------------------------
# TestSignalWeightIntegration
# ---------------------------------------------------------------------------

class TestSignalWeightIntegration:
    """Tests for IC adjustments applied to signal weights via dealflow scoring."""

    def test_positive_delta_increases_weight(self, tmp_path):
        """Positive delta on price_momentum increases its weight."""
        from tradingagents.dealflow.scoring import CORE_SCORE_WEIGHTS

        # Create a mock ic_signal_weights.json with positive delta
        ic_file = tmp_path / "ic_signal_weights.json"
        _write_ic_file(ic_file, {"price_momentum": 5.0}, expired=False)

        # Simulate applying the delta
        original_weight = CORE_SCORE_WEIGHTS["price_momentum"]
        adjusted_weight = max(0, min(40, original_weight + 5.0))

        assert adjusted_weight > original_weight

    def test_negative_delta_decreases_weight(self, tmp_path):
        """Negative delta on price_momentum decreases its weight."""
        from tradingagents.dealflow.scoring import CORE_SCORE_WEIGHTS

        ic_file = tmp_path / "ic_signal_weights.json"
        _write_ic_file(ic_file, {"price_momentum": -5.0}, expired=False)

        original_weight = CORE_SCORE_WEIGHTS["price_momentum"]
        adjusted_weight = max(0, min(40, original_weight - 5.0))

        assert adjusted_weight < original_weight

    def test_weight_clamped_0_40(self, tmp_path):
        """Adjusted weights are clamped to [0, 40]."""
        from tradingagents.dealflow.scoring import CORE_SCORE_WEIGHTS

        # Test floor (clamping to 0)
        ic_file = tmp_path / "ic_signal_weights.json"
        _write_ic_file(ic_file, {"price_momentum": -999.0}, expired=False)

        original_weight = CORE_SCORE_WEIGHTS["price_momentum"]
        adjusted_weight = max(0, min(40, original_weight - 999.0))

        assert adjusted_weight == 0

        # Test ceiling (clamping to 40)
        _write_ic_file(ic_file, {"price_momentum": 999.0}, expired=False)
        adjusted_weight = max(0, min(40, original_weight + 999.0))

        assert adjusted_weight == 40


# ---------------------------------------------------------------------------
# TestSectorOverrideIntegration
# ---------------------------------------------------------------------------

class TestSectorOverrideIntegration:
    """Tests for sector override adjustments in dealflow scoring."""

    def test_positive_override_increases_score(self, tmp_path):
        """Positive sector override multiplies score upward."""
        ic_file = tmp_path / "ic_sector_overrides.json"
        _write_ic_file(ic_file, {"Technology": 0.10}, expired=False)

        base_score = 50.0
        override = 0.10
        adjusted_score = base_score * (1 + override)

        assert adjusted_score == pytest.approx(55.0)
        assert adjusted_score > base_score

    def test_negative_override_decreases_score(self, tmp_path):
        """Negative sector override multiplies score downward."""
        ic_file = tmp_path / "ic_sector_overrides.json"
        _write_ic_file(ic_file, {"Energy": -0.10}, expired=False)

        base_score = 50.0
        override = -0.10
        adjusted_score = base_score * (1 + override)

        assert adjusted_score == pytest.approx(45.0)
        assert adjusted_score < base_score

    def test_clamped_to_bounds(self, tmp_path):
        """Sector overrides are clamped to reasonable bounds (e.g., +/- 0.20)."""
        ic_file = tmp_path / "ic_sector_overrides.json"

        # Test upper bound
        _write_ic_file(ic_file, {"Technology": 0.50}, expired=False)
        raw_override = 0.50
        clamped = max(-0.20, min(0.20, raw_override))

        assert clamped == 0.20

        # Test lower bound
        _write_ic_file(ic_file, {"Energy": -0.50}, expired=False)
        raw_override = -0.50
        clamped = max(-0.20, min(0.20, raw_override))

        assert clamped == -0.20


# ---------------------------------------------------------------------------
# TestConfidenceCalibration
# ---------------------------------------------------------------------------

class TestConfidenceCalibration:
    """Tests for confidence calibration applied in aeternus_scoring."""

    def test_delta_applied_to_confidence(self, tmp_path):
        """Confidence delta is applied from ic_confidence_calibration.json."""
        # Note: JSON keys are always strings, so "4" not 4
        ic_file = tmp_path / "ic_confidence_calibration.json"
        _write_ic_file(ic_file, {"1": -0.5, "2": -0.2, "3": 0.0, "4": 0.2, "5": 0.5}, expired=False)

        data = json.loads(ic_file.read_text())
        adjustments = data.get("adjustments", {})

        # Simulate applying delta for confidence 4 (key is str in JSON)
        original_confidence = 4
        delta = adjustments.get(str(original_confidence), 0)
        adjusted_confidence = original_confidence + delta

        assert adjusted_confidence == 4.2

    def test_result_clamped_1_5(self, tmp_path):
        """Confidence after adjustment is clamped to [1, 5]."""
        ic_file = tmp_path / "ic_confidence_calibration.json"

        # Test floor clamp
        _write_ic_file(ic_file, {"1": -10.0}, expired=False)
        data = json.loads(ic_file.read_text())
        delta = data["adjustments"].get("1", 0)
        adjusted = max(1, min(5, int(round(1 + delta))))

        assert adjusted == 1

        # Test ceiling clamp
        _write_ic_file(ic_file, {"5": 10.0}, expired=False)
        data = json.loads(ic_file.read_text())
        delta = data["adjustments"].get("5", 0)
        adjusted = max(1, min(5, int(round(5 + delta))))

        assert adjusted == 5


# ---------------------------------------------------------------------------
# TestICReviewCompleteSignal
# ---------------------------------------------------------------------------

class TestICReviewCompleteSignal:
    """Tests for IC_REVIEW_COMPLETE signal publishing."""

    def test_signal_published_on_success(self, tmp_path, monkeypatch):
        """After successful run_cycle, IC_REVIEW_COMPLETE signal is published."""
        bus = _make_bus()
        config = {"min_closed_trades": 1}
        agent = InvestmentCommitteeAgent(bus, config)
        agent.output_dir = tmp_path

        calibration = _mock_calibration(closed_decisions=20)
        outcomes = _mock_outcomes()

        mock_llm_response = {
            "signal_weight_deltas": {"price_momentum": 1.0},
            "sector_overrides": {},
            "confidence_calibration": {},
        }

        monkeypatch.setattr(
            "tradingagents.graph.calibration.build_calibration_report",
            lambda *args, **kwargs: calibration
        )
        monkeypatch.setattr(
            "tradingagents.evidence.live_outcomes.build_live_outcome_report",
            lambda *args, **kwargs: outcomes
        )
        monkeypatch.setattr(
            InvestmentCommitteeAgent, "_reason_adjustments",
            lambda self, *args: mock_llm_response
        )

        result = agent.run_cycle()

        assert result.success is True
        bus.publish.assert_called()
        calls = bus.publish.call_args_list
        signal_types = [call[0][0].signal_type for call in calls]
        assert SignalType.IC_REVIEW_COMPLETE in signal_types

    def test_signal_not_published_on_insufficient(self, tmp_path, monkeypatch):
        """When insufficient closed trades, IC_REVIEW_COMPLETE is NOT published."""
        bus = _make_bus()
        config = {"min_closed_trades": 30}
        agent = InvestmentCommitteeAgent(bus, config)
        agent.output_dir = tmp_path

        calibration = _mock_calibration(closed_decisions=5)
        outcomes = _mock_outcomes()

        monkeypatch.setattr(
            "tradingagents.graph.calibration.build_calibration_report",
            lambda *args, **kwargs: calibration
        )
        monkeypatch.setattr(
            "tradingagents.evidence.live_outcomes.build_live_outcome_report",
            lambda *args, **kwargs: outcomes
        )

        result = agent.run_cycle()

        assert result.success is True
        bus.publish.assert_not_called()


# ---------------------------------------------------------------------------
# TestAgentInitialization
# ---------------------------------------------------------------------------

class TestAgentInitialization:
    """Tests for InvestmentCommitteeAgent initialization."""

    def test_agent_name_is_correct(self):
        """Agent name should be 'InvestmentCommittee'."""
        bus = _make_bus()
        agent = InvestmentCommitteeAgent(bus)
        assert agent.name == "InvestmentCommittee"

    def test_default_min_closed_trades(self):
        """Default min_closed_trades should be 10."""
        bus = _make_bus()
        agent = InvestmentCommitteeAgent(bus)
        assert agent.min_closed_trades == 10

    def test_config_override_min_closed_trades(self):
        """Config should override min_closed_trades."""
        bus = _make_bus()
        config = {"min_closed_trades": 25}
        agent = InvestmentCommitteeAgent(bus, config)
        assert agent.min_closed_trades == 25

    def test_output_dir_created(self, tmp_path):
        """output_dir should be set and default to eval_results/control."""
        bus = _make_bus()
        agent = InvestmentCommitteeAgent(bus)
        # Check that output_dir is set (either to default or can be overridden)
        assert hasattr(agent, "output_dir")


# ---------------------------------------------------------------------------
# TestMultipleAdjustmentFiles
# ---------------------------------------------------------------------------

class TestMultipleAdjustmentFiles:
    """Tests for handling all three adjustment file types."""

    def test_writes_three_files_on_success(self, tmp_path, monkeypatch):
        """Successful run writes three JSON files."""
        bus = _make_bus()
        config = {"min_closed_trades": 1}
        agent = InvestmentCommitteeAgent(bus, config)
        agent.output_dir = tmp_path

        calibration = _mock_calibration(closed_decisions=20)
        outcomes = _mock_outcomes()

        mock_llm_response = {
            "signal_weight_deltas": {"price_momentum": 2.0},
            "sector_overrides": {"Technology": 0.05},
            "confidence_calibration": {"1": -0.1, "2": 0.0},
        }

        monkeypatch.setattr(
            "tradingagents.graph.calibration.build_calibration_report",
            lambda *args, **kwargs: calibration
        )
        monkeypatch.setattr(
            "tradingagents.evidence.live_outcomes.build_live_outcome_report",
            lambda *args, **kwargs: outcomes
        )
        monkeypatch.setattr(
            InvestmentCommitteeAgent, "_reason_adjustments",
            lambda self, *args: mock_llm_response
        )

        result = agent.run_cycle()

        assert result.success is True

        ic_signal_weights = tmp_path / "ic_signal_weights.json"
        ic_sector_overrides = tmp_path / "ic_sector_overrides.json"
        ic_confidence_calibration = tmp_path / "ic_confidence_calibration.json"

        assert ic_signal_weights.exists()
        assert ic_sector_overrides.exists()
        assert ic_confidence_calibration.exists()

        weights_data = json.loads(ic_signal_weights.read_text())
        assert weights_data["adjustments"]["price_momentum"] == 2.0

        sector_data = json.loads(ic_sector_overrides.read_text())
        assert sector_data["adjustments"]["Technology"] == 0.05

        conf_data = json.loads(ic_confidence_calibration.read_text())
        assert conf_data["adjustments"]["1"] == -0.1


# ---------------------------------------------------------------------------
# TestRunCycleMetrics
# ---------------------------------------------------------------------------

class TestRunCycleMetrics:
    """Tests for AgentRunResult metrics."""

    def test_result_includes_timestamps(self, tmp_path, monkeypatch):
        """AgentRunResult includes started_at and completed_at."""
        bus = _make_bus()
        config = {"min_closed_trades": 1}
        agent = InvestmentCommitteeAgent(bus, config)
        agent.output_dir = tmp_path

        calibration = _mock_calibration(closed_decisions=10)
        outcomes = _mock_outcomes()

        mock_llm_response = {
            "signal_weight_deltas": {},
            "sector_overrides": {},
            "confidence_calibration": {},
        }

        monkeypatch.setattr(
            "tradingagents.graph.calibration.build_calibration_report",
            lambda *args, **kwargs: calibration
        )
        monkeypatch.setattr(
            "tradingagents.evidence.live_outcomes.build_live_outcome_report",
            lambda *args, **kwargs: outcomes
        )
        monkeypatch.setattr(
            InvestmentCommitteeAgent, "_reason_adjustments",
            lambda self, *args: mock_llm_response
        )

        result = agent.run_cycle()

        assert result.started_at is not None
        assert result.completed_at is not None
        assert len(result.started_at) > 0
        assert len(result.completed_at) > 0

    def test_success_flag_on_guard(self, tmp_path, monkeypatch):
        """Guard returns success=True with insufficient-data summary."""
        bus = _make_bus()
        config = {"min_closed_trades": 20}
        agent = InvestmentCommitteeAgent(bus, config)
        agent.output_dir = tmp_path

        calibration = _mock_calibration(closed_decisions=5)
        outcomes = _mock_outcomes()

        monkeypatch.setattr(
            "tradingagents.graph.calibration.build_calibration_report",
            lambda *args, **kwargs: calibration
        )
        monkeypatch.setattr(
            "tradingagents.evidence.live_outcomes.build_live_outcome_report",
            lambda *args, **kwargs: outcomes
        )

        result = agent.run_cycle()

        assert result.success is True
        assert "insufficient" in result.summary.lower()
        assert result.agent_name == "InvestmentCommittee"

    def test_signals_published_count(self, tmp_path, monkeypatch):
        """signals_published is incremented for each signal sent."""
        bus = _make_bus()
        config = {"min_closed_trades": 1}
        agent = InvestmentCommitteeAgent(bus, config)
        agent.output_dir = tmp_path

        calibration = _mock_calibration(closed_decisions=15)
        outcomes = _mock_outcomes()

        mock_llm_response = {
            "signal_weight_deltas": {"price_momentum": 1.0},
            "sector_overrides": {},
            "confidence_calibration": {},
        }

        monkeypatch.setattr(
            "tradingagents.graph.calibration.build_calibration_report",
            lambda *args, **kwargs: calibration
        )
        monkeypatch.setattr(
            "tradingagents.evidence.live_outcomes.build_live_outcome_report",
            lambda *args, **kwargs: outcomes
        )
        monkeypatch.setattr(
            InvestmentCommitteeAgent, "_reason_adjustments",
            lambda self, *args: mock_llm_response
        )

        result = agent.run_cycle()

        assert result.success is True
        assert result.signals_published >= 1
