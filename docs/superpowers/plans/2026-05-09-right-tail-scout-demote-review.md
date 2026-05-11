# Right-Tail Scout and Demote Review Queues Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Right-Tail Evidence Score plus Right-Tail Scout and Demote Review visibility queues without changing existing Top-10 or Top-15 buy-underwriting outputs.

**Architecture:** Keep the existing Top-10 and `high_conviction_top15_v3_exception_sleeve` selected output stable. Add a separate queue layer that computes right-tail evidence, demote severity, visibility routing, diagnostics, optional target audits, and daily/backtest CSVs from selection-time fields only.

**Important terminology:**

- `selected_sleeve = right_tail_exception`: row actually selected into the existing Top-15 exception sleeve.
- `top15_exception_candidate_queue`: visibility/staging queue for names eligible to be considered; not selected by this queue module.
- `right_tail_scout_queue`: research visibility for messy/low-entry-score right-tail setups.
- `demote_review_queue`: human review for demoted names with right-tail evidence.
- `blocked_hard_demote`: hard-demote visibility only; never buy-underwriting.

---

## Scope and non-goals

Build:

- `right_tail_evidence_score`
- `post_llm_demote_severity`, `post_llm_demote_reason_code`, `post_llm_demote_overrideable`, `post_llm_demote_evidence`
- `top15_exception_candidate_queue.csv`
- `right_tail_scout_queue.csv`
- `demote_review_queue.csv`
- `right_tail_evidence_score_diagnostics.csv`
- historical `target_miss_rescue_audit.csv` for backtests
- optional daily target audit only when `--target-events-csv` is passed
- daily CLI command with `--top15-selected-csv`
- Top-15 backtest/analysis integration and v4 visibility diagnostics

Do not:

- Change current Top-10 output behavior.
- Change current Top-15 selected rows, rank semantics, or performance semantics.
- Make Top-15 larger.
- Treat scout/demote-review queues as buy lists.
- Use return labels, monitoring fields, final-rank/current-return fields, or `return_since_*` fields for routing/scoring.
- Claim full AKG+macro production-v2 validation.

---

## File structure

### New files

- `tradingagents/research/fundamental/src/selection/signal_utils.py`
  - Shared signal constants/helpers for Top-10/Top-15/right-tail queue code.
  - Prevents new code from importing private helpers from `high_conviction_top10.py`.

- `tradingagents/research/fundamental/src/selection/right_tail_queues.py`
  - Demote normalization, right-tail evidence scoring, queue routing, CSV/JSON writing, optional target audit.
  - Does not import backtest code.
  - Does not use forbidden leakage columns.

- `tests/test_right_tail_scout_queues.py`
- `tests/test_cli_fundamental_right_tail_queues.py`
- `tests/test_fundamental_demote_severity.py`

### Existing files to modify

- `tradingagents/research/fundamental/src/selection/high_conviction_top10.py`
  - Import shared helpers from `signal_utils.py`; preserve legacy private aliases to avoid broad churn.

- `tradingagents/research/fundamental/src/selection/__init__.py`
  - Export queue API.

- `tradingagents/research/fundamental/src/features/llm_extraction.py`
  - Add demote severity fields to schema/CSV validation.
  - Force old `post_llm_demote_flag=1` when severity is `soft`, `hard`, or `unknown`.

- `tradingagents/research/fundamental/src/features/post_llm_scores.py`
  - Default new demote fields safely for old rows.

- `cli/commands/fundamental.py`
  - Add `fundamental-right-tail-queues` command.

- `tradingagents/research/fundamental/backtests/high_conviction_top15_exception_sleeve.py`
  - Add queue outputs, target visibility metrics, v4 diagnostics, and Top-15 selected hash guard.

- `scripts/analyze_fundamental_top15_exception_sleeve.py`
  - Add queue visibility analysis and target metric tables.

- `docs/research/aeternus-daily-pipeline-debug-runbook.md`
- `docs/research/fundamental_top15_exception_sleeve_observed_backtest_analysis.md`
- generated output folders under `outputs/fundamental_backtest/`

---

## Shared rules

Forbidden input columns for queue routing:

```python
FORBIDDEN_RIGHT_TAIL_ROUTING_COLUMNS = {
    "return_10d_pct",
    "return_20d_pct",
    "return_30d_pct",
    "return_60d_pct",
    "return_90d_pct",
    "winner_90d_30pct",
    "loser_90d_minus30pct",
    "monitoring_score_0_100",
    "active_monitoring_score_0_100",
    "final_rank_score_0_100",
    "rank_score_0_100",
    "current_return_pct",
    "return_since_signal_pct",
    "return_since_purchase_pct",
}
```

Queue types:

```python
RIGHT_TAIL_QUEUE_TYPES = {
    "top15_exception_candidate",
    "right_tail_scout",
    "demote_review",
    "watchlist_only",
    "blocked_hard_demote",
    "already_selected_top15",
    "ignore",
}
```

`blocked_hard_demote` is a `demote_review_queue.csv` row subtype, not a separate output queue. Target audit routing is the union of actual Top-15 selected status (`selected_sleeve=right_tail_exception`) plus `RIGHT_TAIL_QUEUE_TYPES`; do not force selected Top-15 rows into a queue type.

Evidence score formula:

```python
right_tail_evidence_score =
    +20 if single_rm_signal_bucket
    +12 if rm_buy_review_flag
    +10 if repricing_momentum_priority
    +6  if repricing_momentum_extension
    +10 if market_repricing_score >= 10
    +10 if market_repricing_score >= 14
    +10 if hp_signal_count > 0
    +12 if hp_LLM_best
    +15 if theme_acceleration_research_visibility
    +12 if akg_universe_tier == "T5_RESCAN"
    +10 if primary_theme is populated
    +8  if theme_tailwind_score > 0
    +8  if filing_theme_growth_flag
    +8  if filing_theme_guidance_flag
    +10 if active theme supplier/bottleneck role or keyword match
    -15 if hard_demote
    -8  if soft_demote
    -10 if risk_penalty_score >= 10
```

