"""Retired pre-fundamental scoring surface.

Scout-sourced tickers are never ranked or scored here. They must pass through
the fundamental framework first.
"""

from __future__ import annotations


class DealflowScoringRetired(RuntimeError):
    pass


def __getattr__(name: str):
    raise DealflowScoringRetired(
        f"Pre-fundamental scoring member {name!r} is retired; use fundamental scoring."
    )
