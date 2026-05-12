from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping


def write_text_atomic(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp.write(text)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)
    return path


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        json.dump(payload, tmp, indent=2, sort_keys=True, default=str)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)
    return path


def write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> Path:
    materialized = [dict(row) for row in rows]
    if not materialized:
        return write_text_atomic(path, "")
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(dict.fromkeys(key for row in materialized for key in row.keys()))
    with tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        writer = csv.DictWriter(tmp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(materialized)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)
    return path


def source_hashes(paths: Mapping[str, Path | None]) -> dict[str, str]:
    from tradingagents.research.fundamental.src.storage import source_file_hash
    return {name: source_file_hash(path) for name, path in paths.items()}
