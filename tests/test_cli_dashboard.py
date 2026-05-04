from typer.testing import CliRunner
from cli.main import app
from tradingagents.graph.track_record import TrackRecord
from tradingagents.graph.audit import RatingAuditLog
import uuid
import json
import shutil
from pathlib import Path
import pytest

runner = CliRunner()

@pytest.fixture
def mock_data():
    """Setup mock data for testing."""
    # Use a separate test directory if possible, or just rely on the fact that we append
    # In a real scenario, we should mock the file paths
    tr = TrackRecord()
    rating_id = str(uuid.uuid4())
    rating = {
        "rating_id": rating_id,
        "ticker": "TEST_TICKER",
        "aeternus_score": 88.8,
        "rating": "Buy",
        "status": "OPEN",
        "date": "2024-01-01",
        "price_at_rating": 100.0,
        "price_target": 120.0
    }
    tr.append(rating)
    
    audit = RatingAuditLog()
    audit.log_event("RATING_CREATED", rating_id, rating)
    
    return rating_id

def test_track_record_command(mock_data):
    result = runner.invoke(app, ["track-record"])
    assert result.exit_code == 0
    assert "Video recording started" not in result.stdout # Should not be there
    assert "TEST_TICKER" in result.stdout
    assert "Buy" in result.stdout

def test_performance_command():
    result = runner.invoke(app, ["performance"])
    assert result.exit_code == 0
    assert "Performance Metrics" in result.stdout
    assert "Win Rate" in result.stdout


def test_performance_command_renders_dynamic_v3_benchmark(monkeypatch):
    monkeypatch.setattr(
        "cli.commands.performance.TrackRecord.compute_v3_benchmark",
        lambda self: {
            "ticker": "SPY",
            "date_start": "2025-01-01",
            "date_end": "2025-03-31",
            "period_days": 60,
            "v3_total_return_pct": 12.5,
            "bh_total_return_pct": 7.0,
            "v3_cagr_pct": 58.3,
            "bh_cagr_pct": 30.7,
        },
    )

    result = runner.invoke(app, ["performance"])

    assert result.exit_code == 0
    assert "V3 SPY Benchmark" in result.stdout
    assert "Track-Record Window" in result.stdout
    assert "V3 Total Return" in result.stdout
    assert "Buy & Hold Return" in result.stdout

def test_rating_history_command(mock_data):
    rating_id = mock_data
    result = runner.invoke(app, ["rating-history", rating_id])
    assert result.exit_code == 0
    assert "Audit History" in result.stdout
    assert rating_id in result.stdout
    assert "RATING_CREATED" in result.stdout

def test_rating_history_not_found():
    result = runner.invoke(app, ["rating-history", "non-existent-uuid"])
    assert result.exit_code == 0
    assert "No history found" in result.stdout
