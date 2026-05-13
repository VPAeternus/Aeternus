from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

from ..config.paths import default_legacy_run_root
from ..ingest.cik import resolve_ciks_for_tickers


def current_quarter(today: date | None = None) -> str:
    today = today or date.today()
    return f"{today.year}Q{((today.month - 1) // 3) + 1}"


def default_handoff_path(as_of_date: str) -> Path:
    return Path("eval_results") / "deal_flow" / as_of_date / "final_dealflow_tickers.json"


def read_final_handoff(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def final_handoff_to_universe_rows(
    handoff_payload: dict[str, Any],
    *,
    quarter: str,
    refresh_cik_map: bool = False,
) -> list[dict[str, Any]]:
    tickers = _normalize_symbols(handoff_payload.get("tickers", []) or [])
    metadata_by_ticker = dict(handoff_payload.get("metadata_by_ticker") or {})
    source_stage = str(handoff_payload.get("source_stage") or "")
    resolutions = {row.ticker: row for row in resolve_ciks_for_tickers(tickers, refresh=refresh_cik_map)}

    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        resolved = resolutions.get(ticker)
        metadata = dict(metadata_by_ticker.get(ticker) or {})
        rows.append(
            {
                "ticker": ticker,
                "cik": resolved.cik if resolved else "",
                "company_title": resolved.company_title if resolved else "",
                "cik_status": resolved.status if resolved else "not_resolved",
                "quarter": quarter,
                "dealflow_source_stage": source_stage,
                "scouts_json": json.dumps(list(metadata.get("scouts", []) or []), sort_keys=True),
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
    handoff_path: Path | None = None,
    output_path: Path | None = None,
    quarter: str | None = None,
    refresh_cik_map: bool = False,
) -> dict[str, Any]:
    handoff_path = handoff_path or default_handoff_path(as_of_date)
    quarter = quarter or current_quarter(date.fromisoformat(as_of_date))
    output_path = output_path or (default_legacy_run_root(as_of_date, quarter) / "dealflow_universe.csv")
    payload = read_final_handoff(handoff_path)
    rows = final_handoff_to_universe_rows(
        payload,
        quarter=quarter,
        refresh_cik_map=refresh_cik_map,
    )
    write_universe_csv(output_path, rows)
    unresolved = [row for row in rows if row.get("cik_status") != "resolved"]
    return {
        "as_of_date": as_of_date,
        "quarter": quarter,
        "handoff_path": str(handoff_path),
        "output_path": str(output_path),
        "row_count": len(rows),
        "resolved_cik_count": len(rows) - len(unresolved),
        "unresolved_cik_count": len(unresolved),
        "unresolved": unresolved,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert dealflow final ticker handoff to fundamental universe CSV")
    parser.add_argument("--date", required=True, dest="as_of_date")
    parser.add_argument("--handoff", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--quarter", default=None)
    parser.add_argument("--refresh-cik-map", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_dealflow_universe_csv(
        as_of_date=args.as_of_date,
        handoff_path=args.handoff,
        output_path=args.output,
        quarter=args.quarter,
        refresh_cik_map=bool(args.refresh_cik_map),
    )
    print(json.dumps(result, indent=2))


def _normalize_symbols(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    symbols: list[str] = []
    for raw in values:
        symbol = str(raw or "").upper().replace(".", "-").strip()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
    return symbols


if __name__ == "__main__":
    main()
