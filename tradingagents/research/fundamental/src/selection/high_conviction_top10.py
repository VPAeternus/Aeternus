"""Deterministic post-score high-conviction Top-N selector."""
from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


HARD_REJECT_DOC_STATUSES = {
    "blocked", "invalid", "missing", "missing_docs", "no_docs", "fetch_failed",
    "error", "unavailable", "not_found", "failed", "blocked_metadata_or_issuer_reality",
}
BAD_CIK_STATUSES = {
    "", "missing", "unresolved", "invalid", "not_found", "no_match", "not_resolved",
    "error", "failed", "blocked_unresolved_cik",
}
CONFIDENCE_LABELS = {"high": 4.0, "medium": 3.0, "low": 2.0}
T5_RESCAN_RE = re.compile(r"(?i)(?:\bT5[_ -]?RESCAN\b|\brescan[_ -]?T5\b)")
EXPLICIT_OVERRIDE_FIELDS = {
    "theme_acceleration_research_visibility",
    "theme_acceleration_rescan_flag",
    "repricing_momentum_priority",
    "repricing_momentum_extension",
}
RM_OVERRIDE_RE = re.compile(r"^rm[1-4]_(?:priority|high_priority|llm_supported|extension|rescan|candidate|signal|confirmed)$")
HP_OVERRIDE_RE = re.compile(r"^hp\d+_(?:priority|high_priority|llm_supported|extension|rescan|candidate|signal|confirmed)$")
TIER_OVERRIDE_RE = re.compile(r"^tier\d+_L\d+_(?:priority|high_priority|llm_supported|rescan|signal|confirmed)$")
OPERATING_SETTING = "high_conviction_top10_v2_final"
RM_SIGNAL_FIELDS = (
    "rm1_low_price_dislocation_momentum",
    "rm2_weak_acceleration",
    "rm3_mid_price_dislocation_momentum",
    "rm4_persistent_repricing_wave",
    "rm_buy_review_flag",
)
HP_SIGNAL_FIELDS = (
    "hp0_high_price_broad",
    "hp1_quality_pullback",
    "hp2_dislocation_momentum_priority",
    "hp2_dislocation_momentum_watch",
    "hp3_large_quality_theme_exception",
    "hp4_score_reacceleration_watch",
    "hp_production_extension",
    "hp_research_extension",
    "hp_LLM_best",
)
DAILY_RECOMMENDATION_BULLETS = [
    "Run broad discovery / source Top-30.",
    "Deep-analyze selected names.",
    "Use portfolio max positions = 10.",
    "Prioritize single-RM-signal bucket candidates.",
    "Be more cautious with RM 2+ unless LLM/theme/valuation evidence is very strong.",
    "Treat HP names as useful but higher-left-tail-risk.",
    "Apply macro permission manually/live until PIT macro fields are historically validated.",
    "Continue forward-validating AKG theme acceleration / T5_RESCAN because historical PIT fields are blank.",
]


@dataclass(frozen=True)
class HighConvictionConfig:
    top_n: int = 10
    score_field: str = "entry_score_0_100"
    min_score: float = 70.0
    min_confidence: float = 3.0
    allow_overrides: bool = True
    require_confidence: bool = True
    coverage_gating: bool = False
    core_target: int = 6
    momentum_target: int = 2
    opportunistic_target: int = 2
    theme_acceleration_override_score: float = 80.0
    selection_date: str = ""


def normalize_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    base = asdict(HighConvictionConfig())
    if config:
        for key, value in config.items():
            if key in base and value is not None:
                base[key] = value
    base["top_n"] = int(base["top_n"])
    if base["top_n"] <= 0:
        raise ValueError("top_n must be > 0")
    base["min_score"] = float(base["min_score"])
    base["min_confidence"] = float(base["min_confidence"])
    base["theme_acceleration_override_score"] = float(base["theme_acceleration_override_score"])
    return base


