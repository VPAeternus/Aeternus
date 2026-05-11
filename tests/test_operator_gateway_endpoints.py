import datetime as dt
import json
import sys
import types
from pathlib import Path

# Stub chromadb for Python 3.14 compatibility (pydantic v1 incompatibility)
if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub

from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from tradingagents.capital_allocator.contracts import (
    AllocationIntent,
    AssetClassId,
    ExecutionMode,
    FundingSourceStatus,
    IntentStatus,
    Lane,
    ValuationMethodology,
)
from tradingagents.capital_allocator.repository import SQLiteAllocatorRepository
from tradingagents.dealflow.control_io import write_json_locked
from tradingagents.operator_gateway.app import create_app


def _config(tmp_path: Path) -> dict:
    return {
        "operator_gateway_heartbeat_path": str(tmp_path / "control" / "engine_heartbeat.json"),
        "operator_gateway_system_halt_path": str(tmp_path / "control" / "system_halt.json"),
        "operator_gateway_triage_intents_path": str(tmp_path / "deal_flow" / "ui" / "triage_intents.json"),
        "operator_gateway_triage_receipts_path": str(tmp_path / "deal_flow" / "ui" / "triage_receipts.json"),
        "operator_gateway_negative_constraints_path": str(tmp_path / "deal_flow" / "ui" / "negative_constraints.json"),
        "operator_gateway_allocator_db_path": str(tmp_path / "control" / "capital_allocator.db"),
        "operator_gateway_allocator_regime_override_path": str(
            tmp_path / "control" / "allocator_regime_override.json"
        ),
        "operator_gateway_dealflow_base_dir": str(tmp_path / "deal_flow"),
        "results_dir": str(tmp_path / "results"),
        "operator_gateway_heartbeat_ttl_seconds": 25.0,
        "operator_gateway_clock_offset_max_seconds": 5.0,
        "operator_gateway_intent_maturity_seconds": 5.0,
        "operator_gateway_ingress_guard_seconds": 2.0,
        "operator_gateway_price_slip_max_bps": 150.0,
        "operator_gateway_price_latency_max_ms": 2000.0,
        "operator_gateway_negative_constraint_ttl_days": 14,
        "operator_gateway_bootstrap_since_minutes": 60,
        "operator_gateway_bootstrap_top_candidates": 5,
        "operator_gateway_mirror_challenge_ttl_seconds": 300.0,
        "operator_gateway_require_legal_consent": True,
        "operator_gateway_legal_version": "2026-02-08.v1",
        "operator_gateway_broker_adapter": "mock",
        "operator_gateway_model_allocation_path": str(tmp_path / "control" / "model_allocation.json"),
        "operator_gateway_broker_allocation_path": str(tmp_path / "control" / "broker_allocation.json"),
        "operator_gateway_drift_aligned_threshold_pct": 5.0,
        "operator_gateway_drift_disconnected_threshold_pct": 15.0,
        "operator_gateway_portfolio_sync_stale_seconds": 1200.0,
        "operator_gateway_drift_settings_path": str(tmp_path / "control" / "drift_sensitivity.json"),
        "operator_gateway_drift_snapshot_path": str(tmp_path / "control" / "drift_snapshot.json"),
        "operator_gateway_drift_background_enabled": False,
        "operator_gateway_drift_background_interval_seconds": 30.0,
    }


def _seed_allocator_intent(
    config: dict,
    *,
    intent_id: str,
    status: IntentStatus,
    funding_source_status: FundingSourceStatus = FundingSourceStatus.SETTLED_CASH,
    funding_available_at_utc: dt.datetime | None = None,
):
    repo = SQLiteAllocatorRepository(config["operator_gateway_allocator_db_path"])
    repo.initialize()
    now = dt.datetime.now(dt.timezone.utc)
    repo.insert_intent(
        AllocationIntent(
            intent_id=intent_id,
            run_id="run-alloc-1",
            lane=Lane.CORE,
            symbol="AAPL",
            asset_id="AAPL",
            asset_class_id=AssetClassId.LISTED_EQUITY,
            valuation_methodology=ValuationMethodology.MARK_TO_MARKET,
            execution_mode=ExecutionMode.LIVE,
            side="BUY",
            target_notional_usd=5000.0,
            correlation_group_tag="MEGA_CAP",
            funding_source_status=funding_source_status,
            funding_available_at_utc=funding_available_at_utc,
            funding_reservation_id=f"reserve-{intent_id}",
            snapshot_id="snap-gateway",
            snapshot_hash_canonical="h1",
            snapshot_hash_raw="h2",
            max_slippage_bps=150.0,
            created_at_utc=now,
            expires_at_utc=now + dt.timedelta(hours=2),
            status=status,
            idempotency_key=f"idem-{intent_id}",
        )
    )


def _write_scout_handoff(tmp_path: Path, payload: dict):
    path = tmp_path / "deal_flow" / "latest_final_dealflow_tickers.json"
    if "tickers" in payload:
        handoff = payload
    else:
        items = payload.get("items", []) if isinstance(payload.get("items"), list) else []
        tickers = [str(item.get("symbol") or item.get("ticker") or "").upper() for item in items]
        tickers = [symbol for symbol in tickers if symbol]
        handoff = {
            "run_id": payload.get("run_id", ""),
            "date": payload.get("date", ""),
            "tickers": tickers,
            "metadata_by_ticker": {
                symbol: {
                    "scouts": item.get("scouts") or ["test_scout"],
                    "mention_count": item.get("mention_count", 1),
                }
                for symbol, item in zip(tickers, items)
            },
        }
    write_json_locked(path, handoff)
    return path


