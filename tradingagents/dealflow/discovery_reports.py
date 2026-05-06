"""Discovery-stage report persistence helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from tradingagents.dealflow.discovery_delta import build_discovery_delta
from tradingagents.dealflow.theme_heatmap import write_theme_heatmap


def write_theme_heatmap_report(akg: Any, *, as_of_date: str, out_dir: Path | str = Path("eval_results") / "deal_flow") -> Path | None:
    """Write AKG theme heatmap when AKG is available; otherwise no-op."""
    if akg is None:
        return None
    return write_theme_heatmap(akg, as_of_date=as_of_date, out_dir=out_dir)


def write_discovery_delta_report(
    *,
    as_of_date: str,
    out_dir: Path | str,
    scout_audit: Dict[str, Any],
    fvg_recall: Dict[str, Any],
    fma_recall: Dict[str, Any],
) -> Dict[str, Any]:
    """Build and persist discovery delta artifact."""
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    discovery_delta = build_discovery_delta(
        as_of_date=as_of_date,
        scout_audit=scout_audit,
        fvg_recall=fvg_recall,
        fma_recall=fma_recall,
    )
    (root / "discovery_delta.json").write_text(json.dumps(discovery_delta, indent=2))
    return discovery_delta


def empty_discovery_delta() -> Dict[str, Any]:
    return {
        "coverage_summary": {"signal_count": 0, "record_count": 0},
        "cohorts": {"scout_only": [], "technical_only": [], "multi_channel": []},
        "top_delta_symbols": [],
    }
