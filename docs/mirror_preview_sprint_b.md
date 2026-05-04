# Mirror Preview Sprint B (Layout + Interaction Spec)

## Goal

Deliver a single-screen side-by-side preview that makes model-follow decisions obvious:
- show *why* Aeternus is moving
- show *how* the connected broker portfolio changes
- require deliberate follow confirmation (hold-to-confirm)

## Layout

### 1. Context (Why)
- Title: `Aeternus is moving into <theme>`
- Body: humanized reason from status dictionary (no raw risk math)
- Tone: calm and directive, one primary narrative only

### 2. Delta (Current vs Target)
- Render comparison row for symbol in mirror intent:
  - `Current (Broker)` weight %
  - `Target (Aeternus)` weight %
  - `Delta` weight %
- Source:
  - `GET /ops/mirror-intents/{intent_id}` -> `comparison`
- If comparison unavailable, show read-safe fallback:
  - `Alignment data unavailable. Sync broker snapshot.`

### 3. Action (Follow)
- Primary CTA: `Follow Aeternus Movement`
- Interaction: hold for 1500ms, then call confirm endpoint
- Footer:
  - legal acknowledgement line
  - notional estimate (`target_notional_usd`) and broker label

## API Contract

1. Preview:
- `GET /ops/mirror-intents/{intent_id}`
- returns:
  - intent summary + status message
  - challenge metadata
  - drift pulse snapshot
  - symbol-level comparison

2. Challenge:
- `POST /ops/mirror-intents/{intent_id}/challenge`

3. Confirm:
- `POST /ops/mirror-intents/{intent_id}/confirm`

4. Drift impact (manual trade visibility):
- `GET /ops/drift-impact`
- returns non-model exposures and ranked symbol deltas for the Drift Impact sheet.

## Drift Sensitivity (User Loudness Settings)

1. Read settings:
- `GET /ops/settings/drift-sensitivity`

2. Update settings:
- `POST /ops/settings/drift-sensitivity`
- payload:
  - `amber_threshold_pct`
  - `red_threshold_pct`

3. Bootstrap includes active thresholds:
- `drift_sensitivity`
- plus current drift values:
  - `portfolio_drift_pct`
  - `portfolio_drift_status`
  - `portfolio_drift_message`

## Day-1 Smoke Script

1. Start gateway with mock adapter:
```bash
export OPERATOR_GATEWAY_BROKER_ADAPTER=mock
python scripts/run_operator_gateway.py --host 127.0.0.1 --port 8000 --reload
```

2. Seed model + broker allocation artifacts:
```bash
cat > eval_results/control/model_allocation.json << 'JSON'
{"as_of_utc":"2026-02-08T00:00:00+00:00","weights":{"AAPL":0.70,"XLE":0.30}}
JSON
cat > eval_results/control/broker_allocation.json << 'JSON'
{"as_of_utc":"2026-02-08T00:00:00+00:00","weights":{"AAPL":0.90,"XLE":0.10}}
JSON
```

3. Verify drift appears in bootstrap:
```bash
curl -s http://127.0.0.1:8000/ops/bootstrap | jq '.portfolio_drift_pct,.portfolio_drift_status,.drift_sensitivity'
```

4. Tighten/loosen sensitivity:
```bash
curl -s -X POST http://127.0.0.1:8000/ops/settings/drift-sensitivity \
  -H 'Content-Type: application/json' \
  -d '{"amber_threshold_pct":10,"red_threshold_pct":20}' | jq
```

5. Challenge + preview + confirm for a validated intent:
- create challenge:
```bash
curl -s -X POST http://127.0.0.1:8000/ops/mirror-intents/<INTENT_ID>/challenge \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"operator-ui","created_by":"operator-ui"}' | jq
```
- preview:
```bash
curl -s http://127.0.0.1:8000/ops/mirror-intents/<INTENT_ID> | jq '.comparison,.portfolio_drift_status'
```
- confirm:
```bash
curl -s -X POST http://127.0.0.1:8000/ops/mirror-intents/<INTENT_ID>/confirm \
  -H 'Content-Type: application/json' \
  -d '{"challenge_id":"<CHALLENGE_ID>","client_preview_hash":"<PREVIEW_HASH>","legal_version":"2026-02-08.v1","legal_consent_active":true}' | jq
```
