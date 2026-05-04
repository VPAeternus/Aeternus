"""Comprehensive tests for TradeMemory class."""

import json
from pathlib import Path
import time

import pytest

from tradingagents.agents.utils.memory import TradeMemory


def _make_record(
    ticker="AAPL",
    status="CLOSED",
    date="2026-02-20",
    aeternus_score=75,
    rating="Buy",
    price_at_rating=150.0,
    close_price=155.0,
    sector="Technology",
):
    """Factory helper: create a trade record."""
    return {
        "ticker": ticker,
        "status": status,
        "date": date,
        "aeternus_score": aeternus_score,
        "rating": rating,
        "price_at_rating": price_at_rating,
        "close_price": close_price,
        "sector": sector,
    }


class TestTradeMemoryLoad:
    """Tests for _load() and file handling."""

    def test_empty_file_does_not_exist(self, tmp_path):
        """When no file exists, _load() returns empty list."""
        track_file = tmp_path / "track_record.json"
        memory = TradeMemory(str(track_file))
        result = memory._load()
        assert result == []

    def test_empty_json_array(self, tmp_path):
        """When file has [], _load() returns empty list."""
        track_file = tmp_path / "track_record.json"
        track_file.write_text("[]")
        memory = TradeMemory(str(track_file))
        result = memory._load()
        assert result == []

    def test_corrupt_json_returns_empty(self, tmp_path):
        """When file has malformed JSON, _load() returns empty list."""
        track_file = tmp_path / "track_record.json"
        track_file.write_text("{invalid json")
        memory = TradeMemory(str(track_file))
        result = memory._load()
        assert result == []

    def test_file_mtime_cache_hits(self, tmp_path):
        """Second _load() with same mtime uses cache."""
        track_file = tmp_path / "track_record.json"
        records = [_make_record(ticker="AAPL")]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        first_load = memory._load()

        # Manually modify internal state to verify cache is used
        memory._cache[0]["ticker"] = "MODIFIED"

        # Load again without changing file
        second_load = memory._load()

        # Should get the cached (modified) version, not re-read from file
        assert second_load[0]["ticker"] == "MODIFIED"

    def test_file_mtime_cache_invalidates(self, tmp_path):
        """When file mtime changes, cache is invalidated."""
        track_file = tmp_path / "track_record.json"
        records_v1 = [_make_record(ticker="AAPL")]
        track_file.write_text(json.dumps(records_v1))

        memory = TradeMemory(str(track_file))
        first_load = memory._load()
        assert first_load[0]["ticker"] == "AAPL"

        # Modify file (force mtime change with small sleep)
        time.sleep(0.01)
        records_v2 = [_make_record(ticker="GOOG")]
        track_file.write_text(json.dumps(records_v2))

        # Load again; should re-read because mtime changed
        second_load = memory._load()
        assert second_load[0]["ticker"] == "GOOG"


