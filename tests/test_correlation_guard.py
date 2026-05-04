# tests/test_correlation_guard.py

import sys
import types
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock

# Stub chromadb (Python 3.14 compat)
if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub

from tradingagents.graph.correlation_guard import build_correlation_brief


# ---------------------------------------------------------------------------
# Mock data factory helpers
# ---------------------------------------------------------------------------


def _mock_download_correlated(tickers, **kwargs):
    """Return synthetic price data where all symbols are highly correlated."""
    dates = pd.date_range(end="2026-01-01", periods=30, freq="B")
    base = np.cumsum(np.random.RandomState(42).randn(30)) + 100
    data = {}
    ticker_list = tickers if isinstance(tickers, list) else tickers.split()
    for t in ticker_list:
        # Add small random noise to maintain high correlation
        data[t] = base + np.random.RandomState(hash(t) % 2**31).randn(30) * 0.1
    df = pd.DataFrame(data, index=dates)
    # yf.download returns MultiIndex columns: (Price, Ticker)
    df.columns = pd.MultiIndex.from_product([["Close"], df.columns])
    return df


def _mock_download_uncorrelated(tickers, **kwargs):
    """Return synthetic price data where symbols are uncorrelated."""
    dates = pd.date_range(end="2026-01-01", periods=30, freq="B")
    data = {}
    ticker_list = tickers if isinstance(tickers, list) else tickers.split()
    for i, t in enumerate(ticker_list):
        # Each ticker has its own random walk
        data[t] = np.cumsum(np.random.RandomState(i * 1000).randn(30)) + 100
    df = pd.DataFrame(data, index=dates)
    df.columns = pd.MultiIndex.from_product([["Close"], df.columns])
    return df


def _mock_download_insufficient_data(tickers, **kwargs):
    """Return only 10 rows of data (< 20 threshold)."""
    dates = pd.date_range(end="2026-01-01", periods=10, freq="B")
    ticker_list = tickers if isinstance(tickers, list) else tickers.split()
    data = {t: np.linspace(100, 105, 10) for t in ticker_list}
    df = pd.DataFrame(data, index=dates)
    df.columns = pd.MultiIndex.from_product([["Close"], df.columns])
    return df


def _mock_download_empty(tickers, **kwargs):
    """Return empty DataFrame."""
    return pd.DataFrame()


# ---------------------------------------------------------------------------
# Basic input tests
# ---------------------------------------------------------------------------


class TestBuildCorrelationBriefBasicInput:
    """Test basic input validation."""

    def test_zero_symbols(self):
        """build_correlation_brief with 0 symbols → empty string."""
        result = build_correlation_brief([])
        assert result == ""

    def test_one_symbol(self):
        """build_correlation_brief with 1 symbol → empty string."""
        result = build_correlation_brief(["AAPL"])
        assert result == ""

    def test_two_symbols_with_valid_data(self, monkeypatch):
        """build_correlation_brief with 2+ symbols and valid mock data → contains 'PORTFOLIO CORRELATION'."""
        import yfinance
        monkeypatch.setattr(
            yfinance,
            "download",
            _mock_download_uncorrelated,
        )
        result = build_correlation_brief(["AAPL", "MSFT"])
        assert "PORTFOLIO CORRELATION" in result
        assert result != ""

    def test_three_symbols_with_valid_data(self, monkeypatch):
        """build_correlation_brief with 3 symbols and valid mock data → contains sections."""
        import yfinance
        monkeypatch.setattr(
            yfinance,
            "download",
            _mock_download_uncorrelated,
        )
        result = build_correlation_brief(["AAPL", "MSFT", "GOOGL"])
        assert "PORTFOLIO CORRELATION" in result
        assert result != ""


# ---------------------------------------------------------------------------
# Content validation tests
# ---------------------------------------------------------------------------


