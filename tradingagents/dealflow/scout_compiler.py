from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from .scenario_contracts import REQUIRED_EVENT_CARD_FIELDS


_TICKER_RE = re.compile(r"\$([A-Z]{1,5})\b")


def _dedupe_preserve(values: Iterable[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _normalize_symbol(symbol: Any) -> str:
    return str(symbol or "").upper().strip()


def _extract_mentioned_tickers(text: str) -> List[str]:
    return sorted({_normalize_symbol(match) for match in _TICKER_RE.findall(str(text or "")) if _normalize_symbol(match)})


def _event_type_for(source: str, text: str, pass_type: str = "") -> str:
    lower = str(text or "").lower()
    src = str(source or "").strip()
    source_pass_type = str(pass_type or "").strip()
    if any(token in lower for token in ("iran", "opec", "hormuz", "oil", "war on iran")):
        return "geopolitical_supply_shock"
    if any(token in lower for token in ("leading indicator", "ai compute", "capacity", "supplier", "deployment")):
        return "leading_indicator_signal"
    if any(token in lower for token in (" ai ", "ai memory", "chip", "factory", "fab", "semiconductor", "memory demand")):
        return "leading_indicator_signal"
    if any(token in lower for token in ("redemption", "liquidity", "private credit", "withdrawal", "fund exits", "bcred")):
        return "credit_stress_signal"
    if any(token in lower for token in ("fda", "approval", "cber", "trial", "accelerated approval")):
        return "biotech_regulatory_shock"
    if any(token in lower for token in ("uranium", "nuclear", "reactor", "smr")):
        return "nuclear_theme_signal"
    if source_pass_type == "options_flow" or any(
        token in lower for token in ("unusual options", "options volume", "call volume", "call sweep", "options flow", "sweep")
    ):
        return "options_flow_signal"
    if any(token in lower for token in ("fda", "sec", "tariff", "regulation", "regulatory", "policy")):
        return "policy_regulatory_shock"
    if src == "breakout_scanner":
        return "breakout_cluster"
    if src == "technical_ignition":
        return "technical_ignition"
    if src == "earnings_options":
        return "earnings_options_setup"
    if src == "insider_cluster":
        return "insider_accumulation"
    if src in {"fvg_recall", "fma_recall"}:
        return "technical_recall_signal"
    return "cross_scout_narrative"


def _group_key(record: Dict[str, Any]) -> str:
    event_type = str(record.get("event_type", "")).strip()
    text = str(record.get("text", "")).lower()
    source = str(record.get("source", "")).strip()
    if event_type == "geopolitical_supply_shock":
        if any(token in text for token in ("defense", "air defense", "lmt", "rtx", "noc")):
            return "geopolitical_supply_shock:defense_cluster"
        if any(token in text for token in ("iran", "oil", "hormuz", "opec")):
            return "geopolitical_supply_shock:oil_cluster"
    if event_type == "leading_indicator_signal":
        if "ai" in text or "compute" in text:
            return "leading_indicator_signal:ai_compute"
        return "leading_indicator_signal:capacity_cluster"
    if event_type == "credit_stress_signal":
        return "credit_stress_signal:private_credit_cluster"
    if event_type == "biotech_regulatory_shock":
        return "biotech_regulatory_shock:biotech_cluster"
    if event_type == "nuclear_theme_signal":
        return "nuclear_theme_signal:nuclear_cluster"
    if event_type == "options_flow_signal":
        return "options_flow_signal:unusual_options_cluster"
    if event_type == "breakout_cluster":
        return "breakout_cluster:daily"
    if event_type == "technical_recall_signal":
        return f"{source}:daily"
    if event_type == "technical_ignition":
        return "technical_ignition:daily"
    if event_type == "earnings_options_setup":
        return "earnings_options_setup:daily"
    if event_type == "insider_accumulation":
        return "insider_accumulation:daily"
    symbol = _normalize_symbol(record.get("symbol"))
    return f"{event_type}:{symbol or 'generic'}"


def _channels_for(record: Dict[str, Any]) -> List[str]:
    source = str(record.get("source", "")).strip()
    text = str(record.get("text", "")).lower()
    channels: List[str] = []
    if source == "technical_ignition":
        channels.append("technical_momentum")
    if source == "breakout_scanner":
        channels.extend(["technical_momentum", "breakout"])
    if source == "earnings_options":
        channels.extend(["technical_momentum", "ai_capex"] if "ai" in text else ["technical_momentum"])
    if source == "insider_cluster":
        channels.append("insider_signal")
    if any(token in text for token in ("iran", "oil", "opec", "hormuz")):
        channels.extend(["oil", "risk_off"])
    if any(token in text for token in ("defense", "lockheed", "rtx", "war")):
        channels.append("defense")
    if any(token in text for token in ("redemption", "liquidity", "private credit", "withdrawal", "fund exits", "bcred")):
        channels.append("credit_stress")
    if any(token in text for token in ("uranium", "nuclear", "reactor", "smr")):
        channels.append("nuclear")
    if any(token in text for token in ("fda", "approval", "trial", "cber")):
        channels.append("biotech_regulatory")
    if any(token in text for token in ("unusual options", "options volume", "call volume", "call sweep", "options flow", "sweep")):
        channels.append("options_flow")
    if any(token in text for token in ("supplier", "leading indicator", "ai compute", "capacity")):
        channels.extend(["supply_chain", "ai_capex"])
    if any(token in text for token in (" ai ", "ai memory", "chip", "factory", "fab", "semiconductor", "memory demand")):
        channels.append("ai_capex")
    if not channels and source in {"fvg_recall", "fma_recall", "breakout_scanner"}:
        channels.append("technical_momentum")
    return _dedupe_preserve(channels)


def _direction_to_word(direction: str) -> str:
    norm = str(direction or "").upper().strip()
    if norm == "BULLISH":
        return "up"
    if norm == "BEARISH":
        return "down"
    if norm == "NEUTRAL":
        return "mixed"
    return "unknown"


def _urgency_for(event_type: str) -> str:
    if event_type in {"technical_ignition", "earnings_options_setup", "geopolitical_supply_shock"}:
        return "immediate"
    if event_type in {"policy_regulatory_shock", "insider_accumulation"}:
        return "near_term"
    return "developing"


def _horizon_for(event_type: str) -> str:
    if event_type in {"technical_ignition", "earnings_options_setup", "geopolitical_supply_shock"}:
        return "1d_to_5d"
    if event_type in {"leading_indicator_signal", "supply_chain_signal"}:
        return "5d_to_20d"
    return "20d_plus"


def _required_dimensions_for(event_type: str) -> List[str]:
    mapping = {
        "geopolitical_supply_shock": ["social", "macro", "commodity", "portfolio"],
        "policy_regulatory_shock": ["social", "macro", "portfolio"],
        "earnings_options_setup": ["social", "technical", "portfolio"],
        "technical_ignition": ["technical", "social"],
        "breakout_cluster": ["technical", "social"],
        "technical_recall_signal": ["technical", "portfolio"],
        "insider_accumulation": ["insider", "portfolio"],
        "leading_indicator_signal": ["filing", "supply_chain", "portfolio"],
        "credit_stress_signal": ["social", "macro", "portfolio"],
        "biotech_regulatory_shock": ["social", "filing", "portfolio"],
        "nuclear_theme_signal": ["social", "macro", "portfolio"],
        "options_flow_signal": ["social", "technical", "portfolio"],
    }
    return list(mapping.get(event_type, ["social"]))


def _dimension_map_for_sources(sources: Sequence[str], channels: Sequence[str], macro_cache: Dict[str, Any] | None) -> List[str]:
    dims: List[str] = []
    source_map = {
        "x_feed": "social",
        "technical_ignition": "technical",
        "fvg_recall": "technical",
        "fma_recall": "technical",
        "breakout_scanner": "technical",
        "earnings_options": "social",
        "insider_cluster": "insider",
    }
    for source in sources:
        mapped = source_map.get(source)
        if mapped:
            dims.append(mapped)
    if any(channel in {"oil", "defense"} for channel in channels):
        dims.append("commodity")
    if any(channel in {"supply_chain", "ai_capex"} for channel in channels):
        dims.append("supply_chain")
    if macro_cache:
        dims.append("macro")
    return _dedupe_preserve(dims)


def _portfolio_relevance(holdings: Sequence[str], direct_ids: Sequence[str], universe_symbols: Sequence[str]) -> str:
    holding_set = {_normalize_symbol(symbol) for symbol in holdings}
    direct_set = {_normalize_symbol(symbol) for symbol in direct_ids}
    universe_set = {_normalize_symbol(symbol) for symbol in universe_symbols}
    if holding_set & direct_set:
        return "high"
    if universe_set & direct_set:
        return "medium"
    if direct_set:
        return "low"
    return "none"


def _confidence_for(sources: Sequence[str], direct_count: int, second_order_count: int) -> float:
    value = 0.35 + min(0.3, 0.1 * len(set(sources))) + min(0.2, 0.1 * direct_count) - min(0.1, 0.05 * second_order_count)
    return round(max(0.0, min(0.95, value)), 2)


def _coerce_universe_symbols(universe_filter: Dict[str, Any] | None) -> List[str]:
    payload = dict(universe_filter or {})
    if isinstance(payload.get("symbols"), list):
        return [_normalize_symbol(symbol) for symbol in payload.get("symbols", []) if _normalize_symbol(symbol)]
    if isinstance(payload.get("kept_symbols"), list):
        return [_normalize_symbol(symbol) for symbol in payload.get("kept_symbols", []) if _normalize_symbol(symbol)]
    if isinstance(payload.get("universe"), list):
        return [_normalize_symbol(row.get("symbol")) for row in payload.get("universe", []) if _normalize_symbol(row.get("symbol"))]
    return []


def _build_input_records(
    *,
    scout_audit: Dict[str, Any] | None,
    discovery_delta: Dict[str, Any] | None,
    x_feed_merged: Dict[str, Any] | None,
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []

    for symbol, row in dict(x_feed_merged or {}).items():
        ticker = _normalize_symbol(symbol or (row or {}).get("ticker"))
        text = str((row or {}).get("catalyst") or "")
        if ticker:
            records.append(
                {
                    "symbol": ticker,
                    "source": "x_feed",
                    "direction": str((row or {}).get("sentiment") or "NEUTRAL").upper(),
                    "text": text,
                    "pass_type": str((row or {}).get("source_pass_type") or "").strip(),
                }
            )

    for signal in list((scout_audit or {}).get("signals", []) or []):
        symbol = _normalize_symbol(signal.get("symbol") or signal.get("ticker"))
        if symbol:
            records.append(
                {
                    "symbol": symbol,
                    "source": str(signal.get("source") or "").strip(),
                    "direction": str(signal.get("direction") or "NEUTRAL").upper(),
                    "text": str(signal.get("catalyst") or " ".join(signal.get("tags", []) or [])),
                    "pass_type": "",
                }
            )

    for alert in list(((scout_audit or {}).get("breakout") or {}).get("alerts", []) or []):
        symbol = _normalize_symbol(alert.get("ticker"))
        if symbol:
            records.append(
                {
                    "symbol": symbol,
                    "source": "breakout_scanner",
                    "direction": "BULLISH",
                    "text": "breakout discovery",
                    "pass_type": "",
                }
            )

    for cluster in list(((scout_audit or {}).get("insider") or {}).get("buy_clusters", []) or []):
        symbol = _normalize_symbol(cluster.get("ticker"))
        if symbol:
            records.append(
                {
                    "symbol": symbol,
                    "source": "insider_cluster",
                    "direction": "BULLISH",
                    "text": "insider accumulation",
                    "pass_type": "",
                }
            )

    for cluster in list(((scout_audit or {}).get("insider") or {}).get("sell_clusters", []) or []):
        symbol = _normalize_symbol(cluster.get("ticker"))
        if symbol:
            records.append(
                {
                    "symbol": symbol,
                    "source": "insider_cluster",
                    "direction": "BEARISH",
                    "text": "insider distribution",
                    "pass_type": "",
                }
            )

    for signal in list((discovery_delta or {}).get("signals", []) or []):
        symbol = _normalize_symbol(signal.get("symbol"))
        source = str(signal.get("source") or "").strip()
        if symbol and source in {"fvg_recall", "fma_recall"}:
            records.append(
                {
                    "symbol": symbol,
                    "source": source,
                    "direction": str(signal.get("direction") or "BULLISH").upper(),
                    "text": " ".join(signal.get("tags", []) or []),
                    "pass_type": "",
                }
            )

    for record in records:
        record["event_type"] = _event_type_for(
            record.get("source", ""),
            record.get("text", ""),
            record.get("pass_type", ""),
        )
        record["channels"] = _channels_for(record)
        record["group_key"] = _group_key(record)

    return records


def compile_scout_events(
    *,
    as_of_date: str,
    scout_audit: Dict[str, Any] | None,
    discovery_delta: Dict[str, Any] | None,
    universe_filter: Dict[str, Any] | None,
    x_feed_merged: Dict[str, Any] | None = None,
    macro_cache: Dict[str, Any] | None = None,
    holdings: Sequence[str] | None = None,
) -> Dict[str, Any]:
    holdings = list(holdings or [])
    universe_symbols = _coerce_universe_symbols(universe_filter)
    records = _build_input_records(
        scout_audit=scout_audit,
        discovery_delta=discovery_delta,
        x_feed_merged=x_feed_merged,
    )
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(record["group_key"], []).append(record)

    event_cards: List[Dict[str, Any]] = []
    debug = {
        "input_record_count": len(records),
        "group_count": len(grouped),
        "merge_decisions": [],
        "warnings": [],
    }

    for index, (group_key, rows) in enumerate(sorted(grouped.items()), start=1):
        sources = _dedupe_preserve(row.get("source", "") for row in rows)
        event_type = str(rows[0].get("event_type", "cross_scout_narrative")).strip()
        primary_rows = [row for row in rows if str(row.get("source", "")).strip() not in {"fvg_recall", "fma_recall"}]
        direct_ids = _dedupe_preserve(
            _normalize_symbol(row.get("symbol"))
            for row in (primary_rows or rows)
        )
        mentioned = _dedupe_preserve(
            ticker
            for row in rows
            for ticker in _extract_mentioned_tickers(str(row.get("text", "")))
            if ticker not in direct_ids
        )
        implied_ids = _dedupe_preserve(
            _normalize_symbol(row.get("symbol"))
            for row in rows
            if _normalize_symbol(row.get("symbol")) not in direct_ids
        )
        for symbol in implied_ids:
            if symbol not in mentioned:
                mentioned.append(symbol)
        direct_entities = [
            {"entity_type": "ticker", "entity_id": symbol, "label": symbol}
            for symbol in direct_ids
        ]
        second_order_entities = [
            {"entity_type": "ticker", "entity_id": symbol, "label": symbol}
            for symbol in mentioned
        ]
        channels = _dedupe_preserve(channel for row in rows for channel in row.get("channels", []) or [])
        expected_direction = {}
        for row in rows:
            symbol = _normalize_symbol(row.get("symbol"))
            if symbol and symbol not in expected_direction:
                expected_direction[symbol] = _direction_to_word(row.get("direction", ""))
        for symbol in mentioned:
            expected_direction.setdefault(symbol, "unknown")
        coverage_dimensions = _dimension_map_for_sources(sources, channels, macro_cache)
        required_dimensions = _required_dimensions_for(event_type)
        missing_dimensions = [dim for dim in required_dimensions if dim not in coverage_dimensions]
        portfolio_relevance = _portfolio_relevance(holdings, direct_ids, universe_symbols)
        matched_holdings = sorted({_normalize_symbol(symbol) for symbol in holdings if _normalize_symbol(symbol) in set(direct_ids)})
        matched_universe = sorted({_normalize_symbol(symbol) for symbol in direct_ids + mentioned if _normalize_symbol(symbol) in set(universe_symbols or direct_ids + mentioned)})
        if event_type == "cross_scout_narrative" and len(rows) < 2 and not channels:
            debug["merge_decisions"].append(
                {
                    "group_key": group_key,
                    "sources": sources,
                    "symbol_count": len(direct_entities),
                    "second_order_count": len(second_order_entities),
                    "skipped": True,
                    "reason": "generic_single_symbol",
                }
            )
            continue
        title_root = group_key.split(":", 1)[-1].replace("_", " ").strip() or direct_ids[0]
        title = f"{title_root.title()} scenario".strip()
        if event_type == "geopolitical_supply_shock":
            title = "Iran escalation drives oil cluster" if "oil_cluster" in group_key else "Defense bid / geopolitical escalation"
        elif event_type == "leading_indicator_signal":
            title = "AI infrastructure buildout cluster" if "ai_compute" in group_key else "Leading indicator cluster"
        elif event_type == "credit_stress_signal":
            title = "Private credit redemption stress"
        elif event_type == "biotech_regulatory_shock":
            title = "Biotech regulatory catalyst cluster"
        elif event_type == "nuclear_theme_signal":
            title = "Nuclear / uranium cluster"
        elif event_type == "options_flow_signal":
            title = "Unusual options flow cluster"
        elif event_type == "breakout_cluster":
            title = "Daily breakout cluster"
        elif event_type == "technical_recall_signal":
            title = "Technical recall cluster"
        elif event_type == "technical_ignition":
            title = "Technical ignition cluster" if len(direct_ids) > 1 else f"{direct_ids[0]} technical ignition"
        elif event_type == "earnings_options_setup":
            title = "Daily earnings/options setup" if len(direct_ids) > 1 else f"{direct_ids[0]} earnings/options setup"
        elif event_type == "insider_accumulation":
            title = "Insider accumulation cluster"
        summary = (
            f"Merged daily scenario across {', '.join(sources)}."
            if len(sources) >= 2
            else f"Daily scenario sourced from {sources[0]}."
        )
        card = {
            "event_card_id": f"evt_{as_of_date.replace('-', '_')}_{index:03d}",
            "date": as_of_date,
            "title": title,
            "event_type": event_type,
            "summary": summary,
            "source_bundle": sources,
            "source_records": [
                {
                    "source_family": row.get("source", ""),
                    "raw_symbol": _normalize_symbol(row.get("symbol")),
                    "catalyst_or_reason": str(row.get("text", "")),
                    "artifact_hint": "",
                }
                for row in rows
            ],
            "direct_entities": direct_entities,
            "second_order_entities": second_order_entities,
            "channels": channels,
            "expected_direction": expected_direction,
            "confidence": _confidence_for(sources, len(direct_entities), len(second_order_entities)),
            "urgency": _urgency_for(event_type),
            "time_horizon": _horizon_for(event_type),
            "portfolio_relevance": portfolio_relevance,
            "matched_holdings": matched_holdings,
            "matched_universe_symbols": matched_universe,
            "coverage_dimensions": coverage_dimensions,
            "missing_dimensions": missing_dimensions,
            "followup_questions": [
                "How does this affect current holdings?",
                "What second-order names matter most?",
            ],
        }
        if set(REQUIRED_EVENT_CARD_FIELDS).issubset(card.keys()):
            event_cards.append(card)
        debug["merge_decisions"].append(
            {
                "group_key": group_key,
                "sources": sources,
                "symbol_count": len(direct_entities),
                "second_order_count": len(second_order_entities),
            }
        )

    return {"event_cards": event_cards, "debug": debug}


def build_coverage_precheck(*, as_of_date: str, event_cards: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for card in event_cards:
        direct_count = len(list(card.get("direct_entities", []) or []))
        source_count = len(list(card.get("source_bundle", []) or []))
        channel_count = len(list(card.get("channels", []) or []))
        entity_resolution_score = min(1.0, direct_count / 2.0)
        source_diversity_score = min(1.0, source_count / 2.0)
        channel_confirmation_score = min(1.0, max(1, channel_count) / 2.0) if channel_count else 0.0
        relevance_map = {"high": 1.0, "medium": 0.75, "low": 0.5, "none": 0.0}
        portfolio_relevance_score = relevance_map.get(str(card.get("portfolio_relevance", "none")).lower(), 0.0)
        freshness_score = 1.0
        missing_dimensions = list(card.get("missing_dimensions", []) or [])
        coverage_score = round(
            (
                entity_resolution_score
                + source_diversity_score
                + channel_confirmation_score
                + portfolio_relevance_score
                + freshness_score
            )
            / 5.0,
            4,
        )
        if direct_count == 0 or source_count == 0:
            coverage_status = "MISSING"
        elif not missing_dimensions and coverage_score >= 0.6:
            coverage_status = "COMPLETE"
        else:
            coverage_status = "PARTIAL"
        rows.append(
            {
                "event_card_id": str(card.get("event_card_id", "")),
                "coverage_status": coverage_status,
                "coverage_score": coverage_score,
                "entity_resolution_score": round(entity_resolution_score, 4),
                "source_diversity_score": round(source_diversity_score, 4),
                "channel_confirmation_score": round(channel_confirmation_score, 4),
                "portfolio_relevance_score": round(portfolio_relevance_score, 4),
                "freshness_score": round(freshness_score, 4),
                "missing_dimensions": missing_dimensions,
                "ready_for_retrieval": coverage_status in {"COMPLETE", "PARTIAL"},
                "coverage_notes": [],
            }
        )
    summary = {
        "event_card_count": len(rows),
        "complete_count": sum(1 for row in rows if row["coverage_status"] == "COMPLETE"),
        "partial_count": sum(1 for row in rows if row["coverage_status"] == "PARTIAL"),
        "missing_count": sum(1 for row in rows if row["coverage_status"] == "MISSING"),
    }
    return {"date": as_of_date, "rows": rows, "summary": summary}


def build_akg_writeback_candidates(event_cards: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for card in event_cards:
        event_id = str(card.get("event_card_id", ""))
        summary = str(card.get("summary", ""))
        confidence = float(card.get("confidence", 0.0) or 0.0)
        candidates.append(
            {
                "candidate_id": f"{event_id}:summary",
                "candidate_type": "event_summary",
                "source_entity": str((card.get("direct_entities") or [{}])[0].get("entity_id", "")),
                "target_entity": "",
                "relationship": str(card.get("event_type", "")),
                "payload": {"summary": summary},
                "confidence": confidence,
                "evidence_event_cards": [event_id],
                "durability": "temporary" if confidence < 0.75 else "durable",
                "writeback_recommendation": "needs_review" if confidence >= 0.55 else "temporary_only",
            }
        )
        direct_ids = [entity.get("entity_id", "") for entity in list(card.get("direct_entities", []) or [])]
        for entity in list(card.get("second_order_entities", []) or []):
            target = str(entity.get("entity_id", "")).strip()
            if not target or not direct_ids:
                continue
            candidates.append(
                {
                    "candidate_id": f"{event_id}:{direct_ids[0]}:{target}",
                    "candidate_type": "edge",
                    "source_entity": direct_ids[0],
                    "target_entity": target,
                    "relationship": "scenario_related_to",
                    "payload": {"channels": list(card.get("channels", []) or [])},
                    "confidence": round(max(0.35, confidence - 0.2), 2),
                    "evidence_event_cards": [event_id],
                    "durability": "temporary",
                    "writeback_recommendation": "temporary_only" if confidence < 0.75 else "needs_review",
                }
            )
    return candidates


def persist_scout_compiler_artifacts(
    *,
    as_of_date: str,
    payload: Dict[str, Any],
    base_dir: Path | str = Path("eval_results") / "deal_flow",
) -> Dict[str, Any]:
    root = Path(base_dir) / as_of_date
    root.mkdir(parents=True, exist_ok=True)
    event_cards = list(payload.get("event_cards", []) or [])
    coverage_precheck = dict(payload.get("coverage_precheck", {}) or {})
    debug = dict(payload.get("debug", {}) or {})
    writeback = list(payload.get("akg_writeback_candidates", []) or [])
    (root / "event_cards.json").write_text(json.dumps(event_cards, indent=2))
    (root / "coverage_precheck.json").write_text(json.dumps(coverage_precheck, indent=2))
    (root / "scout_compiler_debug.json").write_text(json.dumps(debug, indent=2))
    (root / "akg_writeback_candidates.json").write_text(json.dumps(writeback, indent=2))
    return {
        "event_card_count": len(event_cards),
        "complete_count": int((coverage_precheck.get("summary") or {}).get("complete_count", 0) or 0),
        "partial_count": int((coverage_precheck.get("summary") or {}).get("partial_count", 0) or 0),
        "missing_count": int((coverage_precheck.get("summary") or {}).get("missing_count", 0) or 0),
        "writeback_candidate_count": len(writeback),
        "output_dir": str(root),
    }


def run_scout_compiler_sidecar(
    *,
    as_of_date: str,
    scout_audit: Dict[str, Any] | None,
    discovery_delta: Dict[str, Any] | None,
    universe_filter: Dict[str, Any] | None,
    x_feed_merged: Dict[str, Any] | None = None,
    macro_cache: Dict[str, Any] | None = None,
    holdings: Sequence[str] | None = None,
    base_dir: Path | str = Path("eval_results") / "deal_flow",
) -> Dict[str, Any]:
    compiled = compile_scout_events(
        as_of_date=as_of_date,
        scout_audit=scout_audit,
        discovery_delta=discovery_delta,
        universe_filter=universe_filter,
        x_feed_merged=x_feed_merged,
        macro_cache=macro_cache,
        holdings=holdings,
    )
    coverage_precheck = build_coverage_precheck(
        as_of_date=as_of_date,
        event_cards=compiled["event_cards"],
    )
    writeback_candidates = build_akg_writeback_candidates(compiled["event_cards"])
    payload = {
        "event_cards": compiled["event_cards"],
        "coverage_precheck": coverage_precheck,
        "debug": compiled["debug"],
        "akg_writeback_candidates": writeback_candidates,
    }
    summary = persist_scout_compiler_artifacts(
        as_of_date=as_of_date,
        payload=payload,
        base_dir=base_dir,
    )
    summary["coverage_precheck"] = coverage_precheck
    return summary
