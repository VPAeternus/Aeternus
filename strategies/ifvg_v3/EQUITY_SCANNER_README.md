# Equity Scanner — IFVG V3

Daily short-only equity scanner/backtester.

It looks for failed bullish FVG support, waits for bearish displacement, then shorts the retrace.

This strategy never opens long trades. Bullish FVGs are tracked only as support zones that can fail. They are not buy signals.

## Main Files

- `ifvg_strategy_v3.py` — core state machine and backtest engine.
- `portfolio_v3.py` — runs the engine across explicit tickers and writes scanner outputs.
- `run_ifvg_v3.py` — direct CLI runner for one or more tickers.
- `support_break_short.py` — locked support-break short test framework.
- `data_cache.py` — reads/updates daily OHLC cache in `market_data_cache/`.

## Run From This Folder

```bash
cd /Users/aeternusholdings/Documents/Aeternus/strategies/ifvg_v3
python3 run_ifvg_v3.py MU
```

Optional:

```bash
python3 run_ifvg_v3.py MU NVDA AMD
python3 run_ifvg_v3.py MU --no-vix
python3 run_ifvg_v3.py MU --no-refresh
python3 run_ifvg_v3.py MU --start-date 2010-01-01
```

## Core Defaults

- Entry level: `0.618`
- Target: `5%` below entry in `portfolio_v3.py`
- Regime filter: intraday entry allowed only when the prior close is below prior SMA50
- Dynamic exit: close short if daily close rises above SMA10
- VIX filter: enabled in `portfolio_v3.py` by default

## Position Direction

Short-only.

- Trade type is `EQ_SHORT`.
- Entry logic only creates short trades.
- Active position list is `active_shorts`.
- PnL uses short math: `entry_price - exit_price`.
- No long entry path exists.

## Locked Support-Break Short Rule

This is the next test framework.

- Build support from latest active bullish FVG low.
- Support moves up only when a newer bullish FVG low is above the current support.
- If prior day closes below support, support is broken.
- Enter short at next day open.
- Stop: max(break-day high, broken support).
- Default take profit: 3R.
- Skip trade if next day open is at or above stop.

Default variant / conservative baseline: `r3-v5-priority`.

`adaptive-v1` uses the same universal support-break engine, then classifies the break day into `LOW_VOL`, `MID_VOL`, `HIGH_VOL`, or `EXTREME_VOL` using ATR%:

- `LOW_VOL`: current R3-V5.1 Priority rules
- `MID_VOL`: looser trend/risk bands and ATR-aware `ret5`
- `HIGH_VOL`: no SMA10>SMA20 requirement, wider risk band, stronger gap requirement, bearish FVG/displacement confirmation
- `EXTREME_VOL`: research-only profile for very high ATR% names

For adaptive trades, target R is fixed at 3R for all profiles. The tested 4R HIGH_VOL trigger underperformed and is disabled.

`adaptive-v2` is the stricter research version:

- disables `EXTREME_VOL` by default
- requires shallow support breaks
- caps gap-up entries
- tightens `risk_atr` to `0.25 <= risk_atr <= 1.00`
- emphasizes fresh FVG support failures
- uses bearish FVG sequence features from support formation to support break
- writes `bearish_confirmation_source` plus confirmation flags so high-vol passes can be audited
- supports candidate audit export with reject reasons

`adaptive-v2-extreme-research` is isolated research for `EXTREME_VOL` only. Normal `adaptive-v2` still rejects `EXTREME_VOL`. Non-extreme rows in the extreme research variant reject with `NOT_EXTREME_VOL`.

Conservative accept rule, R3-V5.1 Priority:

- `risk_pct = (stop - entry) / entry`
- `gap_pct = (entry - close) / close`
- `close_vs_sma10 = (close - sma10) / sma10`
- `sma20_sma200_spread = (sma20 - sma200) / sma200`
- `risk_atr = risk / atr14`
- `old_core_ok`:
  - `gap_pct > 0`
  - `ret5 <= 0.018`
  - `sma10 > sma20 > sma200`
  - `close > sma10 OR (close < sma20 AND close > sma200)`
