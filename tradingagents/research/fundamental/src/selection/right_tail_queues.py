"""Right-tail visibility queues for fundamental research outputs."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .signal_utils import HP_SIGNAL_FIELDS, RM_SIGNAL_FIELDS, signal_bucket, signal_count, to_float, truthy

DEMOTE_SEVERITIES = {"none", "soft", "hard", "unknown"}
HARD_DEMOTE_REASON_CODES = {"going_concern", "accounting_quality", "fraud_or_integrity", "broken_thesis", "missing_filings"}
SOFT_DEMOTE_REASON_CODES = {"weak_fundamentals", "cyclical_trough", "high_leverage", "inventory_digesting", "margin_pressure", "customer_concentration", "liquidity_risk", "dilution_risk"}
DEMOTE_REASON_CODES = HARD_DEMOTE_REASON_CODES | SOFT_DEMOTE_REASON_CODES

FORBIDDEN_RIGHT_TAIL_ROUTING_COLUMNS = {
    "return_10d_pct", "return_20d_pct", "return_30d_pct", "return_60d_pct", "return_90d_pct",
    "winner_90d_30pct", "loser_90d_minus30pct",
    "monitoring_score_0_100", "active_monitoring_score_0_100", "final_rank_score_0_100",
    "rank_score_0_100", "current_return_pct", "return_since_signal_pct", "return_since_purchase_pct",
}

SUPPLIER_THEME_ROLES = {"supplier", "infrastructure_provider", "commodity_exposure", "turnaround_with_theme_tailwind"}
SUPPLIER_KEYWORDS = ("bottleneck", "semicap", "semi cap", "materials", "optical", "supplier")
CORE_RM_SIGNAL_FIELDS = tuple(field for field in RM_SIGNAL_FIELDS if field != "rm_buy_review_flag")

RIGHT_TAIL_SCORING_COLUMNS = tuple(sorted({
    *CORE_RM_SIGNAL_FIELDS,
    *HP_SIGNAL_FIELDS,
    "akg_universe_tier",
    "blocking_issues",
    "entry_score_0_100",
    "evidence_risk",
    "filing_theme_growth_flag",
    "filing_theme_guidance_flag",
    "market_repricing_score",
    "post_llm_demote_evidence",
    "post_llm_demote_flag",
    "post_llm_demote_overrideable",
    "post_llm_demote_reason_code",
    "post_llm_demote_severity",
    "primary_theme",
    "repricing_momentum_extension",
    "repricing_momentum_priority",
    "risk_penalty_score",
    "rm_buy_review_flag",
    "theme_acceleration_research_visibility",
    "theme_evidence_summary",
    "theme_role",
    "theme_tags",
    "theme_tailwind_score",
    "ticker",
    "quarter",
}))


@dataclass(frozen=True)
class RightTailQueueConfig:
    scout_threshold: float = 50.0
    top15_candidate_threshold: float = 70.0
    watchlist_threshold: float = 35.0
    soft_demote_top15_candidate_threshold: float = 80.0


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _clean_lower(value: Any) -> str:
    return _clean(value).lower()


def _single_rm_signal_bucket(row: Mapping[str, Any]) -> bool:
    return signal_bucket(row, CORE_RM_SIGNAL_FIELDS)[0] == "1"


def _theme_text(row: Mapping[str, Any]) -> str:
    values = [row.get("primary_theme"), row.get("theme_tags"), row.get("theme_evidence_summary")]
    return " ".join(_clean(v).lower() for v in values if _clean(v))


def has_active_theme_supplier_role(row: Mapping[str, Any]) -> bool:
    role = _clean_lower(row.get("theme_role"))
    if role in SUPPLIER_THEME_ROLES:
        return True
    text = _theme_text(row)
    return any(keyword in text for keyword in SUPPLIER_KEYWORDS)


def classify_demote_severity(row: Mapping[str, Any]) -> str:
    raw = _clean_lower(row.get("post_llm_demote_severity"))
    if raw in DEMOTE_SEVERITIES:
        return raw
    if not truthy(row.get("post_llm_demote_flag")):
        return "none"
    reason = _clean_lower(row.get("post_llm_demote_reason_code"))
    if reason in HARD_DEMOTE_REASON_CODES:
        return "hard"
    if reason in SOFT_DEMOTE_REASON_CODES:
        return "soft"
    return "unknown"


def compute_right_tail_evidence_score(row: Mapping[str, Any]) -> tuple[float, dict[str, float]]:
    parts: dict[str, float] = {}
    if _single_rm_signal_bucket(row):
        parts["single_rm_signal_bucket"] = 20
    if truthy(row.get("rm_buy_review_flag")):
        parts["rm_buy_review_flag"] = 12
    if truthy(row.get("repricing_momentum_priority")):
        parts["repricing_momentum_priority"] = 10
    if truthy(row.get("repricing_momentum_extension")):
        parts["repricing_momentum_extension"] = 6
    market = to_float(row.get("market_repricing_score")) or 0.0
    if market >= 10:
        parts["market_repricing_score_gte_10"] = 10
    if market >= 14:
        parts["market_repricing_score_gte_14"] = 10
    if signal_count(row, HP_SIGNAL_FIELDS) > 0:
        parts["hp_signal_count_gt_0"] = 10
    if truthy(row.get("hp_LLM_best")):
        parts["hp_LLM_best"] = 12
    if truthy(row.get("theme_acceleration_research_visibility")):
        parts["theme_acceleration_research_visibility"] = 15
    if _clean(row.get("akg_universe_tier")).upper() == "T5_RESCAN":
        parts["akg_t5_rescan"] = 12
    if _clean(row.get("primary_theme")):
        parts["primary_theme"] = 10
    if (to_float(row.get("theme_tailwind_score")) or 0.0) > 0:
        parts["theme_tailwind_score"] = 8
    if truthy(row.get("filing_theme_growth_flag")):
        parts["filing_theme_growth_flag"] = 8
    if truthy(row.get("filing_theme_guidance_flag")):
        parts["filing_theme_guidance_flag"] = 8
    if has_active_theme_supplier_role(row):
        parts["active_theme_supplier_or_bottleneck_role"] = 10
    severity = classify_demote_severity(row)
    if severity == "hard":
        parts["hard_demote"] = -15
    elif severity == "soft":
        parts["soft_demote"] = -8
    if (to_float(row.get("risk_penalty_score")) or 0.0) >= 10:
        parts["risk_penalty_score_gte_10"] = -10
    return float(sum(parts.values())), parts


def _strip_forbidden_columns(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in dict(row).items() if key not in FORBIDDEN_RIGHT_TAIL_ROUTING_COLUMNS}


def _is_overrideable(row: Mapping[str, Any]) -> bool:
    return truthy(row.get("post_llm_demote_overrideable"))


def _demote_review_candidate(row: Mapping[str, Any]) -> bool:
    return any([
        truthy(row.get("rm_buy_review_flag")),
        _single_rm_signal_bucket(row),
        truthy(row.get("repricing_momentum_priority")),
        truthy(row.get("repricing_momentum_extension")),
        (to_float(row.get("market_repricing_score")) or 0.0) >= 10,
        signal_count(row, HP_SIGNAL_FIELDS) > 0,
        (to_float(row.get("theme_tailwind_score")) or 0.0) > 0,
        bool(_clean(row.get("primary_theme"))),
        _clean(row.get("akg_universe_tier")).upper() == "T5_RESCAN",
        truthy(row.get("theme_acceleration_research_visibility")),
    ])


def _thin_signal_candidate(row: Mapping[str, Any]) -> bool:
    return any([
        truthy(row.get("rm_buy_review_flag")),
        _single_rm_signal_bucket(row),
        signal_count(row, HP_SIGNAL_FIELDS) > 0,
        (to_float(row.get("market_repricing_score")) or 0.0) >= 6,
    ])


def _dedupe_reason_codes(codes: Sequence[str]) -> str:
    return ";".join(sorted({code for code in codes if code}))


def _recommended_action(queue_type: str, severity: str) -> str:
    if queue_type == "already_selected_top15":
        return "already_selected_top15_no_queue_action"
    if queue_type == "blocked_hard_demote":
        return "hard_demote_review_only"
    if severity == "unknown":
        return "unknown_demote_needs_human_review"
    if queue_type == "top15_exception_candidate" and severity == "soft":
        return "soft_demote_starter_possible_after_underwriting"
    if queue_type == "top15_exception_candidate":
        return "exception_candidate_research_or_starter_underwriting"
    if queue_type == "right_tail_scout":
        return "scout_research"
    if queue_type == "demote_review":
        return "demote_review"
    if queue_type == "thin_signal_watchlist":
        return "thin_signal_monitor_for_new_theme_or_filing_evidence"
    if queue_type == "watchlist_only":
        return "watchlist_monitor_only"
    return "ignore"


def _annotate_queue_row(row: Mapping[str, Any], queue_type: str, score: float, parts: dict[str, float], input_columns: Sequence[str], extra_reason_codes: Sequence[str] = ()) -> dict[str, Any]:
    severity = classify_demote_severity(row)
    reason_codes = [key for key, value in parts.items() if value > 0] + list(extra_reason_codes)
    return {
        "ticker": _clean(row.get("ticker")).upper(),
        "quarter": _clean(row.get("quarter")),
        "entry_score_0_100": _clean(row.get("entry_score_0_100")),
        "post_llm_demote_flag": _clean(row.get("post_llm_demote_flag")),
        "post_llm_demote_severity": severity,
        "post_llm_demote_reason_code": _clean(row.get("post_llm_demote_reason_code")),
        "post_llm_demote_overrideable": _clean(row.get("post_llm_demote_overrideable")),
        "right_tail_evidence_score": f"{score:.6f}",
        "right_tail_queue_type": queue_type,
        "right_tail_recommended_action": _recommended_action(queue_type, severity),
        "right_tail_reason_codes": _dedupe_reason_codes(reason_codes),
        "right_tail_score_parts": json.dumps(parts, sort_keys=True),
        "right_tail_score_input_columns": ";".join(sorted(input_columns)),
        "market_repricing_score": _clean(row.get("market_repricing_score")),
        "repricing_momentum_priority": _clean(row.get("repricing_momentum_priority")),
        "repricing_momentum_extension": _clean(row.get("repricing_momentum_extension")),
        "primary_theme": _clean(row.get("primary_theme")),
        "theme_role": _clean(row.get("theme_role")),
        "theme_tailwind_score": _clean(row.get("theme_tailwind_score")),
        "why_demoted": _clean(row.get("post_llm_demote_evidence") or row.get("blocking_issues") or row.get("evidence_risk")),
        "why_still_interesting": _dedupe_reason_codes(reason_codes),
    }


def build_right_tail_queues(rows: Sequence[Mapping[str, Any]], top15_selected_keys: set[tuple[str, str]], config: RightTailQueueConfig | None = None) -> dict[str, list[dict[str, Any]]]:
    cfg = config or RightTailQueueConfig()
    queues = {
        "top15_exception_candidate_queue": [],
        "right_tail_scout_queue": [],
        "demote_review_queue": [],
        "watchlist_only_queue": [],
        "thin_signal_watchlist_queue": [],
        "right_tail_evidence_score_diagnostics": [],
    }
    for raw in rows:
        row = _strip_forbidden_columns(raw)
        input_columns = tuple(row.keys())
        ticker = _clean(row.get("ticker")).upper()
        quarter = _clean(row.get("quarter"))
        selected_key = (ticker, quarter)
        score, parts = compute_right_tail_evidence_score(row)
        severity = classify_demote_severity(row)
        demote_candidate = _demote_review_candidate(row)
        queue_type = "ignore"
        target_queue = ""
        extra_reason_codes: list[str] = []
        rm_buy_market_override = truthy(row.get("rm_buy_review_flag")) and (to_float(row.get("market_repricing_score")) or 0.0) >= 14
        if selected_key in top15_selected_keys:
            queue_type = "already_selected_top15"
        elif severity == "hard":
            queue_type = "blocked_hard_demote"
            target_queue = "demote_review_queue"
        elif severity == "unknown" and (demote_candidate or score >= 15):
            queue_type = "demote_review"
            target_queue = "demote_review_queue"
        elif severity == "unknown":
            queue_type = "watchlist_only" if score >= cfg.watchlist_threshold else "ignore"
            target_queue = "watchlist_only_queue" if queue_type == "watchlist_only" else ""
        elif severity == "soft" and _is_overrideable(row) and score >= cfg.soft_demote_top15_candidate_threshold:
            queue_type = "top15_exception_candidate"
            target_queue = "top15_exception_candidate_queue"
        elif severity == "none" and score >= cfg.top15_candidate_threshold:
            queue_type = "top15_exception_candidate"
            target_queue = "top15_exception_candidate_queue"
        elif severity == "soft" and score >= cfg.scout_threshold:
            queue_type = "right_tail_scout"
            target_queue = "right_tail_scout_queue"
        elif severity == "soft" and demote_candidate:
            queue_type = "demote_review"
            target_queue = "demote_review_queue"
        elif severity == "none" and rm_buy_market_override:
            queue_type = "right_tail_scout"
            target_queue = "right_tail_scout_queue"
            extra_reason_codes.append("rm_buy_review_market_repricing_override")
        elif score >= cfg.scout_threshold:
            queue_type = "right_tail_scout"
            target_queue = "right_tail_scout_queue"
        elif score >= cfg.watchlist_threshold:
            queue_type = "watchlist_only"
            target_queue = "watchlist_only_queue"
        elif severity != "hard" and _thin_signal_candidate(row):
            queue_type = "thin_signal_watchlist"
            target_queue = "thin_signal_watchlist_queue"
        annotated = _annotate_queue_row(row, queue_type, score, parts, input_columns, extra_reason_codes)
        if target_queue:
            queues[target_queue].append(annotated)
        queues["right_tail_evidence_score_diagnostics"].append(annotated)
    sorter = lambda r: (-float(r["right_tail_evidence_score"]), r["ticker"], r.get("quarter", ""))
    return {key: sorted(value, key=sorter) for key, value in queues.items()}


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


QUEUE_CSV_FIELDS = [
    "ticker",
    "quarter",
    "entry_score_0_100",
    "post_llm_demote_flag",
    "post_llm_demote_severity",
    "post_llm_demote_reason_code",
    "post_llm_demote_overrideable",
    "right_tail_evidence_score",
    "right_tail_queue_type",
    "right_tail_recommended_action",
    "right_tail_reason_codes",
    "right_tail_score_parts",
    "right_tail_score_input_columns",
    "market_repricing_score",
    "repricing_momentum_priority",
    "repricing_momentum_extension",
    "primary_theme",
    "theme_role",
    "theme_tailwind_score",
    "why_demoted",
    "why_still_interesting",
]

TARGET_AUDIT_FIELDS = [
    "ticker",
    "target_quarter",
    "selected_in_top15_v3",
    "selected_sleeve",
    "miss_failure_mode",
    "routed_visibility_layer",
    "right_tail_evidence_score",
    "right_tail_recommended_action",
    "target_visibility_routed",
    "target_actionable_research_routed",
    "target_scout_or_top15_routed",
    "target_demote_review_routed",
    "target_buy_underwriting_routed",
]


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], default_fields: Sequence[str] | None = None) -> None:
    fields: list[str] = list(default_fields or [])
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields or ["empty"])
        writer.writeheader()
        writer.writerows(rows)


def parse_top15_selected_keys(path: Path | None) -> set[tuple[str, str]]:
    if path is None or not path.exists():
        return set()
    keys: set[tuple[str, str]] = set()
    for row in _read_csv(path):
        ticker = _clean(row.get("ticker")).upper()
        quarter = _clean(row.get("quarter"))
        if ticker:
            keys.add((ticker, quarter))
    return keys


def read_target_events_csv(path: Path) -> list[tuple[str, str]]:
    events: list[tuple[str, str]] = []
    for row in _read_csv(path):
        ticker = _clean(row.get("ticker")).upper()
        quarter = _clean(row.get("quarter") or row.get("target_quarter"))
        if ticker and quarter:
            events.append((ticker, quarter))
    return events


def _iter_target_events(target_events: Mapping[str, str] | Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    if isinstance(target_events, Mapping):
        return [(_clean(ticker).upper(), _clean(quarter)) for ticker, quarter in target_events.items()]
    return [(_clean(ticker).upper(), _clean(quarter)) for ticker, quarter in target_events]


def build_target_visibility_audit(rows: Sequence[Mapping[str, Any]], diagnostics: Sequence[Mapping[str, Any]], target_events: Mapping[str, str] | Sequence[tuple[str, str]]) -> list[dict[str, Any]]:
    raw_by_key = {(_clean(r.get("ticker")).upper(), _clean(r.get("quarter"))): r for r in rows}
    diag_by_key = {(_clean(r.get("ticker")).upper(), _clean(r.get("quarter"))): r for r in diagnostics}
    audit: list[dict[str, Any]] = []
    for ticker, quarter in _iter_target_events(target_events):
        key = (_clean(ticker).upper(), _clean(quarter))
        raw = raw_by_key.get(key, {})
        diag = diag_by_key.get(key, {})
        layer = diag.get("right_tail_queue_type", "not_present")
        selected = layer == "already_selected_top15"
        visibility = selected or layer in {"top15_exception_candidate", "right_tail_scout", "demote_review", "blocked_hard_demote", "thin_signal_watchlist"}
        scout_or_top15 = selected or layer in {"top15_exception_candidate", "right_tail_scout"}
        demote_review = layer == "demote_review"
        positive_evidence = bool(_clean(diag.get("right_tail_reason_codes")))
        actionable = scout_or_top15 or (demote_review and positive_evidence)
        if selected:
            failure_mode = "SELECTED_IN_TOP15_V3"
        elif truthy(raw.get("post_llm_demote_flag")):
            failure_mode = "POST_LLM_DEMOTE"
        elif to_float(raw.get("entry_score_0_100")) is not None and (to_float(raw.get("entry_score_0_100")) or 0) < 35:
            failure_mode = "ENTRY_SCORE_BELOW_EXCEPTION_MIN"
        elif raw:
            failure_mode = "NOT_RANKED_IN_SELECTED_SLOTS"
        else:
            failure_mode = "NOT_PRESENT"
        audit.append({
            "ticker": key[0],
            "target_quarter": key[1],
            "selected_in_top15_v3": int(selected),
            "selected_sleeve": "right_tail_exception" if selected else "",
            "miss_failure_mode": failure_mode,
            "routed_visibility_layer": layer,
            "right_tail_evidence_score": diag.get("right_tail_evidence_score", ""),
            "right_tail_recommended_action": diag.get("right_tail_recommended_action", ""),
            "target_visibility_routed": int(visibility),
            "target_actionable_research_routed": int(actionable),
            "target_scout_or_top15_routed": int(scout_or_top15),
            "target_demote_review_routed": int(demote_review),
            "target_buy_underwriting_routed": int(selected),
        })
    return audit


def select_right_tail_queues_from_csv(
    scores_csv: str | Path,
    output_root: str | Path,
    *,
    top15_selected_csv: str | Path | None = None,
    target_events_csv: str | Path | None = None,
    selection_date: str = "",
) -> dict[str, Any]:
    scores_path = Path(scores_csv)
    out = Path(output_root)
    out.mkdir(parents=True, exist_ok=True)
    rows = _read_csv(scores_path)
    warnings: list[str] = []
    top15_path = Path(top15_selected_csv) if top15_selected_csv else None
    if top15_path is None or not top15_path.exists():
        warnings.append("Top15 selected CSV not provided; scout queues may include already-selected Top15 names.")
    queues = build_right_tail_queues(rows, parse_top15_selected_keys(top15_path))
    _write_csv(out / "top15_exception_candidate_queue.csv", queues["top15_exception_candidate_queue"], QUEUE_CSV_FIELDS)
    _write_csv(out / "right_tail_scout_queue.csv", queues["right_tail_scout_queue"], QUEUE_CSV_FIELDS)
    _write_csv(out / "demote_review_queue.csv", queues["demote_review_queue"], QUEUE_CSV_FIELDS)
    _write_csv(out / "thin_signal_watchlist_queue.csv", queues["thin_signal_watchlist_queue"], QUEUE_CSV_FIELDS)
    _write_csv(out / "right_tail_evidence_score_diagnostics.csv", queues["right_tail_evidence_score_diagnostics"], QUEUE_CSV_FIELDS)
    output_paths = {
        "top15_exception_candidate_queue": str(out / "top15_exception_candidate_queue.csv"),
        "right_tail_scout_queue": str(out / "right_tail_scout_queue.csv"),
        "demote_review_queue": str(out / "demote_review_queue.csv"),
        "thin_signal_watchlist_queue": str(out / "thin_signal_watchlist_queue.csv"),
        "right_tail_evidence_score_diagnostics": str(out / "right_tail_evidence_score_diagnostics.csv"),
        "json": str(out / "right_tail_queues.json"),
    }
    if target_events_csv:
        audit = build_target_visibility_audit(rows, queues["right_tail_evidence_score_diagnostics"], read_target_events_csv(Path(target_events_csv)))
        _write_csv(out / "target_miss_rescue_audit.csv", audit, TARGET_AUDIT_FIELDS)
        output_paths["target_miss_rescue_audit"] = str(out / "target_miss_rescue_audit.csv")
    result = {
        "date": selection_date,
        "summary": {
            "top15_exception_candidate_count": len(queues["top15_exception_candidate_queue"]),
            "right_tail_scout_count": len(queues["right_tail_scout_queue"]),
            "demote_review_count": len(queues["demote_review_queue"]),
            "thin_signal_watchlist_count": len(queues["thin_signal_watchlist_queue"]),
            "diagnostics_count": len(queues["right_tail_evidence_score_diagnostics"]),
        },
        "warnings": warnings,
        "output_paths": output_paths,
    }
    (out / "right_tail_queues.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result
