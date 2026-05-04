"""Atomic JSON artifact IO helpers with file locking."""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - non-posix fallback
    fcntl = None  # type: ignore


class ControlIOError(RuntimeError):
    """Raised when atomic control artifact operations fail."""


def read_json_locked(path: Path, default_factory: Optional[Callable[[], Any]] = None) -> Any:
    """Read JSON under lock, returning default_factory() when file is missing/invalid."""
    default_value = default_factory() if default_factory else {}
    path = Path(path)
    lock_path = _lock_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with _exclusive_lock(lock_path):
        return _read_json_or_default(path, default_value)


def write_json_locked(path: Path, payload: Any) -> None:
    """Write JSON atomically while holding an exclusive lock."""
    path = Path(path)
    lock_path = _lock_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, indent=2)

    with _exclusive_lock(lock_path):
        _atomic_write_text(path, raw)


def update_json_locked(
    path: Path,
    updater: Callable[[Any], Any],
    default_factory: Optional[Callable[[], Any]] = None,
) -> Any:
    """Read-modify-write JSON atomically and return updater result."""
    default_value = default_factory() if default_factory else {}
    path = Path(path)
    lock_path = _lock_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with _exclusive_lock(lock_path):
        current = _read_json_or_default(path, default_value)
        updated = updater(current)
        _atomic_write_text(path, json.dumps(updated, indent=2))
        return updated


@contextmanager
def _exclusive_lock(lock_path: Path, timeout_seconds: float = 10.0):
    if fcntl is None:
        # Best-effort fallback for non-posix environments.
        lock_path.touch(exist_ok=True)
        yield None
        return

    lock_path.touch(exist_ok=True)
    with lock_path.open("a+") as handle:
        start = time.monotonic()
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if (time.monotonic() - start) >= float(timeout_seconds):
                    raise ControlIOError(f"Timed out acquiring lock: {lock_path}")
                time.sleep(0.01)
        try:
            yield handle
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _lock_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".lock")


def _read_json_or_default(path: Path, default_value: Any) -> Any:
    if not path.exists():
        return default_value
    try:
        return json.loads(path.read_text())
    except Exception:
        return default_value


def _atomic_write_text(path: Path, raw_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = None
    tmp_path = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=path.name + ".tmp.",
            dir=str(path.parent),
            text=True,
        )
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "w") as handle:
            fd = None
            handle.write(raw_text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(tmp_path), str(path))
    finally:
        if fd is not None:
            os.close(fd)
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
