"""Tests for tradingagents.graph.fama_french and FF-based alpha decomposition."""

import sys
import types
import os
import time
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

from tradingagents.graph.fama_french import (
    _parse_ff_csv,
    _cache_is_fresh,
    get_ff_factors,
    _CACHE_FILE,
)
from tradingagents.graph.aeternus_scoring import AeternusScorer


# ---------------------------------------------------------------------------
# Sample CSV content mimicking FF format
# ---------------------------------------------------------------------------

_SAMPLE_FF_CSV = """\
This file was created by CMPT_ME_DAILY_FACTORS using the 202601 CRSP database.
The 1-month TBill return is from Ibbotson and Associates Inc.

 Mkt-RF,SMB,HML,RF
20260101,  0.50,  0.10, -0.20,  0.01
20260102, -0.30,  0.05,  0.15,  0.01
20260103,  0.80, -0.10,  0.30,  0.01
20260106,  0.20,  0.00,  0.10,  0.01
20260107, -0.10,  0.15, -0.05,  0.01
"""


# ---------------------------------------------------------------------------
# _parse_ff_csv tests
# ---------------------------------------------------------------------------

class TestParseFFCsv:
    def test_parse_ff_csv_returns_correct_keys(self):
        """Parsed result has mkt_rf, smb, hml, rf keys."""
        result = _parse_ff_csv(_SAMPLE_FF_CSV, lookback_days=60)
        assert result is not None
        assert set(result.keys()) == {"mkt_rf", "smb", "hml", "rf"}

    def test_parse_ff_csv_computes_mean(self):
        """Mean of 5 rows: mkt_rf = (0.50-0.30+0.80+0.20-0.10)/5 = 0.22"""
        result = _parse_ff_csv(_SAMPLE_FF_CSV, lookback_days=60)
        assert result is not None
        assert abs(result["mkt_rf"] - 0.22) < 0.01
        assert abs(result["rf"] - 0.01) < 0.001

    def test_parse_ff_csv_lookback_limits_rows(self):
        """When lookback_days < total rows, only last N rows used."""
        result = _parse_ff_csv(_SAMPLE_FF_CSV, lookback_days=2)
        assert result is not None
        # Last 2 rows: (0.20, 0.00, 0.10, 0.01) and (-0.10, 0.15, -0.05, 0.01)
        assert abs(result["mkt_rf"] - 0.05) < 0.01

    def test_parse_ff_csv_empty_returns_none(self):
        """Empty CSV returns None."""
        result = _parse_ff_csv("", lookback_days=60)
        assert result is None

    def test_parse_ff_csv_no_data_rows_returns_none(self):
        """CSV with only header/description returns None."""
        result = _parse_ff_csv("This is a description\nAnother line\n", lookback_days=60)
        assert result is None


# ---------------------------------------------------------------------------
# Cache tests
# ---------------------------------------------------------------------------

class TestCacheFreshness:
    def test_cache_fresh_skips_download(self, monkeypatch, tmp_path):
        """When cache is fresh, no HTTP call is made."""
        import tradingagents.graph.fama_french as ff_module

        # Write fresh cache
        cache_file = tmp_path / "ff_factors_daily.csv"
        cache_file.write_text(_SAMPLE_FF_CSV)

        monkeypatch.setattr(ff_module, "_CACHE_FILE", str(cache_file))
        monkeypatch.setattr(ff_module, "_CACHE_MAX_AGE_SECONDS", 9999)

        download_called = False
        original_download = ff_module._download_and_cache
        def mock_download():
            nonlocal download_called
            download_called = True
            return None
        monkeypatch.setattr(ff_module, "_download_and_cache", mock_download)

        result = get_ff_factors(lookback_days=60)
        assert result is not None
        assert not download_called

    def test_cache_stale_triggers_download(self, monkeypatch, tmp_path):
        """When cache is stale, download is attempted."""
        import tradingagents.graph.fama_french as ff_module

        # Write stale cache (set mtime to long ago)
        cache_file = tmp_path / "ff_factors_daily.csv"
        cache_file.write_text(_SAMPLE_FF_CSV)
        old_time = time.time() - 999999
        os.utime(str(cache_file), (old_time, old_time))

        monkeypatch.setattr(ff_module, "_CACHE_FILE", str(cache_file))
        monkeypatch.setattr(ff_module, "_CACHE_MAX_AGE_SECONDS", 7 * 24 * 3600)

        download_called = False
        def mock_download():
            nonlocal download_called
            download_called = True
            return _SAMPLE_FF_CSV
        monkeypatch.setattr(ff_module, "_download_and_cache", mock_download)

        result = get_ff_factors(lookback_days=60)
        assert download_called


# ---------------------------------------------------------------------------
# Graceful failure
# ---------------------------------------------------------------------------

class TestGracefulFailure:
    def test_graceful_failure_returns_none(self, monkeypatch):
        """When download fails and no cache, returns None."""
        import tradingagents.graph.fama_french as ff_module

        monkeypatch.setattr(ff_module, "_cache_is_fresh", lambda: False)
        monkeypatch.setattr(ff_module, "_download_and_cache", lambda: None)
        monkeypatch.setattr(ff_module, "_read_cache", lambda: None)

        result = get_ff_factors(lookback_days=60)
        assert result is None


# ---------------------------------------------------------------------------
# Alpha decomposition integration
# ---------------------------------------------------------------------------

class MockLLM:
    def invoke(self, messages):
        class MockResponse:
            content = '{"fundamental_score": 70, "technical_score": 65, "macro_score": 60, "sentiment_score": 75, "momentum_score": 68, "confidence": 3, "score_rationales": {}}'
        return MockResponse()


class TestAlphaDecompositionFF:
    def test_alpha_decomposition_with_ff(self, monkeypatch):
        """When FF data available, factor_source='fama_french'."""
        import tradingagents.graph.aeternus_scoring as scoring_module

        monkeypatch.setattr(scoring_module, "get_ff_factors", lambda lookback_days=60: {
            "mkt_rf": 0.05, "smb": 0.02, "hml": -0.03, "rf": 0.01,
        })

        scorer = AeternusScorer(MockLLM())
        state = {"market_report": "Test"}
        rating = scorer.score(state)
        ad = rating["alpha_decomposition"]
        assert ad["factor_source"] == "fama_french"
        assert "factor_predicted" in ad
        assert "alpha_residual" in ad

    def test_alpha_decomposition_fallback(self, monkeypatch):
        """When FF data unavailable, factor_source='heuristic'."""
        import tradingagents.graph.aeternus_scoring as scoring_module

        monkeypatch.setattr(scoring_module, "get_ff_factors", lambda lookback_days=60: None)

        scorer = AeternusScorer(MockLLM())
        state = {"market_report": "Test"}
        rating = scorer.score(state)
        ad = rating["alpha_decomposition"]
        assert ad["factor_source"] == "heuristic"