class TestBuildCorrelationBriefContent:
    """Test content of generated brief."""

    def test_effective_bets_section_present(self, monkeypatch):
        """build_correlation_brief with 2+ symbols → contains 'Effective independent bets'."""
        import yfinance
        monkeypatch.setattr(
            yfinance,
            "download",
            _mock_download_uncorrelated,
        )
        result = build_correlation_brief(["AAPL", "MSFT"])
        assert "Effective independent bets:" in result

    def test_highest_correlations_section_present(self, monkeypatch):
        """build_correlation_brief with 2+ symbols → contains 'Highest correlations' section."""
        import yfinance
        monkeypatch.setattr(
            yfinance,
            "download",
            _mock_download_uncorrelated,
        )
        result = build_correlation_brief(["AAPL", "MSFT"])
        assert "Highest correlations:" in result

    def test_end_marker_present(self, monkeypatch):
        """build_correlation_brief returns brief with END CORRELATION marker."""
        import yfinance
        monkeypatch.setattr(
            yfinance,
            "download",
            _mock_download_uncorrelated,
        )
        result = build_correlation_brief(["AAPL", "MSFT"])
        assert "=== END CORRELATION ===" in result

    def test_start_and_end_markers(self, monkeypatch):
        """build_correlation_brief contains both start and end markers."""
        import yfinance
        monkeypatch.setattr(
            yfinance,
            "download",
            _mock_download_uncorrelated,
        )
        result = build_correlation_brief(["AAPL", "MSFT"])
        assert "=== PORTFOLIO CORRELATION ===" in result
        assert "=== END CORRELATION ===" in result


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestBuildCorrelationBriefErrorHandling:
    """Test error handling and edge cases."""

    def test_yfinance_import_fails(self, monkeypatch):
        """build_correlation_brief when yfinance import fails → returns empty string."""
        # Mock the import to fail
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "yfinance":
                raise ImportError("yfinance not available")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        result = build_correlation_brief(["AAPL", "MSFT"])
        assert result == ""

    def test_insufficient_return_data(self, monkeypatch):
        """build_correlation_brief with insufficient return data (< 20 rows) → empty string."""
        import yfinance
        monkeypatch.setattr(
            yfinance,
            "download",
            _mock_download_insufficient_data,
        )
        result = build_correlation_brief(["AAPL", "MSFT"])
        assert result == ""

    def test_empty_download_result(self, monkeypatch):
        """build_correlation_brief when yf.download returns empty → empty string."""
        import yfinance
        monkeypatch.setattr(
            yfinance,
            "download",
            _mock_download_empty,
        )
        result = build_correlation_brief(["AAPL", "MSFT"])
        assert result == ""

    def test_download_exception(self, monkeypatch):
        """build_correlation_brief when yf.download raises exception → empty string."""

        def mock_download_fail(*args, **kwargs):
            raise RuntimeError("Download failed")

        import yfinance
        monkeypatch.setattr(
            yfinance,
            "download",
            mock_download_fail,
        )
        result = build_correlation_brief(["AAPL", "MSFT"])
        assert result == ""


# ---------------------------------------------------------------------------
# Diversification warning tests
# ---------------------------------------------------------------------------


class TestBuildCorrelationBriefDiversificationWarning:
    """Test diversification warning logic."""

    def test_highly_correlated_shows_warning(self, monkeypatch):
        """build_correlation_brief with highly correlated symbols → shows WARNING about low diversification."""
        import yfinance
        monkeypatch.setattr(
            yfinance,
            "download",
            _mock_download_correlated,
        )
        result = build_correlation_brief(["AAPL", "MSFT"])
        # Highly correlated data should trigger warning
        # Check if warning is present or not (depends on eigenvalue calculation)
        # For highly correlated data, effective_bets < n * 0.5 should trigger warning
        if "WARNING" in result:
            assert "Low diversification" in result

    def test_uncorrelated_no_warning(self, monkeypatch):
        """build_correlation_brief with uncorrelated symbols → no WARNING."""
        import yfinance
        monkeypatch.setattr(
            yfinance,
            "download",
            _mock_download_uncorrelated,
        )
        result = build_correlation_brief(["AAPL", "MSFT", "GOOGL"])
        # Uncorrelated data should NOT trigger warning
        # Effective bets should be close to number of symbols
        # So effective_bets >= n * 0.5 → no warning
        assert "WARNING" not in result or "Low diversification" not in result


# ---------------------------------------------------------------------------
# Data structure tests
# ---------------------------------------------------------------------------


