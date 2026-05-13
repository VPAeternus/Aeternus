from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

from tradingagents.research.fundamental.src.features.hp_subtiers import add_hp_subtiers
from tradingagents.research.fundamental.src.features.monitoring import compute_monitoring_status
from tradingagents.research.fundamental.src.features.post_llm_scores import classify_llm_status
from tradingagents.research.fundamental.src.features.pre_llm_scores import build_pre_llm_score
from tradingagents.research.fundamental.src.features.repricing_momentum import add_repricing_momentum
from tradingagents.research.fundamental.src.features.scoring import ENTRY_SCORE_FORBIDDEN_COLUMNS, compute_entry_score, prior_key
from tradingagents.research.fundamental.src.features.signal_freshness import compute_signal_freshness
from tradingagents.research.fundamental.src.features.tiers import assign_subtiers, assign_tiers
from tradingagents.research.fundamental.src.features.underwriting import evaluate_underwriting_gates
from tradingagents.research.fundamental.src.features.underwriting import rm_buy_review_flag
from tradingagents.research.fundamental.src.storage import add_run_lineage, make_pipeline_run_id, read_rows, read_table, source_file_hash, write_table


FORBIDDEN_PIPELINE_A_COLUMNS = ENTRY_SCORE_FORBIDDEN_COLUMNS | {"candidate_monitoring"}


def _strip_monitoring_columns(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in FORBIDDEN_PIPELINE_A_COLUMNS}


def _row_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("ticker", "")).upper(), str(row.get("quarter", ""))


