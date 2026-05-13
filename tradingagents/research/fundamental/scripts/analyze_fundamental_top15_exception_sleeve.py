"""Compatibility module for old script import name."""
from .analyze_top15_exception_sleeve import *  # noqa: F401,F403
from .analyze_top15_exception_sleeve import main

if __name__ == "__main__":
    raise SystemExit(main())
