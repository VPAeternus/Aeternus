# Top15 Core Deterioration Refill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an opt-in shadow Top-15 refill variant that demotes validated core deterioration patterns, refills with next ex-ante eligible ranked candidates, and reports full Top-15 shadow results without changing current Top-15 v3.

**Architecture:** Keep official `high_conviction_top15_v3_exception_sleeve` untouched. Extend shared selection utilities with label-active RM/HP counting and named deterioration flags, then add a shadow selector/backtest path that builds `10` refilled core names plus `up to 5` exception names while blocking demoted/refill-ineligible deterioration tickers from exception re-entry. Return labels are attached only after selection is frozen for diagnostics.

**Tech Stack:** Python 3.14, stdlib csv/json, Typer, pytest, existing Aeternus fundamental selector/backtest modules.

---

## Required Skills

- @superpowers:test-driven-development for each code task.
- @superpowers:verification-before-completion before completion claims.
- @superpowers:subagent-driven-development or @superpowers:executing-plans for implementation.

## Critical Constraints

- Do not mutate official Top-15 v3 behavior or default CLI behavior.
- Do not change `selected_names_by_quarter_top15.csv` contents except by regenerating identical contents.
- Do not create a list larger than Top-15: shadow selected output is `10` core + `up to 5` exceptions.
- Do not let demoted/refill-ineligible deterioration tickers re-enter exception sleeve in the same shadow run.
- Do not use forward-looking columns for selection/refill/routing: `return_*`, `winner_*`, `loser_*`, `target*`, `monitoring*`, `current_return*`, `final_rank*`.
- Rank 7/8 is diagnostic metadata only. It must not trigger strict/downgrade demotion by itself.
- Shadow output is PM research/review only, not an official buy list.
- Keep unrelated IFVG / egg-info / Growth dirty files unstaged.

## Core Deterioration Flag Definitions

Implement these exact semantics in `core_deterioration_flags()`:

```text
label_active(value) = str(value).strip().lower() not in {
  "", "0", "0.0", "false", "no", "n", "none", "null", "nan", "na", "n/a"
}

rm_count = count(label_active(row[field]) for field in RM_SIGNAL_FIELDS)
hp_count = count(label_active(row[field]) for field in HP_SIGNAL_FIELDS)

high_score_deterioration_flag =
    entry_score_0_100 >= 80
    AND score_change <= -1
    AND negative_revision_risk >= 2

weak_no_theme_repricing_stack_flag =
    primary_theme blank
    AND pre_llm_fundamental_bucket = "weak"
    AND (
        rm_count >= 3
        OR (hp_count > 0 AND market_repricing_score >= 6)
    )
    AND (
        score_change <= 0
        OR negative_revision_risk >= 2
    )

core_deterioration_review_flag =
    selected_sleeve = "core"
    AND (high_score_deterioration_flag OR weak_no_theme_repricing_stack_flag)

core_deterioration_downgrade_flag =
    core_deterioration_review_flag
    AND (
        weak_no_theme_repricing_stack_flag
        OR (primary_theme blank AND pre_llm_fundamental_bucket = "weak")
    )

core_deterioration_strict_override_required =
    core_deterioration_review_flag
    AND high_score_deterioration_flag
    AND weak_no_theme_repricing_stack_flag
```

Shadow refill modes:

- `strict`: demote `core_deterioration_strict_override_required=1`.
- `downgrade`: demote `core_deterioration_downgrade_flag=1`.
- `all_review`: diagnostic broader mode; not daily default.
- Do not implement `rank78_review` as a selector mode.

## File Structure

### Modify: `tradingagents/research/fundamental/src/selection/signal_utils.py`
Responsibility: shared signal helpers.

Add label-aware helpers without changing existing `truthy()`/`signal_count()` semantics:

- `label_active(value)`
- `label_signal_count(row, fields)`

### Modify: `tradingagents/research/fundamental/src/selection/high_conviction_top10.py`
Responsibility: live selector and daily writer.

Add/update:

- Named deterioration flags in `core_deterioration_flags()`.
- Expanded `CORE_DETERIORATION_FIELDS`.
- `CORE_DETERIORATION_REFILL_FIELDS`.
- `CoreDeteriorationRefillConfig`.
- `should_refill_demote_core_row()`.
- Optional `blocked_tickers` arg in `_select_exception_sleeve()`.
- `_rank_high_conviction_core_pool()` helper preserving Top-10 public contract.
- `select_high_conviction_top15_core_deterioration_refill_shadow()`.
- `select_top15_core_deterioration_refill_shadow_from_csv()`.

### Modify: `tradingagents/research/fundamental/backtests/high_conviction_top10.py`
Responsibility: PIT Top-10 v2 ranking.

Add `_v2_candidates()` full ex-ante ranked pool and make `_select_v2()` return `_v2_candidates(rows)[:10]`.

### Modify: `tradingagents/research/fundamental/backtests/high_conviction_top15_exception_sleeve.py`
Responsibility: historical Top-15 bundle.

Add shadow files without changing official selected output:

- `core_deterioration_refill_shadow_selected.csv` — full Top-15 shadow selected rows.
- `core_deterioration_refill_shadow_replacements.csv` — PM-facing demotion/refill diagnostics.
- `core_deterioration_refill_shadow_summary.csv` — strategy metrics by shadow variant.

### Modify: `scripts/analyze_fundamental_top15_exception_sleeve.py`
Responsibility: analyst report and companion tables.

Copy/write shadow tables and add report section.

### Modify: `cli/commands/fundamental.py`
Responsibility: CLI surface.

Add separate opt-in command: `fundamental-top15-refill-shadow`.

### Modify: `docs/research/aeternus-daily-pipeline-debug-runbook.md`
Responsibility: daily operator instructions.

Add optional shadow command and review order.

### Tests

Modify:

- `tests/test_high_conviction_top15_exception_sleeve.py`
- `tests/test_high_conviction_top15_backtest.py`

Create:

- `tests/test_cli_fundamental_top15_refill_shadow.py`

---

## Task 1: Add Label-Active Counts and Named Deterioration Flags

**Files:**
- Modify: `tradingagents/research/fundamental/src/selection/signal_utils.py`
- Modify: `tradingagents/research/fundamental/src/selection/high_conviction_top10.py`
- Test: `tests/test_high_conviction_top15_exception_sleeve.py`

- [ ] **Step 1: Write failing tests for descriptive RM/HP label counting and named flags**

Append to `tests/test_high_conviction_top15_exception_sleeve.py`:

```python
def test_core_deterioration_flags_count_descriptive_rm_hp_labels():
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import core_deterioration_flags

    candidate = row(
        "STACK",
        82,
        selected_sleeve="core",
        selected_sleeve_rank="4",
        selection_rank="4",
        score_change="-2",
        negative_revision_risk="2",
        pre_llm_fundamental_bucket="weak",
        primary_theme="",
        rm1_low_price_dislocation_momentum="RM1 - Low-price dislocation momentum",
        rm2_weak_acceleration="RM2 - Weak-bucket acceleration",
        rm4_persistent_repricing_wave="RM4 - Persistent repricing wave",
    )

    flags = core_deterioration_flags(candidate)

    assert flags["core_deterioration_rm_count"] == 3
    assert flags["core_deterioration_hp_count"] == 0
    assert flags["high_score_deterioration_flag"] == 1
    assert flags["weak_no_theme_repricing_stack_flag"] == 1
    assert flags["core_deterioration_review_flag"] == 1
    assert flags["core_deterioration_downgrade_flag"] == 1
    assert flags["core_deterioration_strict_override_required"] == 1


def test_rank_7_8_alone_does_not_trigger_core_deterioration_flags():
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import core_deterioration_flags

    clean = row(
        "CLEAN",
        90,
        selected_sleeve="core",
        selected_sleeve_rank="7",
        selection_rank="7",
        score_change="1",
        negative_revision_risk="0",
        pre_llm_fundamental_bucket="strong",
        primary_theme="AI infrastructure",
    )

    flags = core_deterioration_flags(clean)

    assert flags["core_deterioration_rank_context_flag"] == 1
    assert flags["core_deterioration_review_flag"] == 0
    assert flags["core_deterioration_downgrade_flag"] == 0
    assert flags["core_deterioration_strict_override_required"] == 0
```

- [ ] **Step 2: Update existing strict review test for new strict semantics**

In existing `test_core_deterioration_review_queue_flags_strict_core_rows()`, keep the strict expectation but add the weak-stack RM labels to the flagged row:

```python
rows[6].update(
    score_change="-2",
    negative_revision_risk="2",
    pre_llm_fundamental_bucket="weak",
    primary_theme="",
    rm1_low_price_dislocation_momentum="RM1 - Low-price dislocation momentum",
    rm2_weak_acceleration="RM2 - Weak-bucket acceleration",
    rm4_persistent_repricing_wave="RM4 - Persistent repricing wave",
)
```

This prevents the old test from expecting `strict=1` for high-score deterioration without weak-stack confirmation.

- [ ] **Step 3: Run tests to verify failure**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest \
  tests/test_high_conviction_top15_exception_sleeve.py::test_core_deterioration_flags_count_descriptive_rm_hp_labels \
  tests/test_high_conviction_top15_exception_sleeve.py::test_rank_7_8_alone_does_not_trigger_core_deterioration_flags \
  tests/test_high_conviction_top15_exception_sleeve.py::test_core_deterioration_review_queue_flags_strict_core_rows -q
```

Expected: FAIL because named fields/count semantics do not exist yet.

- [ ] **Step 4: Implement label-active helpers**

In `signal_utils.py`, add after `truthy()`:

```python
_FALSE_LABELS = {"", "0", "0.0", "false", "no", "n", "none", "null", "nan", "na", "n/a"}


def label_active(value: Any) -> bool:
    text = str(value if value is not None else "").strip().lower()
    return text not in _FALSE_LABELS


def label_signal_count(row: Mapping[str, Any], fields: Sequence[str]) -> int:
    return len([field for field in fields if field in row and label_active(row.get(field))])
