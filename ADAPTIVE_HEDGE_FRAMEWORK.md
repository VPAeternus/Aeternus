# Adaptive Hedge Framework

**Status:** Active  
**Current default:** QQQ gate + SPY S7, 100% hedge target

## Current production rule

The hedge engine no longer applies a plain `SPY < SMA200` regime hedge by default. Default hedge activation now uses a `QQQ < QQQ_SMA200` gate plus SPY S7a/S7b.

Default policy:

| Condition | Hedge target | Notes |
|---|---:|---|
| `QQQ >= QQQ_SMA200` | `0%` | Hedge gate off |
| `QQQ < QQQ_SMA200`, SPY S7 inactive | `0%` | Plain bear-regime hedge disabled |
| `QQQ < QQQ_SMA200`, SPY S7a or S7b active | `100%` | Short hedge overlay |

Execution model:

- `hedge_signal.market_regime` is the hedge-gate regime; under default policy it describes QQQ vs QQQ SMA200, not SPY.
- Signal is known after close.
- Hedge fill is modeled at the same close for backtests unless otherwise specified.
- Hedge P&L begins on the next close-to-close return window.

## S7 trigger source

`cli.common._detect_s7_active()` checks latest `SPY` S7a/S7b state.

S7a / overnight:

- shared weak-regime SMA stack: `close > SMA3`, `close < SMA20`, `close < SMA50`, `close < SMA200`
- VIX in `[20,30)` or `[40,200)`
- standalone research execution: short close → next open

S7b / RTH:

- same weak-regime SMA stack
- VIX in `[20,25)` or `[30,40)`
- standalone research execution: short next open → next close

Live hedge use:

- S7 is not a standalone production order stream.
- SPY S7 determines whether a QQQ-gated hedge target should be `100%`.
- If QQQ is above SMA200, SPY S7 is ignored and default policy holds `0%`.
- If S7 detection fails or data is unavailable, `_detect_s7_active()` returns `False`; default policy then holds `0%` hedge.
- The default QQQ-gate/S7-only policy also disables the legacy crash-trigger escalation; use `bear_base` only for A/B comparison.

## V3 conflict rule

The V3 index overlay remains independent, but QQQ overnight long exposure is suppressed when the default hedge trigger is active:

- `QQQ < QQQ_SMA200`
- SPY S7a or S7b active

When this conflict fires, `momentum-scan --tickers QQQ --json` reports:

- `overnight_raw=true`
- `overnight=false`
- `overnight_suppressed_by_s7_hedge=true`

Portfolio plans also remove the V3 residual QQQ/TQQQ order and park that residual as cash when the hedge cycle returns `S7_HEDGE`.

Observed QQQ V3 suppression impact, no slippage:

| Window | Metric basis | No suppression | With S7 suppression | QQQ B&H |
|---|---|---:|---:|---:|
| 1999-03-10 → 2026-05-12 | official 1-share points | `+887.28` | `+961.28` | `+656.18` |
| 1999-03-10 → 2026-05-12 | return on start price | `+1737.64%` | `+1882.56%` | `+1285.05%` |
| 2006-01-03 → 2026-05-12 | official 1-share points | `+733.38` | `+803.38` | `+665.93` |
| 2006-01-03 → 2026-05-12 | return on start price | `+1775.30%` | `+1944.75%` | `+1612.03%` |
| 2006-01-03 → 2026-05-12 | compounded CAGR | `13.99%` | `15.26%` | `15.00%` |

Suppressed overnight days: `213` since 1999, `123` since 2006. Suppression removed `-74.00` QQQ overnight points since 1999 and `-70.00` since 2006.

## Instrument selection

The hedge order instrument is chosen by portfolio concentration:

| Portfolio state | Hedge instrument |
|---|---|
| `tech_concentration_pct >= 50` | `QQQ` |
| otherwise | `SPY` |

## A/B policy

Legacy policy remains available only for A/B testing:

```bash
AETERNUS_HEDGE_POLICY=bear_base aeternus hedge-evaluate --format table
```

Legacy behavior:

| Condition | Hedge target |
|---|---:|
| `SPY >= SMA200` | `0%` |
| `SPY < SMA200` | `85%` |
| `SPY < SMA200` + S7 | `150%` cap |
| crash trigger | `150%` cap |

If A/B testing shows legacy policy is not useful, remove the legacy code path instead of leaving it as permanent dead code.

## Key files

| File | Purpose |
|---|---|
| `tradingagents/graph/hedging.py` | Hedge signal, decision, persistence |
| `cli/common.py` | S7 detection, hedge cycle helpers |
| `cli/commands/portfolio.py` | Adds hedge order intent to portfolio plan |
| `cli/commands/execution.py` | Executes and syncs hedge state |
| `tradingagents/phase_engine/phase_engine.py` | S7a/S7b rules |
| `tests/test_hedging.py` | Hedge policy tests |