def _write_analysis_report(tmp_path: Path, symbol: str, date: str, payload: dict):
    path = tmp_path / "results" / symbol / date / "analysis_report.json"
    write_json_locked(path, payload)
    return path


def _seed_x_feed_ready(tmp_path: Path, as_of_date: str):
    raw_dir = tmp_path / "x_feed" / as_of_date / "raw"
    for pass_num in range(1, 17):
        write_json_locked(raw_dir / f"pass_{pass_num:02d}.json", {"trending": []})
    write_json_locked(tmp_path / "x_feed" / as_of_date / "merged.json", {"NVDA": {"ticker": "NVDA"}})


def _write_allocation(path: Path, *, as_of_utc: str, weights: dict):
    write_json_locked(
        path,
        {
            "as_of_utc": as_of_utc,
            "weights": weights,
        },
    )
    return path


def _write_heartbeat(config: dict, *, now: dt.datetime, engine_offset_s: float = 0.0, next_run_s: int = 120):
    payload = {
        "engine_time_utc": (now + dt.timedelta(seconds=engine_offset_s)).isoformat(),
        "run_state": "IDLE",
        "active_run_id": "",
        "active_run_started_at_utc": "",
        "next_run_at_utc_actual": (now + dt.timedelta(seconds=next_run_s)).isoformat(),
        "queue_run_id_target": "run-1",
        "heartbeat_seq": 1,
        "updated_at_utc": now.isoformat(),
    }
    write_json_locked(Path(config["operator_gateway_heartbeat_path"]), payload)


def test_schedule_unknown_when_heartbeat_missing(tmp_path: Path):
    config = _config(tmp_path)
    client = TestClient(create_app(config))
    response = client.get("/ops/schedule")
    assert response.status_code == 200
    payload = response.json()
    assert payload["schedule_status"] == "UNKNOWN"
    assert payload["commit_window_open"] is False


def test_schedule_unknown_when_clock_drift_exceeds_limit(tmp_path: Path):
    config = _config(tmp_path)
    now = dt.datetime.now(dt.timezone.utc)
    _write_heartbeat(config, now=now, engine_offset_s=7.0, next_run_s=180)
    client = TestClient(create_app(config))
    response = client.get("/ops/schedule")
    assert response.status_code == 200
    payload = response.json()
    assert payload["schedule_status"] == "UNKNOWN"


def test_triage_intent_rejected_when_commit_window_closed(tmp_path: Path):
    config = _config(tmp_path)
    now = dt.datetime.now(dt.timezone.utc)
    _write_heartbeat(config, now=now, engine_offset_s=0.0, next_run_s=6)
    client = TestClient(create_app(config))
    response = client.post(
        "/ops/triage-intent",
        json={
            "action": "APPROVE",
            "symbol": "TSLA",
            "queue_id": "q1",
            "target_queue_run_id": "run-1",
            "snapshot_id": "snap-1",
            "snapshot_hash_canonical": "h1",
            "snapshot_hash_raw": "h2",
            "snapshot_validity": "VALID",
            "snapshot_price": 100.0,
            "thesis_tags": ["momentum"],
        },
    )
    assert response.status_code == 409


def test_create_undo_and_bulk_status_roundtrip(tmp_path: Path):
    config = _config(tmp_path)
    now = dt.datetime.now(dt.timezone.utc)
    _write_heartbeat(config, now=now, engine_offset_s=0.0, next_run_s=240)
    client = TestClient(create_app(config))

    created = client.post(
        "/ops/triage-intent",
        json={
            "action": "DEFER",
            "symbol": "AAPL",
            "queue_id": "q2",
            "target_queue_run_id": "run-1",
            "snapshot_id": "snap-2",
            "snapshot_hash_canonical": "h3",
            "snapshot_hash_raw": "h4",
            "snapshot_validity": "VALID",
            "snapshot_price": 220.0,
            "thesis_tags": ["balanced"],
        },
    )
    assert created.status_code == 200
    payload = created.json()

    undone = client.post(
        "/ops/triage-intent/undo",
        json={
            "intent_id": payload["intent_id"],
            "last_known_record_hash": payload["record_hash"],
        },
    )
    assert undone.status_code == 200
    status = client.get("/ops/triage-intents/status?since_minutes=60")
    assert status.status_code == 200
    rows = status.json()["items"]
    assert rows
    row = rows[0]
    assert row["status"] == "CANCELED_BY_UNDO"
    assert row["latest_receipt"]["decision_status"] == "CANCELED_BY_UNDO"


