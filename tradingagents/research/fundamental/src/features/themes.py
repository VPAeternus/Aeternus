from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.features.common import clean, flag, to_float

try:
    from tradingagents.dealflow.theme_aliases import canonicalize_theme_id, load_theme_aliases, match_theme_aliases
except Exception:  # pragma: no cover
    canonicalize_theme_id = None
    load_theme_aliases = None
    match_theme_aliases = None


THEME_CONFIG = Path(__file__).resolve().parents[1] / "config" / "theme_taxonomy.yaml"
SCORING_CONFIG = Path(__file__).resolve().parents[1] / "config" / "theme_scoring_rules.yaml"

DIRECT_ROLES = {
    "direct_beneficiary",
    "supplier",
    "infrastructure_provider",
    "commodity_exposure",
    "platform_leader",
    "leader",
    "supplier_bottleneck",
}


def load_theme_taxonomy(path: Path = THEME_CONFIG) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(payload.get("themes", []))


def _parse_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [clean(item) for item in value if clean(item)]
    text = clean(value)
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [clean(item) for item in parsed if clean(item)]
        except json.JSONDecodeError:
            pass
    return [clean(part) for part in text.split("|") if clean(part)]


def _confidence_rank(value: Any) -> int:
    return {"none": 0, "low": 1, "medium": 2, "high": 3}.get(clean(value).lower(), 0)


def _normalise_theme_id(name: str) -> str:
    return clean(name).lower().replace("/", " ").replace("&", " ").replace("-", " ").replace(" ", "_")


def detect_candidate_themes(row: dict[str, Any], filing_text: str = "") -> list[dict[str, Any]]:
    """Return normalized candidate-theme mappings from generic LLM fields.

    This intentionally does not depend on permanent AI/data-center columns. Those
    can exist as legacy hints, but themes themselves are data/config driven.
    """
    primary = clean(row.get("primary_theme") or row.get("theme_primary"))
    secondary = _parse_list(row.get("secondary_themes") or row.get("theme_secondary"))
    tags = _parse_list(row.get("theme_tags"))
    evidence = _parse_list(row.get("theme_evidence")) or [clean(row.get("theme_evidence_summary") or row.get("theme_driver_summary"))]
    evidence = [item for item in evidence if item]
    role = clean(row.get("theme_role")).lower() or "none"
    confidence = clean(row.get("theme_confidence")).lower() or "none"
    detected_by = clean(row.get("theme_detected_by")) or "llm"
    source = clean(row.get("theme_source")) or "filing"

    names = [primary, *secondary, *tags]
    aliases = load_theme_aliases() if load_theme_aliases else {}
    alias_matches = match_theme_aliases(" ".join([primary, *secondary, *tags, *evidence, filing_text]), aliases) if match_theme_aliases else []
    alias_role_by_theme: dict[str, str] = {}
    for match in alias_matches:
        matched_theme_id = str(match.get("theme_id") or "")
        names.append(matched_theme_id)
        roles = match.get("theme_roles") or []
        if roles:
            alias_role_by_theme[matched_theme_id] = clean(roles[0]).lower()
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for name in names:
        if not name:
            continue
        theme_id = canonicalize_theme_id(name, aliases) if canonicalize_theme_id else _normalise_theme_id(name)
        if theme_id in seen:
            continue
        seen.add(theme_id)
        out.append(
            {
                "ticker": clean(row.get("ticker")).upper(),
                "quarter": clean(row.get("quarter")),
                "theme_id": theme_id,
                "theme_name": name,
                "theme_role": alias_role_by_theme.get(theme_id, role) if role in {"", "none"} else role,
                "theme_confidence": confidence,
                "theme_evidence": " | ".join(evidence),
                "theme_source": source,
                "theme_detected_by": detected_by,
                "theme_score": int(to_float(row.get("theme_tailwind_score")) or 0),
            }
        )
    return out


def _load_scoring_rules(path: Path = SCORING_CONFIG) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _cohort_strength_value(row: dict[str, Any], cohort_scores: dict[str, Any]) -> str:
    row_strength = clean(row.get("theme_cohort_strength")).lower()
    if row_strength:
        return row_strength
    primary = _normalise_theme_id(clean(row.get("primary_theme") or row.get("theme_primary")))
    if primary and primary in cohort_scores:
        return clean(cohort_scores[primary].get("theme_cohort_strength")).lower()
    return "inactive"


