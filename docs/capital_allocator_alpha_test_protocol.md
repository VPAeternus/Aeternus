# Capital Allocator v1 Alpha Test Protocol

## Objective

Validate allocator deterministic controls before execution-path integration:
- reliability + shock scaling
- impact veto and ADV participation cap
- covariance veto
- funding gate and intent lifecycle
- liability hurdle and shadow staleness haircut

## Test Window

- Duration: 7 simulated trading days
- Seed NAV: 100,000,000 USD
- Lane budget baseline:
  - CORE: 70%
  - MOMENTUM: 20%
  - HEDGE: 10%

## Inputs

1. SQLite WAL allocator DB initialized via `SQLiteAllocatorRepository.initialize()`.
2. Cached `market_snapshot` rows for all tested symbols.
3. Intent stream that mixes:
   - listed live intents
   - shadow private intents
4. Deterministic regime sequence with forced Day-3 `CRISIS`.

## Operator Scripts

1. Seed snapshot cache:
   - `./.venv/bin/python scripts/seed_allocator_market_snapshot.py --json`
2. Run Day-1 deterministic simulation:
   - `./.venv/bin/python scripts/run_allocator_alpha_day1.py --seed-snapshots --json`
3. Inject Day-3 shock override:
   - `./.venv/bin/python scripts/inject_regime_shock.py --regime CRISIS --json`

## Gate Expectations

1. Impact gate:
   - participation > 1% ADV30 notional -> `REJECTED_IMPACT_VETO`.
2. Covariance gate:
   - breach group cap or exceed MVC growth threshold -> `REJECTED_COVARIANCE_VETO`.
3. Liability gate:
   - net edge <= 0 after hurdle/impact/tax/stale haircuts -> `REJECTED_LIABILITY_HURDLE`.
4. Funding gate:
   - pending proceeds before available timestamp -> `VALIDATED_WAIT_FUNDING`.

## Crisis Injection (Day 3)

1. Set regime to `CRISIS` for the first heartbeat cycle.
   - via override artifact `eval_results/control/allocator_regime_override.json` using `scripts/inject_regime_shock.py`.
2. Expected outcomes:
   - increased confidence flattening in reliability transform
   - tighter concentration caps and higher veto counts
   - lower validated-notional throughput

## Concentration Wall (Day 5)

1. Keep regime at `CRISIS`.
2. Run concentration stress script:
   - `./.venv/bin/python scripts/run_allocator_alpha_day5_concentration.py --seed-snapshots --strict --json`
3. Expected collision:
   - existing SEMIS exposure: 9% NAV
   - new SEMIS intent: +2% NAV
   - `CRISIS` cap: 10%
   - expected status: `REJECTED_COVARIANCE_VETO`

## Definition of Done

1. 100% allocator intents end in a deterministic state with reason codes.
2. No trade intent bypasses impact/covariance/funding/liability gates.
3. Shadow intents with stale valuation incur deterministic haircut and can fail hurdle.
4. Market data used by allocator gates is read from `market_snapshot` cache.
5. Full repository test suite remains green.
6. Day-5 concentration wall reliably vetoes additive SEMIS risk in `CRISIS` while allowing the same vector in `NORMAL`.

## Exit Guillotine (Day 6)

1. Keep regime in `CRISIS`.
2. Run exit/roach-motel stress script:
   - `./.venv/bin/python scripts/run_allocator_alpha_day6_exit.py --seed-snapshots --strict --json`
3. Expected behavior:
   - risk-reducing `SELL` from breached SEMIS group is `VALIDATED`.
   - separate oversized illiquid `SELL` remains `REJECTED_IMPACT_VETO`.

## Day 7 Report Card

1. Generate allocator alpha report card:
   - `./.venv/bin/python scripts/run_allocator_alpha_day7_report.py --db-path eval_results/control/capital_allocator_alpha_day1.db --json`
2. Validate minimum report outputs:
   - `validation_rate_pct` and `veto_rate_pct`
   - top `rejection_reason_counts`
   - `pending_funding_count` and execution-mode mix
3. Archive output artifact:
   - `eval_results/control/capital_allocator_alpha_day7_report.json`

## Sprint A Mirror Handshake (Post-Alpha)

1. Create follow challenge for a `VALIDATED` allocator intent:
   - `POST /ops/mirror-intents/{intent_id}/challenge`
2. Confirm follow with legal consent + preview hash binding:
   - `POST /ops/mirror-intents/{intent_id}/confirm`
3. Verify expected transition:
   - intent status `VALIDATED -> SUBMITTED`
   - `user_consent_log` row persisted
   - `mirror_challenges.used_at_utc` populated
