"""Canonical filesystem layout for the Fundamental framework.

Generated run artifacts belong under ``runs/`` by default. The directory is
git-ignored; committed docs/manifests describe the contract, not each run's data.
"""
from __future__ import annotations

import os
from pathlib import Path


FUNDAMENTAL_ROOT = Path(__file__).resolve().parents[2]
FUNDAMENTAL_RUNS_ROOT = FUNDAMENTAL_ROOT / "runs"
FUNDAMENTAL_ROOT_ENV = "AETERNUS_FUNDAMENTAL_ROOT"


def fundamental_root() -> Path:
    """Return the active framework root; tests may override with env."""
    override = os.environ.get(FUNDAMENTAL_ROOT_ENV, "").strip()
    return Path(override).expanduser().resolve(strict=False) if override else FUNDAMENTAL_ROOT


def fundamental_runs_root() -> Path:
    """Return the active generated-run root."""
    return fundamental_root() / "runs"


def default_daily_run_root(as_of: str, quarter: str) -> Path:
    """Default gated daily-run artifact root."""
    return fundamental_runs_root() / as_of / quarter / "daily"


def default_legacy_run_root(as_of: str, quarter: str) -> Path:
    """Default legacy scout-run artifact root."""
    return fundamental_runs_root() / as_of / quarter / "legacy_scout"


def default_selection_output_root(as_of: str) -> Path:
    """Default Top 10 + Plus 5 selection artifact root."""
    return fundamental_runs_root() / as_of / "selection"


def default_backtest_output_root() -> Path:
    """Default generated backtest artifact root."""
    return fundamental_runs_root() / "backtests"
