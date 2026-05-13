from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tradingagents.research.fundamental.src.config.cache_paths import SEC_CACHE_ROOT
from tradingagents.research.fundamental.src.config.paths import FUNDAMENTAL_RUNS_ROOT

DEFAULT_QUARTERS: tuple[str, ...] = tuple(
    ["2021Q4"] + [f"{year}Q{quarter}" for year in range(2022, 2026) for quarter in range(1, 5)] + ["2026Q1"]
)
DEFAULT_OUT = FUNDAMENTAL_RUNS_ROOT / "manual" / "sec_pipeline"
DEFAULT_LIVE = SEC_CACHE_ROOT / "live_sec"


def quarter_window_slug(quarters: list[str] | tuple[str, ...]) -> str:
    clean = [str(q).strip() for q in quarters if str(q).strip()]
    if not clean:
        raise ValueError("quarters must contain at least one quarter")
    return clean[0] if len(clean) == 1 else f"{clean[0]}_{clean[-1]}"


@dataclass(frozen=True)
class SecPipelineConfig:
    out: Path = DEFAULT_OUT
    live: Path = DEFAULT_LIVE
    quarters: tuple[str, ...] = field(default_factory=lambda: DEFAULT_QUARTERS)
    window_slug: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "out", Path(self.out))
        object.__setattr__(self, "live", Path(self.live))
        quarters = tuple(str(q).strip() for q in self.quarters if str(q).strip())
        if not quarters:
            raise ValueError("quarters must contain at least one quarter")
        object.__setattr__(self, "quarters", quarters)
        if not self.window_slug:
            object.__setattr__(self, "window_slug", quarter_window_slug(quarters))

    @property
    def sec_cache(self) -> Path:
        return self.live.parent

    @property
    def tickers_json(self) -> Path:
        return self.out / "final_dealflow_tickers_sec_eligible.json"

    @property
    def universe_csv(self) -> Path:
        return self.out / "dealflow_universe.csv"

    @property
    def coverage_manifest_csv(self) -> Path:
        return self.out / f"sec_coverage_manifest_{self.window_slug}.csv"

    @property
    def fetch_queue_json(self) -> Path:
        return self.out / "sec_fetch_queue_resumable.json"

    @property
    def coverage_blockers_json(self) -> Path:
        return self.out / "sec_coverage_blockers.json"

    @property
    def coverage_summary_json(self) -> Path:
        return self.out / "sec_coverage_summary.json"

    @property
    def download_progress_json(self) -> Path:
        return self.out / "sec_download_progress.json"

    @property
    def download_manifest_json(self) -> Path:
        return self.out / f"sec_download_manifest_{self.window_slug}.json"
