from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List

from .hindsight import compute_hindsight
from .ic_weight_writeback import DEFAULT_DB_PATH, DEFAULT_OUTPUT_PATH, write_signal_weight_adjustments
from .observed_edges import update_observed_edges_for_cycle
from .performance_tracker import compute_performance_review
from .source_attribution import build_source_attribution


_DEAL_FLOW_DIR = Path("eval_results/deal_flow")


def _safe_error(exc: Exception) -> str:
    return str(exc).strip() or exc.__class__.__name__


def _call_with_optional_db(func, *, source_date: str, benchmark: str, db_path: Path):
    try:
        return func(source_date=source_date, benchmark=benchmark, db_path=db_path)
    except TypeError:
        return func(source_date=source_date, benchmark=benchmark)


def run_learning_cycle(
    source_date: str,
    *,
    benchmark: str = "QQQ",
    deal_flow_dir: Path | str | None = None,
    db_path: Path | str = DEFAULT_DB_PATH,
    weights_output_path: Path | str = DEFAULT_OUTPUT_PATH,
) -> Dict[str, Any]:
    base_root = Path(deal_flow_dir) if deal_flow_dir is not None else _DEAL_FLOW_DIR
    base = base_root / source_date
    warnings: List[str] = []
    result: Dict[str, Any] = {
        "source_date": source_date,
        "learning_status": "OK",
        "hindsight_status": "SKIPPED",
        "performance_status": "SKIPPED",
        "weight_update_status": "SKIPPED",
        "observed_edges_added": 0,
        "warnings": warnings,
    }

    try:
        hindsight = _call_with_optional_db(
            compute_hindsight,
            source_date=source_date,
            benchmark=benchmark,
            db_path=Path(db_path),
        )
        result["hindsight"] = hindsight
        if hindsight.get("error"):
            result["hindsight_status"] = "ERROR"
            warnings.append(str(hindsight.get("error")))
            result["learning_status"] = "DEGRADED"
        else:
            result["hindsight_status"] = "OK"
    except Exception as exc:
        result["hindsight_status"] = "ERROR"
        warnings.append(_safe_error(exc))
        result["learning_status"] = "DEGRADED"

    try:
        performance = _call_with_optional_db(
            compute_performance_review,
            source_date=source_date,
            benchmark=benchmark,
            db_path=Path(db_path),
        )
        result["performance"] = performance
        if performance.get("error"):
            result["performance_status"] = "ERROR"
            warnings.append(str(performance.get("error")))
            result["learning_status"] = "DEGRADED"
        else:
            result["performance_status"] = "OK"
    except Exception as exc:
        result["performance_status"] = "ERROR"
        warnings.append(_safe_error(exc))
        result["learning_status"] = "DEGRADED"

    try:
        attribution = build_source_attribution(source_date=source_date, base_dir=base_root)
        result["source_attribution"] = attribution
    except Exception as exc:
        warnings.append(f"source_attribution: {_safe_error(exc)}")
        result["learning_status"] = "DEGRADED"

    try:
        edge_result = update_observed_edges_for_cycle(source_date=source_date)
        result["observed_edges"] = edge_result
        result["observed_edges_added"] = int(edge_result.get("edges_added", 0) or 0)
    except Exception as exc:
        warnings.append(f"observed_edges: {_safe_error(exc)}")
        result["learning_status"] = "DEGRADED"

    try:
        weight_result = write_signal_weight_adjustments(
            db_path=Path(db_path),
            output_path=Path(weights_output_path),
        )
        result["weight_writeback"] = weight_result
        weight_status = str(weight_result.get("status") or "SKIPPED").strip().upper()
        if weight_status == "UPDATED":
            if not str(weight_result.get("output_path") or "").strip():
                result["weight_update_status"] = "BLOCKED_INVALID_OUTPUT"
                result["learning_status"] = "BLOCKED"
                warnings.append("weight_writeback invalid payload")
            else:
                result["weight_update_status"] = "UPDATED"
        else:
            result["weight_update_status"] = weight_status
    except Exception as exc:
        result["weight_update_status"] = "ERROR"
        warnings.append(f"weight_writeback: {_safe_error(exc)}")
        if result["learning_status"] != "BLOCKED":
            result["learning_status"] = "DEGRADED"

    output_path = base / "learning_status.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, default=str))
    result["output_path"] = str(output_path)
    return result