class TestTradeMemoryGetLessons:
    """Tests for get_lessons() output and filtering logic."""

    def test_no_matching_ticker_returns_empty(self, tmp_path):
        """When records exist but not for queried ticker, returns empty string."""
        track_file = tmp_path / "track_record.json"
        records = [_make_record(ticker="AAPL")]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="GOOG")
        assert result == ""

    def test_empty_track_record_returns_empty(self, tmp_path):
        """When track_record is empty, get_lessons() returns empty string."""
        track_file = tmp_path / "track_record.json"
        track_file.write_text("[]")

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL")
        assert result == ""

    def test_same_ticker_closed_included(self, tmp_path):
        """Closed record for same ticker is included in output."""
        track_file = tmp_path / "track_record.json"
        records = [_make_record(ticker="AAPL", status="CLOSED")]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL")

        assert result != ""
        assert "AAPL" in result
        assert "CLOSED" not in result  # status label not shown in output

    def test_same_ticker_open_included(self, tmp_path):
        """Open record for same ticker is included with [OPEN] label."""
        track_file = tmp_path / "track_record.json"
        records = [_make_record(ticker="AAPL", status="OPEN")]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL")

        assert "[OPEN]" in result

    def test_sector_match_different_ticker(self, tmp_path):
        """Different ticker, same sector is included (lower priority)."""
        track_file = tmp_path / "track_record.json"
        records = [
            _make_record(ticker="AAPL", status="CLOSED", sector="Technology"),
        ]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="MSFT", sector="Technology")

        assert "AAPL" in result
        assert "Technology" in result

    def test_sector_match_only_closed_records(self, tmp_path):
        """Sector matching only uses CLOSED records (not OPEN)."""
        track_file = tmp_path / "track_record.json"
        records = [
            _make_record(ticker="AAPL", status="OPEN", sector="Technology"),
        ]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="MSFT", sector="Technology")

        # OPEN records should not match by sector
        assert result == ""

    def test_priority_ordering_same_ticker_closed_first(self, tmp_path):
        """Priority: same ticker closed, then same ticker open, then sector."""
        track_file = tmp_path / "track_record.json"
        records = [
            _make_record(ticker="MSFT", status="CLOSED", sector="Technology"),  # sector match
            _make_record(ticker="AAPL", status="OPEN"),  # same ticker open
            _make_record(ticker="AAPL", status="CLOSED"),  # same ticker closed (highest priority)
        ]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL", sector="Technology")

        # Extract lines to check order
        lines = result.split("\n")
        # First AAPL line should be the closed one (highest priority)
        aapl_lines = [l for l in lines if "AAPL" in l and l.strip().startswith("-")]
        assert len(aapl_lines) >= 2
        # Closed record appears before OPEN record
        assert "[OPEN]" not in aapl_lines[0]
        assert "[OPEN]" in aapl_lines[1]

    def test_cap_at_n_records(self, tmp_path):
        """More records than n parameter returns only n records."""
        track_file = tmp_path / "track_record.json"
        records = [
            _make_record(ticker="AAPL", date="2026-02-20"),
            _make_record(ticker="AAPL", date="2026-02-19"),
            _make_record(ticker="AAPL", date="2026-02-18"),
            _make_record(ticker="AAPL", date="2026-02-17"),
            _make_record(ticker="AAPL", date="2026-02-16"),
            _make_record(ticker="AAPL", date="2026-02-15"),
        ]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL", n=3)

        # Count AAPL lines
        aapl_lines = [l for l in result.split("\n") if "AAPL" in l and l.strip().startswith("-")]
        assert len(aapl_lines) == 3