Supplier/bottleneck score is applied once max `+10`. Do not add new `theme_role` enum values. Use current schema roles plus keyword matching:

```python
role in {
    "supplier",
    "infrastructure_provider",
    "commodity_exposure",
    "turnaround_with_theme_tailwind",
}
or keyword in primary_theme/theme_tags/theme_evidence_summary:
    "bottleneck", "semicap", "semi cap", "materials", "optical", "supplier"
```

Routing thresholds:

```python
score >= 70: top15_exception_candidate if severity allows and not already selected
50 <= score <= 69: right_tail_scout
35 <= score <= 49: watchlist_only
score < 35: ignore unless demote-review candidate
```

Demote rules:

```python
hard demote:
    blocked_hard_demote only; never Top-15 candidate or buy-underwriting
unknown demote:
    demote_review only; never Top-15 candidate
soft demote:
    can enter top15_exception_candidate_queue only if post_llm_demote_overrideable == 1 and score >= 80
    otherwise can enter right_tail_scout or demote_review depending on score/evidence
none:
    normal right-tail routing
LLM failure / missing overrideable:
    overrideable defaults to 0
```

Target metrics:

```python
target_visibility_routed_count:
    selected_sleeve=right_tail_exception, top15_exception_candidate, right_tail_scout, demote_review, blocked_hard_demote

target_actionable_research_routed_count:
    selected_sleeve=right_tail_exception, top15_exception_candidate, right_tail_scout, demote_review

target_buy_underwriting_routed_count:
    selected_sleeve=right_tail_exception only
```

Acceptance target: visibility `>= 6/9`, actionable research `>= 4/9`. Hard-demote review counts as visibility only, not actionable/buy underwriting.

---

## Task 1: Extract shared signal utilities

**Files:**
- Create: `tradingagents/research/fundamental/src/selection/signal_utils.py`
- Modify: `tradingagents/research/fundamental/src/selection/high_conviction_top10.py`
- Test: existing Top-10/Top-15 tests

- [ ] **Step 1: Create shared utility module**

Move/share these definitions without changing behavior:

```python
RM_SIGNAL_FIELDS
HP_SIGNAL_FIELDS
truthy(value) -> bool
to_float(value) -> float | None
signal_count(row, fields) -> int
signal_bucket(row, fields) -> tuple[str, int]
rm_signal_bucket(row) -> str
hp_signal_bucket(row) -> str
```

- [ ] **Step 2: Preserve legacy aliases in `high_conviction_top10.py`**

Keep old names working:

```python
_truthy = truthy
_to_float = to_float
_signal_bucket = signal_bucket
```

This avoids breaking existing selectors/tests while letting right-tail queues import non-private utilities.

- [ ] **Step 3: Verify no Top-10/Top-15 behavior changed**

```bash
PYTHONPATH=. /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest \
  tests/test_fundamental_high_conviction_top10.py \
  tests/test_cli_fundamental_top10.py \
  tests/test_high_conviction_top15_exception_sleeve.py \
  -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tradingagents/research/fundamental/src/selection/signal_utils.py \
  tradingagents/research/fundamental/src/selection/high_conviction_top10.py
git commit -m "refactor: share fundamental signal utilities"
```

---

## Task 2: Right-tail evidence scoring module

**Files:**
- Create: `tradingagents/research/fundamental/src/selection/right_tail_queues.py`
- Modify: `tradingagents/research/fundamental/src/selection/__init__.py`
- Test: `tests/test_right_tail_scout_queues.py`

- [ ] **Step 1: Write failing score tests**

Create tests covering:

```python
def test_right_tail_evidence_score_formula_includes_rm_theme_hp_supplier_and_risk():
    # includes single RM bucket, rm_buy_review, repricing_momentum_priority,
    # repricing_momentum_extension, market >=10/>=14, HP, theme, supplier, risk penalty
    assert parts["repricing_momentum_priority"] == 10
    assert parts["repricing_momentum_extension"] == 6
    assert parts["active_theme_supplier_or_bottleneck_role"] == 10


def test_ichr_style_supplier_row_clears_scout_threshold():
    row = {
        "ticker": "ICHR",
        "entry_score_0_100": "3",
        "primary_theme": "semicap supplier",
        "theme_role": "supplier",
        "market_repricing_score": "14",
        "theme_tailwind_score": "8",
        "filing_theme_growth_flag": "1",
    }
    score, parts = compute_right_tail_evidence_score(row)
    assert score == 56
    assert score >= 50


def test_demote_flag_without_new_fields_defaults_unknown():
    assert classify_demote_severity({"post_llm_demote_flag": "1"}) == "unknown"


def test_demote_false_defaults_none():
    assert classify_demote_severity({"post_llm_demote_flag": "0"}) == "none"
```

- [ ] **Step 2: Run tests and verify they fail**

```bash
PYTHONPATH=. /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_right_tail_scout_queues.py -q
```

Expected: FAIL with import errors.

- [ ] **Step 3: Implement scoring**

In `right_tail_queues.py`:

- import shared helpers from `signal_utils.py`, not private `high_conviction_top10.py` helpers
- define `FORBIDDEN_RIGHT_TAIL_ROUTING_COLUMNS`
- define demote reason/severity constants
- implement `classify_demote_severity(row)`
- implement `has_active_theme_supplier_role(row)` using allowed roles plus keyword matching
- implement `compute_right_tail_evidence_score(row)` with the formula above
- ensure supplier/bottleneck points are max `+10` even if both role and keyword match
- ensure repricing fields are treated as right-tail/exception evidence, not demotion evidence

- [ ] **Step 4: Export API**

Modify `selection/__init__.py`:

```python
from .right_tail_queues import (
    classify_demote_severity,
    compute_right_tail_evidence_score,
)
```

- [ ] **Step 5: Run task tests**

