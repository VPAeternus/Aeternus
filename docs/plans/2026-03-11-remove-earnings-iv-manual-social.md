# Remove Earnings IV And Convert Social News To Manual X-Feed Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove the Yahoo-finance `earnings_iv` path from dealflow and make `social_news` consume only the manual X-feed artifact.

**Architecture:** Keep manual Grok ingestion as the only earnings/options and social/news operator path. `discover` continues to promote names from the manual earnings/options scout, while `collect` derives social/news signals directly from manual X-feed merged artifacts and no longer runs any Yahoo IV connector.

**Tech Stack:** Python, Typer, pytest, Rich, JSON artifact pipeline

---

### Task 1: Lock In The New Social-News Contract

**Files:**
- Modify: `tests/test_dealflow_social_news_live.py`
- Modify: `tests/test_social_cache_coverage.py`
- Modify: `tests/test_x_feed_manual.py`
- Test: `tradingagents/dealflow/sources/social_news.py`

**Step 1: Write the failing tests**

- Replace xAI-based expectations with manual-X-feed-based expectations.
- Add a test that `collect_social_news_signals()` reads the manual merged X-feed artifact for a date and emits `OK` signals for included symbols.
- Add a test that symbols not present in merged X-feed emit `NO_DATA`.
- Add a test that `x_feed_manual.ingest_pass()` no longer writes any xAI cache mirror.

**Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_dealflow_social_news_live.py tests/test_social_cache_coverage.py tests/test_x_feed_manual.py -q
```

Expected: failures referencing old xAI cache behavior.

**Step 3: Write minimal implementation**

- Rework `social_news.py` to load manual X-feed merged data.
- Remove xAI cache/API-specific helper usage from `x_feed_manual.py`.

**Step 4: Run tests to verify they pass**

Run the same command and confirm green.

### Task 2: Lock In Removal Of Earnings IV From Dealflow

**Files:**
- Modify: `tests/test_dealflow_pipeline.py`
- Modify: `tests/test_iv_scanner.py`
- Modify: `tests/test_cli_dealflow.py`
- Test: `tradingagents/dealflow/pipeline.py`
- Test: `legacy pre-fundamental scorer`
- Test: `tradingagents/dealflow/contracts.py`

**Step 1: Write the failing tests**

- Add/update tests asserting:
  - `collect()` does not thread an `earnings_iv` connector row.
  - `discover()` does not call legacy `scan_earnings_iv`.
  - scoring/contracts no longer reference `earnings_iv_divergence`.
  - the old Yahoo `earnings-scan` CLI command is absent or rejected.

**Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_dealflow_pipeline.py tests/test_iv_scanner.py tests/test_cli_dealflow.py -q
```

Expected: failures caused by lingering earnings-IV references.

**Step 3: Write minimal implementation**

- Remove imports, config, connector wiring, and scoring/contract references.
- Delete or neuter the old Yahoo CLI path.

**Step 4: Run tests to verify they pass**

Run the same command and confirm green.

### Task 3: Remove Dead Yahoo/xAI Surfaces

**Files:**
- Modify: `tradingagents/dealflow/sources/__init__.py`
- Modify: `tradingagents/default_config.py`
- Modify: `cli/main.py`
- Modify: `cli/commands/earnings_scanner.py`
- Modify: `tradingagents/dealflow/sources/iv_scanner.py`

**Step 1: Write the failing test**

- Add a small regression ensuring imports/CLI registration no longer expose the removed Yahoo path.

**Step 2: Run test to verify it fails**

Run the relevant focused pytest target.

**Step 3: Write minimal implementation**

- Remove dead exports.
- Remove dead config flags.
- Remove the obsolete CLI registration and command module or replace it with a manual-scout pointer.
- Remove the no-longer-used IV implementation file if nothing imports it.

**Step 4: Run tests to verify they pass**

Run the focused command and confirm green.

### Task 4: Focused Verification

**Files:**
- No code changes expected

**Step 1: Run focused verification**

```bash
python3 -m pytest tests/test_dealflow_social_news_live.py tests/test_social_cache_coverage.py tests/test_x_feed_manual.py tests/test_dealflow_pipeline.py tests/test_iv_scanner.py tests/test_cli_dealflow.py -q
```

**Step 2: Run live smoke**

```bash
python3 -m cli.main discover --date 2026-03-11 --format json
python3 -m cli.main collect --date 2026-03-11 --trigger manual --profile daily --top-k 30 --format json
```

Expected:
- no `earnings_iv` connector present
- `social_news` sourced from manual X-feed

### Task 5: Memory Updates

**Files:**
- Modify: `memory/WORKING.md`
- Modify: `memory/2026-03-11.md`
- Modify: `memory/MEMORY.md` (only if the architectural decision needs permanence)

**Step 1: Update session memory**

- Record that:
  - manual Grok is now the only earnings/options scout path
  - Yahoo `earnings_iv` was removed from dealflow
  - `social_news` now reads manual X-feed only

**Step 2: Verify memory files are saved**

Run:

```bash
sed -n '1,120p' memory/WORKING.md
sed -n '1,160p' memory/2026-03-11.md
```

