"""Social/news signal extraction — manual X-feed merged artifact only."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional

from ..contracts import DealFlowSignal, UniverseRow


def collect_social_news_signals(
    universe: Iterable[UniverseRow],
    as_of_date: str,
    max_symbol_calls: int = 35,
    config: Optional[Dict[str, Any]] = None,
) -> List[DealFlowSignal]:
    _ = config

    sorted_universe = sorted(universe, key=lambda row: row.get("liquidity_score", 0.0), reverse=True)
    symbols = [row["symbol"] for row in sorted_universe[:max_symbol_calls]]

    merged_data = _load_manual_x_feed(as_of_date)

    # Manual merged artifact reads are free, so extend coverage to any universe symbol
    # present in the merged set even if it fell outside the top-K liquidity slice.
    if merged_data:
        universe_symbols = {row["symbol"] for row in sorted_universe}
        symbol_set = set(symbols)
        for merged_symbol in merged_data:
            if merged_symbol in universe_symbols and merged_symbol not in symbol_set:
                symbols.append(merged_symbol)
                symbol_set.add(merged_symbol)

    signals: List[DealFlowSignal] = []
    for symbol in symbols:
        merged_hit = merged_data.get(symbol)
        if not merged_hit:
            for family in ("social_momentum", "news_catalyst"):
                signals.append(
                    {
                        "symbol": symbol,
                        "signal_family": family,
                        "raw_score": 0.0,
                        "z_score": 0.0,
                        "direction": "NEUTRAL",
                        "evidence_count": 0,
                        "freshness_hours": 24.0,
                        "source_status": "NO_DATA",
                        "source_name": "manual_x_feed",
                    }
                )
            continue

        sentiment = _coerce_float(merged_hit.get("sentiment"), default=0.0, lo=-1.0, hi=1.0)
        mentions = _coerce_int(merged_hit.get("mentions_estimate"), default=1, lo=1)
        velocity_trend = str(merged_hit.get("velocity_trend", "stable") or "stable").strip().lower()
        catalyst = str(merged_hit.get("catalyst", "") or "").strip() or None

        velocity_bonus = {"rising": 5.0, "stable": 0.0, "falling": -5.0}.get(velocity_trend, 0.0)
        mention_bonus = min(15.0, float(mentions) * 3.0)

        social_raw = _clamp(50.0 + 30.0 * sentiment + mention_bonus + velocity_bonus)
        catalyst_bonus = 8.0 if catalyst else 0.0
        news_raw = _clamp(40.0 + 20.0 * abs(sentiment) + mention_bonus + velocity_bonus + catalyst_bonus)

        for family, raw_score in (
            ("social_momentum", social_raw),
            ("news_catalyst", news_raw),
        ):
            signals.append(
                {
                    "symbol": symbol,
                    "signal_family": family,
                    "raw_score": float(raw_score),
                    "z_score": 0.0,
                    "direction": _direction_from_score(raw_score),
                    "evidence_count": mentions,
                    "freshness_hours": 24.0,
                    "source_status": "OK",
                    "source_name": "manual_x_feed",
                }
            )

    return signals


def _load_manual_x_feed(as_of_date: str) -> Dict[str, Dict[str, Any]]:
    try:
        from .x_feed_manual import load_merged

        payload = load_merged(as_of_date)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _coerce_float(raw: Any, *, default: float, lo: float, hi: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


def _coerce_int(raw: Any, *, default: int, lo: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, value)


def _clamp(score: float) -> float:
    return max(0.0, min(100.0, float(score)))


def _extract_json_payload(content: str) -> Any:
    """Extract a JSON object from an LLM response string."""
    raw = str(content or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(raw[start : end + 1])
        except Exception:
            return None
    return None


def _direction_from_score(score: float) -> str:
    if score >= 60.0:
        return "BULLISH"
    if score <= 40.0:
        return "BEARISH"
    return "NEUTRAL"