```bash
PYTHONPATH=. /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_right_tail_scout_queues.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tradingagents/research/fundamental/src/selection/right_tail_queues.py \
  tradingagents/research/fundamental/src/selection/__init__.py \
  tests/test_right_tail_scout_queues.py
git commit -m "feat: add right-tail evidence score"
```

---

## Task 3: Demote severity fields in LLM/post-LLM features

**Files:**
- Modify: `tradingagents/research/fundamental/src/features/llm_extraction.py`
- Modify: `tradingagents/research/fundamental/src/features/post_llm_scores.py`
- Test: `tests/test_fundamental_demote_severity.py`

- [ ] **Step 1: Write failing tests**

Create tests for:

```python
def test_llm_schema_declares_demote_severity_fields():
    for field in [
        "post_llm_demote_severity",
        "post_llm_demote_reason_code",
        "post_llm_demote_overrideable",
        "post_llm_demote_evidence",
    ]:
        assert field in CSV_FIELDS
        assert field in result_schema()["properties"]["results"]["items"]["properties"]


def test_demote_severity_forces_old_demote_flag():
    payload = valid_payload(
        negative_revision_risk=1,
        story_vs_numbers_gap_penalty=0,
        narrative_delta_bucket="improving",
        post_llm_demote_severity="hard",
        post_llm_demote_reason_code="fraud_or_integrity",
        post_llm_demote_overrideable=0,
        post_llm_demote_evidence="integrity issue",
    )
    out = validate_llm_result(payload, packet())
    assert out["post_llm_demote_flag"] == 1


def test_none_severity_blanks_reason_and_evidence_when_no_deterministic_demote():
    out = validate_llm_result(valid_payload(
        post_llm_demote_severity="none",
        post_llm_demote_reason_code="weak_fundamentals",
        post_llm_demote_evidence="stale text",
        negative_revision_risk=1,
        story_vs_numbers_gap_penalty=0,
        narrative_delta_bucket="neutral",
    ), packet())
    assert out["post_llm_demote_flag"] == 0
    assert out["post_llm_demote_reason_code"] == ""
    assert out["post_llm_demote_evidence"] == ""


def test_old_rows_default_demote_fields_safely():
    out = classify_llm_status(row, {"post_llm_demote_flag": "1", ...})
    assert out["post_llm_demote_severity"] == "unknown"
    assert out["post_llm_demote_overrideable"] == 0
```

- [ ] **Step 2: Run tests and verify they fail**

```bash
PYTHONPATH=tradingagents/research/fundamental:. /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_fundamental_demote_severity.py -q
```

Expected: FAIL until schema/defaults are added.

- [ ] **Step 3: Add schema fields**

Add to `CSV_FIELDS`, `result_schema()`, validation, and prompt text:

```python
post_llm_demote_severity: enum["none", "soft", "hard", "unknown"]
post_llm_demote_reason_code: enum["", weak_fundamentals, cyclical_trough, ..., missing_filings]
post_llm_demote_overrideable: integer 0/1
post_llm_demote_evidence: string
```

Prompt rule:

```text
Hard means integrity, missing filing, going-concern, broken-thesis, or ununderwritable risk.
Soft means ugly but potentially re-ratable.
Unknown means demote signal exists but severity is unclear.
Overrideable=1 only when evidence says a soft demote may still deserve starter underwriting.
```

- [ ] **Step 4: Force old demote flag from severity**

Implement:

```python
severity = normalized["post_llm_demote_severity"]
derived_demote = int(risk >= 4 or gap >= 2 or bucket == "deteriorating")
severity_demote = int(severity in {"soft", "hard", "unknown"})

if severity == "none" and derived_demote:
    normalized["post_llm_demote_severity"] = "unknown"

if severity == "none" and not derived_demote:
    normalized["post_llm_demote_reason_code"] = ""
    normalized["post_llm_demote_evidence"] = ""
    normalized["post_llm_demote_overrideable"] = 0

normalized["post_llm_demote_flag"] = int(derived_demote or severity_demote)
```

LLM failure/default behavior:

```python
post_llm_demote_overrideable = 0
post_llm_demote_severity = "unknown" if old_demote_flag else "none"
```

- [ ] **Step 5: Add post-LLM defaults**

In `post_llm_scores.py`, add defaults on every return path:

```python
post_llm_demote_severity = "unknown" if post_llm_demote_flag else "none"
post_llm_demote_reason_code = ""
post_llm_demote_overrideable = 0
post_llm_demote_evidence = ""
```

- [ ] **Step 6: Run tests**

```bash
PYTHONPATH=tradingagents/research/fundamental:. /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_fundamental_demote_severity.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tradingagents/research/fundamental/src/features/llm_extraction.py \
  tradingagents/research/fundamental/src/features/post_llm_scores.py \
  tests/test_fundamental_demote_severity.py
git commit -m "feat: add demote severity fields"
```

---

## Task 4: Queue routing and daily-safe CSV writer API

**Files:**
- Modify: `tradingagents/research/fundamental/src/selection/right_tail_queues.py`
- Test: `tests/test_right_tail_scout_queues.py`

- [ ] **Step 1: Write failing routing tests**

Append tests:

