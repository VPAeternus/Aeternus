"""Research queue construction helpers for DealFlowPipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from tradingagents.dealflow.hypothesis_ledger import append_ledger_row, make_ledger_row
from tradingagents.dealflow.themes import select_research_playbook, why_now_text

_SKIP_DEEP_ANALYSIS = frozenset({"QQQ", "TQQQ", "SQQQ", "SPY", "VOO", "IVV", "IWM", "DIA", "VTI", "SPXL", "SPXS", "UPRO", "SH", "SSO"})


def build_research_queue(
    *,
    shortlist: Dict[str, Any],
    config: Dict[str, Any],
    ledger_base_dir: Optional[Path] = None,
    triage_score_fn: Callable[[Dict[str, Any]], float] | None = None,
    thesis_tags_fn: Callable[[Dict[str, Any]], List[str]] | None = None,
    normalize_sector: Callable[[Any], str] | None = None,
    suppressor: Callable[..., Tuple[bool, Any]] | None = None,
    synthesize_candidate: Callable[[str, str], Dict[str, Any]] | None = None,
    force_queue: Optional[List[Dict[str, Any]]] = None,
    positions_path: Path | str = Path("eval_results/paper_execution/positions.json"),
) -> Dict[str, Any]:
    triage_score_fn = triage_score_fn or (lambda c: float(c.get("deal_flow_score", c.get("core_score", 0.0))))
    thesis_tags_fn = thesis_tags_fn or (lambda c: [])
    normalize_sector = normalize_sector or (lambda raw: str(raw or "Unclassified Equity"))
    suppressor = suppressor or (lambda **kwargs: (False, None))
    synthesize_candidate = synthesize_candidate or _default_synthesize_candidate

    deep_k = int(config.get("dealflow_deep_k", 8))
    initial_deep_k = deep_k
    core_quota = int(config.get("dealflow_deep_core_quota", 4))
    momentum_quota = int(config.get("dealflow_deep_momentum_quota", 4))
    reserve_quota = int(config.get("dealflow_deep_reserve_quota", 4))

    items: List[Dict[str, Any]] = []
    suppressed_queue_ids: set[str] = set()
    for candidate in shortlist.get("candidates", []):
        symbol = str(candidate.get("symbol", "")).upper().strip()
        if not symbol:
            continue
        lane = str(candidate.get("lane", "CORE"))
        momentum = float(candidate.get("momentum_score", 0.0))
        asymmetry = float(candidate.get("asymmetry_score", 0.0))
        thesis_tags = thesis_tags_fn(candidate)
        queue_id = f"{shortlist['run_id']}:{symbol}"
        item = {
            "queue_id": queue_id,
            "symbol": symbol,
            "asset_class": candidate.get("asset_class", "Unknown"),
            "sector": normalize_sector(candidate.get("sector")),
            "lane": lane if lane in {"CORE", "MOMENTUM"} else "CORE",
            "upside_3m_score": float(candidate.get("upside_3m_score", 0.0)),
            "emergence_proxy_score": float(candidate.get("emergence_proxy_score", 0.0)),
            "narrative_ignition_score": float(candidate.get("narrative_ignition_score", 0.0)),
            "fundamentals_acceleration_score": float(candidate.get("fundamentals_acceleration_score", 0.0)),
            "relative_strength_score": float(candidate.get("relative_strength_score", 0.0)),
            "lane_candidates": list(candidate.get("lane_candidates", [])),
            "deal_flow_score": float(candidate.get("deal_flow_score", 0.0)),
            "momentum_score": momentum,
            "asymmetry_score": asymmetry,
            "subscores": dict(candidate.get("subscores", {})),
            "thesis_tags": thesis_tags,
            "risk_tags": list(candidate.get("risk_tags", [])),
            "evidence": {"active_families": float(candidate.get("active_families", 0)), "evidence_count": float(candidate.get("evidence_count", 0)), "freshness_hours": float(candidate.get("freshness_hours", 9999.0))},
            "why_now": why_now_text(lane=lane, momentum_score=momentum, asymmetry_score=asymmetry, trend_tags=list(candidate.get("trend_tags", []))),
            "source": str(candidate.get("source", "AUTO")).upper(),
            "source_detail": str(candidate.get("source_detail", "AUTO_MODEL")),
            "manual_note": str(candidate.get("manual_note", "")),
            "research_playbook": select_research_playbook(lane=lane, momentum_score=momentum),
            "triage_score": float(round(triage_score_fn(candidate), 4)),
            "selected_for_deep": False,
        }
        suppressed, constraint = suppressor(symbol=symbol, thesis_tags=thesis_tags, config=config)
        if suppressed:
            suppressed_queue_ids.add(queue_id)
            reason = "Operator negative constraint"
            if isinstance(constraint, dict) and constraint.get("constraint_id"):
                reason += f" ({constraint.get('constraint_id')})"
            if reason not in item["risk_tags"]:
                item["risk_tags"].append(reason)
        items.append(item)

    items.sort(key=lambda i: -float(i["triage_score"]))
    eligible = [i for i in items if i["queue_id"] not in suppressed_queue_ids]
    selected_ids = select_for_deep(eligible, deep_k=deep_k, core_quota=core_quota, momentum_quota=momentum_quota)
    selected_ids = ensure_manual_deep_selection(eligible, selected_ids=selected_ids, deep_k=deep_k)
    if bool(config.get("dealflow_iv_force_queue_enabled", False)):
        items, selected_ids = inject_force_queue_candidates(items=items, selected_ids=selected_ids, deep_k=deep_k, reserve_quota=reserve_quota, run_id=shortlist["run_id"], force_queue=force_queue, synthesize_candidate=synthesize_candidate, normalize_sector=normalize_sector)
    pre = len(selected_ids)
    items, selected_ids = inject_held_positions(items=items, selected_ids=selected_ids, run_id=shortlist["run_id"], positions_path=positions_path, synthesize_candidate=synthesize_candidate, normalize_sector=normalize_sector)
    deep_k += len(selected_ids) - pre
    selected_set = set(selected_ids)
    for item in items:
        item["selected_for_deep"] = item["queue_id"] in selected_set

    if ledger_base_dir is not None:
        snapshot = {"deep_k": int(initial_deep_k), "final_deep_k": int(deep_k), "core_quota": int(core_quota), "momentum_quota": int(momentum_quota), "reserve_quota": int(reserve_quota)}
        row = make_ledger_row(run_id=str(shortlist.get("run_id", "")), source_date=str(shortlist.get("date", "")), lane="shared", stage_id="deep_selection_cut", rule_snapshot=snapshot, kept_symbols=[str(i.get("symbol", "")).upper().strip() for i in items if i["queue_id"] in selected_set], dropped_symbols=[str(i.get("symbol", "")).upper().strip() for i in items if i["queue_id"] not in selected_set], base_dir=Path(ledger_base_dir), drop_metadata_by_symbol=build_deep_selection_drop_metadata(items=items, selected_id_set=selected_set, suppressed_queue_ids=suppressed_queue_ids, deep_selection_rule_snapshot=snapshot))
        append_ledger_row(base_dir=Path(ledger_base_dir), lane="shared", row=row)

    return {"run_id": shortlist["run_id"], "date": shortlist["date"], "canonical_sector_map": {str(i["symbol"]): normalize_sector(i.get("sector")) for i in shortlist.get("candidates", [])}, "items": items, "deep_k": deep_k, "selected_queue_ids": selected_ids, "source_artifact": f"eval_results/deal_flow/{shortlist['date']}/shortlist_top20.json"}


def select_for_deep(items, deep_k, core_quota, momentum_quota):
    if not items or deep_k <= 0: return []
    core = sorted([i for i in items if i.get("lane") == "CORE"], key=lambda i: -float(i.get("triage_score", 0.0)))
    momentum = sorted([i for i in items if i.get("lane") == "MOMENTUM"], key=lambda i: -float(i.get("triage_score", 0.0)))
    selected = core[: min(core_quota, deep_k)]
    selected.extend(momentum[: min(momentum_quota, deep_k - len(selected))])
    if len(selected) < deep_k:
        ids = {i["queue_id"] for i in selected}
        selected.extend(sorted([i for i in items if i["queue_id"] not in ids], key=lambda i: -float(i.get("triage_score", 0.0)))[: deep_k - len(selected)])
    return [i["queue_id"] for i in selected[:deep_k]]


def ensure_manual_deep_selection(items, selected_ids, deep_k):
    manual = sorted([i for i in items if str(i.get("source", "AUTO")).upper() == "MANUAL"], key=lambda i: -float(i.get("triage_score", 0.0)))
    if not manual or deep_k <= 0: return selected_ids
    selected = set(selected_ids)
    if any(i["queue_id"] in selected for i in manual): return selected_ids
    removable = sorted([i for i in items if i["queue_id"] in selected and str(i.get("source", "AUTO")).upper() != "MANUAL"], key=lambda i: float(i.get("triage_score", 0.0)))
    if removable: selected.discard(removable[0]["queue_id"])
    elif len(selected) >= deep_k: return selected_ids
    selected.add(manual[0]["queue_id"])
    return [i["queue_id"] for i in sorted(items, key=lambda i: -float(i.get("triage_score", 0.0))) if i["queue_id"] in selected][:deep_k]


def inject_force_queue_candidates(*, items, selected_ids, deep_k, reserve_quota, run_id, force_queue=None, synthesize_candidate=None, normalize_sector=None):
    force_queue = force_queue or []
    synthesize_candidate = synthesize_candidate or _default_synthesize_candidate
    normalize_sector = normalize_sector or (lambda raw: str(raw or "Unclassified Equity"))
    if not force_queue or reserve_quota <= 0: return items, selected_ids
    selected = set(selected_ids)
    manual_count = sum(1 for i in items if i["queue_id"] in selected and str(i.get("source", "")).upper() == "MANUAL")
    available = max(0, reserve_quota - manual_count)
    existing = {str(i.get("symbol", "")).upper(): i for i in items}
    injected = 0
    for entry in force_queue:
        if injected >= available: break
        symbol = str(entry.get("symbol", "")).upper().strip()
        if not symbol: continue
        qid = f"{run_id}:{symbol}"
        if symbol in existing:
            if existing[symbol]["queue_id"] not in selected:
                selected_ids.append(existing[symbol]["queue_id"]); selected.add(existing[symbol]["queue_id"]); injected += 1
            continue
        stub = synthesize_candidate(symbol, "CORE")
        item = {"queue_id": qid, "symbol": symbol, "asset_class": stub.get("asset_class", "Equity"), "sector": normalize_sector(stub.get("sector")), "lane": "RESERVE", "deal_flow_score": float(stub.get("deal_flow_score", 50.0)), "momentum_score": float(stub.get("momentum_score", 50.0)), "asymmetry_score": float(stub.get("asymmetry_score", 50.0)), "subscores": {}, "thesis_tags": ["iv-force-queue"], "risk_tags": ["IV force-queue override"], "evidence": {"active_families": 0, "evidence_count": 0, "freshness_hours": 0.0}, "why_now": "IV divergence detected — earnings play force-queued", "source": "IV_FORCE_QUEUE", "source_detail": "IV_SCANNER", "manual_note": str(entry.get("reason", "")), "research_playbook": "iv_force_queue", "triage_score": 0.0, "selected_for_deep": True}
        items.append(item); selected_ids.append(qid); selected.add(qid); existing[symbol] = item; injected += 1
    return items, selected_ids


def inject_held_positions(*, items, selected_ids, run_id, positions_path, synthesize_candidate=None, normalize_sector=None):
    path = Path(positions_path)
    synthesize_candidate = synthesize_candidate or _default_synthesize_candidate
    normalize_sector = normalize_sector or (lambda raw: str(raw or "Unclassified Equity"))
    if not path.exists(): return items, selected_ids
    try: held = json.loads(path.read_text()).get("open_positions", {})
    except Exception: return items, selected_ids
    selected = set(selected_ids); existing = {str(i.get("symbol", "")).upper(): i for i in items}
    for raw_symbol in held:
        symbol = str(raw_symbol).upper().strip()
        if not symbol or symbol in _SKIP_DEEP_ANALYSIS: continue
        if symbol in existing:
            if existing[symbol].get("asset_class") in {"ETF", "CommodityProxy"}: continue
            if existing[symbol]["queue_id"] not in selected: selected_ids.append(existing[symbol]["queue_id"]); selected.add(existing[symbol]["queue_id"])
            continue
        stub = synthesize_candidate(symbol, "CORE")
        if stub.get("asset_class") in {"ETF", "CommodityProxy"}: continue
        item = {"queue_id": f"{run_id}:{symbol}", "symbol": symbol, "asset_class": stub.get("asset_class", "Equity"), "sector": normalize_sector(stub.get("sector")), "lane": "PORTFOLIO", "deal_flow_score": float(stub.get("deal_flow_score", 50.0)), "momentum_score": float(stub.get("momentum_score", 50.0)), "asymmetry_score": float(stub.get("asymmetry_score", 50.0)), "subscores": {}, "thesis_tags": ["held-position"], "risk_tags": ["held-position-rescore"], "evidence": {"active_families": 0, "evidence_count": 0, "freshness_hours": 0.0}, "why_now": "Held position — mandatory score refresh", "source": "PORTFOLIO", "source_detail": "positions.json", "manual_note": "", "research_playbook": None, "triage_score": 0.0, "selected_for_deep": True}
        items.append(item); selected_ids.append(item["queue_id"]); selected.add(item["queue_id"])
    return items, selected_ids


def build_deep_selection_drop_metadata(*, items, selected_id_set, suppressed_queue_ids, deep_selection_rule_snapshot):
    metadata = {}
    eligible = sorted([i for i in items if str(i.get("queue_id", "")).strip() and i.get("queue_id") not in suppressed_queue_ids], key=lambda r: (-float(r.get("triage_score", 0.0)), str(r.get("symbol", "")).upper().strip()))
    rank_by_id = {str(i.get("queue_id")): idx for idx, i in enumerate(eligible, 1)}
    final_k = int(deep_selection_rule_snapshot.get("final_deep_k", 0) or 0)
    for item in items:
        qid = str(item.get("queue_id", "")).strip()
        symbol = str(item.get("symbol", "")).upper().strip()
        if not qid or qid in selected_id_set or not symbol: continue
        lane = str(item.get("lane", "")).upper().strip(); triage = _float_or_none(item.get("triage_score")); rank = rank_by_id.get(qid)
        if qid in suppressed_queue_ids:
            code = "NEGATIVE_CONSTRAINT_SUPPRESSED"; text = "Operator negative constraints suppressed deep-selection eligibility."; threshold = {"constraint_pass_required": True}; observed = {"suppressed": True, "lane": lane, "triage_score": triage}; delta = 1
        elif rank is not None and final_k > 0 and rank > final_k:
            code = "TRIAGE_RANK_BELOW_DEEP_CUT"; text = "Triage rank was below final deep-selection cutoff."; threshold = {"final_deep_k": final_k}; observed = {"triage_rank": int(rank), "triage_score": triage, "lane": lane}; delta = int(rank) - final_k
        elif rank is not None:
            code = "DEEP_SELECTION_POLICY_EXCLUSION"; text = "Symbol was not selected after deep-selection quota/policy balancing."; threshold = dict(deep_selection_rule_snapshot); observed = {"triage_rank": int(rank), "triage_score": triage, "lane": lane}; delta = 1
        else:
            code = "DEEP_SELECTION_RANK_UNAVAILABLE"; text = "Deep-selection rank could not be resolved for this queue item."; threshold = dict(deep_selection_rule_snapshot); observed = {"triage_score": triage, "lane": lane}; delta = 1
        metadata[symbol] = {"reason_code": code, "reason_text": text, "threshold": threshold, "observed_value": observed, "delta_to_pass": delta}
    return metadata


def _float_or_none(raw):
    try: return float(raw)
    except Exception: return None


def _default_synthesize_candidate(symbol, lane):
    return {"symbol": str(symbol).upper().strip(), "asset_class": "Equity", "sector": "Unclassified Equity", "deal_flow_score": 50, "momentum_score": 50, "asymmetry_score": 50}
