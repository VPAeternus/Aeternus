from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Sequence


_TICKER_RE = re.compile(r"\b[A-Z]{1,5}\b")
_WORD_RE = re.compile(r"[a-z]{3,}")
_STOPWORDS = {"the", "and", "with", "from", "should", "what", "does", "this", "that", "into", "need", "have"}
_GENERIC_SUMMARIES = {
    "Cross-scout event compiled from daily discovery evidence.",
    "Single-source event compiled from daily discovery evidence.",
}


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _extract_tickers(question: str) -> List[str]:
    return sorted({token for token in _TICKER_RE.findall(str(question or "")) if token not in {"WHAT", "WITH", "SHOULD", "TRUMP"}})


def _recommended_gap_fill(missing_inputs: Sequence[str]) -> List[str]:
    recommendations: List[str] = []
    text = " ".join(str(item) for item in missing_inputs).lower()
    if "macro" in text:
        recommendations.append("manual_grok_macro_update")
    if "social" in text or "market reaction" in text or "event" in text:
        recommendations.append("manual_event_specific_x_feed_pass")
    if "filing" in text or "sec" in text:
        recommendations.append("manual_sec_excerpt_upload")
    if "portfolio" in text:
        recommendations.append("manual_portfolio_context_confirm")
    if not recommendations:
        recommendations.append("manual_context_upload")
    return recommendations


def _keyword_tokens(text: str) -> set[str]:
    return {token for token in _WORD_RE.findall(str(text or "").lower()) if token not in _STOPWORDS}


def _coerce_universe_symbols(universe_filter: Dict[str, Any]) -> set[str]:
    if isinstance(universe_filter.get("symbols"), list):
        return {str(symbol).upper().strip() for symbol in universe_filter.get("symbols", []) if str(symbol).strip()}
    if isinstance(universe_filter.get("kept_symbols"), list):
        return {str(symbol).upper().strip() for symbol in universe_filter.get("kept_symbols", []) if str(symbol).strip()}
    if isinstance(universe_filter.get("universe"), list):
        return {
            str(row.get("symbol", "")).upper().strip()
            for row in universe_filter.get("universe", [])
            if str(row.get("symbol", "")).strip()
        }
    return set()


def _is_broad_daily_query(question: str, question_tickers: set[str]) -> bool:
    if question_tickers:
        return False
    lowered = str(question or "").lower()
    return any(phrase in lowered for phrase in ("most important", "today", "daily scenario", "daily scenarios", "top scenario", "top scenarios"))


def _importance_score(card: Dict[str, Any], coverage: Dict[str, Any]) -> float:
    relevance_map = {"high": 0.3, "medium": 0.2, "low": 0.1, "none": 0.0}
    return (
        float(card.get("confidence", 0.0) or 0.0)
        + float(coverage.get("coverage_score", 0.0) or 0.0)
        + min(0.3, 0.05 * len(list(card.get("source_bundle", []) or [])))
        + min(0.2, 0.03 * len(list(card.get("direct_entities", []) or [])))
        + relevance_map.get(str(card.get("portfolio_relevance", "none")).lower(), 0.0)
    )


def _searchable_card_tokens(card: Dict[str, Any]) -> set[str]:
    summary = str(card.get("summary", "")).strip()
    text_parts = [str(card.get("title", "")), str(card.get("event_type", ""))]
    if summary and summary not in _GENERIC_SUMMARIES:
        text_parts.append(summary)
    return _keyword_tokens(" ".join(text_parts))


