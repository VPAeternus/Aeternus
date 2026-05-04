"""Manual watchlist storage and validation utilities for Deal Flow."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
import yfinance as yf

from .contracts import ManualIdea, ManualWatchlist
from tradingagents.context import get_company_context


WATCHLIST_PATH = Path("eval_results") / "deal_flow" / "manual_watchlist.json"


def load_watchlist(path: Path = WATCHLIST_PATH) -> ManualWatchlist:
    if not path.exists():
        return {
            "updated_at": _utc_now_iso(),
            "items": [],
        }

    try:
        payload = json.loads(path.read_text())
    except Exception:
        payload = {}

    raw_items = payload.get("items", []) if isinstance(payload, dict) else []
    items: List[ManualIdea] = []
    if isinstance(raw_items, list):
        for raw in raw_items:
            normalized = _normalize_idea(raw)
            if normalized:
                items.append(normalized)

    return {
        "updated_at": str(payload.get("updated_at") or _utc_now_iso()) if isinstance(payload, dict) else _utc_now_iso(),
        "items": items,
    }


def save_watchlist(data: ManualWatchlist, path: Path = WATCHLIST_PATH) -> None:
    payload = {
        "updated_at": _utc_now_iso(),
        "items": [dict(_normalize_idea(item) or item) for item in data.get("items", [])],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def list_ideas(include_inactive: bool = True, path: Path = WATCHLIST_PATH) -> List[ManualIdea]:
    watchlist = load_watchlist(path)
    ideas = watchlist.get("items", [])
    if include_inactive:
        return ideas
    return [item for item in ideas if bool(item.get("active", True))]


def list_active_ideas(as_of_date: str, path: Path = WATCHLIST_PATH) -> List[ManualIdea]:
    _ = as_of_date
    return list_ideas(include_inactive=False, path=path)


def add_idea(
    symbol: str,
    path: Path = WATCHLIST_PATH,
    context_provider: Optional[Callable[..., Dict[str, Any]]] = None,
) -> ManualIdea:
    normalized_symbol = _normalize_symbol(symbol)
    now = dt.datetime.now(dt.timezone.utc)

    idea: ManualIdea = {
        "symbol": normalized_symbol,
        "created_at": now.isoformat(),
        "active": True,
        "context_snapshot": _build_context_snapshot(normalized_symbol, context_provider=context_provider),
    }

    watchlist = load_watchlist(path)
    items = watchlist.get("items", [])
    replaced = False
    for idx, item in enumerate(items):
        if str(item.get("symbol", "")).upper().strip() == normalized_symbol:
            # Preserve original create timestamp when updating.
            idea["created_at"] = str(item.get("created_at") or idea["created_at"])
            items[idx] = idea
            replaced = True
            break

    if not replaced:
        items.append(idea)

    save_watchlist({"updated_at": _utc_now_iso(), "items": items}, path=path)
    return idea


def remove_idea(symbol: str, path: Path = WATCHLIST_PATH) -> bool:
    normalized_symbol = _normalize_symbol(symbol)
    watchlist = load_watchlist(path)
    items = watchlist.get("items", [])
    changed = False
    for item in items:
        if str(item.get("symbol", "")).upper().strip() == normalized_symbol:
            if bool(item.get("active", True)):
                item["active"] = False
                changed = True
    if changed:
        save_watchlist({"updated_at": _utc_now_iso(), "items": items}, path=path)
    return changed


def import_ideas(file_path: Path, ttl_days: int, path: Path = WATCHLIST_PATH) -> Tuple[int, int]:
    _ = ttl_days
    imported = 0
    skipped = 0
    for record in _parse_import_file(file_path):
        symbol = _normalize_symbol(record.get("symbol"))
        if not symbol:
            skipped += 1
            continue
        add_idea(
            symbol=symbol,
            path=path,
        )
        imported += 1
    return imported, skipped


def validate_symbol_liquidity(
    symbol: str,
    min_adv_usd: float,
) -> Tuple[bool, float]:
    target = _normalize_symbol(symbol)
    if not target:
        return False, 0.0

    try:
        frame = yf.download(
            target,
            period="3mo",
            interval="1d",
            auto_adjust=False,
            progress=False,
        )
    except Exception:
        return False, 0.0

    if frame is None or frame.empty:
        return False, 0.0

    try:
        if isinstance(frame.columns, pd.MultiIndex):
            close = frame[("Close", target)] if ("Close", target) in frame.columns else frame[(target, "Close")]
            volume = frame[("Volume", target)] if ("Volume", target) in frame.columns else frame[(target, "Volume")]
        else:
            close = frame["Close"]
            volume = frame["Volume"]
    except Exception:
        return False, 0.0

    close_series = pd.to_numeric(close, errors="coerce")
    volume_series = pd.to_numeric(volume, errors="coerce")
    data = pd.DataFrame({"close": close_series, "volume": volume_series}).dropna()
    if data.empty:
        return False, 0.0

    data["dollar_volume"] = data["close"] * data["volume"]
    adv = float(data["dollar_volume"].tail(60).mean())
    return adv >= float(min_adv_usd), adv


def _parse_import_file(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []

    try:
        payload = json.loads(path.read_text())
    except Exception:
        payload = None

    rows: List[Dict[str, Any]] = []
    if isinstance(payload, list):
        for row in payload:
            if isinstance(row, dict):
                rows.append(row)
        return rows

    if isinstance(payload, dict):
        raw_items = payload.get("items", [])
        if isinstance(raw_items, list):
            for row in raw_items:
                if isinstance(row, dict):
                    rows.append(row)
            return rows

    # Fallback line-based import:
    # SYMBOL
    for line in path.read_text().splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        parts = [part.strip() for part in raw.split(",")]
        symbol = _normalize_symbol(parts[0]) if parts else ""
        if not symbol:
            continue
        row = {"symbol": symbol}
        rows.append(row)
    return rows


def _normalize_symbol(raw: Any) -> str:
    symbol = str(raw or "").upper().strip()
    if symbol.startswith("$"):
        symbol = symbol[1:]
    symbol = symbol.replace(".", "-").replace("/", "-").replace("_", "-")
    return symbol


def _normalize_idea(raw: Any) -> Optional[ManualIdea]:
    if not isinstance(raw, dict):
        return None
    symbol = _normalize_symbol(raw.get("symbol"))
    if not symbol:
        return None
    created_at = str(raw.get("created_at") or _utc_now_iso())
    active = bool(raw.get("active", True))
    context_snapshot = _normalize_context_snapshot(raw.get("context_snapshot"))
    return {
        "symbol": symbol,
        "created_at": created_at,
        "active": active,
        "context_snapshot": context_snapshot,
    }


def _end_of_day_utc(as_of_date: str) -> dt.datetime:
    try:
        base = dt.datetime.strptime(as_of_date, "%Y-%m-%d")
    except ValueError:
        base = dt.datetime.now()
    return base.replace(tzinfo=dt.timezone.utc, hour=23, minute=59, second=59, microsecond=0)


def _parse_iso_dt(value: Any) -> Optional[dt.datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _build_context_snapshot(
    symbol: str,
    *,
    context_provider: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    provider = context_provider or get_company_context
    try:
        payload = provider(symbol)
    except Exception:
        payload = {}
    akg = payload.get("akg", {}) if isinstance(payload, dict) else {}
    node = akg.get("node", {}) if isinstance(akg, dict) else {}
    return {
        "akg_found": bool(akg.get("found")) if isinstance(akg, dict) else False,
        "display_name": akg.get("display_name") if isinstance(akg, dict) else None,
        "sector": akg.get("sector") if isinstance(akg, dict) else None,
        "asset_class": node.get("asset_class") if isinstance(node, dict) else None,
        "aeternus_score": akg.get("aeternus_score") if isinstance(akg, dict) else None,
        "last_scored_date": node.get("last_scored_date") if isinstance(node, dict) else None,
    }


def _normalize_context_snapshot(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {
            "akg_found": False,
            "display_name": None,
            "sector": None,
            "asset_class": None,
            "aeternus_score": None,
            "last_scored_date": None,
        }
    return {
        "akg_found": bool(raw.get("akg_found", False)),
        "display_name": str(raw.get("display_name") or "") or None,
        "sector": str(raw.get("sector") or "") or None,
        "asset_class": str(raw.get("asset_class") or "") or None,
        "aeternus_score": raw.get("aeternus_score"),
        "last_scored_date": str(raw.get("last_scored_date") or "") or None,
    }
