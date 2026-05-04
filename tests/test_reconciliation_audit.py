"""Tests for ReconciliationDaemon._write_audit_line (S-052)."""

import json
import uuid
import logging
from pathlib import Path

import pytest

from tradingagents.graph.reconciliation_daemon import ReconciliationDaemon


def _make_daemon(tmp_path, mode="alpaca-paper"):
    """Build a ReconciliationDaemon whose file paths all land under tmp_path."""
    cfg = {
        "live_execution_outbox_path": str(tmp_path / "outbox.json"),
        "live_positions_shadow_path": str(tmp_path / "positions_shadow.json"),
        "live_execution_fills_path": str(tmp_path / "fills.json"),
        "live_execution_closed_trades_path": str(tmp_path / "closed_trades.json"),
        "live_broker_orders_snapshot_path": str(tmp_path / "broker_orders_latest.json"),
        "live_broker_positions_snapshot_path": str(tmp_path / "broker_positions_latest.json"),
        "operator_gateway_allocator_regime_override_path": str(tmp_path / "regime.json"),
    }
    return ReconciliationDaemon(config=cfg, mode=mode)


def _audit_file(tmp_path: Path) -> Path:
    """Return path where _write_audit_line will write (relative to CWD)."""
    return tmp_path / "eval_results" / "live_execution" / "reconciliation_audit.jsonl"


# ---------------------------------------------------------------------------
# Test: file is created on first write
# ---------------------------------------------------------------------------

def test_write_audit_line_creates_file(tmp_path, monkeypatch):
    """_write_audit_line must create the JSONL file when it doesn't yet exist."""
    monkeypatch.chdir(tmp_path)

    daemon = _make_daemon(tmp_path)
    daemon._write_audit_line({"ok": True, "matched_orders": 1, "fills_applied": 0,
                               "status_updates": 0, "closed_positions": 0})

    audit_file = _audit_file(tmp_path)
    assert audit_file.exists(), "audit JSONL file should be created"


# ---------------------------------------------------------------------------
# Test: successive calls append, not overwrite
# ---------------------------------------------------------------------------

def test_write_audit_line_appends(tmp_path, monkeypatch):
    """Two successive calls must produce two distinct JSONL lines."""
    monkeypatch.chdir(tmp_path)

    daemon = _make_daemon(tmp_path)
    result = {"ok": True, "matched_orders": 2, "fills_applied": 1,
               "status_updates": 0, "closed_positions": 0}
    daemon._write_audit_line(result)
    daemon._write_audit_line(result)

    audit_file = _audit_file(tmp_path)
    lines = [ln for ln in audit_file.read_text().splitlines() if ln.strip()]
    assert len(lines) == 2, f"Expected 2 JSONL lines, got {len(lines)}"

    # Both must be valid JSON
    for line in lines:
        parsed = json.loads(line)
        assert isinstance(parsed, dict)


# ---------------------------------------------------------------------------
# Test: JSON line format contains required keys
# ---------------------------------------------------------------------------

def test_write_audit_line_required_keys(tmp_path, monkeypatch):
    """Each audit record must contain the required top-level keys."""
    monkeypatch.chdir(tmp_path)

    daemon = _make_daemon(tmp_path, mode="alpaca-paper")
    cycle_result = {
        "ok": True,
        "matched_orders": 3,
        "fills_applied": 2,
        "status_updates": 1,
        "closed_positions": 0,
    }
    daemon._write_audit_line(cycle_result)

    audit_file = _audit_file(tmp_path)
    record = json.loads(audit_file.read_text().strip())

    required_keys = {"timestamp", "cycle_id", "mode", "ok", "matched_orders",
                     "fills_applied", "status_updates", "closed_positions"}
    missing = required_keys - record.keys()
    assert not missing, f"Missing keys in audit record: {missing}"

    assert record["mode"] == "alpaca-paper"
    assert record["ok"] is True
    assert record["matched_orders"] == 3
    assert record["fills_applied"] == 2
    # cycle_id must be a valid UUID
    uuid.UUID(record["cycle_id"])  # raises ValueError if not valid


