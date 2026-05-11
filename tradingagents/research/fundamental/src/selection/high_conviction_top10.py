"""Deterministic post-score high-conviction Top-N selector."""
from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .signal_utils import (
    HP_SIGNAL_FIELDS,
    RM_SIGNAL_FIELDS,
    hp_signal_bucket,
    label_signal_count,
    rm_signal_bucket,
    signal_bucket,
    signal_count,
    to_float,
    truthy,
)


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
TOP15_OPERATING_SETTING = "high_conviction_top15_v3_exception_sleeve"
CORE_DETERIORATION_REVIEW_ACTION = "manual_review_before_buy_underwriting"
CORE_DETERIORATION_STRICT_ACTION = "move_from_core_buy_underwriting_to_scout_review_unless_pm_override"
CORE_DETERIORATION_FIELDS = [
    "ticker", "quarter", "selection_rank", "selected_sleeve", "entry_score_0_100",
    "score_change", "negative_revision_risk", "pre_llm_fundamental_bucket", "primary_theme",
    "core_deterioration_rm_count", "core_deterioration_hp_count", "demoted_market_repricing_score",
    "high_score_deterioration_flag", "weak_no_theme_repricing_stack_flag", "core_deterioration_rank_context_flag",
    "core_deterioration_review_flag", "core_deterioration_downgrade_flag", "core_deterioration_strict_override_required",
    "core_deterioration_recommended_action", "core_deterioration_reason_codes",
]
CORE_DETERIORATION_REFILL_MODES = {"strict", "downgrade", "all_review"}
CORE_DETERIORATION_REFILL_FIELDS = [
    "variant", "quarter", "mode", "demoted_ticker", "replacement_ticker",
    "demoted_core_candidate_rank", "replacement_core_candidate_rank",
    "demoted_entry_score_0_100", "replacement_entry_score_0_100",
    "demoted_score_change", "demoted_negative_revision_risk", "demoted_pre_llm_fundamental_bucket",
    "demoted_primary_theme", "demoted_rm_count", "demoted_hp_count", "demoted_market_repricing_score",
    "high_score_deterioration_flag", "weak_no_theme_repricing_stack_flag",
    "core_deterioration_review_flag", "core_deterioration_downgrade_flag", "core_deterioration_strict_override_required",
    "core_deterioration_reason_codes", "demoted_return_90d_pct", "replacement_return_90d_pct", "replacement_delta_90d_pct",
]
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


@dataclass(frozen=True)
class RightTailExceptionConfig:
    enabled: bool = False
    core_n: int = 10
    exception_slots: int = 5
    min_exception_entry_score: float = 20.0
    near_threshold_entry_score: float = 65.0
    max_rm2plus_slots: int = 2
    max_no_theme_no_llm_exceptions: int = 2
    max_same_theme: int = 2
    max_same_sector: int = 3


@dataclass(frozen=True)
class CoreDeteriorationRefillConfig:
    enabled: bool = False
    mode: str = "strict"
    block_deterioration_from_exceptions: bool = True


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


def _normalize_core_deterioration_refill_config(config: Mapping[str, Any] | None) -> CoreDeteriorationRefillConfig:
    nested = config.get("core_deterioration_refill") if isinstance(config, Mapping) and isinstance(config.get("core_deterioration_refill"), Mapping) else config
    enabled = bool(nested.get("enabled", False)) if isinstance(nested, Mapping) else False
    mode = str(nested.get("mode", "strict") if isinstance(nested, Mapping) else "strict").strip().lower()
    if mode not in CORE_DETERIORATION_REFILL_MODES:
        raise ValueError(f"core deterioration refill mode must be one of {sorted(CORE_DETERIORATION_REFILL_MODES)}")
    block = bool(nested.get("block_deterioration_from_exceptions", True)) if isinstance(nested, Mapping) else True
    return CoreDeteriorationRefillConfig(enabled=enabled, mode=mode, block_deterioration_from_exceptions=block)


