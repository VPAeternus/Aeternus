export type AlertSeverity = "INFO" | "WARNING" | "CRITICAL";

export interface ScheduleResponse {
  schedule_status: string;
  run_state: string;
  active_run_id: string;
  next_run_at_utc_actual: string;
  queue_run_id_target: string;
  heartbeat_seq: number;
  heartbeat_fresh: boolean;
  heartbeat_age_seconds: number | null;
  clock_offset_seconds: number | null;
  commit_cutoff_at_utc: string;
  seconds_to_next_run: number | null;
  commit_window_open: boolean;
  reason: string;
  halt_active: boolean;
  halt_reason: string;
}

export interface SnapshotEnvelope {
  snapshot_id: string;
  snapshot_hash_canonical: string;
  snapshot_hash_raw: string;
  queue_run_id: string;
  as_of_date: string;
  generated_at_utc: string;
  validity: "VALID" | "STALE" | "INVALID";
  stale_reasons: string[];
  triage_enabled: boolean;
}

export interface CandidateDTO {
  symbol: string;
  lane: string;
  score: number;
  confidence: number;
  thesis_summary: string;
  risk_flags: string[];
  quality_tier: string;
  snapshot_id: string;
  queue_id: string;
  selected_for_deep: boolean;
  research_playbook: string;
}

export interface DealflowSummaryDTO {
  run_id: string;
  date: string;
  total_candidates: number;
  selected_for_deep: number;
  lane_counts: Record<string, number>;
  top_symbols: string[];
}

export interface AlertDTO {
  code: string;
  severity: AlertSeverity;
  title: string;
  message: string;
  blocking: boolean;
}

export interface BootstrapResponse {
  server_time_utc: string;
  schedule: ScheduleResponse;
  snapshot: SnapshotEnvelope;
  summary: DealflowSummaryDTO;
  top_candidates: CandidateDTO[];
  pending_created_count: number;
  pending_total_count: number;
  allocator_pending_funding_count: number;
  allocator_pending_count: number;
  portfolio_drift_pct: number | null;
  portfolio_drift_status: string;
  portfolio_last_sync_utc: string;
  portfolio_drift_message: string;
  drift_sensitivity: {
    amber_threshold_pct: number;
    red_threshold_pct: number;
  };
  alerts: AlertDTO[];
}

export type TriageAction = "APPROVE" | "DEFER" | "BLOCK";

export interface TriageIntentCreateRequest {
  action: TriageAction;
  symbol: string;
  queue_id: string;
  target_queue_run_id: string;
  snapshot_id: string;
  snapshot_hash_canonical: string;
  snapshot_hash_raw: string;
  snapshot_validity: "VALID" | "STALE" | "INVALID";
  snapshot_price?: number;
  regime_label_at_snapshot?: string;
  thesis_tags?: string[];
  operator_note?: string;
  created_by?: string;
}

export interface TriageIntentCreateResponse {
  intent_id: string;
  action: TriageAction;
  status: string;
  record_hash: string;
  symbol: string;
  queue_id: string;
}

export interface CandidateDetailResponse {
  snapshot: SnapshotEnvelope;
  candidate: CandidateDTO;
  found: boolean;
  analysis_available: boolean;
  analysis: Record<string, unknown>;
  evidence: Record<string, unknown>;
}

export interface AllocatorIntentDTO {
  intent_id: string;
  symbol: string;
  lane: string;
  side: string;
  status: string;
  funding_source_status: string;
  funding_available_at_utc: string;
  funding_reservation_id: string;
  execution_mode: string;
  asset_class_id: string;
  correlation_group_tag: string;
  reason_code: string;
  reason: string;
  status_message: string;
  updated_at_utc: string;
}

export interface AllocatorStatusResponse {
  since_minutes: number;
  count: number;
  items: AllocatorIntentDTO[];
  status_dictionary_version: string;
}

export interface LaneStatusCountDTO {
  lane: string;
  status: string;
  count: number;
  avg_target_notional_usd: number;
}

export interface RejectionReasonCountDTO {
  reason_code: string;
  count: number;
}

export interface AllocatorReportCardResponse {
  as_of_utc: string;
  lookback_days: number;
  from_utc: string;
  total_intents: number;
  pending_count: number;
  terminal_count: number;
  validated_count: number;
  rejected_count: number;
  validation_rate_pct: number;
  veto_rate_pct: number;
  status_counts: Record<string, number>;
  lane_status_counts: LaneStatusCountDTO[];
  rejection_reason_counts: RejectionReasonCountDTO[];
  recent_vetoes: Array<{
    intent_id: string;
    symbol: string;
    lane: string;
    side: string;
    status: string;
    reason_code: string;
    reason: string;
    status_message: string;
    updated_at_utc: string;
  }>;
  pending_funding_count: number;
  by_execution_mode: Record<string, number>;
  status_dictionary_version: string;
}

export interface MirrorChallengeRequest {
  user_id?: string;
  created_by?: string;
}

export interface MirrorChallengeResponse {
  intent_id: string;
  challenge_id: string;
  preview_hash: string;
  issued_at_utc: string;
  expires_at_utc: string;
  status: string;
  status_message: string;
  symbol: string;
  side: string;
  target_notional_usd: number;
  legal_consent_required: boolean;
  status_dictionary_version: string;
}

export interface MirrorConfirmRequest {
  challenge_id: string;
  client_preview_hash: string;
  user_id?: string;
  interaction_type?: string;
  legal_version?: string;
  legal_consent_active: boolean;
}

export interface MirrorConfirmResponse {
  intent_id: string;
  challenge_id: string;
  consent_id: string;
  consent_hash: string;
  status_before: string;
  status_after: string;
  status_message: string;
  confirmed_at_utc: string;
  reason_code: string;
  order_id: string;
  broker_submission: string;
  broker_order_id: string;
  broker_adapter: string;
  status_dictionary_version: string;
}

export interface MirrorChallengeState {
  challenge_id: string;
  preview_hash: string;
  issued_at_utc: string;
  expires_at_utc: string;
  used_at_utc: string;
}

export interface MirrorIntentPreviewResponse {
  intent_id: string;
  symbol: string;
  lane: string;
  side: string;
  target_notional_usd: number;
  status: string;
  reason_code: string;
  reason: string;
  status_message: string;
  snapshot_id: string;
  snapshot_hash_canonical: string;
  expires_at_utc: string;
  challenge: MirrorChallengeState;
  comparison: {
    available: boolean;
    current_weight_pct: number | null;
    target_weight_pct: number | null;
    delta_weight_pct: number | null;
  };
  portfolio_drift_pct: number | null;
  portfolio_drift_status: string;
  portfolio_last_sync_utc: string;
  portfolio_drift_message: string;
  status_dictionary_version: string;
}

export interface DriftSensitivityRequest {
  amber_threshold_pct: number;
  red_threshold_pct: number;
}

export interface DriftSensitivityResponse {
  amber_threshold_pct: number;
  red_threshold_pct: number;
}

export interface DriftImpactItem {
  symbol: string;
  current_weight_pct: number;
  target_weight_pct: number;
  delta_weight_pct: number;
  classification: string;
}

export interface DriftImpactResponse {
  available: boolean;
  portfolio_drift_pct: number | null;
  portfolio_drift_status: string;
  last_sync_utc: string;
  non_model_exposure_count: number;
  non_model_symbols: string[];
  items: DriftImpactItem[];
  message: string;
}
