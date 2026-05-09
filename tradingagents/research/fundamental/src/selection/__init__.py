"""Selection helpers for fundamental research outputs."""
from __future__ import annotations

from .high_conviction_top10 import (
    HighConvictionConfig,
    RightTailExceptionConfig,
    normalize_config,
    select_from_csv,
    select_high_conviction_top10,
    select_high_conviction_top15_exception_sleeve,
    select_top15_from_csv,
)
from .right_tail_queues import classify_demote_severity, compute_right_tail_evidence_score

__all__ = [
    "HighConvictionConfig",
    "RightTailExceptionConfig",
    "normalize_config",
    "select_from_csv",
    "select_high_conviction_top10",
    "select_high_conviction_top15_exception_sleeve",
    "select_top15_from_csv",
    "classify_demote_severity",
    "compute_right_tail_evidence_score",
]