class TestTradeMemoryFormat:
    """Tests for _format() output structure and labels."""

    def test_format_header_footer(self, tmp_path):
        """Output starts with header and ends with footer."""
        track_file = tmp_path / "track_record.json"
        records = [_make_record(ticker="AAPL")]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL")

        assert result.startswith("--- PAST TRADE OUTCOMES")
        assert result.endswith("---")

    def test_correct_label_buy_positive_pnl(self, tmp_path):
        """Buy with positive PnL shows [CORRECT]."""
        track_file = tmp_path / "track_record.json"
        records = [
            _make_record(
                ticker="AAPL",
                status="CLOSED",
                rating="Buy",
                price_at_rating=100.0,
                close_price=110.0,
            )
        ]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL")

        assert "[CORRECT]" in result

    def test_wrong_label_buy_negative_pnl(self, tmp_path):
        """Buy with negative PnL shows [WRONG]."""
        track_file = tmp_path / "track_record.json"
        records = [
            _make_record(
                ticker="AAPL",
                status="CLOSED",
                rating="Buy",
                price_at_rating=100.0,
                close_price=90.0,
            )
        ]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL")

        assert "[WRONG]" in result

    def test_correct_label_sell_negative_pnl(self, tmp_path):
        """Sell with negative PnL (short profit) shows [CORRECT]."""
        track_file = tmp_path / "track_record.json"
        records = [
            _make_record(
                ticker="AAPL",
                status="CLOSED",
                rating="Sell",
                price_at_rating=100.0,
                close_price=90.0,
            )
        ]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL")

        assert "[CORRECT]" in result

    def test_wrong_label_sell_positive_pnl(self, tmp_path):
        """Sell with positive PnL (short loss) shows [WRONG]."""
        track_file = tmp_path / "track_record.json"
        records = [
            _make_record(
                ticker="AAPL",
                status="CLOSED",
                rating="Sell",
                price_at_rating=100.0,
                close_price=110.0,
            )
        ]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL")

        assert "[WRONG]" in result

    def test_pnl_percentage_formatting(self, tmp_path):
        """PnL percentage is formatted with sign and 1 decimal place."""
        track_file = tmp_path / "track_record.json"
        records = [
            _make_record(
                ticker="AAPL",
                status="CLOSED",
                rating="Buy",
                price_at_rating=100.0,
                close_price=115.5,
            )
        ]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL")

        # Positive: +15.5%
        assert "+15.5%" in result

    def test_negative_pnl_formatting(self, tmp_path):
        """Negative PnL shown without + sign."""
        track_file = tmp_path / "track_record.json"
        records = [
            _make_record(
                ticker="AAPL",
                status="CLOSED",
                rating="Buy",
                price_at_rating=100.0,
                close_price=85.0,
            )
        ]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL")

        # Negative: -15.0%
        assert "-15.0%" in result

    def test_sector_label_for_different_ticker(self, tmp_path):
        """Different ticker shows sector label; same ticker doesn't."""
        track_file = tmp_path / "track_record.json"
        records = [
            _make_record(
                ticker="MSFT",
                status="CLOSED",
                sector="Technology",
                price_at_rating=100.0,
                close_price=105.0,
            ),
        ]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL", sector="Technology")

        # Different ticker should show sector
        assert "(Technology)" in result

    def test_no_sector_label_for_same_ticker(self, tmp_path):
        """Same ticker should not show sector label."""
        track_file = tmp_path / "track_record.json"
        records = [
            _make_record(
                ticker="AAPL",
                status="CLOSED",
                sector="Technology",
                price_at_rating=100.0,
                close_price=105.0,
            ),
        ]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL")

        # Check AAPL line doesn't have sector label
        aapl_line = [l for l in result.split("\n") if "AAPL" in l and l.strip().startswith("-")][0]
        assert "(Technology)" not in aapl_line

    def test_price_display_format(self, tmp_path):
        """Price at rating shown as $XXX.XX."""
        track_file = tmp_path / "track_record.json"
        records = [
            _make_record(
                ticker="AAPL",
                status="CLOSED",
                price_at_rating=150.5,
                close_price=155.0,
            )
        ]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL")

        assert "at $150.50" in result

    def test_missing_price_at_rating_no_price_str(self, tmp_path):
        """When price_at_rating is missing, no price string shown."""
        track_file = tmp_path / "track_record.json"
        record = _make_record(ticker="AAPL", status="CLOSED")
        del record["price_at_rating"]
        track_file.write_text(json.dumps([record]))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL")

        aapl_line = [l for l in result.split("\n") if "AAPL" in l and l.strip().startswith("-")][0]
        assert "at $" not in aapl_line

    def test_closed_no_pnl_when_missing_prices(self, tmp_path):
        """CLOSED record without prices doesn't show PnL/outcome."""
        track_file = tmp_path / "track_record.json"
        record = _make_record(ticker="AAPL", status="CLOSED")
        del record["price_at_rating"]
        track_file.write_text(json.dumps([record]))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL")

        aapl_line = [l for l in result.split("\n") if "AAPL" in l and l.strip().startswith("-")][0]
        assert "[CORRECT]" not in aapl_line
        assert "[WRONG]" not in aapl_line
        assert "%" not in aapl_line

    def test_open_status_label_shown(self, tmp_path):
        """OPEN status shows [OPEN] label instead of PnL."""
        track_file = tmp_path / "track_record.json"
        records = [
            _make_record(
                ticker="AAPL",
                status="OPEN",
                price_at_rating=100.0,
                close_price=None,
            )
        ]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL")

        assert "[OPEN]" in result
        # Should not have [CORRECT] or [WRONG]
        assert "[CORRECT]" not in result
        assert "[WRONG]" not in result

    def test_all_fields_in_output(self, tmp_path):
        """Output includes ticker, date, rating, score."""
        track_file = tmp_path / "track_record.json"
        records = [
            _make_record(
                ticker="AAPL",
                status="CLOSED",
                date="2026-02-20",
                aeternus_score=75,
                rating="Strong Buy",
                price_at_rating=150.0,
                close_price=160.0,
            )
        ]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL")

        assert "AAPL" in result
        assert "2026-02-20" in result
        assert "Strong Buy" in result
        assert "75/100" in result

    def test_footer_message_included(self, tmp_path):
        """Output includes lesson message."""
        track_file = tmp_path / "track_record.json"
        records = [_make_record(ticker="AAPL")]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL")

        assert "Learn from CORRECT decisions" in result
        assert "avoid repeating WRONG ones" in result