```python
def test_low_entry_theme_supplier_routes_to_scout_not_candidate():
    rows = [{
        "ticker": "ICHR",
        "quarter": "2026Q1",
        "entry_score_0_100": "3",
        "primary_theme": "semicap supplier",
        "theme_role": "supplier",
        "market_repricing_score": "14",
        "theme_tailwind_score": "8",
        "filing_theme_growth_flag": "1",
        "post_llm_demote_flag": "0",
    }]
    result = build_right_tail_queues(rows, top15_selected_keys=set())
    assert result["right_tail_scout_queue"][0]["ticker"] == "ICHR"
    assert result["top15_exception_candidate_queue"] == []


def test_repricing_momentum_flags_can_create_demote_review_candidate():
    rows = [{
        "ticker": "BE",
        "quarter": "2025Q3",
        "post_llm_demote_flag": "1",
        "post_llm_demote_severity": "unknown",
        "repricing_momentum_priority": "1",
    }]
    result = build_right_tail_queues(rows, top15_selected_keys=set())
    assert result["demote_review_queue"][0]["ticker"] == "BE"


def test_soft_demote_requires_overrideable_for_candidate_queue():
    row = high_score_soft_demote_row(post_llm_demote_overrideable="0")
    result = build_right_tail_queues([row], top15_selected_keys=set())
    assert result["top15_exception_candidate_queue"] == []
    assert result["demote_review_queue"] or result["right_tail_scout_queue"]

    row["post_llm_demote_overrideable"] = "1"
    result = build_right_tail_queues([row], top15_selected_keys=set())
    assert result["top15_exception_candidate_queue"][0]["ticker"] == row["ticker"]


def test_unknown_demote_never_enters_candidate_queue():
    row = high_score_unknown_demote_row()
    result = build_right_tail_queues([row], top15_selected_keys=set())
    assert result["top15_exception_candidate_queue"] == []
    assert result["demote_review_queue"][0]["right_tail_queue_type"] == "demote_review"


def test_hard_demote_never_enters_candidate_queue():
    row = high_score_hard_demote_row()
    result = build_right_tail_queues([row], top15_selected_keys=set())
    assert result["top15_exception_candidate_queue"] == []
    assert result["demote_review_queue"][0]["right_tail_queue_type"] == "blocked_hard_demote"


def test_already_selected_top15_name_is_suppressed_from_visibility_queues():
    row = clean_candidate_row(ticker="CRDO", quarter="2024Q3")
    result = build_right_tail_queues([row], top15_selected_keys={("CRDO", "2024Q3")})
    assert result["top15_exception_candidate_queue"] == []
    assert result["right_tail_scout_queue"] == []
    assert result["right_tail_evidence_score_diagnostics"][0]["right_tail_queue_type"] == "already_selected_top15"


def test_forbidden_columns_are_removed_before_scoring():
    row = {"ticker": "A", "rm_buy_review_flag": "1", "return_90d_pct": "999", "final_rank_score_0_100": "100"}
    result = build_right_tail_queues([row], top15_selected_keys=set())
    diag = result["right_tail_evidence_score_diagnostics"][0]
    assert "return_90d_pct" not in diag["right_tail_score_input_columns"].split(";")
    assert "final_rank_score_0_100" not in diag["right_tail_score_input_columns"].split(";")
```

- [ ] **Step 2: Run tests and verify they fail**

```bash
PYTHONPATH=. /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_right_tail_scout_queues.py -q
```

Expected: FAIL because routing/API missing.

- [ ] **Step 3: Implement routing**

In `right_tail_queues.py` add:

```python
@dataclass(frozen=True)
class RightTailQueueConfig:
    scout_threshold: float = 50.0
    top15_candidate_threshold: float = 70.0
    watchlist_threshold: float = 35.0
    soft_demote_top15_candidate_threshold: float = 80.0
```

Implement:

- `is_overrideable(row)` from `post_llm_demote_overrideable`
- `_demote_review_candidate(row)` using RM bucket, `rm_buy_review_flag`, `repricing_momentum_priority`, `repricing_momentum_extension`, market repricing, HP, theme, AKG/T5
- `_dedupe_reason_codes(codes)` using `";".join(sorted(set(codes)))`
- `_strip_forbidden_columns(row)` before score computation
- diagnostics field `right_tail_score_input_columns`
- queue result keys:
  - `top15_exception_candidate_queue`
  - `right_tail_scout_queue`
  - `demote_review_queue`
  - `watchlist_only_queue`
  - `right_tail_evidence_score_diagnostics`

Routing order:

```python
if selected_key in top15_selected_keys:
    queue_type = "already_selected_top15"  # diagnostics only
elif severity == "hard":
    demote_review_queue.append(blocked_hard_demote)  # never candidate/scout/watchlist
elif severity == "unknown":
    demote_review_queue.append(demote_review)  # unknown demote review only
elif severity == "soft" and overrideable and score >= 80:
    top15_exception_candidate_queue.append(top15_exception_candidate)
elif severity == "none" and score >= 70:
    top15_exception_candidate_queue.append(top15_exception_candidate)
elif severity == "soft" and score >= 50:
    right_tail_scout_queue.append(right_tail_scout)
elif severity == "soft" and demote_candidate:
    demote_review_queue.append(demote_review)
elif score >= 50:
    right_tail_scout_queue.append(right_tail_scout)
elif score >= 35:
    watchlist_only_queue.append(watchlist_only)
else:
    diagnostics only
```

- [ ] **Step 4: Implement CSV/JSON writer API**

Add:

```python
def parse_top15_selected_keys(path: Path | None) -> set[tuple[str, str]]:
    # read ticker+quarter from high_conviction_top15.csv/selected_names_by_quarter_top15.csv


def read_target_events_csv(path: Path) -> dict[str, str]:
    # columns: ticker, quarter OR ticker, target_quarter


def build_target_visibility_audit(rows, diagnostics, target_events) -> list[dict[str, Any]]:
    # only called when target_events passed in daily mode or always in backtest mode


def select_right_tail_queues_from_csv(scores_csv, output_root, *, top15_selected_csv=None, target_events_csv=None, selection_date="") -> dict[str, Any]:
    # always write candidate/scout/demote/diagnostics/json
    # write target_miss_rescue_audit.csv only when target_events_csv is provided
```

Daily default outputs:

```text
top15_exception_candidate_queue.csv
right_tail_scout_queue.csv
demote_review_queue.csv
right_tail_evidence_score_diagnostics.csv
right_tail_queues.json
```

Optional daily output with `--target-events-csv`:

```text
target_miss_rescue_audit.csv
```

If `top15_selected_csv` is missing, return warning:

```text
Top15 selected CSV not provided; scout queues may include already-selected Top15 names.
```

- [ ] **Step 5: Run tests**

```bash
PYTHONPATH=. /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_right_tail_scout_queues.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tradingagents/research/fundamental/src/selection/right_tail_queues.py tests/test_right_tail_scout_queues.py
git commit -m "feat: route right-tail visibility queues"
```