def test_dealflow_read_endpoint_returns_snapshot_and_candidates(tmp_path: Path):
    config = _config(tmp_path)
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    queue_payload = {
        "run_id": f"{today}-070000-manual",
        "date": today,
        "items": [
            {
                "queue_id": f"{today}-070000-manual:NVDA",
                "symbol": "NVDA",
                "lane": "MOMENTUM",
                "why_now": "High-conviction breakout driven by strong trend and catalysts.",
                "risk_tags": ["Earnings approaching", "High IV"],
                "research_playbook": "MOMENTUM_BREAKOUT",
                "evidence": {
                    "active_families": 3,
                    "evidence_count": 260,
                    "freshness_hours": 12,
                },
            }
        ],
    }
    _write_scout_handoff(tmp_path, queue_payload)
    client = TestClient(create_app(config))
    response = client.get("/ops/dealflow")
    assert response.status_code == 200
    payload = response.json()
    assert payload["snapshot"]["validity"] == "VALID"
    assert payload["summary"]["total_candidates"] == 1
    assert payload["candidates"][0]["symbol"] == "NVDA"
    assert payload["candidates"][0]["snapshot_id"] == payload["snapshot"]["snapshot_id"]


def test_dealflow_limit_query_returns_truncated_candidate_list(tmp_path: Path):
    config = _config(tmp_path)
    queue_payload = {
        "run_id": "2026-02-08-070000-manual",
        "date": "2026-02-08",
        "items": [
            {
                "queue_id": "2026-02-08-070000-manual:NVDA",
                "symbol": "NVDA",
                "lane": "MOMENTUM",
                "why_now": "High-conviction breakout driven by strong trend and catalysts.",
                "research_playbook": "MOMENTUM_BREAKOUT",
            },
            {
                "queue_id": "2026-02-08-070000-manual:AAPL",
                "symbol": "AAPL",
                "lane": "CORE",
                "why_now": "Quality setup with stable trend.",
                "research_playbook": "QUALITY",
            },
        ],
    }
    _write_scout_handoff(tmp_path, queue_payload)
    client = TestClient(create_app(config))
    response = client.get("/ops/dealflow?limit=1")
    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["total_candidates"] == 2
    assert len(payload["candidates"]) == 1


def test_candidate_detail_fail_soft_on_missing_columns(tmp_path: Path):
    config = _config(tmp_path)
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    queue_payload = {
        "run_id": f"{today}-080000-manual",
        "date": today,
        "items": [
            {
                "queue_id": f"{today}-080000-manual:TSLA",
                "symbol": "TSLA",
                # intentionally missing lane/score/evidence fields
                "why_now": "",
            }
        ],
    }
    _write_scout_handoff(tmp_path, queue_payload)
    _write_analysis_report(
        tmp_path,
        "TSLA",
        today,
        {
            "aeternus_score": {"rating": "Hold", "aeternus_score": 55, "confidence": 3},
            "trader_investment_plan": "FINAL TRANSACTION PROPOSAL: **HOLD**",
            "thesis_check": {"thesis_change": "NO"},
        },
    )
    client = TestClient(create_app(config))
    response = client.get("/ops/candidates/TSLA")
    assert response.status_code == 200
    payload = response.json()
    assert payload["snapshot"]["validity"] == "VALID"
    assert payload["candidate"]["symbol"] == "TSLA"
    assert payload["candidate"]["thesis_summary"] == "Scout handoff: test_scout"
    assert payload["analysis"]["recommendation"] == "HOLD"


def test_dealflow_snapshot_marked_stale_for_old_artifact_date(tmp_path: Path):
    config = _config(tmp_path)
    queue_payload = {
        "run_id": "2026-02-06-070000-manual",
        "date": "2026-02-06",
        "items": [],
    }
    _write_scout_handoff(tmp_path, queue_payload)
    client = TestClient(create_app(config))
    response = client.get("/ops/dealflow")
    assert response.status_code == 200
    payload = response.json()
    assert payload["snapshot"]["validity"] == "STALE"
    assert payload["snapshot"]["triage_enabled"] is False


def test_bootstrap_includes_schedule_feed_and_alerts(tmp_path: Path):
    config = _config(tmp_path)
    now = dt.datetime.now(dt.timezone.utc)
    _write_heartbeat(config, now=now, engine_offset_s=0.0, next_run_s=180)
    today = now.date().isoformat()
    _write_scout_handoff(
        tmp_path,
        {
            "run_id": f"{today}-090000-manual",
            "date": today,
            "items": [
                {
                    "queue_id": f"{today}-090000-manual:AAPL",
                    "symbol": "AAPL",
                    "lane": "CORE",
                    "why_now": "High quality with stable macro setup.",
                    "research_playbook": "QUALITY",
                }
            ],
        },
    )
    client = TestClient(create_app(config))
    response = client.get("/ops/bootstrap")
    assert response.status_code == 200
    payload = response.json()
    assert payload["schedule"]["schedule_status"] != "UNKNOWN"
    assert payload["summary"]["total_candidates"] == 1
    assert payload["top_candidates"][0]["symbol"] == "AAPL"
    assert payload["pending_created_count"] == 0
    assert payload["allocator_pending_count"] == 0
    assert payload["allocator_pending_funding_count"] == 0
    alert_codes = {row["code"] for row in payload["alerts"]}
    assert "SCHEDULE_UNKNOWN" not in alert_codes
    assert "SNAPSHOT_STALE" not in alert_codes
    assert payload["portfolio_drift_status"] == "UNKNOWN"
    assert payload["portfolio_drift_pct"] is None


