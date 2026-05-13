# Fundamental Consolidated Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one canonical fundamental pipeline that can generate, on demand, a complete candidate CSV with required fields populated and publish Top 10 core + Plus 5 exception + shadow refill candidates from the same canonical rows.

**Architecture:** Make `tradingagents/research/fundamental/src/` the only output-producing framework. Add a canonical schema/normalization/export layer that sits after daily scoring and before selector publish; it derives legacy-compatible fields from canonical current fields instead of stitching old and new outputs. Keep `tradingagents/research/fundamental/Growth/` as legacy research input/reference only, with explicit migration adapters and no ownership of final CSVs.

**Tech Stack:** Python 3.x, pandas, Typer, pytest, existing `daily_run`, `features`, `ingest`, `selection`, and `sec_pipeline` modules, local SEC companyfacts/document cache.

---

## Operator Outcome

When asked for the full fundamental candidate CSV or a fresh Top10+Plus5+shadow run, there is one supported path.

For a current daily run:

```bash
python -m cli.main fundamental-run-today \
  --mode broad-master-final \
  --date 2026-05-12 \
  --quarter 2026Q2 \
  --master-universe <canonical-master-universe.json> \
  --prior-final-scores <prior-quarter-final-scores.csv> \
  --emit-complete-panel \
  --complete-panel-output-root outputs/fundamental_backtest/full_complete_panel_2021Q4_2026Q2
```

For rebuilding the complete panel from an already finished run:

```bash
python -m cli.main fundamental-build-complete-panel \
  --date 2026-05-12 \
  --quarter 2026Q2 \
  --run-root eval_results/fundamental/2026-05-12_2026Q2_hp_rm_final_v3 \
  --prior-panel outputs/fundamental_backtest/full_complete_panel_2021Q4_2026Q2/fundamental_complete_prellm_to_top15_2021Q4_2026Q2.csv \
  --output-root outputs/fundamental_backtest/full_complete_panel_2021Q4_2026Q2
```

The command writes:

- `fundamental_complete_prellm_to_top15_2021Q4_2026Q2.csv`
- `fundamental_complete_prellm_to_top15_2021Q4_2026Q2_manifest.json`
- `fundamental_complete_prellm_to_top15_2021Q4_2026Q2_columns.json`
- `fundamental_complete_prellm_to_top15_2021Q4_2026Q2_validation.json`
- `high_conviction_top15.csv/json/md`
- `high_conviction_top15_core_deterioration_refill_shadow.csv/json`

The command must hard-stop if required fields are missing without an allowed reason.

---

## Why Two Frameworks Exist Today

Current split:

- `tradingagents/research/fundamental/Growth/`
  - older research/backtest scripts and frozen combined CSVs
  - contains historical subtier columns and early experimental formulas
  - currently leaks into ad hoc analyst exports
- `tradingagents/research/fundamental/src/`
  - current operating framework
  - owns daily run gates, SEC coverage, current feature derivation, HP/RM, LLM eligibility, final scores, Top15, and shadow refill

The blank-field problem came from assembling a CSV across both worlds. `2026Q2` current rows did not carry every historical legacy column, and historical rows did not carry every current field. The fix is not more merging; the fix is one canonical producer that derives every output column from one schema contract.

---

## Non-Negotiable Contracts

1. `src/` owns all final outputs.
2. `Growth/` can only be read by migration/import code with explicit provenance.
3. The complete panel schema is versioned and enforced.
4. Required fields are either populated or have a machine-readable missing reason.
5. Boolean/flag fields are `0/1`, never blank, unless the column is explicitly optional.
6. Top10+Plus5+shadow selection runs from the same final rows that feed the complete CSV.
7. No outcome/forward-return columns can influence selection.
8. A run must produce a validation JSON that says `passed=true` before the CSV is considered publishable.
9. `--prior-panel` accepts only a prior canonical complete-panel CSV with a passing validation artifact; raw `Growth/` combined CSVs are not accepted as prior panels.

---

## Target File Structure

Create:

- `tradingagents/research/fundamental/src/panel/__init__.py`
  - Public package exports.

- `tradingagents/research/fundamental/src/panel/schema.py`
  - Canonical complete-panel schema groups, required-field policy, optional-field policy, field aliases, default values, and schema version.

- `tradingagents/research/fundamental/src/panel/financial_values.py`
  - Canonical SEC companyfacts/XBRL value extraction for raw financial fields.
  - Supports US GAAP and IFRS tags already proven in cleanup.

- `tradingagents/research/fundamental/src/panel/normalize.py`
  - Converts final-score rows plus daily artifacts into canonical complete-panel rows.
  - Derives legacy-compatible fields such as `post_llm_tier_*_flag` from canonical current fields.

- `tradingagents/research/fundamental/src/panel/selection_annotations.py`
  - Runs or attaches Top15 and shadow refill outputs to canonical rows.