def _normalize_exception_config(config: Mapping[str, Any] | RightTailExceptionConfig | None) -> RightTailExceptionConfig:
    base = asdict(RightTailExceptionConfig())
    if isinstance(config, RightTailExceptionConfig):
        base.update(asdict(config))
    elif config:
        nested = config.get("right_tail_exception_config") if isinstance(config.get("right_tail_exception_config"), Mapping) else config
        for key, value in nested.items():
            if key in base and value is not None:
                base[key] = value
    base["enabled"] = bool(base["enabled"])
    for key in ("core_n", "exception_slots", "max_rm2plus_slots", "max_no_theme_no_llm_exceptions", "max_same_theme", "max_same_sector"):
        base[key] = int(base[key])
    for key in ("min_exception_entry_score", "near_threshold_entry_score"):
        base[key] = float(base[key])
    if base["core_n"] <= 0 or base["exception_slots"] < 0:
        raise ValueError("core_n must be > 0 and exception_slots must be >= 0")
    return RightTailExceptionConfig(**base)


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


def select_high_conviction_top15_exception_sleeve(
    rows: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any] | RightTailExceptionConfig | None,
    coverage_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    cfg = _normalize_exception_config(config)
    core_config = {
        "top_n": int(cfg.core_n),
        "selection_date": str(getattr(config, "selection_date", "") if not isinstance(config, Mapping) else config.get("selection_date", "")),
        "coverage_gating": bool(config.get("coverage_gating", False)) if isinstance(config, Mapping) else False,
    }
    coverage_enabled = bool(core_config.get("coverage_gating"))
    coverage = _build_coverage(coverage_rows or []) if coverage_enabled else {}
    core_result = select_high_conviction_top10(rows, core_config, coverage_rows)
    core_rows = [dict(r) for r in core_result["selected_rows"]]
    for rank, row in enumerate(core_rows, start=1):
        row["selected_sleeve"] = "core"
        row["selected_sleeve_rank"] = rank
        row["portfolio_treatment"] = "core_buy_underwriting"
        row.setdefault("right_tail_exception_score", "")
        row.setdefault("right_tail_exception_reason_codes", [])
        row.setdefault("right_tail_exception_warning_codes", [])
        _annotate_operating_guidance(row)
    exceptions, warnings = ([], ["EXCEPTION_SLEEVE_DISABLED"]) if not cfg.enabled else _select_exception_sleeve(core_rows, rows, cfg, coverage, coverage_enabled)
    selected = core_rows + exceptions
    for row in selected:
        row["operating_setting"] = TOP15_OPERATING_SETTING
        row["operating_setting_validation_status"] = "observed_data_top15_exception_sleeve_not_full_akg_macro_validation"
    return {
        "selected_rows": selected,
        "selected": selected,
        "core_rows": core_rows,
        "exception_rows": exceptions,
        "rejected_rows": core_result.get("rejected_rows", []),
        "rejected": core_result.get("rejected_rows", []),
        "summary": {
            "input_count": len(rows),
            "selected_count": len(selected),
            "core_count": len(core_rows),
            "exception_count": len(exceptions),
            "top_n": len(selected),
            "warnings": list(core_result.get("summary", {}).get("warnings", [])) + warnings,
        },
        "config_snapshot": {**core_result.get("config_snapshot", {}), "right_tail_exception_config": asdict(cfg)},
        "config": {**core_result.get("config_snapshot", {}), "right_tail_exception_config": asdict(cfg)},
        "operating_recommendation": _top15_operating_recommendation_snapshot(selected, cfg),
    }


