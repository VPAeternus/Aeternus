from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


def build_scout_quality_daily(
    *,
    as_of_date: str,
    scout_audit: Dict[str, Any] | None,
    event_cards: List[Dict[str, Any]] | None,
    coverage_precheck: Dict[str, Any] | None,
) -> Dict[str, Any]:
    detection_counts: Dict[str, int] = {}
    source_record_counts: Dict[str, int] = {}

    for signal in list((scout_audit or {}).get("signals", []) or []):
        source = str(signal.get("source", "")).strip() or "unknown"
        detection_counts[source] = detection_counts.get(source, 0) + 1

    breakout_alerts = list(((scout_audit or {}).get("breakout") or {}).get("alerts", []) or [])
    if breakout_alerts:
        detection_counts["breakout"] = detection_counts.get("breakout", 0) + len(breakout_alerts)

    insider_clusters = list(((scout_audit or {}).get("insider") or {}).get("buy_clusters", []) or []) + list(
        ((scout_audit or {}).get("insider") or {}).get("sell_clusters", []) or []
    )
    if insider_clusters:
        detection_counts["insider_cluster"] = detection_counts.get("insider_cluster", 0) + len(insider_clusters)

    for card in list(event_cards or []):
        for row in list(card.get("source_records", []) or []):
            source = str(row.get("source_family", "")).strip()
            if source:
                source_record_counts[source] = source_record_counts.get(source, 0) + 1

    coverage_by_event = {
        str(row.get("event_card_id", "")): str(row.get("coverage_status", "MISSING"))
        for row in list((coverage_precheck or {}).get("rows", []) or [])
    }

    rows: List[Dict[str, Any]] = []
    all_sources = sorted(set(detection_counts.keys()) | {
        str(source).strip()
        for card in list(event_cards or [])
        for source in list(card.get("source_bundle", []) or [])
        if str(source).strip()
    })

    for source in all_sources:
        related_cards = [card for card in list(event_cards or []) if source in list(card.get("source_bundle", []) or [])]
        statuses = [coverage_by_event.get(str(card.get("event_card_id", "")), "MISSING") for card in related_cards]
        detection_count = int(detection_counts.get(source, 0) or 0)
        if detection_count == 0:
            detection_count = int(source_record_counts.get(source, 0) or 0)
        rows.append(
            {
                "source": source,
                "detection_count": detection_count,
                "event_card_contribution_count": len(related_cards),
                "complete_count": sum(1 for status in statuses if status == "COMPLETE"),
                "partial_count": sum(1 for status in statuses if status == "PARTIAL"),
                "missing_count": sum(1 for status in statuses if status == "MISSING"),
            }
        )

    return {
        "date": as_of_date,
        "rows": rows,
        "summary": {
            "source_count": len(rows),
            "event_card_count": len(list(event_cards or [])),
        },
    }


def persist_scout_quality_daily(
    *,
    as_of_date: str,
    payload: Dict[str, Any],
    base_dir: Path | str = Path("eval_results") / "deal_flow",
) -> Dict[str, Any]:
    root = Path(base_dir) / as_of_date
    root.mkdir(parents=True, exist_ok=True)
    output_path = root / "scout_quality_daily.json"
    output_path.write_text(json.dumps(payload, indent=2))
    return {"output_path": str(output_path), "row_count": len(list((payload or {}).get("rows", []) or []))}