---

## Task 5: Daily CLI command

**Files:**
- Modify: `cli/commands/fundamental.py`
- Test: `tests/test_cli_fundamental_right_tail_queues.py`

- [ ] **Step 1: Write failing CLI tests**

Create tests:

```python
def test_fundamental_right_tail_queues_writes_default_daily_outputs_without_target_audit(tmp_path):
    scores = write_scores_csv(tmp_path)
    top15 = write_top15_selected_csv(tmp_path, [("CRDO", "2024Q3")])
    out = tmp_path / "out"

    result = runner.invoke(app, [
        "fundamental-right-tail-queues",
        "--scores-csv", str(scores),
        "--top15-selected-csv", str(top15),
        "--output-root", str(out),
        "--date", "2026-05-09",
        "--format", "json",
    ])

    assert result.exit_code == 0, result.output
    for name in [
        "top15_exception_candidate_queue.csv",
        "right_tail_scout_queue.csv",
        "demote_review_queue.csv",
        "right_tail_evidence_score_diagnostics.csv",
        "right_tail_queues.json",
    ]:
        assert (out / name).exists()
    assert not (out / "target_miss_rescue_audit.csv").exists()


def test_fundamental_right_tail_queues_writes_target_audit_only_when_requested(tmp_path):
    result = runner.invoke(app, [
        "fundamental-right-tail-queues",
        "--scores-csv", str(scores),
        "--top15-selected-csv", str(top15),
        "--target-events-csv", str(target_events),
        "--output-root", str(out),
    ])
    assert result.exit_code == 0
    assert (out / "target_miss_rescue_audit.csv").exists()


def test_missing_top15_selected_csv_warns_but_does_not_fail(tmp_path):
    result = runner.invoke(app, ["fundamental-right-tail-queues", "--scores-csv", str(scores), "--output-root", str(out)])
    assert result.exit_code == 0
    assert "Top15 selected CSV not provided" in result.output
```

- [ ] **Step 2: Run tests and verify they fail**

```bash
PYTHONPATH=. /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_cli_fundamental_right_tail_queues.py -q
```

Expected: FAIL because command missing.

- [ ] **Step 3: Add CLI command**

Modify `cli/commands/fundamental.py`:

```python
@app.command("fundamental-right-tail-queues")
def fundamental_right_tail_queues(
    scores_csv: str = typer.Option(..., "--scores-csv"),
    top15_selected_csv: str = typer.Option("", "--top15-selected-csv"),
    target_events_csv: str = typer.Option("", "--target-events-csv"),
    output_root: str = typer.Option("", "--output-root"),
    date: str = typer.Option("", "--date"),
    format: str = typer.Option("table", "--format", help="table|json"),
):
    """Emit right-tail visibility queues from final fundamental scores."""
```

Behavior:

- error if `--scores-csv` missing
- warn but continue if `--top15-selected-csv` missing
- only pass `target_events_csv` when provided
- print/write `right_tail_queues.json`
- never call historical hard-coded target events in daily mode

Daily run example:

```bash
python3 -m cli.main fundamental-right-tail-queues \
  --scores-csv eval_results/fundamental/YYYY-MM-DD/fundamental_final_scores_YYYY-MM-DD.csv \
  --top15-selected-csv eval_results/fundamental/YYYY-MM-DD/high_conviction_top15.csv \
  --output-root eval_results/fundamental/YYYY-MM-DD \
  --date YYYY-MM-DD
```

Optional target audit:

```bash
python3 -m cli.main fundamental-right-tail-queues \
  --scores-csv eval_results/fundamental/YYYY-MM-DD/fundamental_final_scores_YYYY-MM-DD.csv \
  --top15-selected-csv eval_results/fundamental/YYYY-MM-DD/high_conviction_top15.csv \
  --target-events-csv docs/research/right_tail_target_events.csv \
  --output-root eval_results/fundamental/YYYY-MM-DD \
  --date YYYY-MM-DD
```

- [ ] **Step 4: Run CLI tests**

```bash
PYTHONPATH=. /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest \
  tests/test_cli_fundamental_right_tail_queues.py \
  tests/test_cli_fundamental_top10.py \
  -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cli/commands/fundamental.py tests/test_cli_fundamental_right_tail_queues.py
git commit -m "feat: add right-tail queue daily cli"
```

---

## Task 6: Top-15 backtest integration and v4 diagnostics

**Files:**
- Modify: `tradingagents/research/fundamental/backtests/high_conviction_top15_exception_sleeve.py`
- Modify: `tests/test_high_conviction_top15_backtest.py`
- Generated: `outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/`

- [ ] **Step 1: Write failing backtest tests**

Append tests:

```python
def test_right_tail_queue_outputs_exist(tmp_path):
    out = run_backtest_tmp(tmp_path)
    for name in [
        "top15_exception_candidate_queue.csv",
        "right_tail_scout_queue.csv",
        "demote_review_queue.csv",
        "right_tail_evidence_score_diagnostics.csv",
        "target_miss_rescue_audit.csv",
        "v4_rescue_variant_summary.csv",
    ]:
        assert (out / name).exists()


def test_target_visibility_and_actionable_counts(tmp_path):
    out = run_backtest_tmp(tmp_path)
    rows = list(csv.DictReader(open(out / "target_miss_rescue_audit.csv")))
    visibility = [r for r in rows if r["target_visibility_routed"] == "1"]
    actionable = [r for r in rows if r["target_actionable_research_routed"] == "1"]
    assert len(visibility) >= 6
    assert len(actionable) >= 4


def test_crdo_remains_selected_in_top15_target_quarter(tmp_path):
    out = run_backtest_tmp(tmp_path)
    selected = list(csv.DictReader(open(out / "selected_names_by_quarter_top15.csv")))
    assert any(
        r["ticker"] == "CRDO"
        and r["quarter"] == "2024Q3"
        and r.get("selected_sleeve") == "right_tail_exception"
        for r in selected
    )


def test_top15_selected_rows_hash_unchanged(tmp_path):
    prior = Path("outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/selected_names_by_quarter_top15.csv")
    prior_hash = sha256(prior.read_bytes()).hexdigest()
    out = run_backtest_tmp(tmp_path)
    new_hash = sha256((out / "selected_names_by_quarter_top15.csv").read_bytes()).hexdigest()
    assert new_hash == prior_hash


def test_manifest_records_selected_hash_and_no_leakage(tmp_path):
    out = run_backtest_tmp(tmp_path)
    manifest = json.loads((out / "run_manifest.json").read_text())
    assert manifest["top15_selected_rows_unchanged_from_prior_hash"] is True
    assert manifest["prior_selected_names_by_quarter_top15_sha256"] == manifest["new_selected_names_by_quarter_top15_sha256"]
    assert not set(manifest["right_tail_queue_feature_columns"]) & set(manifest["right_tail_queue_forbidden_columns"])


def test_target_audit_has_failure_mode_and_metric_columns(tmp_path):
    out = run_backtest_tmp(tmp_path)
    rows = list(csv.DictReader(open(out / "target_miss_rescue_audit.csv")))
    required = {
        "miss_failure_mode",
        "selected_in_top15_v3",
        "selected_sleeve",
        "routed_visibility_layer",
        "target_visibility_routed",
        "target_actionable_research_routed",
        "target_buy_underwriting_routed",
    }
    assert required.issubset(rows[0])
```

- [ ] **Step 2: Run tests and verify they fail**

```bash
PYTHONPATH=. /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_high_conviction_top15_backtest.py -q
```

Expected: FAIL because queue outputs/manifest fields missing.

- [ ] **Step 3: Build queues from eligible rows after Top-15 selection is frozen**

In backtest module:

```python
top15_selected_keys = {
    (str(row.get("ticker", "")).upper(), str(row.get("quarter", "")))
    for row in selected_rows
    if row.get("variant") == "high_conviction_top15_v3_exception_sleeve"
}
queues = build_right_tail_queues(queue_input, top15_selected_keys)
```

Never feed queue outputs back into Top-15 selection.

- [ ] **Step 4: Write queue CSVs**

```python
_write_csv(out / "top15_exception_candidate_queue.csv", queues["top15_exception_candidate_queue"])
_write_csv(out / "right_tail_scout_queue.csv", queues["right_tail_scout_queue"])
_write_csv(out / "demote_review_queue.csv", queues["demote_review_queue"])
_write_csv(out / "right_tail_evidence_score_diagnostics.csv", queues["right_tail_evidence_score_diagnostics"])
```

- [ ] **Step 5: Add historical target audit**

Backtest can use built-in historical targets:

```python
TARGET_RIGHT_TAIL_EVENTS = {
    "CRNC": "2024Q4",
    "CVNA": "2023Q2",
    "SNDK": "2025Q3",
    "AAOI": "2023Q2",
    "BE": "2025Q3",
    "AXTI": "2026Q1",
    "AEHR": "2026Q1",
    "ICHR": "2026Q1",
    "CRDO": "2024Q3",
}
```

Audit fields:

```text
ticker
target_quarter
selected_in_top15_v3
selected_sleeve
miss_failure_mode
routed_visibility_layer
right_tail_evidence_score
right_tail_recommended_action
target_visibility_routed
target_actionable_research_routed
target_buy_underwriting_routed
```

Failure modes:

```text
SELECTED_IN_TOP15_V3
POST_LLM_DEMOTE
ENTRY_SCORE_BELOW_EXCEPTION_MIN
NOT_RANKED_IN_SELECTED_SLOTS
NOT_PRESENT
```

Use visibility language in values and comments. Avoid saying non-selected names were “rescued” except in the file name required for historical continuity.

- [ ] **Step 6: Add v4 diagnostic output**

Write `v4_rescue_variant_summary.csv` as visibility diagnostics only:

```text
variant,routed_target_count,visibility_routed_count,actionable_research_routed_count,buy_underwriting_routed_count,description
```

Rows:

```text
top15_v4_exception_plus_scout
top15_v4_soft_demote_override
top15_v4_theme_akg_supplier_rescue
```

The `v4_rescue_variant_summary.csv` filename and `*_rescue` variant labels are legacy/debug identifiers only. Descriptions and report language must say these are visibility diagnostics, not selected buy-underwriting variants or proof that names were rescued.

- [ ] **Step 7: Add manifest fields**

```python
"right_tail_queue_outputs": {...}
"right_tail_queue_forbidden_columns": sorted(FORBIDDEN_RIGHT_TAIL_ROUTING_COLUMNS)
"right_tail_queue_feature_columns": sorted(score_input_columns)
"right_tail_queue_no_leakage_statement": "Forbidden return/monitoring/final-rank/current-return/return_since fields are removed before scoring/routing."
"prior_selected_names_by_quarter_top15_sha256": prior_hash
"new_selected_names_by_quarter_top15_sha256": new_hash
"top15_selected_rows_unchanged_from_prior_hash": prior_hash == new_hash
"target_visibility_routed_count": n
"target_actionable_research_routed_count": n
"target_buy_underwriting_routed_count": n
```

- [ ] **Step 8: Run tests**

```bash
PYTHONPATH=. /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest \
  tests/test_high_conviction_top15_backtest.py \
  tests/test_high_conviction_top15_exception_sleeve.py \
  tests/test_right_tail_scout_queues.py \
  -q
```

Expected: PASS.

- [ ] **Step 9: Regenerate historical bundle**

```bash
PYTHONPATH=. /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m tradingagents.research.fundamental.backtests.high_conviction_top15_exception_sleeve \
  --pit-panel outputs/fundamental_backtest/pit_fundamental_panel.csv \
  --prior-selected outputs/fundamental_backtest/high_conviction_top10/selected_names_by_quarter.csv \
  --out-dir outputs/fundamental_backtest/high_conviction_top15_exception_sleeve
```

