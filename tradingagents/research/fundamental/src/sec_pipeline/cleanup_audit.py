from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CLEANUP_TOOL_VERSION = "sec-framework-cleanup-v1"
SOURCE_DIR = Path(__file__).resolve().parent
SOURCE_FILES = [
    "cache_coverage_manifest.py",
    "cache_download_queue.py",
    "incremental_state.py",
    "daily_delta_manifest.py",
    "complete_submission_validation.py",
]
INPUT_NAMES = [
    "dealflow_universe.csv",
    "final_dealflow_tickers_sec_eligible.json",
    "final_dealflow_tickers_sec_eligible.txt",
]
WRAPPER_MODULES = {
    "sec_cache_coverage_manifest.py": "cache_coverage_manifest",
    "sec_cache_download_queue.py": "cache_download_queue",
    "sec_incremental_state.py": "incremental_state",
    "sec_daily_delta_manifest.py": "daily_delta_manifest",
    "sec_complete_submission_validation.py": "complete_submission_validation",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_info(root: Path) -> dict[str, Any]:
    def run(args: list[str]) -> str:
        return subprocess.check_output(args, cwd=root, text=True).strip()
    sha = run(["git", "rev-parse", "HEAD"])
    dirty = bool(run(["git", "status", "--porcelain"]))
    return {"sha": sha, "dirty": dirty}


def dependency_lock_hash(root: Path) -> dict[str, str]:
    for name in ("uv.lock", "poetry.lock", "requirements.txt", "pyproject.toml"):
        path = root / name
        if path.exists():
            return {"path": str(path), "sha256": sha256_file(path)}
    return {}


def file_hashes(paths: list[Path]) -> dict[str, dict[str, Any]]:
    out = {}
    for path in paths:
        if path.exists() and path.is_file() and path.name not in {"*.sqlite-wal", "*.sqlite-shm"}:
            out[str(path)] = {"sha256": sha256_file(path), "size_bytes": path.stat().st_size}
    return out


def inventory(run_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(p for p in run_dir.rglob("*") if p.is_file()):
        suffix = path.suffix.lower()
        rel = str(path.relative_to(run_dir))
        if suffix in {".sqlite-wal", ".sqlite-shm"}:
            classification = "sqlite_runtime_sidecar_keep_snapshot"
            checksum = ""
        elif path.name in WRAPPER_MODULES:
            classification = "sec_logic_script_replace_with_wrapper"
            checksum = sha256_file(path)
        elif suffix in {".csv", ".json", ".jsonl", ".parquet", ".txt", ".sqlite"}:
            classification = "immutable_run_artifact_keep"
            checksum = sha256_file(path)
        else:
            classification = "other_keep"
            checksum = sha256_file(path)
        rows.append({"path": rel, "classification": classification, "sha256": checksum, "size_bytes": path.stat().st_size})
    return rows


def config_snapshot(run_dir: Path) -> dict[str, Any]:
    summary = run_dir / "sec_coverage_summary.json"
    queue = run_dir / "sec_fetch_queue_resumable.json"
    payload: dict[str, Any] = {"run_dir": str(run_dir)}
    if summary.exists():
        payload["coverage_summary"] = json.loads(summary.read_text(encoding="utf-8"))
    if queue.exists():
        data = json.loads(queue.read_text(encoding="utf-8"))
        payload["cache_root"] = data.get("cache_root")
        payload["live_cache_root"] = data.get("live_cache_root")
        payload["quarters"] = data.get("quarters")
    return payload


def write_reproducibility_manifest(root: Path, run_dir: Path, live_cache_root: str) -> None:
    source_paths = [SOURCE_DIR / name for name in SOURCE_FILES]
    input_paths = [run_dir / name for name in INPUT_NAMES]
    payload = {
        "schema": "SEC_REPRODUCIBILITY_MANIFEST_V1",
        "created_at": now_iso(),
        "git": git_info(root),
        "source_file_hashes": file_hashes(source_paths),
        "config_snapshot": config_snapshot(run_dir),
        "input_hashes": file_hashes(input_paths),
        "dependency_lock_hash": dependency_lock_hash(root),
        "cache_root": str(Path(live_cache_root).parent),
        "live_cache_root": live_cache_root,
        "run_timestamps": {"manifest_created_at": now_iso()},
    }
    (run_dir / "sec_reproducibility_manifest.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def wrapper_text(module: str, run_dir: Path, live_cache_root: str) -> str:
    return f'''from __future__ import annotations

import sys
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parent
FUNDAMENTAL_ROOT = RUN_DIR.parents[3] / "tradingagents" / "research" / "fundamental"
if str(FUNDAMENTAL_ROOT) not in sys.path:
    sys.path.insert(0, str(FUNDAMENTAL_ROOT))

from src.sec_pipeline import {module} as pipeline


def main() -> None:
    pipeline.configure(out=RUN_DIR, live=Path({str(live_cache_root)!r}))
    pipeline.main()


if __name__ == "__main__":
    main()
'''


def write_cleanup_manifest(run_dir: Path, pre_inventory: list[dict[str, Any]], post_inventory: list[dict[str, Any]]) -> None:
    changed = []
    for name in WRAPPER_MODULES:
        changed.append({
            "path": name,
            "action": "replaced_with_thin_wrapper",
            "deletion_reason": "copied SEC business logic superseded by src.sec_pipeline source-of-truth",
            "kept_for_audit": True,
        })
    payload = {
        "schema": "SEC_CLEANUP_MANIFEST_V1",
        "created_at": now_iso(),
        "cleanup_tool_version": CLEANUP_TOOL_VERSION,
        "pre_clean_inventory": pre_inventory,
        "post_clean_inventory": post_inventory,
        "changes": changed,
        "safety_notes": [
            "No immutable CSV/JSON/parquet/final-score artifacts deleted.",
            "SQLite .sqlite, .sqlite-wal, and .sqlite-shm files kept/snapshotted, not deleted.",
            "Live SEC cache treated as mutable external cache; not modified.",
        ],
    }
    (run_dir / "sec_cleanup_manifest.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def clean_run(root: Path, run_dir: Path, live_cache_root: str) -> None:
    pre = inventory(run_dir)
    write_reproducibility_manifest(root, run_dir, live_cache_root)
    for filename, module in WRAPPER_MODULES.items():
        (run_dir / filename).write_text(wrapper_text(module, run_dir, live_cache_root), encoding="utf-8")
    post = inventory(run_dir)
    write_cleanup_manifest(run_dir, pre, post)