def assign_theme_tailwind_score(
    row: dict[str, Any],
    theme_tags: list[dict[str, Any]] | None = None,
    cohort_scores: dict[str, Any] | None = None,
    *,
    rules_path: Path = SCORING_CONFIG,
) -> int:
    rules = _load_scoring_rules(rules_path)
    cap = int(rules.get("cap", 20))
    tags = theme_tags if theme_tags is not None else detect_candidate_themes(row)
    if not tags:
        return 0
    evidence = any(clean(tag.get("theme_evidence")) for tag in tags) or clean(row.get("theme_evidence_summary"))
    if not evidence:
        return 0
    confidence_rank = max(_confidence_rank(tag.get("theme_confidence")) for tag in tags)
    if confidence_rank < 2:
        return 0
    roles = {clean(tag.get("theme_role")).lower() for tag in tags}
    if roles and roles <= {"indirect_beneficiary", "none", ""}:
        return 0
    confirmed_by_signal = (
        int(to_float(row.get("causal_change")) or 0) == 3
        or flag(row.get("repricing_momentum_extension"))
        or clean(row.get("positive_repricing_status")) in {"repricing_started", "repricing_confirmed"}
    )
    if not confirmed_by_signal:
        return 0

    score = 0
    score += rules.get("direct_exposure_high_confidence", 5) if confidence_rank >= 3 else rules.get("direct_exposure_medium_confidence", 3)
    if any(role in DIRECT_ROLES for role in roles):
        score += rules.get("leader_or_direct_beneficiary", 5)
    strength = _cohort_strength_value(row, cohort_scores or {})
    score += {
        "strong": rules.get("cohort_strong", 5),
        "active": rules.get("cohort_active", 5),
        "emerging": rules.get("cohort_emerging", 3),
        "fading": rules.get("cohort_fading", -3),
        "overheated": rules.get("cohort_overheated_extended", -5),
    }.get(strength, 0)
    if clean(row.get("theme_driver_type")) in {"revenue", "demand", "backlog", "capacity"}:
        score += rules.get("revenue_or_backlog_evidence", 3)
    if clean(row.get("theme_driver_type")) in {"margin", "pricing"}:
        score += rules.get("margin_or_pricing_evidence", 2)
    return max(0, min(cap, int(score)))


def compute_theme_cohort_strength(rows: pd.DataFrame, as_of_date: str | date) -> dict[str, dict[str, Any]]:
    if rows.empty:
        return {}
    frame = rows.copy()
    if "tradable_date" in frame.columns:
        frame["_tradable_date"] = pd.to_datetime(frame["tradable_date"], errors="coerce")
        cutoff = pd.to_datetime(as_of_date)
        frame = frame[frame["_tradable_date"].isna() | frame["_tradable_date"].le(cutoff)]
    mappings: list[dict[str, Any]] = []
    for row in frame.fillna("").to_dict("records"):
        mappings.extend(detect_candidate_themes(row))
    if not mappings:
        return {}
    map_frame = pd.DataFrame(mappings)
    merged = map_frame.merge(frame, on=["ticker", "quarter"], how="left", suffixes=("", "_candidate"))
    out: dict[str, dict[str, Any]] = {}
    for theme_id, group in merged.groupby("theme_id"):
        count = len(group)
        high_score = pd.to_numeric(group.get("entry_score_0_100", pd.Series(dtype=float)), errors="coerce").ge(70).sum()
        avg_qoq = pd.to_numeric(group.get("entry_qoq_pct", pd.Series(dtype=float)), errors="coerce").mean()
        llm_best = (
            pd.to_numeric(group.get("post_llm_candidate_flag", pd.Series(dtype=float)), errors="coerce").eq(1)
            & pd.to_numeric(group.get("causal_change", pd.Series(dtype=float)), errors="coerce").eq(3)
            & pd.to_numeric(group.get("negative_revision_risk", pd.Series(dtype=float)), errors="coerce").le(2)
        ).sum()
        if count >= 8 and (high_score >= 3 or llm_best >= 3):
            strength = "strong"
        elif count >= 4 and (high_score >= 1 or avg_qoq >= 20):
            strength = "active"
        elif count >= 2:
            strength = "emerging"
        else:
            strength = "inactive"
        out[theme_id] = {
            "theme_id": theme_id,
            "theme_name": group["theme_name"].iloc[0],
            "number_of_candidates_in_theme": int(count),
            "number_of_high_score_candidates_in_theme": int(high_score),
            "average_entry_qoq_pct": round(float(avg_qoq), 4) if pd.notna(avg_qoq) else "",
            "share_with_LLM_best": round(float(llm_best) / count, 4) if count else 0,
            "theme_cohort_strength": strength,
        }
    return out