- `tradingagents/research/fundamental/src/panel/validate.py`
  - Enforces no duplicate ticker-quarter rows, required columns present, required fields populated or reason-tagged, no forbidden selection leakage, Top15/shadow identity checks, and output row-count reconciliation.

- `tradingagents/research/fundamental/src/panel/exporter.py`
  - Main orchestrator for building the complete CSV, manifest, column map, validation JSON, and selection artifacts.

- `tradingagents/research/fundamental/docs/complete_candidate_panel_contract.md`
  - Operator-facing contract for fields, sources, missing reasons, and command usage.

Modify:

- `tradingagents/research/fundamental/src/cli/commands.py`
  - Add `fundamental-build-complete-panel`.
  - Add optional `--emit-complete-panel` to `fundamental-run-today` only after the standalone exporter is stable.

- `tradingagents/research/fundamental/src/daily_run/models.py`
  - Add complete-panel emission options to `DailyRunConfig`.

- `tradingagents/research/fundamental/src/daily_run/orchestrator.py`
  - Call the complete-panel exporter after Gate 10 publish when `emit_complete_panel=True`.

- `tradingagents/research/fundamental/src/daily_run/finalize.py`
  - Keep publish logic unchanged, but expose enough artifact paths for the complete-panel exporter.

- `tradingagents/research/fundamental/backtests/pit_panel.py`
  - Import canonical schema constants from `src.panel.schema` instead of owning a separate feature schema.

Create tests:

- `tests/test_fundamental_panel_schema.py`
- `tests/test_fundamental_panel_financial_values.py`
- `tests/test_fundamental_panel_normalize.py`
- `tests/test_fundamental_panel_selection_annotations.py`
- `tests/test_fundamental_panel_validate.py`
- `tests/test_fundamental_panel_exporter.py`
- `tests/test_cli_fundamental_build_complete_panel.py`
- `tests/test_fundamental_no_growth_output_ownership.py`

---

## Task 1: Canonical Complete-Panel Schema

**Files:**

- Create: `tradingagents/research/fundamental/src/panel/__init__.py`
- Create: `tradingagents/research/fundamental/src/panel/schema.py`
- Test: `tests/test_fundamental_panel_schema.py`

- [x] **Step 1: Write failing schema tests**

```python
# tests/test_fundamental_panel_schema.py
from tradingagents.research.fundamental.src.panel.schema import (
    COMPLETE_PANEL_SCHEMA_VERSION,
    REQUIRED_COMPLETE_PANEL_COLUMNS,
    REQUIRED_NONBLANK_FIELDS,
    FLAG_FIELDS,
    default_for_field,
    missing_reason_field,
)


def test_complete_panel_schema_includes_operator_required_groups():
    required = set(REQUIRED_COMPLETE_PANEL_COLUMNS)
    for field in [
        "ticker",
        "quarter",
        "symbol",
        "cik",
        "company_title",
        "revenue_value",
        "net_income_value",
        "assets_value",
        "operating_cash_flow_value",
        "investing_cash_flow_value",
        "financing_cash_flow_value",
        "pre_llm_fundamental_score",
        "tier_1_bucket",
        "hp_production_extension",
        "llm_status",
        "post_llm_candidate_flag",
        "post_llm_tier_1_1_flag",
        "repricing_momentum_extension",
        "top15_selected",
        "shadow_selected",
        "field_population_status",
    ]:
        assert field in required
    assert COMPLETE_PANEL_SCHEMA_VERSION.startswith("fundamental_complete_panel_v")


def test_required_nonblank_fields_have_missing_reason_fields():
    for field in REQUIRED_NONBLANK_FIELDS:
        assert missing_reason_field(field) in REQUIRED_COMPLETE_PANEL_COLUMNS


def test_flag_fields_default_to_zero():
    for field in FLAG_FIELDS:
        assert default_for_field(field) == "0"
```

- [x] **Step 2: Run failing test**

Run:

```bash
python -m pytest tests/test_fundamental_panel_schema.py -q
```

Expected: FAIL with missing `src.panel.schema`.

- [x] **Step 3: Implement minimal schema module**

Implementation requirements:

- Keep column groups explicit and ordered.
- Include all fields in the currently generated `315`-column CSV unless a field is formally deprecated.
- Add missing-reason sidecars for fields that can be legitimately unavailable:
  - `revenue_value_missing_reason`
  - `net_income_value_missing_reason`
  - `assets_value_missing_reason`
  - `operating_cash_flow_value_missing_reason`
  - `investing_cash_flow_value_missing_reason`
  - `financing_cash_flow_value_missing_reason`
  - `llm_status_missing_reason`
  - `post_llm_missing_reason`
  - `selection_missing_reason`
- Define `FLAG_FIELDS` for every `*_flag`, `top15_selected`, `shadow_selected`, HP/RM/tier boolean output.
- Define `LEGACY_COMPATIBILITY_FIELDS` for fields retained only because historical analyst workflows expect them.

