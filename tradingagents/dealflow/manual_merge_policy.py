"""Manual watchlist merge policy for dealflow shortlists."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from tradingagents.dealflow.manual_watchlist import validate_symbol_liquidity as _default_validate_liquidity


def apply_manual_merge_policy(
    *,
    ranked_auto: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
    manual_ideas: List[Dict[str, Any]],
    top_k: int,
    config: Optional[Dict[str, Any]] = None,
    synthesize_manual_candidate: Optional[Callable[[str, str], Dict[str, Any]]] = None,
    validate_liquidity: Callable[..., Tuple[bool, float]] = _default_validate_liquidity,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    cfg = config or {}
    synth = synthesize_manual_candidate or _default_synthesize_manual_candidate
    shortlist = [dict(row) for row in ranked_auto[:top_k]]
    candidate_map = {str(row.get("symbol", "")).upper().strip(): dict(row) for row in candidates}
    selected_symbols = {str(row.get("symbol", "")).upper().strip() for row in shortlist if row.get("symbol")}
    for row in shortlist:
        row["source"] = str(row.get("source", "AUTO")).upper()
        row["manual_note"] = str(row.get("manual_note", ""))
        row["manual_priority"] = int(row.get("manual_priority", 0) or 0)

    min_slots = int(cfg.get("dealflow_manual_slots_min", 2))
    max_slots = int(cfg.get("dealflow_manual_slots_max", 4))
    target_slots = max(min_slots, min(max_slots, int(cfg.get("dealflow_manual_slots_target", 3))))
    min_adv = float(cfg.get("dealflow_manual_min_adv_usd", 50_000_000))
    force_insert = bool(cfg.get("dealflow_manual_force_insert", True))
    max_sector_count = int(cfg.get("dealflow_max_sector_count", 5))
    max_asset_class_count = int(cfg.get("dealflow_max_asset_class_count", 8))
    decisions: List[Dict[str, Any]] = []
    include_candidates: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    reinforced = rejected = 0
    ordered_manual = sorted([dict(idea) for idea in manual_ideas], key=lambda i: (-int(i.get("priority", 0) or 0), str(i.get("created_at", "")), str(i.get("symbol", ""))))

    for idea in ordered_manual:
        symbol = str(idea.get("symbol", "")).upper().strip()
        lane_pref = str(idea.get("lane_preference", "CORE")).upper()
        note = str(idea.get("note", ""))
        priority = int(idea.get("priority", 3) or 3)
        if not symbol:
            rejected += 1; decisions.append(_manual_decision_row("", "REJECTED", "Missing symbol.", priority, lane_pref, note)); continue
        if symbol in selected_symbols:
            reinforced += 1
            _mark_manual_reinforced(shortlist, symbol, note, priority)
            decisions.append(_manual_decision_row(symbol, "REINFORCED", "Already present in auto shortlist; marked as manual reinforced.", priority, lane_pref, note)); continue
        candidate = dict(candidate_map.get(symbol) or synth(symbol, lane_pref))
        if str(candidate.get("status", "LOW_DATA")) != "ACTIVE":
            candidate["status"] = "ACTIVE"; _add_tag(candidate, "Manual override (low data)")
        if lane_pref in {"CORE", "MOMENTUM"}: candidate["lane"] = lane_pref
        liquid_ok, adv = validate_liquidity(symbol=symbol, min_adv_usd=min_adv)
        if not liquid_ok:
            if not force_insert:
                rejected += 1; decisions.append(_manual_decision_row(symbol, "REJECTED", f"Liquidity gate failed (ADV={adv:.2f}, min={min_adv:.2f}).", priority, lane_pref, note, str(candidate.get("lane", "CORE")))); continue
            _add_tag(candidate, "Manual liquidity unchecked" if adv <= 0 else "Manual liquidity override")
        include_candidates.append((idea, candidate))

    include_candidates.sort(key=lambda pair: (-int(pair[0].get("priority", 0) or 0), -_manual_candidate_rank_score(pair[1], str(pair[0].get("lane_preference", "CORE"))), str(pair[1].get("symbol", ""))))
    included = 0
    for idea, base_candidate in include_candidates:
        if included >= min(len(include_candidates), target_slots): break
        candidate = dict(base_candidate); symbol = str(candidate.get("symbol", "")).upper().strip(); priority = int(idea.get("priority", 3) or 3); lane_pref = str(idea.get("lane_preference", "CORE")).upper(); note = str(idea.get("note", ""))
        candidate.update({"source": "MANUAL", "source_detail": "MANUAL_WATCHLIST", "manual_note": note, "manual_priority": priority}); _add_tag(candidate, "Manual watchlist")
        replace_idx = _find_lowest_auto_index(shortlist)
        if replace_idx is None and len(shortlist) >= top_k:
            rejected += 1; decisions.append(_manual_decision_row(symbol, "REJECTED", "No replaceable auto slot available.", priority, lane_pref, note, str(candidate.get("lane", "CORE")))); continue
        if not _respects_diversification_caps(shortlist, candidate, replace_idx, max_sector_count, max_asset_class_count):
            if not force_insert:
                rejected += 1; decisions.append(_manual_decision_row(symbol, "REJECTED", "Diversification caps rejected insertion.", priority, lane_pref, note, str(candidate.get("lane", "CORE")))); continue
            _add_tag(candidate, "Manual cap override")
        replaced_symbol = None
        if replace_idx is not None and replace_idx < len(shortlist):
            replaced_symbol = str(shortlist[replace_idx].get("symbol", "")); shortlist.pop(replace_idx); selected_symbols.discard(replaced_symbol.upper().strip())
        shortlist.append(candidate); selected_symbols.add(symbol); included += 1
        reason = "Inserted via manual slot." + (f" Replaced {replaced_symbol}." if replaced_symbol else "")
        if "Manual cap override" in candidate.get("risk_tags", []): reason += " Diversification cap override applied."
        decisions.append(_manual_decision_row(symbol, "INCLUDED", reason, priority, lane_pref, note, str(candidate.get("lane", "CORE"))))

    shortlist.sort(key=lambda row: (-_candidate_rank_score(row), float(row.get("freshness_hours", 9999.0)), str(row.get("symbol", ""))))
    shortlist = shortlist[:top_k]
    for idx, row in enumerate(shortlist, 1): row["rank"] = idx
    rank_map = {str(row.get("symbol", "")).upper().strip(): int(row.get("rank", 0) or 0) for row in shortlist}
    for row in decisions: row["selected_rank"] = rank_map.get(str(row.get("symbol", "")).upper().strip())
    return shortlist, {"requested": len(ordered_manual), "included": included, "reinforced": reinforced, "rejected": rejected, "manual_symbols": sorted({str(r.get("symbol", "")).upper().strip() for r in shortlist if str(r.get("source", "AUTO")).upper() == "MANUAL"}), "decisions": decisions}


def _add_tag(candidate: Dict[str, Any], tag: str) -> None:
    tags = list(candidate.get("risk_tags", []))
    if tag not in tags: tags.append(tag)
    candidate["risk_tags"] = tags


def _mark_manual_reinforced(shortlist, symbol, note, priority):
    for row in shortlist:
        if str(row.get("symbol", "")).upper().strip() == symbol.upper().strip():
            row.update({"source": "MANUAL", "source_detail": "MANUAL_REINFORCED", "manual_note": note, "manual_priority": int(max(priority, int(row.get("manual_priority", 0) or 0)))})
            _add_tag(row, "Manual watchlist"); _add_tag(row, "Manual reinforced"); return


def _respects_diversification_caps(shortlist, candidate, replace_idx, max_sector_count, max_asset_class_count):
    trial = [row for idx, row in enumerate(shortlist) if replace_idx is None or idx != replace_idx] + [candidate]
    sectors, assets = {}, {}
    for row in trial:
        sector, asset = str(row.get("sector", "Unknown")), str(row.get("asset_class", "Unknown"))
        sectors[sector] = sectors.get(sector, 0) + 1; assets[asset] = assets.get(asset, 0) + 1
        if sectors[sector] > max_sector_count or assets[asset] > max_asset_class_count: return False
    return True


def _find_lowest_auto_index(shortlist):
    rows = [(idx, _candidate_rank_score(row)) for idx, row in enumerate(shortlist) if str(row.get("source", "AUTO")).upper() == "AUTO"]
    return min(rows, key=lambda row: row[1])[0] if rows else None


def _candidate_rank_score(candidate):
    return float(candidate.get("asymmetry_score" if str(candidate.get("lane", "CORE")).upper() == "MOMENTUM" else "core_score", candidate.get("deal_flow_score", 0.0)))


def _manual_candidate_rank_score(candidate, lane_preference):
    lane = str(lane_preference or "").upper()
    if lane == "MOMENTUM": return float(candidate.get("asymmetry_score", candidate.get("momentum_score", 0.0)))
    if lane == "CORE": return float(candidate.get("core_score", candidate.get("deal_flow_score", 0.0)))
    return _candidate_rank_score(candidate)


def _manual_decision_row(symbol, action, reason, priority, lane_preference, note, lane="CORE"):
    return {"symbol": symbol, "action": action, "reason": reason, "priority": int(priority), "lane_preference": lane_preference if lane_preference in {"CORE", "MOMENTUM"} else "CORE", "note": note, "lane": lane if lane in {"CORE", "MOMENTUM"} else "CORE", "selected_rank": None}


def _default_synthesize_manual_candidate(symbol, lane_preference):
    lane = "MOMENTUM" if str(lane_preference).upper() == "MOMENTUM" else "CORE"
    return {"symbol": str(symbol).upper().strip().replace(".", "-"), "asset_class": "Equity", "sector": "Unclassified Equity", "deal_flow_score": 50.0, "core_score": 50.0, "momentum_score": 50.0, "asymmetry_score": 50.0, "freshness_hours": 9999.0, "status": "ACTIVE", "risk_tags": ["Manual override (no auto coverage)"], "lane": lane}