- accept when:
  - `old_core_ok`
  - `0.0025 <= risk_pct <= 0.025`
  - `-0.015 < close_vs_sma10 <= 0.0125`
  - `sma20_sma200_spread > 0.085`
  - `risk_atr <= 1.5`
  - `stop_source == "BREAK_HIGH"`
  - `gap_pct >= 0.0025`

Research variants:

- `adaptive-v1`: volatility-profile adaptive research system
- `adaptive-v2`: stricter adaptive research system
- `adaptive-v2-extreme-research`: opt-in `EXTREME_VOL` sandbox
- `r3-core`: original R3 core only
- `r3-v5-broad`: default rule without the hard `gap_pct >= 0.0025` threshold
- `r3-v5-conviction`: default rule with stricter `gap_pct >= 0.005`
- `r3-v5-a-plus`: conviction plus break-day range at least 2%
- `r3-v5-fresh`: conviction plus FVG age of 1 bar or less

Run:

```bash
python3 support_break_short.py MU
```

Default output uses `r3-v5-priority`. Other variants remain available with `--variant adaptive-v1`, `--variant adaptive-v2`, `--variant adaptive-v2-extreme-research`, `--variant legacy`, `--variant r3-core`, `--variant r3-v5-broad`, `--variant r3-v5-conviction`, `--variant r3-v5-a-plus`, and `--variant r3-v5-fresh`.

`--save` writes one combined CSV. Use `--output custom.csv` to choose the file path.

`--save-candidates` writes structural support-break candidates with `passed_variant`, `reject_reasons`, `vol_profile`, `bearish_confirmation_source`, confirmation flags, and filter diagnostics. Adaptive V2 uses named reject reasons instead of generic `PROFILE_RULE`.

Saved trade CSVs include FVG anatomy and risk columns:

- `fvg_form_date`, `fvg_age_bars`, `fvg_age_calendar_days`
- `fvg_low`, `fvg_gap_size`, `fvg_gap_pct`
- `broken_support`, `break_high`, `break_low`, `break_close`, `break_range_pct`
- `stop_source`, `support_distance_pct`, `support_ratcheted_count`
- `atr14`, `risk_atr`, `volume_zscore_20`
- `ret5`, `gap_pct`, `risk_pct`, `risk`, `realized_R`, `hold_days`
- `close_vs_sma5`, `close_vs_sma10`, `sma10_sma20_spread`, `sma20_sma200_spread`
- `vol_profile`, `atr_pct`, `atr_pct_252_median`, `bearish_fvg_count_3`, `bearish_fvg_count_5`
- `bearish_fvg_count_since_support`, `bearish_fvg_sequence_max_since_support`
- `bearish_confirmation_source`, `has_break_day_bearish_fvg`, `has_bearish_fvg_sequence`, `has_bearish_fvg_since_support`, `has_range_displacement`

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

Same-bar target handling is conservative for daily bars: if an intraday entry fills, the entry bar only exits for profit when the close is at or below the target. Otherwise target checks begin on the next bar.

## Outputs

`portfolio_v3.py` writes:

- `portfolio_ticker_results.csv`
- `live_signals.json`

`run_ifvg_v3.py` appends:

- `ifvg_v3_results_history.csv`
- `ifvg_v3_all_trades_history.csv`

## Known Issues

- Direct VIX download path inside `ifvg_strategy_v3.py` currently behaves differently than the preloaded VIX path used by `portfolio_v3.py`.
- Single-ticker tests overwrite global output files.
- Historical results use the tickers supplied at run time. If those tickers are selected from today's universe, results may have survivorship or selection bias.
- SMA10 close exits are intentionally evaluated on the entry bar when the trade fills intraday. This is a declared modeling assumption, not a fully intraday-sequenced fill model.
