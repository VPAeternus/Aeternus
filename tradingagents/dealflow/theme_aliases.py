"""Config-driven theme aliases that feed AKG/theme detection without replacing existing hard-coded themes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

import yaml

DEFAULT_THEME_ALIASES_PATH = Path("config/theme_aliases.yaml")


def load_theme_aliases(path: Path | str = DEFAULT_THEME_ALIASES_PATH) -> Dict[str, Dict[str, Any]]:
    src = Path(path)
    if not src.exists():
        return {}
    payload = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
    themes = payload.get("themes", {})
    return dict(themes or {}) if isinstance(themes, dict) else {}


def match_theme_aliases(text: str, aliases: Dict[str, Dict[str, Any]] | None = None) -> List[Dict[str, Any]]:
    clean = str(text or "").lower()
    if not clean:
        return []
    aliases = aliases if aliases is not None else load_theme_aliases()
    matches: List[Dict[str, Any]] = []
    for theme_id, info in aliases.items():
        matched = []
        for alias in list(info.get("aliases", []) or []):
            pattern = re.escape(str(alias).lower())
            if re.search(pattern, clean):
                matched.append(str(alias))
        if matched:
            matches.append({
                "theme_id": str(theme_id),
                "theme_name": str(info.get("theme_name") or theme_id),
                "matched_aliases": matched,
                "theme_roles": list(info.get("theme_roles", []) or []),
                "theme_example_tickers": list(info.get("theme_example_tickers", []) or []),
                "theme_edge_types": list(info.get("theme_edge_types", []) or []),
            })
    return matches
