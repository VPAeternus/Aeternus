from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tradingagents.dealflow.control_io import read_json_locked, update_json_locked, write_json_locked


def test_write_and_read_json_locked_roundtrip(tmp_path: Path):
    path = tmp_path / "control" / "state.json"
    payload = {"value": 7, "items": ["a", "b"]}
    write_json_locked(path, payload)
    loaded = read_json_locked(path, default_factory=dict)
    assert loaded == payload


def test_update_json_locked_is_safe_under_parallel_updates(tmp_path: Path):
    path = tmp_path / "control" / "counter.json"
    write_json_locked(path, {"count": 0})

    def _bump():
        def _update(payload):
            current = dict(payload or {})
            current["count"] = int(current.get("count", 0)) + 1
            return current

        update_json_locked(path, _update, default_factory=lambda: {"count": 0})

    workers = 12
    loops = 25
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for _ in range(workers * loops):
            pool.submit(_bump)

    result = read_json_locked(path, default_factory=dict)
    assert result["count"] == workers * loops