- [x] **Step 4: Run schema test**

Run:

```bash
python -m pytest tests/test_fundamental_panel_schema.py -q
```

Expected: PASS.

---

## Task 2: Canonical Financial Fact Extraction

**Files:**

- Create: `tradingagents/research/fundamental/src/panel/financial_values.py`
- Test: `tests/test_fundamental_panel_financial_values.py`

- [x] **Step 1: Write failing tests for SEC fact population and allowed missing reasons**

```python
# tests/test_fundamental_panel_financial_values.py
from datetime import date

from tradingagents.research.fundamental.src.panel.financial_values import fill_financial_values


def test_fill_financial_values_uses_gaap_and_ifrs_concepts():
    rows = [
        {"ticker": "AAA", "quarter": "2026Q2", "entry_open_date": "2026-05-12"},
        {"ticker": "NOK", "quarter": "2026Q2", "entry_open_date": "2026-05-12"},
    ]
    facts = {
        "AAA": {
            "facts": {"us-gaap": {
                "Revenues": {"units": {"USD": [{"form": "10-Q", "filed": "2026-05-01", "start": "2026-01-01", "end": "2026-03-31", "val": 100}]}},
                "NetIncomeLoss": {"units": {"USD": [{"form": "10-Q", "filed": "2026-05-01", "start": "2026-01-01", "end": "2026-03-31", "val": 10}]}},
                "Assets": {"units": {"USD": [{"form": "10-Q", "filed": "2026-05-01", "end": "2026-03-31", "val": 500}]}},
                "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [{"form": "10-Q", "filed": "2026-05-01", "start": "2026-01-01", "end": "2026-03-31", "val": 20}]}},
                "NetCashProvidedByUsedInInvestingActivities": {"units": {"USD": [{"form": "10-Q", "filed": "2026-05-01", "start": "2026-01-01", "end": "2026-03-31", "val": -5}]}},
                "NetCashProvidedByUsedInFinancingActivities": {"units": {"USD": [{"form": "10-Q", "filed": "2026-05-01", "start": "2026-01-01", "end": "2026-03-31", "val": -2}]}},
            }},
            "entityName": "AAA Inc",
            "cik": "1",
        },
        "NOK": {
            "facts": {"ifrs-full": {
                "Revenue": {"units": {"EUR": [{"form": "20-F", "filed": "2026-04-30", "start": "2026-01-01", "end": "2026-03-31", "val": 200}]}},
                "ProfitLoss": {"units": {"EUR": [{"form": "20-F", "filed": "2026-04-30", "start": "2026-01-01", "end": "2026-03-31", "val": 30}]}},
                "Assets": {"units": {"EUR": [{"form": "20-F", "filed": "2026-04-30", "end": "2026-03-31", "val": 800}]}},
                "CashFlowsFromUsedInOperatingActivities": {"units": {"EUR": [{"form": "20-F", "filed": "2026-04-30", "start": "2026-01-01", "end": "2026-03-31", "val": 40}]}},
                "CashFlowsFromUsedInInvestingActivities": {"units": {"EUR": [{"form": "20-F", "filed": "2026-04-30", "start": "2026-01-01", "end": "2026-03-31", "val": -15}]}},
                "CashFlowsFromUsedInFinancingActivities": {"units": {"EUR": [{"form": "20-F", "filed": "2026-04-30", "start": "2026-01-01", "end": "2026-03-31", "val": -3}]}},
            }},
            "entityName": "Nokia Corporation",
            "cik": "924613",
        },
    }

    out, summary = fill_financial_values(rows, facts_by_ticker=facts, as_of=date(2026, 5, 12))
    assert out[0]["revenue_value"] == "100"
    assert out[1]["revenue_value"] == "200"
    assert out[1]["financial_values_namespace"] == "ifrs-full"
    assert summary["rows_with_any_missing_financial_value"] == 0


def test_missing_financial_value_gets_reason_not_silent_blank():
    out, summary = fill_financial_values(
        [{"ticker": "CIFR", "quarter": "2022Q1", "entry_open_date": "2022-03-07"}],
        facts_by_ticker={"CIFR": {"facts": {"us-gaap": {}}}},
        as_of=date(2022, 3, 7),
    )
    assert out[0]["revenue_value"] == ""
    assert out[0]["revenue_value_missing_reason"] == "source_fact_unavailable_as_of"
    assert "revenue_value" in out[0]["financial_values_missing_fields"]
    assert summary["rows_with_any_missing_financial_value"] == 1
```

- [x] **Step 2: Run failing test**

Run:

```bash
python -m pytest tests/test_fundamental_panel_financial_values.py -q
```

Expected: FAIL with missing module.

- [x] **Step 3: Implement financial extraction**

Implementation requirements:

- Use structured companyfacts JSON, not string parsing.
- Preferred concepts:
  - revenue: US GAAP `Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`, `SalesRevenueNet`; IFRS `Revenue`, `RevenueFromContractsWithCustomers`; sector fallbacks for homebuilders, insurers, REITs, and asset managers
  - net income: `NetIncomeLoss`, `ProfitLoss`, IFRS parent profit variants
  - assets: `Assets`
  - cash flow: US GAAP `NetCashProvidedByUsedIn*`; IFRS `CashFlowsFromUsedIn*`
- Prefer strict facts filed on/before the row as-of date.
- If only later comparative/restated fact exists, fill only when `allow_relaxed_filed_date=True` and mark `financial_values_source=companyfacts_relaxed_filed_date`.
- Never invent zeros for missing values.

- [x] **Step 4: Run focused tests**

Run:

```bash
python -m pytest tests/test_fundamental_panel_financial_values.py -q
```

Expected: PASS.

---

## Task 3: Normalize Current Run Artifacts Into Complete Rows

**Files:**

- Create: `tradingagents/research/fundamental/src/panel/normalize.py`
- Test: `tests/test_fundamental_panel_normalize.py`

- [x] **Step 1: Write failing normalization tests**

```python
# tests/test_fundamental_panel_normalize.py
from tradingagents.research.fundamental.src.panel.normalize import normalize_complete_panel_rows


def test_normalize_derives_legacy_post_llm_subtiers_from_canonical_fields():
    rows = [{
        "ticker": "AAA",
        "quarter": "2026Q2",
        "tier_1_bucket": "Tier 1 - Balanced priority feed",
        "post_llm_candidate_flag": "1",
        "post_llm_high_priority_flag": "1",
        "causal_change": "3",
        "negative_revision_risk": "1",
        "narrative_delta_bucket": "constructive",
        "score_addition": "3",
        "prior_score_addition": "1",
    }]
    out, summary = normalize_complete_panel_rows(rows, source_name="daily_final_scores")
    row = out[0]
    assert row["post_llm_tier_1_1_flag"] == "1"
    assert row["post_llm_tier_1_2_flag"] == "1"
    assert row["post_llm_tier_1_3_flag"] == "1"
    assert row["post_llm_tier_1_4_flag"] == "1"
    assert summary["rows"] == 1


def test_normalize_fills_flag_blanks_with_zero():
    rows = [{"ticker": "BBB", "quarter": "2026Q2", "post_llm_candidate_flag": ""}]
    out, _ = normalize_complete_panel_rows(rows, source_name="daily_final_scores")
    assert out[0]["top15_selected"] == "0"
    assert out[0]["shadow_selected"] == "0"
    assert out[0]["post_llm_candidate_flag"] == "0"
```

- [x] **Step 2: Run failing test**

Run:

```bash
python -m pytest tests/test_fundamental_panel_normalize.py -q
```

Expected: FAIL with missing module.

- [x] **Step 3: Implement normalizer**

Implementation requirements:

- Accept current daily final-score rows, tier rows, LLM eligibility rows, score quarantines, and optional prior panel rows.
- Normalize identity fields:
  - `ticker`
  - `symbol`
  - `cik`
  - `company_title`
  - `quarter`
- Normalize required source/provenance fields:
  - `source_run_root`
  - `source_artifact`
  - `source_artifact_sha256`
  - `field_population_status`
- Call `add_post_llm_subtiers()` for legacy subtier flags.
- Call `fill_financial_values()` for raw financial fields.
- Call existing feature derivation helpers instead of reimplementing formulas:
  - `build_pre_llm_score`
  - `assign_daily_tiers`
  - `add_post_llm_subtiers`
  - `build_signal_tables` where needed
- Preserve final scoring fields from `fundamental_final_scores.csv` when present.

- [x] **Step 4: Run focused tests**

Run:

```bash
python -m pytest tests/test_fundamental_panel_normalize.py -q
```

Expected: PASS.

---

## Task 4: Attach Top15 and Shadow Refill Annotations From Canonical Selection

**Files:**

- Create: `tradingagents/research/fundamental/src/panel/selection_annotations.py`
- Test: `tests/test_fundamental_panel_selection_annotations.py`

- [x] **Step 1: Write failing tests**

```python
# tests/test_fundamental_panel_selection_annotations.py
from pathlib import Path

from tradingagents.research.fundamental.src.panel.selection_annotations import attach_selection_annotations


def test_attach_selection_annotations_marks_top15_and_shadow(tmp_path):
    rows = [
        {"ticker": "AAA", "quarter": "2026Q2"},
        {"ticker": "BBB", "quarter": "2026Q2"},
    ]
    top15 = tmp_path / "high_conviction_top15.csv"
    top15.write_text("ticker,selection_rank,selected_sleeve,top15_bucket\\nAAA,1,core,Top 10 core\\n")
    shadow = tmp_path / "shadow.csv"
    shadow.write_text("ticker,selection_rank,selected_sleeve,shadow_refill_status\\nBBB,1,core,shadow_refill_review_only_not_official\\n")

    out, summary = attach_selection_annotations(rows, top15_csv=top15, shadow_csv=shadow, quarter="2026Q2")
    by_ticker = {row["ticker"]: row for row in out}
    assert by_ticker["AAA"]["top15_selected"] == "1"
    assert by_ticker["BBB"]["shadow_selected"] == "1"
    assert summary["top15_selected_count"] == 1
    assert summary["shadow_selected_count"] == 1
```

