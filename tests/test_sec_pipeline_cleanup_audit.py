from __future__ import annotations

import ast
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEC_SRC = ROOT / "tradingagents/research/fundamental/src/sec_pipeline"
RUN_DIRS = [
    ROOT / "eval_results/fundamental/2026-05-07_full",
    ROOT / "eval_results/fundamental/2026-05-08_xfeed_sec_test",
]
SEC_WRAPPERS = {
    "sec_cache_coverage_manifest.py",
    "sec_cache_download_queue.py",
    "sec_incremental_state.py",
    "sec_daily_delta_manifest.py",
    "sec_complete_submission_validation.py",
}
FORBIDDEN_WRAPPER_IMPORTS = {"urllib", "requests", "sqlite3", "gzip", "csv"}
FORBIDDEN_WRAPPER_NAMES = {"urlopen", "Request", "ThreadPoolExecutor", "sqlite3", "csv"}


def test_sec_pipeline_source_modules_compile() -> None:
    for path in SEC_SRC.glob("*.py"):
        py_compile.compile(str(path), doraise=True)


def test_run_sec_scripts_are_thin_wrappers() -> None:
    for run_dir in RUN_DIRS:
        for path in run_dir.glob("sec_*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            assert len(path.read_text(encoding="utf-8").splitlines()) <= 25, path
            imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
            imports |= {str(node.module).split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
            assert not (imports & FORBIDDEN_WRAPPER_IMPORTS), path
            names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
            assert not (names & FORBIDDEN_WRAPPER_NAMES), path
            assert "src.sec_pipeline" in path.read_text(encoding="utf-8")
            assert "configure(out=RUN_DIR" in path.read_text(encoding="utf-8")


def test_no_copied_sec_logic_in_eval_results() -> None:
    for run_dir in RUN_DIRS:
        assert {p.name for p in run_dir.glob("sec_*.py")} == SEC_WRAPPERS
        for path in run_dir.glob("sec_*.py"):
            text = path.read_text(encoding="utf-8")
            forbidden = ["urlopen(", "ThreadPoolExecutor", "sqlite3.connect", "csv.DictReader", "parse_complete_submission"]
            assert not any(token in text for token in forbidden), path


def test_cleanup_and_repro_manifests_present_and_current() -> None:
    for run_dir in RUN_DIRS:
        cleanup = run_dir / "sec_cleanup_manifest.json"
        repro = run_dir / "sec_reproducibility_manifest.json"
        assert cleanup.exists()
        assert repro.exists()
        cleanup_text = cleanup.read_text(encoding="utf-8")
        repro_text = repro.read_text(encoding="utf-8")
        assert "SEC_CLEANUP_MANIFEST_V1" in cleanup_text
        assert "SEC_REPRODUCIBILITY_MANIFEST_V1" in repro_text
        assert "replaced_with_thin_wrapper" in cleanup_text
        assert "cache_coverage_manifest.py" in repro_text


def test_generated_sqlite_sidecars_excluded_from_source_checks() -> None:
    source_names = {p.name for p in SEC_SRC.glob("*.py")}
    assert not any(name.endswith((".sqlite-wal", ".sqlite-shm")) for name in source_names)
    for run_dir in RUN_DIRS:
        cleanup = (run_dir / "sec_cleanup_manifest.json").read_text(encoding="utf-8")
        assert "sqlite_runtime_sidecar_keep_snapshot" in cleanup
