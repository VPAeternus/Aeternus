"""Business logic for operator gateway endpoints."""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tradingagents.broker_adapters.base import BrokerOrderRequest
from tradingagents.capital_allocator.contracts import IntentStatus
from tradingagents.capital_allocator.reporting import build_allocator_report_card
from tradingagents.capital_allocator.repository import (
    MirrorIntentError,
    SQLiteAllocatorRepository,
)
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.dealflow.control_io import write_json_locked
from tradingagents.dealflow.canonical_json import canonical_hash
from tradingagents.dealflow.engine_heartbeat import evaluate_schedule_guard
from tradingagents.dealflow.system_halt import clear_system_halt, is_hands_off_active, load_system_halt, set_system_halt
from tradingagents.dealflow.triage_control import (
    TriageConflictError,
    TriageValidationError,
    create_intent,
    list_recent_intents,
    load_receipts,
    triage_intents_path,
    triage_receipts_path,
    undo_intent,
)
from .broker_bridge import BrokerAdapterDisabledError, build_broker_adapter
from .drift_engine import build_drift_impact, build_symbol_alignment_delta, compute_portfolio_drift
from .drift_settings import (
    load_drift_sensitivity,
    save_drift_sensitivity,
)
from .status_dictionary import STATUS_DICTIONARY_VERSION, humanize_allocator_status
from .transformers import build_snapshot_envelope, transform_candidate_detail, transform_dealflow_feed


class OperatorGatewayError(RuntimeError):
    """Base error for operator gateway service failures."""


class OperatorGatewayBlockedError(OperatorGatewayError):
    """Raised when a mutation is blocked by safety gates."""


class OperatorGatewayNotFoundError(OperatorGatewayError):
    """Raised when a requested operator resource does not exist."""


