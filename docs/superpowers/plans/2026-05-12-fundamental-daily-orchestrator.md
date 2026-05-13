# Fundamental Daily Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one gated daily orchestrator for "run the fundamental framework for today" so broad-master final runs cannot silently collapse into scout-only, incomplete, or wrong-LLM-universe outputs.

**Architecture:** Add a focused `daily_run` package under the existing fundamental framework. It wraps existing SEC, scoring, LLM, HP/RM, and Top15 modules with explicit gate state, artifacts, hard stop conditions, and dependency injection for tests. Do not rewrite scoring internals; enforce lineage/count/eligibility contracts around them.

**Tech Stack:** Python 3.10+, Typer, pandas, pytest, existing `tradingagents.research.fundamental.src` modules, local SEC cache, Yahoo price adapter, external Codex LLM runner.

---

## Critical thinking / scope decision

## Decision: gated wrapper, not scoring rewrite

### Initial inclination

Build a new orchestrator package that calls existing modules in the right order because the current failure was orchestration/lineage, not fundamental math.

### Adversarial challenge

Against this approach:

- A wrapper can create false safety if it trusts bad outputs from existing scripts.
- Current SEC coverage code has hard-coded output names and module globals; careless wrapping can still misroute files.
- Tier 0-4 currently depends on `entry_open`, so companyfacts coverage alone is not enough.
- Fetch queue `0` does not mean LLM-ready; metadata gaps can remain.
- If tests only assert command success, the known 162-vs-1276 failure can recur.

What might be wrong:

- Some existing modules may not expose clean pure functions, so small adapter seams may be needed.
- Price/tradable-date coverage may be the real daily blocker, not SEC filings.

### Resolution

The implementation must assert row-count lineage at each gate and use dependency injection/mocks in tests. Live SEC, price, and LLM calls must be outside unit tests. A failed gate is a valid output only if it writes a diagnosis and blocks final publish.

### Recommendation

Implement the daily orchestrator in small gate files with explicit artifacts, hard stops, and tests proving:

- broad final mode cannot use scout-only universe
- pre-LLM scoring can proceed despite missing earnings exhibits
- Tier assignment stops/quarantines missing `entry_open`
- LLM packets are only Tier 1-4 evidence-ready rows
- final scores preserve broad row count
- Top10 + Plus5 + shadow publishes only from broad final scores

---

## Existing context to read first

- `tradingagents/research/fundamental/docs/daily_run_gate_sequence.md`
- `tradingagents/research/fundamental/docs/daily_universe_llm_funnel_contract.md`
- `tradingagents/research/fundamental/src/cli/commands.py`
- `tradingagents/research/fundamental/src/pipeline/dealflow_adapter.py`
- `tradingagents/research/fundamental/src/sec_pipeline/cache_coverage_manifest.py`
- `tradingagents/research/fundamental/src/sec_pipeline/cache_download_queue.py`
- `tradingagents/research/fundamental/src/features/pre_llm_scores.py`
- `tradingagents/research/fundamental/src/features/tiers.py`
- `tradingagents/research/fundamental/src/features/llm_packets.py`
- `tradingagents/research/fundamental/src/pipeline/run_on_new_filing.py`
- `tradingagents/research/fundamental/src/selection/high_conviction_top10.py`

Current reference counts from the 2026Q2 diagnostic run:

- broad master universe: `1,276`
- scout-only mistaken scoring universe: `162`
- companyfacts cached: `1,276`
- pre-LLM scorable: `1,262`
- strict full LLM-doc ready: `76`
- strict full LLM-doc incomplete: `1,200`
- fetch queue after fast SEC materialization: `0`
- hard domestic-pipeline invalid tickers: `NOK`, `SILC`, `TSEM`

---

## File structure

Create:

- `tradingagents/research/fundamental/src/daily_run/__init__.py`
  - Public exports for the orchestrator package.

- `tradingagents/research/fundamental/src/daily_run/models.py`
  - Dataclasses/enums for run mode, gate status, gate result, run config, run state, and stop errors.

- `tradingagents/research/fundamental/src/daily_run/artifacts.py`
  - Atomic JSON/CSV/Markdown writers, snapshot helpers, source hash capture, and run report rendering.

- `tradingagents/research/fundamental/src/daily_run/universe.py`
  - Build broad master universe from SEC-eligible JSON/CSV, append scout tickers, dedupe, write drift report, enforce broad-vs-scout guard.

- `tradingagents/research/fundamental/src/daily_run/coverage.py`
  - Run/reuse SEC coverage manifest, run fetch loop until stable, classify missing inputs by stage, load cached raw documents for LLM evidence.

- `tradingagents/research/fundamental/src/daily_run/scoring_inputs.py`
  - Build pre-LLM rows from cached companyfacts, derive conservative tradable dates, fetch/attach entry prices, write readiness/quarantine reports.

- `tradingagents/research/fundamental/src/daily_run/eligibility.py`
  - Assign Tier 0-4, compute LLM eligibility, build LLM packets only for eligible Tier 1-4 evidence-ready rows, validate packet counts.

- `tradingagents/research/fundamental/src/daily_run/llm_validation.py`
  - Validate post-LLM CSV rows against packet sample IDs before merge.

- `tradingagents/research/fundamental/src/daily_run/finalize.py`
  - Merge post-LLM into broad rows, compute final signal rows/HP/RM via `build_signal_tables`, export final scores, run Top10 + Plus5 + shadow refill with broad-input guard.

- `tradingagents/research/fundamental/src/daily_run/orchestrator.py`
  - Sequential 10-gate runner with dependency injection, stop-gate handling, resume-aware artifacts, and final run report.

Create tests:

- `tests/test_fundamental_daily_run_models.py`
- `tests/test_fundamental_daily_universe_gate.py`
- `tests/test_fundamental_daily_coverage_gate.py`
- `tests/test_fundamental_daily_scoring_inputs.py`
- `tests/test_fundamental_daily_eligibility_gate.py`
- `tests/test_fundamental_daily_llm_validation.py`
- `tests/test_fundamental_daily_finalize_gate.py`
- `tests/test_cli_fundamental_run_today.py`
- `tests/test_fundamental_daily_orchestrator_contract.py`

Modify:

- `tradingagents/research/fundamental/src/cli/commands.py`
  - Add new command `fundamental-run-today`. Keep existing `fundamental` command backward-compatible as scout-smoke legacy.
  - Command naming decision: use flat `fundamental-run-today` in this implementation because the current Typer app already has a flat `fundamental` command; a nested `fundamental run-today` group would require a separate backward-compatibility refactor.

- `tradingagents/research/fundamental/docs/daily_run_gate_sequence.md`
  - Add implemented command name and produced artifacts after implementation.

Do not modify scoring formulas unless a failing test proves the formula violates the gate contract.

---

## Task 1: Gate models and artifact writers

**Files:**

- Create: `tradingagents/research/fundamental/src/daily_run/__init__.py`
- Create: `tradingagents/research/fundamental/src/daily_run/models.py`
- Create: `tradingagents/research/fundamental/src/daily_run/artifacts.py`
- Test: `tests/test_fundamental_daily_run_models.py`

- [ ] **Step 1: Write failing tests for run mode, gate result, and artifact writing**

```python
# tests/test_fundamental_daily_run_models.py
import json
from pathlib import Path

import pytest

from tradingagents.research.fundamental.src.daily_run.artifacts import write_json_atomic
from tradingagents.research.fundamental.src.daily_run.models import (
    DailyRunConfig,
    GateResult,
    GateStatus,
    RunMode,
    StopGateError,
)


def test_daily_run_config_rejects_missing_mode(tmp_path):
    with pytest.raises(ValueError, match="mode"):
        DailyRunConfig(as_of="2026-05-12", quarter="2026Q2", mode="", output_root=tmp_path)


def test_daily_run_config_accepts_broad_master_final(tmp_path):
    cfg = DailyRunConfig(as_of="2026-05-12", quarter="2026Q2", mode="broad-master-final", output_root=tmp_path)
    assert cfg.run_mode == RunMode.BROAD_MASTER_FINAL
    assert cfg.output_root == tmp_path


def test_gate_result_hard_stop_raises_stop_gate_error():
    result = GateResult(
        gate_number=2,
        gate_name="Universe construction",
        status=GateStatus.HARD_STOP,
        summary={"reason": "scout_only_universe"},
        artifacts={},
    )
    with pytest.raises(StopGateError, match="Gate 2"):
        result.raise_if_hard_stop()


def test_write_json_atomic_round_trips(tmp_path):
    path = tmp_path / "run_manifest.json"
    write_json_atomic(path, {"status": "ok", "rows": 1276})
    assert json.loads(path.read_text()) == {"status": "ok", "rows": 1276}
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_fundamental_daily_run_models.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `daily_run`.

- [ ] **Step 3: Implement models**

```python
# tradingagents/research/fundamental/src/daily_run/models.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class RunMode(str, Enum):
    BROAD_MASTER_FINAL = "broad-master-final"
    SCOUT_SMOKE = "scout-smoke"
    DIAGNOSTIC_ONLY = "diagnostic-only"


class GateStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    HARD_STOP = "hard_stop"
    SKIPPED = "skipped"


class StopGateError(RuntimeError):
    def __init__(self, result: "GateResult") -> None:
        self.result = result
        super().__init__(f"Gate {result.gate_number} hard stop: {result.gate_name}: {result.summary}")


@dataclass(frozen=True)
class DailyRunConfig:
    as_of: str
    quarter: str
    mode: str
    output_root: Path
    master_universe_path: Path | None = None
    handoff_path: Path | None = None
    sec_live_root: Path | None = None
    skip_fetch: bool = False
    skip_llm: bool = False
    llm_mode: str = "subagent"
    llm_model: str = "gpt-5.5"
    llm_reasoning_effort: str = "high"
    min_broad_universe_count: int = 1000

    @property
    def run_mode(self) -> RunMode:
        try:
            return RunMode(self.mode.strip().lower())
        except ValueError as exc:
            raise ValueError(f"mode must be one of {[m.value for m in RunMode]}") from exc


@dataclass
class GateResult:
    gate_number: int
    gate_name: str
    status: GateStatus
    summary: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)

    def raise_if_hard_stop(self) -> None:
        if self.status == GateStatus.HARD_STOP:
            raise StopGateError(self)


@dataclass
class DailyRunState:
    config: DailyRunConfig
    run_id: str
    gates: list[GateResult] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)

    def record(self, result: GateResult) -> GateResult:
        self.gates.append(result)
        self.artifacts.update(result.artifacts)
        return result
```

- [ ] **Step 4: Implement artifact helpers**

```python
# tradingagents/research/fundamental/src/daily_run/artifacts.py
from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

from tradingagents.research.fundamental.src.storage import source_file_hash


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        json.dump(payload, tmp, indent=2, sort_keys=True, default=str)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)
    return path


def write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    materialized = [dict(row) for row in rows]
    if not materialized:
        write_text_atomic(path, "")
        return path
    fieldnames = list(dict.fromkeys(key for row in materialized for key in row))
    with tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        writer = csv.DictWriter(tmp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(materialized)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)
    return path


