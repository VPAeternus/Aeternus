"""Compatibility wrapper for fundamental Top15 exception-sleeve analysis."""
from tradingagents.research.fundamental.scripts.analyze_top15_exception_sleeve import *  # noqa: F401,F403
from tradingagents.research.fundamental.scripts.analyze_top15_exception_sleeve import main

if __name__ == "__main__":
    raise SystemExit(main())