class OperatorGatewayService:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = dict(config or DEFAULT_CONFIG)

    def get_schedule(self, *, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
        schedule = evaluate_schedule_guard(config=self.config, now=now)
        halt = load_system_halt(self.config)
        schedule["halt_active"] = bool(halt.get("active"))
        schedule["halt_reason"] = str(halt.get("reason") or "")
        if bool(halt.get("active")):
            schedule["commit_window_open"] = False
        return schedule

    def get_dealflow_feed(self, *, now: Optional[dt.datetime] = None, limit: Optional[int] = None) -> Dict[str, Any]:
        queue_payload, queue_path = self._load_latest_research_queue()
        out = transform_dealflow_feed(
            raw_queue=queue_payload,
            snapshot=build_snapshot_envelope(
                raw_payload=queue_payload,
                artifact_path=queue_path,
                now=now,
            ),
            thesis_summary_max_chars=int(self.config.get("operator_gateway_thesis_summary_max_chars", 140)),
        )
        if limit is not None and limit > 0:
            out["candidates"] = list(out.get("candidates", []))[: int(limit)]
        return out

    def get_candidate_detail(self, *, symbol: str, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
        symbol_norm = str(symbol or "").upper().strip()
        queue_payload, queue_path = self._load_latest_research_queue()
        snapshot = build_snapshot_envelope(raw_payload=queue_payload, artifact_path=queue_path, now=now)
        queue_item = self._find_queue_item(queue_payload=queue_payload, symbol=symbol_norm)
        queue_date = str(queue_payload.get("date") or "")
        analysis_report, _analysis_path = self._load_analysis_report(symbol=symbol_norm, analysis_date=queue_date)
        return transform_candidate_detail(
            symbol=symbol_norm,
            queue_item=queue_item,
            analysis_report=analysis_report,
            snapshot=snapshot,
            detail_summary_max_chars=int(self.config.get("operator_gateway_detail_summary_max_chars", 320)),
        )

    def get_bootstrap(self, *, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
        now_utc = _as_utc(now)
        schedule = self.get_schedule(now=now_utc)
        dealflow = self.get_dealflow_feed(now=now_utc)
        sensitivity = self.get_drift_sensitivity()
        drift = compute_portfolio_drift(config=self.config, now=now_utc, sensitivity=sensitivity)
        drift_impact = build_drift_impact(
            config=self.config,
            now=now_utc,
            sensitivity=sensitivity,
            max_items=1,
        )
        since_minutes = int(self.config.get("operator_gateway_bootstrap_since_minutes", 60))
        status = self.list_triage_status(since_minutes=since_minutes, now=now_utc)
        allocator_status = self.list_allocator_status(since_minutes=since_minutes, now=now_utc)
        items = status.get("items", []) if isinstance(status, dict) else []
        allocator_items = allocator_status.get("items", []) if isinstance(allocator_status, dict) else []
        created_count = sum(1 for row in items if isinstance(row, dict) and str(row.get("status") or "") == "CREATED")
        allocator_pending_statuses = {
            IntentStatus.PROPOSED.value,
            IntentStatus.VALIDATED.value,
            IntentStatus.VALIDATED_WAIT_FUNDING.value,
            IntentStatus.SUBMITTED.value,
        }
        allocator_pending_count = sum(
            1
            for row in allocator_items
            if isinstance(row, dict) and str(row.get("status") or "") in allocator_pending_statuses
        )
        allocator_pending_funding_count = sum(
            1
            for row in allocator_items
            if isinstance(row, dict)
            and (
                str(row.get("status") or "") == IntentStatus.VALIDATED_WAIT_FUNDING.value
                or str(row.get("funding_source_status") or "") == "PENDING_SALE_PROCEEDS"
            )
        )
        candidate_limit = max(1, int(self.config.get("operator_gateway_bootstrap_top_candidates", 12)))
        top_candidates = list(dealflow.get("candidates", []))[:candidate_limit]
        snapshot = dealflow.get("snapshot", {})
        summary = dealflow.get("summary", {})
        alerts = self._build_bootstrap_alerts(
            schedule=schedule,
            snapshot=snapshot if isinstance(snapshot, dict) else {},
            pending_created_count=created_count,
            allocator_pending_funding_count=allocator_pending_funding_count,
            drift=drift,
            non_model_exposure_count=int(drift_impact.get("non_model_exposure_count", 0)),
        )
        return {
            "server_time_utc": now_utc.isoformat(),
            "schedule": schedule,
            "snapshot": snapshot,
            "summary": summary,
            "top_candidates": top_candidates,
            "pending_created_count": int(created_count),
            "pending_total_count": int(len(items)),
            "allocator_pending_funding_count": int(allocator_pending_funding_count),
            "allocator_pending_count": int(allocator_pending_count),
            "portfolio_drift_pct": drift.get("portfolio_drift_pct"),
            "portfolio_drift_status": str(drift.get("portfolio_drift_status") or "UNKNOWN"),
            "portfolio_last_sync_utc": str(drift.get("portfolio_last_sync_utc") or ""),
            "portfolio_drift_message": str(drift.get("portfolio_drift_message") or ""),
            "portfolio_non_model_exposure_count": int(drift_impact.get("non_model_exposure_count", 0)),
            "drift_sensitivity": sensitivity,
            "alerts": alerts,
        }

    def get_bootstrap_etag(self, *, now: Optional[dt.datetime] = None) -> str:
        now_utc = _as_utc(now)
        bucket_seconds = max(1, int(self.config.get("operator_gateway_bootstrap_etag_bucket_seconds", 20)))
        bucket = int(now_utc.timestamp()) // bucket_seconds
        queue_path = self._resolve_latest_research_queue_path()
        payload = {
            "bucket": bucket,
            "heartbeat": _file_fingerprint(Path(str(self.config.get("operator_gateway_heartbeat_path", "")))),
            "system_halt": _file_fingerprint(Path(str(self.config.get("operator_gateway_system_halt_path", "")))),
            "queue": _file_fingerprint(queue_path),
            "intents": _file_fingerprint(triage_intents_path(self.config)),
            "receipts": _file_fingerprint(triage_receipts_path(self.config)),
            "allocator_db": _file_fingerprint(self._allocator_db_path()),
            "bootstrap_since_minutes": int(self.config.get("operator_gateway_bootstrap_since_minutes", 60)),
            "bootstrap_top_candidates": int(self.config.get("operator_gateway_bootstrap_top_candidates", 12)),
        }
        return canonical_hash(payload)

    def get_mission_control(
        self,
        *,
        as_of_date: Optional[str] = None,
        now: Optional[dt.datetime] = None,
    ) -> Dict[str, Any]:
        resolved_date = self._resolve_as_of_date(as_of_date=as_of_date)
        now_utc = _as_utc(now)
        date_dir = self._dealflow_date_dir(resolved_date)
        scouts = self._safe_read_json(date_dir / "scout_audit.json")
        universe_filter = self._safe_read_json(date_dir / "universe_filter.json")
        discovery_delta = self._safe_read_json(date_dir / "discovery_delta.json")
        connector_health = self._safe_read_json_list(date_dir / "connector_health.json")
        shortlist = self._safe_read_json(date_dir / "shortlist_top20.json")
        research_queue = self._safe_read_json(date_dir / "research_queue.json")
        learning_status = self._safe_read_json(date_dir / "learning_status.json")
        source_attribution = self._safe_read_json(date_dir / "source_attribution.json")

        x_feed_readiness = self._compute_x_feed_readiness(resolved_date)
        x_ready = bool(x_feed_readiness.get("ready"))
        x_completed = len(list(x_feed_readiness.get("completed_passes", []) or []))
        x_required = len(list(x_feed_readiness.get("required_passes", []) or []))
        breakout_count = int(((scouts.get("breakout") or {}).get("count", 0) or 0)
                             if isinstance(scouts, dict) else 0)
        technical_count = int(
            ((scouts.get("technical_ignition") or {}).get("promoted_count", 0) or 0)
            if isinstance(scouts, dict)
            else 0
        )
        earnings_count = int(
            ((scouts.get("earnings_options") or {}).get("promoted_count", 0) or 0)
            if isinstance(scouts, dict)
            else 0
        )

        scout_status = "MISSING"
        if scouts and x_ready:
            scout_status = "OK"
        elif scouts or x_completed > 0 or int(x_feed_readiness.get("merged_symbol_count", 0) or 0) > 0:
            scout_status = "DEGRADED"

        scout_stage = self._make_stage(
            stage_id="scouts",
            label="Scouts",
            status=scout_status,
            summary=(
                f"X-feed {x_completed}/{x_required} passes, breakout={breakout_count}, "
                f"technical={technical_count}, earnings/options={earnings_count}"
            ),
            artifacts=self._existing_artifact_strings(
                [
                    date_dir / "scout_audit.json",
                    self._x_feed_date_dir(resolved_date) / "merged.json",
                    self._macro_cache_path(resolved_date),
                    self._earnings_options_scout_path(resolved_date),
                ]
            ),
            metrics={
                "x_feed_ready": x_ready,
                "x_feed_completed_passes": x_completed,
                "x_feed_required_passes": x_required,
                "x_feed_merged_symbols": int(x_feed_readiness.get("merged_symbol_count", 0) or 0),
                "breakout_count": breakout_count,
                "technical_ignition_count": technical_count,
                "earnings_options_count": earnings_count,
            },
        )

        discover_ready = bool(universe_filter.get("overall_ready")) if universe_filter else False
        discover_status = "MISSING"
        if universe_filter:
            discover_status = "OK" if discover_ready else "DEGRADED"
        elif discovery_delta:
            discover_status = "DEGRADED"
        rule_snapshot = dict(universe_filter.get("rule_snapshot", {}) or {}) if universe_filter else {}
        kept_count = int(universe_filter.get("kept_symbols_count", 0) or universe_filter.get("universe_size", 0) or 0)
        pre_filter_count = int(
            rule_snapshot.get("total_company_count", 0)
            or (int(rule_snapshot.get("candidate_drop_count", 0) or 0) + kept_count)
            or 0
        )
        discover_stage = self._make_stage(
            stage_id="discover",
            label="Discover",
            status=discover_status,
            summary=f"Universe filtered to {kept_count} symbols from {pre_filter_count} candidates",
            artifacts=self._existing_artifact_strings(
                [
                    date_dir / "universe_filter.json",
                    date_dir / "discovery_delta.json",
                    date_dir / "fvg_recall.json",
                    date_dir / "fma_recall.json",
                ]
            ),
            metrics={
                "pre_filter_count": pre_filter_count,
                "post_filter_count": kept_count,
                "tier_counts": dict(universe_filter.get("tier_counts", {}) or {}),
                "signal_count": int(
                    ((discovery_delta.get("coverage_summary") or {}).get("signal_count", 0) or 0)
                    if isinstance(discovery_delta, dict)
                    else 0
                ),
            },
        )

        shortlist_candidates = list(shortlist.get("candidates", []) or []) if shortlist else []
        connector_errors = sum(1 for row in connector_health if str((row or {}).get("status") or "") == "ERROR")
        collect_status = "MISSING"
        if shortlist:
            collect_status = "DEGRADED" if connector_errors > 0 or not connector_health else "OK"
        collect_stage = self._make_stage(
            stage_id="collect",
            label="Collect & Score",
            status=collect_status,
            summary=(
                f"{len(shortlist_candidates)} shortlisted, {len(connector_health)} connectors, "
                f"{connector_errors} connector errors"
            ),
            artifacts=self._existing_artifact_strings(
                [
                    date_dir / "connector_health.json",
                    date_dir / "signals_raw.json",
                    date_dir / "shortlist_top20.json",
                    date_dir / "all_scored_candidates.json",
                ]
            ),
            metrics={
                "shortlist_count": len(shortlist_candidates),
                "connector_count": len(connector_health),
                "connector_error_count": connector_errors,
                "event_triggered": bool(shortlist.get("event_triggered")) if shortlist else False,
            },
        )

        queue_items = list(research_queue.get("items", []) or []) if research_queue else []
        analysis_paths = self._analysis_report_paths(resolved_date, queue_items)
        analysis_count = len(analysis_paths)
        research_status = "MISSING"
        if queue_items:
            if analysis_count >= len(queue_items):
                research_status = "OK"
            elif analysis_count > 0:
                research_status = "DEGRADED"
            else:
                research_status = "PENDING"
        research_stage = self._make_stage(
            stage_id="research",
            label="Research",
            status=research_status,
            summary=f"{analysis_count}/{len(queue_items)} analysis reports available",
            artifacts=self._existing_artifact_strings([date_dir / "research_queue.json", *analysis_paths[:8]]),
            metrics={
                "queue_count": len(queue_items),
                "analysis_count": analysis_count,
            },
        )

        portfolio_plan_path = self._paper_execution_dir() / "latest_plan.json"
        portfolio_plan = self._safe_read_json(portfolio_plan_path)
        plan_orders = list(portfolio_plan.get("orders", []) or []) if portfolio_plan else []
        plan_date = str(portfolio_plan.get("date") or "") if portfolio_plan else ""
        portfolio_status = "MISSING"
        if portfolio_plan:
            portfolio_status = "OK" if plan_date == resolved_date else "STALE"
        portfolio_stage = self._make_stage(
            stage_id="portfolio",
            label="Portfolio Plan",
            status=portfolio_status,
            summary=f"{len(plan_orders)} order intents in latest plan ({plan_date or 'unknown date'})",
            artifacts=self._existing_artifact_strings([portfolio_plan_path]),
            metrics={
                "plan_date": plan_date,
                "order_count": len(plan_orders),
                "candidates_considered": int(portfolio_plan.get("candidates_considered", 0) or 0)
                if portfolio_plan
                else 0,
            },
        )

        positions_path = self._paper_execution_dir() / "positions.json"
        positions_payload = self._safe_read_json(positions_path)
        open_positions = dict(positions_payload.get("open_positions", {}) or {}) if positions_payload else {}
        execution_status = "MISSING"
        if positions_payload:
            execution_status = "OK"
        execution_stage = self._make_stage(
            stage_id="execution",
            label="Execution",
            status=execution_status,
            summary=f"{len(open_positions)} open paper positions",
            artifacts=self._existing_artifact_strings(
                [
                    positions_path,
                    self._live_execution_dir() / "fills.json",
                    self._live_execution_dir() / "closed_trades.json",
                ]
            ),
            metrics={
                "open_positions": len(open_positions),
                "source_plan_id": str(positions_payload.get("source_plan_id") or "") if positions_payload else "",
            },
        )

        learning_stage_status = str(learning_status.get("learning_status") or "").upper().strip() if learning_status else ""
        learning_status_normalized = learning_stage_status or "MISSING"
        if learning_status_normalized not in {"OK", "DEGRADED", "BLOCKED"}:
            learning_status_normalized = "DEGRADED" if learning_status else "MISSING"
        learning_stage = self._make_stage(
            stage_id="learning",
            label="Learning",
            status=learning_status_normalized,
            summary=(
                f"hindsight={learning_status.get('hindsight_status', 'MISSING')}, "
                f"performance={learning_status.get('performance_status', 'MISSING')}, "
                f"weights={learning_status.get('weight_update_status', 'MISSING')}"
                if learning_status
                else "Learning artifacts missing"
            ),
            artifacts=self._existing_artifact_strings(
                [
                    date_dir / "learning_status.json",
                    date_dir / "source_attribution.json",
                    date_dir / "performance_review.json",
                ]
            ),
            metrics={
                "hindsight_status": str(learning_status.get("hindsight_status") or "") if learning_status else "",
                "performance_status": str(learning_status.get("performance_status") or "") if learning_status else "",
                "weight_update_status": str(learning_status.get("weight_update_status") or "") if learning_status else "",
                "observed_edges_added": int(learning_status.get("observed_edges_added", 0) or 0)
                if learning_status
                else 0,
                "source_attribution_rows": len(list(source_attribution.get("rows", []) or []))
                if source_attribution
                else 0,
            },
        )

        stages = [
            scout_stage,
            discover_stage,
            collect_stage,
            research_stage,
            portfolio_stage,
            execution_stage,
            learning_stage,
        ]

        blockers: List[str] = []
        recommendations: List[str] = []
        if scout_stage["status"] in {"MISSING", "DEGRADED"} and not x_ready:
            blockers.append("Manual X-feed is incomplete for this date.")
            recommendations.append("Complete missing X-feed passes before manual workflow runs.")
        if discover_stage["status"] == "MISSING":
            blockers.append("Discovery artifacts are missing for this date.")
        if collect_stage["status"] == "MISSING":
            blockers.append("Collection/scoring artifacts are missing for this date.")
        if research_stage["status"] in {"MISSING", "PENDING"}:
            recommendations.append("Run batch/deep analysis so shortlist symbols produce analysis reports.")
        if learning_stage["status"] == "MISSING":
            recommendations.append("Run learning cycle to produce hindsight, IC, and writeback artifacts.")

        pipeline_state = "OK"
        if blockers:
            pipeline_state = "BLOCKED"
        elif any(str(stage.get("status") or "") in {"DEGRADED", "STALE", "PENDING"} for stage in stages):
            pipeline_state = "DEGRADED"

        return {
            "as_of_date": resolved_date,
            "generated_at_utc": now_utc.isoformat(),
            "pipeline_state": pipeline_state,
            "stages": stages,
            "blockers": blockers,
            "recommendations": recommendations,
        }

    def get_scout_inventory(
        self,
        *,
        as_of_date: Optional[str] = None,
        now: Optional[dt.datetime] = None,
    ) -> Dict[str, Any]:
        del now
        resolved_date = self._resolve_as_of_date(as_of_date=as_of_date)
        scouts = self._build_scout_catalog(as_of_date=resolved_date)
        return {
            "as_of_date": resolved_date,
            "total_scouts": len(scouts),
            "scouts": scouts,
        }

    def get_scout_detail(
        self,
        *,
        scout_id: str,
        as_of_date: Optional[str] = None,
        pass_num: Optional[int] = None,
        now: Optional[dt.datetime] = None,
    ) -> Dict[str, Any]:
        del now
        resolved_date = self._resolve_as_of_date(as_of_date=as_of_date)
        scout = self._find_scout(scout_id=scout_id, as_of_date=resolved_date)
        detail: Dict[str, Any] = {
            "as_of_date": resolved_date,
            "scout": scout,
            "prompt_text": "",
            "prompt_parts": [],
            "ingest_schema": {},
            "notes": [],
        }
        scout_id_norm = str(scout_id or "").strip().lower()
        if scout_id_norm == "x_feed_manual":
            prompt_text, resolved_pass, pass_label, pass_parts = self._build_x_feed_prompt(
                as_of_date=resolved_date,
                pass_num=pass_num,
            )
            detail["prompt_text"] = prompt_text
            detail["prompt_parts"] = pass_parts
            detail["ingest_schema"] = {
                "required": ["raw_payload", "pass_num"],
                "optional": ["as_of_date"],
                "pass_num": resolved_pass,
                "pass_label": pass_label,
            }
            detail["notes"] = [
                "Paste Grok output exactly as returned (JSON-only preferred).",
                "Ingest writes raw archives plus merged symbols for this date.",
            ]
            return detail
        if scout_id_norm == "macro_prompt":
            detail["prompt_text"] = self._build_macro_prompt(resolved_date)
            detail["ingest_schema"] = {
                "required": ["raw_payload"],
                "optional": ["as_of_date"],
            }
            detail["notes"] = ["Macro payload must include all 8 dimensions and all 11 sectors."]
            return detail
        if scout_id_norm == "earnings_options_prompt":
            detail["prompt_text"] = self._build_earnings_options_prompt(resolved_date)
            detail["ingest_schema"] = {
                "required": ["raw_payload"],
                "optional": ["as_of_date"],
            }
            detail["notes"] = ["Payload should be a JSON object with a 'trending' list."]
            return detail
        detail["notes"] = ["This scout is automatic and runs inside discovery/sidecar pipeline stages."]
        return detail

    def get_scout_prompt(
        self,
        *,
        scout_id: str,
        as_of_date: Optional[str] = None,
        pass_num: Optional[int] = None,
    ) -> Dict[str, Any]:
        resolved_date = self._resolve_as_of_date(as_of_date=as_of_date)
        scout_id_norm = str(scout_id or "").strip().lower()
        if scout_id_norm == "x_feed_manual":
            prompt_text, resolved_pass, _, _ = self._build_x_feed_prompt(
                as_of_date=resolved_date,
                pass_num=pass_num,
            )
            return {
                "scout_id": scout_id_norm,
                "as_of_date": resolved_date,
                "pass_num": resolved_pass,
                "prompt_text": prompt_text,
                "copy_hint": (
                    "Paste into Grok, then POST raw output to /ops/scouts/x_feed_manual/ingest "
                    "with the same pass_num."
                ),
            }
        if scout_id_norm == "macro_prompt":
            return {
                "scout_id": scout_id_norm,
                "as_of_date": resolved_date,
                "pass_num": None,
                "prompt_text": self._build_macro_prompt(resolved_date),
                "copy_hint": "Paste into Grok, then POST output to /ops/scouts/macro_prompt/ingest.",
            }
        if scout_id_norm == "earnings_options_prompt":
            return {
                "scout_id": scout_id_norm,
                "as_of_date": resolved_date,
                "pass_num": None,
                "prompt_text": self._build_earnings_options_prompt(resolved_date),
                "copy_hint": "Paste into Grok, then POST output to /ops/scouts/earnings_options_prompt/ingest.",
            }
        if self._is_known_scout(scout_id_norm, as_of_date=resolved_date):
            raise OperatorGatewayError(f"Scout '{scout_id_norm}' is automatic and has no manual prompt.")
        raise OperatorGatewayNotFoundError(f"Unknown scout_id: {scout_id_norm}")

    def ingest_scout_payload(
        self,
        *,
        scout_id: str,
        as_of_date: Optional[str] = None,
        pass_num: Optional[int] = None,
        raw_payload: str,
    ) -> Dict[str, Any]:
        resolved_date = self._resolve_as_of_date(as_of_date=as_of_date)
        payload_text = str(raw_payload or "")
        if not payload_text.strip():
            raise OperatorGatewayError("raw_payload is required.")
        scout_id_norm = str(scout_id or "").strip().lower()

        if scout_id_norm == "x_feed_manual":
            effective_pass = int(pass_num or 0)
            if effective_pass <= 0:
                raise OperatorGatewayError("x_feed_manual ingest requires pass_num.")
            from tradingagents.dealflow.sources.x_feed_manual import ingest_pass

            result = ingest_pass(
                as_of_date=resolved_date,
                raw_text=payload_text,
                pass_num=effective_pass,
                dry_run=False,
            )
            readiness = self._compute_x_feed_readiness(resolved_date)
            status = "READY" if bool(readiness.get("ready")) else "PARTIAL"
            artifact_paths = []
            raw_path = str(result.get("raw_path") or "")
            merged_path = str(readiness.get("merged_path") or "")
            if raw_path:
                artifact_paths.append(raw_path)
            if merged_path:
                artifact_paths.append(merged_path)
            return {
                "scout_id": scout_id_norm,
                "as_of_date": resolved_date,
                "status": status,
                "message": (
                    f"Pass {effective_pass} ingested "
                    f"({int(result.get('tickers_parsed', 0) or 0)} parsed)."
                ),
                "artifact_paths": artifact_paths,
                "metrics": {
                    "pass_num": effective_pass,
                    "tickers_parsed": int(result.get("tickers_parsed", 0) or 0),
                    "tickers_merged": int(result.get("tickers_merged", 0) or 0),
                    "akg_written": int(result.get("akg_written", 0) or 0),
                    "completed_passes": len(list(readiness.get("completed_passes", []) or [])),
                    "required_passes": len(list(readiness.get("required_passes", []) or [])),
                    "merged_symbol_count": int(readiness.get("merged_symbol_count", 0) or 0),
                },
            }

        if scout_id_norm == "macro_prompt":
            parsed = self._extract_json_payload(payload_text)
            from cli.commands.macro_prompt import _validate_macro_payload

            normalized = _validate_macro_payload(parsed)
            path = self._macro_cache_path(resolved_date)
            write_json_locked(path, normalized)
            return {
                "scout_id": scout_id_norm,
                "as_of_date": resolved_date,
                "status": "SAVED",
                "message": "Macro cache updated.",
                "artifact_paths": [str(path)],
                "metrics": {
                    "regime": str(normalized.get("regime") or ""),
                    "dimension_count": len(dict(normalized.get("dimensions", {}) or {})),
                    "sector_count": len(dict(normalized.get("sectors", {}) or {})),
                },
            }

        if scout_id_norm == "earnings_options_prompt":
            parsed = self._extract_json_payload(payload_text)
            from cli.commands.earnings_options_prompt import _validate_payload

            normalized = _validate_payload(parsed)
            path = self._earnings_options_scout_path(resolved_date)
            write_json_locked(path, normalized)
            trending = list(normalized.get("trending", []) or [])
            return {
                "scout_id": scout_id_norm,
                "as_of_date": resolved_date,
                "status": "SAVED",
                "message": f"Earnings/options scout updated ({len(trending)} setups).",
                "artifact_paths": [str(path)],
                "metrics": {"setup_count": len(trending)},
            }

        if self._is_known_scout(scout_id_norm, as_of_date=resolved_date):
            raise OperatorGatewayError(f"Scout '{scout_id_norm}' is automatic and cannot be ingested manually.")
        raise OperatorGatewayNotFoundError(f"Unknown scout_id: {scout_id_norm}")

    def create_triage_intent(self, payload: Dict[str, Any], *, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
        self._assert_mutation_allowed(snapshot_validity=str(payload.get("snapshot_validity") or ""), now=now)
        try:
            return create_intent(config=self.config, now=now, **payload)
        except (TriageValidationError, TriageConflictError) as exc:
            raise OperatorGatewayError(str(exc)) from exc

    def undo_triage_intent(self, payload: Dict[str, Any], *, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
        self._assert_mutation_allowed(snapshot_validity="VALID", now=now)
        try:
            return undo_intent(config=self.config, now=now, **payload)
        except TriageConflictError as exc:
            raise OperatorGatewayBlockedError(str(exc)) from exc
        except TriageValidationError as exc:
            raise OperatorGatewayError(str(exc)) from exc

    def create_mirror_challenge(
        self,
        *,
        intent_id: str,
        payload: Optional[Dict[str, Any]] = None,
        now: Optional[dt.datetime] = None,
    ) -> Dict[str, Any]:
        self._assert_halt_inactive()
        repo = self._allocator_repository()
        if repo is None:
            raise OperatorGatewayError("Allocator repository unavailable.")
        now_utc = _as_utc(now)
        actor = str((payload or {}).get("created_by") or (payload or {}).get("user_id") or "operator-ui")
        ttl_seconds = float(self.config.get("operator_gateway_mirror_challenge_ttl_seconds", 300.0))
        try:
            challenge = repo.create_mirror_challenge(
                intent_id=intent_id,
                now_utc=now_utc,
                ttl_seconds=ttl_seconds,
                created_by=actor,
                allowed_statuses=(IntentStatus.VALIDATED,),
            )
        except MirrorIntentError as exc:
            raise self._as_gateway_error(exc) from exc

        challenge["status_message"] = humanize_allocator_status(
            status=str(challenge.get("status") or ""),
            reason_code="",
            reason="",
        )
        challenge["legal_consent_required"] = bool(
            self.config.get("operator_gateway_require_legal_consent", True)
        )
        challenge["status_dictionary_version"] = STATUS_DICTIONARY_VERSION
        return challenge

    def confirm_mirror_intent(
        self,
        *,
        intent_id: str,
        payload: Dict[str, Any],
        now: Optional[dt.datetime] = None,
    ) -> Dict[str, Any]:
        self._assert_halt_inactive()
        self._assert_legal_consent(payload=payload)
        repo = self._allocator_repository()
        if repo is None:
            raise OperatorGatewayError("Allocator repository unavailable.")

        try:
            adapter = build_broker_adapter(self.config)
        except BrokerAdapterDisabledError as exc:
            code = str(exc).split(":", 1)[0].strip().upper() or "BROKER_ADAPTER_DISABLED"
            raise OperatorGatewayBlockedError(f"{code}: broker adapter not configured.") from exc

        now_utc = _as_utc(now)
        try:
            result = repo.confirm_mirror_intent(
                intent_id=intent_id,
                challenge_id=str(payload.get("challenge_id") or ""),
                client_preview_hash=str(payload.get("client_preview_hash") or ""),
                user_id=str(payload.get("user_id") or "operator-ui"),
                interaction_type=str(payload.get("interaction_type") or "HOLD_TO_FOLLOW"),
                legal_version=str(payload.get("legal_version") or ""),
                now_utc=now_utc,
                allowed_statuses=(IntentStatus.VALIDATED,),
            )
        except MirrorIntentError as exc:
            raise self._as_gateway_error(exc) from exc

        intent = repo.get_intent(intent_id)
        if intent is None:
            raise OperatorGatewayError(f"Intent disappeared during mirror confirm: {intent_id}")

        broker_result = adapter.submit_order(
            BrokerOrderRequest(
                intent_id=intent.intent_id,
                symbol=intent.symbol,
                side=intent.side,
                target_notional_usd=float(intent.target_notional_usd),
                lane=intent.lane.value,
                consent_id=str(result.get("consent_id") or ""),
                challenge_id=str(result.get("challenge_id") or ""),
                requested_at_utc=now_utc,
            )
        )
        repo.mark_order_submitted(
            order_id=str(result.get("order_id") or ""),
            broker_order_id=str(broker_result.broker_order_id or ""),
            submitted_at_utc=broker_result.submitted_at_utc or now_utc,
            status=str(broker_result.submission_status or IntentStatus.SUBMITTED.value),
        )
        status_after = str(result.get("status_after") or "")
        reason_code = str(result.get("reason_code") or "")
        return {
            **result,
            "broker_submission": str(broker_result.submission_status or ""),
            "broker_order_id": str(broker_result.broker_order_id or ""),
            "broker_adapter": str(broker_result.adapter_name or ""),
            "status_message": humanize_allocator_status(
                status=status_after,
                reason_code=reason_code,
                reason="",
            ),
            "status_dictionary_version": STATUS_DICTIONARY_VERSION,
        }

    def get_mirror_intent_preview(
        self,
        *,
        intent_id: str,
        now: Optional[dt.datetime] = None,
    ) -> Dict[str, Any]:
        repo = self._allocator_repository()
        if repo is None:
            raise OperatorGatewayError("Allocator repository unavailable.")
        intent = repo.get_intent(intent_id)
        if intent is None:
            raise OperatorGatewayError(f"INTENT_NOT_FOUND: {intent_id}")

        with repo.connection() as conn:
            challenge = conn.execute(
                """
                SELECT challenge_id, preview_hash, issued_at_utc, expires_at_utc, used_at_utc
                FROM mirror_challenges
                WHERE intent_id = ?
                ORDER BY issued_at_utc DESC
                LIMIT 1
                """,
                (intent.intent_id,),
            ).fetchone()
        now_utc = _as_utc(now)
        drift = compute_portfolio_drift(
            config=self.config,
            now=now_utc,
            sensitivity=self.get_drift_sensitivity(),
        )
        challenge_payload: Dict[str, Any] = {}
        if challenge is not None:
            challenge_payload = {
                "challenge_id": str(challenge["challenge_id"] or ""),
                "preview_hash": str(challenge["preview_hash"] or ""),
                "issued_at_utc": str(challenge["issued_at_utc"] or ""),
                "expires_at_utc": str(challenge["expires_at_utc"] or ""),
                "used_at_utc": str(challenge["used_at_utc"] or ""),
            }
        comparison = build_symbol_alignment_delta(config=self.config, symbol=intent.symbol)
        return {
            "intent_id": intent.intent_id,
            "symbol": intent.symbol,
            "lane": intent.lane.value,
            "side": intent.side,
            "target_notional_usd": float(intent.target_notional_usd),
            "status": intent.status.value,
            "reason_code": intent.reason_code,
            "reason": intent.reason,
            "status_message": humanize_allocator_status(
                status=intent.status.value,
                reason_code=intent.reason_code,
                reason=intent.reason,
            ),
            "snapshot_id": intent.snapshot_id,
            "snapshot_hash_canonical": intent.snapshot_hash_canonical,
            "expires_at_utc": intent.expires_at_utc.isoformat(),
            "challenge": challenge_payload,
            "comparison": comparison,
            "portfolio_drift_pct": drift.get("portfolio_drift_pct"),
            "portfolio_drift_status": str(drift.get("portfolio_drift_status") or "UNKNOWN"),
            "portfolio_last_sync_utc": str(drift.get("portfolio_last_sync_utc") or ""),
            "portfolio_drift_message": str(drift.get("portfolio_drift_message") or ""),
            "status_dictionary_version": STATUS_DICTIONARY_VERSION,
        }

    def list_triage_status(self, *, since_minutes: int = 60, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
        intents = list_recent_intents(since_minutes=since_minutes, config=self.config, now=now)
        receipts = load_receipts(self.config).get("items", [])
        receipt_by_intent: Dict[str, Dict[str, Any]] = {}
        for row in receipts if isinstance(receipts, list) else []:
            if not isinstance(row, dict):
                continue
            intent_id = str(row.get("intent_id") or "")
            if not intent_id:
                continue
            previous = receipt_by_intent.get(intent_id)
            if previous is None or str(row.get("created_at_utc") or "") > str(previous.get("created_at_utc") or ""):
                receipt_by_intent[intent_id] = row

        out = []
        for intent in intents:
            item = dict(intent)
            latest_receipt = receipt_by_intent.get(str(intent.get("intent_id") or ""))
            if latest_receipt:
                item["latest_receipt"] = dict(latest_receipt)
            out.append(item)
        return {"since_minutes": int(since_minutes), "count": len(out), "items": out}

    def list_allocator_status(
        self,
        *,
        since_minutes: int = 60,
        now: Optional[dt.datetime] = None,
    ) -> Dict[str, Any]:
        repo = self._allocator_repository()
        if repo is None:
            return {"since_minutes": int(since_minutes), "count": 0, "items": []}

        now_utc = _as_utc(now)
        cutoff_utc = now_utc - dt.timedelta(minutes=max(1, int(since_minutes)))
        cutoff_iso = cutoff_utc.isoformat()

        with repo.connection() as conn:
            rows = conn.execute(
                """
                SELECT
                  intent_id,
                  symbol,
                  lane,
                  side,
                  status,
                  funding_source_status,
                  funding_available_at_utc,
                  funding_reservation_id,
                  execution_mode,
                  asset_class_id,
                  correlation_group_tag,
                  reason_code,
                  reason,
                  updated_at_utc
                FROM allocator_intents
                WHERE created_at_utc >= ?
                   OR updated_at_utc >= ?
                ORDER BY updated_at_utc DESC
                LIMIT 500
                """,
                (cutoff_iso, cutoff_iso),
            ).fetchall()

        items: List[Dict[str, Any]] = []
        for row in rows:
            status = str(row["status"] or "")
            reason_code = str(row["reason_code"] or "")
            reason = str(row["reason"] or "")
            items.append(
                {
                    "intent_id": str(row["intent_id"] or ""),
                    "symbol": str(row["symbol"] or ""),
                    "lane": str(row["lane"] or ""),
                    "side": str(row["side"] or ""),
                    "status": status,
                    "funding_source_status": str(row["funding_source_status"] or ""),
                    "funding_available_at_utc": str(row["funding_available_at_utc"] or ""),
                    "funding_reservation_id": str(row["funding_reservation_id"] or ""),
                    "execution_mode": str(row["execution_mode"] or ""),
                    "asset_class_id": str(row["asset_class_id"] or ""),
                    "correlation_group_tag": str(row["correlation_group_tag"] or ""),
                    "reason_code": reason_code,
                    "reason": reason,
                    "status_message": humanize_allocator_status(
                        status=status,
                        reason_code=reason_code,
                        reason=reason,
                    ),
                    "updated_at_utc": str(row["updated_at_utc"] or ""),
                }
            )
        return {
            "since_minutes": int(since_minutes),
            "count": len(items),
            "items": items,
            "status_dictionary_version": STATUS_DICTIONARY_VERSION,
        }

    def get_allocator_report_card(
        self,
        *,
        lookback_days: int = 7,
        now: Optional[dt.datetime] = None,
    ) -> Dict[str, Any]:
        repo = self._allocator_repository()
        if repo is None:
            now_utc = _as_utc(now)
            return {
                "as_of_utc": now_utc.isoformat(),
                "lookback_days": max(1, int(lookback_days)),
                "from_utc": (now_utc - dt.timedelta(days=max(1, int(lookback_days)))).isoformat(),
                "total_intents": 0,
                "pending_count": 0,
                "terminal_count": 0,
                "validated_count": 0,
                "rejected_count": 0,
                "validation_rate_pct": 0.0,
                "veto_rate_pct": 0.0,
                "status_counts": {},
                "lane_status_counts": [],
                "rejection_reason_counts": [],
                "recent_vetoes": [],
                "pending_funding_count": 0,
                "by_execution_mode": {},
                "status_dictionary_version": STATUS_DICTIONARY_VERSION,
            }
        report = build_allocator_report_card(
            repo=repo,
            lookback_days=max(1, int(lookback_days)),
            now_utc=_as_utc(now),
        )
        enriched_recent_vetoes: List[Dict[str, Any]] = []
        for row in list(report.get("recent_vetoes", [])):
            if not isinstance(row, dict):
                continue
            status = str(row.get("status") or "")
            reason_code = str(row.get("reason_code") or "")
            reason = str(row.get("reason") or "")
            enriched_recent_vetoes.append(
                {
                    **row,
                    "status_message": humanize_allocator_status(
                        status=status,
                        reason_code=reason_code,
                        reason=reason,
                    ),
                }
            )
        report["recent_vetoes"] = enriched_recent_vetoes
        report["status_dictionary_version"] = STATUS_DICTIONARY_VERSION
        return report

    def get_drift_sensitivity(self) -> Dict[str, float]:
        return load_drift_sensitivity(self.config)

    def update_drift_sensitivity(self, payload: Dict[str, Any]) -> Dict[str, float]:
        return save_drift_sensitivity(self.config, payload)

    def refresh_drift_snapshot(self, *, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
        now_utc = _as_utc(now)
        sensitivity = self.get_drift_sensitivity()
        drift = compute_portfolio_drift(config=self.config, now=now_utc, sensitivity=sensitivity)
        artifact = {
            **drift,
            "drift_sensitivity": sensitivity,
            "updated_at_utc": now_utc.isoformat(),
        }
        write_json_locked(self.drift_snapshot_path(), artifact)
        return artifact

    def get_drift_impact(self, *, max_items: int = 8, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
        now_utc = _as_utc(now)
        sensitivity = self.get_drift_sensitivity()
        return build_drift_impact(
            config=self.config,
            now=now_utc,
            sensitivity=sensitivity,
            max_items=max_items,
        )

    def activate_system_halt(self, *, reason: str, set_by: str = "operator", now: Optional[dt.datetime] = None) -> Dict[str, Any]:
        return set_system_halt(reason=reason, set_by=set_by, config=self.config, now=now)

    def clear_system_halt(self, *, cleared_by: str = "operator", now: Optional[dt.datetime] = None) -> Dict[str, Any]:
        return clear_system_halt(cleared_by=cleared_by, config=self.config, now=now)

    def _assert_mutation_allowed(self, *, snapshot_validity: str, now: Optional[dt.datetime] = None) -> None:
        validity = str(snapshot_validity or "").upper().strip()
        if validity != "VALID":
            raise OperatorGatewayBlockedError(f"Snapshot validity is {validity or 'UNKNOWN'}; mutations are blocked.")
        self._assert_halt_inactive()

        schedule = evaluate_schedule_guard(config=self.config, now=now)
        if str(schedule.get("schedule_status") or "UNKNOWN").upper() == "UNKNOWN":
            raise OperatorGatewayBlockedError(str(schedule.get("reason") or "Schedule unknown."))
        if not bool(schedule.get("commit_window_open")):
            raise OperatorGatewayBlockedError(
                f"Commit window closed: {schedule.get('reason', 'outside cutoff')}"
            )

    def _assert_halt_inactive(self) -> None:
        if is_hands_off_active(self.config):
            halt = load_system_halt(self.config)
            raise OperatorGatewayBlockedError(
                f"SYSTEM_HALT_ACTIVE: {halt.get('scope', 'HANDS_OFF')} {halt.get('reason', '')}".strip()
            )

    def _assert_legal_consent(self, *, payload: Dict[str, Any]) -> None:
        require_consent = bool(self.config.get("operator_gateway_require_legal_consent", True))
        if not require_consent:
            return
        if not bool(payload.get("legal_consent_active")):
            raise OperatorGatewayBlockedError("LEGAL_CONSENT_REQUIRED: legal consent confirmation missing.")
        legal_version = str(payload.get("legal_version") or "").strip()
        if not legal_version:
            raise OperatorGatewayBlockedError("LEGAL_CONSENT_REQUIRED: legal_version is required.")

    @staticmethod
    def _as_gateway_error(exc: MirrorIntentError) -> OperatorGatewayError:
        message = f"{exc.code}: {str(exc)}".strip()
        blocking_codes = {
            "CHALLENGE_EXPIRED",
            "CHALLENGE_ALREADY_USED",
            "CONFLICT_PREVIEW_HASH_MISMATCH",
            "CONFLICT_INTENT_CHANGED",
            "EXPIRED_INTENT",
            "INTENT_NOT_READY",
        }
        if exc.code in blocking_codes:
            return OperatorGatewayBlockedError(message)
        return OperatorGatewayError(message)

    def _build_bootstrap_alerts(
        self,
        *,
        schedule: Dict[str, Any],
        snapshot: Dict[str, Any],
        pending_created_count: int,
        allocator_pending_funding_count: int,
        drift: Optional[Dict[str, Any]] = None,
        non_model_exposure_count: int = 0,
    ) -> List[Dict[str, Any]]:
        alerts: List[Dict[str, Any]] = []

        schedule_status = str(schedule.get("schedule_status") or "").upper().strip()
        if schedule_status == "UNKNOWN":
            alerts.append(
                {
                    "code": "SCHEDULE_UNKNOWN",
                    "severity": "CRITICAL",
                    "title": "Schedule Unknown",
                    "message": str(schedule.get("reason") or "Execution schedule is unavailable."),
                    "blocking": True,
                }
            )

        if bool(schedule.get("halt_active")):
            alerts.append(
                {
                    "code": "SYSTEM_HALT_ACTIVE",
                    "severity": "CRITICAL",
                    "title": "System Halt Active",
                    "message": str(schedule.get("halt_reason") or "HANDS_OFF mode enabled."),
                    "blocking": True,
                }
            )

        validity = str(snapshot.get("validity") or "").upper().strip()
        if validity and validity != "VALID":
            alerts.append(
                {
                    "code": f"SNAPSHOT_{validity}",
                    "severity": "CRITICAL",
                    "title": "Snapshot Not Valid",
                    "message": "Latest dealflow snapshot is not valid for triage actions.",
                    "blocking": True,
                }
            )

        if not bool(schedule.get("commit_window_open")) and schedule_status != "UNKNOWN":
            alerts.append(
                {
                    "code": "COMMIT_WINDOW_CLOSED",
                    "severity": "WARNING",
                    "title": "Commit Window Closed",
                    "message": str(schedule.get("reason") or "Intent window is closed."),
                    "blocking": True,
                }
            )

        if pending_created_count > 0:
            alerts.append(
                {
                    "code": "PENDING_TRIAGE_INTENTS",
                    "severity": "INFO",
                    "title": "Pending Intents",
                    "message": f"{pending_created_count} intent(s) still pending terminal consumption.",
                    "blocking": False,
                }
            )

        if allocator_pending_funding_count > 0:
            alerts.append(
                {
                    "code": "ALLOCATOR_PENDING_FUNDING",
                    "severity": "INFO",
                    "title": "Funding Pending",
                    "message": (
                        f"{allocator_pending_funding_count} allocator intent(s) are waiting for settlement "
                        "or funding availability."
                    ),
                    "blocking": False,
                }
            )

        drift_status = str((drift or {}).get("portfolio_drift_status") or "UNKNOWN").upper()
        drift_message = str((drift or {}).get("portfolio_drift_message") or "").strip()
        if drift_status == "DISCONNECTED":
            alerts.append(
                {
                    "code": "PORTFOLIO_DISCONNECTED",
                    "severity": "WARNING",
                    "title": "Alignment Drift High",
                    "message": drift_message or "Portfolio drift is above alignment threshold.",
                    "blocking": False,
                }
            )
        elif drift_status == "UNKNOWN":
            alerts.append(
                {
                    "code": "PORTFOLIO_ALIGNMENT_UNKNOWN",
                    "severity": "INFO",
                    "title": "Alignment Unavailable",
                    "message": drift_message or "Connect broker sync to enable alignment pulse.",
                    "blocking": False,
                }
            )
        if int(non_model_exposure_count) > 0:
            alerts.append(
                {
                    "code": "NON_MODEL_EXPOSURE_DETECTED",
                    "severity": "WARNING",
                    "title": "Manual Exposure Detected",
                    "message": (
                        f"{int(non_model_exposure_count)} non-model position(s) detected. "
                        "Review drift impact."
                    ),
                    "blocking": False,
                }
            )

        return alerts

    def _make_stage(
        self,
        *,
        stage_id: str,
        label: str,
        status: str,
        summary: str,
        artifacts: List[str],
        metrics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        artifact_paths = [Path(path) for path in artifacts if str(path).strip()]
        updated_at = self._latest_artifact_timestamp(artifact_paths)
        return {
            "stage_id": stage_id,
            "label": label,
            "status": str(status or "UNKNOWN").upper().strip(),
            "summary": str(summary or "").strip(),
            "updated_at_utc": updated_at,
            "artifacts": artifacts,
            "metrics": dict(metrics or {}),
        }

    def _resolve_as_of_date(self, *, as_of_date: Optional[str] = None) -> str:
        candidate = str(as_of_date or "").strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", candidate):
            return candidate

        base = self._dealflow_base_dir()
        if base.exists():
            dated_dirs = sorted(
                [row.name for row in base.iterdir() if row.is_dir() and re.match(r"^\d{4}-\d{2}-\d{2}$", row.name)]
            )
            if dated_dirs:
                return dated_dirs[-1]

        queue_payload, _ = self._load_latest_research_queue()
        queue_date = str(queue_payload.get("date") or "").strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", queue_date):
            return queue_date
        return dt.date.today().isoformat()

    def _dealflow_base_dir(self) -> Path:
        return Path(str(self.config.get("operator_gateway_dealflow_base_dir", "eval_results/deal_flow")))

    def _dealflow_date_dir(self, as_of_date: str) -> Path:
        return self._dealflow_base_dir() / str(as_of_date).strip()

    def _eval_results_root(self) -> Path:
        return self._dealflow_base_dir().parent

    def _x_feed_base_dir(self) -> Path:
        return self._eval_results_root() / "x_feed"

    def _x_feed_date_dir(self, as_of_date: str) -> Path:
        return self._x_feed_base_dir() / str(as_of_date).strip()

    def _paper_execution_dir(self) -> Path:
        return self._eval_results_root() / "paper_execution"

    def _live_execution_dir(self) -> Path:
        return self._eval_results_root() / "live_execution"

    def _macro_cache_path(self, as_of_date: str) -> Path:
        return self._dealflow_base_dir() / f"macro_cache_{str(as_of_date).strip()}.json"

    def _earnings_options_scout_path(self, as_of_date: str) -> Path:
        return self._dealflow_base_dir() / f"earnings_options_scout_{str(as_of_date).strip()}.json"

    @staticmethod
    def _existing_artifact_strings(paths: List[Path]) -> List[str]:
        out: List[str] = []
        for path in paths:
            candidate = Path(path)
            if candidate.exists():
                out.append(str(candidate))
        return out

    @staticmethod
    def _latest_artifact_timestamp(paths: List[Path]) -> str:
        latest: Optional[Path] = None
        latest_mtime = -1.0
        for path in paths:
            candidate = Path(path)
            if not candidate.exists():
                continue
            mtime = float(candidate.stat().st_mtime)
            if mtime > latest_mtime:
                latest_mtime = mtime
                latest = candidate
        if latest is None:
            return ""
        return dt.datetime.fromtimestamp(latest_mtime, tz=dt.timezone.utc).isoformat()

    def _compute_x_feed_readiness(self, as_of_date: str) -> Dict[str, Any]:
        raw_dir = self._x_feed_date_dir(as_of_date) / "raw"
        completed_passes: set[int] = set()
        raw_archives: List[str] = []
        pass_file_re = re.compile(r"^pass_(\d{2})(?:_v\d+)?\.json$")

        if raw_dir.exists():
            for entry in sorted(raw_dir.iterdir()):
                if not entry.is_file():
                    continue
                match = pass_file_re.match(entry.name)
                if not match:
                    continue
                completed_passes.add(int(match.group(1)))
                raw_archives.append(str(entry))

        merged_path = self._x_feed_date_dir(as_of_date) / "merged.json"
        merged_payload = self._safe_read_json(merged_path) if merged_path.exists() else {}
        required_passes = self._x_feed_required_passes()
        missing_passes = [pass_num for pass_num in required_passes if pass_num not in completed_passes]
        ready = not missing_passes and merged_path.exists() and bool(merged_payload)
        return {
            "date": as_of_date,
            "required_passes": required_passes,
            "completed_passes": sorted(completed_passes),
            "missing_passes": missing_passes,
            "raw_archive_count": len(raw_archives),
            "raw_archives": raw_archives,
            "merged_exists": merged_path.exists(),
            "merged_path": str(merged_path),
            "merged_symbol_count": len(dict(merged_payload or {})),
            "ready": ready,
        }

    @staticmethod
    def _x_feed_required_passes() -> List[int]:
        try:
            from tradingagents.dealflow.sources.x_feed_manual import PASS_NUMBERS

            return [int(value) for value in PASS_NUMBERS]
        except Exception:
            return list(range(1, 16))

    def _analysis_report_paths(self, as_of_date: str, queue_items: List[Dict[str, Any]]) -> List[Path]:
        results_dir = Path(str(self.config.get("results_dir", "./results")))
        symbols: List[str] = []
        seen: set[str] = set()
        for row in queue_items:
            symbol = str((row or {}).get("symbol") or "").upper().strip()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            symbols.append(symbol)
        report_paths: List[Path] = []
        for symbol in symbols:
            candidate = results_dir / symbol / as_of_date / "analysis_report.json"
            if candidate.exists():
                report_paths.append(candidate)
        return report_paths

    def _build_scout_catalog(self, *, as_of_date: str) -> List[Dict[str, Any]]:
        date_dir = self._dealflow_date_dir(as_of_date)
        scout_audit_path = date_dir / "scout_audit.json"
        scout_audit = self._safe_read_json(scout_audit_path)
        x_feed = self._compute_x_feed_readiness(as_of_date)
        macro_path = self._macro_cache_path(as_of_date)
        macro_payload = self._safe_read_json(macro_path)
        earnings_path = self._earnings_options_scout_path(as_of_date)
        earnings_payload = self._safe_read_json(earnings_path)
        event_cards_path = date_dir / "event_cards.json"
        event_cards = self._safe_read_json_list(event_cards_path)
        coverage_path = date_dir / "coverage_precheck.json"
        coverage_payload = self._safe_read_json(coverage_path)

        breakout_count = int(((scout_audit.get("breakout") or {}).get("count", 0) or 0)
                             if isinstance(scout_audit, dict) else 0)
        insider_buy = len(list(((scout_audit.get("insider") or {}).get("buy_clusters", []) or []))
                         if isinstance(scout_audit, dict) else [])
        insider_sell = len(list(((scout_audit.get("insider") or {}).get("sell_clusters", []) or []))
                          if isinstance(scout_audit, dict) else [])
        technical_promoted = int(
            ((scout_audit.get("technical_ignition") or {}).get("promoted_count", 0) or 0)
            if isinstance(scout_audit, dict)
            else 0
        )
        earnings_promoted = len(list((earnings_payload.get("trending", []) or [])) if earnings_payload else [])
        macro_sectors = len(dict(macro_payload.get("sectors", {}) or {})) if macro_payload else 0
        x_completed = len(list(x_feed.get("completed_passes", []) or []))
        x_required = len(list(x_feed.get("required_passes", []) or []))

        scouts: List[Dict[str, Any]] = []
        x_status = "READY" if bool(x_feed.get("ready")) else ("INCOMPLETE" if x_completed > 0 else "MISSING")
        scouts.append(
            {
                "scout_id": "x_feed_manual",
                "label": "Manual X Feed",
                "category": "social",
                "mode": "manual",
                "status": x_status,
                "description": "15-pass Grok-assisted social discovery sweep with pass-level ingest.",
                "last_run_at_utc": self._latest_artifact_timestamp(
                    [self._x_feed_date_dir(as_of_date) / "merged.json", scout_audit_path]
                ),
                "metrics": {
                    "completed_passes": x_completed,
                    "required_passes": x_required,
                    "missing_passes": len(list(x_feed.get("missing_passes", []) or [])),
                    "merged_symbols": int(x_feed.get("merged_symbol_count", 0) or 0),
                },
                "artifacts": self._existing_artifact_strings(
                    [self._x_feed_date_dir(as_of_date) / "merged.json"]
                ),
                "actions": [
                    {
                        "action_id": "generate_prompt",
                        "label": "Get Prompt",
                        "kind": "prompt",
                        "requires_manual_input": False,
                    },
                    {
                        "action_id": "ingest_pass",
                        "label": "Ingest Grok Output",
                        "kind": "ingest",
                        "requires_manual_input": True,
                    },
                ],
            }
        )
        scouts.append(
            {
                "scout_id": "macro_prompt",
                "label": "Macro Regime Prompt",
                "category": "macro",
                "mode": "manual",
                "status": "READY" if macro_sectors > 0 else ("NO_DATA" if macro_path.exists() else "MISSING"),
                "description": "Manual macro prompt + ingest for 8 dimensions and 11 sectors.",
                "last_run_at_utc": self._latest_artifact_timestamp([macro_path]),
                "metrics": {
                    "regime": str(macro_payload.get("regime") or "") if macro_payload else "",
                    "sector_count": macro_sectors,
                },
                "artifacts": self._existing_artifact_strings([macro_path]),
                "actions": [
                    {
                        "action_id": "generate_prompt",
                        "label": "Get Prompt",
                        "kind": "prompt",
                        "requires_manual_input": False,
                    },
                    {
                        "action_id": "ingest_payload",
                        "label": "Ingest Grok Output",
                        "kind": "ingest",
                        "requires_manual_input": True,
                    },
                ],
            }
        )
        scouts.append(
            {
                "scout_id": "earnings_options_prompt",
                "label": "Earnings/Options Prompt",
                "category": "event",
                "mode": "manual",
                "status": "READY" if earnings_promoted > 0 else ("NO_DATA" if earnings_path.exists() else "MISSING"),
                "description": "Manual earnings/options setup prompt and cache ingest.",
                "last_run_at_utc": self._latest_artifact_timestamp([earnings_path]),
                "metrics": {"setup_count": earnings_promoted},
                "artifacts": self._existing_artifact_strings([earnings_path]),
                "actions": [
                    {
                        "action_id": "generate_prompt",
                        "label": "Get Prompt",
                        "kind": "prompt",
                        "requires_manual_input": False,
                    },
                    {
                        "action_id": "ingest_payload",
                        "label": "Ingest Grok Output",
                        "kind": "ingest",
                        "requires_manual_input": True,
                    },
                ],
            }
        )
        scouts.append(
            {
                "scout_id": "breakout_discovery",
                "label": "Breakout Discovery",
                "category": "technical",
                "mode": "automatic",
                "status": "OK" if breakout_count > 0 else ("NO_DATA" if scout_audit else "MISSING"),
                "description": "Automatic breakout scanner that enriches AKG prior to universe build.",
                "last_run_at_utc": self._latest_artifact_timestamp([scout_audit_path]),
                "metrics": {"breakout_count": breakout_count},
                "artifacts": self._existing_artifact_strings([scout_audit_path]),
                "actions": [],
            }
        )
        scouts.append(
            {
                "scout_id": "insider_cluster",
                "label": "Insider Cluster Scout",
                "category": "smart_money",
                "mode": "automatic",
                "status": (
                    "OK"
                    if (insider_buy + insider_sell) > 0
                    else ("NO_DATA" if scout_audit else "MISSING")
                ),
                "description": "Automatic Form 4 sweep producing insider buy/sell clusters.",
                "last_run_at_utc": self._latest_artifact_timestamp([scout_audit_path]),
                "metrics": {"buy_clusters": insider_buy, "sell_clusters": insider_sell},
                "artifacts": self._existing_artifact_strings([scout_audit_path]),
                "actions": [],
            }
        )
        scouts.append(
            {
                "scout_id": "technical_ignition",
                "label": "Technical Ignition Scout",
                "category": "technical",
                "mode": "automatic",
                "status": "OK" if technical_promoted > 0 else ("NO_DATA" if scout_audit else "MISSING"),
                "description": "Automatic KAMA/FVG-backed ignition promotion scanner.",
                "last_run_at_utc": self._latest_artifact_timestamp([scout_audit_path]),
                "metrics": {"promoted_count": technical_promoted},
                "artifacts": self._existing_artifact_strings([scout_audit_path]),
                "actions": [],
            }
        )
        scouts.append(
            {
                "scout_id": "scenario_compiler",
                "label": "Scout Compiler Sidecar",
                "category": "compiler",
                "mode": "automatic",
                "status": (
                    "OK"
                    if len(event_cards) > 0
                    else ("NO_DATA" if coverage_path.exists() else "MISSING")
                ),
                "description": "Compiles scout evidence into event cards and coverage precheck.",
                "last_run_at_utc": self._latest_artifact_timestamp([event_cards_path, coverage_path]),
                "metrics": {
                    "event_card_count": len(event_cards),
                    "complete_count": int(coverage_payload.get("complete_count", 0) or 0),
                    "partial_count": int(coverage_payload.get("partial_count", 0) or 0),
                    "missing_count": int(coverage_payload.get("missing_count", 0) or 0),
                },
                "artifacts": self._existing_artifact_strings([event_cards_path, coverage_path]),
                "actions": [],
            }
        )
        return scouts

    def _is_known_scout(self, scout_id: str, *, as_of_date: str) -> bool:
        return any(str(row.get("scout_id") or "") == scout_id for row in self._build_scout_catalog(as_of_date=as_of_date))

    def _find_scout(self, *, scout_id: str, as_of_date: str) -> Dict[str, Any]:
        target = str(scout_id or "").strip().lower()
        for scout in self._build_scout_catalog(as_of_date=as_of_date):
            if str(scout.get("scout_id") or "").strip().lower() == target:
                return scout
        raise OperatorGatewayNotFoundError(f"Unknown scout_id: {target}")

    def _build_x_feed_prompt(
        self,
        *,
        as_of_date: str,
        pass_num: Optional[int] = None,
    ) -> Tuple[str, int, str, List[Dict[str, Any]]]:
        from tradingagents.dealflow.sources.x_feed_manual import generate_prompts

        prompts = list(generate_prompts(as_of_date=as_of_date))
        if not prompts:
            raise OperatorGatewayError("No x-feed prompts available.")
        prompt_parts = [
            {"pass_num": int(pnum), "label": str(label)}
            for pnum, label, _ in prompts
        ]
        effective_pass = int(pass_num or 1)
        for pnum, label, prompt in prompts:
            if int(pnum) == effective_pass:
                return str(prompt), int(pnum), str(label), prompt_parts
        raise OperatorGatewayError(
            f"Invalid pass_num={effective_pass}. Valid range is 1-{len(prompts)}."
        )

    @staticmethod
    def _build_macro_prompt(as_of_date: str) -> str:
        from cli.commands.macro_prompt import _MACRO_PROMPT_TEMPLATE

        return str(_MACRO_PROMPT_TEMPLATE).replace("__DATE__", as_of_date)

    @staticmethod
    def _build_earnings_options_prompt(as_of_date: str) -> str:
        from cli.commands.earnings_options_prompt import _PROMPT_TEMPLATE

        return str(_PROMPT_TEMPLATE).replace("__DATE__", as_of_date)

    @staticmethod
    def _extract_json_payload(raw_payload: str) -> Dict[str, Any]:
        from tradingagents.dealflow.sources.social_news import _extract_json_payload

        parsed = _extract_json_payload(raw_payload)
        if not isinstance(parsed, dict):
            raise OperatorGatewayError("Invalid JSON payload.")
        return parsed

    def _load_latest_research_queue(self) -> Tuple[Dict[str, Any], Optional[Path]]:
        queue_path = self._resolve_latest_research_queue_path()
        if queue_path is not None and queue_path.exists():
            return self._safe_read_json(queue_path), queue_path
        return {}, None

    def _resolve_latest_research_queue_path(self) -> Optional[Path]:
        configured = str(self.config.get("operator_gateway_research_queue_path", "")).strip()
        if configured:
            path = Path(configured)
            if path.exists():
                return path

        base = Path(str(self.config.get("operator_gateway_dealflow_base_dir", "eval_results/deal_flow")))
        latest_path = base / "latest_research_queue.json"
        if latest_path.exists():
            return latest_path

        dated = sorted(base.glob("*/research_queue.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if dated:
            return dated[0]
        return None

    def _load_analysis_report(
        self,
        *,
        symbol: str,
        analysis_date: str,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Path]]:
        results_dir = Path(str(self.config.get("results_dir", "./results")))
        symbol_dir = results_dir / symbol
        if analysis_date:
            target = symbol_dir / analysis_date / "analysis_report.json"
            if target.exists():
                return self._safe_read_json(target), target

        candidates = sorted(symbol_dir.glob("*/analysis_report.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            return self._safe_read_json(candidates[0]), candidates[0]
        return None, None

    @staticmethod
    def _find_queue_item(*, queue_payload: Dict[str, Any], symbol: str) -> Optional[Dict[str, Any]]:
        rows = queue_payload.get("items", [])
        if not isinstance(rows, list):
            return None
        target = str(symbol or "").upper().strip()
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("symbol") or "").upper().strip() == target:
                return dict(row)
        return None

    def _allocator_db_path(self) -> Path:
        configured = str(self.config.get("operator_gateway_allocator_db_path", "")).strip()
        if configured:
            return Path(configured)
        return Path("eval_results/control/capital_allocator.db")

    def regime_override_path(self) -> Path:
        configured = str(self.config.get("operator_gateway_allocator_regime_override_path", "")).strip()
        if configured:
            return Path(configured)
        return Path("eval_results/control/allocator_regime_override.json")

    def drift_snapshot_path(self) -> Path:
        configured = str(self.config.get("operator_gateway_drift_snapshot_path", "")).strip()
        if configured:
            return Path(configured)
        return Path("eval_results/control/drift_snapshot.json")

    def _allocator_repository(self) -> Optional[SQLiteAllocatorRepository]:
        path = self._allocator_db_path()
        if not path.exists():
            return None
        repo = SQLiteAllocatorRepository(path)
        try:
            repo.initialize()
        except Exception:
            return None
        return repo

    @staticmethod
    def _safe_read_json(path: Path) -> Dict[str, Any]:
        try:
            payload = json.loads(path.read_text())
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _safe_read_json_list(path: Path) -> List[Dict[str, Any]]:
        try:
            payload = json.loads(path.read_text())
        except Exception:
            return []
        if not isinstance(payload, list):
            return []
        return [dict(row) for row in payload if isinstance(row, dict)]


def _as_utc(value: Optional[dt.datetime]) -> dt.datetime:
    if value is None:
        return dt.datetime.now(dt.timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _file_fingerprint(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return {"exists": False}
    candidate = Path(path)
    if not candidate.exists():
        return {"exists": False, "path": str(candidate)}
    stat = candidate.stat()
    return {
        "exists": True,
        "path": str(candidate),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }
