# Equity Scanner — IFVG V3

Daily short-only equity scanner/backtester.

It looks for failed bullish FVG support, waits for bearish displacement, then shorts the retrace.

This strategy never opens long trades. Bullish FVGs are tracked only as support zones that can fail. They are not buy signals.

## Main Files

- `ifvg_strategy_v3.py` — core state machine and backtest engine.
- `portfolio_v3.py` — runs the engine across a watchlist and writes scanner outputs.
- `run_ifvg_v3.py` — direct CLI runner for one or more tickers.
- `watchlist_manager.py` — stores tickers in `watchlist.db`.
- `data_cache.py` — reads/updates daily OHLC cache in `market_data_cache/`.
- `generate_pm_report.py` — filters live signals into PM report artifacts.
- `proximity_engine.py` — checks live distance to resting limit prices.
- `dashboard/` — Next.js viewer over generated CSV/JSON files.

## Run From This Folder

```bash
cd /Users/aeternusholdings/Documents/Aeternus/strategies/ifvg_v3
python3 run_ifvg_v3.py MU
```

Optional:

```bash
python3 run_ifvg_v3.py MU NVDA AMD
python3 run_ifvg_v3.py MU --no-vix
python3 run_ifvg_v3.py MU --start-date 2010-01-01
```

## Core Defaults

- Entry level: `0.618`
- Target: `5%` below entry in `portfolio_v3.py`
- Regime filter: entry allowed only when close is below SMA50
- Dynamic exit: close short if daily close rises above SMA10
- VIX filter: enabled in `portfolio_v3.py` by default

## Position Direction

Short-only.

- Trade type is `EQ_SHORT`.
- Entry logic only creates short trades.
- Active position list is `active_shorts`.
- PnL uses short math: `entry_price - exit_price`.
- No long entry path exists.

## State Machine

1. Load ticker daily OHLC from `market_data_cache/`.
2. Add `sma10`, `sma20`, `sma50`.
3. Add VIX open when VIX filter is enabled.
4. Track bullish FVGs: today low is above high from two bars ago.
5. Track bearish FVGs: today high is below low from two bars ago.
6. Start in `HUNTING`.
7. When bearish FVG forms, check whether price closes below a prior bullish FVG's lowest low.
8. If yes, move to `EXPANDING`.
9. In `EXPANDING`, track the falling swing low and origin swing high.
10. When price stops closing below the swing low, move to `RETRACING`.
11. In `RETRACING`, place a short limit at:
   `swing_low + (swing_high - swing_low) * entry_level`
12. With default `entry_level=0.618`, entry sits 61.8% back up the displacement leg.
13. If day high reaches the limit, short fills.
14. If open gaps above the limit, fill uses open.
15. Stop is `swing_high`.
16. Target is `entry_price * (1 - target_pct)`.
17. Exit if stop hit, target hit, or close rises above SMA10.
18. After an entry attempt, reset to `HUNTING`.

## Outputs

`portfolio_v3.py` writes:

- `portfolio_ticker_results.csv`
- `live_signals.json`

`generate_pm_report.py` reads those and writes:

- `execution_reports/execution_report_YYYY-MM-DD.md`
- `execution_reports/pm_conviction_stack.json`

`proximity_engine.py` writes:

- `execution_reports/proximity_data.json`

## Known Issues

- Direct VIX download path inside `ifvg_strategy_v3.py` currently behaves differently than the preloaded VIX path used by `portfolio_v3.py`.
- Empty `live_signals.json` makes `generate_pm_report.py` exit early without writing an empty daily report.
- Single-ticker tests overwrite global output files.
- Watchlist metadata may be missing unless enrichment has been run.
