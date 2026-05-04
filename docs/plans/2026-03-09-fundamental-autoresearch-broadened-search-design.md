# Fundamental Autoresearch Broadened Search Design

## Goal

Broaden the constrained fundamental search space in the smallest evidence-driven way by allowing a small positive `valuation` sleeve alongside the currently winning family:

- positive `health`
- inverted `quality`
- inverted `growth`
- positive `valuation`

The purpose is to test whether valuation acts as a useful moderator on the current anti-crowding thesis without opening the search space so wide that the loop becomes hard to trust.

## Why This Slice

The current state is:

- the SEC/market-data harness is real
- baseline, inverted baseline, constrained search, robustness, and constrained autoresearch are all real
- the best strategy remains `health_0p5__inv_growth_0p1__inv_quality_0p4 = +0.087029`
- a feature-refinement slice did not improve that winner

So the next highest-probability gain is not more feature nuance in the same family. It is a carefully broadened constrained space using the only remaining factor family that has not clearly earned rejection and is economically plausible as a moderator.

## Why Valuation First

`valuation_only` was weak, but not strongly toxic. More importantly, valuation is the most plausible way to sharpen the interpretation of:

- expensive visible growth
- expensive beloved quality
- health-led balance-sheet resilience

This makes valuation a better first broadening candidate than capital discipline.

## Scope

### In Scope

- broadened constrained generator
- broadened constrained autoresearch loop
- same evaluation contract
- robustness on the top result

### Out of Scope

- no capital-discipline expansion in this slice
- no universe expansion
- no live pillar changes
- no feature-engineering changes

## Search Space

Candidate strategies must satisfy:

- `health > 0`
- `quality <= 0`
- `growth <= 0`
- `valuation >= 0`
- `capital_discipline = 0`
- absolute weights sum to `1.0`
- `health` remains dominant
- `valuation` stays small relative to `health`

The goal is not to let valuation take over the model. The goal is to test whether it improves the health-led anti-crowding family.

## Architecture

Modify:

- `tradingagents/research/fundamental_autoresearch/search.py`
- `tradingagents/research/fundamental_autoresearch/autoresearch.py`
- `tradingagents/research/fundamental_autoresearch/robustness.py` if strategy parsing requires it
- `cli/commands/fundamental_research.py`

The existing evaluator, artifact layer, and prepared dataset contract should stay unchanged.

## Success Criteria

- the broadened search space runs deterministically
- the new best strategy is clearly ranked
- robustness can be computed on the new winner
- the expansion only survives if it beats `+0.087029` and remains robust

## Decision Rule

If the broadened search does not beat the current winner:

- keep `health_0p5__inv_growth_0p1__inv_quality_0p4` as the canonical winner
- do not keep broadening just for the sake of complexity

If it does beat the current winner and remains robust:

- accept valuation as a justified constrained moderator
- only then consider whether capital discipline deserves the next expansion slice
