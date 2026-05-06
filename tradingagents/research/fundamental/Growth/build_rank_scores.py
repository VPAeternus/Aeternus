from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from src.features.themes import assign_theme_tailwind_score, detect_candidate_themes
from src.features.underwriting import rm_buy_review_flag


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "Growth" / "earnings_8k_sec_parser"
DEFAULT_INPUT = BASE / "combined_tier0_tier1_tier2_tier3_tier4_2021Q4_2026Q1_partial_gpt55_mixed.csv"
DEFAULT_OUTPUT = BASE / "rank_scored_tier0_tier1_tier2_tier3_tier4_2021Q4_2026Q1_partial_gpt55_mixed.csv"
DEFAULT_SUMMARY = BASE / "rank_scored_tier0_tier1_tier2_tier3_tier4_2021Q4_2026Q1_partial_gpt55_mixed_summary.csv"

LLM_CRITICAL_FIELDS = [
    "post_llm_candidate_flag",
    "post_llm_high_priority_flag",
    "post_llm_demote_flag",
    "causal_change",
    "negative_revision_risk",
    "narrative_delta_bucket",
    "operating_leverage_quality",
    "durability",
    "score_addition",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def clean(value: Any) -> str:
    return str(value or "").strip()


def to_float(value: Any) -> float | None:
    text = clean(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def to_int(value: Any, default: int = 0) -> int:
    number = to_float(value)
    if number is None:
        return default
    return int(number)


def flag(value: Any) -> bool:
    return clean(value) in {"1", "true", "True", "yes", "Y"}


def present_flag(value: Any) -> bool:
    text = clean(value)
    return bool(text) and text not in {"0", "0.0", "false", "False", "FALSE", "none", "None"}


def clamp(value: float, lo: int = 0, hi: int = 100) -> int:
    return int(max(lo, min(hi, value)))


def prior_quarter(quarter: str) -> str:
    year_text, q_text = clean(quarter).split("Q", maxsplit=1)
    year = int(year_text)
    quarter_num = int(q_text)
    if quarter_num == 1:
        return f"{year - 1}Q4"
    return f"{year}Q{quarter_num - 1}"


def tier_structure_score(row: dict[str, Any]) -> int:
    score = 0
    if clean(row.get("tier_0_bucket")) or clean(row.get("tier_bucket")):
        score = max(score, 10)
    if clean(row.get("tier_1_bucket")):
        score = max(score, 18)
    if clean(row.get("tier_2_bucket")):
        score = max(score, 25)
    if clean(row.get("tier_3_bucket")):
        score += 4
    if clean(row.get("tier_4_bucket")):
        score += 5
    return min(score, 30)


def hp_structure_score(row: dict[str, Any]) -> int:
    score = 0
    if clean(row.get("hp1_quality_pullback")):
        score = max(score, 15)
    if clean(row.get("hp2_dislocation_momentum_priority")):
        score = max(score, 18)
    if clean(row.get("hp2_dislocation_momentum_watch")):
        score = max(score, 8)
    if clean(row.get("hp3_large_quality_theme_exception")):
        score = max(score, 10)
    if clean(row.get("hp4_score_reacceleration_watch")):
        score = max(score, 8)
    return score


def llm_business_improvement_score(row: dict[str, Any], prior_score_addition: int | None) -> int:
    score = 0
    if flag(row.get("post_llm_candidate_flag")):
        score += 8
    if flag(row.get("post_llm_high_priority_flag")):
        score += 6

    causal = to_int(row.get("causal_change"))
    if causal == 1:
        score += 4
    elif causal == 2:
        score += 10
    elif causal == 3:
        score += 20

    neg_risk = to_float(row.get("negative_revision_risk"))
    if neg_risk is not None:
        if neg_risk <= 1:
            score += 6
        elif neg_risk == 2:
            score += 4

    narrative = clean(row.get("narrative_delta_bucket"))
    if narrative == "inflecting":
        score += 5
    elif narrative == "constructive":
        score += 3
    elif narrative == "neutral":
        score += 1

    op_lev = to_int(row.get("operating_leverage_quality"))
    if op_lev == 2:
        score += 4
    elif op_lev == 1:
        score += 2

    durability = to_int(row.get("durability"))
    if durability == 2:
        score += 3
    elif durability == 1:
        score += 1

    score_addition = to_float(row.get("score_addition")) or 0
    if score_addition > 0 and prior_score_addition is not None and prior_score_addition > 0:
        score += 5
    if flag(row.get("post_llm_high_priority_flag")) and prior_score_addition is not None and prior_score_addition > 0:
        score += 3

    return min(score, 45)


def fundamental_rerating_score(row: dict[str, Any], prior_pre_score: float | None) -> int:
    score = 0
    asset = to_int(row.get("asset_efficiency_score"))
    if asset == 2:
        score += 5
    elif asset == 1:
        score += 3

    pre_score = to_float(row.get("pre_llm_fundamental_score"))
    causal = to_int(row.get("causal_change"))
    if pre_score is not None:
        if pre_score <= 0:
            score += 3
        if pre_score <= -2:
            score += 2
        if pre_score > 0 and causal == 3:
            score += 3

    if pre_score is not None and prior_pre_score is not None and pre_score <= 0 and prior_pre_score <= 0:
        score += 3

    financing = to_float(row.get("financing_dependence_score"))
    if financing == 1:
        score += 3
    elif financing == 0:
        score += 1

    return min(score, 15)


def load_theme_rows(path: Path | None) -> dict[tuple[str, str], dict[str, str]]:
    if not path:
        return {}
    return {(clean(row.get("quarter")), clean(row.get("ticker")).upper()): row for row in read_csv(path)}


def theme_external_confirmation_score(row: dict[str, Any]) -> int:
    # Legacy compatibility only. Adaptive scoring uses theme_tailwind_score.
    score = 0
    if flag(row.get("theme_active")):
        score += 4
    if flag(row.get("theme_leader_or_direct_beneficiary")):
        score += 3
    if flag(row.get("theme_cohort_strength")):
        score += 3
    return min(score, 10)


def theme_tailwind_score(row: dict[str, Any]) -> int:
    existing = to_float(row.get("theme_tailwind_score"))
    if existing is not None and existing > 0:
        return max(0, min(20, int(existing)))
    return assign_theme_tailwind_score(row, detect_candidate_themes(row), {})


def market_repricing_score(row: dict[str, Any]) -> int:
    return max(0, min(20, to_int(row.get("market_repricing_score"))))


def missing_critical_llm_fields(row: dict[str, Any]) -> int:
    if not flag(row.get("has_post_llm")):
        return 0
    return int(any(clean(row.get(field)) == "" for field in LLM_CRITICAL_FIELDS))


def risk_penalty_score(row: dict[str, Any], missing_llm_fields: int) -> int:
    penalty = 0
    if flag(row.get("post_llm_demote_flag")):
        penalty += 7
    if clean(row.get("narrative_delta_bucket")) == "deteriorating":
        penalty += 5
    if to_int(row.get("negative_revision_risk")) >= 3:
        penalty += 6

    financing = to_float(row.get("financing_dependence_score"))
    if financing == -1:
        penalty += 4
    elif financing == 0:
        penalty += 1

    entry = to_float(row.get("entry_open"))
    if entry is not None:
        if entry < 2:
            penalty += 6
        elif entry < 5:
            penalty += 2

    if missing_llm_fields == 1:
        penalty += 3

    return penalty


def hard_reject_reason(row: dict[str, Any]) -> str:
    reasons: list[str] = []
    if clean(row.get("pre_llm_fundamental_bucket")) == "not_scored":
        reasons.append("pre_llm_fundamental_bucket_not_scored")
    if to_float(row.get("entry_open")) is None:
        reasons.append("missing_entry_open")
    if not clean(row.get("revenue_bucket")):
        reasons.append("missing_revenue_bucket")
    return ";".join(reasons)


def score_label(score: int, status: str) -> str:
    if status == "kill_review":
        return "Stop / review"
    if score >= 85:
        return "A+"
    if score >= 75:
        return "A"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    if score >= 30:
        return "D"
    return "Avoid / stale / low priority"


def entry_score_bucket(score: int) -> str:
    if score >= 80:
        return "Highest-priority entry research"
    if score >= 70:
        return "High-priority entry research"
    if score >= 60:
        return "Good candidate, needs downstream confirmation"
    if score >= 40:
        return "Watchlist / secondary research"
    return "Low priority unless theme override exists"


def monitoring_score(entry_score: int, row: dict[str, Any]) -> tuple[int, str, int, int, int, str]:
    status = "pre_checkpoint"
    adjustment = 0

    return_60d = to_float(row.get("return_60d_pct"))
    return_30d = to_float(row.get("return_30d_pct"))
    return_20d = to_float(row.get("return_20d_pct"))
    return_10d = to_float(row.get("return_10d_pct"))

    if return_60d is not None and return_60d <= -10:
        return min(entry_score, 20), "kill_review", min(entry_score, 20) - entry_score, 0, 0, "none"
    if return_30d is not None and return_30d <= -15:
        adjustment = -12
        status = "midpoint_stress"
    elif return_20d is not None and return_20d <= -20:
        adjustment = -10
        status = "early_stress"
    elif return_10d is not None and return_10d <= -20:
        adjustment = -10
        status = "early_stress"
    elif any(value is not None for value in [return_10d, return_20d, return_30d, return_60d]):
        status = "active_ok"

    repricing_started = int(
        status != "kill_review"
        and (
            (return_20d is not None and return_20d >= 20)
            or (return_30d is not None and return_30d >= 20)
        )
    )
    repricing_confirmed = int(status != "kill_review" and return_60d is not None and return_60d >= 30)
    positive_repricing_status = "none"
    if repricing_started:
        positive_repricing_status = "repricing_started"
    if repricing_confirmed:
        positive_repricing_status = "repricing_confirmed"
    return clamp(entry_score + adjustment), status, adjustment, repricing_started, repricing_confirmed, positive_repricing_status


def force_llm_extraction_flag(row: dict[str, Any], repricing_started: int = 0, repricing_confirmed: int = 0) -> int:
    triggered = any(
        present_flag(row.get(column))
        for column in [
            "tier_1_bucket",
            "tier_2_bucket",
            "tier_3_bucket",
            "tier_4_bucket",
            "hp_production_extension",
            "hp_research_extension",
            "repricing_momentum_extension",
        ]
    )
    triggered = triggered or bool(repricing_started) or bool(repricing_confirmed)
    return 1 if triggered else 0


def build_rank_scores(input_path: Path, output_path: Path, summary_path: Path, theme_path: Path | None) -> None:
    rows = read_csv(input_path)
    theme_rows = load_theme_rows(theme_path)
    prior_score_addition_by_key = {
        (clean(row.get("ticker")).upper(), clean(row.get("quarter"))): to_int(row.get("score_addition"))
        for row in rows
    }
    prior_pre_score_by_key = {
        (clean(row.get("ticker")).upper(), clean(row.get("quarter"))): to_float(row.get("pre_llm_fundamental_score"))
        for row in rows
    }

    output: list[dict[str, Any]] = []
    for row in rows:
        ticker = clean(row.get("ticker")).upper()
        quarter = clean(row.get("quarter"))
        merged = dict(row)
        merged.update(theme_rows.get((quarter, ticker), {}))
        try:
            prior_q = prior_quarter(quarter)
        except (ValueError, IndexError):
            prior_q = ""

        prior_addition = prior_score_addition_by_key.get((ticker, prior_q))
        prior_pre_score = prior_pre_score_by_key.get((ticker, prior_q))
        missing_llm = missing_critical_llm_fields(merged)
        reject = hard_reject_reason(merged)

        tier_score = tier_structure_score(merged)
        hp_score = hp_structure_score(merged)
        total_score = max(tier_score, hp_score)
        llm_score = llm_business_improvement_score(merged, prior_addition)
        fundamental_score = fundamental_rerating_score(merged, prior_pre_score)
        repricing_score = market_repricing_score(merged)
        theme_score = theme_tailwind_score(merged)
        legacy_theme_score = theme_external_confirmation_score(merged)
        penalty = risk_penalty_score(merged, missing_llm)
        base_raw_score = tier_score + llm_score + fundamental_score + repricing_score + theme_score - penalty
        base_entry_score = 0 if reject else clamp(base_raw_score)
        raw_score = total_score + llm_score + fundamental_score + repricing_score + theme_score - penalty
        entry_score = 0 if reject else clamp(raw_score)
        hp_adjusted_raw_score = raw_score
        hp_adjusted_entry_score = entry_score
        active_score, status, monitoring_adjustment, monitor_repricing_started, monitor_repricing_confirmed, positive_repricing_status = monitoring_score(entry_score, merged)
        rm_review = rm_buy_review_flag(
            {
                **merged,
                "market_repricing_score": repricing_score,
                "repricing_confirmed": monitor_repricing_confirmed,
                "positive_repricing_status": positive_repricing_status,
            }
        )
        force_llm = force_llm_extraction_flag(merged, monitor_repricing_started, monitor_repricing_confirmed)
        final_score = active_score

        output.append(
            {
                **merged,
                "force_llm_extraction": force_llm,
                "prior_score_addition": "" if prior_addition is None else prior_addition,
                "prior_pre_llm_fundamental_score": "" if prior_pre_score is None else prior_pre_score,
                "missing_critical_llm_fields": missing_llm,
                "tier_structure_score": tier_score,
                "hp_structure_score": hp_score,
                "total_structure_score": total_score,
                "llm_business_improvement_score": llm_score,
                "fundamental_rerating_score": fundamental_score,
                "market_repricing_score": repricing_score,
                "rm_buy_review_flag": rm_review,
                "theme_tailwind_score": theme_score,
                "theme_external_confirmation_score": legacy_theme_score,
                "risk_penalty_score": penalty,
                "base_entry_raw_score": base_raw_score,
                "base_entry_score_0_100": base_entry_score,
                "entry_raw_score": raw_score,
                "entry_score_0_100": entry_score,
                "entry_score_0_100_bucket": entry_score_bucket(entry_score),
                "hp_adjusted_raw_score": hp_adjusted_raw_score,
                "hp_adjusted_entry_score": hp_adjusted_entry_score,
                "hp_adjusted_entry_score_bucket": entry_score_bucket(hp_adjusted_entry_score),
                "monitoring_adjustment": monitoring_adjustment,
                "monitoring_score_0_100": active_score,
                "final_rank_score_0_100": final_score,
                "rank_score_label": score_label(final_score, status),
                "monitoring_status": status,
                "repricing_started": monitor_repricing_started,
                "repricing_confirmed": monitor_repricing_confirmed,
                "positive_repricing_status": positive_repricing_status,
                "hard_reject_reason": reject,
            }
        )

    score_columns = [
        "prior_score_addition",
        "prior_pre_llm_fundamental_score",
        "missing_critical_llm_fields",
        "tier_structure_score",
        "hp_structure_score",
        "total_structure_score",
        "llm_business_improvement_score",
        "fundamental_rerating_score",
        "market_repricing_score",
        "rm_buy_review_flag",
        "theme_tailwind_score",
        "theme_external_confirmation_score",
        "risk_penalty_score",
        "base_entry_raw_score",
        "base_entry_score_0_100",
        "entry_raw_score",
        "entry_score_0_100",
        "entry_score_0_100_bucket",
        "hp_adjusted_raw_score",
        "hp_adjusted_entry_score",
        "hp_adjusted_entry_score_bucket",
        "monitoring_adjustment",
        "monitoring_score_0_100",
        "final_rank_score_0_100",
        "rank_score_label",
        "monitoring_status",
        "repricing_started",
        "repricing_confirmed",
        "positive_repricing_status",
        "hard_reject_reason",
    ]
    base_fieldnames = [key for key in output[0] if key not in score_columns]
    if "tradable_date" in base_fieldnames:
        insert_at = base_fieldnames.index("tradable_date")
        fieldnames = base_fieldnames[:insert_at] + score_columns + base_fieldnames[insert_at:]
    else:
        fieldnames = base_fieldnames + score_columns
    write_csv(output_path, output, fieldnames)

    summary_rows = [
        {"metric": "rows", "bucket": "", "value": len(output)},
        {"metric": "hard_reject_count", "bucket": "", "value": sum(bool(row["hard_reject_reason"]) for row in output)},
        {"metric": "missing_critical_llm_fields", "bucket": "", "value": sum(int(row["missing_critical_llm_fields"]) for row in output)},
    ]
    for label in ["A+", "A", "B", "C", "D", "Avoid / stale / low priority", "Stop / review"]:
        summary_rows.append({"metric": "rank_score_label", "bucket": label, "value": sum(row["rank_score_label"] == label for row in output)})
    for bucket in [
        "Highest-priority entry research",
        "High-priority entry research",
        "Good candidate, needs downstream confirmation",
        "Watchlist / secondary research",
        "Low priority unless theme override exists",
    ]:
        summary_rows.append({"metric": "entry_score_0_100_bucket", "bucket": bucket, "value": sum(row["entry_score_0_100_bucket"] == bucket for row in output)})
        summary_rows.append({"metric": "hp_adjusted_entry_score_bucket", "bucket": bucket, "value": sum(row["hp_adjusted_entry_score_bucket"] == bucket for row in output)})
    for status in ["pre_checkpoint", "active_ok", "early_stress", "midpoint_stress", "kill_review"]:
        summary_rows.append({"metric": "monitoring_status", "bucket": status, "value": sum(row["monitoring_status"] == status for row in output)})
    summary_rows.append({"metric": "positive_monitoring", "bucket": "repricing_started", "value": sum(int(row["repricing_started"]) for row in output)})
    summary_rows.append({"metric": "positive_monitoring", "bucket": "repricing_confirmed", "value": sum(int(row["repricing_confirmed"]) for row in output)})
    for status in ["none", "repricing_started", "repricing_confirmed"]:
        summary_rows.append({"metric": "positive_repricing_status", "bucket": status, "value": sum(row["positive_repricing_status"] == status for row in output)})
    write_csv(summary_path, summary_rows, ["metric", "bucket", "value"])

    print(f"wrote {output_path} rows={len(output)}")
    print(f"wrote {summary_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build exact 0-100 rank scores without SPY regime risk")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--theme-csv", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_rank_scores(args.input, args.output, args.summary, args.theme_csv)


if __name__ == "__main__":
    main()
