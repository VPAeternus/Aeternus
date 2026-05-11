"""Retired pre-fundamental writeback surface.

Scout-sourced dealflow tickers are not scored before fundamental research.
"""

from __future__ import annotations

from typing import Any


def _retired(*_: Any, **__: Any) -> int:
    raise RuntimeError("pre-fundamental writeback is retired; use fundamental outputs for score writeback")


writeback_scores_to_akg = _retired
writeback_signals_to_akg = _retired
