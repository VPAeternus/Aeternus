from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


_STAGE_ORDER = [
    "scouts",
    "event_cards",
    "universe_filter",
    "collect",
    "shortlist",
    "deep_selection",
]

_STAGE_ARTIFACTS = {
    "scouts": ["scout_audit.json", "discovery_delta.json"],
    "event_cards": ["event_cards.json", "coverage_precheck.json"],
    "universe_filter": ["universe_filter.json", "hypothesis_ledger/*/rows.json"],
    "collect": ["all_scored_candidates.json", "signals_raw.json", "hypothesis_ledger/*/rows.json"],
    "shortlist": ["shortlist_top20.json", "all_scored_candidates.json", "hypothesis_ledger/*/rows.json"],
    "deep_selection": ["research_queue.json", "hypothesis_ledger/*/rows.json"],
}


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _normalize_symbol(value: Any) -> str:
    return str(value or "").upper().strip()


def _coerce_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_event_card_symbols(card: Dict[str, Any]) -> Set[str]:
    symbols: Set[str] = set()
    entities = list(card.get("direct_entities", []) or []) + list(card.get("second_order_entities", []) or [])
    for entity in entities:
        symbol = _normalize_symbol(entity.get("entity_id"))
        if symbol:
            symbols.add(symbol)
    return symbols


def _extract_universe_symbols(universe_filter: Dict[str, Any]) -> Set[str]:
    if isinstance(universe_filter.get("symbols"), list):
        return {_normalize_symbol(symbol) for symbol in universe_filter.get("symbols", []) if _normalize_symbol(symbol)}
    if isinstance(universe_filter.get("kept_symbols"), list):
        return {_normalize_symbol(symbol) for symbol in universe_filter.get("kept_symbols", []) if _normalize_symbol(symbol)}
    if isinstance(universe_filter.get("universe"), list):
        return {
            _normalize_symbol(row.get("symbol"))
            for row in universe_filter.get("universe", [])
            if isinstance(row, dict) and _normalize_symbol(row.get("symbol"))
        }
    return set()


def _symbols_from_rows(rows: Iterable[Dict[str, Any]]) -> Set[str]:
    symbols: Set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = _normalize_symbol(row.get("symbol") or row.get("ticker"))
        if symbol:
            symbols.add(symbol)
    return symbols


def _contains_any(symbols: Set[str], values: Set[str]) -> bool:
    return bool(symbols & values)


def _load_artifacts(root: Path) -> Dict[str, Any]:
    return {
        "event_cards": list(_load_json(root / "event_cards.json", [])),
        "coverage_precheck": dict(_load_json(root / "coverage_precheck.json", {})),
        "universe_filter": dict(_load_json(root / "universe_filter.json", {})),
        "all_scored_candidates": list(_load_json(root / "all_scored_candidates.json", [])),
        "signals_raw": list(_load_json(root / "signals_raw.json", [])),
        "shortlist": dict(_load_json(root / "shortlist_top20.json", {})),
        "research_queue": dict(_load_json(root / "research_queue.json", {})),
        "scout_audit": dict(_load_json(root / "scout_audit.json", {})),
        "discovery_delta": dict(_load_json(root / "discovery_delta.json", {})),
    }


def _resolve_artifact_path(path_value: str, *, root: Path) -> Path:
    raw = str(path_value or "").strip()
    if not raw:
        return Path("")
    candidate = Path(raw)
    if candidate.is_absolute() and candidate.exists():
        return candidate
    if candidate.exists():
        return candidate
    cwd_candidate = Path.cwd() / candidate
    if cwd_candidate.exists():
        return cwd_candidate

    if candidate.parts and candidate.parts[0] == "eval_results":
        eval_results_dir: Optional[Path] = None
        cursor = root
        for parent in [cursor, *cursor.parents]:
            if parent.name == "eval_results":
                eval_results_dir = parent
                break
        if eval_results_dir is not None:
            parent_candidate = eval_results_dir.parent / candidate
            if parent_candidate.exists():
                return parent_candidate
    return candidate


