from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .artifacts import write_json_atomic, write_text_atomic


START_FILE = Path("tradingagents/research/fundamental/data/master_fundamental_universe_start_2021Q4.json")
ADDITIONS_LEDGER = Path("tradingagents/research/fundamental/data/master_fundamental_universe_additions.jsonl")


def _ticker(value: Any) -> str:
    return str(value or "").upper().replace(".", "-").strip()


def _coerce_row(item: Mapping[str, Any]) -> dict[str, Any] | None:
    ticker = _ticker(item.get("symbol") or item.get("ticker"))
    if not ticker:
        return None
    row = dict(item)
    row["ticker"] = ticker
    row["symbol"] = ticker
    return row


def _load_start_rows(start_path: Path = START_FILE) -> list[dict[str, Any]]:
    try:
        raw = start_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValueError(f"start universe file not found: {start_path}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"start universe JSON is malformed: {start_path}") from exc
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        items = payload["items"]
    elif isinstance(payload, list):
        items = payload
    else:
        raise ValueError(f"start universe JSON must be a list or an object with an items list: {start_path}")
    rows = [_coerce_row(item) for item in items if isinstance(item, Mapping)]
    return [row for row in rows if row is not None]


def _load_additions_rows(additions_path: Path = ADDITIONS_LEDGER) -> list[dict[str, Any]]:
    if not additions_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(additions_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"additions ledger JSONL is malformed: {additions_path} line {line_number}") from exc
        if isinstance(payload, Mapping):
            row = _coerce_row(payload)
            if row is not None:
                rows.append(row)
    return rows


def load_master_universe_rows(*, start_path: Path = START_FILE, additions_path: Path = ADDITIONS_LEDGER) -> list[dict[str, Any]]:
    start_rows = _load_start_rows(start_path)
    start_tickers = {row["ticker"] for row in start_rows}
    merged: dict[str, dict[str, Any]] = {row["ticker"]: dict(row) for row in start_rows}
    for row in _load_additions_rows(additions_path):
        if row["ticker"] not in start_tickers:
            merged[row["ticker"]] = dict(row)
    return [merged[ticker] for ticker in sorted(merged)]


def materialize_master_universe(*, output_root: Path, start_path: Path = START_FILE, additions_path: Path = ADDITIONS_LEDGER) -> Path:
    rows = load_master_universe_rows(start_path=start_path, additions_path=additions_path)
    out_path = output_root / "master_fundamental_universe_2021Q4_active.json"
    write_json_atomic(out_path, {"items": rows, "source": start_path.name, "additions_source": additions_path.name if additions_path.exists() else "", "count": len(rows)})
    return out_path


def append_master_additions(rows: list[Mapping[str, Any]], *, additions_path: Path = ADDITIONS_LEDGER) -> Path:
    existing = additions_path.read_text(encoding="utf-8") if additions_path.exists() else ""
    lines = [existing.rstrip("\n")] if existing.strip() else []
    for row in rows:
        coerced = _coerce_row(row)
        if coerced is not None:
            lines.append(json.dumps(coerced, sort_keys=True, default=str))
    return write_text_atomic(additions_path, "\n".join(line for line in lines if line) + ("\n" if lines else ""))
