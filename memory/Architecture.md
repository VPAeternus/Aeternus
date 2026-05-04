# Aeternus Architecture (Principles + Constraints)

DeepWiki master architecture article: `memory/DeepWiki_System_Architecture.md`

## System Shape

```text
Deal Flow -> Research -> Portfolio Construction -> Execution
      |                                            |
      +-----------------> Track Record <-----------+
                           ^
                           |
                        Audit Log
                           ^
                           |
                     Hedging Overlay
```

## Team Responsibilities

1. **Deal Flow Team**
   - sources candidates across social/news/macro/smart-money
   - emits ranked shortlist and research queue
2. **Research Team**
   - performs thesis generation and validation
   - emits recommendation artifacts with score/confidence
3. **Portfolio Construction Team**
   - allocates capital by conviction/risk constraints
4. **Execution Team**
   - places orders via adapters (paper first, live later)
5. **Hedging Team**
   - controls beta/VaR/drawdown with deterministic rules

## Core Principles

1. Deterministic first, LLM second:
   - deterministic formulas for gating, ranking, and controls
   - LLMs for synthesis/comparison where deterministic rules are insufficient
2. Auditable by default:
   - every critical state transition must write an audit event
3. Graceful degradation:
   - partial data availability cannot crash the end-to-end run
4. Strong interfaces:
   - typed contracts for inter-team artifacts
5. Backward compatibility:
   - preserve existing CLI workflows while adding new modes

## Interface Contracts (Current)

1. Deal Flow contracts:
   - `DealFlowSignal`
   - `DealFlowCandidate`
   - `DealFlowShortlist`
   - `ResearchQueueItem`
   - `ResearchQueue`
2. Hedging contracts:
   - `PortfolioRiskSnapshot`
   - `MarketRegimeSnapshot`
   - `HedgeSignal`
   - `HedgeDecision`
   - `HedgeOrder`

## Data + Persistence Constraints

1. JSON artifacts are first-class interfaces, not temporary debug files.
2. Artifact paths must remain stable for downstream automation.
3. Audit and track-record logs are append-oriented and must remain parseable.
4. Missing external connectors must emit explicit status (e.g., `NOT_CONFIGURED`, `NO_DATA`).

## Operational Constraints

1. U.S. market daily cadence baseline.
2. Event-trigger refresh with cooldown for volatility/macro shocks.
3. One rebalance per day default for hedging except emergency override conditions.
4. All major commands must have both human-readable and JSON output modes.

## Testing Constraints

1. Unit tests for formulas and boundaries.
2. Integration tests for CLI command behavior and artifact generation.
3. Regression tests for backward-compatible commands (`score`, manual `analyze`, `performance`, `track-record`).
4. No milestone closure without passing test suite.
