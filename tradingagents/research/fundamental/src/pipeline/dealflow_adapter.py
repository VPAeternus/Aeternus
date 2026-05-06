from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

from ..ingest.cik import resolve_ciks_for_tickers


def current_quarter(today: date | None = None) -> str:
    today = today or date.today()
    return f"{today.year}Q{((today.month - 1) // 3) + 1}"


def default_queue_path(as_of_date: str) -> Path:
    return Path("eval_results") / "deal_flow" / as_of_date / "research_queue.json"


def read_research_queue(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def queue_items_to_universe_rows(
    queue_payload: dict[str, Any],
    *,
    quarter: str,
    refresh_cik_map: bool = False,
    selected_only: bool = True,
) -> list[dict[str, Any]]:
    items = list(queue_payload.get("items", []) or [])
    if selected_only:
        items = [item for item in items if bool(item.get("selected_for_deep"))]

    symbols = [str(item.get("symbol", "")).upper().replace(".", "-").strip() for item in items]
    resolutions = {row.ticker: row for row in resolve_ciks_for_tickers(symbols, refresh=refresh_cik_map)}

    rows: list[dict[str, Any]] = []
    for idx, item in enumerate(items, start=1):
        ticker = str(item.get("symbol", "")).upper().replace(".", "-").strip()
        if not ticker:
            continue
        resolved = resolutions.get(ticker)
        rows.append(
            {
                "ticker": ticker,
                "cik": resolved.cik if resolved else "",
                "company_title": resolved.company_title if resolved else "",
                "cik_status": resolved.status if resolved else "not_resolved",
                "quarter": quarter,
                "dealflow_queue_id": item.get("queue_id", ""),
                "dealflow_rank": idx,
                "sector": item.get("sector", ""),
                "asset_class": item.get("asset_class", "Equity"),
                "lane": item.get("lane", ""),
                "deal_flow_score": item.get("deal_flow_score", ""),
                "triage_score": item.get("triage_score", ""),
                "momentum_score": item.get("momentum_score", ""),
                "asymmetry_score": item.get("asymmetry_score", ""),
                "research_playbook": item.get("research_playbook", ""),
                "why_now": item.get("why_now", ""),
                "source": item.get("source", ""),
                "source_detail": item.get("source_detail", ""),
                "thesis_tags_json": json.dumps(item.get("thesis_tags", []) or [], sort_keys=True),
                "risk_tags_json": json.dumps(item.get("risk_tags", []) or [], sort_keys=True),
                "subscores_json": json.dumps(item.get("subscores", {}) or {}, sort_keys=True),
                "evidence_json": json.dumps(item.get("evidence", {}) or {}, sort_keys=True),
            }
        )
    return rows


def write_universe_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_dealflow_universe_csv(
    *,
    as_of_date: str,
    queue_path: Path | None = None,
    output_path: Path | None = None,
    quarter: str | None = None,
    refresh_cik_map: bool = False,
    selected_only: bool = True,
) -> dict[str, Any]:
    queue_path = queue_path or default_queue_path(as_of_date)
    quarter = quarter or current_quarter(date.fromisoformat(as_of_date))
    output_path = output_path or (
        Path("eval_results") / "fundamental" / as_of_date / "dealflow_universe.csv"
    )
    payload = read_research_queue(queue_path)
    rows = queue_items_to_universe_rows(
        payload,
        quarter=quarter,
        refresh_cik_map=refresh_cik_map,
        selected_only=selected_only,
    )
    write_universe_csv(output_path, rows)
    unresolved = [row for row in rows if row.get("cik_status") != "resolved"]
    return {
        "as_of_date": as_of_date,
        "quarter": quarter,
        "queue_path": str(queue_path),
        "output_path": str(output_path),
        "row_count": len(rows),
        "resolved_cik_count": len(rows) - len(unresolved),
        "unresolved_cik_count": len(unresolved),
        "unresolved": unresolved,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert dealflow research_queue.json to fundamental universe CSV")
    parser.add_argument("--date", required=True, dest="as_of_date")
    parser.add_argument("--queue", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--quarter", default=None)
    parser.add_argument("--refresh-cik-map", action="store_true")
    parser.add_argument("--all", action="store_true", help="Include all queue items, not only selected_for_deep")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_dealflow_universe_csv(
        as_of_date=args.as_of_date,
        queue_path=args.queue,
        output_path=args.output,
        quarter=args.quarter,
        refresh_cik_map=bool(args.refresh_cik_map),
        selected_only=not bool(args.all),
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
