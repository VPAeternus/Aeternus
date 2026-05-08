"""Fundamental research backtest exporters."""

__all__ = ["build_pit_panel", "run_high_conviction_top10_backtest"]


def build_pit_panel(*args, **kwargs):
    from .pit_panel import build_pit_panel as _build_pit_panel

    return _build_pit_panel(*args, **kwargs)


def run_high_conviction_top10_backtest(*args, **kwargs):
    from .high_conviction_top10 import run_high_conviction_top10_backtest as _run_backtest

    return _run_backtest(*args, **kwargs)
