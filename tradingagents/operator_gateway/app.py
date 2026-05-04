"""FastAPI app exposing operator control-plane endpoints."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .controller import SystemController
from .models import (
    AllocatorReportCardResponse,
    AllocatorStatusResponse,
    BootstrapResponse,
    CandidateDetailResponse,
    DealflowFeedResponse,
    DriftImpactResponse,
    DriftSensitivityRequest,
    DriftSensitivityResponse,
    MissionControlResponse,
    MirrorChallengeRequest,
    MirrorChallengeResponse,
    MirrorConfirmRequest,
    MirrorConfirmResponse,
    MirrorIntentPreviewResponse,
    RegimeShockRequest,
    RegimeShockResponse,
    ScheduleResponse,
    ScoutDetailResponse,
    ScoutIngestRequest,
    ScoutIngestResponse,
    ScoutInventoryResponse,
    ScoutPromptResponse,
    SystemHaltClearRequest,
    SystemHaltRequest,
    TriageIntentCreateRequest,
    TriageStatusResponse,
    TriageUndoRequest,
)
from .service import (
    OperatorGatewayBlockedError,
    OperatorGatewayError,
    OperatorGatewayNotFoundError,
    OperatorGatewayService,
)
from tradingagents.graph.paper_execution import close_all_positions

logger = logging.getLogger(__name__)


def create_app(config: Optional[Dict[str, Any]] = None) -> FastAPI:
    effective_config = dict(config or {})
    service = OperatorGatewayService(config=effective_config)
    controller = SystemController(service=service)
    app = FastAPI(title="Aeternus Operator Gateway", version="0.1.0")
    cors_origins = _parse_cors_origins(effective_config)
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    auth_header_name = str(effective_config.get("operator_gateway_api_key_header", "X-Aeternus-Key")).strip()
    auth_key = str(effective_config.get("operator_gateway_api_key", "")).strip()
    enforce_auth = bool(effective_config.get("operator_gateway_enforce_api_key", False))

    @app.middleware("http")
    async def _auth_guard(request: Request, call_next):
        if (
            enforce_auth
            and request.url.path.startswith("/ops")
            and request.method.upper() != "OPTIONS"
        ):
            provided = str(request.headers.get(auth_header_name) or "").strip()
            if not auth_key or provided != auth_key:
                return JSONResponse(
                    status_code=401,
                    content={
                        "detail": f"Missing or invalid API key header: {auth_header_name}",
                    },
                )
        return await call_next(request)

    @app.get("/health")
    def get_health() -> Dict[str, str]:
        return {"status": "ok"}

    @app.get("/ops/schedule", response_model=ScheduleResponse)
    def get_schedule() -> Dict[str, Any]:
        return controller.get_schedule()

    @app.get("/ops/dealflow", response_model=DealflowFeedResponse)
    def get_dealflow(limit: int = 0) -> Dict[str, Any]:
        return controller.get_dealflow_feed(limit=limit if limit > 0 else None)

    @app.get("/ops/bootstrap", response_model=BootstrapResponse)
    def get_bootstrap(request: Request, response: Response) -> Dict[str, Any] | Response:
        etag = controller.get_bootstrap_etag()
        if _if_none_match_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=304, headers={"ETag": _quote_etag(etag)})
        payload = controller.get_bootstrap_data()
        response.headers["ETag"] = _quote_etag(etag)
        return payload

    @app.get("/ops/mission-control", response_model=MissionControlResponse)
    def get_mission_control(date: str = "") -> Dict[str, Any]:
        return controller.get_mission_control(as_of_date=(date or "").strip() or None)

    @app.get("/ops/scouts", response_model=ScoutInventoryResponse)
    def get_scout_inventory(date: str = "") -> Dict[str, Any]:
        return controller.get_scout_inventory(as_of_date=(date or "").strip() or None)

    @app.get("/ops/scouts/{scout_id}", response_model=ScoutDetailResponse)
    def get_scout_detail(scout_id: str, date: str = "", pass_num: int = 0) -> Dict[str, Any]:
        try:
            return controller.get_scout_detail(
                scout_id=scout_id,
                as_of_date=(date or "").strip() or None,
                pass_num=int(pass_num) if int(pass_num or 0) > 0 else None,
            )
        except OperatorGatewayNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except OperatorGatewayError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/ops/scouts/{scout_id}/prompt", response_model=ScoutPromptResponse)
    def get_scout_prompt(scout_id: str, date: str = "", pass_num: int = 0) -> Dict[str, Any]:
        try:
            return controller.get_scout_prompt(
                scout_id=scout_id,
                as_of_date=(date or "").strip() or None,
                pass_num=int(pass_num) if int(pass_num or 0) > 0 else None,
            )
        except OperatorGatewayNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except OperatorGatewayError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/ops/scouts/{scout_id}/ingest", response_model=ScoutIngestResponse)
    def post_scout_ingest(scout_id: str, request: ScoutIngestRequest) -> Dict[str, Any]:
        try:
            return controller.ingest_scout_payload(
                scout_id=scout_id,
                as_of_date=request.as_of_date,
                pass_num=request.pass_num,
                raw_payload=request.raw_payload,
            )
        except OperatorGatewayNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except OperatorGatewayError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/ops/settings/drift-sensitivity", response_model=DriftSensitivityResponse)
    def get_drift_sensitivity() -> Dict[str, Any]:
        return controller.get_drift_sensitivity()

    @app.post("/ops/settings/drift-sensitivity", response_model=DriftSensitivityResponse)
    def post_drift_sensitivity(request: DriftSensitivityRequest) -> Dict[str, Any]:
        return controller.update_drift_sensitivity(request.model_dump())

    @app.get("/ops/drift-impact", response_model=DriftImpactResponse)
    def get_drift_impact(max_items: int = 8) -> Dict[str, Any]:
        return controller.get_drift_impact(max_items=max(1, int(max_items)))

    @app.get("/ops/candidates/{symbol}", response_model=CandidateDetailResponse)
    def get_candidate(symbol: str) -> Dict[str, Any]:
        return controller.get_candidate_detail(symbol=symbol)

    @app.post("/ops/triage-intent")
    def post_triage_intent(request: TriageIntentCreateRequest) -> Dict[str, Any]:
        try:
            return controller.create_triage_intent(request.model_dump())
        except OperatorGatewayBlockedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except OperatorGatewayError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/ops/triage-intent/undo")
    def post_triage_undo(request: TriageUndoRequest) -> Dict[str, Any]:
        try:
            return controller.undo_triage_intent(request.model_dump())
        except OperatorGatewayBlockedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except OperatorGatewayError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/ops/mirror-intents/{intent_id}/challenge", response_model=MirrorChallengeResponse)
    def post_mirror_challenge(intent_id: str, request: MirrorChallengeRequest) -> Dict[str, Any]:
        try:
            return controller.create_mirror_challenge(intent_id=intent_id, payload=request.model_dump())
        except OperatorGatewayBlockedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except OperatorGatewayError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/ops/mirror-intents/{intent_id}", response_model=MirrorIntentPreviewResponse)
    def get_mirror_intent_preview(intent_id: str) -> Dict[str, Any]:
        try:
            return controller.get_mirror_intent_preview(intent_id=intent_id)
        except OperatorGatewayBlockedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except OperatorGatewayError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/ops/mirror-intents/{intent_id}/confirm", response_model=MirrorConfirmResponse)
    def post_mirror_confirm(intent_id: str, request: MirrorConfirmRequest) -> Dict[str, Any]:
        try:
            return controller.confirm_mirror_intent(intent_id=intent_id, payload=request.model_dump())
        except OperatorGatewayBlockedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except OperatorGatewayError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/ops/intent/{intent_id}/confirm", response_model=MirrorConfirmResponse)
    def post_intent_confirm_alias(intent_id: str, request: MirrorConfirmRequest) -> Dict[str, Any]:
        try:
            return controller.confirm_mirror_intent(intent_id=intent_id, payload=request.model_dump())
        except OperatorGatewayBlockedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except OperatorGatewayError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/ops/triage-intents/status", response_model=TriageStatusResponse)
    def get_triage_status(since_minutes: int = 60) -> Dict[str, Any]:
        return controller.list_triage_status(since_minutes=since_minutes)

    @app.get("/ops/allocator-intents/status", response_model=AllocatorStatusResponse)
    def get_allocator_status(since_minutes: int = 60) -> Dict[str, Any]:
        return controller.list_allocator_status(since_minutes=since_minutes)

    @app.get("/ops/allocator/report-card", response_model=AllocatorReportCardResponse)
    def get_allocator_report_card(lookback_days: int = 7) -> Dict[str, Any]:
        return controller.allocator_report_card(lookback_days=lookback_days)

    @app.post("/ops/system-halt")
    def post_system_halt(request: SystemHaltRequest) -> Dict[str, Any]:
        logger.warning("System halt ACTIVATED: reason=%r set_by=%r", request.reason, request.set_by)
        return controller.activate_system_halt(reason=request.reason, set_by=request.set_by)

    @app.post("/ops/system-halt/clear")
    def post_system_halt_clear(request: SystemHaltClearRequest) -> Dict[str, Any]:
        logger.warning("System halt CLEARED by %r", request.cleared_by)
        return controller.clear_system_halt(cleared_by=request.cleared_by)

    @app.post("/ops/system/shock", response_model=RegimeShockResponse)
    def post_system_shock(request: RegimeShockRequest) -> Dict[str, Any]:
        return controller.inject_regime_shock(
            regime=request.regime,
            reason=request.reason,
            source=request.source or "operator",
        )

    @app.post("/ops/panic-liquidate")
    async def ops_panic_liquidate(request: Request):
        """EMERGENCY: Cancel all orders and liquidate all positions."""
        mode = request.app.state.config.get("execution_broker_mode", "paper") if hasattr(request.app.state, "config") else effective_config.get("execution_broker_mode", "paper")
        try:
            result = close_all_positions(mode=mode, cancel_orders_first=True)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        return result

    drift_enabled = bool(effective_config.get("operator_gateway_drift_background_enabled", True))
    drift_interval_seconds = max(
        5.0,
        float(effective_config.get("operator_gateway_drift_background_interval_seconds", 30.0)),
    )

    @app.on_event("startup")
    async def _startup_validate_auth():
        if enforce_auth and not auth_key:
            raise RuntimeError(
                "operator_gateway_enforce_api_key is true but operator_gateway_api_key is not configured. "
                "Set operator_gateway_api_key via config or environment variable."
            )

    @app.on_event("startup")
    async def _startup_drift_background():
        logger.info("Aeternus Operator Gateway started (drift_enabled=%s)", drift_enabled)
        if not drift_enabled:
            return
        stop_event = asyncio.Event()
        app.state._drift_stop_event = stop_event

        async def _drift_loop():
            while not stop_event.is_set():
                try:
                    controller.refresh_drift_snapshot()
                except Exception:
                    # Drift snapshot is advisory only; never crash gateway startup loop.
                    pass
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=drift_interval_seconds)
                except asyncio.TimeoutError:
                    continue

        app.state._drift_task = asyncio.create_task(_drift_loop())

    @app.on_event("shutdown")
    async def _shutdown_drift_background():
        stop_event = getattr(app.state, "_drift_stop_event", None)
        task = getattr(app.state, "_drift_task", None)
        if stop_event is not None:
            stop_event.set()
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    return app


def _parse_cors_origins(config: Dict[str, Any]) -> list[str]:
    raw = str(config.get("operator_gateway_cors_origins", "")).strip()
    if not raw:
        return []
    if raw == "*":
        return ["*"]
    return [item.strip() for item in raw.split(",") if item.strip()]


def _quote_etag(etag: str) -> str:
    return f"\"{etag}\""


def _if_none_match_matches(if_none_match_header: Optional[str], etag: str) -> bool:
    if not if_none_match_header:
        return False
    target = etag.strip().strip("\"")
    tokens = [item.strip().strip("\"") for item in str(if_none_match_header).split(",") if item.strip()]
    return "*" in tokens or target in tokens


app = create_app()
