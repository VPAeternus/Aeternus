from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class RunMode(str, Enum):
    BROAD_MASTER_FINAL = "broad-master-final"
    SCOUT_SMOKE = "scout-smoke"
    DIAGNOSTIC_ONLY = "diagnostic-only"


class GateStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    HARD_STOP = "hard_stop"
    SKIPPED = "skipped"


class StopGateError(RuntimeError):
    def __init__(self, result: "GateResult") -> None:
        self.result = result
        super().__init__(f"Gate {result.gate_number} hard stop: {result.gate_name}: {result.summary}")


@dataclass(frozen=True)
class DailyRunConfig:
    as_of: str
    quarter: str
    mode: str
    output_root: Path
    master_universe_path: Path | None = None
    handoff_path: Path | None = None
    sec_live_root: Path | None = None
    skip_fetch: bool = False
    skip_llm: bool = False
    llm_mode: str = "subagent"
    llm_model: str = "gpt-5.5"
    llm_reasoning_effort: str = "high"
    llm_batch_size: int = 8
    post_llm_path: Path | None = None
    prior_context_path: Path | None = None
    llm_output_dir: Path | None = None
    llm_output_csv: Path | None = None
    min_broad_universe_count: int = 1000
    max_sec_fetch_passes: int = 5
    emit_complete_panel: bool = False
    complete_panel_output_root: Path | None = None
    build_review_list_from_sec: bool = False
    sec_ticker_map_path: Path | None = None
    review_min_close: float = 2.0
    review_min_adv60: float = 500_000.0
    review_price_lookback_days: int = 120
    review_price_batch_size: int = 200
    review_price_cache_path: Path | None = None
    review_allow_live_price_fetch: bool = True

    @property
    def run_mode(self) -> RunMode:
        try:
            return RunMode(str(self.mode).strip().lower())
        except ValueError as exc:
            raise ValueError(f"mode must be one of {[m.value for m in RunMode]}") from exc


@dataclass
class GateResult:
    gate_number: int
    gate_name: str
    status: GateStatus
    summary: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)

    def raise_if_hard_stop(self) -> None:
        if self.status == GateStatus.HARD_STOP:
            raise StopGateError(self)


@dataclass
class DailyRunState:
    config: DailyRunConfig
    run_id: str
    gates: list[GateResult] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)

    def record(self, result: GateResult) -> GateResult:
        self.gates.append(result)
        self.artifacts.update(result.artifacts)
        return result
