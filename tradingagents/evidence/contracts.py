"""Typed contracts for deterministic evidence-pack generation."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict


EvidenceStatus = Literal["COMPLETE", "PARTIAL_DATA", "INSUFFICIENT_DEPTH"]


class MetricSet(TypedDict):
    count: int
    success_count: int
    failure_count: int
    skipped_count: int
    evaluated_5d: int
    evaluated_20d: int
    avg_return_5d_pct: Optional[float]
    avg_return_20d_pct: Optional[float]
    avg_benchmark_return_5d_pct: Optional[float]
    avg_benchmark_return_20d_pct: Optional[float]
    avg_edge_5d_pct: Optional[float]
    avg_edge_20d_pct: Optional[float]
    edge_win_rate_5d: Optional[float]
    edge_win_rate_20d: Optional[float]
    avg_strategy_return_5d_pct: Optional[float]
    avg_strategy_return_20d_pct: Optional[float]
    avg_strategy_edge_5d_pct: Optional[float]
    avg_strategy_edge_20d_pct: Optional[float]
    strategy_edge_win_rate_5d: Optional[float]
    strategy_edge_win_rate_20d: Optional[float]
    edge_win_rate_5d_p: Optional[float]
    edge_win_rate_20d_p: Optional[float]
    strategy_edge_win_rate_5d_p: Optional[float]
    strategy_edge_win_rate_20d_p: Optional[float]
    sharpe_5d: Optional[float]
    sharpe_20d: Optional[float]


class RegimeSlice(TypedDict):
    regime: str
    count: int
    pct: float
    metrics: MetricSet


class WalkForwardWindow(TypedDict):
    window_id: str
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    train_count: int
    test_count: int
    train_edge_5d_pct: Optional[float]
    train_edge_20d_pct: Optional[float]
    test_edge_5d_pct: Optional[float]
    test_edge_20d_pct: Optional[float]
    drift_5d_pct: Optional[float]
    drift_20d_pct: Optional[float]


class AblationSlice(TypedDict):
    family: str
    runs_evaluated: int
    avg_selection_turnover: float
    avg_edge_delta_5d_pct: Optional[float]
    avg_edge_delta_20d_pct: Optional[float]
    avg_win_rate_delta_5d: Optional[float]
    avg_win_rate_delta_20d: Optional[float]
    lane_mix_delta: Dict[str, float]


class EvidenceRunConfig(TypedDict):
    from_date: str
    to_date: str
    primary_benchmark: str
    secondary_benchmark: str
    extra_benchmarks: List[str]
    walkforward_train_days: int
    walkforward_test_days: int
    walkforward_step_days: int
    walkforward_fallback_train_days: int
    walkforward_fallback_test_days: int
    deep_k: int
    slippage_bps: float


class EvidencePack(TypedDict):
    generated_at: str
    status: EvidenceStatus
    from_date: str
    to_date: str
    sample_days: int
    benchmarks: Dict[str, Any]
    config: EvidenceRunConfig
    overall_metrics: MetricSet
    by_lane: Dict[str, MetricSet]
    by_playbook: Dict[str, MetricSet]
    by_signal_family: Dict[str, MetricSet]
    by_regime: Dict[str, MetricSet]
    regime_slices: List[RegimeSlice]
    walkforward: Dict[str, Any]
    ablation: Dict[str, Any]
    source_ablation: Dict[str, Any]
    live_outcome: Dict[str, Any]
    readiness_summary: Dict[str, Any]
    artifacts: Dict[str, str]
