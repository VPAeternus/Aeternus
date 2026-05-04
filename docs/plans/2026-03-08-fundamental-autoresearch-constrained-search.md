# Fundamental Autoresearch Constrained Search

Date: 2026-03-08

## Implementation Plan

1. Add a deterministic constrained-search helper over:
   - `health`
   - inverted `growth`
   - inverted `quality`
2. Generate bounded weight combinations that sum to `1.0`.
3. Reuse the existing scorer/evaluator contract.
4. Write a ranked `constrained_search.json` artifact.
5. Add a thin CLI command to run the search on a prepared dataset.
6. Add focused tests for:
   - search result generation
   - artifact writing
   - CLI invocation
7. Run the focused harness suite.
8. Run the real historical constrained search on `large_cap_v1-2009plus-with-returns.json`.
