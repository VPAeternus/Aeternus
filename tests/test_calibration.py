"""
Tests for tradingagents.graph.calibration module.
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

import json
import pytest

from tradingagents.graph.calibration import (
    _is_win,
    _compute_calibration_by_confidence,
    _compute_accuracy_by_sector,
    _compute_accuracy_by_regime,
    _generate_bias_strings,
    build_calibration_report,
)


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def _closed_entry(
    ticker="AAPL",
    rating="Buy",
    price_at=150.0,
    close_price=160.0,
    confidence=3,
    sector="Technology",
    regime="NEUTRAL",
):
    return {
        "ticker": ticker,
        "rating": rating,
        "price_at_rating": price_at,
        "close_price": close_price,
        "confidence": confidence,
        "sector": sector,
        "weight_regime": regime,
        "status": "CLOSED",
        "date": "2025-01-01",
        "aeternus_score": 65.0,
        "rating_id": f"test-{ticker}-{confidence}",
    }


def _open_entry(
    ticker="MSFT",
    rating="Hold",
    price_at=400.0,
    confidence=3,
    sector="Technology",
):
    return {
        "ticker": ticker,
        "rating": rating,
        "price_at_rating": price_at,
        "confidence": confidence,
        "sector": sector,
        "status": "OPEN",
        "date": "2025-01-15",
        "aeternus_score": 50.0,
    }


# ---------------------------------------------------------------------------
# TestIsWin
# ---------------------------------------------------------------------------

class TestIsWin:
    def test_buy_up_is_win(self):
        entry = _closed_entry(rating="Buy", price_at=100.0, close_price=110.0)
        assert _is_win(entry) is True

    def test_buy_down_is_loss(self):
        entry = _closed_entry(rating="Buy", price_at=100.0, close_price=90.0)
        assert _is_win(entry) is False

    def test_sell_down_is_win(self):
        entry = _closed_entry(rating="Sell", price_at=100.0, close_price=85.0)
        assert _is_win(entry) is True

    def test_hold_returns_none(self):
        entry = _closed_entry(rating="Hold", price_at=100.0, close_price=110.0)
        assert _is_win(entry) is None

    def test_missing_prices_returns_none(self):
        entry = _closed_entry(rating="Buy")
        entry["price_at_rating"] = None
        entry["close_price"] = None
        assert _is_win(entry) is None


# ---------------------------------------------------------------------------
# TestCalibrationByConfidence
# ---------------------------------------------------------------------------

class TestCalibrationByConfidence:
    def test_all_five_levels_present(self):
        result = _compute_calibration_by_confidence([])
        assert set(result.keys()) == {1, 2, 3, 4, 5}

    def test_actual_computed_when_n_ge_5(self):
        entries = [
            _closed_entry(rating="Buy", price_at=100.0, close_price=110.0, confidence=3)
            for _ in range(5)
        ]
        result = _compute_calibration_by_confidence(entries)
        assert result[3]["n"] == 5
        assert result[3]["actual"] == pytest.approx(1.0)

    def test_actual_none_when_n_lt_5(self):
        entries = [
            _closed_entry(rating="Buy", price_at=100.0, close_price=110.0, confidence=4)
            for _ in range(4)
        ]
        result = _compute_calibration_by_confidence(entries)
        assert result[4]["n"] == 4
        assert result[4]["actual"] is None


# ---------------------------------------------------------------------------
# TestAccuracyBySector
# ---------------------------------------------------------------------------

class TestAccuracyBySector:
    def test_known_accuracy_calculation(self):
        entries = [
            _closed_entry(rating="Buy", price_at=100.0, close_price=110.0, sector="Tech"),
            _closed_entry(rating="Buy", price_at=100.0, close_price=110.0, sector="Tech"),
            _closed_entry(rating="Buy", price_at=100.0, close_price=90.0, sector="Tech"),
            _closed_entry(rating="Buy", price_at=100.0, close_price=90.0, sector="Tech"),
        ]
        result = _compute_accuracy_by_sector(entries)
        assert result["Tech"] == pytest.approx(0.5)

    def test_empty_sector_excluded(self):
        entry = _closed_entry(rating="Buy", price_at=100.0, close_price=110.0)
        entry["sector"] = ""
        result = _compute_accuracy_by_sector([entry])
        assert result == {}

    def test_open_entries_skipped(self):
        entries = [
            _closed_entry(rating="Buy", price_at=100.0, close_price=110.0, sector="Energy"),
            _open_entry(sector="Energy"),
        ]
        result = _compute_accuracy_by_sector(entries)
        # Only 1 closed Buy entry, it wins → accuracy = 1.0
        assert result["Energy"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# TestAccuracyByRegime
# ---------------------------------------------------------------------------

class TestAccuracyByRegime:
    def test_reads_weight_regime_field(self):
        entries = [
            _closed_entry(rating="Buy", price_at=100.0, close_price=110.0, regime="BULL"),
            _closed_entry(rating="Buy", price_at=100.0, close_price=90.0, regime="BULL"),
        ]
        result = _compute_accuracy_by_regime(entries)
        assert "BULL" in result
        assert result["BULL"] == pytest.approx(0.5)

    def test_handles_missing_regime(self):
        entry = _closed_entry(rating="Buy", price_at=100.0, close_price=110.0)
        entry["weight_regime"] = None
        result = _compute_accuracy_by_regime([entry])
        assert result == {}

    def test_multiple_regimes(self):
        entries = [
            _closed_entry(rating="Buy", price_at=100.0, close_price=110.0, regime="BULL"),
            _closed_entry(rating="Buy", price_at=100.0, close_price=90.0, regime="BEAR"),
        ]
        result = _compute_accuracy_by_regime(entries)
        assert result["BULL"] == pytest.approx(1.0)
        assert result["BEAR"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# TestBiasStrings
# ---------------------------------------------------------------------------

class TestBiasStrings:
    def test_overconfidence_detected(self):
        # Level 5 predicted 100%, actual 0% (5 losses) → overconfident
        calibration = {
            1: {"predicted": 0.20, "actual": None, "n": 0},
            2: {"predicted": 0.40, "actual": None, "n": 0},
            3: {"predicted": 0.60, "actual": None, "n": 0},
            4: {"predicted": 0.80, "actual": None, "n": 0},
            5: {"predicted": 1.00, "actual": 0.0, "n": 5},
        }
        biases = _generate_bias_strings(calibration, {}, {}, closed_count=15)
        assert any("Overconfident at level 5" in b for b in biases)

    def test_small_sample_returns_empty(self):
        calibration = {
            1: {"predicted": 0.20, "actual": 0.90, "n": 5},
            2: {"predicted": 0.40, "actual": None, "n": 0},
            3: {"predicted": 0.60, "actual": None, "n": 0},
            4: {"predicted": 0.80, "actual": None, "n": 0},
            5: {"predicted": 1.00, "actual": None, "n": 0},
        }
        biases = _generate_bias_strings(calibration, {}, {}, closed_count=5)
        assert biases == []


# ---------------------------------------------------------------------------
# TestBuildCalibrationReport
# ---------------------------------------------------------------------------

class TestBuildCalibrationReport:
    def test_all_keys_present(self, tmp_path):
        track_file = tmp_path / "track_record.json"
        track_file.write_text(json.dumps([]))
        result = build_calibration_report(str(track_file))
        expected_keys = {
            "total_decisions",
            "closed_decisions",
            "calibration_by_confidence",
            "accuracy_by_sector",
            "accuracy_by_regime",
            "systematic_biases",
            "sample_sufficient",
            "last_updated",
        }
        assert set(result.keys()) == expected_keys

    def test_sample_sufficient_requires_30_closed(self, tmp_path):
        track_file = tmp_path / "track_record.json"

        # 29 closed → not sufficient
        entries_29 = [_closed_entry(ticker=f"T{i}") for i in range(29)]
        track_file.write_text(json.dumps(entries_29))
        result = build_calibration_report(str(track_file))
        assert result["sample_sufficient"] is False

        # 30 closed → sufficient
        entries_30 = [_closed_entry(ticker=f"T{i}") for i in range(30)]
        track_file.write_text(json.dumps(entries_30))
        result = build_calibration_report(str(track_file))
        assert result["sample_sufficient"] is True

    def test_empty_track_record_returns_defaults(self, tmp_path):
        track_file = tmp_path / "track_record.json"
        track_file.write_text(json.dumps([]))
        result = build_calibration_report(str(track_file))
        assert result["total_decisions"] == 0
        assert result["closed_decisions"] == 0
        assert result["sample_sufficient"] is False
        assert result["systematic_biases"] == []
        assert set(result["calibration_by_confidence"].keys()) == {1, 2, 3, 4, 5}

    def test_file_not_found_returns_defaults_gracefully(self):
        result = build_calibration_report("/nonexistent/path/track_record.json")
        assert result["total_decisions"] == 0
        assert result["closed_decisions"] == 0
        assert result["sample_sufficient"] is False
        assert "last_updated" in result
