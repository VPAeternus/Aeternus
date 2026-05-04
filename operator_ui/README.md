# Aeternus Operator UI (Week 2 Shell)

Minimal Expo shell for the operator command center.

## Gateway Contract

This shell consumes:

- `GET /ops/bootstrap`
- `GET /ops/dealflow`
- `GET /ops/candidates/{symbol}`
- `GET /ops/schedule`

## Local Start

1. Copy `.env.example` to `.env` and set `EXPO_PUBLIC_OPERATOR_GATEWAY_URL`.
2. Install dependencies: `npm install`
3. Start: `npm run start`

## Notes

- UI is read-first and triage-safe by design.
- Mutation actions should only be enabled when bootstrap alerts are non-blocking and snapshot validity is `VALID`.
- Command center currently supports:
  - `/ops/bootstrap` polling
    - includes alignment pulse drift fields (`portfolio_drift_*`)
  - allocator veto dashboard (`/ops/allocator-intents/status`, `/ops/allocator/report-card`)
  - inspect candidate deep-dive via `/ops/candidates/{symbol}`
  - triage actions (`APPROVE`/`DEFER`/`BLOCK`) via `/ops/triage-intent`
  - mirror handshake API wiring for follow-confirm:
    - `/ops/mirror-intents/{intent_id}` (preview)
    - `/ops/mirror-intents/{intent_id}/challenge`
    - `/ops/mirror-intents/{intent_id}/confirm`
  - drift sensitivity settings:
    - `/ops/settings/drift-sensitivity` (GET/POST)
  - drift impact readout:
    - `/ops/drift-impact`