- [x] **Step 2: Run failing test**

Run:

```bash
python -m pytest tests/test_fundamental_panel_selection_annotations.py -q
```

Expected: FAIL with missing module.

- [x] **Step 3: Implement selection annotation**

Implementation requirements:

- Prefer running selectors from final scores when `top15_csv` or `shadow_csv` is absent.
- Use:
  - `select_top15_from_csv`
  - `select_top15_core_deterioration_refill_shadow_from_csv`
- Annotate rows by `(quarter, ticker)`.
- For unselected rows, fill all selection flag fields as `0`.
- Validate selected tickers exist in panel rows.
- Emit selection summary with official and shadow counts.

- [x] **Step 4: Run focused tests**

Run:

```bash
python -m pytest tests/test_fundamental_panel_selection_annotations.py -q
```

Expected: PASS.

---

## Task 5: Validate No Silent Blanks and No Selector Leakage

**Files:**

- Create: `tradingagents/research/fundamental/src/panel/validate.py`
- Test: `tests/test_fundamental_panel_validate.py`

- [x] **Step 1: Write failing validation tests**

```python
# tests/test_fundamental_panel_validate.py
from tradingagents.research.fundamental.src.panel.validate import validate_complete_panel


def test_validate_complete_panel_fails_on_required_blank_without_reason():
    result = validate_complete_panel([{
        "ticker": "AAA",
        "quarter": "2026Q2",
        "revenue_value": "",
        "revenue_value_missing_reason": "",
    }])
    assert result["passed"] is False
    assert result["errors"][0]["code"] == "required_blank_without_reason"


def test_validate_complete_panel_accepts_allowed_source_unavailable_reason():
    result = validate_complete_panel([{
        "ticker": "CIFR",
        "quarter": "2022Q1",
        "revenue_value": "",
        "revenue_value_missing_reason": "source_fact_unavailable_as_of",
    }])
    assert result["passed"] is True


def test_validate_complete_panel_rejects_duplicate_ticker_quarter():
    result = validate_complete_panel([
        {"ticker": "AAA", "quarter": "2026Q2"},
        {"ticker": "AAA", "quarter": "2026Q2"},
    ])
    assert result["passed"] is False
    assert any(error["code"] == "duplicate_ticker_quarter" for error in result["errors"])
```

- [x] **Step 2: Run failing test**

Run:

```bash
python -m pytest tests/test_fundamental_panel_validate.py -q
```

Expected: FAIL with missing module.

- [x] **Step 3: Implement validation**

Validation rules:

- Missing column: hard fail.
- Duplicate `(quarter, ticker)`: hard fail.
- Required nonblank field blank without missing reason: hard fail.
- Flag field blank or non-`0/1`: hard fail.
- Selection forbidden columns cannot be used in ranking logic.
- If Top15/shadow artifacts are provided, selected identities must match annotations.
- If output scope says `2021Q4-2026Q2`, quarter coverage must match exactly.

- [x] **Step 4: Run validation tests**

Run:

```bash
python -m pytest tests/test_fundamental_panel_validate.py -q
```

Expected: PASS.

---

## Task 6: Complete Panel Exporter

**Files:**

- Create: `tradingagents/research/fundamental/src/panel/exporter.py`
- Test: `tests/test_fundamental_panel_exporter.py`

- [x] **Step 1: Write failing exporter test**