# ---------------------------------------------------------------------------
# Test: error scenarios are captured when ok=False
# ---------------------------------------------------------------------------

def test_write_audit_line_captures_error(tmp_path, monkeypatch):
    """When ok=False, the error field must appear in the audit record."""
    monkeypatch.chdir(tmp_path)

    daemon = _make_daemon(tmp_path)
    cycle_result = {
        "ok": False,
        "error": "broker_orders_fetch_failed: connection refused",
        "mode": "alpaca-paper",
    }
    daemon._write_audit_line(cycle_result)

    audit_file = _audit_file(tmp_path)
    record = json.loads(audit_file.read_text().strip())

    assert record["ok"] is False
    assert "error" in record
    assert "broker_orders_fetch_failed" in record["error"]


# ---------------------------------------------------------------------------
# Test: exit_check summary is included when present
# ---------------------------------------------------------------------------

def test_write_audit_line_includes_exit_check(tmp_path, monkeypatch):
    """exit_signals and exit_orders_submitted must appear when exit_check is present."""
    monkeypatch.chdir(tmp_path)

    daemon = _make_daemon(tmp_path)
    cycle_result = {
        "ok": True,
        "matched_orders": 0,
        "fills_applied": 0,
        "status_updates": 0,
        "closed_positions": 0,
        "exit_check": {
            "ok": True,
            "signals_generated": 2,
            "orders_submitted": 1,
            "failed_orders": 0,
        },
    }
    daemon._write_audit_line(cycle_result)

    audit_file = _audit_file(tmp_path)
    record = json.loads(audit_file.read_text().strip())

    assert record["exit_signals"] == 2
    assert record["exit_orders_submitted"] == 1


# ---------------------------------------------------------------------------
# Test: positions file enrichment (positions_count + estimated_nlv)
# ---------------------------------------------------------------------------

def test_write_audit_line_enriches_from_positions_file(tmp_path, monkeypatch):
    """When positions_shadow.json exists, positions_count and estimated_nlv are written."""
    monkeypatch.chdir(tmp_path)

    # Write a positions shadow file with two positions
    positions_data = {
        "AAPL": {"net_quantity": 10, "last_mark_price": 200.0},
        "MSFT": {"net_quantity": 5, "last_mark_price": 400.0},
    }
    positions_file = tmp_path / "positions_shadow.json"
    positions_file.write_text(json.dumps(positions_data))

    daemon = _make_daemon(tmp_path)
    daemon._write_audit_line({"ok": True, "matched_orders": 0, "fills_applied": 0,
                               "status_updates": 0, "closed_positions": 0})

    audit_file = _audit_file(tmp_path)
    record = json.loads(audit_file.read_text().strip())

    assert record["positions_count"] == 2
    # AAPL: 10 * 200 = 2000, MSFT: 5 * 400 = 2000 → total 4000
    assert record["estimated_nlv"] == pytest.approx(4000.0)


# ---------------------------------------------------------------------------
# Test: write failure is silent (best-effort)
# ---------------------------------------------------------------------------

def test_write_audit_line_is_resilient_to_write_failure(tmp_path, monkeypatch, caplog):
    """If the file write fails, _write_audit_line must not raise — only warn."""
    monkeypatch.chdir(tmp_path)

    # Pre-create the audit dir, then place a directory at the file path so open() fails
    audit_file = _audit_file(tmp_path)
    audit_file.parent.mkdir(parents=True, exist_ok=True)
    audit_file.mkdir()  # make it a directory — open("a") will fail with IsADirectoryError

    daemon = _make_daemon(tmp_path)
    with caplog.at_level(logging.WARNING, logger="tradingagents.graph.reconciliation_daemon"):
        # Must not raise
        daemon._write_audit_line({"ok": True, "matched_orders": 0, "fills_applied": 0,
                                   "status_updates": 0, "closed_positions": 0})

    assert any("Failed to write reconciliation audit line" in r.message for r in caplog.records)
