"""Fundamental research backtest exporters."""

__all__ = ["build_pit_panel"]


def build_pit_panel(*args, **kwargs):
    from .pit_panel import build_pit_panel as _build_pit_panel

    return _build_pit_panel(*args, **kwargs)