def test_bootstrap_includes_portfolio_drift_when_allocations_available(tmp_path: Path):
    config = _config(tmp_path)
    now = dt.datetime.now(dt.timezone.utc)
    _write_heartbeat(config, now=now, engine_offset_s=0.0, next_run_s=180)
    today = now.date().isoformat()
    _write_scout_handoff(
        tmp_path,
        {
            "run_id": f"{today}-090000-manual",
            "date": today,
            "items": [],
        },
    )
    _write_allocation(
        Path(config["operator_gateway_model_allocation_path"]),
        as_of_utc=now.isoformat(),
        weights={"AAPL": 0.50, "XLE": 0.50},
    )
    _write_allocation(
        Path(config["operator_gateway_broker_allocation_path"]),
        as_of_utc=now.isoformat(),
        weights={"AAPL": 0.90, "XLE": 0.10},
    )
    client = TestClient(create_app(config))
    response = client.get("/ops/bootstrap")
    assert response.status_code == 200
    payload = response.json()
    assert payload["portfolio_drift_pct"] == 40.0
    assert payload["portfolio_drift_status"] == "DISCONNECTED"
    assert payload["portfolio_non_model_exposure_count"] == 0
    assert "portfolio_drift_message" in payload
    alert_codes = {row["code"] for row in payload["alerts"]}
    assert "PORTFOLIO_DISCONNECTED" in alert_codes


def test_drift_impact_detects_non_model_exposure(tmp_path: Path):
    config = _config(tmp_path)
    now = dt.datetime.now(dt.timezone.utc)
    _write_heartbeat(config, now=now, engine_offset_s=0.0, next_run_s=180)
    _write_scout_handoff(
        tmp_path,
        {
            "run_id": f"{now.date().isoformat()}-090000-manual",
            "date": now.date().isoformat(),
            "items": [],
        },
    )
    _write_allocation(
        Path(config["operator_gateway_model_allocation_path"]),
        as_of_utc=now.isoformat(),
        weights={"AAPL": 0.50, "XLE": 0.50},
    )
    _write_allocation(
        Path(config["operator_gateway_broker_allocation_path"]),
        as_of_utc=now.isoformat(),
        weights={"AAPL": 0.40, "XLE": 0.40, "XYZ": 0.20},
    )
    client = TestClient(create_app(config))
    impact = client.get("/ops/drift-impact?max_items=8")
    assert impact.status_code == 200
    payload = impact.json()
    assert payload["available"] is True
    assert payload["non_model_exposure_count"] == 1
    assert payload["non_model_symbols"] == ["XYZ"]
    assert any(row["classification"] == "NON_MODEL_EXPOSURE" and row["symbol"] == "XYZ" for row in payload["items"])

    bootstrap = client.get("/ops/bootstrap")
    assert bootstrap.status_code == 200
    bootstrap_payload = bootstrap.json()
    assert bootstrap_payload["portfolio_non_model_exposure_count"] == 1
    alert_codes = {row["code"] for row in bootstrap_payload["alerts"]}
    assert "NON_MODEL_EXPOSURE_DETECTED" in alert_codes


def test_drift_sensitivity_settings_update_affects_bootstrap_status(tmp_path: Path):
    config = _config(tmp_path)
    now = dt.datetime.now(dt.timezone.utc)
    _write_heartbeat(config, now=now, engine_offset_s=0.0, next_run_s=180)
    _write_scout_handoff(
        tmp_path,
        {
            "run_id": f"{now.date().isoformat()}-090000-manual",
            "date": now.date().isoformat(),
            "items": [],
        },
    )
    _write_allocation(
        Path(config["operator_gateway_model_allocation_path"]),
        as_of_utc=now.isoformat(),
        weights={"AAPL": 0.58, "XLE": 0.42},
    )
    _write_allocation(
        Path(config["operator_gateway_broker_allocation_path"]),
        as_of_utc=now.isoformat(),
        weights={"AAPL": 0.66, "XLE": 0.34},
    )
    client = TestClient(create_app(config))
    initial = client.get("/ops/bootstrap")
    assert initial.status_code == 200
    assert initial.json()["portfolio_drift_pct"] == 8.0
    assert initial.json()["portfolio_drift_status"] == "DRIFTING"

    updated = client.post(
        "/ops/settings/drift-sensitivity",
        json={"amber_threshold_pct": 10.0, "red_threshold_pct": 20.0},
    )
    assert updated.status_code == 200
    payload = updated.json()
    assert payload["amber_threshold_pct"] == 10.0
    assert payload["red_threshold_pct"] == 20.0

    after = client.get("/ops/bootstrap")
    assert after.status_code == 200
    assert after.json()["portfolio_drift_status"] == "ALIGNED"


def test_bootstrap_flags_snapshot_stale_and_pending_created(tmp_path: Path):
    config = _config(tmp_path)
    now = dt.datetime.now(dt.timezone.utc)
    _write_heartbeat(config, now=now, engine_offset_s=0.0, next_run_s=240)
    stale_date = (now.date() - dt.timedelta(days=2)).isoformat()
    _write_scout_handoff(
        tmp_path,
        {
            "run_id": f"{stale_date}-090000-manual",
            "date": stale_date,
            "items": [
                {
                    "queue_id": f"{stale_date}-090000-manual:TSLA",
                    "symbol": "TSLA",
                    "lane": "MOMENTUM",
                    "why_now": "Momentum continuation setup.",
                    "research_playbook": "MOMENTUM_BREAKOUT",
                }
            ],
        },
    )
    client = TestClient(create_app(config))
    created = client.post(
        "/ops/triage-intent",
        json={
            "action": "APPROVE",
            "symbol": "TSLA",
            "queue_id": f"{stale_date}-090000-manual:TSLA",
            "target_queue_run_id": "run-1",
            "snapshot_id": "snap-x",
            "snapshot_hash_canonical": "h1",
            "snapshot_hash_raw": "h2",
            "snapshot_validity": "VALID",
            "snapshot_price": 100.0,
            "thesis_tags": ["momentum"],
        },
    )
    assert created.status_code == 200

    response = client.get("/ops/bootstrap")
    assert response.status_code == 200
    payload = response.json()
    assert payload["snapshot"]["validity"] == "STALE"
    assert payload["pending_created_count"] == 1
    alert_codes = {row["code"] for row in payload["alerts"]}
    assert "SNAPSHOT_STALE" in alert_codes
    assert "PENDING_TRIAGE_INTENTS" in alert_codes


