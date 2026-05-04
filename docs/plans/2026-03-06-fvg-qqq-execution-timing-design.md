# FVG QQQ Execution Timing Design

## Goal

Add an explicit execution-timing assumption to the `QQQ` FVG strategy backtest so we can compare:

- `next_open`: signal is computed from the completed bar and filled at the next session open
- `signal_close`: signal is computed from the completed bar and assumed filled at that same close

## Why

The current strategy path is conservative and executable: signal on day `t`, fill on day `t+1` open. The user wants to compare that against an intentionally optimistic same-close fill assumption. The backtest needs to label and separate those assumptions rather than silently mixing them.

## Scope

Only the `QQQ` strategy path changes:

- `tradingagents/dealflow/fvg_recall.py`
- `cli/commands/technical.py`
- `tests/test_fvg_recall.py`
- `tests/test_cli_dealflow.py`

The cross-sectional `fvg-backtest` replay stays unchanged in this task.

## Design

Add a new `execution_timing` parameter with two supported values:

- `next_open` (default)
- `signal_close`

Behavior:

- Entry:
  - `next_open`: fill using `features.iloc[index + 1]["open"]`
  - `signal_close`: fill using `row["close"]`
- Exit:
  - `next_open`: trigger on bar `t`, fill using bar `t+1` open
  - `signal_close`: trigger and fill using bar `t` close

Comparison mode should thread the execution timing to all three exit variants and surface it in the output artifact so runs remain interpretable.

## Guardrails

- Keep `next_open` as the default.
- Label `signal_close` as an optimistic assumption in the CLI and payload.
- Add tests that prove the timing branch changes fill prices and dates exactly as expected.
