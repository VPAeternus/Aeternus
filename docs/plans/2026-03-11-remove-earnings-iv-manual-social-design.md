# Remove Earnings IV And Convert Social News To Manual X-Feed Design

## Goal

Remove the Yahoo-finance-driven `earnings_iv` path from dealflow entirely, keep the manual Grok earnings/options scout as the only earnings/options path, and convert `social_news` to consume the manual X-feed artifact instead of the dead xAI cache/API path.

## Why

- `earnings_iv` is slow, low-yield, and not material enough to justify running on the filtered universe.
- The current `social_news` implementation still assumes an xAI cache/API path that is no longer the intended operator workflow.
- The operator already provides the highest-quality Grok/X research through manual X-feed and manual earnings/options scout ingestion, so the pipeline should use those artifacts directly.

## Scope

### Remove

- Discover-time legacy Yahoo IV scout hooks.
- Collect-time `earnings_iv` connector.
- `earnings_iv_divergence` scoring/contract references.
- IV-specific config flags that only supported the Yahoo path.
- The old Yahoo-backed `earnings-scan` CLI command.
- xAI cache/API code in `social_news.py`.
- xAI cache writeback coupling in `x_feed_manual.py`.

### Keep

- Manual Grok earnings/options scout:
  - `earnings-options-prompt --generate`
  - `earnings-options-prompt --ingest`
- Manual X-feed workflow and artifacts.
- Social/news scoring as a collector concept, but sourced only from manual X-feed artifacts.

## Target Behavior

### Earnings / Options

- `discover` keeps reading the manual earnings/options scout artifact and promotes those names into the universe.
- No Yahoo-based IV scan runs in `discover`.
- No Yahoo-based IV collector runs in `collect`.
- No force-queue or scoring path depends on `earnings_iv`.
- The old `earnings-scan` CLI command is removed so no stale Yahoo IV surface remains.

### Social News

- `collect_social_news_signals()` reads only from the manual X-feed merged artifact for the run date.
- It scores `social_momentum` and `news_catalyst` from the merged manual X-feed entries.
- Symbols not present in the manual X-feed artifact get `NO_DATA`.
- No xAI API config, cache path, or xAI-specific source name remains in the collector.

## Data Contract

`social_news` will treat `eval_results/x_feed/<date>/merged.json` as the source of truth.

Expected per-symbol fields already available from manual X-feed ingestion:

- `ticker`
- `sentiment`
- `mentions_estimate`
- `catalyst`
- `velocity_trend`

Derived scoring behavior:

- `social_momentum`:
  - based on merged sentiment + mention intensity + velocity trend
- `news_catalyst`:
  - based on catalyst presence + mention intensity + absolute sentiment

This keeps the collector deterministic while using the operator-curated Grok artifact as its only input.

## Implementation Notes

- Keep `_extract_json_payload()` available in `social_news.py` because other prompt-ingest commands import it.
- `x_feed_manual.py` should stop mirroring into any xAI cache file.
- Tests should be rewritten around:
  - manual X-feed backed `social_news`
  - absence of `earnings_iv` connector/scoring paths

## Risks

- Removing `earnings_iv` changes connector-health expectations and some test fixtures.
- `social_news` coverage will be limited to what the operator actually ingests through manual X-feed, which is intentional.
- Any stale references to `earnings_iv_divergence`, `scan_earnings_iv`, or xAI cache paths will need to be cleaned up or the repo will fail focused tests.

## Verification

- Focused tests for `social_news`, `x_feed_manual`, pipeline collect/discover, CLI command registration, and scoring/contracts.
- Live smoke:
  - ingest manual X-feed for a date
  - verify `collect_social_news_signals()` produces `OK` scores from merged X-feed
  - verify `collect` no longer advertises or times `earnings_iv`
