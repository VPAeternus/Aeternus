"""
Aeternus Phase Engine — Wyckoff Adaptive Phase System
Forked from UnifiedStrategyClaude/aeternus_core into AeternusAgents.

Exports:
    config            — All tunable parameters
    data_engine       — OHLCV + VIX download, cache, indicator computation
    phase_engine      — Wyckoff phase classification + signals S2-S7
    scanner           — Multi-ticker signal scanner
    backtest_pnl      — Per-ticker short-only P&L calculator
    backtest          — Long/short equity backtester
    alpaca_data       — Alpaca live data drop-in
    cc_overbought     — Covered Call overbought exit engine (stocks)
    index_overlay     — v3 VIX momentum system for QQQ/SPY
    cc_scanner        — Covered Call Scanner: cc_overbought + wyckoff + index → CC timing signals
    cc_wyckoff_phase  — Covered Call Wyckoff Phase: scanner signals → portfolio order intents
"""

from . import config
from . import data_engine
from . import phase_engine
from . import scanner
from . import backtest_pnl
from . import backtest
from . import alpaca_data
from . import cc_overbought
from . import v3_backtest
from . import index_overlay
from . import cc_scanner
from . import cc_wyckoff_phase
