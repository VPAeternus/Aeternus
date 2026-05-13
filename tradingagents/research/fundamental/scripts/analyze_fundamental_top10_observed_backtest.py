"""Compatibility module for old script import name."""
from .analyze_top10_observed_backtest import *  # noqa: F401,F403
from .analyze_top10_observed_backtest import main

if __name__ == "__main__":
    raise SystemExit(main())
