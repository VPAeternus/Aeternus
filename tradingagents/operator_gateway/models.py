"""Pydantic models for operator gateway API."""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ScheduleResponse(BaseModel):
    schedule_status: str
    run_state: str
    active_run_id: str
    next_run_at_utc_actual: str
    queue_run_id_target: str
    heartbeat_seq: int
    heartbeat_fresh: bool
    heartbeat_age_seconds: Optional[float]
    clock_offset_seconds: Optional[float]
    commit_cutoff_at_utc: str
    seconds_to_next_run: Optional[float]
    commit_window_open: bool
    reason: str
    halt_active: bool = False
    halt_reason: str = ""


class SnapshotEnvelope(BaseModel):
    snapshot_id: str
    snapshot_hash_canonical: str
    snapshot_hash_raw: str
    queue_run_id: str
    as_of_date: str
    generated_at_utc: str
    validity: Literal["VALID", "STALE", "INVALID"]
    stale_reasons: List[str] = Field(default_factory=list)
    triage_enabled: bool = False


class CandidateDTO(BaseModel):
    symbol: str
    lane: str
    score: int
    confidence: int
    thesis_summary: str
    risk_flags: List[str]
    quality_tier: str
    snapshot_id: str
    queue_id: str
    selected_for_deep: bool
    research_playbook: str


class DealflowSummaryDTO(BaseModel):
    run_id: str
    date: str
    total_candidates: int
    selected_for_deep: int
    lane_counts: Dict[str, int]
    top_symbols: List[str]


class DealflowFeedResponse(BaseModel):
    snapshot: SnapshotEnvelope
    summary: DealflowSummaryDTO
    candidates: List[CandidateDTO]


class MissionControlStageDTO(BaseModel):
    stage_id: str
    label: str
    status: str
    summary: str = ""
    updated_at_utc: str = ""
    artifacts: List[str] = Field(default_factory=list)
    metrics: Dict[str, object] = Field(default_factory=dict)


class MissionControlResponse(BaseModel):
    as_of_date: str
    generated_at_utc: str
    pipeline_state: str
    stages: List[MissionControlStageDTO]
    blockers: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


class ScoutActionDTO(BaseModel):
    action_id: str
    label: str
    kind: str
    requires_manual_input: bool = False


class ScoutDTO(BaseModel):
    scout_id: str
    label: str
    category: str
    mode: str
    status: str
    description: str
    last_run_at_utc: str = ""
    metrics: Dict[str, object] = Field(default_factory=dict)
    artifacts: List[str] = Field(default_factory=list)
    actions: List[ScoutActionDTO] = Field(default_factory=list)


class ScoutInventoryResponse(BaseModel):
    as_of_date: str
    total_scouts: int
    scouts: List[ScoutDTO]


class ScoutDetailResponse(BaseModel):
    as_of_date: str
    scout: ScoutDTO
    prompt_text: str = ""
    prompt_parts: List[Dict[str, object]] = Field(default_factory=list)
    ingest_schema: Dict[str, object] = Field(default_factory=dict)
    notes: List[str] = Field(default_factory=list)


class ScoutPromptResponse(BaseModel):
    scout_id: str
    as_of_date: str
    pass_num: Optional[int] = None
    prompt_text: str
    copy_hint: str = ""


class ScoutIngestRequest(BaseModel):
    as_of_date: Optional[str] = None
    pass_num: Optional[int] = None
    raw_payload: str


class ScoutIngestResponse(BaseModel):
    scout_id: str
    as_of_date: str
    status: str
    message: str
    artifact_paths: List[str] = Field(default_factory=list)
    metrics: Dict[str, object] = Field(default_factory=dict)


class CandidateDetailResponse(BaseModel):
    snapshot: SnapshotEnvelope
    candidate: CandidateDTO
    found: bool
    analysis_available: bool
    analysis: Dict[str, object]
    evidence: Dict[str, object]


class AlertDTO(BaseModel):
    code: str
    severity: Literal["INFO", "WARNING", "CRITICAL"]
    title: str
    message: str
    blocking: bool = False


class DriftSensitivityResponse(BaseModel):
    amber_threshold_pct: float
    red_threshold_pct: float


class DriftSensitivityRequest(BaseModel):
    amber_threshold_pct: float
    red_threshold_pct: float


class BootstrapResponse(BaseModel):
    server_time_utc: str
    schedule: ScheduleResponse
    snapshot: SnapshotEnvelope
    summary: DealflowSummaryDTO
    top_candidates: List[CandidateDTO]
    pending_created_count: int
    pending_total_count: int
    allocator_pending_funding_count: int = 0
    allocator_pending_count: int = 0
    portfolio_drift_pct: Optional[float] = None
    portfolio_drift_status: str = "UNKNOWN"
    portfolio_last_sync_utc: str = ""
    portfolio_drift_message: str = ""
    portfolio_non_model_exposure_count: int = 0
    drift_sensitivity: DriftSensitivityResponse = Field(
        default_factory=lambda: DriftSensitivityResponse(amber_threshold_pct=5.0, red_threshold_pct=15.0)
    )
    alerts: List[AlertDTO] = Field(default_factory=list)


class TriageIntentCreateRequest(BaseModel):
    action: Literal["APPROVE", "DEFER", "BLOCK"]
    symbol: str
    queue_id: str
    target_queue_run_id: str
    snapshot_id: str
    snapshot_hash_canonical: str
    snapshot_hash_raw: str
    snapshot_validity: Literal["VALID", "STALE", "INVALID"] = "VALID"
    snapshot_price: Optional[float] = None
    regime_label_at_snapshot: str = ""
    thesis_tags: List[str] = Field(default_factory=list)
    operator_note: str = ""
    created_by: str = "operator"


