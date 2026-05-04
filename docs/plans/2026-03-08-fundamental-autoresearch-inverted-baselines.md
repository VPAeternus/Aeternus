# Fundamental Autoresearch Inverted Baselines

Date: 2026-03-08

## Implementation Plan

1. Add inverted baseline strategies to the scorer.
2. Use complemented sub-scores for inverted strategies.
3. Extend default baseline comparison strategy list.
4. Add focused tests for:
   - inverted strategy scoring
   - inclusion in baseline comparison output
5. Run the focused harness suite.
6. Run the real historical comparison on `large_cap_v1-2009plus-with-returns.json`.
7. Update memory with the ranked results and the new recommendation.
