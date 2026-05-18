from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from tradingagents.research.fundamental.src.panel.schema import COMPLETE_PANEL_SCHEMA_VERSION


PIT_COLUMNS = (
    "pit_as_of",
    "pit_run_id",
    "pit_source_panel_csv",
    "pit_source_panel_sha256",
    "pit_official_latest",
)


def append_pit_master(
    *,
    panel_csv: Path,
    master_csv: Path,
    quarter: str,
    as_of: str,
    run_id: str,
    official_latest: bool = True,
) -> dict[str, Any]:
    """Append or replace one quarter snapshot into the point-in-time master CSV."""

    panel_csv = Path(panel_csv)
    master_csv = Path(master_csv)
    quarter = _clean_quarter(quarter)
    as_of = str(as_of).strip()
    run_id = str(run_id).strip()
    if not quarter:
        raise ValueError("quarter is required")
    if not as_of:
        raise ValueError("as_of is required")
    if not run_id:
        raise ValueError("run_id is required")

    _validate_canonical_panel(panel_csv)
    panel_rows, panel_columns = _read_csv(panel_csv)
    selected_rows = [row for row in panel_rows if _clean_quarter(row.get("quarter")) == quarter]
    if not selected_rows:
        raise ValueError(f"panel has no rows for quarter {quarter}")

    panel_hash = _sha256_file(panel_csv)
    new_rows = []
    for row in selected_rows:
        out = dict(row)
        out.update(
            {
                "pit_as_of": as_of,
                "pit_run_id": run_id,
                "pit_source_panel_csv": str(panel_csv),
                "pit_source_panel_sha256": panel_hash,
                "pit_official_latest": "1" if official_latest else "0",
            }
        )
        new_rows.append(out)

    existing_rows: list[dict[str, str]] = []
    existing_columns: list[str] = []
    if master_csv.exists():
        existing_rows, existing_columns = _read_csv(master_csv)

    keep_rows = []
    replaced_rows = 0
    for row in existing_rows:
        same_snapshot = (
            _clean_quarter(row.get("quarter")) == quarter
            and str(row.get("pit_as_of", "")).strip() == as_of
            and str(row.get("pit_run_id", "")).strip() == run_id
        )
        if same_snapshot:
            replaced_rows += 1
            continue
        if official_latest and _clean_quarter(row.get("quarter")) == quarter:
            row = dict(row)
            row["pit_official_latest"] = "0"
        keep_rows.append(row)

    all_rows = keep_rows + new_rows
    columns = _merge_columns(existing_columns, panel_columns, PIT_COLUMNS, all_rows)
    master_csv.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(master_csv, all_rows, columns)

    return {
        "master_csv": str(master_csv),
        "panel_csv": str(panel_csv),
        "quarter": quarter,
        "as_of": as_of,
        "run_id": run_id,
        "appended_rows": len(new_rows),
        "replaced_rows": replaced_rows,
        "rows_written": len(all_rows),
        "official_latest": official_latest,
        "sha256": _sha256_file(master_csv),
    }


def discover_complete_panel(run_root: Path, quarter: str) -> Path:
    """Find the canonical complete panel for a run root."""

    run_root = Path(run_root)
    quarter = _clean_quarter(quarter)
    candidates = [
        run_root / "complete_panel" / f"fundamental_complete_prellm_to_top15_{quarter}.csv",
        run_root / f"fundamental_complete_prellm_to_top15_{quarter}.csv",
        run_root / "final" / f"fundamental_complete_prellm_to_top15_{quarter}.csv",
    ]
    candidates.extend(sorted(run_root.glob(f"**/fundamental_complete_prellm_to_top15_{quarter}.csv")))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"complete panel not found for {quarter} under {run_root}")


def infer_run_id(run_root: Path | None, panel_csv: Path) -> str:
    if run_root is not None:
        run_root = Path(run_root)
        identity = run_root / "run_identity.json"
        if identity.is_file():
            try:
                data = json.loads(identity.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
            value = str(data.get("run_id") or "").strip()
            if value:
                return value
        return run_root.name
    parent = Path(panel_csv).parent
    if parent.name == "complete_panel" and parent.parent.name:
        return parent.parent.name
    return parent.name or Path(panel_csv).stem


def _validate_canonical_panel(panel_csv: Path) -> None:
    if not panel_csv.is_file():
        raise FileNotFoundError(f"panel CSV not found: {panel_csv}")
    lower_parts = {part.lower() for part in panel_csv.parts}
    if "growth" in lower_parts or panel_csv.name.lower().startswith("combined_all_tiers"):
        raise ValueError("legacy historical CSV is not a canonical PIT source")
    validation_path = panel_csv.with_name(f"{panel_csv.stem}_validation.json")
    manifest_path = panel_csv.with_name(f"{panel_csv.stem}_manifest.json")
    columns_path = panel_csv.with_name(f"{panel_csv.stem}_columns.json")
    for required in (validation_path, manifest_path, columns_path):
        if not required.is_file():
            raise ValueError(f"canonical sidecar missing: {required}")
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    if validation.get("passed") is not True:
        raise ValueError(f"complete panel validation did not pass: {validation_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") not in {"fundamental_complete_panel_v1", COMPLETE_PANEL_SCHEMA_VERSION}:
        raise ValueError(f"complete panel manifest schema mismatch: {manifest_path}")
    expected_hash = str(manifest.get("output_sha256") or "").strip()
    actual_hash = _sha256_file(panel_csv)
    if not expected_hash:
        raise ValueError(f"complete panel manifest missing output_sha256: {manifest_path}")
    if expected_hash != actual_hash:
        raise ValueError(f"complete panel CSV hash does not match manifest: {panel_csv}")


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [{key: value for key, value in row.items()} for row in reader], list(reader.fieldnames or [])


def _write_csv(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _merge_columns(
    existing_columns: list[str],
    panel_columns: list[str],
    pit_columns: tuple[str, ...],
    rows: list[dict[str, str]],
) -> list[str]:
    out: list[str] = []
    for source in (existing_columns, panel_columns, list(pit_columns)):
        for column in source:
            if column and column not in out:
                out.append(column)
    for row in rows:
        for column in row:
            if column not in out:
                out.append(column)
    return out


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clean_quarter(value: Any) -> str:
    return str(value or "").strip().upper()
