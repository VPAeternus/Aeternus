"""Scout attribution audit helpers for dealflow discovery.

Persists which scout found which tickers so downstream performance can be
measured by scout/source over time.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def append_scout_audit(
    *,
    scout: str,
    as_of_date: str,
    symbols: Iterable[str],
    records: Optional[List[Dict[str, Any]]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    base_dir: Path | str = Path("eval_results") / "deal_flow",
) -> Dict[str, Any]:
    """Append/update scout attribution artifacts for a date.

    Writes:
    - eval_results/deal_flow/<date>/scout_audit.json
    - eval_results/deal_flow/scout_audit_background.jsonl
    """
    clean_symbols = sorted({str(s or "").upper().strip() for s in symbols if str(s or "").strip()})
    now = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    row = {
        "scout": str(scout),
        "as_of_date": str(as_of_date),
        "timestamp": now,
        "count": len(clean_symbols),
        "symbols": clean_symbols,
        "records": list(records or []),
        "metadata": dict(metadata or {}),
    }

    root = Path(base_dir)
    day_dir = root / str(as_of_date)
    day_dir.mkdir(parents=True, exist_ok=True)
    daily_path = day_dir / "scout_audit.json"
    try:
        payload = json.loads(daily_path.read_text()) if daily_path.exists() else {}
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}
    scouts = dict(payload.get("scouts", {}) or {})
    scouts[str(scout)] = row
    payload.update({"date": str(as_of_date), "updated_at": now, "scouts": scouts})
    daily_path.write_text(json.dumps(payload, indent=2))

    jsonl_path = root / "scout_audit_background.jsonl"
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with open(jsonl_path, "a") as f:
        f.write(json.dumps(row) + "\n")

    return row
