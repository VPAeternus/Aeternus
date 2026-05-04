from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


DEFAULT_BASE_DIR = Path("eval_results/deal_flow")


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    with open(path, "r") as fh:
        return json.load(fh)


def build_source_attribution(
    source_date: str,
    *,
    base_dir: Path | str = DEFAULT_BASE_DIR,
) -> Dict[str, Any]:
    base = Path(base_dir) / source_date
    discovery_delta = _load_json(base / "discovery_delta.json") or {}
    scout_audit = _load_json(base / "scout_audit.json") or {}
    signals_raw = _load_json(base / "signals_raw.json") or []
    research_queue = _load_json(base / "research_queue.json") or {"items": []}
    shortlist = _load_json(base / "shortlist_top20.json") or {"candidates": []}

    rows: Dict[str, dict] = {}

    def _row(symbol: str) -> dict:
        symbol = str(symbol or "").upper().strip()
        if symbol not in rows:
            rows[symbol] = {
                "symbol": symbol,
                "discovery_sources": set(),
                "collector_families_present": set(),
                "entered_shortlist": False,
                "selected_for_deep": False,
                "entered_plan": False,
                "discovery_stage_hits": set(),
            }
        return rows[symbol]

    for record in discovery_delta.get("symbol_records", []):
        symbol = str(record.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        row = _row(symbol)
        row["discovery_sources"].update(record.get("sources_fired", []))
        row["discovery_stage_hits"].add("discovery_delta")

    for signal in discovery_delta.get("signals", []):
        symbol = str(signal.get("symbol") or "").upper().strip()
        source = str(signal.get("source") or "").strip()
        if not symbol:
            continue
        row = _row(symbol)
        if source:
            row["discovery_sources"].add(source)
        row["discovery_stage_hits"].add("discovery_delta")

    for signal in scout_audit.get("signals", []):
        symbol = str(signal.get("symbol") or signal.get("ticker") or "").upper().strip()
        source = str(signal.get("source") or "").strip()
        if not symbol:
            continue
        row = _row(symbol)
        if source:
            row["discovery_sources"].add(source)
        row["discovery_stage_hits"].add("scout_audit")

    for alert in ((scout_audit.get("breakout") or {}).get("alerts") or []):
        symbol = str(alert.get("ticker") or "").upper().strip()
        if not symbol:
            continue
        row = _row(symbol)
        row["discovery_sources"].add("breakout")
        row["discovery_stage_hits"].add("scout_audit")

    for sig in signals_raw:
        symbol = str(sig.get("symbol") or "").upper().strip()
        family = str(sig.get("signal_family") or "").strip()
        if not symbol:
            continue
        row = _row(symbol)
        if family:
            row["collector_families_present"].add(family)
        row["discovery_stage_hits"].add("collect")

    selected_ids = {
        str(item.get("symbol") or "").upper().strip()
        for item in research_queue.get("items", [])
        if bool(item.get("selected_for_deep"))
    }
    queue_ids = {
        str(item.get("symbol") or "").upper().strip()
        for item in research_queue.get("items", [])
    }
    for symbol in queue_ids:
        if not symbol:
            continue
        row = _row(symbol)
        row["entered_shortlist"] = True
        row["selected_for_deep"] = symbol in selected_ids
        row["discovery_stage_hits"].add("queue")

    for candidate in shortlist.get("candidates", []):
        symbol = str(candidate.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        row = _row(symbol)
        row["entered_shortlist"] = True
        row["discovery_stage_hits"].add("shortlist")

    normalized_rows: List[dict] = []
    for symbol in sorted(rows):
        row = dict(rows[symbol])
        row["discovery_sources"] = sorted(str(item) for item in row["discovery_sources"] if str(item).strip())
        row["collector_families_present"] = sorted(str(item) for item in row["collector_families_present"] if str(item).strip())
        row["discovery_stage_hits"] = sorted(str(item) for item in row["discovery_stage_hits"] if str(item).strip())
        normalized_rows.append(row)

    payload = {
        "source_date": source_date,
        "ticker_count": len(normalized_rows),
        "rows": normalized_rows,
    }
    output_path = base / "source_attribution.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2))
    payload["output_path"] = str(output_path)
    return payload
