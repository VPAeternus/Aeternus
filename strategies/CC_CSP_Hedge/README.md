# CSP / Covered Call Scanner

Standalone research sandbox for scanning cash-secured-put / covered-call opportunities using daily OHLCV data from yfinance.

## Core Idea

The system looks for flat-to-overbought windows where short-premium trades may benefit from price mean reversion, sideways movement, or falling price.

## Signal Timing

- Signal is evaluated on the latest daily close.
- Scanner should be run after the market close, when final close and volume are available.
- Trade entry is at the next trading day open.

## Entry Rules

Sell CSP/CC at next day open only when all conditions pass on the signal bar:

1. `RoC > 0.01`
2. `AMA > AMA2`
3. `Volume < 10-day average volume`
4. `RSI(14) > 50`

## Indicators

Dual KAMA / AMA system:

- `fast = 1`
- `fast2 = 2`
- `slow = 15`
- `efficiency ratio length = 10`

Other filters:

- RSI period: `14`
- Volume average: prior `10` bars

## Exit Rules

Exit when either condition occurs first:

1. Take profit: price drops `3%` from entry
2. Signal exit: `RoC < 0.01`

## Backtest PnL Convention

Backtest PnL is a simplified short-trade proxy:

`PnL = entry_price - exit_price`

Implication:

- Profit when price falls after entry.
- Loss when price rises after entry.

This does not model option premiums, strikes, IV, assignment, commissions, slippage, or margin.

## CLI Usage

Run full scanner:

`python3 scanner.py`

Run scanner for a historical date:

`python3 scanner.py --date YYYY-MM-DD`

Save output to a custom CSV:

`python3 scanner.py --out signals.csv`