def test_bootstrap_includes_allocator_pending_funding_alert(tmp_path: Path):
    config = _config(tmp_path)
    now = dt.datetime.now(dt.timezone.utc)
    _write_heartbeat(config, now=now, engine_offset_s=0.0, next_run_s=240)
    today = now.date().isoformat()
    _write_scout_handoff(
        tmp_path,
        {
            "run_id": f"{today}-090000-manual",
            "date": today,
            "items": [],
        },
    )
    _seed_allocator_intent(
        config,
        intent_id="intent-pending-funding",
        status=IntentStatus.VALIDATED_WAIT_FUNDING,
        funding_source_status=FundingSourceStatus.PENDING_SALE_PROCEEDS,
        funding_available_at_utc=now + dt.timedelta(hours=1),
    )
    client = TestClient(create_app(config))
    response = client.get("/ops/bootstrap")
    assert response.status_code == 200
    payload = response.json()
    assert payload["allocator_pending_count"] >= 1
    assert payload["allocator_pending_funding_count"] >= 1
    alert_codes = {row["code"] for row in payload["alerts"]}
    assert "ALLOCATOR_PENDING_FUNDING" in alert_codes


def test_allocator_status_endpoint_returns_recent_intents(tmp_path: Path):
    config = _config(tmp_path)
    now = dt.datetime.now(dt.timezone.utc)
    _seed_allocator_intent(
        config,
        intent_id="intent-allocator-status",
        status=IntentStatus.VALIDATED,
        funding_source_status=FundingSourceStatus.SETTLED_CASH,
        funding_available_at_utc=now,
    )
    client = TestClient(create_app(config))
    response = client.get("/ops/allocator-intents/status?since_minutes=60")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] >= 1
    row = payload["items"][0]
    assert row["intent_id"] == "intent-allocator-status"
    assert row["status"] == IntentStatus.VALIDATED.value
    assert row["funding_source_status"] == FundingSourceStatus.SETTLED_CASH.value


def test_bootstrap_returns_304_when_etag_matches(tmp_path: Path):
    config = _config(tmp_path)
    now = dt.datetime.now(dt.timezone.utc)
    _write_heartbeat(config, now=now, engine_offset_s=0.0, next_run_s=180)
    _write_scout_handoff(
        tmp_path,
        {
            "run_id": f"{now.date().isoformat()}-090000-manual",
            "date": now.date().isoformat(),
            "items": [],
        },
    )
    client = TestClient(create_app(config))
    first = client.get("/ops/bootstrap")
    assert first.status_code == 200
    etag = first.headers.get("etag")
    assert etag

    second = client.get("/ops/bootstrap", headers={"If-None-Match": etag})
    assert second.status_code == 304
    assert second.headers.get("etag") == etag


def test_bootstrap_etag_changes_when_handoff_changes(tmp_path: Path):
    config = _config(tmp_path)
    now = dt.datetime.now(dt.timezone.utc)
    _write_heartbeat(config, now=now, engine_offset_s=0.0, next_run_s=180)
    today = now.date().isoformat()
    _write_scout_handoff(
        tmp_path,
        {
            "run_id": f"{today}-090000-manual",
            "date": today,
            "items": [],
        },
    )
    client = TestClient(create_app(config))
    first = client.get("/ops/bootstrap")
    etag = first.headers.get("etag")
    assert etag

    _write_scout_handoff(
        tmp_path,
        {
            "run_id": f"{today}-090000-manual",
            "date": today,
            "items": [
                {
                    "queue_id": f"{today}-090000-manual:AAPL",
                    "symbol": "AAPL",
                    "lane": "CORE",
                    "why_now": "Quality setup with stable trend.",
                    "research_playbook": "QUALITY",
                }
            ],
        },
    )
    updated = client.get("/ops/bootstrap", headers={"If-None-Match": etag})
    assert updated.status_code == 200
    assert updated.headers.get("etag")
    assert updated.headers.get("etag") != etag


def test_gateway_enables_cors_when_origins_configured(tmp_path: Path):
    config = _config(tmp_path)
    config["operator_gateway_cors_origins"] = "http://localhost:19006,https://ops.aeternus.local"
    app = create_app(config)
    classes = [entry.cls for entry in app.user_middleware]
    assert CORSMiddleware in classes


