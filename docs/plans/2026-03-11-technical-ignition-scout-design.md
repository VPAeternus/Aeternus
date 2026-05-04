# Technical Ignition Scout Design

## Goal

Add a discovery-only `technical_ignition` scout that uses the cached `KAMA + bullish FVG regime` state to flag optimal technical setups during `discover()`, promote fresh setups into the filtered universe, and expose the results through existing scout audit / universe-filter / discovery-delta artifacts.

## Why This Boundary

The current evidence supports `technical_ignition` as a strong technical setup detector, but not yet as a standalone portfolio gate. It fits best as a scout:

- deterministic and sparse
- cache-backed, so cheap to query
- strong enough to improve recall and promotion
- not yet proven enough to become a first-class `collect` signal family

## Approach Options

### Option 1: Discovery-only scout with its own universe tier

Use the cache as a read-only source, run a new scout inside `discover()`, and promote only `BUY_TRIGGER` / `BUY_ZONE` names into the universe via a dedicated `T3D_TECHNICAL_IGNITION` tier.

Pros:
- cleanest semantics
- no pollution of `MANUAL` or existing recall tiers
- minimal impact on collect/ranking
- uses existing audit and delta artifacts

Cons:
- one more discovery path to maintain

### Option 2: Fold it into `price_momentum`

Treat the setup as another momentum-style score inside the existing connector.

Pros:
- fewer new modules

Cons:
- wrong boundary
- loses scout behavior
- delays setup visibility until `collect`
- blurs setup detection and scored connector logic

### Option 3: Immediate new `collect` signal family

Add `technical_ignition` as both a scout and a live scored signal family.

Pros:
- fastest path to portfolio influence

Cons:
- too aggressive for the current evidence level
- larger blast radius
- harder to interpret whether the new edge comes from discovery or scoring

## Recommendation

Use Option 1.

This keeps the new logic in the discovery layer, preserves existing ranking behavior, and gives Aeternus a clean technical scout that can later be promoted into a scored family if live evidence supports it.

## Design

### 1. New Scout Module

Create `tradingagents/dealflow/sources/technical_ignition_scout.py`.

Responsibilities:
- read `buy_zone_state_current` from the SQLite cache
- filter to rows with `as_of_date == discover_date`
- promote only `BUY_TRIGGER` and `BUY_ZONE`
- keep `TREND_UP_NOT_FRESH` as audit-only context
- return a compact result payload:
  - promoted rows
  - promoted symbols
  - stale rows
  - stale symbols
  - `signals` rows for `scout_audit["signals"]`

Graceful degradation:
- missing DB, empty cache, or stale cache date returns an empty result
- no network calls inside the scout

### 2. Discovery Integration

Wire the scout into `DealFlowPipeline.discover()` before universe construction.

Flow:
- run breakout / IV / insider scouts
- run `technical_ignition` scout from the cache
- pass promoted symbols into `build_universe_from_akg(...)`
- keep those names discovery-only; do not add a new `collect` connector yet

### 3. Dedicated Universe Tier

Add a new filtered-universe tier:
- `T3D_TECHNICAL_IGNITION`

This avoids marking scout-promoted names as `MANUAL`.

Rules:
- only names not already captured by higher-priority tiers get the new tier
- tier count appears in rule snapshot / universe filter outputs

### 4. Artifact / Reporting Integration

Extend `_build_scout_audit(...)` so it writes:
- a dedicated `technical_ignition` section with promoted and stale rows
- promoted names into the existing `signals` list

That lets existing downstream logic keep working:
- `universe_filter` already consumes `scout_audit["signals"]`
- `discovery_delta` already consumes `scout_audit["signals"]`

### 5. Config

Add minimal config keys:
- `dealflow_technical_ignition_enabled` default `true`
- `dealflow_technical_signal_db_path` default `eval_results/control/technical_signal_cache.db`

Keep status promotion hardcoded in v1:
- promote `BUY_TRIGGER`, `BUY_ZONE`
- audit-only `TREND_UP_NOT_FRESH`

YAGNI: do not add a large status-policy matrix yet.

## Error Handling

- If the cache DB does not exist, return empty scout output.
- If the cache only has older dates, return empty promoted output.
- If individual rows are malformed, skip them and continue.
- If the scout raises, discovery should continue with no technical-ignition promotions.

## Testing

### Unit

- scout returns promoted symbols only for `BUY_TRIGGER` / `BUY_ZONE`
- scout ignores stale or mismatched dates
- scout degrades cleanly on missing DB

### Integration

- `discover()` threads technical ignition symbols into universe build
- `scout_audit.json` persists the dedicated section plus promoted `signals`
- `universe_filter` / `discovery_delta` include the promoted scout activity
- new universe tier is preserved in tier counts

### CLI / Operator Surface

- existing `discover` command remains stable
- summary can optionally show `technical_ignition_count` if exposed

## Success Criteria

- running `discover()` with cached `BUY_TRIGGER` / `BUY_ZONE` rows promotes those names into the filtered universe without marking them `MANUAL`
- `scout_audit.json`, `universe_filter.json`, and `discovery_delta.json` all reflect the new scout
- no new `collect` signal family is introduced in v1
