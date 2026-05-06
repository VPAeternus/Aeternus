"""Collect-stage hypothesis ledger row construction."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from tradingagents.dealflow.hypothesis_ledger import append_ledger_row, make_ledger_row


def write_collect_ledger_rows(
    *,
    base_dir: Path | str,
    as_of_date: str,
    shortlist: Dict[str, Any],
    all_scored_candidates: List[Dict[str, Any]],
    universe_ledger: Dict[str, Any],
    min_signal_families: int,
    min_evidence_count: int,
    universe_tier_map: Optional[Dict[str, Any]] = None,
    core_quota: int = 18,
    momentum_quota: int = 12,
) -> List[Dict[str, Any]]:
    """Build and append collect-stage shared hypothesis ledger rows in pipeline order."""
    base = Path(base_dir)
    rows: List[Dict[str, Any]] = []

    for stage_id, dropped_symbols in (
        ("universe_gate_edge", list(universe_ledger.get("candidate_drop_symbols", []))),
        ("universe_gate_haystack", list(universe_ledger.get("haystack_drop_symbols", []))),
    ):
        row = make_ledger_row(
            run_id=str(shortlist.get("run_id", "")),
            source_date=as_of_date,
            lane="shared",
            stage_id=stage_id,
            rule_snapshot=dict(universe_ledger.get("rule_snapshot", {})),
            kept_symbols=list(universe_ledger.get("kept_symbols", [])),
            dropped_symbols=dropped_symbols,
            base_dir=base,
            drop_metadata_by_symbol=build_universe_drop_metadata(
                stage_id=stage_id,
                dropped_symbols=dropped_symbols,
                universe_ledger=universe_ledger,
                universe_tier_map=universe_tier_map or {},
            ),
        )
        append_ledger_row(base_dir=base, lane="shared", row=row)
        rows.append(row)

    active_symbols = [
        _normalize_symbol(candidate.get("symbol", ""))
        for candidate in all_scored_candidates
        if str(candidate.get("status", "ACTIVE")).upper() == "ACTIVE" and _normalize_symbol(candidate.get("symbol", ""))
    ]
    low_data_symbols = [
        _normalize_symbol(candidate.get("symbol", ""))
        for candidate in all_scored_candidates
        if str(candidate.get("status", "")).upper() == "LOW_DATA" and _normalize_symbol(candidate.get("symbol", ""))
    ]
    evidence_row = make_ledger_row(
        run_id=str(shortlist.get("run_id", "")),
        source_date=as_of_date,
        lane="shared",
        stage_id="evidence_gate",
        rule_snapshot={"min_signal_families": int(min_signal_families), "min_evidence_count": int(min_evidence_count)},
        kept_symbols=active_symbols,
        dropped_symbols=low_data_symbols,
        base_dir=base,
        drop_metadata_by_symbol=build_evidence_gate_drop_metadata(
            all_scored_candidates=all_scored_candidates,
            min_signal_families=min_signal_families,
            min_evidence_count=min_evidence_count,
        ),
    )
    append_ledger_row(base_dir=base, lane="shared", row=evidence_row)
    rows.append(evidence_row)

    shortlisted_symbols = {_normalize_symbol(candidate.get("symbol", "")) for candidate in shortlist.get("candidates", []) if _normalize_symbol(candidate.get("symbol", ""))}
    dropped_symbols = [
        _normalize_symbol(candidate.get("symbol", ""))
        for candidate in all_scored_candidates
        if _normalize_symbol(candidate.get("symbol", "")) and _normalize_symbol(candidate.get("symbol", "")) not in shortlisted_symbols
    ]
    shortlist_rule_snapshot = {
        "top_k": int(shortlist.get("top_k", 0) or 0),
        "core_quota": int(core_quota),
        "momentum_quota": int(momentum_quota),
        "manual_merge_summary": dict(shortlist.get("manual_merge_summary", {})),
    }
    shortlist_row = make_ledger_row(
        run_id=str(shortlist.get("run_id", "")),
        source_date=as_of_date,
        lane="shared",
        stage_id="shortlist_cut",
        rule_snapshot=shortlist_rule_snapshot,
        kept_symbols=[_normalize_symbol(candidate.get("symbol", "")) for candidate in shortlist.get("candidates", [])],
        dropped_symbols=dropped_symbols,
        base_dir=base,
        drop_metadata_by_symbol=build_shortlist_drop_metadata(
            all_scored_candidates=all_scored_candidates,
            dropped_symbols=dropped_symbols,
            top_k=int(shortlist.get("top_k", 0) or 0),
            rule_snapshot=shortlist_rule_snapshot,
        ),
    )
    append_ledger_row(base_dir=base, lane="shared", row=shortlist_row)
    rows.append(shortlist_row)
    return rows


def build_universe_drop_metadata(*, stage_id: str, dropped_symbols: List[str], universe_ledger: Dict[str, Any], universe_tier_map: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    metadata: Dict[str, Dict[str, Any]] = {}
    rule_snapshot = dict(universe_ledger.get("rule_snapshot", {}))
    for symbol in _universe_symbols(dropped_symbols):
        in_tier_map = symbol in universe_tier_map
        tier_label = str(universe_tier_map.get(symbol, "")).strip() or None
        if stage_id == "universe_gate_haystack":
            reason_code = "UNIVERSE_TIER_PRESENT_BUT_EXCLUDED" if in_tier_map else "UNIVERSE_NOT_IN_ACTIVE_TIERS"
            reason_text = "Symbol mapped to a universe tier but still absent from filtered universe." if in_tier_map else "Symbol was not mapped into any active universe tier in this cycle."
        else:
            reason_code = "UNIVERSE_CANDIDATE_GATE_EXCLUDED"
            reason_text = "Symbol failed universe candidate gate and did not enter the filtered universe."
        metadata[symbol] = {
            "reason_code": reason_code,
            "reason_text": reason_text,
            "threshold": dict(rule_snapshot),
            "observed_value": {"in_filtered_universe": False, "in_tier_map": bool(in_tier_map), "tier": tier_label},
            "delta_to_pass": 1,
        }
    return metadata


def build_evidence_gate_drop_metadata(*, all_scored_candidates: List[Dict[str, Any]], min_signal_families: int, min_evidence_count: int) -> Dict[str, Dict[str, Any]]:
    metadata: Dict[str, Dict[str, Any]] = {}
    for candidate in all_scored_candidates:
        symbol = _normalize_symbol(candidate.get("symbol", ""))
        if not symbol or str(candidate.get("status", "")).upper().strip() != "LOW_DATA":
            continue
        active_families = _countish(candidate.get("active_families", 0))
        evidence_count = _countish(candidate.get("evidence_count", 0))
        family_gap = max(0, int(min_signal_families) - active_families)
        evidence_gap = max(0, int(min_evidence_count) - evidence_count)
        if family_gap > 0 and evidence_gap > 0:
            reason_code = "EVIDENCE_GATE_FAMILIES_AND_COUNT_BELOW_MIN"
            reason_text = "Signal-family coverage and evidence count were both below gate minimums."
            delta_to_pass: Any = {"signal_families": family_gap, "evidence_count": evidence_gap}
        elif family_gap > 0:
            reason_code = "EVIDENCE_GATE_SIGNAL_FAMILIES_BELOW_MIN"
            reason_text = "Signal-family coverage was below minimum."
            delta_to_pass = family_gap
        else:
            reason_code = "EVIDENCE_GATE_EVIDENCE_COUNT_BELOW_MIN"
            reason_text = "Evidence count was below minimum."
            delta_to_pass = evidence_gap
        metadata[symbol] = {
            "reason_code": reason_code,
            "reason_text": reason_text,
            "threshold": {"min_signal_families": int(min_signal_families), "min_evidence_count": int(min_evidence_count)},
            "observed_value": {"active_families": active_families, "evidence_count": evidence_count, "status": "LOW_DATA"},
            "delta_to_pass": delta_to_pass,
        }
    return metadata


def build_shortlist_drop_metadata(*, all_scored_candidates: List[Dict[str, Any]], dropped_symbols: List[str], top_k: int, rule_snapshot: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    metadata: Dict[str, Dict[str, Any]] = {}
    dropped_set = set(_universe_symbols(dropped_symbols))
    candidate_map: Dict[str, Dict[str, Any]] = {}
    active_rows: List[Dict[str, Any]] = []
    for candidate in all_scored_candidates:
        symbol = _normalize_symbol(candidate.get("symbol", ""))
        if not symbol:
            continue
        candidate_map[symbol] = dict(candidate)
        if str(candidate.get("status", "")).upper().strip() == "ACTIVE":
            active_rows.append({"symbol": symbol, "momentum_score": _coerce_float(candidate.get("momentum_score")), "core_score": _coerce_float(candidate.get("core_score")), "lane": str(candidate.get("lane", "")).upper().strip()})
    active_rows.sort(key=lambda row: (-(row["momentum_score"] if row["momentum_score"] is not None else -1e9), -(row["core_score"] if row["core_score"] is not None else -1e9), str(row["symbol"])))
    rank_by_symbol = {row["symbol"]: idx for idx, row in enumerate(active_rows, start=1)}
    for symbol in dropped_set:
        candidate = dict(candidate_map.get(symbol, {}))
        status = str(candidate.get("status", "")).upper().strip()
        momentum_score = _coerce_float(candidate.get("momentum_score"))
        core_score = _coerce_float(candidate.get("core_score"))
        lane = str(candidate.get("lane", "")).upper().strip()
        rank = rank_by_symbol.get(symbol)
        if status and status != "ACTIVE":
            reason_code = "UPSTREAM_EVIDENCE_GATE_LOW_DATA"
            reason_text = "Symbol did not meet evidence gate and remained in LOW_DATA state."
            threshold = {"required_status": "ACTIVE"}
            observed_value = {"status": status, "active_families": _countish(candidate.get("active_families", 0)), "evidence_count": _countish(candidate.get("evidence_count", 0))}
            delta_to_pass = 1
        elif rank is not None and int(top_k) > 0 and rank > int(top_k):
            reason_code = "RANK_BELOW_SHORTLIST_CUT"
            reason_text = "Active rank was below shortlist top_k cutoff."
            threshold = {"top_k": int(top_k)}
            observed_value = {"rank": int(rank), "momentum_score": momentum_score, "core_score": core_score, "lane": lane}
            delta_to_pass = int(rank) - int(top_k)
        elif rank is not None:
            reason_code = "SHORTLIST_POLICY_EXCLUSION"
            reason_text = "Rank was competitive but shortlist policy/quotas excluded the symbol."
            threshold = dict(rule_snapshot)
            observed_value = {"rank": int(rank), "momentum_score": momentum_score, "core_score": core_score, "lane": lane}
            delta_to_pass = 1
        else:
            reason_code = "SHORTLIST_INPUT_MISSING"
            reason_text = "Symbol was absent from active ranking inputs at shortlist stage."
            threshold = dict(rule_snapshot)
            observed_value = {"status": status or None}
            delta_to_pass = 1
        metadata[symbol] = {"reason_code": reason_code, "reason_text": reason_text, "threshold": threshold, "observed_value": observed_value, "delta_to_pass": delta_to_pass}
    return metadata


def _normalize_symbol(raw: Any) -> str:
    return str(raw or "").upper().strip()


def _universe_symbols(symbols: List[str]) -> List[str]:
    return [_normalize_symbol(symbol) for symbol in symbols if _normalize_symbol(symbol)]


def _countish(raw: Any) -> int:
    if isinstance(raw, (list, tuple, set)):
        return len(raw)
    try:
        return int(raw or 0)
    except Exception:
        return 0


def _coerce_float(raw: Any) -> Optional[float]:
    try:
        if raw in {None, ""}:
            return None
        return float(raw)
    except Exception:
        return None
