# Registry-Driven Fundamental Factor Implementation Plan

## Goal

Wire the live SEC fundamental connector to the autoresearch registry so live serving and historical truth use the same strategy contract.

## Tasks

1. Extend the signal registry
- add latest-registry loading
- add active-strategy resolution with `promoted` then `shadow` preference
- add focused tests

2. Add the shadow signal family contract
- update Deal Flow signal-family typing to include `fundamental_factor_shadow`

3. Refactor the live connector
- make `fundamental_factor.py` load the active registry strategy
- use the harness SEC cache + prepare layer to build current feature rows
- score with registry weights
- emit `fundamental_factor_shadow` unless the strategy is truly promoted
- degrade clearly when no strategy is available

4. Verify
- registry helper tests
- connector behavior tests
- focused dealflow regression around signal-family handling

5. Update memory
- note that the live SEC connector is now registry-driven and shadow-capable