def select_high_conviction_top10(
    rows: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any] | None,
    coverage_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Select high-conviction rows after final fundamental scores are already computed."""
    cfg = normalize_config(config)
    coverage_enabled = bool(cfg.get("coverage_gating"))
    coverage = _build_coverage(coverage_rows or []) if coverage_enabled else {}
    eligible: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    warnings: list[str] = []

    for idx, raw in enumerate(rows):
        assessed = _assess_row(dict(raw), idx, cfg, coverage, coverage_enabled)
        if assessed["selected_candidate"]:
            eligible.append(assessed)
        else:
            rejected.append(assessed)

    ranked = sorted(
        eligible,
        key=lambda r: (-r["composite_score"], -r["score"], -r["confidence_sort"], r["ticker"]),
    )
    selected = ranked[: int(cfg["top_n"])]
    _annotate_soft_balance(selected, cfg, warnings)
    selected_ids = {r["_row_id"] for r in selected}
    for rank, row in enumerate(selected, start=1):
        row["selection_rank"] = rank
        row["selected"] = True
        _annotate_operating_guidance(row)
    for row in ranked:
        if row["_row_id"] not in selected_ids:
            row["selected"] = False
            row["reason_codes"].append("NOT_IN_TOP_N")
            rejected.append(row)

    if len(selected) < int(cfg["top_n"]):
        warnings.append(f"SHORTFALL_SELECTED_{len(selected)}_OF_{cfg['top_n']}")

    selected_public = [_public_row(r) for r in selected]
    rejected_public = [_public_row(r) for r in rejected]
    return {
        "selected_rows": selected_public,
        "rejected_rows": rejected_public,
        "selected": selected_public,
        "rejected": rejected_public,
        "summary": {
            "input_count": len(rows),
            "eligible_count": len(ranked),
            "selected_count": len(selected),
            "rejected_count": len(rejected),
            "top_n": cfg["top_n"],
            "warnings": warnings,
        },
        "config_snapshot": cfg,
        "config": cfg,
        "operating_recommendation": _operating_recommendation_snapshot(selected_public, cfg),
    }


def select_from_csv(
    scores_csv: str | Path,
    output_root: str | Path,
    config: Mapping[str, Any] | None,
    coverage_manifest: str | Path | None = None,
) -> dict[str, Any]:
    scores_path = Path(scores_csv)
    out_root = Path(output_root)
    rows = _read_csv(scores_path)
    coverage_rows = _read_csv(Path(coverage_manifest)) if coverage_manifest else None
    result = select_high_conviction_top10(rows, config, coverage_rows)
    out_root.mkdir(parents=True, exist_ok=True)
    date = str(result["config_snapshot"].get("selection_date") or "")
    csv_path = out_root / "high_conviction_top10.csv"
    json_path = out_root / "high_conviction_top10.json"
    recommendation_path = out_root / "high_conviction_top10_daily_recommendation.md"
    result["date"] = date
    result["output_paths"] = {"csv": str(csv_path), "json": str(json_path), "recommendation_md": str(recommendation_path)}
    _write_csv(csv_path, result["selected_rows"])
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    recommendation_path.write_text(_daily_recommendation_markdown(result), encoding="utf-8")
    return result


def _signal_bucket(row: Mapping[str, Any], fields: Sequence[str]) -> tuple[str, list[str]]:
    active = [field for field in fields if field in row and _truthy(row.get(field))]
    if len(active) >= 2:
        return "2+", active
    return str(len(active)), active


def _annotate_operating_guidance(row: dict[str, Any]) -> None:
    rm_bucket, rm_active = _signal_bucket(row, RM_SIGNAL_FIELDS)
    hp_bucket, hp_active = _signal_bucket(row, HP_SIGNAL_FIELDS)
    row["operating_setting"] = OPERATING_SETTING
    row["operating_setting_validation_status"] = "observed_data_v2_not_full_akg_macro_validation"
    row["portfolio_max_positions"] = 10
    row["rm_signal_bucket"] = rm_bucket
    row["rm_active_fields"] = rm_active
    if rm_bucket == "1":
        row["rm_operating_guidance"] = "PRIORITIZE_SINGLE_RM_SIGNAL_BUCKET"
    elif rm_bucket == "2+":
        row["rm_operating_guidance"] = "CAUTION_MULTI_RM_SIGNAL_BUCKET_REQUIRES_STRONG_LLM_THEME_VALUATION"
    else:
        row["rm_operating_guidance"] = "NO_RM_SIGNAL_BUCKET_PRIORITY"
    row["hp_signal_bucket"] = hp_bucket
    row["hp_active_fields"] = hp_active
    row["hp_operating_guidance"] = "HP_USEFUL_BUT_HIGHER_LEFT_TAIL_RISK" if hp_bucket != "0" else "NO_HP_LEFT_TAIL_RISK_FLAG"
    row["macro_permission_guidance"] = "APPLY_MANUAL_LIVE_MACRO_PERMISSION_UNTIL_PIT_MACRO_VALIDATED"
    row["akg_theme_validation_guidance"] = "FORWARD_VALIDATE_AKG_THEME_ACCELERATION_AND_T5_RESCAN"


def _operating_recommendation_snapshot(selected: Sequence[Mapping[str, Any]], cfg: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "operating_setting": OPERATING_SETTING,
        "validation_status": "observed-data v2; not fully validated AKG+macro production v2",
        "top_n": int(cfg.get("top_n", 10) or 10),
        "portfolio_max_positions": 10,
        "recommendation": "Use high_conviction_top10_v2_final as the operating setting, but treat it as observed-data v2, not fully validated AKG+macro v2.",
        "operational_steps": DAILY_RECOMMENDATION_BULLETS,
        "selected_count": len(selected),
        "single_rm_signal_selected_count": sum(1 for row in selected if str(row.get("rm_signal_bucket", "")) == "1"),
        "multi_rm_signal_selected_count": sum(1 for row in selected if str(row.get("rm_signal_bucket", "")) == "2+"),
        "hp_selected_count": sum(1 for row in selected if str(row.get("hp_signal_bucket", "0")) != "0"),
        "rm_bucket_note": "rm_signal_bucket=1 means exactly one RM-related signal was active; it is not necessarily the literal rm1_low_price_dislocation_momentum rule.",
    }


def _daily_recommendation_markdown(result: Mapping[str, Any]) -> str:
    rec = result.get("operating_recommendation", {})
    date = str(result.get("date") or result.get("config_snapshot", {}).get("selection_date") or "")
    rows = result.get("selected_rows", [])
    lines = [
        "# Fundamental High-Conviction Top-10 Daily Recommendation",
        "",
        f"Date: `{date}`" if date else "Date: `not_provided`",
        f"Operating setting: `{OPERATING_SETTING}`",
        "Validation label: `observed-data v2, not fully validated AKG+macro production v2`",
        "",
        "## Recommendation",
        "",
        str(rec.get("recommendation") or "Use high_conviction_top10_v2_final as the operating setting, with observed-data caveats."),
        "",
        "## Operational checklist",
        "",
    ]
    lines.extend(f"{idx}. {bullet}" for idx, bullet in enumerate(DAILY_RECOMMENDATION_BULLETS, start=1))
    lines.extend(
        [
            "",
            "## RM bucket wording",
            "",
            "`rm_signal_bucket=1` means exactly one RM-related signal was active. It is not necessarily the literal `rm1_low_price_dislocation_momentum` rule.",
            "`rm_signal_bucket=2+` means multiple RM-related signals were active and should be treated more cautiously unless LLM/theme/valuation evidence is very strong.",
            "",
            "## Selected names",
            "",
            "| rank | ticker | score | composite | rm_signal_bucket | rm_guidance | hp_signal_bucket | hp_guidance |",
            "| --- | --- | ---: | ---: | --- | --- | --- | --- |",
        ]
    )
    for row in rows:
        lines.append(
            "| {rank} | {ticker} | {score} | {composite} | {rm_bucket} | {rm_guidance} | {hp_bucket} | {hp_guidance} |".format(
                rank=row.get("selection_rank", ""),
                ticker=row.get("ticker", ""),
                score=row.get("score", row.get("entry_score_0_100", "")),
                composite=row.get("composite_score", ""),
                rm_bucket=row.get("rm_signal_bucket", ""),
                rm_guidance=row.get("rm_operating_guidance", ""),
                hp_bucket=row.get("hp_signal_bucket", ""),
                hp_guidance=row.get("hp_operating_guidance", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Caveats",
            "",
            "- Apply macro permission manually/live until PIT macro fields are historically validated.",
            "- Continue forward-validating AKG theme acceleration / T5_RESCAN because historical PIT fields are blank.",
            "- This artifact is a daily operating recommendation after finalized dealflow/fundamental scores, not a claim that full AKG+macro production v2 has been historically validated.",
            "",
        ]
    )
    return "\n".join(lines)


def _assess_row(
    row: dict[str, Any],
    idx: int,
    cfg: dict[str, Any],
    coverage: dict[str, dict[str, int]],
    coverage_enabled: bool,
) -> dict[str, Any]:
    ticker = str(row.get("ticker") or row.get("symbol") or "").strip().upper()
    reasons: list[str] = []
    contributions: dict[str, float] = {}
    score = _to_float(row.get(cfg["score_field"]))
    confidence_present = "confidence" in row and str(row.get("confidence", "")).strip() != ""
    confidence = _parse_confidence(row.get("confidence")) if confidence_present else None

    if not ticker:
        reasons.append("MISSING_TICKER")
    if score is None:
        reasons.append("MISSING_OR_NON_NUMERIC_SCORE")
    if _bad_cik(row):
        reasons.append("BAD_CIK")
    if str(row.get("hard_reject_reason", "")).strip():
        reasons.append("HARD_REJECT_REASON_PRESENT")
    if _bad_doc_status(row):
        reasons.append("BAD_DOCUMENT_STATUS")
    if confidence is None:
        if cfg.get("require_confidence"):
            reasons.append("MISSING_CONFIDENCE")
    elif confidence < float(cfg["min_confidence"]):
        reasons.append("CONFIDENCE_BELOW_THRESHOLD")
    if coverage_enabled:
        cov = coverage.get(ticker, {"needs_fetch": 0, "cached_ready": 0})
        if cov["needs_fetch"] > 0:
            reasons.append("SEC_COVERAGE_NEEDS_FETCH")
        if cov["cached_ready"] == 0:
            reasons.append("SEC_COVERAGE_ZERO_CACHED_READY")

    override_reasons = _override_reasons(row, cfg) if cfg.get("allow_overrides") else []
    if score is not None and score < float(cfg["min_score"]) and not override_reasons:
        reasons.append("SCORE_BELOW_THRESHOLD")

    hard_reasons = [r for r in reasons if r != "SCORE_BELOW_THRESHOLD"]
    selected_candidate = not hard_reasons and (score is not None) and (score >= float(cfg["min_score"]) or bool(override_reasons))
    comp = 0.0
    if score is not None:
        comp += score
        contributions["score"] = score
    if confidence is not None:
        contributions["confidence_bonus"] = confidence * 2.0
        comp += contributions["confidence_bonus"]

    lane = _lane(row)
    return {
        **row,
        "_row_id": idx,
        "ticker": ticker,
        "score": score if score is not None else "",
        "confidence_numeric": confidence if confidence is not None else "",
        "confidence_sort": confidence if confidence is not None else -1.0,
        "lane_normalized": lane,
        "composite_score": round(comp, 6),
        "composite_contributions": contributions,
        "override_reason_codes": override_reasons,
        "reason_codes": reasons,
        "selected_candidate": selected_candidate,
        "selected": False,
    }


def _annotate_soft_balance(selected: list[dict[str, Any]], cfg: dict[str, Any], warnings: list[str]) -> None:
    targets = {"core": int(cfg["core_target"]), "momentum": int(cfg["momentum_target"]), "opportunistic": int(cfg["opportunistic_target"])}
    counts = {lane: 0 for lane in targets}
    for row in selected:
        counts[row["lane_normalized"]] = counts.get(row["lane_normalized"], 0) + 1
    for lane, target in targets.items():
        if target > 0 and counts.get(lane, 0) == 0:
            warnings.append(f"SOFT_BALANCE_NO_{lane.upper()}_LANE")
    warnings.append("SOFT_BALANCE_ANNOTATION_ONLY_RANKING_DOMINATES")
    for row in selected:
        row["lane_mix_selected_count"] = counts.get(row["lane_normalized"], 0)
        row["lane_target"] = targets.get(row["lane_normalized"], 0)


def _build_coverage(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for row in rows:
        ticker = str(row.get("ticker") or row.get("symbol") or "").strip().upper()
        status = str(row.get("status") or row.get("coverage_status") or row.get("cache_status") or "").strip().upper()
        if not ticker:
            continue
        bucket = out.setdefault(ticker, {"needs_fetch": 0, "cached_ready": 0})
        if status == "NEEDS_FETCH":
            bucket["needs_fetch"] += 1
        if status == "CACHED_READY":
            bucket["cached_ready"] += 1
    return out


def _bad_cik(row: Mapping[str, Any]) -> bool:
    has_cik = "cik" in row
    has_status = "cik_status" in row
    if has_cik and _normalize_cik(row.get("cik")) == "":
        return True
    if has_status and str(row.get("cik_status", "")).strip().lower() in BAD_CIK_STATUSES:
        return True
    return False


def _normalize_cik(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    if text.lower() in {"", "nan", "none", "null"}:
        return ""
    numeric = _to_float(text)
    if numeric is not None:
        if not numeric.is_integer() or numeric < 0:
            return ""
        text = str(int(numeric))
    text = text.lstrip("0") or "0"
    if not text.isdigit():
        return ""
    return text.zfill(10)


def _bad_doc_status(row: Mapping[str, Any]) -> bool:
    if "document_status" not in row:
        return False
    status = str(row.get("document_status", "")).strip().lower()
    if not status:
        return False
    normalized = re.sub(r"[^a-z0-9]+", "_", status).strip("_")
    if normalized in HARD_REJECT_DOC_STATUSES:
        return True
    obvious_blocked_prefixes = ("blocked_", "invalid_", "missing_", "failed_", "fetch_failed_")
    return normalized.startswith(obvious_blocked_prefixes) or normalized.endswith("_failed")


def _override_reasons(row: Mapping[str, Any], cfg: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    tas = _to_float(row.get("theme_acceleration_score"))
    if tas is not None and tas >= float(cfg["theme_acceleration_override_score"]):
        reasons.append("OVERRIDE_THEME_ACCELERATION_SCORE")
    for key, value in row.items():
        low = str(key).lower()
        if _is_allowed_override_field(low) and _truthy(value):
            reasons.append(f"OVERRIDE_{str(key).upper()}")
    text = " ".join(str(row.get(k, "")) for k in ("source", "thesis_tags", "risk_tags"))
    if T5_RESCAN_RE.search(text):
        reasons.append("OVERRIDE_T5_RESCAN")
    return sorted(set(reasons))


def _is_allowed_override_field(key: str) -> bool:
    return (
        key in EXPLICIT_OVERRIDE_FIELDS
        or bool(RM_OVERRIDE_RE.fullmatch(key))
        or bool(HP_OVERRIDE_RE.fullmatch(key))
        or bool(TIER_OVERRIDE_RE.fullmatch(key))
    )


def _lane(row: Mapping[str, Any]) -> str:
    text = str(row.get("lane") or row.get("decision_type") or "").strip().lower()
    if "opportun" in text:
        return "opportunistic"
    if "momentum" in text or "repricing" in text:
        return "momentum"
    return "core"


def _truthy(value: Any) -> bool:
    text = str(value if value is not None else "").strip().lower()
    if text in {"", "nan", "none", "null", "false", "no", "n", "low", "0"}:
        return False
    numeric = _to_float(text)
    if numeric is not None:
        return numeric != 0
    return text in {"1", "true", "yes", "y", "high", "priority", "t5_rescan"}


def _parse_confidence(value: Any) -> float | None:
    numeric = _to_float(value)
    if numeric is not None:
        return numeric
    return CONFIDENCE_LABELS.get(str(value).strip().lower())


def _to_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames or ["ticker"])
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v for k, v in row.items()})


def _public_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if not k.startswith("_") and k not in {"selected_candidate", "confidence_sort"}}
