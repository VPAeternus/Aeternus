from __future__ import annotations

import csv
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


def _master_row(item: Mapping[str, Any], *, quarter: str, source_name: str) -> dict[str, Any] | None:
    ticker = _ticker(item.get("symbol") or item.get("ticker"))
    if not ticker:
        return None
    return {
        "ticker": ticker, "symbol": ticker, "cik": str(item.get("cik", "")).strip(),
        "company_title": str(item.get("company_title", item.get("title", ""))).strip(),
        "cik_status": str(item.get("cik_status") or "resolved").strip(), "quarter": quarter,
        "master_universe_source": source_name, "dealflow_source_stage": "master_fundamental_universe", "scouts_json": "[]",
    }


def _load_master_json_rows(path: Path, quarter: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"master universe JSON is malformed: {path}") from exc
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict) and isinstance(payload.get("items"), list):
        items = payload["items"]
    else:
        raise ValueError("master universe JSON must be a list or an object with an items list")
    rows = [_master_row(item, quarter=quarter, source_name=path.name) for item in items if isinstance(item, Mapping)]
    return [row for row in rows if row is not None]


def _load_master_csv_rows(path: Path, quarter: str) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = {str(field or "").strip() for field in (reader.fieldnames or [])}
        if not ({"ticker", "symbol"} & fields):
            raise ValueError("master universe CSV must include ticker or symbol column")
        if "cik" not in fields:
            raise ValueError("master universe CSV must include cik column")
        rows = [_master_row(row, quarter=quarter, source_name=path.name) for row in reader]
    return [row for row in rows if row is not None]


def _load_master_rows(path: Path, quarter: str) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        rows = _load_master_csv_rows(path, quarter)
    elif suffix in {".json", ""}:
        rows = _load_master_json_rows(path, quarter)
    else:
        raise ValueError("master universe must be JSON (.json) or compatibility CSV (.csv)")
    if not rows:
        raise ValueError("master universe contains no valid ticker rows")
    return rows


def _load_scout_payload(path: Path | None) -> tuple[list[str], dict[str, Any], str]:
    if path is None or not path.exists():
        return [], {}, ""
    payload = json.loads(path.read_text(encoding="utf-8"))
    seen: set[str] = set(); tickers: list[str] = []
    for raw in payload.get("tickers", []) or []:
        ticker = _ticker(raw)
        if ticker and ticker not in seen:
            tickers.append(ticker); seen.add(ticker)
    return tickers, dict(payload.get("metadata_by_ticker") or {}), str(payload.get("source_stage") or "")


def build_combined_universe(
    *,
    master_universe_path: Path,
    handoff_path: Path | None,
    quarter: str,
    output_csv: Path,
    unresolved_new_scouts: Mapping[str, Mapping[str, Any]] | None = None,
    rejected_new_scouts: Mapping[str, Mapping[str, Any]] | None = None,
) -> UniverseBuildResult:
    master_rows = _load_master_rows(master_universe_path, quarter)
    by_ticker = {row["ticker"]: dict(row) for row in master_rows}
    scouts, metadata, source_stage = _load_scout_payload(handoff_path)
    resolved_new = {str(k).upper().replace(".", "-"): dict(v) for k, v in (unresolved_new_scouts or {}).items()}
    rejected_new = {str(k).upper().replace(".", "-"): dict(v) for k, v in (rejected_new_scouts or {}).items()}
    new_scouts = []
    rejected_scouts = []
    for ticker in scouts:
        scout_meta = dict(metadata.get(ticker) or {})
        if ticker in by_ticker:
            by_ticker[ticker]["dealflow_source_stage"] = source_stage or by_ticker[ticker].get("dealflow_source_stage", "")
            by_ticker[ticker]["scouts_json"] = json.dumps(list(scout_meta.get("scouts", []) or []), sort_keys=True)
            continue
        resolved = resolved_new.get(ticker, {})
        if str(resolved.get("cik", "")).strip() and str(resolved.get("company_title", "")).strip():
            by_ticker[ticker] = {
                **resolved,
                "ticker": ticker,
                "symbol": ticker,
                "cik": str(resolved.get("cik", "")).strip(),
                "company_title": str(resolved.get("company_title", "")).strip(),
                "cik_status": str(resolved.get("cik_status") or "resolved"),
                "quarter": quarter,
                "master_universe_source": "daily_scout_append",
                "dealflow_source_stage": source_stage,
                "scouts_json": json.dumps(list(scout_meta.get("scouts", []) or []), sort_keys=True),
            }
            new_scouts.append(ticker)
        else:
            rejected = rejected_new.get(ticker, {})
            rejected_scouts.append({"ticker": ticker, "quarter": quarter, "dealflow_source_stage": source_stage, **rejected})
    rows = [by_ticker[ticker] for ticker in sorted(by_ticker)]
    write_csv(output_csv, rows)
    rejection_path = output_csv.parent / "dealflow_identity_rejections.csv"
    write_csv(rejection_path, rejected_scouts)
    summary = {
        "master_count": len(master_rows),
        "scout_count": len(scouts),
        "combined_count": len(rows),
        "new_scout_count": len(new_scouts),
        "rejected_new_scout_count": len(rejected_scouts),
        "new_scouts": new_scouts,
        "rejected_new_scouts": [row["ticker"] for row in rejected_scouts],
        "missing_cik_count": sum(1 for row in rows if not row.get("cik")),
    }
    summary_path = output_csv.parent / "universe_gate_summary.json"
    write_json_atomic(summary_path, summary)
    return UniverseBuildResult(rows, summary, {"universe_csv": str(output_csv), "universe_summary": str(summary_path), "dealflow_identity_rejections": str(rejection_path)})


def validate_universe_gate(rows: list[dict[str, Any]], *, run_mode: RunMode, scout_count: int, min_broad_universe_count: int, artifacts: dict[str, str]) -> GateResult:
    row_count = len(rows); missing_cik = sum(1 for row in rows if not str(row.get("cik", "")).strip())
    summary = {"row_count": row_count, "scout_count": scout_count, "missing_cik_count": missing_cik}
    if run_mode == RunMode.BROAD_MASTER_FINAL and (row_count < min_broad_universe_count or row_count <= scout_count):
        summary["reason"] = "broad_master_universe_too_small_or_scout_only"
        return GateResult(2, "Universe construction and drift control", GateStatus.HARD_STOP, summary, artifacts)
    if missing_cik:
        summary["reason"] = "missing_cik"
        return GateResult(2, "Universe construction and drift control", GateStatus.HARD_STOP, summary, artifacts)
    return GateResult(2, "Universe construction and drift control", GateStatus.PASS, summary, artifacts)