def _dedupe_by_entity(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for row in rows:
        key = (str(row.get("entity", "")).upper().strip(), str(row.get("direction", "")).strip(), str(row.get("reason", "")).strip())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def retrieve_scenario_context(
    *,
    question: str,
    as_of_date: str,
    base_dir: Path | str = Path("eval_results") / "deal_flow",
    event_card_id: str | None = None,
    ticker_scope: Sequence[str] | None = None,
    portfolio_scope: bool = False,
) -> Dict[str, Any]:
    root = Path(base_dir) / as_of_date
    event_cards = list(_load_json(root / "event_cards.json", []))
    coverage_rows = {
        str(row.get("event_card_id", "")): row
        for row in list((_load_json(root / "coverage_precheck.json", {}) or {}).get("rows", []) or [])
    }
    universe_filter = dict(_load_json(root / "universe_filter.json", {}))
    universe_symbols = _coerce_universe_symbols(universe_filter)
    question_lower = str(question or "").lower()
    question_tickers = set(_extract_tickers(question))
    if ticker_scope:
        question_tickers |= {str(symbol).upper().strip() for symbol in ticker_scope if str(symbol).strip()}

    matched_cards: List[Dict[str, Any]] = []
    if event_card_id:
        matched_cards = [card for card in event_cards if str(card.get("event_card_id", "")) == event_card_id]
    elif _is_broad_daily_query(question, question_tickers):
        ranked = sorted(
            event_cards,
            key=lambda card: _importance_score(card, coverage_rows.get(str(card.get("event_card_id", "")), {})),
            reverse=True,
        )
        matched_cards = ranked[: min(5, len(ranked))]
    else:
        question_keywords = _keyword_tokens(question_lower)
        for card in event_cards:
            card_entities = {
                str(entity.get("entity_id", "")).upper().strip()
                for entity in list(card.get("direct_entities", []) or []) + list(card.get("second_order_entities", []) or [])
                if str(entity.get("entity_id", "")).strip()
            }
            if question_tickers & card_entities:
                matched_cards.append(card)
                continue
            searchable_tokens = _searchable_card_tokens(card)
            if searchable_tokens & question_keywords:
                matched_cards.append(card)

    matched_event_ids = [str(card.get("event_card_id", "")) for card in matched_cards]
    matched_entities = sorted({
        str(entity.get("entity_id", "")).upper().strip()
        for card in matched_cards
        for entity in list(card.get("direct_entities", []) or []) + list(card.get("second_order_entities", []) or [])
        if str(entity.get("entity_id", "")).strip()
    } | question_tickers | (question_tickers & universe_symbols))

    direct_impacts: List[Dict[str, Any]] = []
    second_order_candidates: List[Dict[str, Any]] = []
    portfolio_impacts: List[Dict[str, Any]] = []
    hedge_candidates: List[Dict[str, Any]] = []
    missing_inputs: List[str] = []
    statuses: List[str] = []

    for card in matched_cards:
        coverage = coverage_rows.get(str(card.get("event_card_id", "")), {})
        if coverage.get("coverage_status"):
            statuses.append(str(coverage.get("coverage_status")))
        missing_inputs.extend(list(coverage.get("missing_dimensions", []) or []))
        missing_inputs.extend(list(card.get("missing_dimensions", []) or []))

        for entity in list(card.get("direct_entities", []) or []):
            entity_id = str(entity.get("entity_id", "")).upper().strip()
            if not entity_id:
                continue
            direct_impacts.append(
                {
                    "entity": entity_id,
                    "direction": str((card.get("expected_direction") or {}).get(entity_id, "unknown")),
                    "reason": str(card.get("summary", "")),
                }
            )

        for entity in list(card.get("second_order_entities", []) or []):
            entity_id = str(entity.get("entity_id", "")).upper().strip()
            if not entity_id:
                continue
            second_order_candidates.append(
                {
                    "entity": entity_id,
                    "direction": str((card.get("expected_direction") or {}).get(entity_id, "unknown")),
                    "reason": str(card.get("summary", "")),
                }
            )

        for held in list(card.get("matched_holdings", []) or []):
            portfolio_impacts.append(
                {
                    "entity": str(held).upper().strip(),
                    "holding_status": "held",
                    "impact": "beneficiary" if (card.get("expected_direction") or {}).get(str(held).upper().strip()) == "up" else "watch",
                }
            )

        channels = set(str(channel) for channel in card.get("channels", []) or [])
        if "risk_off" in channels or "volatility" in channels or "oil" in channels:
            hedge_candidates.append(
                {
                    "entity": "SPY",
                    "direction": "hedge",
                    "reason": "Broad risk proxy for event-driven drawdown protection",
                }
            )

    if not matched_cards:
        coverage_status = "MISSING"
        missing_inputs = ["internal event coverage", "relevant scenario evidence"]
    elif any(status == "PARTIAL" for status in statuses):
        coverage_status = "PARTIAL"
    elif statuses and all(status == "COMPLETE" for status in statuses):
        coverage_status = "COMPLETE"
    else:
        coverage_status = "PARTIAL"

    missing_inputs = sorted({str(item).strip() for item in missing_inputs if str(item).strip()})
    if coverage_status == "COMPLETE":
        wait_for_user = False
    else:
        wait_for_user = True

    return {
        "question": question,
        "coverage_status": coverage_status,
        "matched_event_cards": matched_event_ids,
        "matched_entities": matched_entities,
        "direct_impacts": _dedupe_by_entity(direct_impacts),
        "second_order_candidates": _dedupe_by_entity(second_order_candidates),
        "portfolio_impacts": portfolio_impacts if portfolio_scope else portfolio_impacts,
        "hedge_candidates": _dedupe_by_entity(hedge_candidates),
        "missing_inputs": missing_inputs,
        "recommended_manual_gap_fill": _recommended_gap_fill(missing_inputs),
        "wait_for_user": wait_for_user,
    }
