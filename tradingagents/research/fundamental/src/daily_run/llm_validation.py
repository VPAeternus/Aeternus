from __future__ import annotations

import csv
from pathlib import Path

from tradingagents.research.fundamental.src.features.post_llm_scores import REQUIRED_LLM_FIELDS

from .models import GateResult, GateStatus


def _clean(value: object) -> str:
    return str(value or "").strip()


def validate_post_llm_csv(path: Path, *, expected_sample_ids: set[str]) -> GateResult:
    if not path.exists() or path.stat().st_size == 0:
        return GateResult(8, "LLM packet, extraction, and validation", GateStatus.HARD_STOP, {"reason": "post_llm_missing_or_empty", "path": str(path)}, {})
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    seen = [str(row.get("sample_id") or f"{str(row.get('ticker', '')).upper()}_{row.get('quarter', '')}") for row in rows]
    duplicates = sorted({sample_id for sample_id in seen if seen.count(sample_id) > 1})
    missing = sorted(expected_sample_ids - set(seen))
    unexpected = sorted(set(seen) - expected_sample_ids)
    rows_missing_fields = {
        seen[idx]: [field for field in REQUIRED_LLM_FIELDS if _clean(row.get(field)) == ""]
        for idx, row in enumerate(rows)
    }
    rows_missing_fields = {sample_id: fields for sample_id, fields in rows_missing_fields.items() if fields}
    status = GateStatus.PASS if not duplicates and not missing and not unexpected and not rows_missing_fields else GateStatus.HARD_STOP
    summary = {
        "expected_count": len(expected_sample_ids),
        "completed_count": len(rows),
        "missing_sample_ids": missing,
        "duplicate_sample_ids": duplicates,
        "unexpected_sample_ids": unexpected,
        "rows_missing_required_fields": rows_missing_fields,
    }
    if rows_missing_fields:
        summary["reason"] = "post_llm_missing_required_fields"
    return GateResult(8, "LLM packet, extraction, and validation", status, summary, {"post_llm_scores": str(path)})