```

- [ ] **Step 5: Implement named deterioration flags**

In `high_conviction_top10.py`, import `label_signal_count` from `.signal_utils`.

Replace `CORE_DETERIORATION_FIELDS` with:

```python
CORE_DETERIORATION_FIELDS = [
    "ticker",
    "quarter",
    "selection_rank",
    "selected_sleeve",
    "entry_score_0_100",
    "score_change",
    "negative_revision_risk",
    "pre_llm_fundamental_bucket",
    "primary_theme",
    "core_deterioration_rm_count",
    "core_deterioration_hp_count",
    "demoted_market_repricing_score",
    "high_score_deterioration_flag",
    "weak_no_theme_repricing_stack_flag",
    "core_deterioration_rank_context_flag",
    "core_deterioration_review_flag",
    "core_deterioration_downgrade_flag",
    "core_deterioration_strict_override_required",
    "core_deterioration_recommended_action",
    "core_deterioration_reason_codes",
]
```

Replace `core_deterioration_flags()` with:

```python
def core_deterioration_flags(row: Mapping[str, Any]) -> dict[str, Any]:
    sleeve = str(row.get("selected_sleeve", "")).strip().lower()
    selected_rank = to_float(row.get("selection_rank") or row.get("selected_sleeve_rank"))
    rank_int = int(selected_rank) if selected_rank is not None else None
    entry_score = to_float(row.get("entry_score_0_100") or row.get("score"))
    score_change = to_float(row.get("score_change"))
    negative_revision_risk = to_float(row.get("negative_revision_risk"))
    market_repricing_score = to_float(row.get("market_repricing_score")) or 0.0
    theme_blank = not str(row.get("primary_theme") or "").strip()
    weak_pre_llm = str(row.get("pre_llm_fundamental_bucket") or "").strip().lower() == "weak"
    rm_count = label_signal_count(row, RM_SIGNAL_FIELDS)
    hp_count = label_signal_count(row, HP_SIGNAL_FIELDS)

    high_score = bool(
        entry_score is not None and entry_score >= 80
        and score_change is not None and score_change <= -1
        and negative_revision_risk is not None and negative_revision_risk >= 2
    )
    weak_stack = bool(
        theme_blank
        and weak_pre_llm
        and (rm_count >= 3 or (hp_count > 0 and market_repricing_score >= 6))
        and (
            (score_change is not None and score_change <= 0)
            or (negative_revision_risk is not None and negative_revision_risk >= 2)
        )
    )
    review = bool(sleeve == "core" and (high_score or weak_stack))
    downgrade = bool(review and (weak_stack or (theme_blank and weak_pre_llm)))
    strict = bool(review and high_score and weak_stack)
    rank_context = bool(rank_int in {7, 8})

    reasons: list[str] = []
    if high_score:
        reasons.append("high_score_deterioration")
    if weak_stack:
        reasons.append("weak_no_theme_repricing_stack")
    if rank_context:
        reasons.append("rank_7_8_context_only")
    if theme_blank:
        reasons.append("primary_theme_blank")
    if weak_pre_llm:
        reasons.append("pre_llm_fundamental_bucket_weak")
    if rm_count >= 3:
        reasons.append("rm_count_gte_3")
    if hp_count > 0 and market_repricing_score >= 6:
        reasons.append("hp_count_gt_0_and_market_repricing_gte_6")

    action = CORE_DETERIORATION_STRICT_ACTION if strict else CORE_DETERIORATION_REVIEW_ACTION if review else ""
    return {
        "core_deterioration_rm_count": rm_count,
        "core_deterioration_hp_count": hp_count,
        "demoted_market_repricing_score": market_repricing_score,
        "high_score_deterioration_flag": int(high_score),
        "weak_no_theme_repricing_stack_flag": int(weak_stack),
        "core_deterioration_rank_context_flag": int(rank_context),
        "core_deterioration_review_flag": int(review),
        "core_deterioration_downgrade_flag": int(downgrade),
        "core_deterioration_strict_override_required": int(strict),
        "core_deterioration_recommended_action": action,
        "core_deterioration_reason_codes": ";".join(reasons) if review else "",
    }
```

Update `build_core_deterioration_review_rows()` to carry new fields automatically via `**flags`. Ensure `demoted_market_repricing_score` appears in output with the value from flags.

- [ ] **Step 6: Run focused tests**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest \
  tests/test_high_conviction_top15_exception_sleeve.py::test_core_deterioration_flags_count_descriptive_rm_hp_labels \
  tests/test_high_conviction_top15_exception_sleeve.py::test_rank_7_8_alone_does_not_trigger_core_deterioration_flags \
  tests/test_high_conviction_top15_exception_sleeve.py::test_core_deterioration_review_queue_flags_strict_core_rows -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tradingagents/research/fundamental/src/selection/signal_utils.py tradingagents/research/fundamental/src/selection/high_conviction_top10.py tests/test_high_conviction_top15_exception_sleeve.py
git commit -m "feat: define core deterioration patterns"
```

---

## Task 2: Add Refill Predicate and Exception Blocker

**Files:**
- Modify: `tradingagents/research/fundamental/src/selection/high_conviction_top10.py`
- Test: `tests/test_high_conviction_top15_exception_sleeve.py`

- [ ] **Step 1: Write failing tests for refill modes**

Append:

```python
def test_should_refill_demote_core_row_uses_bad_feature_combos_not_rank():
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import should_refill_demote_core_row

    strict_combo = row(
        "STRICT",
        85,
        selected_sleeve="core",
        selection_rank="4",
        selected_sleeve_rank="4",
        score_change="-2",
        negative_revision_risk="2",
        pre_llm_fundamental_bucket="weak",
        primary_theme="",
        rm1_low_price_dislocation_momentum="RM1 - Low-price dislocation momentum",
        rm2_weak_acceleration="RM2 - Weak-bucket acceleration",
        rm4_persistent_repricing_wave="RM4 - Persistent repricing wave",
    )
    rank_only = row(
        "RANK7",
        90,
        selected_sleeve="core",
        selection_rank="7",
        selected_sleeve_rank="7",
        score_change="1",
        negative_revision_risk="0",
        pre_llm_fundamental_bucket="strong",
        primary_theme="AI infrastructure",
    )

    assert should_refill_demote_core_row(strict_combo, "strict") is True
    assert should_refill_demote_core_row(strict_combo, "downgrade") is True
    assert should_refill_demote_core_row(rank_only, "strict") is False
    assert should_refill_demote_core_row(rank_only, "downgrade") is False


def test_should_refill_demote_core_row_allows_downgrade_without_strict_stack():
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import should_refill_demote_core_row

    high_score_blank_weak = row(
        "DOWN",
        85,
        selected_sleeve="core",
        selection_rank="3",
        selected_sleeve_rank="3",
        score_change="-2",
        negative_revision_risk="2",
        pre_llm_fundamental_bucket="weak",
        primary_theme="",
    )

    assert should_refill_demote_core_row(high_score_blank_weak, "strict") is False
    assert should_refill_demote_core_row(high_score_blank_weak, "downgrade") is True
```

- [ ] **Step 2: Write failing test for exception blocker**

Append:

```python
def test_exception_sleeve_blocks_explicit_deterioration_tickers():
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import RightTailExceptionConfig, _select_exception_sleeve

    core_rows = [row(f"C{i}", 100 - i) for i in range(10)]
    all_rows = core_rows + [
        row("BAD", 80, rm1_low_price_dislocation_momentum="1", primary_theme="AI"),
        row("GOOD", 50, rm1_low_price_dislocation_momentum="1", primary_theme="energy"),
    ]

    exceptions, _ = _select_exception_sleeve(
        core_rows,
        all_rows,
        RightTailExceptionConfig(enabled=True, exception_slots=1),
        blocked_tickers={"BAD"},
    )

    assert [r["ticker"] for r in exceptions] == ["GOOD"]
```

- [ ] **Step 3: Run tests to verify failure**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest \
  tests/test_high_conviction_top15_exception_sleeve.py::test_should_refill_demote_core_row_uses_bad_feature_combos_not_rank \
  tests/test_high_conviction_top15_exception_sleeve.py::test_should_refill_demote_core_row_allows_downgrade_without_strict_stack \
  tests/test_high_conviction_top15_exception_sleeve.py::test_exception_sleeve_blocks_explicit_deterioration_tickers -q
```

Expected: FAIL because predicate/blocker does not exist.

- [ ] **Step 4: Implement refill config and predicate**

In `high_conviction_top10.py`, add near deterioration constants:

```python
CORE_DETERIORATION_REFILL_MODES = {"strict", "downgrade", "all_review"}
CORE_DETERIORATION_REFILL_FIELDS = [
    "variant",
    "quarter",
    "mode",
    "demoted_ticker",
    "replacement_ticker",
    "demoted_core_candidate_rank",
    "replacement_core_candidate_rank",
    "demoted_entry_score_0_100",
    "replacement_entry_score_0_100",
    "demoted_score_change",
    "demoted_negative_revision_risk",
    "demoted_pre_llm_fundamental_bucket",
    "demoted_primary_theme",
    "demoted_rm_count",
    "demoted_hp_count",
    "demoted_market_repricing_score",
    "high_score_deterioration_flag",
    "weak_no_theme_repricing_stack_flag",
    "core_deterioration_review_flag",
    "core_deterioration_downgrade_flag",
    "core_deterioration_strict_override_required",
    "core_deterioration_reason_codes",
    "demoted_return_90d_pct",
    "replacement_return_90d_pct",
    "replacement_delta_90d_pct",
]


@dataclass(frozen=True)
class CoreDeteriorationRefillConfig:
    enabled: bool = False
    mode: str = "strict"
    block_deterioration_from_exceptions: bool = True


def _normalize_core_deterioration_refill_config(config: Mapping[str, Any] | None) -> CoreDeteriorationRefillConfig:
    nested = config.get("core_deterioration_refill") if isinstance(config, Mapping) and isinstance(config.get("core_deterioration_refill"), Mapping) else config
    enabled = bool(nested.get("enabled", False)) if isinstance(nested, Mapping) else False
    mode = str(nested.get("mode", "strict") if isinstance(nested, Mapping) else "strict").strip().lower()
    if mode not in CORE_DETERIORATION_REFILL_MODES:
        raise ValueError(f"core deterioration refill mode must be one of {sorted(CORE_DETERIORATION_REFILL_MODES)}")
    block = bool(nested.get("block_deterioration_from_exceptions", True)) if isinstance(nested, Mapping) else True
    return CoreDeteriorationRefillConfig(enabled=enabled, mode=mode, block_deterioration_from_exceptions=block)