- [ ] **Step 10: Validate target metrics**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 - <<'PY'
import csv
rows=list(csv.DictReader(open('outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/target_miss_rescue_audit.csv')))
visibility=sum(r['target_visibility_routed']=='1' for r in rows)
actionable=sum(r['target_actionable_research_routed']=='1' for r in rows)
buy=sum(r['target_buy_underwriting_routed']=='1' for r in rows)
print('visibility', visibility, 'actionable', actionable, 'buy', buy)
assert visibility >= 6
assert actionable >= 4
PY
```

- [ ] **Step 11: Commit**

```bash
git add tradingagents/research/fundamental/backtests/high_conviction_top15_exception_sleeve.py \
  tests/test_high_conviction_top15_backtest.py \
  outputs/fundamental_backtest/high_conviction_top15_exception_sleeve
git commit -m "feat: add right-tail visibility backtest outputs"
```

---

## Task 7: Analysis report and companion tables

**Files:**
- Modify: `scripts/analyze_fundamental_top15_exception_sleeve.py`
- Generated: `docs/research/fundamental_top15_exception_sleeve_observed_backtest_analysis.md`
- Generated: `outputs/fundamental_backtest/analysis_top15_exception/`

- [ ] **Step 1: Write failing analysis test**

```python
def test_top15_analysis_emits_queue_visibility_tables(tmp_path):
    run(bundle_dir, prior_analysis_dir, out, report)
    assert (out / "right_tail_queue_summary.csv").exists()
    assert (out / "target_visibility_metrics.csv").exists()
    assert (out / "target_miss_rescue_audit.csv").exists()
    text = report.read_text()
    assert "Right-Tail Scout + Demote Review" in text
    assert "visibility/research outputs, not buy lists" in text
    assert "visibility-routed" in text
```

- [ ] **Step 2: Extend analysis script**

Read:

```text
top15_exception_candidate_queue.csv
right_tail_scout_queue.csv
demote_review_queue.csv
right_tail_evidence_score_diagnostics.csv
target_miss_rescue_audit.csv
v4_rescue_variant_summary.csv
```

Write:

```text
right_tail_queue_summary.csv
target_visibility_metrics.csv
target_miss_rescue_audit.csv
v4_rescue_variant_summary.csv
```

Report language:

```text
These queues are visibility/research outputs, not buy lists.
A target can be visibility-routed without being selected into Top-15.
Hard-demote review counts as visibility only, not actionable research or buy underwriting.
```

Avoid:

```text
rescued CRNC
rescued BE
```

Use:

```text
routed to visibility
routed to demote review
routed to scout
selected into Top-15
```

- [ ] **Step 3: Regenerate analysis**

```bash
PYTHONPATH=. /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 scripts/analyze_fundamental_top15_exception_sleeve.py \
  --bundle-dir outputs/fundamental_backtest/high_conviction_top15_exception_sleeve \
  --prior-analysis-dir outputs/fundamental_backtest/analysis \
  --out-dir outputs/fundamental_backtest/analysis_top15_exception
```

- [ ] **Step 4: Validate analysis hashes**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 - <<'PY'
import json, hashlib
from pathlib import Path
m=json.load(open('outputs/fundamental_backtest/analysis_top15_exception/analysis_manifest.json'))
bad=[]
for p,h in m['outputs'].items():
    if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h:
        bad.append(p)
print('hash_failures', len(bad))
assert not bad
PY
```

- [ ] **Step 5: Commit**

```bash
git add scripts/analyze_fundamental_top15_exception_sleeve.py \
  tests/test_high_conviction_top15_backtest.py \
  docs/research/fundamental_top15_exception_sleeve_observed_backtest_analysis.md \
  outputs/fundamental_backtest/analysis_top15_exception
git commit -m "analysis: add right-tail visibility review"
```

---

## Task 8: Daily runbook and docs

**Files:**
- Modify: `docs/research/aeternus-daily-pipeline-debug-runbook.md`
- Modify: `docs/research/fundamental_top15_exception_sleeve_observed_backtest_analysis.md`
- Optional: `memory/2026-05-09.md`, `memory/WORKING.md`

- [ ] **Step 1: Update daily runbook**

Add:

```markdown
### Right-Tail Scout + Demote Review daily queues

Run after finalized dealflow/fundamental scores and `fundamental-top15`:

```bash
python3 -m cli.main fundamental-right-tail-queues \
  --scores-csv eval_results/fundamental/YYYY-MM-DD/fundamental_final_scores_YYYY-MM-DD.csv \
  --top15-selected-csv eval_results/fundamental/YYYY-MM-DD/high_conviction_top15.csv \
  --output-root eval_results/fundamental/YYYY-MM-DD \
  --date YYYY-MM-DD
```

Default outputs:

- `top15_exception_candidate_queue.csv`
- `right_tail_scout_queue.csv`
- `demote_review_queue.csv`
- `right_tail_evidence_score_diagnostics.csv`
- `right_tail_queues.json`

Optional historical/debug target audit:

```bash
python3 -m cli.main fundamental-right-tail-queues \
  --scores-csv eval_results/fundamental/YYYY-MM-DD/fundamental_final_scores_YYYY-MM-DD.csv \
  --top15-selected-csv eval_results/fundamental/YYYY-MM-DD/high_conviction_top15.csv \
  --target-events-csv docs/research/right_tail_target_events.csv \
  --output-root eval_results/fundamental/YYYY-MM-DD \
  --date YYYY-MM-DD
```

Without `--target-events-csv`, no `target_miss_rescue_audit.csv` is written in daily live mode.
These queues are visibility/fundamental review lists, not buy lists.
```

- [ ] **Step 2: Add final behavior statement**

Ensure report says:

```text
1. Top-10 Core: clean buy-underwriting queue.
2. Top-15 Exception Sleeve: selected right-tail exception/starter-underwriting rows; output unchanged.
3. Top-15 Exception Candidate Queue: visibility/staging only.
4. Right-Tail Scout + Demote Review: messy theme-wave / turnaround / hidden-supplier candidates too important to ignore but not automatically buys.
```