```python
# tests/test_fundamental_panel_exporter.py
import csv
import json

from tradingagents.research.fundamental.src.panel.exporter import build_complete_panel


def test_build_complete_panel_writes_csv_manifest_columns_and_validation(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    final_scores = run / "fundamental_final_scores_2026-05-12.csv"
    final_scores.write_text(
        "ticker,quarter,symbol,cik,company_title,entry_score_0_100,confidence,tier_1_bucket,post_llm_candidate_flag,causal_change,negative_revision_risk\\n"
        "AAA,2026Q2,AAA,1,AAA Inc,80,high,Tier 1 - Balanced priority feed,1,3,1\\n"
    )
    top15 = run / "high_conviction_top15.csv"
    top15.write_text("ticker,selection_rank,selected_sleeve,top15_bucket\\nAAA,1,core,Top 10 core\\n")
    shadow = run / "high_conviction_top15_core_deterioration_refill_shadow.csv"
    shadow.write_text("ticker,selection_rank,selected_sleeve,shadow_refill_status\\nAAA,1,core,shadow_refill_review_only_not_official\\n")

    result = build_complete_panel(
        run_root=run,
        output_root=tmp_path / "out",
        quarter="2026Q2",
        as_of="2026-05-12",
        prior_panel_path=None,
        allow_missing_financials=True,
    )

    assert result["validation"]["passed"] is True
    assert result["csv_path"].endswith(".csv")
    assert result["manifest_path"].endswith("_manifest.json")
    assert result["columns_path"].endswith("_columns.json")
    assert result["validation_path"].endswith("_validation.json")

    with open(result["csv_path"], newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["ticker"] == "AAA"
    assert rows[0]["top15_selected"] == "1"
    assert rows[0]["shadow_selected"] == "1"


def test_build_complete_panel_rejects_raw_growth_prior_panel(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    final_scores = run / "fundamental_final_scores_2026-05-12.csv"
    final_scores.write_text("ticker,quarter\nAAA,2026Q2\n")
    growth_prior = tmp_path / "Growth" / "combined_all_tiers.csv"
    growth_prior.parent.mkdir()
    growth_prior.write_text("ticker,quarter\nAAA,2026Q1\n")

    result = build_complete_panel(
        run_root=run,
        output_root=tmp_path / "out",
        quarter="2026Q2",
        as_of="2026-05-12",
        prior_panel_path=growth_prior,
        allow_missing_financials=True,
    )

    assert result["validation"]["passed"] is False
    assert any(error["code"] == "prior_panel_not_canonical" for error in result["validation"]["errors"])
```

- [x] **Step 2: Run failing test**

Run:

```bash
python -m pytest tests/test_fundamental_panel_exporter.py -q
```

Expected: FAIL with missing module.

- [x] **Step 3: Implement exporter**

Implementation requirements:

- Locate artifacts from `run_root`:
  - `fundamental_final_scores_*.csv`
  - `tier_classification.csv`
  - `llm_eligibility.csv`
  - `llm_quarantine.csv`
  - `score_input_quarantine.csv`
  - `post_llm_scores.csv` if present
  - `high_conviction_top15.csv`
  - `high_conviction_top15_core_deterioration_refill_shadow.csv`
- Accept optional `prior_panel_path` and append non-overlapping prior quarters after revalidation.
- Reject direct legacy `Growth/` combined CSVs as `prior_panel_not_canonical`.
- Require prior panel manifest/validation sidecar with matching schema version and `passed=true` before appending.
- Never append a stale row for the same `(quarter, ticker)`.
- Normalize every row through `normalize_complete_panel_rows`.
- Attach Top15/shadow annotations through `selection_annotations`.
- Validate through `validate_complete_panel`.
- Write manifest with:
  - source artifact hashes
  - schema version
  - row counts by quarter
  - blank counts by required field
  - missing reasons by field
  - top15/shadow counts
  - output SHA256

- [x] **Step 4: Run exporter test**

Run:

```bash
python -m pytest tests/test_fundamental_panel_exporter.py -q
```

Expected: PASS.

---

## Task 7: CLI Command

**Files:**

- Modify: `tradingagents/research/fundamental/src/cli/commands.py`
- Test: `tests/test_cli_fundamental_build_complete_panel.py`

- [x] **Step 1: Write failing CLI tests**

```python
# tests/test_cli_fundamental_build_complete_panel.py
from typer.testing import CliRunner

from cli.main import app


runner = CliRunner()


def test_fundamental_build_complete_panel_help():
    result = runner.invoke(app, ["fundamental-build-complete-panel", "--help"])
    assert result.exit_code == 0
    assert "--run-root" in result.output
    assert "--quarter" in result.output
    assert "--output-root" in result.output


def test_fundamental_build_complete_panel_rejects_missing_run_root(tmp_path):
    result = runner.invoke(app, [
        "fundamental-build-complete-panel",
        "--run-root", str(tmp_path / "missing"),
        "--quarter", "2026Q2",
        "--date", "2026-05-12",
        "--output-root", str(tmp_path / "out"),
    ])
    assert result.exit_code != 0
    assert "run root" in result.output.lower()
```

- [x] **Step 2: Run failing CLI test**

Run:

```bash
python -m pytest tests/test_cli_fundamental_build_complete_panel.py -q
```

Expected: FAIL because command does not exist.

- [x] **Step 3: Add CLI command**

Command contract:

```bash
python -m cli.main fundamental-build-complete-panel \
  --run-root <daily-run-root> \
  --quarter 2026Q2 \
  --date 2026-05-12 \
  --output-root <output-root> \
  --prior-panel <optional-existing-complete-panel>
```

Options:

- `--allow-missing-financials / --strict-financials`
- `--run-selectors / --use-existing-selectors`
- `--format table|json`

Exit behavior:

- Exit `0` only when validation passes.
- Exit nonzero when required blanks, duplicate keys, or selector identity mismatch exist.

- [x] **Step 4: Run CLI tests**

Run:

```bash
python -m pytest tests/test_cli_fundamental_build_complete_panel.py -q
```