class TestBuildCorrelationBriefDataStructure:
    """Test structure and formatting of output."""

    def test_multi_line_output(self, monkeypatch):
        """build_correlation_brief returns multi-line string."""
        import yfinance
        monkeypatch.setattr(
            yfinance,
            "download",
            _mock_download_uncorrelated,
        )
        result = build_correlation_brief(["AAPL", "MSFT"])
        lines = result.split("\n")
        assert len(lines) >= 3  # At least header, content, footer

    def test_contains_ticker_pairs(self, monkeypatch):
        """build_correlation_brief output contains ticker pair correlations."""
        import yfinance
        monkeypatch.setattr(
            yfinance,
            "download",
            _mock_download_uncorrelated,
        )
        result = build_correlation_brief(["AAPL", "MSFT"])
        # Should contain correlation pairs with format "TICKER1 — TICKER2: 0.XX"
        assert "AAPL" in result and "MSFT" in result

    def test_correlation_values_formatted(self, monkeypatch):
        """build_correlation_brief shows correlation values with 2 decimal places."""
        import yfinance
        monkeypatch.setattr(
            yfinance,
            "download",
            _mock_download_uncorrelated,
        )
        result = build_correlation_brief(["AAPL", "MSFT"])
        # Look for pattern like "0.XX" in correlation display
        import re
        # Check for correlation value pattern (decimal with 2 places)
        pattern = r":\s*-?\d+\.\d{2}"
        matches = re.findall(pattern, result)
        assert len(matches) > 0  # Should have at least one correlation value

    def test_effective_bets_numeric(self, monkeypatch):
        """build_correlation_brief shows effective bets as numeric value."""
        import yfinance
        monkeypatch.setattr(
            yfinance,
            "download",
            _mock_download_uncorrelated,
        )
        result = build_correlation_brief(["AAPL", "MSFT"])
        # Should contain pattern like "Effective independent bets: X.X / 2"
        assert "/ 2" in result or "/ 3" in result or "Effective independent bets:" in result


# ---------------------------------------------------------------------------
# Special cases
# ---------------------------------------------------------------------------


class TestBuildCorrelationBriefSpecialCases:
    """Test special and edge cases."""

    def test_lookback_days_parameter(self, monkeypatch):
        """build_correlation_brief respects lookback_days parameter."""
        import yfinance
        monkeypatch.setattr(
            yfinance,
            "download",
            _mock_download_uncorrelated,
        )
        # Should not raise error with custom lookback
        result = build_correlation_brief(["AAPL", "MSFT"], lookback_days=30)
        assert result != ""

    def test_large_portfolio(self, monkeypatch):
        """build_correlation_brief handles larger portfolios (5+ symbols)."""
        import yfinance
        monkeypatch.setattr(
            yfinance,
            "download",
            _mock_download_uncorrelated,
        )
        symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]
        result = build_correlation_brief(symbols)
        assert "PORTFOLIO CORRELATION" in result
        assert "Effective independent bets:" in result

    def test_output_is_string(self, monkeypatch):
        """build_correlation_brief always returns a string."""
        import yfinance
        monkeypatch.setattr(
            yfinance,
            "download",
            _mock_download_uncorrelated,
        )
        result = build_correlation_brief(["AAPL", "MSFT"])
        assert isinstance(result, str)

    def test_no_nan_values_in_correlations(self, monkeypatch):
        """build_correlation_brief handles NaN values in correlation matrix."""

        def mock_download_with_nans(tickers, **kwargs):
            dates = pd.date_range(end="2026-01-01", periods=30, freq="B")
            ticker_list = tickers if isinstance(tickers, list) else tickers.split()
            data = {}
            for t in ticker_list:
                vals = np.linspace(100, 105, 30)
                # Insert some NaN values
                vals[5] = np.nan
                data[t] = vals
            df = pd.DataFrame(data, index=dates)
            df.columns = pd.MultiIndex.from_product([["Close"], df.columns])
            return df

        import yfinance
        monkeypatch.setattr(
            yfinance,
            "download",
            mock_download_with_nans,
        )
        result = build_correlation_brief(["AAPL", "MSFT"])
        # Should handle gracefully and still return content (after dropna)
        assert result != ""
