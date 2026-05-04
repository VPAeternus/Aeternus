import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid


class RatingAuditLog:
    """
    Immutable audit log for all rating events.

    Storage format: NDJSON (newline-delimited JSON). Each line is one JSON
    object. A `prev_hash` field on each entry contains the SHA-256 hash of
    the previous raw line, enabling tamper detection via verify_chain().

    Backward compatibility: if the file contains a JSON array on first
    append, it is migrated to NDJSON in-place.
    """

    _GENESIS_HASH = "0" * 64  # sentinel for the first entry

    def __init__(self, path: str = "eval_results/audit_log.ndjson"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Do not create the file here; _append handles first-write.

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_event(self, event_type: str, rating_id: str, data: Dict[str, Any]) -> None:
        """Append a hash-chained event to the audit trail.

        Args:
            event_type: 'RATING_CREATED', 'RATING_UPDATED', 'TRADE_CLOSED'
            rating_id: The UUID of the rating being affected
            data: The payload (snapshot of the rating or update details)
        """
        event = {
            "event_id": str(uuid.uuid4()),
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "rating_id": rating_id,
            "data": data,
        }
        self._append(event)

    def get_rating_history(self, rating_id: str) -> List[Dict[str, Any]]:
        """Return full event history for a specific rating ID."""
        return [e for e in self._load() if e.get("rating_id") == rating_id]

    def get_all_events(self) -> List[Dict[str, Any]]:
        """Return all events from the audit log."""
        return self._load()

    def verify_chain(self) -> Dict[str, Any]:
        """Verify the SHA-256 hash chain of the audit log.

        Returns:
            {
                "valid": bool,
                "entries": int,
                "first_break_at": int | None  # 1-based line number, None if intact
            }
        """
        if not self.path.exists():
            return {"valid": True, "entries": 0, "first_break_at": None}

        lines = [l for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]
        if not lines:
            return {"valid": True, "entries": 0, "first_break_at": None}

        prev_hash = self._GENESIS_HASH
        for idx, raw_line in enumerate(lines, start=1):
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                return {"valid": False, "entries": idx - 1, "first_break_at": idx}

            recorded_prev = entry.get("prev_hash")
            if recorded_prev != prev_hash:
                return {"valid": False, "entries": idx - 1, "first_break_at": idx}

            prev_hash = hashlib.sha256(raw_line.encode("utf-8")).hexdigest()

        return {"valid": True, "entries": len(lines), "first_break_at": None}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> List[Dict[str, Any]]:
        """Load all entries; handles both NDJSON and legacy JSON-array files."""
        if not self.path.exists():
            # Also check the legacy .json path for backward compat reads.
            legacy = self.path.with_suffix(".json")
            if legacy.exists():
                try:
                    data = json.loads(legacy.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        return data
                except Exception:
                    pass
            return []

        raw = self.path.read_text(encoding="utf-8").strip()
        if not raw:
            return []

        # Detect legacy JSON array format.
        if raw.startswith("["):
            try:
                return json.loads(raw)
            except Exception:
                return []

        results = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return results

    def _last_line_hash(self) -> str:
        """Return SHA-256 of the last raw line in the file, or genesis hash."""
        if not self.path.exists() or self.path.stat().st_size == 0:
            return self._GENESIS_HASH

        # Read last non-empty line efficiently.
        last_line: Optional[str] = None
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                last_line = line
        if last_line is None:
            return self._GENESIS_HASH
        return hashlib.sha256(last_line.encode("utf-8")).hexdigest()

    def _migrate_if_needed(self) -> None:
        """Migrate a legacy JSON-array file to NDJSON in-place."""
        if not self.path.exists():
            return
        raw = self.path.read_text(encoding="utf-8").strip()
        if not raw.startswith("["):
            return  # already NDJSON

        try:
            entries: List[Dict[str, Any]] = json.loads(raw)
        except Exception:
            return  # malformed; leave alone

        if not isinstance(entries, list):
            return

        # Rewrite as NDJSON with hash chaining.
        prev_hash = self._GENESIS_HASH
        lines = []
        for entry in entries:
            entry["prev_hash"] = prev_hash
            raw_line = json.dumps(entry, separators=(",", ":"), ensure_ascii=False)
            lines.append(raw_line)
            prev_hash = hashlib.sha256(raw_line.encode("utf-8")).hexdigest()

        self.path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    def _append(self, event: Dict[str, Any]) -> None:
        """Append one event to the NDJSON file with hash chaining."""
        self._migrate_if_needed()

        prev_hash = self._last_line_hash()
        event["prev_hash"] = prev_hash
        raw_line = json.dumps(event, separators=(",", ":"), ensure_ascii=False)

        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(raw_line + "\n")