def _load_snapshot_symbols(path: Path) -> Set[str]:
    if not path.exists():
        return set()
    payload = _load_json(path, [])
    if not isinstance(payload, list):
        return set()
    return {_normalize_symbol(value) for value in payload if _normalize_symbol(value)}


def _load_drop_metadata(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.exists():
        return {}
    payload = _load_json(path, {})
    if not isinstance(payload, dict):
        return {}
    normalized: Dict[str, Dict[str, Any]] = {}
    for raw_symbol, raw_row in payload.items():
        symbol = _normalize_symbol(raw_symbol)
        if not symbol or not isinstance(raw_row, dict):
            continue
        normalized[symbol] = dict(raw_row)
    return normalized


def _select_target_drop_metadata(
    *,
    drop_metadata: Dict[str, Dict[str, Any]],
    target_symbols: Set[str],
) -> Dict[str, Any]:
    for symbol in sorted(target_symbols):
        if symbol in drop_metadata:
            return dict(drop_metadata[symbol])
    return {}


def _collect_ledger_context(
    *,
    root: Path,
    target_symbols: Set[str],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    drops_by_stage: Dict[str, Dict[str, Any]] = {}
    stage_rules: Dict[str, Dict[str, Any]] = {}
    ledger_root = root / "hypothesis_ledger"
    if not ledger_root.is_dir():
        return drops_by_stage, stage_rules

    for lane_dir in ledger_root.iterdir():
        if not lane_dir.is_dir():
            continue
        rows = _load_json(lane_dir / "rows.json", [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            stage_id = str(row.get("stage_id") or "").strip()
            if not stage_id:
                continue
            if stage_id not in stage_rules:
                stage_rules[stage_id] = dict(row.get("rule_snapshot", {}) or {})

            dropped_path = _resolve_artifact_path(str(row.get("dropped_symbols_path") or ""), root=root)
            dropped_symbols = _load_snapshot_symbols(dropped_path)
            if not _contains_any(target_symbols, dropped_symbols):
                continue
            if stage_id in drops_by_stage:
                continue
            drop_metadata_path = _resolve_artifact_path(
                str(row.get("dropped_symbols_metadata_path") or ""),
                root=root,
            )
            drop_metadata = _select_target_drop_metadata(
                drop_metadata=_load_drop_metadata(drop_metadata_path),
                target_symbols=target_symbols,
            )
            drops_by_stage[stage_id] = {
                "stage_id": stage_id,
                "lane": str(row.get("lane") or lane_dir.name),
                "rule_snapshot": dict(row.get("rule_snapshot", {}) or {}),
                "kept_count": int(row.get("kept_count", 0) or 0),
                "dropped_count": int(row.get("dropped_count", 0) or 0),
                "drop_metadata": drop_metadata,
            }
    return drops_by_stage, stage_rules


def _score_rankings(rows: List[Dict[str, Any]]) -> Tuple[Dict[str, int], Dict[str, Dict[str, Optional[float]]]]:
    scored_rows: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = _normalize_symbol(row.get("symbol") or row.get("ticker"))
        if not symbol:
            continue
        status = str(row.get("status") or "").upper().strip()
        if status and status != "ACTIVE":
            continue
        scored_rows.append(
            {
                "symbol": symbol,
                "momentum_score": _coerce_float(row.get("momentum_score")),
                "core_score": _coerce_float(row.get("core_score")),
            }
        )

    scored_rows.sort(
        key=lambda row: (
            -(row.get("momentum_score") if row.get("momentum_score") is not None else -1e9),
            -(row.get("core_score") if row.get("core_score") is not None else -1e9),
            str(row.get("symbol") or ""),
        )
    )
    rank_by_symbol: Dict[str, int] = {}
    score_by_symbol: Dict[str, Dict[str, Optional[float]]] = {}
    for idx, row in enumerate(scored_rows, start=1):
        symbol = str(row["symbol"])
        rank_by_symbol[symbol] = idx
        score_by_symbol[symbol] = {
            "momentum_score": row.get("momentum_score"),
            "core_score": row.get("core_score"),
        }
    return rank_by_symbol, score_by_symbol


def _present_stage_row(stage: str, observed_value: Any = None) -> Dict[str, Any]:
    return {
        "stage": stage,
        "status": "FOUND",
        "reason_code": "PASSED",
        "reason_text": "Symbol is present at this stage.",
        "threshold": None,
        "observed_value": observed_value,
        "delta_to_pass": 0,
        "artifacts": list(_STAGE_ARTIFACTS.get(stage, [])),
    }


def _miss_stage_row(
    *,
    stage: str,
    reason_code: str,
    reason_text: str,
    threshold: Any,
    observed_value: Any,
    delta_to_pass: Any,
) -> Dict[str, Any]:
    return {
        "stage": stage,
        "status": "MISS",
        "reason_code": str(reason_code or "").strip(),
        "reason_text": str(reason_text or "").strip(),
        "threshold": threshold,
        "observed_value": observed_value,
        "delta_to_pass": delta_to_pass,
        "artifacts": list(_STAGE_ARTIFACTS.get(stage, [])),
    }


def _miss_stage_from_drop_metadata(
    *,
    stage: str,
    drop_context: Dict[str, Any],
    fallback_reason_code: str,
    fallback_reason_text: str,
    fallback_threshold: Any,
    fallback_observed_value: Any,
    fallback_delta_to_pass: Any,
) -> Dict[str, Any]:
    metadata = dict(drop_context.get("drop_metadata", {}) or {})
    reason_code = str(metadata.get("reason_code") or "").strip() or str(fallback_reason_code)
    reason_text = str(metadata.get("reason_text") or "").strip() or str(fallback_reason_text)
    threshold = metadata.get("threshold", fallback_threshold)
    observed_value = metadata.get("observed_value", fallback_observed_value)
    delta_to_pass = metadata.get("delta_to_pass", fallback_delta_to_pass)
    return _miss_stage_row(
        stage=stage,
        reason_code=reason_code,
        reason_text=reason_text,
        threshold=threshold,
        observed_value=observed_value,
        delta_to_pass=delta_to_pass,
    )


def run_investigation(
    *,
    investigation_packet: Dict[str, Any],
    as_of_date: str,
    base_dir: Path | str = Path("eval_results") / "deal_flow",
) -> Dict[str, Any]:
    root = Path(base_dir) / as_of_date
    artifacts = _load_artifacts(root)

    target_entities = {
        _normalize_symbol(symbol)
        for symbol in list(investigation_packet.get("target_entities", []) or [])
        if _normalize_symbol(symbol)
    }
    primary_symbol = next(iter(sorted(target_entities)), "")

    scout_symbols = _symbols_from_rows(list((artifacts.get("scout_audit") or {}).get("signals", []) or []))
    discovery_symbols = _symbols_from_rows(list((artifacts.get("discovery_delta") or {}).get("symbol_records", []) or []))
    scout_symbols |= discovery_symbols

    event_cards = list(artifacts.get("event_cards", []) or [])
    matched_event_cards = [
        str(card.get("event_card_id", ""))
        for card in event_cards
        if str(card.get("event_card_id", "")) and _contains_any(target_entities, _extract_event_card_symbols(card))
    ]

    event_card_symbols: Set[str] = set()
    for card in event_cards:
        event_card_symbols |= _extract_event_card_symbols(card)

    universe_symbols = _extract_universe_symbols(dict(artifacts.get("universe_filter", {})))
    collect_rows = list(artifacts.get("all_scored_candidates", []) or [])
    collect_symbols = _symbols_from_rows(collect_rows)
    shortlist_candidates = list((artifacts.get("shortlist") or {}).get("candidates", []) or [])
    shortlist_symbols = _symbols_from_rows(shortlist_candidates)
    queue_items = list((artifacts.get("research_queue") or {}).get("items", []) or [])
    queue_by_symbol = {
        _normalize_symbol(row.get("symbol") or row.get("ticker")): row
        for row in queue_items
        if isinstance(row, dict) and _normalize_symbol(row.get("symbol") or row.get("ticker"))
    }
    deep_symbols = _symbols_from_rows([row for row in queue_items if bool((row or {}).get("selected_for_deep"))])
    signals_raw = list(artifacts.get("signals_raw", []) or [])

    stage_presence = {
        "scouts": _contains_any(target_entities, scout_symbols),
        "event_cards": _contains_any(target_entities, event_card_symbols),
        "universe_filter": _contains_any(target_entities, universe_symbols),
        "collect": _contains_any(target_entities, collect_symbols),
        "shortlist": _contains_any(target_entities, shortlist_symbols),
        "deep_selection": _contains_any(target_entities, deep_symbols),
    }

    drops_by_stage, stage_rules = _collect_ledger_context(root=root, target_symbols=target_entities)
    rank_by_symbol, score_by_symbol = _score_rankings(collect_rows)
    shortlist_top_k = int((artifacts.get("shortlist") or {}).get("top_k", 0) or 0)
    if shortlist_top_k <= 0:
        shortlist_top_k = len(shortlist_candidates)

    signal_families_for_targets = {
        str(row.get("signal_family") or "").strip()
        for row in signals_raw
        if isinstance(row, dict) and _normalize_symbol(row.get("symbol") or row.get("ticker")) in target_entities
    }
    signal_families_for_targets.discard("")
    signal_family_count = len(signal_families_for_targets)
    evidence_threshold = _coerce_float((stage_rules.get("evidence_gate") or {}).get("min_signal_families"))

    stage_diagnosis: List[Dict[str, Any]] = []
    for stage in _STAGE_ORDER:
        if stage_presence.get(stage):
            if stage == "event_cards":
                stage_diagnosis.append(_present_stage_row(stage, observed_value={"matched_event_cards": matched_event_cards}))
            elif stage == "shortlist":
                symbol_rank = rank_by_symbol.get(primary_symbol)
                stage_diagnosis.append(
                    _present_stage_row(
                        stage,
                        observed_value={"rank": symbol_rank, "top_k": shortlist_top_k},
                    )
                )
            else:
                stage_diagnosis.append(_present_stage_row(stage))
            continue

        if stage == "scouts":
            stage_diagnosis.append(
                _miss_stage_row(
                    stage=stage,
                    reason_code="SCOUT_SIGNAL_ABSENT",
                    reason_text="Ticker is absent from scout_audit and discovery_delta scout outputs.",
                    threshold={"required_signals": 1},
                    observed_value={"scout_signal_count": 0},
                    delta_to_pass=1,
                )
            )
            continue

        if stage == "event_cards":
            matched_count = len(matched_event_cards)
            stage_diagnosis.append(
                _miss_stage_row(
                    stage=stage,
                    reason_code="EVENT_CARD_ABSENT",
                    reason_text="No Event Card contains the target ticker as a direct or second-order entity.",
                    threshold={"required_event_cards": 1},
                    observed_value={"matched_event_cards": matched_count},
                    delta_to_pass=max(0, 1 - matched_count),
                )
            )
            continue

        if stage == "universe_filter":
            universe_drop = drops_by_stage.get("universe_gate_edge") or drops_by_stage.get("universe_gate_haystack")
            if universe_drop:
                stage_diagnosis.append(
                    _miss_stage_from_drop_metadata(
                        stage=stage,
                        drop_context=universe_drop,
                        fallback_reason_code=f"{str(universe_drop.get('stage_id', 'universe_gate')).upper()}_DROPPED",
                        fallback_reason_text="Ticker is in a universe-gate dropped snapshot in hypothesis ledger.",
                        fallback_threshold=dict(universe_drop.get("rule_snapshot", {}) or {}),
                        fallback_observed_value={
                            "lane": str(universe_drop.get("lane", "")),
                            "dropped_count": int(universe_drop.get("dropped_count", 0) or 0),
                        },
                        fallback_delta_to_pass=1,
                    )
                )
            else:
                stage_diagnosis.append(
                    _miss_stage_row(
                        stage=stage,
                        reason_code="UNIVERSE_EXCLUDED",
                        reason_text="Ticker is not present in the filtered universe artifact.",
                        threshold=dict((artifacts.get("universe_filter") or {}).get("rule_snapshot", {}) or {}),
                        observed_value={"in_filtered_universe": False},
                        delta_to_pass=1,
                    )
                )
            continue

        if stage == "collect":
            evidence_drop = drops_by_stage.get("evidence_gate")
            if evidence_drop:
                stage_diagnosis.append(
                    _miss_stage_from_drop_metadata(
                        stage=stage,
                        drop_context=evidence_drop,
                        fallback_reason_code="EVIDENCE_GATE_DROPPED",
                        fallback_reason_text="Ticker was dropped by evidence_gate according to hypothesis ledger.",
                        fallback_threshold=dict(evidence_drop.get("rule_snapshot", {}) or {}),
                        fallback_observed_value={
                            "signal_family_count": signal_family_count,
                            "signal_families": sorted(signal_families_for_targets),
                        },
                        fallback_delta_to_pass=(
                            max(0.0, float(evidence_threshold) - float(signal_family_count))
                            if evidence_threshold is not None
                            else None
                        ),
                    )
                )
            else:
                stage_diagnosis.append(
                    _miss_stage_row(
                        stage=stage,
                        reason_code="NOT_SCORED",
                        reason_text="Ticker does not appear in all_scored_candidates for this cycle.",
                        threshold={"min_signal_families": evidence_threshold},
                        observed_value={
                            "signal_family_count": signal_family_count,
                            "signal_families": sorted(signal_families_for_targets),
                        },
                        delta_to_pass=(
                            max(0.0, float(evidence_threshold) - float(signal_family_count))
                            if evidence_threshold is not None
                            else None
                        ),
                    )
                )
            continue

        if stage == "shortlist":
            shortlist_drop = drops_by_stage.get("shortlist_cut")
            symbol_rank = rank_by_symbol.get(primary_symbol)
            symbol_scores = score_by_symbol.get(primary_symbol, {})
            if symbol_rank is not None and shortlist_top_k > 0:
                if symbol_rank <= shortlist_top_k:
                    reason_code = "SHORTLIST_EXCLUSION_ANOMALY"
                    reason_text = "Ticker ranked inside top_k by score but is absent from shortlist output."
                    delta_to_pass = 0
                else:
                    reason_code = "RANK_BELOW_SHORTLIST_CUT"
                    reason_text = "Ticker rank is below shortlist top_k cutoff."
                    delta_to_pass = int(symbol_rank - shortlist_top_k)
                stage_diagnosis.append(
                    _miss_stage_row(
                        stage=stage,
                        reason_code=reason_code,
                        reason_text=reason_text,
                        threshold={"top_k": shortlist_top_k},
                        observed_value={
                            "rank": symbol_rank,
                            "momentum_score": symbol_scores.get("momentum_score"),
                            "core_score": symbol_scores.get("core_score"),
                        },
                        delta_to_pass=delta_to_pass,
                    )
                )
            elif shortlist_drop:
                stage_diagnosis.append(
                    _miss_stage_from_drop_metadata(
                        stage=stage,
                        drop_context=shortlist_drop,
                        fallback_reason_code="SHORTLIST_CUT_DROPPED",
                        fallback_reason_text="Ticker is in shortlist_cut dropped snapshot in hypothesis ledger.",
                        fallback_threshold=dict(shortlist_drop.get("rule_snapshot", {}) or {}),
                        fallback_observed_value={"dropped_count": int(shortlist_drop.get("dropped_count", 0) or 0)},
                        fallback_delta_to_pass=1,
                    )
                )
            else:
                stage_diagnosis.append(
                    _miss_stage_row(
                        stage=stage,
                        reason_code="UPSTREAM_COLLECT_MISS",
                        reason_text="Ticker is missing from shortlist because it did not survive upstream scoring/evidence gates.",
                        threshold=None,
                        observed_value={"scored_presence": False},
                        delta_to_pass=None,
                    )
                )
            continue

        if stage == "deep_selection":
            deep_drop = drops_by_stage.get("deep_selection_cut")
            queue_row = queue_by_symbol.get(primary_symbol)
            if isinstance(queue_row, dict):
                stage_diagnosis.append(
                    _miss_stage_row(
                        stage=stage,
                        reason_code="DEEP_SELECTION_NOT_SELECTED",
                        reason_text="Ticker is in research queue but selected_for_deep is false.",
                        threshold={"selected_for_deep": True},
                        observed_value={
                            "selected_for_deep": bool(queue_row.get("selected_for_deep", False)),
                            "deal_flow_score": _coerce_float(queue_row.get("deal_flow_score")),
                            "lane": str(queue_row.get("lane") or ""),
                        },
                        delta_to_pass=1,
                    )
                )
            elif deep_drop:
                stage_diagnosis.append(
                    _miss_stage_from_drop_metadata(
                        stage=stage,
                        drop_context=deep_drop,
                        fallback_reason_code="DEEP_SELECTION_CUT_DROPPED",
                        fallback_reason_text="Ticker is in deep_selection_cut dropped snapshot in hypothesis ledger.",
                        fallback_threshold=dict(deep_drop.get("rule_snapshot", {}) or {}),
                        fallback_observed_value={"dropped_count": int(deep_drop.get("dropped_count", 0) or 0)},
                        fallback_delta_to_pass=1,
                    )
                )
            elif _contains_any(target_entities, shortlist_symbols):
                stage_diagnosis.append(
                    _miss_stage_row(
                        stage=stage,
                        reason_code="DEEP_SELECTION_QUEUE_ABSENT",
                        reason_text="Ticker reached shortlist but no queue row is present for deep selection.",
                        threshold={"queue_presence": True},
                        observed_value={"queue_presence": False},
                        delta_to_pass=1,
                    )
                )
            else:
                stage_diagnosis.append(
                    _miss_stage_row(
                        stage=stage,
                        reason_code="UPSTREAM_SHORTLIST_MISS",
                        reason_text="Ticker is missing from deep selection because it was cut earlier at shortlist.",
                        threshold=None,
                        observed_value={"shortlist_presence": False},
                        delta_to_pass=None,
                    )
                )
            continue

    first_miss_stage = next((row["stage"] for row in stage_diagnosis if row["status"] == "MISS"), None)
    evidence_found = [row["stage"] for row in stage_diagnosis if row["status"] == "FOUND"]
    evidence_missing = [row["stage"] for row in stage_diagnosis if row["status"] == "MISS"]

    return {
        "query_type": str(investigation_packet.get("query_type", "")).strip(),
        "intent": str(investigation_packet.get("intent", "")).strip(),
        "target_entities": sorted(target_entities),
        "as_of_date": str(as_of_date),
        "stage_diagnosis": stage_diagnosis,
        "first_miss_stage": first_miss_stage,
        "matched_event_cards": matched_event_cards,
        "evidence_found": evidence_found,
        "evidence_missing": evidence_missing,
    }