def _merge_by_key(base_rows: list[dict[str, Any]], *side_tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = [dict(row) for row in base_rows]
    for table in side_tables:
        side = {_row_key(row): row for row in table}
        merged = [{**row, **side.get(_row_key(row), {})} for row in merged]
    return merged


def route_candidate_state(row: dict[str, Any], entry_score: int) -> str:
    if row.get("candidate_state"):
        return str(row["candidate_state"])
    if rm_buy_review_flag(row):
        return "fundamental_review"
    if row.get("repricing_momentum_priority"):
        return "fundamental_review"
    if row.get("repricing_momentum_extension"):
        return "active_watchlist"
    return "fundamental_review" if entry_score >= 65 else "watchlist"


def build_signal_tables(
    rows: list[dict[str, Any]],
    *,
    as_of: str,
    post_llm_rows: list[dict[str, Any]] | None = None,
    prior_rows: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    rows = _merge_by_key(rows, post_llm_rows or [])
    bases: list[dict[str, Any]] = []
    output: list[dict[str, Any]] = []
    tier_rows: list[dict[str, Any]] = []
    pre_rows: list[dict[str, Any]] = []
    for input_order, original in enumerate(rows):
        base = _strip_monitoring_columns(original)
        if "pre_llm_fundamental_bucket" not in base:
            base.update(build_pre_llm_score(base))
        bases.append({**base, "__input_order": input_order})
        pre_rows.append(
            {
                "ticker": base.get("ticker", ""),
                "quarter": base.get("quarter", ""),
                "tradable_date": base.get("tradable_date", ""),
                "entry_open": base.get("entry_open", ""),
                "entry_qoq_pct": base.get("entry_qoq_pct", ""),
                "score_change": base.get("score_change", ""),
                "current_price": base.get("current_price", ""),
                "current_return_pct": base.get("current_return_pct", ""),
                "return_since_signal_pct": base.get("return_since_signal_pct", ""),
                "return_since_purchase_pct": base.get("return_since_purchase_pct", ""),
                "return_10d_pct": base.get("return_10d_pct", ""),
                "return_20d_pct": base.get("return_20d_pct", ""),
                "return_30d_pct": base.get("return_30d_pct", ""),
                "return_60d_pct": base.get("return_60d_pct", ""),
                "revenue_bucket": base.get("revenue_bucket", ""),
                "pre_llm_fundamental_score": base.get("pre_llm_fundamental_score", ""),
                "pre_llm_fundamental_bucket": base.get("pre_llm_fundamental_bucket", ""),
                "profitability_score": base.get("profitability_score", ""),
                "operating_cash_flow_score": base.get("operating_cash_flow_score", ""),
                "fcf_proxy_score": base.get("fcf_proxy_score", ""),
                "financing_dependence_score": base.get("financing_dependence_score", ""),
                "asset_efficiency_score": base.get("asset_efficiency_score", ""),
                "missing_fields": base.get("pre_llm_fundamental_missing_fields", ""),
            }
        )
    if bases:
        expanded_rows = add_repricing_momentum(add_hp_subtiers(pd.DataFrame(bases))).fillna("").to_dict("records")
        expanded_rows = sorted(expanded_rows, key=lambda row: int(row.get("__input_order", 0)))
        expanded_rows = [{key: value for key, value in row.items() if key != "__input_order"} for row in expanded_rows]
    else:
        expanded_rows = []
    prior_by_key = {_row_key(row): row for row in (prior_rows or [])}
    prior_by_key.update({_row_key(row): row for row in expanded_rows})
    for base in expanded_rows:
        tiers = assign_tiers(base)
        merged = {**base, **tiers}
        llm = classify_llm_status(merged, merged)
        prior = prior_by_key.get(prior_key(merged), {})
        subtiers = assign_subtiers(llm, prior) if llm.get("llm_status") == "complete" else {}
        tier_rows.append({"ticker": merged.get("ticker", ""), "quarter": merged.get("quarter", ""), **tiers, **subtiers})
        scored = compute_entry_score({**llm, **subtiers}, prior)
        freshness = {}
        if merged.get("tradable_date"):
            freshness = compute_signal_freshness(str(merged["tradable_date"]), as_of)
        monitoring_status = compute_monitoring_status({})
        underwriting = evaluate_underwriting_gates({**llm, **scored, **freshness, "monitoring_status": monitoring_status})
        candidate_state = route_candidate_state(llm, scored["entry_score_0_100"])
        output.append(
            {
                **llm,
                **subtiers,
                **scored,
                **freshness,
                **underwriting,
                "monitoring_status": monitoring_status,
                "candidate_state": candidate_state,
                "dashboard_score_0_100": scored["entry_score_0_100"],
            }
        )
    return output, tier_rows, pre_rows


def build_signal_rows(
    rows: list[dict[str, Any]],
    *,
    as_of: str,
    post_llm_rows: list[dict[str, Any]] | None = None,
    prior_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return build_signal_tables(rows, as_of=as_of, post_llm_rows=post_llm_rows, prior_rows=prior_rows)[0]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run event-driven live fundamental signal pipeline")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--input", type=Path, default=None, help="CSV or Parquet candidate rows")
    parser.add_argument("--post-llm", type=Path, default=None, help="Optional CSV/Parquet post-LLM rows")
    parser.add_argument("--lake-root", type=Path, default=Path("outputs/live/parquet"))
    parser.add_argument("--pipeline-run-id", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = read_rows(args.input) if args.input else read_table(args.lake_root, "pre_llm_scores").fillna("").to_dict("records")
    post_llm_rows = read_rows(args.post_llm) if args.post_llm else read_table(args.lake_root, "post_llm_scores").fillna("").to_dict("records")
    signal_rows, tier_rows, pre_rows = build_signal_tables(rows, as_of=args.as_of, post_llm_rows=post_llm_rows)
    run_id = args.pipeline_run_id or make_pipeline_run_id("signal")
    lineage = add_run_lineage(
        signal_rows,
        pipeline_run_id=run_id,
        as_of_date=args.as_of,
        source_hash=source_file_hash(args.input),
    )
    write_table(args.lake_root, "pre_llm_scores", add_run_lineage(pre_rows, pipeline_run_id=run_id, as_of_date=args.as_of, source_hash=source_file_hash(args.input)))
    write_table(args.lake_root, "tier_classification", add_run_lineage(tier_rows, pipeline_run_id=run_id, as_of_date=args.as_of, source_hash=source_file_hash(args.input)))
    write_table(args.lake_root, "candidate_scores", lineage)
    print(f"wrote candidate_scores rows={len(lineage)} run_id={run_id}")


if __name__ == "__main__":
    main()
