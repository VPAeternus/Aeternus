"""Internal company-context lookup helpers for CLI and harness surfaces."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


_DEFAULT_KG_PATH = Path("eval_results/control/knowledge_graph.json")
_DEFAULT_DEALFLOW_DIR = Path("eval_results/deal_flow")
_DEFAULT_RESULTS_DIR = Path("results")
_DEFAULT_POSITIONS_PATH = Path("eval_results/paper_execution/positions.json")
_DEFAULT_X_FEED_DIR = Path("eval_results/x_feed")


def get_company_context(
    symbol: str,
    *,
    as_of_date: Optional[str] = None,
    knowledge_graph_path: Path | str = _DEFAULT_KG_PATH,
    dealflow_base_dir: Path | str = _DEFAULT_DEALFLOW_DIR,
    results_base_dir: Path | str = _DEFAULT_RESULTS_DIR,
    positions_path: Path | str = _DEFAULT_POSITIONS_PATH,
    x_feed_base_dir: Path | str = _DEFAULT_X_FEED_DIR,
) -> Dict[str, Any]:
    symbol_norm = str(symbol or "").upper().strip()
    resolved_date = _resolve_as_of_date(as_of_date)

    akg = _lookup_akg_node(symbol_norm, Path(knowledge_graph_path))
    analysis = _lookup_latest_analysis(symbol_norm, resolved_date, Path(results_base_dir))
    scout_handoff = _lookup_latest_scout_handoff_hit(symbol_norm, resolved_date, Path(dealflow_base_dir))
    portfolio = _lookup_position(symbol_norm, Path(positions_path))
    x_feed = _lookup_latest_x_feed_hit(symbol_norm, resolved_date, Path(x_feed_base_dir))

    known_gaps: List[str] = []
    if not akg.get("found"):
        known_gaps.append("Ticker not present in AKG.")
    if not analysis.get("found"):
        known_gaps.append("No internal analysis report found.")
    if not scout_handoff.get("found"):
        known_gaps.append("Ticker not present in latest scout ticker handoff.")
    if not portfolio.get("found"):
        known_gaps.append("Ticker not present in current internal positions.")
    if not x_feed.get("found"):
        known_gaps.append("Ticker not present in internal X-feed coverage.")

    return {
        "symbol": symbol_norm,
        "as_of_date": resolved_date,
        "search_scope": "internal_only",
        "akg": akg,
        "analysis": analysis,
        "dealflow": {
            "scout_handoff": scout_handoff,
        },
        "portfolio": portfolio,
        "x_feed": x_feed,
        "known_gaps": known_gaps,
    }


def _resolve_as_of_date(as_of_date: Optional[str]) -> str:
    text = str(as_of_date or "").strip()
    if text:
        return text
    return dt.date.today().isoformat()


def _lookup_akg_node(symbol: str, path: Path) -> Dict[str, Any]:
    payload = _read_json(path)
    nodes = payload.get("nodes", {}) if isinstance(payload, dict) else {}
    node = nodes.get(symbol) if isinstance(nodes, dict) else None
    if not isinstance(node, dict):
        return {
            "found": False,
            "path": str(path),
            "display_name": None,
            "sector": None,
            "aeternus_score": None,
            "node": None,
        }
    return {
        "found": True,
        "path": str(path),
        "display_name": node.get("display_name"),
        "sector": node.get("sector"),
        "aeternus_score": node.get("aeternus_score"),
        "node": node,
    }


def _lookup_latest_analysis(symbol: str, as_of_date: str, results_base_dir: Path) -> Dict[str, Any]:
    symbol_dir = results_base_dir / symbol
    if not symbol_dir.exists():
        return {
            "found": False,
            "path": None,
            "latest_report_date": None,
            "rating": None,
            "aeternus_score": None,
            "confidence": None,
        }

    for date_str, date_dir in _iter_dated_dirs(symbol_dir, as_of_date):
        report_path = date_dir / "analysis_report.json"
        report = _read_json(report_path)
        if not isinstance(report, dict):
            continue
        rating_block = report.get("aeternus_score") if isinstance(report.get("aeternus_score"), dict) else report
        if not isinstance(rating_block, dict):
            rating_block = {}
        return {
            "found": True,
            "path": str(report_path),
            "latest_report_date": date_str,
            "rating": rating_block.get("rating"),
            "aeternus_score": rating_block.get("aeternus_score"),
            "confidence": rating_block.get("confidence"),
            "summary_excerpt": _first_non_empty_string(
                report.get("final_trade_decision"),
                report.get("trader_investment_plan"),
                report.get("investment_plan"),
            ),
        }

    return {
        "found": False,
        "path": None,
        "latest_report_date": None,
        "rating": None,
        "aeternus_score": None,
        "confidence": None,
    }


def _lookup_latest_scout_handoff_hit(symbol: str, as_of_date: str, base_dir: Path) -> Dict[str, Any]:
    for date_str, date_dir in _iter_dated_dirs(base_dir, as_of_date):
        artifact_path = date_dir / "final_dealflow_tickers.json"
        payload = _read_json(artifact_path)
        tickers = payload.get("tickers", []) if isinstance(payload, dict) else []
        if symbol not in {str(ticker).upper().strip() for ticker in tickers}:
            continue
        metadata = dict((payload.get("metadata_by_ticker") or {}).get(symbol) or {})
        return {
            "found": True,
            "date": date_str,
            "path": str(artifact_path),
            "source_stage": payload.get("source_stage"),
            "metadata": metadata,
        }

    return {
        "found": False,
        "date": None,
        "path": None,
        "source_stage": None,
        "metadata": None,
    }


def _lookup_position(symbol: str, positions_path: Path) -> Dict[str, Any]:
    payload = _read_json(positions_path)
    open_positions = payload.get("open_positions", {}) if isinstance(payload, dict) else {}
    position = open_positions.get(symbol) if isinstance(open_positions, dict) else None
    if not isinstance(position, dict):
        return {
            "found": False,
            "path": str(positions_path),
            "updated_at": payload.get("updated_at") if isinstance(payload, dict) else None,
            "position": None,
        }
    return {
        "found": True,
        "path": str(positions_path),
        "updated_at": payload.get("updated_at") if isinstance(payload, dict) else None,
        "position": position,
    }


def _lookup_latest_x_feed_hit(symbol: str, as_of_date: str, base_dir: Path) -> Dict[str, Any]:
    for date_str, date_dir in _iter_dated_dirs(base_dir, as_of_date):
        merged_path = date_dir / "merged.json"
        payload = _read_json(merged_path)
        if not isinstance(payload, dict):
            continue
        entry = payload.get(symbol)
        if not isinstance(entry, dict):
            continue
        return {
            "found": True,
            "source_date": date_str,
            "path": str(merged_path),
            "entry": entry,
        }

    return {
        "found": False,
        "source_date": None,
        "path": None,
        "entry": None,
    }


def _iter_dated_dirs(base_dir: Path, as_of_date: str) -> List[Tuple[str, Path]]:
    if not base_dir.exists():
        return []
    as_of = _parse_date(as_of_date)
    rows: List[Tuple[str, Path]] = []
    for child in base_dir.iterdir():
        if not child.is_dir():
            continue
        parsed = _parse_date(child.name)
        if parsed is None:
            continue
        if as_of is not None and parsed > as_of:
            continue
        rows.append((child.name, child))
    rows.sort(key=lambda row: row[0], reverse=True)
    return rows


def _parse_date(value: str) -> Optional[dt.date]:
    try:
        return dt.datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, IsADirectoryError, json.JSONDecodeError, OSError, TypeError):
        return {}


def _first_non_empty_string(*values: Any) -> Optional[str]:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None
