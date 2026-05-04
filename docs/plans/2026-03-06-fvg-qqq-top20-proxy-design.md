# FVG QQQ Top-20 Proxy Design

**Goal:** Add a fast, clearly labeled `QQQ` top-20 proxy universe to the existing FVG replay so we can compare current mega-cap leaders against `QQQ` without pretending the result is point-in-time clean.

**Approach:** Keep the existing replay engine intact and add one new universe-resolution path. The proxy universe will come from the current `QQQ` holdings feed exposed through `yfinance`, and the CLI will expose both `--universe` and `--benchmark` so proxy runs are explicit and reproducible.

**Guardrails:**
- Label the universe as a proxy in both payload and CLI.
- Keep `--tickers` as the highest-priority override.
- Separate default artifact paths by universe and benchmark so `SMH` and `QQQ` runs do not overwrite one another.
- Do not treat this as historical truth; it is a fast comparison surface only.