def write_text_atomic(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp.write(text)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)
    return path


def source_hashes(paths: Mapping[str, Path | None]) -> dict[str, str]:
    return {name: source_file_hash(path) for name, path in paths.items()}
```

```python
# tradingagents/research/fundamental/src/daily_run/__init__.py
from .models import DailyRunConfig, DailyRunState, GateResult, GateStatus, RunMode, StopGateError

__all__ = ["DailyRunConfig", "DailyRunState", "GateResult", "GateStatus", "RunMode", "StopGateError"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_fundamental_daily_run_models.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tradingagents/research/fundamental/src/daily_run tests/test_fundamental_daily_run_models.py
git commit -m "feat: add fundamental daily run gate models"
```

---

## Task 2: Universe construction and broad-vs-scout guard

**Files:**

- Create: `tradingagents/research/fundamental/src/daily_run/universe.py`
- Test: `tests/test_fundamental_daily_universe_gate.py`

- [ ] **Step 1: Write failing universe tests**

```python
# tests/test_fundamental_daily_universe_gate.py
import json

from tradingagents.research.fundamental.src.daily_run.models import GateStatus, RunMode
from tradingagents.research.fundamental.src.daily_run.universe import (
    build_combined_universe,
    validate_universe_gate,
)


def _write_master_json(path):
    path.write_text(json.dumps({
        "items": [
            {"symbol": "AAA", "cik": "1", "company_title": "AAA Inc"},
            {"symbol": "BBB", "cik": "2", "company_title": "BBB Inc"},
            {"symbol": "CCC", "cik": "3", "company_title": "CCC Inc"},
        ]
    }))


def _write_handoff(path):
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "date": "2026-05-12",
        "source_stage": "scout_ticker_summary",
        "tickers": ["BBB", "DDD"],
        "metadata_by_ticker": {"DDD": {"scouts": ["breakout_scan"]}},
    }))


def test_build_combined_universe_appends_scouts_without_replacing_master(tmp_path):
    master = tmp_path / "final_dealflow_tickers_sec_eligible.json"
    handoff = tmp_path / "deal_flow" / "final_dealflow_tickers.json"
    _write_master_json(master)
    _write_handoff(handoff)

    result = build_combined_universe(
        master_universe_path=master,
        handoff_path=handoff,
        quarter="2026Q2",
        output_csv=tmp_path / "master_fundamental_universe_2026Q2.csv",
        unresolved_new_scouts={"DDD": {"cik": "4", "company_title": "DDD Inc", "cik_status": "resolved"}},
    )

    assert result.summary["master_count"] == 3
    assert result.summary["scout_count"] == 2
    assert result.summary["combined_count"] == 4
    assert result.summary["new_scout_count"] == 1
    assert [row["ticker"] for row in result.rows] == ["AAA", "BBB", "CCC", "DDD"]
    assert result.rows[-1]["dealflow_source_stage"] == "scout_ticker_summary"


def test_broad_final_hard_stops_when_universe_collapses_to_scout_only(tmp_path):
    rows = [{"ticker": f"S{i}", "cik": str(i), "quarter": "2026Q2"} for i in range(162)]

    gate = validate_universe_gate(
        rows,
        run_mode=RunMode.BROAD_MASTER_FINAL,
        scout_count=162,
        min_broad_universe_count=1000,
        artifacts={},
    )

    assert gate.status == GateStatus.HARD_STOP
    assert gate.summary["reason"] == "broad_master_universe_too_small_or_scout_only"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_fundamental_daily_universe_gate.py -v
```

Expected: FAIL because `daily_run.universe` does not exist.

- [ ] **Step 3: Implement universe gate**

```python
# tradingagents/research/fundamental/src/daily_run/universe.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .artifacts import write_csv, write_json_atomic
from .models import GateResult, GateStatus, RunMode


@dataclass
class UniverseBuildResult:
    rows: list[dict[str, Any]]
    summary: dict[str, Any]
    artifacts: dict[str, str]


def _ticker(value: Any) -> str:
    return str(value or "").upper().replace(".", "-").strip()


def _load_master_rows(path: Path, quarter: str) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for item in payload.get("items", []):
        ticker = _ticker(item.get("symbol") or item.get("ticker"))
        if not ticker:
            continue
        rows.append({
            "ticker": ticker,
            "symbol": ticker,
            "cik": str(item.get("cik", "")).strip(),
            "company_title": str(item.get("company_title", "")).strip(),
            "cik_status": str(item.get("cik_status") or "resolved").strip(),
            "quarter": quarter,
            "master_universe_source": path.name,
            "dealflow_source_stage": "master_fundamental_universe",
            "scouts_json": "[]",
        })
    return rows


def _load_scout_payload(path: Path | None) -> tuple[list[str], dict[str, Any], str]:
    if path is None or not path.exists():
        return [], {}, ""
    payload = json.loads(path.read_text(encoding="utf-8"))
    tickers = []
    seen: set[str] = set()
    for raw in payload.get("tickers", []) or []:
        ticker = _ticker(raw)
        if ticker and ticker not in seen:
            tickers.append(ticker)
            seen.add(ticker)
    return tickers, dict(payload.get("metadata_by_ticker") or {}), str(payload.get("source_stage") or "")


def build_combined_universe(
    *,
    master_universe_path: Path,
    handoff_path: Path | None,
    quarter: str,
    output_csv: Path,
    unresolved_new_scouts: Mapping[str, Mapping[str, Any]] | None = None,
) -> UniverseBuildResult:
    master_rows = _load_master_rows(master_universe_path, quarter)
    by_ticker = {row["ticker"]: dict(row) for row in master_rows}
    scouts, metadata, source_stage = _load_scout_payload(handoff_path)
    resolved_new = {str(k).upper(): dict(v) for k, v in (unresolved_new_scouts or {}).items()}
    new_scouts: list[str] = []

    for ticker in scouts:
        scout_meta = dict(metadata.get(ticker) or {})
        if ticker in by_ticker:
            by_ticker[ticker]["dealflow_source_stage"] = source_stage or by_ticker[ticker].get("dealflow_source_stage", "")
            by_ticker[ticker]["scouts_json"] = json.dumps(list(scout_meta.get("scouts", []) or []), sort_keys=True)
            continue
        resolved = resolved_new.get(ticker, {})
        by_ticker[ticker] = {
            "ticker": ticker,
            "symbol": ticker,
            "cik": str(resolved.get("cik", "")).strip(),
            "company_title": str(resolved.get("company_title", "")).strip(),
            "cik_status": str(resolved.get("cik_status") or ("resolved" if resolved.get("cik") else "not_resolved")),
            "quarter": quarter,
            "master_universe_source": "daily_scout_append",
            "dealflow_source_stage": source_stage,
            "scouts_json": json.dumps(list(scout_meta.get("scouts", []) or []), sort_keys=True),
        }
        new_scouts.append(ticker)

    rows = [by_ticker[ticker] for ticker in sorted(by_ticker)]
    write_csv(output_csv, rows)
    summary = {
        "master_count": len(master_rows),
        "scout_count": len(scouts),
        "combined_count": len(rows),
        "new_scout_count": len(new_scouts),
        "new_scouts": new_scouts,
        "missing_cik_count": sum(1 for row in rows if not row.get("cik")),
    }
    summary_path = output_csv.parent / "universe_gate_summary.json"
    write_json_atomic(summary_path, summary)
    return UniverseBuildResult(rows=rows, summary=summary, artifacts={"universe_csv": str(output_csv), "universe_summary": str(summary_path)})