Expected: PASS.

---

## Task 8: Remove Growth Output Ownership

**Files:**

- Test: `tests/test_fundamental_no_growth_output_ownership.py`
- Modify only if needed:
  - `tradingagents/research/fundamental/backtests/pit_panel.py`
  - `tradingagents/research/fundamental/docs/complete_candidate_panel_contract.md`

- [x] **Step 1: Write failing architecture test**

```python
# tests/test_fundamental_no_growth_output_ownership.py
from pathlib import Path


def test_src_panel_and_daily_run_do_not_import_growth_scripts():
    root = Path("tradingagents/research/fundamental/src")
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "tradingagents.research.fundamental.Growth" in text or "fundamental/Growth" in text:
            offenders.append(str(path))
    assert offenders == []


def test_complete_panel_exporter_is_under_src_not_growth():
    path = Path("tradingagents/research/fundamental/src/panel/exporter.py")
    assert path.exists()
```

- [x] **Step 2: Run architecture test**

Run:

```bash
python -m pytest tests/test_fundamental_no_growth_output_ownership.py -q
```

Expected: PASS after Tasks 1-7.

- [x] **Step 3: Document legacy status**

Add to `complete_candidate_panel_contract.md`:

- `Growth/` scripts are historical research artifacts.
- New publishable complete panels must come from `src.panel.exporter`.
- Legacy combined CSVs can be imported only by explicit migration tooling, not directly as `--prior-panel`.

---

## Task 9: Integrate Complete Panel Emission Into Daily Run

**Files:**

- Modify: `tradingagents/research/fundamental/src/daily_run/models.py`
- Modify: `tradingagents/research/fundamental/src/daily_run/orchestrator.py`
- Modify: `tradingagents/research/fundamental/src/cli/commands.py`
- Test: `tests/test_cli_fundamental_run_today.py`
- Test: `tests/test_fundamental_daily_orchestrator_contract.py`

- [x] **Step 1: Write failing CLI and orchestrator tests**

```python
# tests/test_cli_fundamental_run_today.py
from typer.testing import CliRunner

from cli.main import app


runner = CliRunner()


def test_fundamental_run_today_help_exposes_complete_panel_options():
    result = runner.invoke(app, ["fundamental-run-today", "--help"])
    assert result.exit_code == 0
    assert "--emit-complete-panel" in result.output
    assert "--complete-panel-output-root" in result.output
```

```python
# tests/test_fundamental_daily_orchestrator_contract.py
def test_orchestrator_emits_complete_panel_after_publish_when_requested(tmp_path):
    cfg, services = _fake_orchestrator_fixture(tmp_path)
    cfg = DailyRunConfig(**{
        **cfg.__dict__,
        "emit_complete_panel": True,
        "complete_panel_output_root": tmp_path / "panel",
    })

    result = run_daily_fundamental(cfg, services=services)

    assert result.summary["final"] is True
    assert "complete_panel_csv" in result.artifacts
    assert (tmp_path / "panel").exists()
```

- [x] **Step 2: Run failing tests**

Run:

```bash
python -m pytest \
  tests/test_cli_fundamental_run_today.py::test_fundamental_run_today_help_exposes_complete_panel_options \
  tests/test_fundamental_daily_orchestrator_contract.py::test_orchestrator_emits_complete_panel_after_publish_when_requested \
  -q
```

Expected: FAIL because daily-run config and CLI do not expose complete-panel emission.

- [x] **Step 3: Implement daily-run hook**

Implementation requirements:

- Add `emit_complete_panel: bool = False` to `DailyRunConfig`.
- Add `complete_panel_output_root: Path | None = None` to `DailyRunConfig`.
- Add CLI options:
  - `--emit-complete-panel / --no-emit-complete-panel`
  - `--complete-panel-output-root <path>`
- After Gate 10 publish passes, call `build_complete_panel()` with the current daily run output root as `run_root`.
- If complete-panel validation fails and `emit_complete_panel=True`, hard-stop finalization and return a failed validation artifact.
- Record `complete_panel_csv`, `complete_panel_manifest`, `complete_panel_columns`, and `complete_panel_validation` in daily-run artifacts.
- Keep default behavior unchanged when `emit_complete_panel=False`.

- [x] **Step 4: Run daily-run integration tests**

Run:

```bash
python -m pytest \
  tests/test_cli_fundamental_run_today.py \
  tests/test_fundamental_daily_orchestrator_contract.py \
  -q
```

Expected: PASS.

---

## Task 10: Full Contract Regression Against Existing 2026Q2 Run

**Files:**

- Test: `tests/test_fundamental_panel_exporter.py`
- No production file changes unless this test exposes a real contract gap.

- [x] **Step 1: Add integration-style fixture test**

Test using existing local artifact paths when present; skip if missing:

```python
def test_existing_2026q2_run_exports_complete_panel_contract(tmp_path):
    import pytest
    from pathlib import Path
    from tradingagents.research.fundamental.src.panel.exporter import build_complete_panel

    run_root = Path("eval_results/fundamental/2026-05-12_2026Q2_hp_rm_final_v3")
    if not run_root.exists():
        pytest.skip("local 2026Q2 run artifact not present")

    result = build_complete_panel(
        run_root=run_root,
        output_root=tmp_path / "panel",
        quarter="2026Q2",
        as_of="2026-05-12",
        prior_panel_path=None,
        allow_missing_financials=True,
    )

    assert result["validation"]["passed"] is True
    assert result["validation"]["duplicate_ticker_quarter_count"] == 0
    assert result["validation"]["required_columns_missing"] == []
    assert result["validation"]["top15_selected_count"] == 15
    assert result["validation"]["shadow_selected_count"] == 15
```

- [x] **Step 2: Run integration test**

Run:

```bash
python -m pytest tests/test_fundamental_panel_exporter.py::test_existing_2026q2_run_exports_complete_panel_contract -q
```

Expected: PASS or SKIP if artifact absent.

---

## Task 11: Documentation and Operator Runbook

**Files:**

- Create: `tradingagents/research/fundamental/docs/complete_candidate_panel_contract.md`
- Modify: `tradingagents/research/fundamental/docs/README.md`
- Modify: `memory/WORKING.md`

- [x] **Step 1: Write contract doc**

Required sections:

- Purpose
- One-command usage
- Required fields
- Allowed missing reasons
- Output files
- Validation gates
- Relationship to Top10+Plus5+shadow refill
- Legacy `Growth/` status

- [x] **Step 2: Link doc from docs README**

Add a bullet for `complete_candidate_panel_contract.md`.

- [x] **Step 3: Update memory**

Record:

- command name
- output path convention
- schema version
- validation command
- status of `Growth/`

---

## Task 12: Final Verification

Run:

```bash
python -m pytest \
  tests/test_fundamental_panel_schema.py \
  tests/test_fundamental_panel_financial_values.py \
  tests/test_fundamental_panel_normalize.py \
  tests/test_fundamental_panel_selection_annotations.py \
  tests/test_fundamental_panel_validate.py \
  tests/test_fundamental_panel_exporter.py \
  tests/test_cli_fundamental_build_complete_panel.py \
  tests/test_fundamental_no_growth_output_ownership.py \
  tests/test_cli_fundamental_run_today.py \
  tests/test_fundamental_daily_*.py \
  tests/test_fundamental_high_conviction_top10.py \
  tests/test_cli_fundamental_top15_refill_shadow.py \
  -q
```

Expected:

- all tests pass
- no duplicate ticker-quarter rows
- Q2 Top15 matches source selector
- Q2 shadow matches source selector
- `fundamental-run-today --emit-complete-panel` writes the same canonical panel artifacts as `fundamental-build-complete-panel`
- no blank required fields unless allowed missing reason exists
- all flag columns are `0/1`

Run py_compile:

```bash
python -m py_compile \
  tradingagents/research/fundamental/src/panel/schema.py \
  tradingagents/research/fundamental/src/panel/financial_values.py \
  tradingagents/research/fundamental/src/panel/normalize.py \
  tradingagents/research/fundamental/src/panel/selection_annotations.py \
  tradingagents/research/fundamental/src/panel/validate.py \
  tradingagents/research/fundamental/src/panel/exporter.py \
  tradingagents/research/fundamental/src/cli/commands.py
```

Expected: no output, exit `0`.

Completed final verification:

- Target pytest suite: `117 passed, 2 warnings`.
- Touched production py_compile: exit `0`.
- Final read-only QA blocker was fixed and re-reviewed: exporter now validates forbidden selector source columns before CSV narrowing.

---

## QA/QC Checklist

- [x] Plan creates a single canonical producer under `src/`.
- [x] Plan does not make `Growth/` an output owner.
- [x] Plan includes tests for required field population.
- [x] Plan includes tests for allowed missing reasons.
- [x] Plan includes tests for Q2 legacy subtier derivation.
- [x] Plan includes selector annotation and identity validation.
- [x] Plan includes no-leakage validation.
- [x] Plan includes standalone CLI entrypoint.
- [x] Plan includes daily-run complete-panel emission.
- [x] Plan blocks raw legacy `Growth/` CSVs from direct `--prior-panel` use.
- [x] Plan includes operator docs.
- [x] Plan includes final verification commands.

QA/QC status: PASS. The plan now has one canonical producer, no `Growth/` output ownership, direct daily-run emission, standalone rebuild support, prior-panel canonical validation, and publish-blocking validation.

---

## Implementation Order

Recommended order:

1. Schema.
2. Financial values.
3. Normalization.
4. Selection annotations.
5. Validation.
6. Exporter.
7. CLI.
8. Daily-run integration.
9. Full regression.
10. Documentation.
11. Final verification.

This order makes each layer testable before the next one depends on it.