def should_refill_demote_core_row(row: Mapping[str, Any], mode: str = "strict") -> bool:
    mode = str(mode or "strict").strip().lower()
    if mode not in CORE_DETERIORATION_REFILL_MODES:
        raise ValueError(f"core deterioration refill mode must be one of {sorted(CORE_DETERIORATION_REFILL_MODES)}")
    flags = core_deterioration_flags(row)
    if mode == "strict":
        return bool(flags.get("core_deterioration_strict_override_required"))
    if mode == "downgrade":
        return bool(flags.get("core_deterioration_downgrade_flag"))
    return bool(flags.get("core_deterioration_review_flag"))
```

- [ ] **Step 5: Add optional exception blocker**

Update `_select_exception_sleeve()` signature:

```python
def _select_exception_sleeve(
    core_rows: Sequence[Mapping[str, Any]],
    all_rows: Sequence[Mapping[str, Any]],
    cfg: RightTailExceptionConfig,
    coverage: dict[str, dict[str, int]] | None = None,
    coverage_enabled: bool = False,
    blocked_tickers: set[str] | None = None,
) -> tuple[list[dict], list[str]]:
    core_tickers = {str(r.get("ticker", "")).upper() for r in core_rows}
    core_tickers |= {str(t).upper() for t in (blocked_tickers or set())}
```

Do not change existing call behavior when `blocked_tickers` is omitted.

- [ ] **Step 6: Run tests**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest \
  tests/test_high_conviction_top15_exception_sleeve.py::test_should_refill_demote_core_row_uses_bad_feature_combos_not_rank \
  tests/test_high_conviction_top15_exception_sleeve.py::test_should_refill_demote_core_row_allows_downgrade_without_strict_stack \
  tests/test_high_conviction_top15_exception_sleeve.py::test_exception_sleeve_blocks_explicit_deterioration_tickers -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tradingagents/research/fundamental/src/selection/high_conviction_top10.py tests/test_high_conviction_top15_exception_sleeve.py
git commit -m "feat: add deterioration refill predicate"
```

---

## Task 3: Expose Live Ranked Core Pool Without Changing Top-10 Contract

**Files:**
- Modify: `tradingagents/research/fundamental/src/selection/high_conviction_top10.py`
- Test: `tests/test_high_conviction_top15_exception_sleeve.py`

- [ ] **Step 1: Write failing contract test**

Append:

```python
def test_rank_high_conviction_core_pool_matches_top10_contract():
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import _rank_high_conviction_core_pool, select_high_conviction_top10

    rows = [row(f"C{i}", 100 - i) for i in range(12)]
    pool = _rank_high_conviction_core_pool(rows, {"top_n": 10}, None)
    top10 = select_high_conviction_top10(rows, {"top_n": 10})

    assert [r["ticker"] for r in pool["ranked_rows"][:10]] == [r["ticker"] for r in top10["selected_rows"]]
    assert [r["core_candidate_rank"] for r in pool["ranked_rows"][:3]] == [1, 2, 3]
    assert top10["summary"]["selected_count"] == 10
    assert all(r["selected"] is True for r in top10["selected_rows"])
```

- [ ] **Step 2: Run test to verify failure**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest \
  tests/test_high_conviction_top15_exception_sleeve.py::test_rank_high_conviction_core_pool_matches_top10_contract -q
```

Expected: FAIL because helper does not exist.

- [ ] **Step 3: Add helper**

Add before `select_high_conviction_top10()`:

```python
def _rank_high_conviction_core_pool(
    rows: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any] | None,
    coverage_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    cfg = normalize_config(config)
    coverage_enabled = bool(cfg.get("coverage_gating"))
    coverage = _build_coverage(coverage_rows or []) if coverage_enabled else {}
    eligible: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    warnings: list[str] = []

    for idx, raw in enumerate(rows):
        assessed = _assess_row(dict(raw), idx, cfg, coverage, coverage_enabled)
        if assessed["selected_candidate"]:
            eligible.append(assessed)
        else:
            rejected.append(assessed)

    ranked = sorted(
        eligible,
        key=lambda r: (-r["composite_score"], -r["score"], -r["confidence_sort"], r["ticker"]),
    )
    for rank, row in enumerate(ranked, start=1):
        row["core_candidate_rank"] = rank
    return {
        "ranked_rows": ranked,
        "rejected_rows": rejected,
        "warnings": warnings,
        "config_snapshot": cfg,
    }
