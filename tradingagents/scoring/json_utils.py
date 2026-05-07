"""JSON parsing helpers for scoring modules."""

from __future__ import annotations

import json
from typing import Any, Dict


def safe_parse_json(text: str) -> Dict[str, Any]:
    if not text:
        return {}

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}

    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