class TestTradeMemoryEdgeCases:
    """Tests for edge cases and robustness."""

    def test_missing_fields_handled_gracefully(self, tmp_path):
        """Records with missing fields don't crash; use defaults."""
        track_file = tmp_path / "track_record.json"
        record = {"ticker": "AAPL"}  # Minimal record
        track_file.write_text(json.dumps([record]))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL")

        # Should not crash and should have output
        assert result != ""
        assert "AAPL" in result

    def test_none_values_handled(self, tmp_path):
        """Records with None values don't crash."""
        track_file = tmp_path / "track_record.json"
        record = _make_record(
            ticker="AAPL",
            price_at_rating=None,
            close_price=None,
        )
        track_file.write_text(json.dumps([record]))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL")

        assert result != ""

    def test_sector_parameter_optional(self, tmp_path):
        """get_lessons() works without sector parameter."""
        track_file = tmp_path / "track_record.json"
        records = [_make_record(ticker="AAPL")]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL")  # No sector param

        assert result != ""

    def test_multiple_calls_same_instance(self, tmp_path):
        """Multiple get_lessons() calls on same instance work."""
        track_file = tmp_path / "track_record.json"
        records = [
            _make_record(ticker="AAPL"),
            _make_record(ticker="GOOG"),
        ]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        result1 = memory.get_lessons(ticker="AAPL")
        result2 = memory.get_lessons(ticker="GOOG")

        assert "AAPL" in result1
        assert "GOOG" in result2

    def test_zero_n_parameter(self, tmp_path):
        """n=0 returns empty string."""
        track_file = tmp_path / "track_record.json"
        records = [_make_record(ticker="AAPL")]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL", n=0)

        assert result == ""

    def test_large_pnl_percentage(self, tmp_path):
        """Large PnL percentages formatted correctly."""
        track_file = tmp_path / "track_record.json"
        records = [
            _make_record(
                ticker="AAPL",
                status="CLOSED",
                rating="Buy",
                price_at_rating=10.0,
                close_price=100.0,
            )
        ]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL")

        assert "+900.0%" in result

    def test_very_small_pnl_percentage(self, tmp_path):
        """Very small PnL percentages formatted correctly."""
        track_file = tmp_path / "track_record.json"
        records = [
            _make_record(
                ticker="AAPL",
                status="CLOSED",
                rating="Buy",
                price_at_rating=100.0,
                close_price=100.05,
            )
        ]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL")

        assert "+0.0%" in result  # Rounded to 1 decimal

    def test_exact_zero_pnl(self, tmp_path):
        """Zero PnL shown as 0.0% (no + prefix) and marked [WRONG]."""
        track_file = tmp_path / "track_record.json"
        records = [
            _make_record(
                ticker="AAPL",
                status="CLOSED",
                rating="Buy",
                price_at_rating=100.0,
                close_price=100.0,
            )
        ]
        track_file.write_text(json.dumps(records))

        memory = TradeMemory(str(track_file))
        result = memory.get_lessons(ticker="AAPL")

        # Zero PnL: no + prefix, marked as WRONG (neither positive nor negative)
        assert "(0.0%)" in result
        assert "[WRONG]" in result