class TriageUndoRequest(BaseModel):
    intent_id: str
    last_known_record_hash: str
    actor: str = "operator"


class TriageStatusResponse(BaseModel):
    since_minutes: int
    count: int
    items: List[dict]


class AllocatorIntentDTO(BaseModel):
    intent_id: str
    symbol: str
    lane: str
    side: str
    status: str
    funding_source_status: str
    funding_available_at_utc: str = ""
    funding_reservation_id: str = ""
    execution_mode: str = ""
    asset_class_id: str = ""
    correlation_group_tag: str = ""
    reason_code: str = ""
    reason: str = ""
    status_message: str = ""
    updated_at_utc: str = ""


class AllocatorStatusResponse(BaseModel):
    since_minutes: int
    count: int
    items: List[AllocatorIntentDTO]
    status_dictionary_version: str = ""


class LaneStatusCountDTO(BaseModel):
    lane: str
    status: str
    count: int
    avg_target_notional_usd: float


class RejectionReasonCountDTO(BaseModel):
    reason_code: str
    count: int


class AllocatorRecentVetoDTO(BaseModel):
    intent_id: str
    symbol: str
    lane: str
    side: str
    status: str
    reason_code: str = ""
    reason: str = ""
    status_message: str = ""
    updated_at_utc: str = ""


class AllocatorReportCardResponse(BaseModel):
    as_of_utc: str
    lookback_days: int
    from_utc: str
    total_intents: int
    pending_count: int
    terminal_count: int
    validated_count: int
    rejected_count: int
    validation_rate_pct: float
    veto_rate_pct: float
    status_counts: Dict[str, int]
    lane_status_counts: List[LaneStatusCountDTO]
    rejection_reason_counts: List[RejectionReasonCountDTO]
    recent_vetoes: List[AllocatorRecentVetoDTO]
    pending_funding_count: int
    by_execution_mode: Dict[str, int]
    status_dictionary_version: str = ""


class MirrorChallengeRequest(BaseModel):
    user_id: str = "operator-ui"
    created_by: str = "operator-ui"


class MirrorChallengeResponse(BaseModel):
    intent_id: str
    challenge_id: str
    preview_hash: str
    issued_at_utc: str
    expires_at_utc: str
    status: str
    status_message: str
    symbol: str
    side: str
    target_notional_usd: float
    legal_consent_required: bool
    status_dictionary_version: str = ""


class MirrorConfirmRequest(BaseModel):
    challenge_id: str
    client_preview_hash: str
    user_id: str = "operator-ui"
    interaction_type: str = "HOLD_TO_FOLLOW"
    legal_version: str = ""
    legal_consent_active: bool = False


class MirrorConfirmResponse(BaseModel):
    intent_id: str
    challenge_id: str
    consent_id: str
    consent_hash: str
    status_before: str
    status_after: str
    status_message: str
    confirmed_at_utc: str
    reason_code: str
    order_id: str
    broker_submission: str = ""
    broker_order_id: str = ""
    broker_adapter: str = ""
    status_dictionary_version: str = ""


class MirrorChallengeState(BaseModel):
    challenge_id: str = ""
    preview_hash: str = ""
    issued_at_utc: str = ""
    expires_at_utc: str = ""
    used_at_utc: str = ""


class MirrorIntentComparison(BaseModel):
    available: bool = False
    current_weight_pct: Optional[float] = None
    target_weight_pct: Optional[float] = None
    delta_weight_pct: Optional[float] = None


class DriftImpactItem(BaseModel):
    symbol: str
    current_weight_pct: float
    target_weight_pct: float
    delta_weight_pct: float
    classification: str


class DriftImpactResponse(BaseModel):
    available: bool
    portfolio_drift_pct: Optional[float] = None
    portfolio_drift_status: str = "UNKNOWN"
    last_sync_utc: str = ""
    non_model_exposure_count: int = 0
    non_model_symbols: List[str] = Field(default_factory=list)
    items: List[DriftImpactItem] = Field(default_factory=list)
    message: str = ""


class MirrorIntentPreviewResponse(BaseModel):
    intent_id: str
    symbol: str
    lane: str
    side: str
    target_notional_usd: float
    status: str
    reason_code: str = ""
    reason: str = ""
    status_message: str = ""
    snapshot_id: str
    snapshot_hash_canonical: str
    expires_at_utc: str
    challenge: MirrorChallengeState = Field(default_factory=MirrorChallengeState)
    comparison: MirrorIntentComparison = Field(default_factory=MirrorIntentComparison)
    portfolio_drift_pct: Optional[float] = None
    portfolio_drift_status: str = "UNKNOWN"
    portfolio_last_sync_utc: str = ""
    portfolio_drift_message: str = ""
    status_dictionary_version: str = ""


class RegimeShockRequest(BaseModel):
    regime: Literal["NORMAL", "STRESS", "SHOCK", "CRISIS"]
    reason: str = ""
    source: str = "operator"


class RegimeShockResponse(BaseModel):
    regime: str
    source: str
    reason: str
    updated_at_utc: str
    override_path: str


class SystemHaltRequest(BaseModel):
    reason: str
    set_by: str = "operator"


class SystemHaltClearRequest(BaseModel):
    cleared_by: str = "operator"
