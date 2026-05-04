# Earnings Options Scout Refactor Design

## Goal

Move earnings/options discovery to a manual Grok scout in `discover`, and move quantitative IV divergence work to a deterministic collector in `collect`.

## Problem

The current IV scanner lives in discovery, but it is doing collector-grade work:

- earnings date lookups
- option chain downloads
- ATM implied-move calculation
- historical earnings-move comparison
- force-queue override injection

This is slow, network-bound, and conceptually in the wrong stage. Discovery should be high-recall and cheap. Exact option-chain math belongs later, after the filtered universe is already narrowed.

## Design Choice

Use a hybrid model:

1. `manual Grok earnings/options scout` in `discover`
2. `deterministic IV divergence collector` in `collect`

This keeps Grok where it is strongest:

- public X/options-flow account coverage
- web/X earnings attention detection
- fast thematic/public setup discovery

And keeps deterministic code where it is strongest:

- exact earnings window checks
- exact option-chain math
- exact historical earnings move comparison

## Rejected Alternatives

### Keep current IV scanner in `discover`

This preserves behavior but keeps expensive confirmation logic in the scout stage. It does not solve the stage-boundary problem.

### Grok-only options/earnings workflow

Operationally simple, but too weak for trust. Public chatter is useful for recall, but it is not enough to replace exact implied-vs-historical IV confirmation.

## Proposed Data Flow

### 1. Manual daily scout artifact

Add a new CLI workflow:

- `python3 -m cli.main earnings-options-prompt --generate --date YYYY-MM-DD`
- `python3 -m cli.main earnings-options-prompt --ingest --date YYYY-MM-DD`

Artifact path:

- `eval_results/deal_flow/earnings_options_scout_YYYY-MM-DD.json`

JSON contract:

```json
{
  "trending": [
    {
      "ticker": "MU",
      "buzz_rank": 1,
      "sentiment": "BULLISH",
      "velocity": "ACCELERATING",
      "catalyst": "High-confidence earnings/options setup from public flow and earnings discussion",
      "sector": "Technology",
      "earnings_date": "2026-03-18",
      "setup_type": "earnings_options",
      "flow_summary": "$3.2M call sweep in April expiry from public flow accounts",
      "accounts_flagged": 3
    }
  ]
}
```

Required:

- `ticker`
- `buzz_rank`
- `sentiment`
- `velocity`
- `catalyst`
- `sector`

Optional:

- `earnings_date`
- `setup_type`
- `flow_summary`
- `accounts_flagged`

### 2. Discovery integration

`discover()` should:

- load the manual earnings/options scout artifact if present
- promote its tickers into the universe as a scout contribution
- persist the contribution into:
  - `scout_audit.json`
  - `discovery_delta.json`
  - `universe_filter.json`

This keeps discovery cheap and recall-oriented.

### 3. Collector integration

Add a deterministic collector connector, likely named:

- `earnings_iv_divergence`

It should:

- run on the filtered universe
- fetch earnings dates once per ticker
- only fetch option chains for names with earnings in the configured window
- compute implied move vs historical earnings move
- emit normal `DealFlowSignal` rows

It should not force-queue names directly.

### 4. Retirement of IV force-queue

The current `_iv_force_queue` pipeline path should be removed or disabled:

- no more discover-time `force_queue` override
- no more `IV_FORCE_QUEUE` synthetic queue items in the default path

If needed, this can remain behind a config flag temporarily for migration safety.

## Pipeline Semantics After Refactor

### Discover

- breakout scout
- insider sweep
- technical ignition scout
- manual X-feed carryforward
- manual earnings/options Grok scout
- FVG/FMA recall

### Collect

- social/news
- price momentum
- macro
- smart money
- sector rotation
- insider cluster
- fundamental shadow
- deterministic earnings IV divergence

This is a cleaner scout vs collector boundary.

## Error Handling

### Manual scout missing

If the daily earnings/options scout artifact is absent:

- discovery continues
- audit records `NO_DATA`
- no names are promoted from this source

### Deterministic IV collector failures

If Yahoo or options chain fetch fails:

- collector returns `NO_DATA` or empty signals for that ticker
- connector health captures degradation
- pipeline continues

### Validation

The ingest command should reject malformed JSON and require:

- `trending` list present
- required per-entry fields
- normalized ticker casing

## Testing Strategy

1. CLI tests for prompt generate and ingest
2. Source loader tests for reading/writing the daily scout artifact
3. Discovery integration tests proving promoted symbols enter scout audit and universe build
4. Collector tests proving:
   - earnings date is fetched once
   - option chain is only fetched for earnings-window candidates
   - emitted signal family is deterministic and non-force-queue
5. Regression tests proving the old IV force-queue path is no longer active in the default flow

## Recommendation

Implement the refactor in two small slices:

1. add manual scout CLI + discovery integration
2. move quantitative IV logic into a collect-time connector and retire force-queue behavior

This gives an immediate operational win even before the collector migration is fully complete.