def validate_universe_gate(
    rows: list[dict[str, Any]],
    *,
    run_mode: RunMode,
    scout_count: int,
    min_broad_universe_count: int,
    artifacts: dict[str, str],
) -> GateResult:
    row_count = len(rows)
    missing_cik = sum(1 for row in rows if not str(row.get("cik", "")).strip())
    summary = {"row_count": row_count, "scout_count": scout_count, "missing_cik_count": missing_cik}
    if run_mode == RunMode.BROAD_MASTER_FINAL and (row_count < min_broad_universe_count or row_count <= scout_count):
        summary["reason"] = "broad_master_universe_too_small_or_scout_only"
        return GateResult(2, "Universe construction and drift control", GateStatus.HARD_STOP, summary, artifacts)
    if missing_cik:
        summary["reason"] = "missing_cik"
        return GateResult(2, "Universe construction and drift control", GateStatus.HARD_STOP, summary, artifacts)
    return GateResult(2, "Universe construction and drift control", GateStatus.PASS, summary, artifacts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_fundamental_daily_universe_gate.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/research/fundamental/src/daily_run/universe.py tests/test_fundamental_daily_universe_gate.py
git commit -m "feat: gate fundamental daily universe construction"
```

---

## Task 3: SEC coverage and fetch/materialization gate

**Files:**

- Create: `tradingagents/research/fundamental/src/daily_run/coverage.py`
- Test: `tests/test_fundamental_daily_coverage_gate.py`

- [ ] **Step 1: Write failing coverage classification tests**

```python
# tests/test_fundamental_daily_coverage_gate.py
from tradingagents.research.fundamental.src.daily_run.coverage import (
    classify_coverage_summary,
    normalize_coverage_summary,
    should_continue_fetch,
)
from tradingagents.research.fundamental.src.daily_run.models import GateStatus


def test_coverage_allows_pre_llm_when_exhibits_missing_but_companyfacts_ready():
    summary = classify_coverage_summary(
        ticker_count=1276,
        companyfacts_ready_count=1276,
        coverage_status_counts={"CACHED_READY": 76, "BLOCKED_METADATA_OR_ISSUER_REALITY": 1200},
        missing_input_counts={"earnings_exhibit_metadata": 1015, "8k_item_202_metadata": 185},
        fetch_queue_count=0,
        blocked_tickers=["NOK", "SILC", "TSEM"],
    )

    assert summary["pre_llm_blocked"] is False
    assert summary["llm_doc_ready_count"] == 76
    assert summary["remaining_work_type"] == "metadata_or_parser_routing"


def test_should_not_continue_fetch_when_queue_zero_even_if_metadata_missing():
    assert should_continue_fetch(fetch_queue_count=0, missing_input_counts={"earnings_exhibit_metadata": 1015}) is False


def test_coverage_hard_stops_when_companyfacts_missing_for_broad_universe():
    summary = classify_coverage_summary(
        ticker_count=1276,
        companyfacts_ready_count=100,
        coverage_status_counts={},
        missing_input_counts={"companyfacts": 1176},
        fetch_queue_count=0,
        blocked_tickers=[],
    )

    assert summary["gate_status"] == GateStatus.HARD_STOP.value
    assert summary["pre_llm_blocked"] is True


def test_normalize_coverage_summary_has_stable_contract():
    raw = {
        "ticker_count": 1276,
        "status_counts": {"CACHED_READY": 76},
        "missing_input_counts": {"earnings_exhibit_metadata": 1015},
        "fetch_queue_count": 0,
        "blocked_tickers": ["NOK"],
        "outputs": {"manifest_csv": "manifest.csv"},
    }

    summary = normalize_coverage_summary(raw, universe_count=1276, companyfacts_ready_count=1276)

    assert summary["ticker_count"] == 1276
    assert summary["companyfacts_ready_count"] == 1276
    assert summary["llm_doc_ready_count"] == 76
    assert summary["outputs"] == {"manifest_csv": "manifest.csv"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_fundamental_daily_coverage_gate.py -v
```

Expected: FAIL because `daily_run.coverage` does not exist.

- [ ] **Step 3: Implement coverage classification and fetch-loop wrappers**

```python
# tradingagents/research/fundamental/src/daily_run/coverage.py
from __future__ import annotations

import csv
import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from tradingagents.research.fundamental.src.ingest.documents import classify_doc_quality, html_to_text

from .artifacts import write_json_atomic
from .models import GateResult, GateStatus


def should_continue_fetch(*, fetch_queue_count: int, missing_input_counts: Mapping[str, int]) -> bool:
    if fetch_queue_count <= 0:
        return False
    return True


def classify_coverage_summary(
    *,
    ticker_count: int,
    companyfacts_ready_count: int,
    coverage_status_counts: Mapping[str, int],
    missing_input_counts: Mapping[str, int],
    fetch_queue_count: int,
    blocked_tickers: list[str],
) -> dict[str, Any]:
    pre_llm_blocked = companyfacts_ready_count < max(1, int(ticker_count * 0.90))
    llm_ready = int(coverage_status_counts.get("CACHED_READY", 0))
    remaining_work_type = "fetchable" if fetch_queue_count else "metadata_or_parser_routing"
    gate_status = GateStatus.HARD_STOP.value if pre_llm_blocked else GateStatus.PASS.value
    return {
        "ticker_count": ticker_count,
        "companyfacts_ready_count": companyfacts_ready_count,
        "llm_doc_ready_count": llm_ready,
        "coverage_status_counts": dict(coverage_status_counts),
        "missing_input_counts": dict(missing_input_counts),
        "fetch_queue_count": fetch_queue_count,
        "blocked_tickers": blocked_tickers,
        "pre_llm_blocked": pre_llm_blocked,
        "remaining_work_type": remaining_work_type,
        "gate_status": gate_status,
    }


def normalize_coverage_summary(raw: Mapping[str, Any], *, universe_count: int, companyfacts_ready_count: int) -> dict[str, Any]:
    summary = classify_coverage_summary(
        ticker_count=int(raw.get("ticker_count") or universe_count),
        companyfacts_ready_count=companyfacts_ready_count,
        coverage_status_counts=raw.get("status_counts", {}) or raw.get("coverage_status_counts", {}),
        missing_input_counts=raw.get("missing_input_counts", {}),
        fetch_queue_count=int(raw.get("fetch_queue_count", 0) or 0),
        blocked_tickers=list(raw.get("blocked_tickers", []) or []),
    )
    summary["outputs"] = dict(raw.get("outputs", {}) or {})
    return summary



def run_sec_coverage_manifest(
    *,
    out_root: Path,
    universe_csv: Path,
    eligible_json: Path,
    quarter: str,
    live_sec_root: Path,
) -> dict[str, Any]:
    from tradingagents.research.fundamental.src.sec_pipeline import cache_coverage_manifest as manifest

    out_root.mkdir(parents=True, exist_ok=True)
    target_eligible = out_root / "final_dealflow_tickers_sec_eligible.json"
    if eligible_json.resolve() != target_eligible.resolve():
        shutil.copy2(eligible_json, target_eligible)
    manifest.configure(out=out_root, live=live_sec_root)
    manifest.QUARTERS = [quarter]
    manifest.UNIVERSE_CSV = universe_csv
    manifest.TICKERS_JSON = target_eligible
    manifest.main()
    legacy_manifest = out_root / "sec_coverage_manifest_2021Q4_2026Q1.csv"
    quarter_manifest = out_root / f"sec_coverage_manifest_{quarter}.csv"
    if legacy_manifest.exists():
        shutil.copy2(legacy_manifest, quarter_manifest)
    summary_path = out_root / "sec_coverage_summary.json"
    return json.loads(summary_path.read_text(encoding="utf-8"))


def run_sec_fetch_once(*, out_root: Path, live_sec_root: Path) -> dict[str, Any]:
    from tradingagents.research.fundamental.src.sec_pipeline import cache_download_queue as download

    download.configure(out=out_root, live=live_sec_root)
    download.DOWNLOAD_MANIFEST_PATH = out_root / "sec_download_manifest_daily_run.json"
    download.main()
    return json.loads(download.DOWNLOAD_MANIFEST_PATH.read_text(encoding="utf-8"))


def coverage_gate_result(summary: Mapping[str, Any], *, artifact_paths: Mapping[str, str]) -> GateResult:
    status = GateStatus(summary.get("gate_status", GateStatus.PASS.value))
    return GateResult(3, "Filing and companyfacts coverage", status, dict(summary), dict(artifact_paths))


def _doc_path(live_sec_root: Path, ticker: str, accession: str, document: str) -> Path:
    return live_sec_root / "documents" / f"{ticker.upper()}_{accession.replace('-', '')}_{document}"


def load_raw_documents_from_coverage(manifest_csv: Path, live_sec_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not manifest_csv.exists():
        return rows
    with manifest_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            ticker = str(row.get("ticker", "")).upper()
            quarter = str(row.get("quarter", ""))
            docs = [
                ("primary_8k", row.get("earnings_8k_accession", ""), row.get("earnings_8k_primary_document", "")),
                ("earnings_exhibit", row.get("earnings_8k_accession", ""), row.get("earnings_exhibit_document", "")),
                ("periodic_10q_10k", row.get("periodic_accession", ""), row.get("periodic_primary_document", "")),
            ]
            for document_type, accession, document in docs:
                if not accession or not document:
                    continue
                path = _doc_path(live_sec_root, ticker, accession, document)
                if not path.exists():
                    continue
                raw = path.read_text(encoding="utf-8", errors="ignore")
                clean = html_to_text(raw)
                rows.append({
                    "ticker": ticker,
                    "quarter": quarter,
                    "accession": accession,
                    "document_type": document_type,
                    "document_name": document,
                    "cache_path": str(path),
                    "document_status": "cached_or_fetched",
                    "raw_text": raw,
                    "clean_text": clean,
                    **classify_doc_quality(document_type, clean),
                })
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_fundamental_daily_coverage_gate.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/research/fundamental/src/daily_run/coverage.py tests/test_fundamental_daily_coverage_gate.py
git commit -m "feat: add fundamental SEC coverage gate"
```

---

## Task 4: Pre-LLM scoring from cached companyfacts

**Files:**

- Create: `tradingagents/research/fundamental/src/daily_run/scoring_inputs.py`
- Test: `tests/test_fundamental_daily_scoring_inputs.py`

- [ ] **Step 1: Write failing pre-LLM tests**

```python
# tests/test_fundamental_daily_scoring_inputs.py
import json

from tradingagents.research.fundamental.src.daily_run.scoring_inputs import (
    build_pre_llm_from_companyfacts_cache,
    derive_tradable_date_from_coverage,
)


def _companyfacts_payload():
    return {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [{"end": "2026-03-31", "val": 1_000_000_000}]}},
                "NetIncomeLoss": {"units": {"USD": [{"end": "2026-03-31", "val": 120_000_000}]}},
                "Assets": {"units": {"USD": [{"end": "2026-03-31", "val": 800_000_000}]}},
                "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [{"end": "2026-03-31", "val": 150_000_000}]}},
                "NetCashProvidedByUsedInInvestingActivities": {"units": {"USD": [{"end": "2026-03-31", "val": -50_000_000}]}},
                "NetCashProvidedByUsedInFinancingActivities": {"units": {"USD": [{"end": "2026-03-31", "val": -10_000_000}]}},
            }
        }
    }


def test_build_pre_llm_from_companyfacts_does_not_require_earnings_exhibit(tmp_path):
    facts_root = tmp_path / "companyfacts"
    facts_root.mkdir()
    (facts_root / "CIK0000000001.json").write_text(json.dumps(_companyfacts_payload()))

    rows, summary = build_pre_llm_from_companyfacts_cache(
        universe_rows=[{"ticker": "AAA", "cik": "1", "quarter": "2026Q2"}],
        companyfacts_root=facts_root,
        quarter="2026Q2",
    )

    assert summary["companyfacts_cached"] == 1
    assert summary["pre_llm_scored"] == 1
    assert rows[0]["pre_llm_fundamental_bucket"] in {"strong", "good", "mixed", "weak"}
    assert rows[0]["revenue_bucket"] == "$1B-$2B"


def test_derive_tradable_date_uses_next_trading_day_after_latest_filing_date():
    row = {"earnings_8k_filing_date": "2026-05-08", "periodic_filing_date": "2026-05-08"}  # Friday
    assert derive_tradable_date_from_coverage(row) == "2026-05-11"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_fundamental_daily_scoring_inputs.py -v
```

Expected: FAIL for missing functions.

- [ ] **Step 3: Implement pre-LLM companyfacts builder and conservative trade-date derivation**

```python
# append to tradingagents/research/fundamental/src/daily_run/scoring_inputs.py
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from tradingagents.research.fundamental.src.features.pre_llm_scores import build_pre_llm_rows
from tradingagents.research.fundamental.src.ingest.xbrl import companyfacts_to_pre_llm_input


