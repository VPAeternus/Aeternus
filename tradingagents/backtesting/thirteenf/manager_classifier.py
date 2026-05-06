"""13F manager classification for broad scans.

Goal: separate active investment managers from banks, RIAs, pensions, brokers,
foreign/admin filers, passive warehouses, and one-position control filers.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .ingest import normalize_cik
from .manager_scan import load_manager_quality_rules


DEFAULT_MIN_AUM = 1_000_000_000.0
DEFAULT_MIN_POSITIONS = 10
DEFAULT_MAX_POSITIONS = 250
DEFAULT_MIN_TOP10 = 0.25
DEFAULT_MAX_TOP10 = 0.95


def classify_manager(
    manager: Dict[str, Any],
    stats: Dict[str, Any] | None = None,
    *,
    rules: Dict[str, Any] | None = None,
    min_aum: float = DEFAULT_MIN_AUM,
    min_positions: int = DEFAULT_MIN_POSITIONS,
    max_positions: int = DEFAULT_MAX_POSITIONS,
    min_top10: float = DEFAULT_MIN_TOP10,
    max_top10: float = DEFAULT_MAX_TOP10,
) -> Dict[str, Any]:
    rules = rules or load_manager_quality_rules()
    stats = stats or {}
    cik = normalize_cik(manager.get("manager_cik", ""))
    name = str(manager.get("manager_name", ""))
    name_l = f" {name.lower()} "
    allow_ciks = {normalize_cik(x) for x in rules.get("allowlist_ciks", [])}
    deny_ciks = {normalize_cik(x) for x in rules.get("denylist_ciks", [])}
    allow_terms = [str(x).lower() for x in rules.get("allow_terms", [])]
    deny_terms = [str(x).lower() for x in rules.get("deny_terms", [])]

    reasons: List[str] = []
    rejects: List[str] = []
    score = 0

    if cik in allow_ciks:
        score += 100
        reasons.append("allowlist_cik")
    if cik in deny_ciks:
        rejects.append("denylist_cik")

    matched_deny = [term for term in deny_terms if term in name_l]
    matched_allow = [term for term in allow_terms if term in name_l]
    if matched_deny:
        rejects.append("deny_terms:" + ",".join(matched_deny[:5]))
    if matched_allow:
        score += min(30, 10 * len(matched_allow))
        reasons.append("allow_terms:" + ",".join(matched_allow[:5]))

    aum = _float(stats.get("latest_13f_aum_usd"))
    positions = int(_float(stats.get("latest_position_count")))
    top10 = _float(stats.get("top10_concentration"))

    if aum >= min_aum:
        score += 20
        reasons.append("aum_pass")
    else:
        rejects.append("aum_below_min")
    if min_positions <= positions <= max_positions:
        score += 20
        reasons.append("position_count_pass")
    else:
        rejects.append("position_count_out_of_range")
    if min_top10 <= top10 <= max_top10:
        score += 20
        reasons.append("concentration_pass")
    else:
        rejects.append("concentration_out_of_range")

    if positions > 150 and top10 < 0.35:
        rejects.append("quasi_index_profile")
    if positions <= 3:
        rejects.append("control_or_shell_profile")
    if "wealth" in name_l or "financial" in name_l:
        rejects.append("ria_wealth_profile")

    status = "approved" if score >= 70 and not rejects else "rejected"
    if score >= 60 and rejects and "deny_terms" not in ";".join(rejects) and "denylist_cik" not in rejects:
        status = "review"

    return {
        "manager_id": manager.get("manager_id", ""),
        "manager_name": name,
        "manager_cik": cik,
        "status": status,
        "proper_manager_score": score,
        "reasons": reasons,
        "rejects": rejects,
        "latest_13f_aum_usd": aum,
        "latest_position_count": positions,
        "top10_concentration": top10,
    }


def classify_managers(managers: List[Dict[str, Any]], aum_summary: Dict[str, Dict[str, Any]], *, rules: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    out = []
    for manager in managers:
        stats = aum_summary.get(str(manager.get("manager_id", "")), {})
        out.append(classify_manager(manager, stats, rules=rules))
    return sorted(out, key=lambda row: (row["status"] != "approved", row["status"] != "review", -row["proper_manager_score"], row["manager_name"]))


def _float(raw: Any) -> float:
    try:
        return float(raw)
    except Exception:
        return 0.0
