# Aeternus Documentation (Milestone Status + Decisions)

## Milestone Status

| Milestone | Status | Notes |
|-----------|--------|-------|
| M1 Deal Flow Team v1 | DONE | CLI + pipeline + queue handoff shipped |
| M2 Smart Money Connectors | DONE | SEC 13F + Congress connectors integrated with graceful fallback |
| M3 Social Data Hardening | IN PROGRESS | direct X integrated; Reddit/X cost-quality tuning still iterative |
| M4 Batch Deep Research | DONE | deep/quick batch modes + attribution + cached fallback |
| M5 Portfolio + Execution Wiring | IN PROGRESS | recommendation -> order chain live in paper/alpaca-paper; live-ops guardrails hardening active |
| M6 Hedging Operationalization | IN PROGRESS | core engine done; deal-flow scheduler now in place |
| M7 Attribution Loop | IN PROGRESS | evidence-pack v1.1 shipped (regimes + walkforward + ablation) |

## Decision Ledger

## 2026-02-05
1. Adopt deterministic adaptive hedging overlay (Beta+VaR + regime).
2. Keep daily thesis-check as analyze-only feature.
3. Preserve confidence scale as 1-5 for backward compatibility.

## 2026-02-06
1. Prioritize Deal Flow Team before expanding downstream teams.
2. Keep manual ticker analyze path as fallback while queue-driven path is introduced.
3. Implement phased connector strategy:
   - Phase 1 proxy signals ship first
   - Phase 2 smart-money data live connectors
   - Phase 3 direct X/social upgrades
4. Add durable memory control-plane files (`Prompt.md`, `Plans.md`, `Architecture.md`, `Implement.md`, `Documentation.md`) as complementary layer to existing five-tier memory.
5. Implement smart-money source as live composite of SEC 13F + Congress disclosures with deterministic scoring and non-fatal source fallback semantics.
6. Implement direct X social connector with influencer-quality scoring, token-gated for production.
7. Implement deal-flow orchestration scheduler (daily pre-open + event-trigger cooldown) and expose via CLI command `orchestrate`.

## 2026-02-08
1. Implemented Step 2 Evidence Pack v1.1 as deterministic artifact-based validation layer (`tradingagents/evidence/`).
2. Added regime classification with fixed precedence and mixed-frequency normalization (CPI monthly forward-fill + DGS10 alignment).
3. Added walk-forward and ablation CLI surfaces (`evidence-pack`, `evidence-regimes`, `evidence-walkforward`, `evidence-ablation`).
4. Added `evidence_quality` gate into Step 1 readiness so promotion can be blocked by weak evidence depth/coverage/decay.

## Validation Index

Reference validation commands by milestone:

1. M1:
   - `./.venv/bin/python -m pytest tests/test_cli_dealflow.py -q`
   - `./.venv/bin/python -m pytest tests/ -q`
   - `./.venv/bin/python -m cli.main source --date <YYYY-MM-DD> --trigger daily --top-k 20 --format table`
2. M6:
   - `./.venv/bin/python -m pytest tests/test_hedging.py tests/test_market_regime.py tests/test_cli_hedging.py -q`
3. M2/M3 orchestration:
   - `./.venv/bin/python -m pytest tests/test_dealflow_smart_money.py tests/test_dealflow_x_social.py tests/test_dealflow_scheduler.py tests/test_cli_dealflow.py -q`
   - `./.venv/bin/python -m pytest -q`

## Open Risks

1. Some fallback connectors currently emit runtime failures (keys/rate limits/deprecated endpoints).
2. Full Congress coverage depends on a reliable House feed/provider; default Senate feed alone is incomplete.
3. Direct X connector requires a bearer token (`X_API_BEARER_TOKEN`) separate from `XAI_API_KEY`.

## Ownership Notes

1. Tactical session state lives in `memory/WORKING.md`.
2. Daily execution details live in `memory/YYYY-MM-DD.md`.
3. This file is for milestone-level status and durable decisions only.
