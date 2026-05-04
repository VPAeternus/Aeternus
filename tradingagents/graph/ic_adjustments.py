"""IC adjustment file loader (extracted from scheduler)."""

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict


def load_ic_adjustments(filename: str, output_dir: str = "eval_results/control") -> Dict[str, Any]:
    """Load IC adjustment file. Returns empty dict if missing or expired."""
    path = Path(output_dir) / filename
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return {}
        expires_at = data.get("expires_at")
        if not expires_at:
            return {}
        # Parse expiry and check
        expiry = dt.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        now = dt.datetime.now(dt.timezone.utc)
        if now > expiry:
            return {}
        return data
    except Exception:
        return {}
