"""Compatibility wrapper for fundamental Top10 observed backtest analysis."""
from tradingagents.research.fundamental.scripts.analyze_top10_observed_backtest import *  # noqa: F401,F403
from tradingagents.research.fundamental.scripts.analyze_top10_observed_backtest import main

if __name__ == "__main__":
    raise SystemExit(main())