- [ ] **Step 3: Update memory files**

Record:

- files added
- target visibility/actionable counts
- verification commands
- caveat: queues are visibility/research, not buys

- [ ] **Step 4: Commit docs**

```bash
git add docs/research/aeternus-daily-pipeline-debug-runbook.md \
  docs/research/fundamental_top15_exception_sleeve_observed_backtest_analysis.md \
  memory/2026-05-09.md memory/WORKING.md
git commit -m "docs: document right-tail visibility workflow"
```

---

## Task 9: Final verification and handoff

- [ ] **Step 1: Run focused tests**

```bash
PYTHONPATH=tradingagents/research/fundamental:. /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest \
  tests/test_fundamental_high_conviction_top10.py \
  tests/test_cli_fundamental_top10.py \
  tests/test_high_conviction_top15_exception_sleeve.py \
  tests/test_high_conviction_top15_backtest.py \
  tests/test_right_tail_scout_queues.py \
  tests/test_cli_fundamental_right_tail_queues.py \
  tests/test_fundamental_demote_severity.py \
  -q
```

Expected: all pass.

- [ ] **Step 2: Regenerate backtest and analysis artifacts**

```bash
PYTHONPATH=. /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m tradingagents.research.fundamental.backtests.high_conviction_top15_exception_sleeve \
  --pit-panel outputs/fundamental_backtest/pit_fundamental_panel.csv \
  --prior-selected outputs/fundamental_backtest/high_conviction_top10/selected_names_by_quarter.csv \
  --out-dir outputs/fundamental_backtest/high_conviction_top15_exception_sleeve

PYTHONPATH=. /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 scripts/analyze_fundamental_top15_exception_sleeve.py \
  --bundle-dir outputs/fundamental_backtest/high_conviction_top15_exception_sleeve \
  --prior-analysis-dir outputs/fundamental_backtest/analysis \
  --out-dir outputs/fundamental_backtest/analysis_top15_exception
```

- [ ] **Step 3: Validate hash manifests**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 - <<'PY'
import json, hashlib
from pathlib import Path
for mf in [
    'outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/run_manifest.json',
    'outputs/fundamental_backtest/analysis_top15_exception/analysis_manifest.json',
]:
    m=json.load(open(mf))
    hashes=m.get('output_hashes') or m.get('outputs') or {}
    bad=[]
    for p,h in hashes.items():
        path=Path(p)
        if not path.exists():
            path=Path(mf).parent / p
        if hashlib.sha256(path.read_bytes()).hexdigest()!=h:
            bad.append(str(path))
    print(mf, 'hash_failures', len(bad))
    assert not bad
PY
```

Expected: `hash_failures 0` for both manifests.

- [ ] **Step 4: Validate Top-15 selected hash guard**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 - <<'PY'
import json
m=json.load(open('outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/run_manifest.json'))
print('top15_selected_rows_unchanged_from_prior_hash', m['top15_selected_rows_unchanged_from_prior_hash'])
assert m['top15_selected_rows_unchanged_from_prior_hash'] is True
assert m['prior_selected_names_by_quarter_top15_sha256'] == m['new_selected_names_by_quarter_top15_sha256']
PY
```

- [ ] **Step 5: Final git status sanity check**

```bash
git status --short
```

Expected: only unrelated pre-existing dirty files remain, or clean if isolated.

- [ ] **Step 6: Final commit if regeneration changed artifacts**

```bash
git add outputs/fundamental_backtest/high_conviction_top15_exception_sleeve \
  outputs/fundamental_backtest/analysis_top15_exception \
  docs/research/fundamental_top15_exception_sleeve_observed_backtest_analysis.md
git commit -m "data: refresh right-tail visibility artifacts"
```

Skip if no tracked changes.

- [ ] **Step 7: Push**

```bash
git push origin main
```

---

## Acceptance criteria

Implementation is complete only if:

1. Existing Top-10 and Top-15 tests pass.
2. Existing Top-15 selected rows are unchanged unless intentionally changed.
3. `right_tail_evidence_score` is computed after physically removing return, monitoring, final-rank, current-return, and `return_since_*` fields.
4. New demote severity fields are added and default safely for old rows.
5. `post_llm_demote_flag` is forced to `1` when severity is `soft`, `hard`, or `unknown`.
6. Soft demote can enter `top15_exception_candidate_queue` only if `post_llm_demote_overrideable=1` and score `>=80`.
7. Unknown demote routes only to demote review.
8. Hard demote never becomes buy-underwriting, Top-15 selected, or Top-15 candidate.
9. Daily CLI can exclude already-selected Top-15 names via `--top15-selected-csv` and warns if missing.
10. Daily CLI writes historical target audit only when `--target-events-csv` is passed.
11. At least 6 of 9 historical target events are visibility-routed.
12. At least 4 of 9 historical target events are actionable-research-routed.
13. `CRDO` remains selected in its target quarter.
14. Reports clearly state queues are visibility/research outputs, not buy lists.
15. Hash manifests validate with zero failures.

---

## Expected final handoff files

```text
tradingagents/research/fundamental/src/selection/signal_utils.py
tradingagents/research/fundamental/src/selection/right_tail_queues.py
tests/test_right_tail_scout_queues.py
tests/test_cli_fundamental_right_tail_queues.py
tests/test_fundamental_demote_severity.py
outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/top15_exception_candidate_queue.csv
outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/right_tail_scout_queue.csv
outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/demote_review_queue.csv
outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/right_tail_evidence_score_diagnostics.csv
outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/target_miss_rescue_audit.csv
outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/v4_rescue_variant_summary.csv
outputs/fundamental_backtest/analysis_top15_exception/right_tail_queue_summary.csv
outputs/fundamental_backtest/analysis_top15_exception/target_visibility_metrics.csv
outputs/fundamental_backtest/analysis_top15_exception/target_miss_rescue_audit.csv
docs/research/fundamental_top15_exception_sleeve_observed_backtest_analysis.md
```
