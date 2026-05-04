# Operator UI Week 2: First Light

This is the minimal read-first UI/data-plane contract for Aeternus Operator.

## Start Gateway

```bash
python scripts/run_operator_gateway.py --host 127.0.0.1 --port 8000 --reload
```

Optional CORS origins (comma-separated):

```bash
export OPERATOR_GATEWAY_CORS_ORIGINS="http://localhost:19006,http://localhost:8081"
```

Optional auth enforcement (recommended outside localhost):

```bash
export OPERATOR_GATEWAY_ENFORCE_API_KEY=true
export OPERATOR_GATEWAY_API_KEY_HEADER="X-Aeternus-Key"
export OPERATOR_GATEWAY_API_KEY="<shared-secret>"
```

Mirror handshake defaults (non-discretionary follow):

```bash
export OPERATOR_GATEWAY_REQUIRE_LEGAL_CONSENT=true
export OPERATOR_GATEWAY_LEGAL_VERSION="2026-02-08.v1"
export OPERATOR_GATEWAY_BROKER_ADAPTER="mock"   # disabled|mock (v1)
```

## Start Heartbeat Emitter (local/dev)

```bash
python scripts/emit_engine_heartbeat.py --interval-seconds 10
```

## Start Expo Shell

```bash
cd operator_ui
cp .env.example .env
# set EXPO_PUBLIC_OPERATOR_GATEWAY_URL if needed
# set EXPO_PUBLIC_OPERATOR_GATEWAY_API_KEY if gateway auth is enabled
npm install
npm run start
```

## Key Endpoints

- `GET /ops/bootstrap` (single poll for command center)
  - includes alignment pulse fields:
    - `portfolio_drift_pct`
    - `portfolio_drift_status`
    - `portfolio_last_sync_utc`
    - `portfolio_drift_message`
- `GET /ops/dealflow`
- `GET /ops/candidates/{symbol}`
- `GET /ops/schedule`
- `GET /ops/mirror-intents/{intent_id}`
- `GET /ops/settings/drift-sensitivity`
- `POST /ops/settings/drift-sensitivity`
- `GET /ops/drift-impact`
- `GET /ops/allocator-intents/status`
- `GET /ops/allocator/report-card`
- `POST /ops/triage-intent`
- `POST /ops/triage-intent/undo`
- `POST /ops/mirror-intents/{intent_id}/challenge`
- `POST /ops/mirror-intents/{intent_id}/confirm`
- `POST /ops/intent/{intent_id}/confirm` (alias)
- `GET /ops/triage-intents/status`
- `POST /ops/system-halt`
- `POST /ops/system-halt/clear`
- `POST /ops/system/shock`

## Safety Notes

- Triage mutations are blocked when snapshot validity is not `VALID`.
- Triage mutations are blocked when schedule is `UNKNOWN` or commit window is closed.
- `HANDS_OFF` halt blocks mutation/consume paths while read paths remain available.
- Mirror confirm is blocked without explicit `legal_consent_active=true` and matching preview hash challenge.
- Drift pulse thresholds are operator-configurable through drift sensitivity settings.
