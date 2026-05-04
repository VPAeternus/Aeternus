"""Macro framework backtesting helpers."""

from .forward_returns import DEFAULT_HORIZONS, attach_forward_returns
from .historical_snapshots import build_historical_macro_snapshots
from .regime_tables import build_performance_table
from .regime_episodes import build_episode_performance, build_regime_episodes, build_transition_matrix
from .dealflow_ablation import run_macro_ablation

__all__ = [
    "DEFAULT_HORIZONS",
    "attach_forward_returns",
    "build_historical_macro_snapshots",
    "build_performance_table",
    "build_regime_episodes",
    "build_episode_performance",
    "build_transition_matrix",
    "run_macro_ablation",
]
