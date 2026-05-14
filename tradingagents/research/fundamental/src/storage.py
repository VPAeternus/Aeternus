from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd


TABLES = {
    "universe",
    "filing_events",
    "raw_documents",
    "pre_llm_scores",
    "post_llm_scores",
    "tier_classification",
    "candidate_scores",
    "investment_decisions",
    "research_memos",
    "positions",
    "price_history",
    "candidate_monitoring",
    "theme_taxonomy",
    "candidate_theme_tags",
    "theme_cohort_scores",
}

REQUIRED_COLUMNS = {
    "universe": {"ticker"},
    "filing_events": {"ticker", "quarter"},
    "raw_documents": {"ticker", "quarter", "document_type"},
    "pre_llm_scores": {"ticker", "quarter", "pre_llm_fundamental_bucket"},
    "post_llm_scores": {"ticker", "quarter"},
    "tier_classification": {"ticker", "quarter"},
    "candidate_scores": {"ticker", "quarter", "entry_score_0_100"},
    "investment_decisions": {"ticker", "quarter", "decision_date", "decision_type"},
    "research_memos": {"ticker", "decision_date"},
    "positions": {"ticker", "quarter", "position_open_date"},
    "price_history": {"ticker", "date", "open", "close"},
    "candidate_monitoring": {"ticker", "quarter", "as_of_date"},
    "theme_taxonomy": {"theme_id", "theme_name"},
    "candidate_theme_tags": {"ticker", "quarter", "theme_id"},
    "theme_cohort_scores": {"theme_id", "as_of_date"},
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def make_pipeline_run_id(prefix: str = "run") -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def source_file_hash(path: Path | None) -> str:
    if path is None or not path.exists() or not path.is_file():
        return ""
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def add_run_lineage(
    rows: list[dict[str, Any]],
    *,
    pipeline_run_id: str,
    as_of_date: str,
    source_hash: str = "",
    created_at: str | None = None,
) -> list[dict[str, Any]]:
    stamp = created_at or utc_now_iso()
    return [
        {
            "pipeline_run_id": pipeline_run_id,
            "as_of_date": as_of_date,
            "created_at": stamp,
            "source_file_hash": source_hash,
            **row,
        }
        for row in rows
    ]


def table_path(lake_root: Path, table: str) -> Path:
    if table not in TABLES:
        raise ValueError(f"unknown table: {table}")
    return lake_root / f"{table}.parquet"


def read_table(lake_root: Path, table: str) -> pd.DataFrame:
    path = table_path(lake_root, table)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


DEFAULT_KEYS = {
    "universe": ["ticker"],
    "filing_events": ["ticker", "quarter", "filing_accession", "filing_type"],
    "raw_documents": ["ticker", "quarter", "accession", "document_type"],
    "pre_llm_scores": ["ticker", "quarter"],
    "post_llm_scores": ["ticker", "quarter"],
    "tier_classification": ["ticker", "quarter"],
    "candidate_scores": ["ticker", "quarter"],
    "investment_decisions": ["ticker", "quarter", "decision_date", "decision_type"],
    "research_memos": ["ticker", "decision_date"],
    "positions": ["ticker", "quarter", "position_open_date"],
    "price_history": ["ticker", "date"],
    "candidate_monitoring": ["ticker", "quarter", "as_of_date"],
    "theme_taxonomy": ["theme_id"],
    "candidate_theme_tags": ["ticker", "quarter", "theme_id"],
    "theme_cohort_scores": ["theme_id", "as_of_date"],
}


def _upsert(old: pd.DataFrame, new: pd.DataFrame, key_columns: list[str]) -> pd.DataFrame:
    present_keys = [key for key in key_columns if key in old.columns and key in new.columns]
    if not present_keys or old.empty:
        return pd.concat([old, new], ignore_index=True)
    merged = pd.concat([old, new], ignore_index=True)
    return merged.drop_duplicates(subset=present_keys, keep="last").reset_index(drop=True)


def _normalise_for_parquet(frame: pd.DataFrame) -> pd.DataFrame:
    normalised = frame.copy()
    for column in normalised.columns:
        series = normalised[column]
        if series.dtype != "object":
            continue
        non_null = series.dropna()
        if non_null.empty:
            normalised[column] = series.astype("string")
            continue
        types = {type(value) for value in non_null}
        if len(types) > 1 or bytes in types:
            normalised[column] = series.map(lambda value: value.decode("utf-8", errors="ignore") if isinstance(value, bytes) else ("" if value is None else str(value)))
    return normalised


def write_table(
    lake_root: Path,
    table: str,
    rows: list[dict[str, Any]],
    *,
    append: bool = True,
    key_columns: list[str] | None = None,
) -> Path:
    path = table_path(lake_root, table)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    missing = REQUIRED_COLUMNS.get(table, set()) - set(frame.columns)
    if rows and missing:
        raise ValueError(f"{table} missing required columns: {sorted(missing)}")
    if append and path.exists():
        old = pd.read_parquet(path)
        frame = _upsert(old, frame, key_columns or DEFAULT_KEYS.get(table, []))
    frame = _normalise_for_parquet(frame)
    frame.to_parquet(path, index=False)
    return path


def read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path).fillna("").to_dict("records")
    return pd.read_csv(path).fillna("").to_dict("records")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return path