```

Replace the entire `select_high_conviction_top10()` function with this exact implementation:

```python
def select_high_conviction_top10(
    rows: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any] | None,
    coverage_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Select high-conviction rows after final fundamental scores are already computed."""
    pool = _rank_high_conviction_core_pool(rows, config, coverage_rows)
    cfg = pool["config_snapshot"]
    ranked = pool["ranked_rows"]
    rejected = list(pool["rejected_rows"])
    warnings = list(pool["warnings"])

    selected = ranked[: int(cfg["top_n"])]
    _annotate_soft_balance(selected, cfg, warnings)
    selected_ids = {r["_row_id"] for r in selected}
    for rank, row in enumerate(selected, start=1):
        row["selection_rank"] = rank
        row["selected"] = True
        _annotate_operating_guidance(row)
    for row in ranked:
        if row["_row_id"] not in selected_ids:
            row["selected"] = False
            row["reason_codes"].append("NOT_IN_TOP_N")
            rejected.append(row)

    if len(selected) < int(cfg["top_n"]):
        warnings.append(f"SHORTFALL_SELECTED_{len(selected)}_OF_{cfg['top_n']}")

    selected_public = [_public_row(r) for r in selected]
    rejected_public = [_public_row(r) for r in rejected]
    return {
        "selected_rows": selected_public,
        "rejected_rows": rejected_public,
        "selected": selected_public,
        "rejected": rejected_public,
        "summary": {
            "input_count": len(rows),
            "eligible_count": len(ranked),
            "selected_count": len(selected),
            "rejected_count": len(rejected),
            "top_n": cfg["top_n"],
            "warnings": warnings,
        },
        "config_snapshot": cfg,
        "config": cfg,
        "operating_recommendation": _operating_recommendation_snapshot(selected_public, cfg),
    }
```

- [ ] **Step 4: Run focused Top-10/Top-15 contract tests**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest \
  tests/test_high_conviction_top15_exception_sleeve.py::test_rank_high_conviction_core_pool_matches_top10_contract \
  tests/test_high_conviction_top15_exception_sleeve.py::test_top15_preserves_top10_when_exception_disabled \
  tests/test_fundamental_high_conviction_top10.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/research/fundamental/src/selection/high_conviction_top10.py tests/test_high_conviction_top15_exception_sleeve.py
git commit -m "refactor: expose high conviction core pool"
```

---

## Task 4: Add Live Full Top-15 Shadow Refill Selector and Daily Writer

**Files:**
- Modify: `tradingagents/research/fundamental/src/selection/high_conviction_top10.py`
- Test: `tests/test_high_conviction_top15_exception_sleeve.py`

- [ ] **Step 1: Write failing test for full shadow refill**

Append:

```python
def test_top15_refill_shadow_outputs_full_top15_with_replacement_and_exception():
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import select_high_conviction_top15_core_deterioration_refill_shadow

    rows = [row(f"C{i}", 100 - i) for i in range(9)]
    rows.insert(5, row(
        "BAD",
        95,
        score_change="-2",
        negative_revision_risk="2",
        pre_llm_fundamental_bucket="weak",
        primary_theme="",
        rm1_low_price_dislocation_momentum="RM1 - Low-price dislocation momentum",
        rm2_weak_acceleration="RM2 - Weak-bucket acceleration",
        rm4_persistent_repricing_wave="RM4 - Persistent repricing wave",
    ))
    rows += [
        row("NEXT", 89),
        row("GOODX", 50, rm1_low_price_dislocation_momentum="1", primary_theme="AI"),
    ]

    result = select_high_conviction_top15_core_deterioration_refill_shadow(
        rows,
        {"enabled": True, "exception_slots": 1, "core_deterioration_refill": {"enabled": True, "mode": "strict"}},
    )

    assert "BAD" not in [r["ticker"] for r in result["selected_rows"]]
    assert "NEXT" in [r["ticker"] for r in result["core_rows"]]
    assert [r["ticker"] for r in result["exception_rows"]] == ["GOODX"]
    assert result["summary"]["core_count"] == 10
    assert result["summary"]["exception_count"] == 1
    assert result["summary"]["selected_count"] == 11
    assert result["core_deterioration_refill_rows"][0]["demoted_ticker"] == "BAD"
    assert result["core_deterioration_refill_rows"][0]["replacement_ticker"] == "NEXT"
```

- [ ] **Step 2: Write no-leakage replacement test**

Append:

```python
def test_top15_refill_shadow_replacement_uses_ex_ante_rank_not_return_labels():
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import select_high_conviction_top15_core_deterioration_refill_shadow

    rows = [row(f"C{i}", 100 - i) for i in range(9)]
    rows.insert(5, row(
        "BAD",
        95,
        return_90d_pct="-40",
        score_change="-2",
        negative_revision_risk="2",
        pre_llm_fundamental_bucket="weak",
        primary_theme="",
        rm1_low_price_dislocation_momentum="RM1 - Low-price dislocation momentum",
        rm2_weak_acceleration="RM2 - Weak-bucket acceleration",
        rm4_persistent_repricing_wave="RM4 - Persistent repricing wave",
    ))
    rows += [
        row("NEXT", 89, return_90d_pct="100"),
        row("LOWER", 70, return_90d_pct="300"),
    ]

    result = select_high_conviction_top15_core_deterioration_refill_shadow(
        rows,
        {"enabled": True, "exception_slots": 0, "core_deterioration_refill": {"enabled": True, "mode": "strict"}},
    )

    assert result["core_deterioration_refill_rows"][0]["replacement_ticker"] == "NEXT"
    assert "LOWER" not in [r["ticker"] for r in result["selected_rows"]]
```

- [ ] **Step 3: Write test that below-cutoff deterioration cannot enter exceptions**

Append:

```python
def test_top15_refill_shadow_blocks_below_cutoff_deterioration_from_exceptions():
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import select_high_conviction_top15_core_deterioration_refill_shadow

    rows = [row(f"C{i}", 100 - i) for i in range(10)]
    rows += [
        row(
            "BADX",
            85,
            score_change="-2",
            negative_revision_risk="2",
            pre_llm_fundamental_bucket="weak",
            primary_theme="",
            rm1_low_price_dislocation_momentum="RM1 - Low-price dislocation momentum",
            rm2_weak_acceleration="RM2 - Weak-bucket acceleration",
            rm4_persistent_repricing_wave="RM4 - Persistent repricing wave",
        ),
        row("GOODX", 50, rm1_low_price_dislocation_momentum="1", primary_theme="AI"),
    ]

    result = select_high_conviction_top15_core_deterioration_refill_shadow(
        rows,
        {"enabled": True, "exception_slots": 1, "core_deterioration_refill": {"enabled": True, "mode": "strict"}},
    )

    assert "BADX" not in [r["ticker"] for r in result["selected_rows"]]
    assert [r["ticker"] for r in result["exception_rows"]] == ["GOODX"]
```

- [ ] **Step 4: Write core-ineligible deterioration exception-blocking test**

Append:

```python
def test_top15_refill_shadow_blocks_core_ineligible_deterioration_from_exceptions():
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import select_high_conviction_top15_core_deterioration_refill_shadow

    rows = [row(f"C{i}", 100 - i) for i in range(10)]
    rows += [
        row(
            "BADX",
            85,
            1,
            score_change="-2",
            negative_revision_risk="2",
            pre_llm_fundamental_bucket="weak",
            primary_theme="",
            rm1_low_price_dislocation_momentum="RM1 - Low-price dislocation momentum",
            rm2_weak_acceleration="RM2 - Weak-bucket acceleration",
            rm4_persistent_repricing_wave="RM4 - Persistent repricing wave",
        ),
        row("GOODX", 50, rm1_low_price_dislocation_momentum="1", primary_theme="AI"),
    ]

    result = select_high_conviction_top15_core_deterioration_refill_shadow(
        rows,
        {"enabled": True, "exception_slots": 1, "core_deterioration_refill": {"enabled": True, "mode": "strict"}},
    )

    assert "BADX" not in [r["ticker"] for r in result["selected_rows"]]
    assert [r["ticker"] for r in result["exception_rows"]] == ["GOODX"]
```

- [ ] **Step 5: Write coverage-gating regression test**

Append:

```python
def test_top15_refill_shadow_exception_sleeve_respects_coverage_gate():
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import select_high_conviction_top15_core_deterioration_refill_shadow

    rows = [row(f"C{i}", 100 - i) for i in range(10)] + [
        row("BAD", 80, rm1_low_price_dislocation_momentum="1", primary_theme="AI"),
        row("GOOD", 50, rm1_low_price_dislocation_momentum="1", primary_theme="energy"),
    ]
    coverage_rows = [
        *[{"ticker": f"C{i}", "status": "CACHED_READY"} for i in range(10)],
        {"ticker": "BAD", "status": "NEEDS_FETCH"},
        {"ticker": "GOOD", "status": "CACHED_READY"},
    ]

    result = select_high_conviction_top15_core_deterioration_refill_shadow(
        rows,
        {"enabled": True, "exception_slots": 1, "coverage_gating": True, "core_deterioration_refill": {"enabled": True, "mode": "strict"}},
        coverage_rows,
    )

    assert [r["ticker"] for r in result["exception_rows"]] == ["GOOD"]
```

- [ ] **Step 6: Run tests to verify failure**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest \
  tests/test_high_conviction_top15_exception_sleeve.py::test_top15_refill_shadow_outputs_full_top15_with_replacement_and_exception \
  tests/test_high_conviction_top15_exception_sleeve.py::test_top15_refill_shadow_replacement_uses_ex_ante_rank_not_return_labels \
  tests/test_high_conviction_top15_exception_sleeve.py::test_top15_refill_shadow_blocks_below_cutoff_deterioration_from_exceptions \
  tests/test_high_conviction_top15_exception_sleeve.py::test_top15_refill_shadow_blocks_core_ineligible_deterioration_from_exceptions \
  tests/test_high_conviction_top15_exception_sleeve.py::test_top15_refill_shadow_exception_sleeve_respects_coverage_gate -q
```

Expected: FAIL because selector does not exist.

- [ ] **Step 7: Implement live shadow selector**

In `high_conviction_top10.py`, ensure the existing dataclass import includes `asdict`:

```python
from dataclasses import asdict, dataclass
```

Then add:

```python
TOP15_REFILL_SHADOW_SETTING = "high_conviction_top15_v4_core_deterioration_refill_shadow"


def _core_flag_row(row: Mapping[str, Any], rank: int) -> dict[str, Any]:
    out = dict(row)
    out["selected_sleeve"] = "core"
    out["selection_rank"] = rank
    out["selected_sleeve_rank"] = rank
    return out


def _replacement_diagnostic(mode: str, demoted: Mapping[str, Any], replacement: Mapping[str, Any] | None = None) -> dict[str, Any]:
    flags = core_deterioration_flags(demoted)
    return {
        "variant": TOP15_REFILL_SHADOW_SETTING,
        "quarter": demoted.get("quarter", ""),
        "mode": mode,
        "demoted_ticker": str(demoted.get("ticker", "")).upper(),
        "replacement_ticker": str((replacement or {}).get("ticker", "")).upper(),
        "demoted_core_candidate_rank": demoted.get("core_candidate_rank", demoted.get("selection_rank", "")),
        "replacement_core_candidate_rank": (replacement or {}).get("core_candidate_rank", ""),
        "demoted_entry_score_0_100": demoted.get("entry_score_0_100", demoted.get("score", "")),
        "replacement_entry_score_0_100": (replacement or {}).get("entry_score_0_100", (replacement or {}).get("score", "")),
        "demoted_score_change": demoted.get("score_change", ""),
        "demoted_negative_revision_risk": demoted.get("negative_revision_risk", ""),
        "demoted_pre_llm_fundamental_bucket": demoted.get("pre_llm_fundamental_bucket", ""),
        "demoted_primary_theme": demoted.get("primary_theme", ""),
        "demoted_rm_count": flags.get("core_deterioration_rm_count", ""),
        "demoted_hp_count": flags.get("core_deterioration_hp_count", ""),
        "demoted_market_repricing_score": flags.get("demoted_market_repricing_score", ""),
        "high_score_deterioration_flag": flags.get("high_score_deterioration_flag", 0),
        "weak_no_theme_repricing_stack_flag": flags.get("weak_no_theme_repricing_stack_flag", 0),
        "core_deterioration_review_flag": flags.get("core_deterioration_review_flag", 0),
        "core_deterioration_downgrade_flag": flags.get("core_deterioration_downgrade_flag", 0),
        "core_deterioration_strict_override_required": flags.get("core_deterioration_strict_override_required", 0),
        "core_deterioration_reason_codes": flags.get("core_deterioration_reason_codes", ""),
        "demoted_return_90d_pct": "",
        "replacement_return_90d_pct": "",
        "replacement_delta_90d_pct": "",
    }


def select_high_conviction_top15_core_deterioration_refill_shadow(
    rows: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any] | None,
    coverage_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    config_map = config or {}
    cfg = _normalize_exception_config(config_map)
    refill_cfg = _normalize_core_deterioration_refill_config(config_map)
    if not refill_cfg.enabled:
        raise ValueError("core deterioration refill shadow requires core_deterioration_refill.enabled=true")

    core_config = dict(config_map)
    core_config["top_n"] = int(cfg.core_n)
    coverage_enabled = bool(core_config.get("coverage_gating", False))
    coverage = _build_coverage(coverage_rows or []) if coverage_enabled else {}
    pool = _rank_high_conviction_core_pool(rows, core_config, coverage_rows)
    ranked = pool["ranked_rows"]
    selected_core_raw: list[dict[str, Any]] = []
    demoted_raw: list[dict[str, Any]] = []
    blocked_tickers: set[str] = set()

    # First scan the full input universe, not just the core-ranked pool, so core-ineligible
    # deterioration-pattern rows cannot bypass refill logic and enter exceptions.
    flagged_by_ticker: dict[str, dict[str, Any]] = {}
    for raw in rows:
        candidate = dict(raw)
        ticker = str(candidate.get("ticker") or candidate.get("symbol") or "").upper()
        if not ticker:
            continue
        candidate["ticker"] = ticker
        candidate_for_flags = _core_flag_row(candidate, 999999)
        if should_refill_demote_core_row(candidate_for_flags, refill_cfg.mode):
            blocked_tickers.add(ticker)
            flagged_by_ticker[ticker] = candidate_for_flags

    for candidate in ranked:
        ticker = str(candidate.get("ticker", "")).upper()
        candidate_rank = int(to_float(candidate.get("core_candidate_rank")) or 999999)
        if ticker in blocked_tickers:
            if candidate_rank <= int(cfg.core_n):
                demoted_raw.append(_core_flag_row(candidate, candidate_rank))
            continue
        selected_core_raw.append(candidate)
        if len(selected_core_raw) >= int(cfg.core_n):
            break

    core_rows: list[dict[str, Any]] = []
    replacements_raw = [r for r in selected_core_raw if int(to_float(r.get("core_candidate_rank")) or 999999) > int(cfg.core_n)]
    replacement_diagnostics: list[dict[str, Any]] = []
    shadow_warnings = list(pool.get("warnings", []))
    if len(selected_core_raw) < int(cfg.core_n):
        shadow_warnings.append(f"CORE_REFILL_SHORTFALL_SELECTED_{len(selected_core_raw)}_OF_{cfg.core_n}")

    for rank, raw in enumerate(selected_core_raw[: int(cfg.core_n)], start=1):
        out = dict(raw)
        out["selected_sleeve"] = "core"
        out["selected_sleeve_rank"] = rank
        out["selection_rank"] = rank
        out["portfolio_treatment"] = "core_buy_underwriting"
        out["core_deterioration_refill_shadow"] = 1
        out["core_refill_source"] = "next_ranked_core_candidate" if int(to_float(raw.get("core_candidate_rank")) or rank) > int(cfg.core_n) else "original_top10"
        out.setdefault("right_tail_exception_score", "")
        out.setdefault("right_tail_exception_reason_codes", [])
        out.setdefault("right_tail_exception_warning_codes", [])
        _annotate_operating_guidance(out)
        core_rows.append(_public_row(out))

    for idx, demoted in enumerate(demoted_raw):
        replacement = replacements_raw[idx] if idx < len(replacements_raw) else None
        replacement_diagnostics.append(_replacement_diagnostic(refill_cfg.mode, demoted, replacement))

    exceptions, warnings = ([], ["EXCEPTION_SLEEVE_DISABLED"]) if not cfg.enabled else _select_exception_sleeve(
        core_rows,
        rows,
        cfg,
        coverage=coverage,
        coverage_enabled=coverage_enabled,
        blocked_tickers=blocked_tickers if refill_cfg.block_deterioration_from_exceptions else set(),
    )
    selected = core_rows + exceptions
    for row in selected:
        row["operating_setting"] = TOP15_REFILL_SHADOW_SETTING
        row["operating_setting_validation_status"] = "shadow_observed_data_not_approved_operating_selector"

    return {
        "selected_rows": selected,
        "selected": selected,
        "core_rows": core_rows,
        "exception_rows": exceptions,
        "core_deterioration_refill_rows": replacement_diagnostics,
        "core_deterioration_refill_summary": {
            "mode": refill_cfg.mode,
            "demoted_count": len(demoted_raw),
            "replacement_count": len(replacements_raw),
            "blocked_from_exception_count": len(blocked_tickers),
        },
        "summary": {
            "input_count": len(rows),
            "selected_count": len(selected),
            "core_count": len(core_rows),
            "exception_count": len(exceptions),
            "top_n": len(selected),
            "warnings": shadow_warnings + warnings,
        },
        "config_snapshot": {**pool.get("config_snapshot", {}), "right_tail_exception_config": asdict(cfg), "core_deterioration_refill": asdict(refill_cfg)},
    }
```

- [ ] **Step 8: Harden fixed-field CSV writing and add daily CSV writer**

First update `_write_csv_with_fields()` so extra diagnostic keys cannot crash `DictWriter`:

```python
def _write_csv_with_fields(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    fields = list(fieldnames)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v for k, v in row.items() if k in fields})
```

Then add near `select_top15_from_csv()`:

```python
def select_top15_core_deterioration_refill_shadow_from_csv(
    scores_csv: str | Path,
    output_root: str | Path,
    config: Mapping[str, Any] | None,
    coverage_manifest: str | Path | None = None,
) -> dict[str, Any]:
    scores_path = Path(scores_csv)
    out_root = Path(output_root)
    rows = _read_csv(scores_path)
    coverage_rows = _read_csv(Path(coverage_manifest)) if coverage_manifest else None
    result = select_high_conviction_top15_core_deterioration_refill_shadow(rows, config or {}, coverage_rows)
    out_root.mkdir(parents=True, exist_ok=True)
    date = str((config or {}).get("selection_date", ""))
    selected_path = out_root / "high_conviction_top15_core_deterioration_refill_shadow.csv"
    json_path = out_root / "high_conviction_top15_core_deterioration_refill_shadow.json"
    refill_path = out_root / "core_deterioration_refill_shadow_replacements.csv"
    result["date"] = date
    result["output_paths"] = {
        "csv": str(selected_path),
        "json": str(json_path),
        "core_deterioration_refill_shadow_replacements": str(refill_path),
    }
    _write_csv(selected_path, result["selected_rows"])
    _write_csv_with_fields(refill_path, result["core_deterioration_refill_rows"], CORE_DETERIORATION_REFILL_FIELDS)
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result
```

- [ ] **Step 9: Run focused selector tests**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_high_conviction_top15_exception_sleeve.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add tradingagents/research/fundamental/src/selection/high_conviction_top10.py tests/test_high_conviction_top15_exception_sleeve.py
git commit -m "feat: add top15 refill shadow selector"
```

---

## Task 5: Add PIT v2 Full Candidate Ranking Helper

**Files:**
- Modify: `tradingagents/research/fundamental/backtests/high_conviction_top10.py`
- Test: `tests/test_high_conviction_top15_backtest.py`

- [ ] **Step 1: Write failing test**

Append:

```python
def test_v2_candidates_returns_full_ex_ante_ranked_pool():
    from tradingagents.research.fundamental.backtests.high_conviction_top10 import _select_v2, _v2_candidates

    rows = [_row(f"C{i}", score=100 - i) for i in range(12)]
    rows[-1]["return_90d_pct"] = "999"
    pool = _v2_candidates(rows)
    selected = _select_v2(rows)

    assert len(pool) == 12
    assert [r["ticker"] for r in pool[:10]] == [r["ticker"] for r in selected]
    assert [r["core_candidate_rank"] for r in pool[:3]] == [1, 2, 3]
    assert pool[-1]["ticker"] == "C11"
```

- [ ] **Step 2: Run test to verify failure**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest \
  tests/test_high_conviction_top15_backtest.py::test_v2_candidates_returns_full_ex_ante_ranked_pool -q
```

Expected: FAIL because `_v2_candidates` does not exist.

- [ ] **Step 3: Implement helper**

In `high_conviction_top10.py` backtest module, replace `_select_v2()` body with:

```python
def _v2_candidates(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for row in rows:
        if _macro_blocks_v2(row):
            continue
        entry_score = _entry_score(row)
        hp_override = _truthy(row.get("hp_production_extension")) and _truthy(row.get("hp_LLM_best")) and entry_score >= 60
        rm_override = _truthy(row.get("repricing_momentum_priority")) and ((_to_float(row.get("market_repricing_score")) or 0.0) >= 14 or _truthy(row.get("rm_buy_review_flag")))
        theme_or_t5 = _truthy(row.get("theme_acceleration_research_visibility")) or str(row.get("akg_universe_tier", "")).strip() == "T5_RESCAN"
        if entry_score >= 70 or hp_override or rm_override or theme_or_t5:
            candidates.append(_with_score(row, _v2_score(row)))
    ranked = sorted(candidates, key=lambda r: (-(_to_float(r.get("hc_score")) or float("-inf")), -(_to_float(r.get("entry_score_0_100")) or float("-inf")), str(r.get("ticker", "")).upper()))
    return [{**row, "selection_rank": rank, "core_candidate_rank": rank} for rank, row in enumerate(ranked, 1)]


def _select_v2(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return _v2_candidates(rows)[:10]
```

- [ ] **Step 4: Run test**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_high_conviction_top15_backtest.py::test_v2_candidates_returns_full_ex_ante_ranked_pool -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/research/fundamental/backtests/high_conviction_top10.py tests/test_high_conviction_top15_backtest.py
git commit -m "refactor: expose v2 ranked candidate pool"
```

---

## Task 6: Add Historical Full Top-15 Shadow Refill Outputs

**Files:**
- Modify: `tradingagents/research/fundamental/backtests/high_conviction_top15_exception_sleeve.py`
- Test: `tests/test_high_conviction_top15_backtest.py`

- [ ] **Step 1: Write failing fixture and test**

Append to `tests/test_high_conviction_top15_backtest.py`:

```python
def _refill_fixture(tmp_path):
    pit = tmp_path / "pit.csv"
    prior = tmp_path / "prior.csv"
    out = tmp_path / "out"
    rows = [_row(f"C{i}", score=100 - i, ret90=5 + i) for i in range(10)]
    rows[5].update({
        "ticker": "BAD",
        "entry_score_0_100": "95",
        "score_change": "-2",
        "negative_revision_risk": "2",
        "pre_llm_fundamental_bucket": "weak",
        "primary_theme": "",
        "rm1_low_price_dislocation_momentum": "RM1 - Low-price dislocation momentum",
        "rm2_weak_acceleration": "RM2 - Weak-bucket acceleration",
        "rm4_persistent_repricing_wave": "RM4 - Persistent repricing wave",
        "return_90d_pct": "-40",
        "winner_90d_30pct": "False",
        "loser_90d_minus30pct": "True",
    })
    rows.append(_row("NEXT", score=89, ret90=30))
    rows.append(_row("BADX", score=85, ret90=-20, confidence="1", score_change="-2", negative_revision_risk="2", pre_llm_fundamental_bucket="weak", primary_theme="", rm1_low_price_dislocation_momentum="RM1 - Low-price dislocation momentum", rm2_weak_acceleration="RM2 - Weak-bucket acceleration", rm4_persistent_repricing_wave="RM4 - Persistent repricing wave"))
    rows.append(_row("GOODX", score=50, ret90=20, rm1_low_price_dislocation_momentum="1", primary_theme="AI"))
    rows.append(_row("LOWER", score=70, ret90=300))
    rows += [_row(ticker, score=30, ret90=0, eligible_for_backtest="False") for ticker in TARGET_RIGHT_TAIL_NAMES]
    _write_csv(pit, rows)
    baseline = [dict(r, variant="high_conviction_top10_v2_final", selection_rank=i + 1) for i, r in enumerate(rows[:10])]
    _write_csv(prior, baseline)
    manifest = run_high_conviction_top15_exception_sleeve_backtest(pit, prior, out)
    return out, manifest


def test_core_deterioration_refill_shadow_outputs_full_top15_and_replacement_diagnostics(tmp_path):
    out, manifest = _refill_fixture(tmp_path)
    selected = _read_rows(out / "core_deterioration_refill_shadow_selected.csv")
    replacements = _read_rows(out / "core_deterioration_refill_shadow_replacements.csv")
    summary = _read_rows(out / "core_deterioration_refill_shadow_summary.csv")

    strict_rows = [r for r in selected if r["variant"] == "top15_v4_core_deterioration_refill_strict"]
    assert "BAD" not in {r["ticker"] for r in strict_rows}
    assert "BADX" not in {r["ticker"] for r in strict_rows}
    assert "NEXT" in {r["ticker"] for r in strict_rows}
    assert any(r["selected_sleeve"] == "right_tail_exception" for r in strict_rows)
    assert any(r["demoted_ticker"] == "BAD" and r["replacement_ticker"] == "NEXT" for r in replacements)
    assert any(r["replacement_delta_90d_pct"] == "70.000000" for r in replacements)
    strict_summary = next(r for r in summary if r["variant"] == "top15_v4_core_deterioration_refill_strict")
    assert strict_summary["core_count"] == "10"
    assert int(strict_summary["total_picks"]) >= 10
    assert "avg_return_90d_pct" in strict_summary
    assert "core_deterioration_refill_shadow_outputs" in manifest
```

- [ ] **Step 2: Run test to verify failure**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest \
  tests/test_high_conviction_top15_backtest.py::test_core_deterioration_refill_shadow_outputs_full_top15_and_replacement_diagnostics -q
```

Expected: FAIL because shadow files do not exist.

- [ ] **Step 3: Import helpers and add constants**

In `high_conviction_top15_exception_sleeve.py`, update imports:

```python
from tradingagents.research.fundamental.backtests.high_conviction_top10 import (
    FORBIDDEN_SELECTION_COLUMNS,
    LABEL_COLUMNS,
    OUTCOME_COLUMNS,
    _avg,
    _eligible_groups,
    _feature_columns,
    _file_sha256,
    _rate,
    _read_csv,
    _to_float,
    _truthy,
    _v2_candidates,
    _validate_unique_ticker_quarter,
    _write_csv,
)
from tradingagents.research.fundamental.src.selection.high_conviction_top10 import (
    CORE_DETERIORATION_FIELDS,
    CORE_DETERIORATION_REFILL_FIELDS,
    RightTailExceptionConfig,
    _select_exception_sleeve,
    build_core_deterioration_review_rows,
    core_deterioration_flags,
    select_high_conviction_top15_exception_sleeve,
    should_refill_demote_core_row,
)
```

Add near `TOP15_VARIANTS`:

```python
CORE_DETERIORATION_REFILL_SHADOW_VARIANTS = {
    "top15_v4_core_deterioration_refill_strict": "strict",
    "top15_v4_core_deterioration_refill_downgrade": "downgrade",
}
CORE_DETERIORATION_REFILL_SELECTED_FIELDS = [
    "variant", "quarter", "selection_rank", "selected_sleeve", "selected_sleeve_rank", "ticker",
    "core_refill_source", "demoted_replacement_for", "right_tail_exception_score", *LABEL_COLUMNS,
]
CORE_DETERIORATION_REFILL_SUMMARY_FIELDS = [
    "variant", "quarter_count", "core_count", "exception_count", "total_picks", "avg_picks_per_quarter",
    "avg_return_90d_pct", "winner_90d_30pct_rate", "loser_90d_minus30pct_rate",
]
```

`avg_return_90d_pct`, winner rate, and loser rate in this summary are quarter-average metrics, matching existing `strategy_summary_top15.csv` semantics.

Add files to `OUTPUT_FILES` immediately after `core_deterioration_review_queue.csv`:

```python
"core_deterioration_refill_shadow_selected.csv",
"core_deterioration_refill_shadow_replacements.csv",
"core_deterioration_refill_shadow_summary.csv",
```

- [ ] **Step 4: Add historical helper functions**

Add before `run_high_conviction_top15_exception_sleeve_backtest()`:

```python
def _core_refill_flag_row(row: Mapping[str, Any], rank: int) -> dict[str, Any]:
    out = dict(row)
    out["selected_sleeve"] = "core"
    out["selection_rank"] = rank
    out["selected_sleeve_rank"] = rank
    return out


def _build_refill_replacement_row(variant: str, quarter: str, mode: str, demoted: Mapping[str, Any], replacement: Mapping[str, Any] | None, by_ticker: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    flags = core_deterioration_flags(demoted)
    demoted_ticker = str(demoted.get("ticker", "")).upper()
    replacement_ticker = str((replacement or {}).get("ticker", "")).upper()
    demoted_ret = by_ticker.get(demoted_ticker, {}).get("return_90d_pct", "")
    replacement_ret = by_ticker.get(replacement_ticker, {}).get("return_90d_pct", "") if replacement_ticker else ""
    d = _to_float(demoted_ret)
    r = _to_float(replacement_ret)
    return {
        "variant": variant,
        "quarter": quarter,
        "mode": mode,
        "demoted_ticker": demoted_ticker,
        "replacement_ticker": replacement_ticker,
        "demoted_core_candidate_rank": demoted.get("core_candidate_rank", demoted.get("selection_rank", "")),
        "replacement_core_candidate_rank": (replacement or {}).get("core_candidate_rank", ""),
        "demoted_entry_score_0_100": demoted.get("entry_score_0_100", ""),
        "replacement_entry_score_0_100": (replacement or {}).get("entry_score_0_100", ""),
        "demoted_score_change": demoted.get("score_change", ""),
        "demoted_negative_revision_risk": demoted.get("negative_revision_risk", ""),
        "demoted_pre_llm_fundamental_bucket": demoted.get("pre_llm_fundamental_bucket", ""),
        "demoted_primary_theme": demoted.get("primary_theme", ""),
        "demoted_rm_count": flags.get("core_deterioration_rm_count", ""),
        "demoted_hp_count": flags.get("core_deterioration_hp_count", ""),
        "demoted_market_repricing_score": flags.get("demoted_market_repricing_score", ""),
        "high_score_deterioration_flag": flags.get("high_score_deterioration_flag", 0),
        "weak_no_theme_repricing_stack_flag": flags.get("weak_no_theme_repricing_stack_flag", 0),
        "core_deterioration_review_flag": flags.get("core_deterioration_review_flag", 0),
        "core_deterioration_downgrade_flag": flags.get("core_deterioration_downgrade_flag", 0),
        "core_deterioration_strict_override_required": flags.get("core_deterioration_strict_override_required", 0),
        "core_deterioration_reason_codes": flags.get("core_deterioration_reason_codes", ""),
        "demoted_return_90d_pct": demoted_ret,
        "replacement_return_90d_pct": replacement_ret,
        "replacement_delta_90d_pct": f"{(r - d):.6f}" if d is not None and r is not None else "",
    }


def _build_core_deterioration_refill_shadow(
    variant: str,
    mode: str,
    quarter: str,
    eligible: Sequence[dict[str, str]],
    selection_safe_cols: Sequence[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    required_identity_cols = ["ticker", "quarter", "tradable_date", "entry_open", "eligible_for_backtest"]
    safe_cols = list(dict.fromkeys([*required_identity_cols, *selection_safe_cols]))
    safe_rows = [{c: r.get(c, "") for c in safe_cols} for r in eligible]
    by_ticker = {str(r.get("ticker", "")).upper(): r for r in eligible}
    ranked = _v2_candidates(safe_rows)
    selected_core_raw: list[dict[str, Any]] = []
    demoted_raw: list[dict[str, Any]] = []
    blocked_tickers: set[str] = set()

    # First scan the full safe historical universe, not just the core-ranked pool, so
    # core-ineligible deterioration-pattern rows cannot bypass refill logic and enter exceptions.
    flagged_by_ticker: dict[str, dict[str, Any]] = {}
    for candidate in safe_rows:
        ticker = str(candidate.get("ticker", "")).upper()
        if not ticker:
            continue
        flagged = _core_refill_flag_row(candidate, 999999)
        if should_refill_demote_core_row(flagged, mode):
            blocked_tickers.add(ticker)
            flagged_by_ticker[ticker] = flagged

    for candidate in ranked:
        ticker = str(candidate.get("ticker", "")).upper()
        rank = int(_to_float(candidate.get("core_candidate_rank") or candidate.get("selection_rank")) or 999999)
        if ticker in blocked_tickers:
            if rank <= 10:
                demoted_raw.append(_core_refill_flag_row(candidate, rank))
            continue
        selected_core_raw.append(candidate)
        if len(selected_core_raw) >= 10:
            break

    selected_core: list[dict[str, Any]] = []
    replacements_raw = [r for r in selected_core_raw if int(_to_float(r.get("core_candidate_rank") or 999999) or 999999) > 10]
    replacement_rows: list[dict[str, Any]] = []

    for idx, row in enumerate(selected_core_raw, start=1):
        ticker = str(row.get("ticker", "")).upper()
        original = by_ticker[ticker]
        frozen = _freeze(row, original, variant, quarter, idx)
        frozen["selected_sleeve"] = "core"
        frozen["selected_sleeve_rank"] = idx
        frozen["core_refill_source"] = "next_ranked_core_candidate" if int(_to_float(row.get("core_candidate_rank") or idx) or idx) > 10 else "original_top10"
        selected_core.append(frozen)

    for idx, demoted in enumerate(demoted_raw):
        replacement = replacements_raw[idx] if idx < len(replacements_raw) else None
        replacement_rows.append(_build_refill_replacement_row(variant, quarter, mode, demoted, replacement, by_ticker))

    cfg = RightTailExceptionConfig(enabled=True, core_n=10, exception_slots=5)
    exceptions, _warnings = _select_exception_sleeve(selected_core, safe_rows, cfg, blocked_tickers=blocked_tickers)
    selected_exceptions: list[dict[str, Any]] = []
    for idx, row in enumerate(exceptions, start=1):
        ticker = str(row.get("ticker", "")).upper()
        if ticker not in by_ticker:
            continue
        frozen = _freeze(row, by_ticker[ticker], variant, quarter, len(selected_core) + idx)
        frozen["selected_sleeve"] = "right_tail_exception"
        frozen["selected_sleeve_rank"] = idx
        frozen["core_refill_source"] = ""
        selected_exceptions.append(frozen)

    return selected_core + selected_exceptions, replacement_rows


def _refill_shadow_summary_rows(selected_rows: Sequence[Mapping[str, Any]], quarter_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for variant in CORE_DETERIORATION_REFILL_SHADOW_VARIANTS:
        picks = [r for r in selected_rows if r["variant"] == variant]
        qrows = [r for r in quarter_rows if r["variant"] == variant]
        rows.append({
            "variant": variant,
            "quarter_count": len(qrows),
            "core_count": sum(r.get("selected_sleeve") == "core" for r in picks),
            "exception_count": sum(r.get("selected_sleeve") == "right_tail_exception" for r in picks),
            "total_picks": len(picks),
            "avg_picks_per_quarter": f"{len(picks) / len(qrows):.6f}" if qrows else "",
            "avg_return_90d_pct": _avg(qrows, "avg_return_90d_pct"),
            "winner_90d_30pct_rate": _avg(qrows, "winner_90d_30pct_rate"),
            "loser_90d_minus30pct_rate": _avg(qrows, "loser_90d_minus30pct_rate"),
        })
    return rows
```

- [ ] **Step 5: Wire helper into runner**

Before the existing `for q in sorted(groups):` loop in `run_high_conviction_top15_exception_sleeve_backtest()`, initialize:

```python
refill_selected_rows: list[dict[str, Any]] = []
refill_replacement_rows: list[dict[str, Any]] = []
refill_quarter_rows: list[dict[str, Any]] = []
```

Inside the per-quarter loop, after the existing `for variant, cfg in TOP15_VARIANTS.items():` loop completes and before `_validate_selected(...)`, add at the same indentation level as the `for variant` loop:

```python
for refill_variant, mode in CORE_DETERIORATION_REFILL_SHADOW_VARIANTS.items():
    refill_selected, refill_replacements = _build_core_deterioration_refill_shadow(refill_variant, mode, q, eligible, safe_cols)
    refill_selected_rows.extend(refill_selected)
    refill_replacement_rows.extend(refill_replacements)
    refill_quarter_rows.append(_summarize_quarter(refill_variant, q, refill_selected, len(eligible), 15))
```

After existing CSV writes, add:

```python
refill_summary = _refill_shadow_summary_rows(refill_selected_rows, refill_quarter_rows)
_write_csv(out / "core_deterioration_refill_shadow_selected.csv", refill_selected_rows, CORE_DETERIORATION_REFILL_SELECTED_FIELDS)
_write_csv(out / "core_deterioration_refill_shadow_replacements.csv", refill_replacement_rows, CORE_DETERIORATION_REFILL_FIELDS)
_write_csv(out / "core_deterioration_refill_shadow_summary.csv", refill_summary, CORE_DETERIORATION_REFILL_SUMMARY_FIELDS)
```

Add manifest entries:

```python
"core_deterioration_refill_shadow_outputs": {
    "selected": "core_deterioration_refill_shadow_selected.csv",
    "replacements": "core_deterioration_refill_shadow_replacements.csv",
    "summary": "core_deterioration_refill_shadow_summary.csv",
},
"core_deterioration_refill_shadow_variants": CORE_DETERIORATION_REFILL_SHADOW_VARIANTS,
"core_deterioration_refill_shadow_no_leakage_statement": "Selection/refill uses PIT feature columns only; return labels are attached after selection is frozen for diagnostics.",
```

- [ ] **Step 6: Add test that official Top-15 output remains unchanged on rerun**

Append:

```python
def test_refill_shadow_does_not_change_official_top15_selected_output(tmp_path):
    out, _ = _fixture(tmp_path)
    first = (out / "selected_names_by_quarter_top15.csv").read_text(encoding="utf-8")
    pit = tmp_path / "pit.csv"
    prior = tmp_path / "prior.csv"
    run_high_conviction_top15_exception_sleeve_backtest(pit, prior, out)
    second = (out / "selected_names_by_quarter_top15.csv").read_text(encoding="utf-8")
    manifest = json.loads((out / "run_manifest.json").read_text(encoding="utf-8"))

    assert second == first
    assert "core_deterioration_refill_shadow_selected.csv" in manifest["output_hashes"]
    assert "core_deterioration_refill_shadow_replacements.csv" in manifest["output_hashes"]
    assert "core_deterioration_refill_shadow_summary.csv" in manifest["output_hashes"]
```

- [ ] **Step 7: Run focused backtest tests**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_high_conviction_top15_backtest.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add tradingagents/research/fundamental/backtests/high_conviction_top15_exception_sleeve.py tests/test_high_conviction_top15_backtest.py
git commit -m "feat: add top15 refill shadow backtest"
```

---

## Task 7: Add Analysis Report Tables and Narrative

**Files:**
- Modify: `scripts/analyze_fundamental_top15_exception_sleeve.py`
- Test: `tests/test_high_conviction_top15_backtest.py`

- [ ] **Step 1: Write failing analysis test**

Append:

```python
def test_top15_analysis_emits_core_deterioration_refill_shadow_tables(tmp_path):
    from scripts.analyze_fundamental_top15_exception_sleeve import run

    out_bundle, _ = _refill_fixture(tmp_path)
    analysis_out = tmp_path / "analysis"
    report = tmp_path / "report.md"
    run(out_bundle, Path("outputs/fundamental_backtest/analysis"), analysis_out, report)

    assert (analysis_out / "core_deterioration_refill_shadow_selected.csv").exists()
    assert (analysis_out / "core_deterioration_refill_shadow_replacements.csv").exists()
    assert (analysis_out / "core_deterioration_refill_shadow_summary.csv").exists()
    text = report.read_text(encoding="utf-8")
    assert "Core Deterioration Refill Shadow Review" in text
    assert "shadow-only" in text
    assert "not the official Top-15 list" in text
```

- [ ] **Step 2: Run test to verify failure**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest \
  tests/test_high_conviction_top15_backtest.py::test_top15_analysis_emits_core_deterioration_refill_shadow_tables -q
```

Expected: FAIL.

- [ ] **Step 3: Update analysis script**

In `scripts/analyze_fundamental_top15_exception_sleeve.py`, add an optional reader near `read_csv()` so older bundles without shadow files do not crash:

```python
def read_csv_optional(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return read_csv(path)
```

Then read bundle files near other reads:

```python
refill_selected = read_csv_optional(bundle_dir / "core_deterioration_refill_shadow_selected.csv")
refill_replacements = read_csv_optional(bundle_dir / "core_deterioration_refill_shadow_replacements.csv")
refill_summary = read_csv_optional(bundle_dir / "core_deterioration_refill_shadow_summary.csv")
```

Add to outputs dict:

```python
"core_deterioration_refill_shadow_selected.csv": refill_selected,
"core_deterioration_refill_shadow_replacements.csv": refill_replacements,
"core_deterioration_refill_shadow_summary.csv": refill_summary,
```

Add report section:

```markdown
## Core Deterioration Refill Shadow Review

This is a shadow-only research variant, not the official Top-15 list. It preserves Top-15 capacity by combining refilled core rows with the exception sleeve, and it blocks demoted/refill-ineligible deterioration tickers from exception auto-selection.

Use `core_deterioration_refill_shadow_replacements.csv` to compare demoted core names against next eligible ex-ante replacements. Return labels and replacement deltas are diagnostic only and are attached after selection is frozen.
```

- [ ] **Step 4: Run test**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest \
  tests/test_high_conviction_top15_backtest.py::test_top15_analysis_emits_core_deterioration_refill_shadow_tables -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/analyze_fundamental_top15_exception_sleeve.py tests/test_high_conviction_top15_backtest.py
git commit -m "analysis: add top15 refill shadow review"
```

---

## Task 8: Add Opt-In Daily CLI Command

**Files:**
- Modify: `cli/commands/fundamental.py`
- Create: `tests/test_cli_fundamental_top15_refill_shadow.py`

- [ ] **Step 1: Write failing CLI test**

Create `tests/test_cli_fundamental_top15_refill_shadow.py`:

```python
import csv

from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


def _write_scores(path):
    rows = []
    for idx in range(9):
        rows.append({"ticker": f"C{idx}", "entry_score_0_100": str(100 - idx), "confidence": "4", "cik": "123", "cik_status": "resolved", "document_status": "CACHED_READY"})
    rows.insert(5, {
        "ticker": "BAD",
        "entry_score_0_100": "95",
        "confidence": "4",
        "cik": "123",
        "cik_status": "resolved",
        "document_status": "CACHED_READY",
        "score_change": "-2",
        "negative_revision_risk": "2",
        "pre_llm_fundamental_bucket": "weak",
        "primary_theme": "",
        "rm1_low_price_dislocation_momentum": "RM1 - Low-price dislocation momentum",
        "rm2_weak_acceleration": "RM2 - Weak-bucket acceleration",
        "rm4_persistent_repricing_wave": "RM4 - Persistent repricing wave",
    })
    rows.append({"ticker": "NEXT", "entry_score_0_100": "89", "confidence": "4", "cik": "123", "cik_status": "resolved", "document_status": "CACHED_READY"})
    fieldnames = sorted({k for r in rows for k in r})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_fundamental_top15_refill_shadow_cli_writes_shadow_outputs(tmp_path):
    scores = tmp_path / "scores.csv"
    out = tmp_path / "out"
    _write_scores(scores)

    result = runner.invoke(app, [
        "fundamental-top15-refill-shadow",
        "--scores-csv", str(scores),
        "--output-root", str(out),
        "--date", "2026-05-11",
        "--mode", "strict",
    ])

    assert result.exit_code == 0, result.output
    assert (out / "high_conviction_top15_core_deterioration_refill_shadow.csv").exists()
    assert (out / "core_deterioration_refill_shadow_replacements.csv").exists()
    assert "Wrote shadow" in result.output
```

- [ ] **Step 2: Run test to verify failure**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_cli_fundamental_top15_refill_shadow.py -q
```

Expected: FAIL because command does not exist.

- [ ] **Step 3: Add CLI command**

Add after `fundamental_top15()` in `cli/commands/fundamental.py`:

```python
@app.command("fundamental-top15-refill-shadow")
def fundamental_top15_refill_shadow(
    scores_csv: str = typer.Option(..., "--scores-csv", help="Required final fundamental scores CSV path"),
    coverage_manifest: str = typer.Option("", "--coverage-manifest", help="Optional SEC coverage manifest CSV path"),
    output_root: str = typer.Option("", "--output-root", help="Output root; defaults to scores CSV parent or eval_results/fundamental/<date>"),
    date: str = typer.Option("", "--date", help="Selection date YYYY-MM-DD"),
    mode: str = typer.Option("strict", "--mode", help="Refill mode: strict|downgrade|all_review"),
    core_n: int = typer.Option(10, "--core-n", min=1, help="Core names to select"),
    exception_slots: int = typer.Option(5, "--exception-slots", min=0, help="Right-tail exception slots"),
    format: str = typer.Option("table", "--format", help="Output format: table|json"),
):
    """Emit shadow Top-15 refill variant; does not replace normal Top-15."""
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import select_top15_core_deterioration_refill_shadow_from_csv

    fmt = format.strip().lower()
    if fmt not in {"table", "json"}:
        console.print("[red]--format must be table or json[/red]")
        raise typer.Exit(1)
    scores_path = Path(scores_csv)
    if not scores_path.exists():
        console.print(f"[red]scores CSV not found: {scores_path}[/red]")
        raise typer.Exit(1)
    coverage_path = Path(coverage_manifest) if coverage_manifest.strip() else None
    if coverage_path is not None and not coverage_path.exists():
        console.print(f"[red]coverage manifest not found: {coverage_path}[/red]")
        raise typer.Exit(1)
    selection_date = date.strip()
    out_root = Path(output_root.strip()) if output_root.strip() else (
        Path("eval_results") / "fundamental" / selection_date if selection_date else scores_path.parent
    )
    config = {
        "selection_date": selection_date,
        "enabled": True,
        "core_n": core_n,
        "exception_slots": exception_slots,
        "coverage_gating": coverage_path is not None,
        "core_deterioration_refill": {"enabled": True, "mode": mode.strip().lower()},
    }
    result = select_top15_core_deterioration_refill_shadow_from_csv(scores_path, out_root, config, coverage_path)
    if fmt == "json":
        console.print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_top15_table(result.get("selected_rows", []))
        paths = result["output_paths"]
        console.print(f"[green]Wrote shadow[/green] {paths['csv']} | {paths['json']} | {paths['core_deterioration_refill_shadow_replacements']}")
```

- [ ] **Step 4: Run CLI test**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_cli_fundamental_top15_refill_shadow.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cli/commands/fundamental.py tests/test_cli_fundamental_top15_refill_shadow.py
git commit -m "feat: add top15 refill shadow cli"
```

---

## Task 9: Regenerate Historical Artifacts and Analysis

**Files:**
- Generated/modified:
  - `outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/run_manifest.json`
  - `outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/core_deterioration_review_queue.csv`
  - `outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/core_deterioration_refill_shadow_selected.csv`
  - `outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/core_deterioration_refill_shadow_replacements.csv`
  - `outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/core_deterioration_refill_shadow_summary.csv`
  - `outputs/fundamental_backtest/analysis_top15_exception/*shadow*.csv`
  - `docs/research/fundamental_top15_exception_sleeve_observed_backtest_analysis.md`

- [ ] **Step 1: Regenerate Top-15 backtest bundle**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m tradingagents.research.fundamental.backtests.high_conviction_top15_exception_sleeve \
  --pit-panel outputs/fundamental_backtest/pit_fundamental_panel.csv \
  --prior-selected outputs/fundamental_backtest/high_conviction_top10/selected_names_by_quarter.csv \
  --out-dir outputs/fundamental_backtest/high_conviction_top15_exception_sleeve
```

Expected: exits 0 and prints JSON with `eligible_row_count`, `output_dir`, `quarter_count`.

- [ ] **Step 2: Regenerate analysis report**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 scripts/analyze_fundamental_top15_exception_sleeve.py \
  --bundle-dir outputs/fundamental_backtest/high_conviction_top15_exception_sleeve \
  --prior-analysis-dir outputs/fundamental_backtest/analysis \
  --out-dir outputs/fundamental_backtest/analysis_top15_exception \
  --report docs/research/fundamental_top15_exception_sleeve_observed_backtest_analysis.md
```

Expected: exits 0 and prints JSON with `output_count` and report path.

- [ ] **Step 3: Verify official Top-15 selected hash unchanged**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 - <<'PY'
import json
m=json.load(open('outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/run_manifest.json'))
print(m['top15_selected_rows_unchanged_from_prior_hash'])
print(m.get('core_deterioration_refill_shadow_outputs'))
PY
```

Expected first line: `True`.

- [ ] **Step 4: Inspect shadow outputs**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 - <<'PY'
import csv
for path in [
 'outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/core_deterioration_refill_shadow_summary.csv',
 'outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/core_deterioration_refill_shadow_replacements.csv',
]:
    print()
    print(path)
    with open(path, newline='', encoding='utf-8') as fh:
        for idx, row in enumerate(csv.DictReader(fh)):
            print(row)
            if idx >= 5:
                break
PY
```

Expected: strict/downgrade variants appear; replacement rows include `demoted_ticker`, `replacement_ticker`, `demoted_rm_count`, `demoted_hp_count`, `demoted_market_repricing_score`, `replacement_delta_90d_pct`.

- [ ] **Step 5: Commit artifacts**

```bash
git add \
  outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/run_manifest.json \
  outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/core_deterioration_review_queue.csv \
  outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/core_deterioration_refill_shadow_selected.csv \
  outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/core_deterioration_refill_shadow_replacements.csv \
  outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/core_deterioration_refill_shadow_summary.csv \
  outputs/fundamental_backtest/analysis_top15_exception/core_deterioration_refill_shadow_selected.csv \
  outputs/fundamental_backtest/analysis_top15_exception/core_deterioration_refill_shadow_replacements.csv \
  outputs/fundamental_backtest/analysis_top15_exception/core_deterioration_refill_shadow_summary.csv \
  outputs/fundamental_backtest/analysis_top15_exception/analysis_manifest.json \
  docs/research/fundamental_top15_exception_sleeve_observed_backtest_analysis.md

git commit -m "data: add top15 refill shadow artifacts"
```

---

## Task 10: Update Daily Runbook

**Files:**
- Modify: `docs/research/aeternus-daily-pipeline-debug-runbook.md`

- [ ] **Step 1: Add optional shadow command**

After normal `fundamental-top15` command, add:

````markdown
Optional shadow-only core deterioration refill check:

```bash
python3 -m cli.main fundamental-top15-refill-shadow \
  --scores-csv eval_results/fundamental/YYYY-MM-DD/fundamental_final_scores_YYYY-MM-DD.csv \
  --output-root eval_results/fundamental/YYYY-MM-DD \
  --date YYYY-MM-DD \
  --mode strict
```

Outputs:

- `high_conviction_top15_core_deterioration_refill_shadow.csv`
- `core_deterioration_refill_shadow_replacements.csv`
- `high_conviction_top15_core_deterioration_refill_shadow.json`

This is not the official Top-15 list. Use it to compare core deterioration demotions against next eligible replacements before PM override.
````

Update daily review order:

```markdown
1. Official Top-15 core / exception names
2. `core_deterioration_review_queue.csv`
3. Optional `core_deterioration_refill_shadow_replacements.csv`
4. `right_tail_scout_queue.csv`
5. `demote_review_priority_1.csv`
6. top-ranked names from `thin_signal_watchlist_top100.csv`
```

- [ ] **Step 2: Commit docs**

```bash
git add docs/research/aeternus-daily-pipeline-debug-runbook.md
git commit -m "docs: add top15 refill shadow runbook"
```

---

## Task 11: Final Verification and Review Gate

**Files:**
- No intended code edits.

- [ ] **Step 1: Run focused tests**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest \
  tests/test_high_conviction_top15_exception_sleeve.py \
  tests/test_high_conviction_top15_backtest.py \
  tests/test_cli_fundamental_top15_refill_shadow.py \
  tests/test_cli_fundamental_top10.py -q
```

Expected: all pass; existing Python 3.14 dependency warnings acceptable.

- [ ] **Step 2: Run broader relevant tests**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest \
  tests/test_fundamental_high_conviction_top10.py \
  tests/test_high_conviction_top15_exception_sleeve.py \
  tests/test_high_conviction_top15_backtest.py \
  tests/test_cli_fundamental_top10.py \
  tests/test_cli_fundamental_right_tail_queues.py \
  tests/test_right_tail_scout_queues.py -q
```

Expected: all pass.

- [ ] **Step 3: Confirm official selected output unchanged**

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 - <<'PY'
import json
m=json.load(open('outputs/fundamental_backtest/high_conviction_top15_exception_sleeve/run_manifest.json'))
assert m['top15_selected_rows_unchanged_from_prior_hash'] is True
print('top15 hash guard true')
PY
```

Expected: `top15 hash guard true`.

- [ ] **Step 4: Check staged/untracked files**

```bash
git status --short
```

Expected: only files from this plan are staged/modified. Leave unrelated IFVG / egg-info / Growth files unstaged.

- [ ] **Step 5: Request final code review**

Use @superpowers:requesting-code-review. Review prompt:

```text
Review the Top15 core deterioration refill shadow implementation. Verify:
- official Top15 v3 output remains unchanged by default
- named deterioration flags match the spec
- rank 7/8 alone cannot trigger demotion
- descriptive RM/HP labels are counted for weak stack flags
- shadow selected output is full Top15: refilled core + exception sleeve
- replacement selection is ex-ante and ignores return labels
- demoted/refill-ineligible deterioration tickers cannot re-enter exceptions
- shadow outputs are clearly not buy lists
```

- [ ] **Step 6: Fix reviewer blockers only, rerun focused tests, push**

```bash
git push origin HEAD
```

Expected: push succeeds.

---

## Expected Final Evidence

- Focused tests pass.
- Backtest and analysis regenerate successfully.
- `top15_selected_rows_unchanged_from_prior_hash = true`.
- Shadow selected/replacement/summary CSVs exist.
- Shadow selected file includes core and exception sleeves.
- Replacement table contains RM/HP counts and post-freeze return deltas.
- Daily CLI writes shadow outputs without changing official Top-15.

## Rollback Plan

If shadow selector is unstable:

1. Revert commits adding refill shadow selector/backtest/CLI/artifacts.
2. Keep the prior `core_deterioration_review_queue.csv` behavior only if the new flag definitions are rejected; otherwise revert flag-definition commit too.
3. Re-run Top-15 backtest.
4. Confirm `selected_names_by_quarter_top15.csv` hash guard is true.