def _cik10(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return str(int(float(text))).zfill(10)
    except ValueError:
        return text.zfill(10)


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def _next_weekday(value: date) -> date:
    current = value + timedelta(days=1)
    while current.weekday() >= 5:
        current += timedelta(days=1)
    return current


def derive_tradable_date_from_coverage(row: dict[str, Any]) -> str:
    dates = [_parse_date(row.get("earnings_8k_filing_date")), _parse_date(row.get("periodic_filing_date"))]
    valid = [item for item in dates if item is not None]
    if not valid:
        return ""
    return _next_weekday(max(valid)).isoformat()


def build_pre_llm_from_companyfacts_cache(
    *,
    universe_rows: list[dict[str, Any]],
    companyfacts_root: Path,
    quarter: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    input_rows: list[dict[str, Any]] = []
    cached = 0
    for row in universe_rows:
        ticker = str(row.get("ticker", "")).upper()
        cik10 = _cik10(row.get("cik"))
        facts_path = companyfacts_root / f"CIK{cik10}.json" if cik10 else None
        facts_input: dict[str, Any] = {"ticker": ticker, "quarter": quarter}
        if facts_path and facts_path.exists():
            cached += 1
            facts_input.update(companyfacts_to_pre_llm_input(json.loads(facts_path.read_text(encoding="utf-8")), ticker=ticker, quarter=quarter))
        input_rows.append({**row, **facts_input, "quarter": quarter})
    scored = build_pre_llm_rows(input_rows)
    summary = {
        "universe_rows": len(universe_rows),
        "companyfacts_cached": cached,
        "pre_llm_scored": sum(1 for row in scored if row.get("pre_llm_fundamental_bucket") != "not_scored"),
        "pre_llm_not_scored": sum(1 for row in scored if row.get("pre_llm_fundamental_bucket") == "not_scored"),
    }
    return scored, summary
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_fundamental_daily_scoring_inputs.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/research/fundamental/src/daily_run/scoring_inputs.py tests/test_fundamental_daily_scoring_inputs.py
git commit -m "feat: build daily pre-LLM inputs from companyfacts"
```

---

## Task 5: Entry-open price coverage gate

**Files:**

- Modify: `tradingagents/research/fundamental/src/daily_run/scoring_inputs.py`
- Test: `tests/test_fundamental_daily_scoring_inputs.py`

- [ ] **Step 1: Add failing price attachment test**

Append to `tests/test_fundamental_daily_scoring_inputs.py`:

```python
def test_attach_entry_prices_quarantines_missing_price_rows():
    from tradingagents.research.fundamental.src.daily_run.scoring_inputs import attach_entry_prices

    rows = [
        {"ticker": "AAA", "quarter": "2026Q2", "tradable_date": "2026-05-11"},
        {"ticker": "BBB", "quarter": "2026Q2", "tradable_date": "2026-05-11"},
    ]

    def fake_price_provider(tickers, *, start, end):
        assert start == "2026-05-11"
        assert end == "2026-05-12"
        return [{"ticker": "AAA", "date": "2026-05-11", "open": 12.34, "close": 13.0}]

    priced, quarantine, summary = attach_entry_prices(rows, as_of="2026-05-12", price_provider=fake_price_provider)

    assert next(row for row in priced if row["ticker"] == "AAA")["entry_open"] == 12.34
    assert [row["ticker"] for row in quarantine] == ["BBB"]
    assert quarantine[0]["quarantine_reason"] == "missing_entry_open"
    assert summary["entry_open_ready"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_fundamental_daily_scoring_inputs.py::test_attach_entry_prices_quarantines_missing_price_rows -v
```

Expected: FAIL for missing `attach_entry_prices`.

- [ ] **Step 3: Implement `attach_entry_prices`**

```python
# append to tradingagents/research/fundamental/src/daily_run/scoring_inputs.py

def attach_entry_prices(
    rows: list[dict[str, Any]],
    *,
    as_of: str,
    price_provider: Callable[..., list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    needs = [row for row in rows if row.get("ticker") and row.get("tradable_date") and not row.get("entry_open")]
    tickers = sorted({str(row["ticker"]).upper() for row in needs})
    dates = [str(row["tradable_date"]) for row in needs]
    price_rows = price_provider(tickers, start=min(dates), end=as_of) if tickers and dates else []
    open_by_key = {
        (str(item.get("ticker", "")).upper(), str(item.get("date", ""))): item.get("open", "")
        for item in price_rows
    }
    output: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    for row in rows:
        out = dict(row)
        if out.get("tradable_date") and not out.get("entry_open"):
            value = open_by_key.get((str(out.get("ticker", "")).upper(), str(out.get("tradable_date", ""))))
            if value not in {None, ""}:
                out["entry_open"] = value
                out["entry_open_source"] = "price_provider_open"
        if not out.get("entry_open"):
            quarantine.append({"ticker": out.get("ticker", ""), "quarter": out.get("quarter", ""), "quarantine_reason": "missing_entry_open"})
        output.append(out)
    summary = {"rows": len(rows), "entry_open_ready": len(rows) - len(quarantine), "missing_entry_open": len(quarantine)}
    return output, quarantine, summary
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_fundamental_daily_scoring_inputs.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/research/fundamental/src/daily_run/scoring_inputs.py tests/test_fundamental_daily_scoring_inputs.py
git commit -m "feat: gate daily entry price coverage"
```

---

## Task 6: Tier 0-4 and LLM eligibility gate

**Files:**

- Create: `tradingagents/research/fundamental/src/daily_run/eligibility.py`
- Test: `tests/test_fundamental_daily_eligibility_gate.py`

- [ ] **Step 1: Write failing Tier/LLM eligibility tests**

```python
# tests/test_fundamental_daily_eligibility_gate.py
from tradingagents.research.fundamental.src.daily_run.eligibility import (
    assign_daily_tiers,
    build_llm_eligibility,
    build_tier_filtered_llm_packets,
)


def _row(ticker, entry_open, score=3, revenue_bucket="$500M-$1B"):
    return {
        "ticker": ticker,
        "quarter": "2026Q2",
        "entry_open": str(entry_open),
        "revenue_bucket": revenue_bucket,
        "pre_llm_fundamental_score": str(score),
        "pre_llm_fundamental_bucket": "good",
    }


def test_assign_daily_tiers_assigns_tier_zero_to_low_price_broad_candidate():
    rows, summary = assign_daily_tiers([_row("AAA", 20)])
    assert rows[0]["tier_0_bucket"]
    assert not rows[0]["tier_1_bucket"]
    assert summary["tier_0_count"] == 1


def test_llm_eligibility_excludes_tier_zero_and_requires_cached_ready():
    tiered, _ = assign_daily_tiers([_row("T0", 20), _row("T1", 12), _row("MISS", 8)])
    coverage = [
        {"ticker": "T0", "quarter": "2026Q2", "coverage_status": "CACHED_READY"},
        {"ticker": "T1", "quarter": "2026Q2", "coverage_status": "CACHED_READY"},
        {"ticker": "MISS", "quarter": "2026Q2", "coverage_status": "BLOCKED_METADATA_OR_ISSUER_REALITY"},
    ]

    eligible, quarantine, summary = build_llm_eligibility(tiered, coverage)

    assert [row["ticker"] for row in eligible] == ["T1"]
    assert {row["ticker"] for row in quarantine} == {"T0", "MISS"}
    assert summary["llm_eligible_count"] == 1


def test_build_tier_filtered_packets_never_builds_for_full_universe_or_tier_zero():
    candidates = [{"ticker": "T1", "quarter": "2026Q2", "tier_1_bucket": "Tier 1 - Balanced priority feed"}]
    docs = [{"ticker": "T1", "quarter": "2026Q2", "document_type": "earnings_exhibit", "clean_text": "Management raised guidance."}]
    packets, quarantine, summary = build_tier_filtered_llm_packets(candidates, docs, broad_universe_count=3)

    assert quarantine == []
    assert len(packets) == 1
    assert packets[0]["sample_id"] == "T1_2026Q2"
    assert packets[0]["evidence_snippets"]
    assert summary["packet_count"] == 1
    assert summary["eligible_count"] == 1
    assert summary["broad_universe_count"] == 3


def test_build_tier_filtered_packets_quarantines_empty_evidence():
    candidates = [{"ticker": "T1", "quarter": "2026Q2", "tier_1_bucket": "Tier 1 - Balanced priority feed"}]
    packets, quarantine, summary = build_tier_filtered_llm_packets(candidates, [], broad_universe_count=3)

    assert packets == []
    assert [row["ticker"] for row in quarantine] == ["T1"]
    assert quarantine[0]["llm_quarantine_reason"] == "empty_evidence_docs"
    assert summary["packet_count"] == 0
    assert summary["empty_evidence_count"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_fundamental_daily_eligibility_gate.py -v
```

Expected: FAIL because `daily_run.eligibility` does not exist.

- [ ] **Step 3: Implement Tier and LLM eligibility functions**

```python
# tradingagents/research/fundamental/src/daily_run/eligibility.py
from __future__ import annotations

from collections import Counter
from typing import Any

from tradingagents.research.fundamental.src.features.llm_packets import build_llm_packets
from tradingagents.research.fundamental.src.features.tiers import assign_tiers


def _key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("ticker", "")).upper(), str(row.get("quarter", ""))


def _has_tier_1_to_4(row: dict[str, Any]) -> bool:
    return any(str(row.get(col, "")).strip() for col in ["tier_1_bucket", "tier_2_bucket", "tier_3_bucket", "tier_4_bucket"])


def assign_daily_tiers(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    output: list[dict[str, Any]] = []
    counts = Counter()
    for row in rows:
        tiers = assign_tiers(row)
        merged = {**row, **tiers}
        for col in ["tier_0_bucket", "tier_1_bucket", "tier_2_bucket", "tier_3_bucket", "tier_4_bucket"]:
            if str(merged.get(col, "")).strip():
                counts[f"{col.replace('_bucket', '')}_count"] += 1
        output.append(merged)
    return output, dict(counts)


def build_llm_eligibility(
    tiered_rows: list[dict[str, Any]],
    coverage_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    coverage = {_key(row): row for row in coverage_rows}
    eligible: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    for row in tiered_rows:
        cov = coverage.get(_key(row), {})
        if not _has_tier_1_to_4(row):
            quarantine.append({**row, "llm_quarantine_reason": "tier0_or_not_tier_1_to_4"})
            continue
        if str(cov.get("coverage_status", "")).upper() != "CACHED_READY":
            quarantine.append({**row, **cov, "llm_quarantine_reason": "llm_evidence_missing"})
            continue
        eligible.append({**row, **cov, "llm_eligible": 1})
    summary = {"tiered_count": len(tiered_rows), "llm_eligible_count": len(eligible), "llm_quarantine_count": len(quarantine)}
    return eligible, quarantine, summary


def build_tier_filtered_llm_packets(
    eligible_rows: list[dict[str, Any]],
    raw_documents: list[dict[str, Any]],
    *,
    broad_universe_count: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    packets = build_llm_packets(eligible_rows, raw_documents)
    packet_by_sample = {packet["sample_id"]: packet for packet in packets}
    good_packets: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    for row in eligible_rows:
        sample_id = f"{str(row.get('ticker', '')).upper()}_{row.get('quarter', '')}"
        packet = packet_by_sample.get(sample_id)
        if not packet or not packet.get("evidence_snippets"):
            quarantine.append({**row, "llm_quarantine_reason": "empty_evidence_docs"})
            continue
        good_packets.append(packet)
    if good_packets and len(good_packets) >= broad_universe_count:
        raise ValueError("LLM packet count equals/exceeds broad universe count; refusing likely full-universe LLM run")
    summary = {
        "packet_count": len(good_packets),
        "eligible_count": len(eligible_rows),
        "empty_evidence_count": len(quarantine),
        "broad_universe_count": broad_universe_count,
    }
    return good_packets, quarantine, summary
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_fundamental_daily_eligibility_gate.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/research/fundamental/src/daily_run/eligibility.py tests/test_fundamental_daily_eligibility_gate.py
git commit -m "feat: gate LLM eligibility by Tier 1-4"
```

---

## Task 7: LLM output validation gate

**Files:**

- Create: `tradingagents/research/fundamental/src/daily_run/llm_validation.py`
- Test: `tests/test_fundamental_daily_llm_validation.py`

- [ ] **Step 1: Write failing LLM validation tests**

```python
# tests/test_fundamental_daily_llm_validation.py
import csv

from tradingagents.research.fundamental.src.daily_run.llm_validation import validate_post_llm_csv
from tradingagents.research.fundamental.src.daily_run.models import GateStatus


def _write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_validate_post_llm_csv_passes_one_row_per_packet(tmp_path):
    path = tmp_path / "post_llm_scores.csv"
    _write_csv(path, [{"sample_id": "AAA_2026Q2", "ticker": "AAA", "quarter": "2026Q2", "post_llm_candidate_flag": "1"}])

    result = validate_post_llm_csv(path, expected_sample_ids={"AAA_2026Q2"})

    assert result.status == GateStatus.PASS
    assert result.summary["completed_count"] == 1


def test_validate_post_llm_csv_hard_stops_on_missing_sample_id(tmp_path):
    path = tmp_path / "post_llm_scores.csv"
    _write_csv(path, [{"sample_id": "AAA_2026Q2", "ticker": "AAA", "quarter": "2026Q2"}])

    result = validate_post_llm_csv(path, expected_sample_ids={"AAA_2026Q2", "BBB_2026Q2"})

    assert result.status == GateStatus.HARD_STOP
    assert result.summary["missing_sample_ids"] == ["BBB_2026Q2"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_fundamental_daily_llm_validation.py -v
```

Expected: FAIL because `daily_run.llm_validation` does not exist.

- [ ] **Step 3: Implement post-LLM validation**

```python
# tradingagents/research/fundamental/src/daily_run/llm_validation.py
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .models import GateResult, GateStatus


def validate_post_llm_csv(path: Path, *, expected_sample_ids: set[str]) -> GateResult:
    if not path.exists() or path.stat().st_size == 0:
        return GateResult(8, "LLM packet, extraction, and validation", GateStatus.HARD_STOP, {"reason": "post_llm_missing_or_empty", "path": str(path)}, {})
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    seen = [str(row.get("sample_id") or f"{str(row.get('ticker', '')).upper()}_{row.get('quarter', '')}") for row in rows]
    duplicates = sorted({sample_id for sample_id in seen if seen.count(sample_id) > 1})
    missing = sorted(expected_sample_ids - set(seen))
    unexpected = sorted(set(seen) - expected_sample_ids)
    status = GateStatus.PASS if not duplicates and not missing and not unexpected else GateStatus.HARD_STOP
    return GateResult(
        8,
        "LLM packet, extraction, and validation",
        status,
        {
            "expected_count": len(expected_sample_ids),
            "completed_count": len(rows),
            "missing_sample_ids": missing,
            "duplicate_sample_ids": duplicates,
            "unexpected_sample_ids": unexpected,
        },
        {"post_llm_scores": str(path)},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_fundamental_daily_llm_validation.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/research/fundamental/src/daily_run/llm_validation.py tests/test_fundamental_daily_llm_validation.py
git commit -m "feat: validate daily post-LLM outputs"
```

---

## Task 8: Final scoring, HP/RM, and Top10 + Plus5 publish gate

**Files:**

- Create: `tradingagents/research/fundamental/src/daily_run/finalize.py`
- Test: `tests/test_fundamental_daily_finalize_gate.py`

- [ ] **Step 1: Write failing finalization tests**

```python
# tests/test_fundamental_daily_finalize_gate.py
from tradingagents.research.fundamental.src.daily_run.finalize import (
    build_final_scores,
    validate_broad_final_scores,
)
from tradingagents.research.fundamental.src.daily_run.models import GateStatus, RunMode


def _base(ticker, entry_open="12"):
    return {
        "ticker": ticker,
        "quarter": "2026Q2",
        "tradable_date": "2026-05-11",
        "entry_open": entry_open,
        "revenue_bucket": "$500M-$1B",
        "pre_llm_fundamental_score": "3",
        "pre_llm_fundamental_bucket": "good",
    }


def test_build_final_scores_preserves_broad_rows_when_post_llm_is_subset():
    broad = [_base("AAA"), _base("BBB", entry_open="20")]
    post_llm = [{"ticker": "AAA", "quarter": "2026Q2", "post_llm_candidate_flag": "1", "causal_change": "3", "negative_revision_risk": "1", "narrative_delta_bucket": "constructive", "operating_leverage_quality": "1", "durability": "1", "proof_alignment": "2"}]

    rows, summary = build_final_scores(broad, as_of="2026-05-12", post_llm_rows=post_llm)

    assert [row["ticker"] for row in rows] == ["AAA", "BBB"]
    assert summary["final_score_rows"] == 2
    assert "entry_score_0_100" in rows[0]
    assert "hp_structure_score" in rows[0]
    assert "rm_buy_review_flag" in rows[0]


def test_validate_broad_final_scores_hard_stops_on_unreconciled_row_loss():
    gate = validate_broad_final_scores(
        final_rows=[{"ticker": f"S{i}"} for i in range(162)],
        broad_universe_count=1276,
        explicit_invalid_quarantine_count=3,
        run_mode=RunMode.BROAD_MASTER_FINAL,
        artifacts={},
    )

    assert gate.status == GateStatus.HARD_STOP
    assert gate.summary["reason"] == "final_scores_plus_quarantine_do_not_reconcile_to_broad_universe"


def test_validate_broad_final_scores_passes_when_rows_plus_explicit_quarantine_reconcile():
    gate = validate_broad_final_scores(
        final_rows=[{"ticker": f"T{i}"} for i in range(4)],
        broad_universe_count=5,
        explicit_invalid_quarantine_count=1,
        run_mode=RunMode.BROAD_MASTER_FINAL,
        artifacts={},
    )

    assert gate.status == GateStatus.PASS
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_fundamental_daily_finalize_gate.py -v
```

Expected: FAIL because `daily_run.finalize` does not exist.

- [ ] **Step 3: Implement final scoring and broad final guard**

```python
# tradingagents/research/fundamental/src/daily_run/finalize.py
from __future__ import annotations

from pathlib import Path
from typing import Any

from tradingagents.research.fundamental.src.pipeline.run_on_new_filing import build_signal_tables
from tradingagents.research.fundamental.src.selection.high_conviction_top10 import (
    select_top15_core_deterioration_refill_shadow_from_csv,
    select_top15_from_csv,
)

from .artifacts import write_csv, write_json_atomic
from .models import GateResult, GateStatus, RunMode


def build_final_scores(
    broad_rows: list[dict[str, Any]],
    *,
    as_of: str,
    post_llm_rows: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    signal_rows, tier_rows, pre_rows = build_signal_tables(broad_rows, as_of=as_of, post_llm_rows=post_llm_rows or [])
    summary = {
        "broad_rows": len(broad_rows),
        "post_llm_rows": len(post_llm_rows or []),
        "final_score_rows": len(signal_rows),
        "tier_rows": len(tier_rows),
        "pre_rows": len(pre_rows),
    }
    return signal_rows, summary


def validate_broad_final_scores(
    *,
    final_rows: list[dict[str, Any]],
    broad_universe_count: int,
    explicit_invalid_quarantine_count: int,
    run_mode: RunMode,
    artifacts: dict[str, str],
) -> GateResult:
    reconciled_count = len(final_rows) + int(explicit_invalid_quarantine_count)
    summary = {
        "final_score_rows": len(final_rows),
        "explicit_invalid_quarantine_count": int(explicit_invalid_quarantine_count),
        "reconciled_count": reconciled_count,
        "broad_universe_count": broad_universe_count,
    }
    if run_mode == RunMode.BROAD_MASTER_FINAL and reconciled_count != broad_universe_count:
        summary["reason"] = "final_scores_plus_quarantine_do_not_reconcile_to_broad_universe"
        return GateResult(9, "Final scoring, HP buckets, and RM buckets", GateStatus.HARD_STOP, summary, artifacts)
    return GateResult(9, "Final scoring, HP buckets, and RM buckets", GateStatus.PASS, summary, artifacts)


def write_final_scores_csv(path: Path, rows: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, str]:
    write_csv(path, rows)
    summary_path = path.with_name(path.stem + "_summary.json")
    write_json_atomic(summary_path, summary)
    return {"final_scores_csv": str(path), "final_scores_summary": str(summary_path)}


def publish_top15_and_shadow(
    *,
    scores_csv: Path,
    output_root: Path,
    as_of: str,
    broad_universe_count: int,
    coverage_manifest: Path | None = None,
) -> GateResult:
    import pandas as pd

    frame = pd.read_csv(scores_csv).fillna("")
    summary = {"input_rows": int(len(frame)), "broad_universe_count": broad_universe_count}
    if len(frame) != broad_universe_count:
        summary["reason"] = "top15_input_not_broad_final_scores"
        return GateResult(10, "Top10 + Plus5 + shadow refill publish", GateStatus.HARD_STOP, summary, {"scores_csv": str(scores_csv)})
    top15 = select_top15_from_csv(scores_csv, output_root, {"selection_date": as_of, "enabled": True, "core_n": 10, "exception_slots": 5}, coverage_manifest)
    shadow = select_top15_core_deterioration_refill_shadow_from_csv(
        scores_csv,
        output_root,
        {"selection_date": as_of, "enabled": True, "core_n": 10, "exception_slots": 5, "core_deterioration_refill": {"enabled": True, "mode": "strict"}},
        coverage_manifest,
    )
    artifacts = {"scores_csv": str(scores_csv), **{f"top15_{k}": str(v) for k, v in top15.get("output_paths", {}).items()}, **{f"shadow_{k}": str(v) for k, v in shadow.get("output_paths", {}).items()}}
    summary.update({"top15_selected_count": len(top15.get("selected_rows", [])), "shadow_selected_count": len(shadow.get("selected_rows", []))})
    return GateResult(10, "Top10 + Plus5 + shadow refill publish", GateStatus.PASS, summary, artifacts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_fundamental_daily_finalize_gate.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/research/fundamental/src/daily_run/finalize.py tests/test_fundamental_daily_finalize_gate.py
git commit -m "feat: gate broad final scores and Top15 publish"
```

---

## Task 9: Daily orchestrator runner with 10 gate artifacts

**Files:**

- Create: `tradingagents/research/fundamental/src/daily_run/orchestrator.py`
- Test: `tests/test_fundamental_daily_orchestrator_contract.py`

- [ ] **Step 1: Write failing orchestrator contract tests**

```python
# tests/test_fundamental_daily_orchestrator_contract.py
import json
from pathlib import Path

from tradingagents.research.fundamental.src.daily_run.models import DailyRunConfig, GateStatus
from tradingagents.research.fundamental.src.daily_run.orchestrator import run_daily_fundamental


def _write_master(path, count=5):
    path.write_text(json.dumps({"items": [{"symbol": f"T{i}", "cik": str(i + 1), "company_title": f"T{i} Inc"} for i in range(count)]}))


def _write_handoff(path):
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"tickers": ["T1"], "metadata_by_ticker": {}, "source_stage": "daily_scout"}))


def test_orchestrator_diagnostic_writes_manifest_and_stops_before_publish_when_skip_llm(tmp_path, monkeypatch):
    master = tmp_path / "master.json"
    handoff = tmp_path / "handoff.json"
    _write_master(master)
    _write_handoff(handoff)

    cfg = DailyRunConfig(
        as_of="2026-05-12",
        quarter="2026Q2",
        mode="diagnostic-only",
        output_root=tmp_path / "run",
        master_universe_path=master,
        handoff_path=handoff,
        skip_fetch=True,
        skip_llm=True,
        min_broad_universe_count=3,
    )

    result = run_daily_fundamental(cfg)

    assert (cfg.output_root / "run_manifest.json").exists()
    assert result.summary["final"] is False
    assert any(gate.gate_number == 1 for gate in result.gates)


def test_orchestrator_broad_final_hard_stops_on_scout_only_universe(tmp_path):
    master = tmp_path / "master.json"
    handoff = tmp_path / "handoff.json"
    _write_master(master, count=2)
    _write_handoff(handoff)

    cfg = DailyRunConfig(
        as_of="2026-05-12",
        quarter="2026Q2",
        mode="broad-master-final",
        output_root=tmp_path / "run",
        master_universe_path=master,
        handoff_path=handoff,
        skip_fetch=True,
        skip_llm=True,
        min_broad_universe_count=1000,
    )

    result = run_daily_fundamental(cfg)

    assert result.summary["final"] is False
    assert result.gates[-1].status == GateStatus.HARD_STOP
    assert not (cfg.output_root / "high_conviction_top15.csv").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_fundamental_daily_orchestrator_contract.py -v
```

Expected: FAIL because `daily_run.orchestrator` does not exist.

- [ ] **Step 3: Implement orchestrator skeleton with honest stop behavior**

```python
# tradingagents/research/fundamental/src/daily_run/orchestrator.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from tradingagents.research.fundamental.src.config.cache_paths import sec_cache_root
from tradingagents.research.fundamental.src.storage import source_file_hash

from .artifacts import write_json_atomic
from .models import DailyRunConfig, DailyRunState, GateResult, GateStatus, RunMode, StopGateError
from .universe import build_combined_universe, validate_universe_gate


@dataclass
class DailyRunResult:
    gates: list[GateResult]
    summary: dict[str, Any]
    artifacts: dict[str, str]


def _record(state: DailyRunState, result: GateResult) -> None:
    state.record(result)
    write_json_atomic(state.config.output_root / "gates" / f"gate_{result.gate_number:02d}.json", {
        "gate_number": result.gate_number,
        "gate_name": result.gate_name,
        "status": result.status.value,
        "summary": result.summary,
        "artifacts": result.artifacts,
    })
    result.raise_if_hard_stop()


def _finish(state: DailyRunState, *, final: bool, stopped: str = "") -> DailyRunResult:
    summary = {
        "run_id": state.run_id,
        "as_of": state.config.as_of,
        "quarter": state.config.quarter,
        "mode": state.config.run_mode.value,
        "final": final,
        "stopped": stopped,
        "gate_statuses": [{"gate": gate.gate_number, "name": gate.gate_name, "status": gate.status.value} for gate in state.gates],
        "artifacts": state.artifacts,
    }
    write_json_atomic(state.config.output_root / "run_manifest.json", summary)
    return DailyRunResult(gates=state.gates, summary=summary, artifacts=state.artifacts)


def run_daily_fundamental(config: DailyRunConfig) -> DailyRunResult:
    config.output_root.mkdir(parents=True, exist_ok=True)
    state = DailyRunState(config=config, run_id=f"daily_{uuid4().hex[:12]}")
    try:
        # Gate 1 - run identity / snapshot
        manifest = {
            "run_id": state.run_id,
            "as_of": config.as_of,
            "quarter": config.quarter,
            "mode": config.run_mode.value,
            "source_hashes": {
                "master_universe": source_file_hash(config.master_universe_path),
                "handoff": source_file_hash(config.handoff_path),
            },
        }
        manifest_path = config.output_root / "run_identity.json"
        write_json_atomic(manifest_path, manifest)
        _record(state, GateResult(1, "Run identity and immutable snapshot", GateStatus.PASS, manifest, {"run_identity": str(manifest_path)}))

        # Gate 2 - universe. Later tasks extend this skeleton through Gate 10.
        if config.master_universe_path is None:
            _record(state, GateResult(2, "Universe construction and drift control", GateStatus.HARD_STOP, {"reason": "missing_master_universe_path"}, {}))
        universe_csv = config.output_root / f"master_fundamental_universe_{config.quarter}.csv"
        universe = build_combined_universe(
            master_universe_path=config.master_universe_path,
            handoff_path=config.handoff_path,
            quarter=config.quarter,
            output_csv=universe_csv,
        )
        scout_count = int(universe.summary.get("scout_count", 0))
        _record(state, validate_universe_gate(
            universe.rows,
            run_mode=config.run_mode,
            scout_count=scout_count,
            min_broad_universe_count=config.min_broad_universe_count,
            artifacts=universe.artifacts,
        ))

        # Until Gate 3-10 wiring is implemented, diagnostic-only and skip_llm runs stop honestly.
        _record(state, GateResult(3, "Filing and companyfacts coverage", GateStatus.SKIPPED, {"reason": "not_yet_wired_in_task_10"}, {}))
        return _finish(state, final=False, stopped="diagnostic_skeleton_complete")
    except StopGateError as exc:
        return _finish(state, final=False, stopped=str(exc))
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_fundamental_daily_orchestrator_contract.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/research/fundamental/src/daily_run/orchestrator.py tests/test_fundamental_daily_orchestrator_contract.py
git commit -m "feat: add gated daily fundamental orchestrator skeleton"
```

---

## Task 10: Wire Gates 3-10 into the orchestrator

**Files:**

- Modify: `tradingagents/research/fundamental/src/daily_run/orchestrator.py`
- Modify: `tradingagents/research/fundamental/src/daily_run/coverage.py`
- Modify: `tradingagents/research/fundamental/src/daily_run/scoring_inputs.py`
- Modify: `tradingagents/research/fundamental/src/daily_run/eligibility.py`
- Modify: `tradingagents/research/fundamental/src/daily_run/finalize.py`
- Test: `tests/test_fundamental_daily_orchestrator_contract.py`

- [ ] **Step 1: Add integration test with fake services**

Append to `tests/test_fundamental_daily_orchestrator_contract.py` before implementation. It imports `DailyRunServices` before it exists, so it fails red first.

```python
def _companyfacts_payload():
    return {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [{"end": "2026-03-31", "val": 1_000_000_000}]}},
        "NetIncomeLoss": {"units": {"USD": [{"end": "2026-03-31", "val": 120_000_000}]}},
        "Assets": {"units": {"USD": [{"end": "2026-03-31", "val": 800_000_000}]}},
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [{"end": "2026-03-31", "val": 150_000_000}]}},
        "NetCashProvidedByUsedInInvestingActivities": {"units": {"USD": [{"end": "2026-03-31", "val": -50_000_000}]}},
        "NetCashProvidedByUsedInFinancingActivities": {"units": {"USD": [{"end": "2026-03-31", "val": -10_000_000}]}},
    }}}


def test_orchestrator_final_mode_preserves_broad_rows_and_filters_llm(tmp_path):
    import csv
    import json
    import pandas as pd

    from tradingagents.research.fundamental.src.daily_run.models import GateResult, GateStatus
    from tradingagents.research.fundamental.src.daily_run.orchestrator import DailyRunServices

    master = tmp_path / "master.json"
    master.write_text(json.dumps({
        "items": [{"symbol": f"T{i}", "cik": str(i + 1), "company_title": f"T{i} Inc"} for i in range(5)]
    }))
    live = tmp_path / "live_sec"
    (live / "companyfacts").mkdir(parents=True)
    for i in range(5):
        (live / "companyfacts" / f"CIK{str(i + 1).zfill(10)}.json").write_text(json.dumps(_companyfacts_payload()))

    def fake_coverage(*, out_root, universe_csv, eligible_json, quarter, live_sec_root):
        manifest = out_root / f"sec_coverage_manifest_{quarter}.csv"
        rows = []
        for ticker in ["T0", "T1", "T2", "T3", "T4"]:
            status = "CACHED_READY" if ticker in {"T1", "T2"} else "BLOCKED_METADATA_OR_ISSUER_REALITY"
            rows.append({
                "ticker": ticker, "quarter": quarter, "coverage_status": status, "missing_inputs": "" if status == "CACHED_READY" else "earnings_exhibit_metadata",
                "earnings_8k_accession": f"00000000-{ticker}", "earnings_8k_filing_date": "2026-05-08", "earnings_8k_primary_document": "8k.htm", "earnings_exhibit_document": "ex99.htm",
                "periodic_accession": f"00000000-{ticker}Q", "periodic_form": "10-Q", "periodic_filing_date": "2026-05-08", "periodic_primary_document": "10q.htm",
            })
        with manifest.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
        for ticker in ["T1", "T2"]:
            for accession, doc in [(f"00000000-{ticker}", "8k.htm"), (f"00000000-{ticker}", "ex99.htm"), (f"00000000-{ticker}Q", "10q.htm")]:
                path = live / "documents" / f"{ticker}_{accession.replace('-', '')}_{doc}"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("<html>Management raised guidance and margins improved.</html>")
        return {"ticker_count": 5, "status_counts": {"CACHED_READY": 2, "BLOCKED_METADATA_OR_ISSUER_REALITY": 3}, "missing_input_counts": {"earnings_exhibit_metadata": 3}, "fetch_queue_count": 0, "blocked_tickers": [], "outputs": {"manifest_csv": str(manifest)}}

    def fake_prices(tickers, *, start, end):
        opens = {"T0": 20, "T1": 12, "T2": 8, "T3": 7, "T4": 30}
        return [{"ticker": ticker, "date": "2026-05-11", "open": opens[ticker], "close": opens[ticker]} for ticker in tickers]

    def fake_llm(*, packets_path, output_root, config):
        packets = [json.loads(line) for line in packets_path.read_text().splitlines() if line.strip()]
        assert [packet["ticker"] for packet in packets] == ["T1", "T2"]
        out = output_root / "post_llm_scores.csv"
        rows = [{"sample_id": packet["sample_id"], "ticker": packet["ticker"], "quarter": packet["quarter"], "post_llm_candidate_flag": "1", "post_llm_high_priority_flag": "1", "post_llm_demote_flag": "0", "causal_change": "3", "negative_revision_risk": "1", "narrative_delta_bucket": "constructive", "operating_leverage_quality": "1", "durability": "1", "proof_alignment": "2"} for packet in packets]
        with out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
        return out

    def fake_publish(*, scores_csv, output_root, as_of, broad_universe_count, coverage_manifest):
        assert len(pd.read_csv(scores_csv)) == broad_universe_count == 5
        return GateResult(10, "Top10 + Plus5 + shadow refill publish", GateStatus.PASS, {"input_rows": 5}, {"scores_csv": str(scores_csv)})

    cfg = DailyRunConfig(as_of="2026-05-12", quarter="2026Q2", mode="broad-master-final", output_root=tmp_path / "run", master_universe_path=master, handoff_path=None, sec_live_root=live, min_broad_universe_count=5)
    result = run_daily_fundamental(cfg, services=DailyRunServices(price_provider=fake_prices, run_coverage=fake_coverage, run_llm=fake_llm, publish=fake_publish))

    assert result.summary["final"] is True
    assert (cfg.output_root / "fundamental_final_scores_2026-05-12.csv").exists()
    assert (cfg.output_root / "lake" / "artifacts" / "2026Q2_llm_packets.jsonl").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_fundamental_daily_orchestrator_contract.py::test_orchestrator_final_mode_preserves_broad_rows_and_filters_llm -v
```

Expected: FAIL until services are injected.

- [ ] **Step 3: Add `DailyRunServices` to make live dependencies testable**

```python
# add to daily_run/orchestrator.py
from dataclasses import dataclass
from typing import Callable

from tradingagents.research.fundamental.src.ingest.prices import fetch_yahoo_ohlcv


@dataclass
class DailyRunServices:
    price_provider: Callable[..., list[dict[str, Any]]] = fetch_yahoo_ohlcv
    run_coverage: Callable[..., dict[str, Any]] | None = None
    run_fetch_once: Callable[..., dict[str, Any]] | None = None
    run_llm: Callable[..., Path | None] | None = None
    publish: Callable[..., GateResult] | None = None
```

Change signature:

```python
def run_daily_fundamental(config: DailyRunConfig, services: DailyRunServices | None = None) -> DailyRunResult:
    services = services or DailyRunServices()
```

- [ ] **Step 4: Wire Gate 3 coverage**

Inside `run_daily_fundamental` after Gate 2:

```python
from .coverage import coverage_gate_result, normalize_coverage_summary, run_sec_coverage_manifest, run_sec_fetch_once

live_root = config.sec_live_root or sec_cache_root("live_sec")
coverage_runner = services.run_coverage or run_sec_coverage_manifest
coverage_summary_raw = coverage_runner(
    out_root=config.output_root,
    universe_csv=universe_csv,
    eligible_json=config.master_universe_path,
    quarter=config.quarter,
    live_sec_root=live_root,
)
companyfacts_ready = len(universe.rows) - int((coverage_summary_raw.get("missing_input_counts", {}) or {}).get("companyfacts", 0))
coverage_summary = normalize_coverage_summary(
    coverage_summary_raw,
    universe_count=len(universe.rows),
    companyfacts_ready_count=companyfacts_ready,
)
_record(state, coverage_gate_result(coverage_summary, artifact_paths=coverage_summary.get("outputs", {})))
```

- [ ] **Step 5: Wire Gate 4 fetch loop**

Add after coverage gate:

```python
if not config.skip_fetch and coverage_summary["fetch_queue_count"]:
    fetcher = services.run_fetch_once or run_sec_fetch_once
    before = coverage_summary["fetch_queue_count"]
    fetch_manifest = fetcher(out_root=config.output_root, live_sec_root=live_root)
    _record(state, GateResult(4, "Fetch and materialization", GateStatus.PASS, {"initial_fetch_queue_count": before, "fetch_manifest": fetch_manifest}, {}))
else:
    _record(state, GateResult(4, "Fetch and materialization", GateStatus.PASS, {"fetch_queue_count": coverage_summary["fetch_queue_count"], "reason": "no_fetchable_queue_or_skip_fetch"}, {}))
```

- [ ] **Step 6: Wire Gate 5 pre-LLM rows**

```python
from .artifacts import write_csv
from .scoring_inputs import build_pre_llm_from_companyfacts_cache

pre_rows, pre_summary = build_pre_llm_from_companyfacts_cache(
    universe_rows=universe.rows,
    companyfacts_root=live_root / "companyfacts",
    quarter=config.quarter,
)
pre_path = config.output_root / "pre_llm_scores.csv"
write_csv(pre_path, pre_rows)
_record(state, GateResult(5, "Pre-LLM scoring readiness", GateStatus.PASS, pre_summary, {"pre_llm_scores": str(pre_path)}))
```

- [ ] **Step 7: Wire Gate 6 trade dates and entry prices**

Load coverage CSV, add tradable dates by ticker, call `attach_entry_prices`, write quarantine:

```python
import csv
from .scoring_inputs import attach_entry_prices, derive_tradable_date_from_coverage

coverage_csv = Path(coverage_summary_raw.get("outputs", {}).get("manifest_csv", config.output_root / f"sec_coverage_manifest_{config.quarter}.csv"))
coverage_rows = list(csv.DictReader(coverage_csv.open(newline="", encoding="utf-8"))) if coverage_csv.exists() else []
coverage_by_key = {(row["ticker"].upper(), row["quarter"]): row for row in coverage_rows}
pre_with_dates = []
for row in pre_rows:
    cov = coverage_by_key.get((row["ticker"].upper(), row["quarter"]), {})
    pre_with_dates.append({**row, **cov, "tradable_date": row.get("tradable_date") or derive_tradable_date_from_coverage(cov)})
priced_rows, price_quarantine, price_summary = attach_entry_prices(pre_with_dates, as_of=config.as_of, price_provider=services.price_provider)
price_ready_rows = [row for row in priced_rows if row.get("entry_open")]
write_csv(config.output_root / "entry_price_quarantine.csv", price_quarantine)
price_gate_status = GateStatus.HARD_STOP if config.run_mode == RunMode.BROAD_MASTER_FINAL and price_quarantine else GateStatus.PASS
_record(state, GateResult(
    6,
    "Trade date, price, and entry-open",
    price_gate_status,
    {**price_summary, "tier_input_rows": len(price_ready_rows), "reason": "missing_entry_open" if price_quarantine else ""},
    {"entry_price_quarantine": str(config.output_root / "entry_price_quarantine.csv")},
))
```

- [ ] **Step 8: Wire Gate 7 Tier/LLM eligibility**

```python
from .eligibility import assign_daily_tiers, build_llm_eligibility

tiered_rows, tier_summary = assign_daily_tiers(price_ready_rows)
eligible_rows, llm_quarantine, eligibility_summary = build_llm_eligibility(tiered_rows, coverage_rows)
write_csv(config.output_root / "tier_classification.csv", tiered_rows)
write_csv(config.output_root / "llm_eligibility.csv", eligible_rows)
write_csv(config.output_root / "llm_quarantine.csv", llm_quarantine)
_record(state, GateResult(7, "Tier 0-4 and LLM eligibility", GateStatus.PASS, {**tier_summary, **eligibility_summary}, {"tier_classification": str(config.output_root / "tier_classification.csv"), "llm_eligibility": str(config.output_root / "llm_eligibility.csv")}))
```

- [ ] **Step 9: Wire Gate 8 packets and optional LLM validation**

```python
import json
from .artifacts import write_text_atomic
from .coverage import load_raw_documents_from_coverage
from .eligibility import build_tier_filtered_llm_packets
from .llm_validation import validate_post_llm_csv

raw_docs = load_raw_documents_from_coverage(coverage_csv, live_root)
packets, empty_evidence_quarantine, packet_summary = build_tier_filtered_llm_packets(eligible_rows, raw_docs, broad_universe_count=len(universe.rows))
packet_path = config.output_root / "lake" / "artifacts" / f"{config.quarter}_llm_packets.jsonl"
write_text_atomic(packet_path, "\n".join(json.dumps(packet, sort_keys=True) for packet in packets))
write_csv(config.output_root / "llm_empty_evidence_quarantine.csv", empty_evidence_quarantine)
post_llm_path = None
if packet_summary["packet_count"] != packet_summary["eligible_count"] - packet_summary["empty_evidence_count"]:
    _record(state, GateResult(8, "LLM packet, extraction, and validation", GateStatus.HARD_STOP, {**packet_summary, "reason": "packet_count_mismatch"}, {"llm_packets": str(packet_path)}))
if config.skip_llm or config.run_mode == RunMode.DIAGNOSTIC_ONLY:
    _record(state, GateResult(8, "LLM packet, extraction, and validation", GateStatus.SKIPPED, {**packet_summary, "reason": "skip_llm_or_diagnostic"}, {"llm_packets": str(packet_path), "llm_empty_evidence_quarantine": str(config.output_root / "llm_empty_evidence_quarantine.csv")}))
else:
    post_llm_path = services.run_llm(packets_path=packet_path, output_root=config.output_root, config=config) if services.run_llm else None
    if post_llm_path is None:
        _record(state, GateResult(8, "LLM packet, extraction, and validation", GateStatus.HARD_STOP, {"reason": "llm_runner_not_configured"}, {"llm_packets": str(packet_path)}))
    validation = validate_post_llm_csv(post_llm_path, expected_sample_ids={packet["sample_id"] for packet in packets})
    _record(state, validation)
```

- [ ] **Step 10: Wire Gate 9 final scores**

```python
from tradingagents.research.fundamental.src.storage import read_rows
from .finalize import build_final_scores, validate_broad_final_scores, write_final_scores_csv

post_rows = read_rows(post_llm_path) if (not config.skip_llm and post_llm_path) else []
final_rows, final_summary = build_final_scores(tiered_rows, as_of=config.as_of, post_llm_rows=post_rows)
final_path = config.output_root / f"fundamental_final_scores_{config.as_of}.csv"
artifacts = write_final_scores_csv(final_path, final_rows, final_summary)
# Count rows intentionally excluded before final scoring. Gate 6 hard-stops final mode on price quarantine,
# but this still makes reconciliation exact for diagnostic/scout modes and future invalid-issuer quarantine.
explicit_invalid_quarantine_count = len(price_quarantine)
_record(state, validate_broad_final_scores(
    final_rows=final_rows,
    broad_universe_count=len(universe.rows),
    explicit_invalid_quarantine_count=explicit_invalid_quarantine_count,
    run_mode=config.run_mode,
    artifacts=artifacts,
))
```

- [ ] **Step 11: Wire Gate 10 publish only when final mode and LLM complete**

```python
from .finalize import publish_top15_and_shadow

if config.run_mode == RunMode.BROAD_MASTER_FINAL and not config.skip_llm:
    publish_gate = (services.publish or publish_top15_and_shadow)(
        scores_csv=final_path,
        output_root=config.output_root,
        as_of=config.as_of,
        broad_universe_count=len(universe.rows),
        coverage_manifest=coverage_csv if coverage_csv.exists() else None,
    )
    _record(state, publish_gate)
    return _finish(state, final=True)
_record(state, GateResult(10, "Top10 + Plus5 + shadow refill publish", GateStatus.SKIPPED, {"reason": "not_broad_final_or_skip_llm"}, {}))
return _finish(state, final=False, stopped="publish_skipped")
```

- [ ] **Step 12: Complete the fake-service integration test**

Use the concrete fake-service test from Step 1. Required assertions:

```python
assert result.summary["final"] is True
assert result.gates[-1].gate_number == 10
assert result.gates[-1].status == GateStatus.PASS
assert (cfg.output_root / "master_fundamental_universe_2026Q2.csv").exists()
assert (cfg.output_root / "pre_llm_scores.csv").exists()
assert (cfg.output_root / "tier_classification.csv").exists()
assert (cfg.output_root / "lake" / "artifacts" / "2026Q2_llm_packets.jsonl").exists()
```

The fake `services.run_llm` must write a valid `post_llm_scores.csv`. The fake `services.publish` must read `scores_csv` and assert row count equals broad count before returning Gate 10 PASS.

Also add this regression test for the diagnostic/no-LLM edge case. To keep it DRY, first extract the fake setup in Step 1 into `_fake_orchestrator_fixture(tmp_path, mode, skip_llm, fake_llm=None) -> tuple[DailyRunConfig, DailyRunServices]`; the helper must create the master JSON, companyfacts cache, fake coverage manifest/docs, fake price provider, and fake publish callback used by the full fake-service test.

```python
def test_orchestrator_diagnostic_mode_with_skip_llm_false_does_not_require_post_llm_path(tmp_path):
    def fail_if_called(**kwargs):
        raise AssertionError("diagnostic mode must not call LLM")

    cfg, services = _fake_orchestrator_fixture(
        tmp_path,
        mode="diagnostic-only",
        skip_llm=False,
        fake_llm=fail_if_called,
    )

    result = run_daily_fundamental(cfg, services=services)

    assert result.summary["final"] is False
    assert result.summary["stopped"] == "publish_skipped"
    assert any(gate.gate_number == 8 and gate.status == GateStatus.SKIPPED for gate in result.gates)
    assert not (cfg.output_root / "high_conviction_top15.csv").exists()
```

- [ ] **Step 13: Run orchestrator contract tests**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_fundamental_daily_orchestrator_contract.py -v
```

Expected: PASS.

- [ ] **Step 14: Commit**

```bash
git add tradingagents/research/fundamental/src/daily_run tests/test_fundamental_daily_orchestrator_contract.py
git commit -m "feat: wire fundamental daily run gates"
```

---

## Task 11: CLI command `fundamental-run-today`

**Files:**

- Modify: `tradingagents/research/fundamental/src/cli/commands.py`
- Test: `tests/test_cli_fundamental_run_today.py`

- [ ] **Step 1: Write failing CLI tests**

```python
# tests/test_cli_fundamental_run_today.py
import json

from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


def test_fundamental_run_today_help_exposes_gate_options():
    result = runner.invoke(app, ["fundamental-run-today", "--help"])

    assert result.exit_code == 0
    assert "--mode" in result.output
    assert "--master-universe" in result.output
    assert "--skip-llm" in result.output


def test_fundamental_run_today_rejects_missing_mode(tmp_path):
    result = runner.invoke(app, ["fundamental-run-today", "--mode", "", "--output-root", str(tmp_path)])

    assert result.exit_code != 0
    assert "mode" in result.output.lower()


def test_fundamental_run_today_diagnostic_writes_manifest(tmp_path):
    master = tmp_path / "master.json"
    master.write_text(json.dumps({"items": [{"symbol": "AAA", "cik": "1", "company_title": "AAA Inc"}]}))
    out = tmp_path / "run"

    result = runner.invoke(app, [
        "fundamental-run-today",
        "--mode", "diagnostic-only",
        "--date", "2026-05-12",
        "--quarter", "2026Q2",
        "--master-universe", str(master),
        "--output-root", str(out),
        "--skip-fetch",
        "--skip-llm",
        "--min-broad-universe-count", "1",
        "--format", "json",
    ])

    assert result.exit_code == 0, result.output
    assert (out / "run_manifest.json").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_cli_fundamental_run_today.py -v
```

Expected: FAIL because command does not exist.

- [ ] **Step 3: Add CLI command without breaking existing `fundamental`**

Append in `tradingagents/research/fundamental/src/cli/commands.py` after existing `fundamental` command:

```python
@app.command("fundamental-run-today")
def fundamental_run_today(
    date: str = typer.Option("", "--date", help="Run date YYYY-MM-DD; defaults to today"),
    quarter: str = typer.Option("", "--quarter", help="Fundamental quarter, e.g. 2026Q2; defaults from date"),
    mode: str = typer.Option(..., "--mode", help="Run mode: broad-master-final|scout-smoke|diagnostic-only"),
    master_universe: str = typer.Option("", "--master-universe", help="Broad master universe JSON path"),
    handoff: str = typer.Option("", "--handoff", help="Daily scout handoff JSON path"),
    output_root: str = typer.Option("", "--output-root", help="Output root; defaults to eval_results/fundamental/<date>_<quarter>_daily"),
    sec_live_root: str = typer.Option("", "--sec-live-root", help="SEC live cache root"),
    skip_fetch: bool = typer.Option(False, "--skip-fetch", help="Skip SEC fetch/materialization"),
    skip_llm: bool = typer.Option(False, "--skip-llm", help="Build packets but skip LLM/publish final"),
    llm_mode: str = typer.Option("subagent", "--llm-mode", help="LLM mode for orchestrator: subagent|external|post-file"),
    min_broad_universe_count: int = typer.Option(1000, "--min-broad-universe-count", help="Minimum broad universe count in final mode"),
    format: str = typer.Option("table", "--format", help="Output format: table|json"),
):
    """Run the gated daily fundamental framework from broad master universe."""
    from tradingagents.research.fundamental.src.daily_run.models import DailyRunConfig
    from tradingagents.research.fundamental.src.daily_run.orchestrator import run_daily_fundamental
    from tradingagents.research.fundamental.src.pipeline.dealflow_adapter import current_quarter

    run_date = date.strip() or _dt.date.today().isoformat()
    run_quarter = quarter.strip() or current_quarter(_dt.date.fromisoformat(run_date))
    out = Path(output_root.strip()) if output_root.strip() else Path("eval_results") / "fundamental" / f"{run_date}_{run_quarter}_daily"
    master_path = Path(master_universe.strip()) if master_universe.strip() else out / "final_dealflow_tickers_sec_eligible.json"
    handoff_path = Path(handoff.strip()) if handoff.strip() else Path("eval_results") / "deal_flow" / run_date / "final_dealflow_tickers.json"
    sec_root = Path(sec_live_root.strip()) if sec_live_root.strip() else None
    try:
        cfg = DailyRunConfig(
            as_of=run_date,
            quarter=run_quarter,
            mode=mode,
            output_root=out,
            master_universe_path=master_path,
            handoff_path=handoff_path if handoff_path.exists() else None,
            sec_live_root=sec_root,
            skip_fetch=skip_fetch,
            skip_llm=skip_llm,
            llm_mode=llm_mode,
            min_broad_universe_count=min_broad_universe_count,
        )
        result = run_daily_fundamental(cfg)
    except Exception as exc:  # noqa: BLE001 - CLI must display gate/config errors cleanly.
        console.print(f"[red]fundamental-run-today failed:[/red] {exc}")
        raise typer.Exit(1)
    if format.strip().lower() == "json":
        console.print(json.dumps(result.summary, indent=2, sort_keys=True, default=str))
    else:
        console.print(f"[green]Daily fundamental run[/green] final={result.summary.get('final')} stopped={result.summary.get('stopped')} manifest={out / 'run_manifest.json'}")
    if any(gate.status.value == "hard_stop" for gate in result.gates):
        raise typer.Exit(2)
```

- [ ] **Step 4: Run CLI tests**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/test_cli_fundamental_run_today.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/research/fundamental/src/cli/commands.py tests/test_cli_fundamental_run_today.py
git commit -m "feat: add gated fundamental daily CLI"
```

---

## Task 12: Documentation and final verification

**Files:**

- Modify: `tradingagents/research/fundamental/docs/daily_run_gate_sequence.md`
- Modify: `tradingagents/research/fundamental/docs/daily_universe_llm_funnel_contract.md`
- Optional update after implementation: `memory/WORKING.md`, `memory/YYYY-MM-DD.md`

- [ ] **Step 1: Update the gate sequence docs**

Add a short implementation note to `tradingagents/research/fundamental/docs/daily_run_gate_sequence.md`:

```markdown
## Implemented command

Use:

`python -m cli.main fundamental-run-today --mode broad-master-final --date <YYYY-MM-DD> --quarter <YYYYQ#> --master-universe <path>`

The legacy `fundamental` command remains scout-smoke/backward-compatible. It is not the official broad daily final run.
```

- [ ] **Step 2: Run focused daily orchestrator tests**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest \
  tests/test_fundamental_daily_run_models.py \
  tests/test_fundamental_daily_universe_gate.py \
  tests/test_fundamental_daily_coverage_gate.py \
  tests/test_fundamental_daily_scoring_inputs.py \
  tests/test_fundamental_daily_eligibility_gate.py \
  tests/test_fundamental_daily_llm_validation.py \
  tests/test_fundamental_daily_finalize_gate.py \
  tests/test_fundamental_daily_orchestrator_contract.py \
  tests/test_cli_fundamental_run_today.py \
  -v
```

Expected: PASS.

- [ ] **Step 3: Run existing related regression tests**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest \
  tests/test_fundamental_dealflow_adapter.py \
  tests/test_fundamental_live_scoring_parity.py \
  tests/test_cli_fundamental_top10.py \
  tests/test_high_conviction_top15_exception_sleeve.py \
  tests/test_cli_fundamental_top15_refill_shadow.py \
  -v
```

Expected: PASS.

- [ ] **Step 4: Run full test suite if time allows**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m pytest tests/ -v
```

Expected: PASS or document unrelated pre-existing failures with exact failing tests.

- [ ] **Step 5: Run a diagnostic-only smoke command against a tiny fixture**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m cli.main fundamental-run-today \
  --mode diagnostic-only \
  --date 2026-05-12 \
  --quarter 2026Q2 \
  --master-universe eval_results/fundamental/2026-05-11_2026Q2_master_sec_fetch/final_dealflow_tickers_sec_eligible.json \
  --output-root eval_results/fundamental/2026-05-12_2026Q2_daily_diagnostic \
  --skip-fetch \
  --skip-llm \
  --format json
```

Expected:

- command exits `0` or diagnostic non-final status if later gates intentionally skipped
- `run_manifest.json` exists
- `master_fundamental_universe_2026Q2.csv` row count is broad scale
- no `high_conviction_top15.csv` is published in diagnostic mode

- [ ] **Step 6: Commit docs**

```bash
git add tradingagents/research/fundamental/docs/daily_run_gate_sequence.md tradingagents/research/fundamental/docs/daily_universe_llm_funnel_contract.md
git commit -m "docs: document gated fundamental daily command"
```

---

## Definition of done

Implementation is done only when:

- `fundamental-run-today --help` works.
- final mode requires explicit run mode.
- broad final mode hard-stops on scout-only/small universes.
- pre-LLM scoring can run with companyfacts even when earnings exhibits are missing.
- Tier 0-4 assignment does not run for rows missing `entry_open` without quarantine.
- LLM packets include only Tier 1-4 evidence-ready rows and packet count equals non-quarantined eligible count.
- post-LLM CSV is validated one row per packet.
- final scores plus explicit invalid quarantine count reconcile exactly to broad universe count.
- Top10 + Plus5 + shadow publish only from broad final scores.
- every gate writes an artifact and summary.
- failed gates write diagnosis and do not publish final Top15.
- focused tests and existing related regression tests pass.

## Execution notes

Use @superpowers:subagent-driven-development for implementation. Dispatch one worker per task, review after each task, and do not start the next task until tests pass. If implementing inline, use @superpowers:executing-plans and checkpoint after Tasks 3, 6, 9, and 12.