def _first_nonblank(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key not in row:
            continue
        value = row.get(key)
        if value is None:
            continue
        if isinstance(value, str) and value.strip() == "":
            continue
        return value
    return None


def core_deterioration_flags(row: Mapping[str, Any]) -> dict[str, Any]:
    sleeve = str(row.get("selected_sleeve", "")).strip().lower()
    selected_rank = to_float(_first_nonblank(row, "selection_rank", "selected_sleeve_rank"))
    rank_int = int(selected_rank) if selected_rank is not None else None
    entry_score = to_float(_first_nonblank(row, "entry_score_0_100", "score"))
    score_change = to_float(row.get("score_change"))
    negative_revision_risk = to_float(row.get("negative_revision_risk"))
    market_repricing_score = to_float(_first_nonblank(row, "demoted_market_repricing_score", "market_repricing_score")) or 0.0
    rm_count = label_signal_count(row, RM_SIGNAL_FIELDS)
    hp_count = label_signal_count(row, HP_SIGNAL_FIELDS)
    theme_blank = not str(row.get("primary_theme") or "").strip()
    weak_pre_llm = str(row.get("pre_llm_fundamental_bucket") or "").strip().lower() == "weak"
    high_score = bool(
        entry_score is not None and entry_score >= 80
        and score_change is not None and score_change <= -1
        and negative_revision_risk is not None and negative_revision_risk >= 2
    )
    weak_stack = bool(
        theme_blank
        and weak_pre_llm
        and (rm_count >= 3 or (hp_count > 0 and market_repricing_score >= 6))
        and ((score_change is not None and score_change <= 0) or (negative_revision_risk is not None and negative_revision_risk >= 2))
    )
    review = bool(sleeve == "core" and (high_score or weak_stack))
    downgrade = bool(review and (weak_stack or (theme_blank and weak_pre_llm)))
    strict = bool(review and high_score and weak_stack)
    rank_context = rank_int in {7, 8}
    reasons: list[str] = []
    if high_score:
        reasons.append("high_score_deterioration")
    if weak_stack:
        reasons.append("weak_no_theme_repricing_stack")
    if rank_context:
        reasons.append("selection_rank_7_or_8" if review else "rank_7_8_context_only")
    action = CORE_DETERIORATION_STRICT_ACTION if strict else CORE_DETERIORATION_REVIEW_ACTION if review else ""
    return {
        "core_deterioration_rm_count": rm_count,
        "core_deterioration_hp_count": hp_count,
        "demoted_market_repricing_score": market_repricing_score,
        "high_score_deterioration_flag": int(high_score),
        "weak_no_theme_repricing_stack_flag": int(weak_stack),
        "core_deterioration_rank_context_flag": int(rank_context),
        "core_deterioration_review_flag": int(review),
        "core_deterioration_downgrade_flag": int(downgrade),
        "core_deterioration_strict_override_required": int(strict),
        "core_deterioration_recommended_action": action,
        "core_deterioration_reason_codes": ";".join(reasons),
    }


def should_refill_demote_core_row(row: Mapping[str, Any], mode: str = "strict") -> bool:
    mode = str(mode or "strict").strip().lower()
    if mode not in CORE_DETERIORATION_REFILL_MODES:
        raise ValueError(f"core deterioration refill mode must be one of {sorted(CORE_DETERIORATION_REFILL_MODES)}")
    flags = core_deterioration_flags(row)
    if mode == "strict":
        return bool(flags.get("core_deterioration_strict_override_required"))
    if mode == "downgrade":
        return bool(flags.get("core_deterioration_downgrade_flag"))
    return bool(flags.get("core_deterioration_review_flag"))



def build_core_deterioration_review_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    review_rows: list[dict[str, Any]] = []
    for row in rows:
        flags = core_deterioration_flags(row)
        if not flags["core_deterioration_review_flag"]:
            continue
        review_rows.append({
            "ticker": str(row.get("ticker", "")).upper(),
            "quarter": row.get("quarter", ""),
            "selection_rank": row.get("selection_rank", row.get("selected_sleeve_rank", "")),
            "selected_sleeve": row.get("selected_sleeve", ""),
            "entry_score_0_100": row.get("entry_score_0_100", row.get("score", "")),
            "score_change": row.get("score_change", ""),
            "negative_revision_risk": row.get("negative_revision_risk", ""),
            "pre_llm_fundamental_bucket": row.get("pre_llm_fundamental_bucket", ""),
            "primary_theme": row.get("primary_theme", ""),
            **flags,
        })
    return review_rows


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


def select_top15_from_csv(
    scores_csv: str | Path,
    output_root: str | Path,
    config: Mapping[str, Any] | RightTailExceptionConfig | None,
    coverage_manifest: str | Path | None = None,
) -> dict[str, Any]:
    scores_path = Path(scores_csv)
    out_root = Path(output_root)
    rows = _read_csv(scores_path)
    coverage_rows = _read_csv(Path(coverage_manifest)) if coverage_manifest else None
    result = select_high_conviction_top15_exception_sleeve(rows, config, coverage_rows)
    out_root.mkdir(parents=True, exist_ok=True)
    date = str(result["config_snapshot"].get("selection_date") or (config.get("selection_date", "") if isinstance(config, Mapping) else ""))
    csv_path = out_root / "high_conviction_top15.csv"
    json_path = out_root / "high_conviction_top15.json"
    recommendation_path = out_root / "high_conviction_top15_daily_recommendation.md"
    core_deterioration_path = out_root / "core_deterioration_review_queue.csv"
    core_deterioration_rows = build_core_deterioration_review_rows(result["selected_rows"])
    result["core_deterioration_review_rows"] = core_deterioration_rows
    result["core_deterioration_review_count"] = len(core_deterioration_rows)
    result["date"] = date
    result["output_paths"] = {"csv": str(csv_path), "json": str(json_path), "recommendation_md": str(recommendation_path), "core_deterioration_review_queue": str(core_deterioration_path)}
    _write_csv(csv_path, result["selected_rows"])
    _write_csv_with_fields(core_deterioration_path, core_deterioration_rows, CORE_DETERIORATION_FIELDS)
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    recommendation_path.write_text(_daily_recommendation_markdown(result), encoding="utf-8")
    return result


_truthy = truthy
_to_float = to_float
_signal_count = signal_count
_signal_bucket = signal_bucket


def _single_rm_signal_bucket(row: Mapping[str, Any]) -> bool:
    return _signal_count(row, RM_SIGNAL_FIELDS) == 1


def _rm_signal_bucket(row: Mapping[str, Any]) -> str:
    return rm_signal_bucket(row)


def _hp_signal_bucket(row: Mapping[str, Any]) -> str:
    return hp_signal_bucket(row)


def _has_theme_or_akg_confirmation(row: Mapping[str, Any]) -> bool:
    return bool(str(row.get("primary_theme", "")).strip()) or _to_float(row.get("theme_tailwind_score")) not in (None, 0.0) or _truthy(row.get("theme_acceleration_research_visibility")) or str(row.get("akg_universe_tier", "")).strip().upper() == "T5_RESCAN"


def _has_llm_or_hp_confirmation(row: Mapping[str, Any]) -> bool:
    return _truthy(row.get("hp_LLM_best")) or _signal_count(row, HP_SIGNAL_FIELDS) > 0


def _is_right_tail_exception_candidate(
    row: Mapping[str, Any],
    cfg: RightTailExceptionConfig,
    coverage: dict[str, dict[str, int]] | None = None,
    coverage_enabled: bool = False,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    assessed = _assess_row(dict(row), 0, normalize_config({"min_score": 0, "require_confidence": False}), coverage or {}, coverage_enabled)
    hard = [r for r in assessed["reason_codes"] if r != "SCORE_BELOW_THRESHOLD"]
    if hard:
        return False, hard
    if str(row.get("hard_reject_reason", "")).strip():
        return False, ["HARD_REJECT_REASON_PRESENT"]
    if _truthy(row.get("post_llm_demote_flag")):
        return False, ["POST_LLM_DEMOTE"]
    score = _to_float(row.get("entry_score_0_100"))
    if score is None or score < cfg.min_exception_entry_score:
        return False, ["ENTRY_SCORE_BELOW_EXCEPTION_MIN"]
    near = score >= cfg.near_threshold_entry_score and _truthy(row.get("rm_buy_review_flag")) and (_truthy(row.get("hp_LLM_best")) or _signal_count(row, HP_SIGNAL_FIELDS) > 0 or (_to_float(row.get("market_repricing_score")) or 0) >= 10)
    signals = []
    checks = {
        "SINGLE_RM_SIGNAL_BUCKET": _single_rm_signal_bucket(row),
        "RM_BUY_REVIEW": _truthy(row.get("rm_buy_review_flag")),
        "REPRICING_MOMENTUM_PRIORITY": _truthy(row.get("repricing_momentum_priority")),
        "MARKET_REPRICING": (_to_float(row.get("market_repricing_score")) or 0) >= 10,
        "HP_LLM_BEST": _truthy(row.get("hp_LLM_best")),
        "HP_SIGNAL": _signal_count(row, HP_SIGNAL_FIELDS) > 0,
        "THEME_TAILWIND": (_to_float(row.get("theme_tailwind_score")) or 0) > 0,
        "PRIMARY_THEME": bool(str(row.get("primary_theme", "")).strip()),
        "THEME_ACCELERATION_VISIBILITY": _truthy(row.get("theme_acceleration_research_visibility")),
        "AKG_T5_RESCAN": str(row.get("akg_universe_tier", "")).strip().upper() == "T5_RESCAN",
    }
    signals = [k for k, v in checks.items() if v]
    if near:
        signals.append("NEAR_THRESHOLD_EXCEPTION")
    return (bool(signals), signals if signals else ["NO_RIGHT_TAIL_SIGNAL"])


def _right_tail_exception_score(row: Mapping[str, Any]) -> tuple[float, dict[str, float]]:
    parts: dict[str, float] = {"entry_score_0_100": _to_float(row.get("entry_score_0_100")) or 0.0}
    adders = [
        ("single_rm_signal_bucket", 15, _single_rm_signal_bucket(row)),
        ("rm_buy_review_flag", 8, _truthy(row.get("rm_buy_review_flag"))),
        ("repricing_momentum_priority", 8, _truthy(row.get("repricing_momentum_priority"))),
        ("market_repricing_score_gte_10", 8, (_to_float(row.get("market_repricing_score")) or 0) >= 10),
        ("hp_LLM_best", 8, _truthy(row.get("hp_LLM_best"))),
        ("hp_signal_count", 6, _signal_count(row, HP_SIGNAL_FIELDS) > 0),
        ("primary_theme", 8, bool(str(row.get("primary_theme", "")).strip())),
        ("theme_tailwind_score", 6, (_to_float(row.get("theme_tailwind_score")) or 0) > 0),
        ("theme_acceleration_research_visibility", 10, _truthy(row.get("theme_acceleration_research_visibility"))),
        ("akg_t5_rescan", 8, str(row.get("akg_universe_tier", "")).strip().upper() == "T5_RESCAN"),
    ]
    for name, value, ok in adders:
        if ok:
            parts[name] = float(value)
    if _rm_signal_bucket(row) == "2+" and not (_has_theme_or_akg_confirmation(row) or _has_llm_or_hp_confirmation(row)):
        parts["rm2plus_no_confirmation_penalty"] = -10.0
    if (_to_float(row.get("risk_penalty_score")) or 0) >= 10:
        parts["risk_penalty"] = -10.0
    if _truthy(row.get("post_llm_demote_flag")):
        parts["post_llm_demote_penalty"] = -15.0
    return round(sum(parts.values()), 6), parts


def _select_exception_sleeve(
    core_rows: Sequence[Mapping[str, Any]],
    all_rows: Sequence[Mapping[str, Any]],
    cfg: RightTailExceptionConfig,
    coverage: dict[str, dict[str, int]] | None = None,
    coverage_enabled: bool = False,
    blocked_tickers: set[str] | None = None,
) -> tuple[list[dict], list[str]]:
    core_tickers = {str(r.get("ticker", "")).upper() for r in core_rows}
    core_tickers |= {str(t).upper() for t in (blocked_tickers or set())}
    candidates: list[dict[str, Any]] = []
    for raw in all_rows:
        row = dict(raw)
        ticker = str(row.get("ticker") or row.get("symbol") or "").strip().upper()
        if not ticker or ticker in core_tickers:
            continue
        ok, reasons = _is_right_tail_exception_candidate(row, cfg, coverage, coverage_enabled)
        if not ok:
            continue
        score, parts = _right_tail_exception_score(row)
        row["ticker"] = ticker
        row["right_tail_exception_score"] = score
        row["right_tail_exception_score_contributions"] = parts
        row["right_tail_exception_reason_codes"] = reasons
        _annotate_operating_guidance(row)
        candidates.append(row)
    candidates.sort(key=lambda r: (-(r["right_tail_exception_score"]), -(_to_float(r.get("entry_score_0_100")) or 0), -(_to_float(r.get("market_repricing_score")) or 0), r["ticker"]))
    selected: list[dict] = []
    selected_ids: set[int] = set()
    warnings: list[str] = []
    rm2plain = no_theme = 0
    theme_counts: dict[str, int] = {}
    sector_counts: dict[str, int] = {}

    def try_add(row: dict[str, Any]) -> bool:
        nonlocal rm2plain, no_theme
        if len(selected) >= cfg.exception_slots:
            return False
        confirms = _has_theme_or_akg_confirmation(row) or _has_llm_or_hp_confirmation(row)
        theme = str(row.get("primary_theme", "")).strip().lower()
        sector = str(row.get("sector", "")).strip().lower()
        if _rm_signal_bucket(row) == "2+" and not confirms and rm2plain >= cfg.max_rm2plus_slots:
            warnings.append("MAX_RM2PLUS_SLOTS_REACHED")
            return False
        if not confirms and no_theme >= cfg.max_no_theme_no_llm_exceptions:
            warnings.append("MAX_NO_THEME_NO_LLM_EXCEPTIONS_REACHED")
            return False
        if theme and theme_counts.get(theme, 0) >= cfg.max_same_theme:
            warnings.append("MAX_SAME_THEME_REACHED")
            return False
        if sector and sector_counts.get(sector, 0) >= cfg.max_same_sector:
            warnings.append("MAX_SAME_SECTOR_REACHED")
            return False
        selected.append(row)
        selected_ids.add(id(row))
        if _rm_signal_bucket(row) == "2+" and not confirms:
            rm2plain += 1
        if not confirms:
            no_theme += 1
        if theme:
            theme_counts[theme] = theme_counts.get(theme, 0) + 1
        if sector:
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
        return True

    single_rm_candidates = [row for row in candidates if _single_rm_signal_bucket(row)]
    single_rm_target = min(2, cfg.exception_slots, len(single_rm_candidates))
    for row in single_rm_candidates:
        if sum(1 for picked in selected if _single_rm_signal_bucket(picked)) >= single_rm_target:
            break
        try_add(row)
    for row in candidates:
        if id(row) in selected_ids:
            continue
        if len(selected) >= cfg.exception_slots:
            break
        try_add(row)
    if len(selected) < cfg.exception_slots:
        warnings.append(f"EXCEPTION_SHORTFALL_SELECTED_{len(selected)}_OF_{cfg.exception_slots}")
    for rank, row in enumerate(selected, start=1):
        row["selected_sleeve"] = "right_tail_exception"
        row["selected_sleeve_rank"] = rank
        row["portfolio_treatment"] = "exception_research_or_starter_underwriting"
        row["right_tail_exception_warning_codes"] = warnings
    if sum(1 for r in selected if _single_rm_signal_bucket(r)) < min(2, len([c for c in candidates if _single_rm_signal_bucket(c)])):
        warnings.append("MIN_SINGLE_RM_PRIORITY_NOT_FILLED")
    return [_public_row(r) for r in selected], sorted(set(warnings))


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


def _top15_operating_recommendation_snapshot(selected: Sequence[Mapping[str, Any]], cfg: RightTailExceptionConfig) -> dict[str, Any]:
    return {
        "operating_setting": "high_conviction_top15_v3_exception_sleeve",
        "validation_status": "observed-data extension; not full AKG+macro production v2 validation",
        "top_n": int(cfg.core_n + cfg.exception_slots),
        "core_n": int(cfg.core_n),
        "exception_slots": int(cfg.exception_slots),
        "exception_selected_count": sum(1 for row in selected if row.get("selected_sleeve") == "right_tail_exception"),
        "portfolio_max_positions": 10,
        "recommendation": f"Core {cfg.core_n} are primary buy-underwriting candidates; exception sleeve names are right-tail research / starter-underwriting candidates. Do not equal-weight all {cfg.core_n + cfg.exception_slots} automatically.",
        "selected_count": len(selected),
    }


def _daily_recommendation_markdown(result: Mapping[str, Any]) -> str:
    rec = result.get("operating_recommendation", {})
    date = str(result.get("date") or result.get("config_snapshot", {}).get("selection_date") or "")
    rows = result.get("selected_rows", [])
    if rec.get("operating_setting") == "high_conviction_top15_v3_exception_sleeve":
        exception_cfg = result.get("config_snapshot", {}).get("right_tail_exception_config", {})
        core_count = len([row for row in rows if row.get("selected_sleeve") == "core"])
        exception_count = len([row for row in rows if row.get("selected_sleeve") == "right_tail_exception"])
        exception_slots = rec.get("exception_slots", exception_cfg.get("exception_slots", 0))
        queue_capacity = int(rec.get("core_n", exception_cfg.get("core_n", core_count)) or core_count) + int(exception_slots or 0)
        if queue_capacity <= 0:
            queue_capacity = len(rows)
        deterioration_rows = result.get("core_deterioration_review_rows", [])
        lines = [
            "# Fundamental High-Conviction Top-15 Daily Recommendation",
            "",
            f"Date: `{date}`" if date else "Date: `not_provided`",
            "Operating setting: `high_conviction_top15_v3_exception_sleeve`",
            "Validation label: `observed-data extension, not fully validated AKG+macro production v2`",
            "",
            "## Recommendation",
            "",
            f"Core {core_count} are primary buy-underwriting candidates.",
            f"Exception sleeve selected {exception_count} of {exception_slots} configured slots as right-tail research / starter-underwriting candidates.",
            f"Do not equal-weight all {queue_capacity} automatically.",
            "Use high_conviction_top15_v3_exception_sleeve as observed-data extension; do not claim full AKG+macro production v2 validation.",
            "",
            "## Core deterioration review gate",
            "",
            f"Core deterioration review rows: `{len(deterioration_rows)}`.",
            "If present, review `core_deterioration_review_queue.csv` before core buy-underwriting. Strict rows move from core buy-underwriting to scout/review unless PM overrides.",
            "",
            "## Selected names",
            "",
            "| sleeve | rank | ticker | treatment | score | exception_score | core_deterioration_action | reasons |",
            "| --- | ---: | --- | --- | ---: | ---: | --- | --- |",
        ]
        for row in rows:
            flags = core_deterioration_flags(row)
            treatment = row.get("portfolio_treatment", "")
            if flags.get("core_deterioration_strict_override_required"):
                treatment = "core_scout_review_unless_pm_override"
            lines.append("| {sleeve} | {rank} | {ticker} | {treatment} | {score} | {exscore} | {core_action} | {reasons} |".format(
                sleeve=row.get("selected_sleeve", ""), rank=row.get("selected_sleeve_rank", row.get("selection_rank", "")), ticker=row.get("ticker", ""), treatment=treatment, score=row.get("score", row.get("entry_score_0_100", "")), exscore=row.get("right_tail_exception_score", ""), core_action=flags.get("core_deterioration_recommended_action", ""), reasons=",".join(str(x) for x in row.get("right_tail_exception_reason_codes", [])),
            ))
        return "\n".join(lines) + "\n"
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


def _parse_confidence(value: Any) -> float | None:
    numeric = _to_float(value)
    if numeric is not None:
        return numeric
    return CONFIDENCE_LABELS.get(str(value).strip().lower())


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


def _write_csv_with_fields(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(fieldnames))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v for k, v in row.items()})


def _public_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if not k.startswith("_") and k not in {"selected_candidate", "confidence_sort"}}