def test_gateway_enforces_api_key_when_enabled(tmp_path: Path):
    config = _config(tmp_path)
    config["operator_gateway_enforce_api_key"] = True
    config["operator_gateway_api_key_header"] = "X-Aeternus-Key"
    config["operator_gateway_api_key"] = "test-secret"
    now = dt.datetime.now(dt.timezone.utc)
    _write_heartbeat(config, now=now, engine_offset_s=0.0, next_run_s=180)
    _write_scout_handoff(
        tmp_path,
        {
            "run_id": f"{now.date().isoformat()}-090000-manual",
            "date": now.date().isoformat(),
            "items": [],
        },
    )
    client = TestClient(create_app(config))

    blocked = client.get("/ops/bootstrap")
    assert blocked.status_code == 401

    allowed = client.get("/ops/bootstrap", headers={"X-Aeternus-Key": "test-secret"})
    assert allowed.status_code == 200


def test_system_shock_endpoint_writes_regime_override(tmp_path: Path):
    config = _config(tmp_path)
    client = TestClient(create_app(config))
    response = client.post(
        "/ops/system/shock",
        json={
            "regime": "CRISIS",
            "reason": "integration_test",
            "source": "test-harness",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["regime"] == "CRISIS"
    assert payload["reason"] == "integration_test"
    override_path = Path(payload["override_path"])
    assert override_path.exists()
    stored = override_path.read_text()
    assert "\"regime\": \"CRISIS\"" in stored


def test_allocator_report_card_endpoint_returns_summary(tmp_path: Path):
    config = _config(tmp_path)
    now = dt.datetime.now(dt.timezone.utc)
    _seed_allocator_intent(
        config,
        intent_id="intent-report-validated",
        status=IntentStatus.VALIDATED,
        funding_source_status=FundingSourceStatus.SETTLED_CASH,
        funding_available_at_utc=now,
    )
    _seed_allocator_intent(
        config,
        intent_id="intent-report-pending-funding",
        status=IntentStatus.VALIDATED_WAIT_FUNDING,
        funding_source_status=FundingSourceStatus.PENDING_SALE_PROCEEDS,
        funding_available_at_utc=now + dt.timedelta(hours=1),
    )
    client = TestClient(create_app(config))
    response = client.get("/ops/allocator/report-card?lookback_days=7")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_intents"] >= 2
    assert payload["validated_count"] >= 2
    assert payload["pending_funding_count"] >= 1
    assert "status_counts" in payload


def test_mirror_confirm_requires_legal_consent(tmp_path: Path):
    config = _config(tmp_path)
    now = dt.datetime.now(dt.timezone.utc)
    _seed_allocator_intent(
        config,
        intent_id="intent-mirror-legal",
        status=IntentStatus.VALIDATED,
        funding_source_status=FundingSourceStatus.SETTLED_CASH,
        funding_available_at_utc=now,
    )
    client = TestClient(create_app(config))

    challenge = client.post(
        "/ops/mirror-intents/intent-mirror-legal/challenge",
        json={"user_id": "u-1", "created_by": "operator-ui"},
    )
    assert challenge.status_code == 200
    challenge_payload = challenge.json()
    confirm = client.post(
        "/ops/mirror-intents/intent-mirror-legal/confirm",
        json={
            "challenge_id": challenge_payload["challenge_id"],
            "client_preview_hash": challenge_payload["preview_hash"],
            "user_id": "u-1",
            "interaction_type": "HOLD_TO_FOLLOW",
            "legal_version": "2026-02-08.v1",
            "legal_consent_active": False,
        },
    )
    assert confirm.status_code == 409
    assert "LEGAL_CONSENT_REQUIRED" in confirm.json()["detail"]


def test_mirror_challenge_confirm_updates_allocator_status(tmp_path: Path):
    config = _config(tmp_path)
    now = dt.datetime.now(dt.timezone.utc)
    _seed_allocator_intent(
        config,
        intent_id="intent-mirror-ok",
        status=IntentStatus.VALIDATED,
        funding_source_status=FundingSourceStatus.SETTLED_CASH,
        funding_available_at_utc=now,
    )
    client = TestClient(create_app(config))

    challenge = client.post(
        "/ops/mirror-intents/intent-mirror-ok/challenge",
        json={"user_id": "u-2", "created_by": "operator-ui"},
    )
    assert challenge.status_code == 200
    challenge_payload = challenge.json()
    assert challenge_payload["status"] == IntentStatus.VALIDATED.value
    assert challenge_payload["legal_consent_required"] is True

    confirm = client.post(
        "/ops/mirror-intents/intent-mirror-ok/confirm",
        json={
            "challenge_id": challenge_payload["challenge_id"],
            "client_preview_hash": challenge_payload["preview_hash"],
            "user_id": "u-2",
            "interaction_type": "HOLD_TO_FOLLOW",
            "legal_version": "2026-02-08.v1",
            "legal_consent_active": True,
        },
    )
    assert confirm.status_code == 200
    payload = confirm.json()
    assert payload["status_after"] == IntentStatus.SUBMITTED.value
    assert payload["broker_submission"] == "SUBMITTED"
    assert payload["broker_adapter"] == "mock"

    status = client.get("/ops/allocator-intents/status?since_minutes=60")
    assert status.status_code == 200
    rows = status.json()["items"]
    matched = next(row for row in rows if row["intent_id"] == "intent-mirror-ok")
    assert matched["status"] == IntentStatus.SUBMITTED.value
    assert matched["reason_code"] == "MIRROR_CONFIRMED"
    assert matched["status_message"] == "Follow confirmed."


def test_mirror_confirm_rejects_preview_hash_mismatch(tmp_path: Path):
    config = _config(tmp_path)
    now = dt.datetime.now(dt.timezone.utc)
    _seed_allocator_intent(
        config,
        intent_id="intent-mirror-bad-hash",
        status=IntentStatus.VALIDATED,
        funding_source_status=FundingSourceStatus.SETTLED_CASH,
        funding_available_at_utc=now,
    )
    client = TestClient(create_app(config))

    challenge = client.post(
        "/ops/mirror-intents/intent-mirror-bad-hash/challenge",
        json={"user_id": "u-3", "created_by": "operator-ui"},
    )
    assert challenge.status_code == 200
    challenge_payload = challenge.json()

    confirm = client.post(
        "/ops/mirror-intents/intent-mirror-bad-hash/confirm",
        json={
            "challenge_id": challenge_payload["challenge_id"],
            "client_preview_hash": "mismatch",
            "user_id": "u-3",
            "interaction_type": "HOLD_TO_FOLLOW",
            "legal_version": "2026-02-08.v1",
            "legal_consent_active": True,
        },
    )
    assert confirm.status_code == 409
    assert "CONFLICT_PREVIEW_HASH_MISMATCH" in confirm.json()["detail"]


def test_intent_confirm_alias_matches_mirror_confirm(tmp_path: Path):
    config = _config(tmp_path)
    now = dt.datetime.now(dt.timezone.utc)
    _seed_allocator_intent(
        config,
        intent_id="intent-mirror-alias",
        status=IntentStatus.VALIDATED,
        funding_source_status=FundingSourceStatus.SETTLED_CASH,
        funding_available_at_utc=now,
    )
    client = TestClient(create_app(config))
    challenge = client.post(
        "/ops/mirror-intents/intent-mirror-alias/challenge",
        json={"user_id": "u-5", "created_by": "operator-ui"},
    )
    assert challenge.status_code == 200
    challenge_payload = challenge.json()

    confirm = client.post(
        "/ops/intent/intent-mirror-alias/confirm",
        json={
            "challenge_id": challenge_payload["challenge_id"],
            "client_preview_hash": challenge_payload["preview_hash"],
            "user_id": "u-5",
            "interaction_type": "HOLD_TO_FOLLOW",
            "legal_version": "2026-02-08.v1",
            "legal_consent_active": True,
        },
    )
    assert confirm.status_code == 200
    payload = confirm.json()
    assert payload["status_after"] == IntentStatus.SUBMITTED.value


def test_mirror_intent_preview_includes_latest_challenge_and_drift(tmp_path: Path):
    config = _config(tmp_path)
    now = dt.datetime.now(dt.timezone.utc)
    _seed_allocator_intent(
        config,
        intent_id="intent-mirror-preview",
        status=IntentStatus.VALIDATED,
        funding_source_status=FundingSourceStatus.SETTLED_CASH,
        funding_available_at_utc=now,
    )
    _write_allocation(
        Path(config["operator_gateway_model_allocation_path"]),
        as_of_utc=now.isoformat(),
        weights={"AAPL": 0.70, "XLE": 0.30},
    )
    _write_allocation(
        Path(config["operator_gateway_broker_allocation_path"]),
        as_of_utc=now.isoformat(),
        weights={"AAPL": 0.68, "XLE": 0.32},
    )
    client = TestClient(create_app(config))
    challenge = client.post(
        "/ops/mirror-intents/intent-mirror-preview/challenge",
        json={"user_id": "u-6", "created_by": "operator-ui"},
    )
    assert challenge.status_code == 200
    challenge_payload = challenge.json()

    preview = client.get("/ops/mirror-intents/intent-mirror-preview")
    assert preview.status_code == 200
    payload = preview.json()
    assert payload["intent_id"] == "intent-mirror-preview"
    assert payload["challenge"]["challenge_id"] == challenge_payload["challenge_id"]
    assert payload["portfolio_drift_status"] == "ALIGNED"
    assert payload["portfolio_drift_pct"] is not None
    assert payload["comparison"]["available"] is True
    assert payload["comparison"]["target_weight_pct"] == 70.0
    assert payload["comparison"]["current_weight_pct"] == 68.0
    assert payload["comparison"]["delta_weight_pct"] == 2.0


def test_mirror_confirm_blocked_when_broker_adapter_disabled(tmp_path: Path):
    config = _config(tmp_path)
    config["operator_gateway_broker_adapter"] = "disabled"
    now = dt.datetime.now(dt.timezone.utc)
    _seed_allocator_intent(
        config,
        intent_id="intent-mirror-adapter-off",
        status=IntentStatus.VALIDATED,
        funding_source_status=FundingSourceStatus.SETTLED_CASH,
        funding_available_at_utc=now,
    )
    client = TestClient(create_app(config))

    challenge = client.post(
        "/ops/mirror-intents/intent-mirror-adapter-off/challenge",
        json={"user_id": "u-4", "created_by": "operator-ui"},
    )
    assert challenge.status_code == 200
    challenge_payload = challenge.json()

    confirm = client.post(
        "/ops/mirror-intents/intent-mirror-adapter-off/confirm",
        json={
            "challenge_id": challenge_payload["challenge_id"],
            "client_preview_hash": challenge_payload["preview_hash"],
            "user_id": "u-4",
            "interaction_type": "HOLD_TO_FOLLOW",
            "legal_version": "2026-02-08.v1",
            "legal_consent_active": True,
        },
    )
    assert confirm.status_code == 409
    assert "BROKER_ADAPTER_DISABLED" in confirm.json()["detail"]


def test_mission_control_endpoint_returns_end_to_end_stages(tmp_path: Path):
    config = _config(tmp_path)
    as_of_date = "2026-03-11"
    date_dir = tmp_path / "deal_flow" / as_of_date
    _seed_x_feed_ready(tmp_path, as_of_date)
    write_json_locked(
        date_dir / "scout_audit.json",
        {
            "breakout": {"count": 3},
            "insider": {"buy_clusters": [], "sell_clusters": []},
            "technical_ignition": {"promoted_count": 1},
            "earnings_options": {"promoted_count": 1},
        },
    )
    write_json_locked(
        date_dir / "universe_filter.json",
        {
            "overall_ready": True,
            "kept_symbols_count": 357,
            "rule_snapshot": {"total_company_count": 5489, "candidate_drop_count": 5132},
        },
    )
    write_json_locked(
        date_dir / "discovery_delta.json",
        {"coverage_summary": {"signal_count": 47}},
    )
    write_json_locked(
        date_dir / "connector_health.json",
        [
            {"connector": "social_news", "status": "OK"},
            {"connector": "macro", "status": "OK"},
        ],
    )
    write_json_locked(
        date_dir / "scout_ticker_summary.json",
        {"date": as_of_date, "total_mentions": 1, "unique_ticker_count": 1},
    )
    write_json_locked(
        date_dir / "final_dealflow_tickers.json",
        {"run_id": f"{as_of_date}-manual", "date": as_of_date, "tickers": ["NVDA"]},
    )
    write_json_locked(
        date_dir / "learning_status.json",
        {
            "learning_status": "OK",
            "hindsight_status": "OK",
            "performance_status": "OK",
            "weight_update_status": "UPDATED",
            "observed_edges_added": 2,
        },
    )
    write_json_locked(date_dir / "source_attribution.json", {"rows": [{"source": "x_feed"}]})
    write_json_locked(
        tmp_path / "paper_execution" / "latest_plan.json",
        {"date": as_of_date, "orders": [{"symbol": "NVDA"}], "candidates_considered": 1},
    )
    write_json_locked(
        tmp_path / "paper_execution" / "positions.json",
        {"open_positions": {"NVDA": {"symbol": "NVDA"}}, "source_plan_id": "plan-1"},
    )
    _write_analysis_report(tmp_path, "NVDA", as_of_date, {"recommendation": "BUY"})

    client = TestClient(create_app(config))
    response = client.get(f"/ops/mission-control?date={as_of_date}")
    assert response.status_code == 200
    payload = response.json()
    stages = {row["stage_id"]: row for row in payload["stages"]}
    assert payload["as_of_date"] == as_of_date
    assert payload["pipeline_state"] == "OK"
    assert {
        "scouts",
        "discover",
        "collect",
        "research",
        "portfolio",
        "execution",
        "learning",
    }.issubset(set(stages.keys()))
    assert stages["discover"]["metrics"]["pre_filter_count"] == 5489
    assert stages["discover"]["metrics"]["post_filter_count"] == 357
    assert stages["research"]["metrics"]["analysis_count"] == 1


def test_scout_inventory_contains_manual_and_auto_scouts(tmp_path: Path):
    config = _config(tmp_path)
    as_of_date = "2026-03-11"
    date_dir = tmp_path / "deal_flow" / as_of_date
    _seed_x_feed_ready(tmp_path, as_of_date)
    write_json_locked(
        date_dir / "scout_audit.json",
        {
            "breakout": {"count": 2},
            "insider": {"buy_clusters": [], "sell_clusters": []},
            "technical_ignition": {"promoted_count": 0},
            "earnings_options": {"promoted_count": 0},
        },
    )
    write_json_locked(date_dir / "coverage_precheck.json", {"complete_count": 1, "partial_count": 0, "missing_count": 0})
    write_json_locked(date_dir / "event_cards.json", [{"event_id": "evt-1"}])

    client = TestClient(create_app(config))
    response = client.get(f"/ops/scouts?date={as_of_date}")
    assert response.status_code == 200
    payload = response.json()
    scout_ids = {row["scout_id"] for row in payload["scouts"]}
    assert payload["as_of_date"] == as_of_date
    assert {"x_feed_manual", "earnings_options_prompt", "scenario_compiler"}.issubset(scout_ids)


def test_scout_prompt_endpoint_supports_x_feed_pass_selection(tmp_path: Path):
    config = _config(tmp_path)
    client = TestClient(create_app(config))
    response = client.get("/ops/scouts/x_feed_manual/prompt?date=2026-03-11&pass_num=1")
    assert response.status_code == 200
    payload = response.json()
    assert payload["scout_id"] == "x_feed_manual"
    assert payload["pass_num"] == 1
    assert "TASK:" in payload["prompt_text"]


def test_unknown_scout_returns_404(tmp_path: Path):
    config = _config(tmp_path)
    client = TestClient(create_app(config))
    response = client.get("/ops/scouts/not_a_real_scout?date=2026-03-11")
    assert response.status_code == 404

