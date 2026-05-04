#!/usr/bin/env python3
"""Build a Grok committee packet with inline evidence and freshness telemetry.

Outputs:
1) eval_results/deal_flow/<date>/grok_committee_input_v2.json
2) docs/prompts/grok/grok_committee_packet_<date>_v2.md
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _truncate(text: Any, max_len: int = 900) -> str:
    if text is None:
        return ""
    value = str(text).strip()
    if len(value) <= max_len:
        return value
    return value[: max_len - 3].rstrip() + "..."


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _round2(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 2)


def _is_ymd(value: str) -> bool:
    if len(value) != 10:
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _resolve_report_path(ticker: str, as_of_date: str) -> tuple[Path | None, str | None, bool]:
    """Return best report path for ticker on/before as_of_date.

    Returns: (path, report_date, is_fallback_prior_date)
    """
    exact = Path("results") / ticker / as_of_date / "analysis_report.json"
    if exact.exists():
        return exact, as_of_date, False

    root = Path("results") / ticker
    if not root.exists():
        return None, None, False

    candidates: list[tuple[str, Path]] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        name = child.name
        if not _is_ymd(name):
            continue
        rp = child / "analysis_report.json"
        if not rp.exists():
            continue
        if name <= as_of_date:
            candidates.append((name, rp))

    if not candidates:
        return None, None, False

    best_date, best_path = sorted(candidates, key=lambda x: x[0])[-1]
    return best_path, best_date, best_date != as_of_date


def _extract_score_block(report: dict[str, Any]) -> dict[str, Any]:
    aet = report.get("aeternus_score") or {}
    llm = aet.get("llm_influence") or {}
    pre = _to_float(llm.get("base_score_pre_llm"))
    final = _to_float(aet.get("aeternus_score"))
    if pre is None:
        pre = final
    score_delta = _round2((final - pre) if (final is not None and pre is not None) else None)
    breakdown = aet.get("breakdown") or {}
    active_components: list[str] = []
    if llm.get("research_debate"):
        active_components.append("research_debate")
    if llm.get("trader_verdict"):
        active_components.append("trader_verdict")
    if llm.get("risk_verdict"):
        active_components.append("risk_verdict")
    return {
        "pre_llm_score": _round2(pre),
        "final_score": _round2(final),
        "score_delta": score_delta,
        "rating": aet.get("rating"),
        "confidence": aet.get("confidence"),
        "pillars": {
            "fundamental": breakdown.get("fundamental"),
            "coherence": breakdown.get("coherence"),
            "macro": breakdown.get("macro"),
            "sentiment": breakdown.get("sentiment"),
            "momentum": breakdown.get("momentum"),
        },
        "active_debate_components": active_components,
    }


def _extract_report_brief(report: dict[str, Any]) -> dict[str, Any]:
    macro = report.get("macro_metrics") or {}
    macro_ind = macro.get("indicators") or {}
    fundamental = report.get("fundamental_metrics") or {}
    sentiment = report.get("sentiment_metrics") or {}
    momentum = report.get("momentum_metrics") or {}
    score_block = _extract_score_block(report)
    coverage_values = [
        _to_float(fundamental.get("data_coverage")),
        _to_float(sentiment.get("data_coverage")),
        _to_float(macro.get("data_coverage")),
        _to_float(momentum.get("data_coverage")),
    ]
    coverage_values = [x for x in coverage_values if x is not None]
    blended_coverage = _round2(sum(coverage_values) / len(coverage_values)) if coverage_values else None
    return {
        "trade_date": report.get("trade_date"),
        "score_context": score_block,
        "macro_context": {
            "regime": macro.get("regime"),
            "vix_close": _round2(_to_float(macro_ind.get("vix_close"))),
            "spy_close": _round2(_to_float(macro_ind.get("spy_close"))),
            "spy_sma20": _round2(_to_float(macro_ind.get("spy_sma20"))),
        },
        "momentum_context": {
            "regime": momentum.get("regime"),
            "signal_state": momentum.get("signal_state"),
            "composite_score": momentum.get("composite_score"),
            "accel_percentile": _round2(_to_float(momentum.get("accel_percentile"))),
        },
        "sentiment_context": {
            "composite_score": sentiment.get("composite_score"),
            "direction": sentiment.get("direction"),
            "articles": (sentiment.get("buzz") or {}).get("total_articles"),
        },
        "fundamental_context": {
            "piotroski_fscore": ((fundamental.get("piotroski") or {}).get("fscore")),
            "revenue_growth_qoq": ((fundamental.get("income") or {}).get("revenue_growth_qoq")),
            "fcf_positive": ((fundamental.get("cashflow") or {}).get("fcf_positive")),
        },
        "decision_excerpt": _truncate(report.get("final_trade_decision"), 1100),
        "plan_excerpt": _truncate(report.get("investment_plan"), 900),
        "trader_view_excerpt": _truncate(report.get("trader_investment_decision"), 700),
        "blended_data_coverage": blended_coverage,
    }


def _collect_x_posts_for_ticker(raw_dir: Path, ticker: str) -> list[dict[str, Any]]:
    posts: list[dict[str, Any]] = []
    for path in sorted(raw_dir.glob("pass_*.json")):
        payload = _read_json(path, {})
        pass_number = int(path.stem.replace("pass_", "")) if path.stem.startswith("pass_") else None
        pass_type = "unknown"
        if pass_number in {12}:
            pass_type = "thematic"
        elif pass_number in {13}:
            pass_type = "contrarian"
        elif pass_number in {14}:
            pass_type = "options_flow"
        elif pass_number in {15}:
            pass_type = "gex"
        elif pass_number is not None:
            pass_type = "sector"
        for row in payload.get("trending", []) or []:
            if row.get("ticker") != ticker:
                continue
            posts.append(
                {
                    "ticker": ticker,
                    "pass_number": pass_number,
                    "source_pass_type": pass_type,
                    "buzz_rank": row.get("buzz_rank"),
                    "sentiment": row.get("sentiment"),
                    "velocity": row.get("velocity"),
                    "catalyst": row.get("catalyst"),
                }
            )
    # High-signal ordering: thematic > contrarian > sector, then buzz rank asc.
    pass_priority = {"thematic": 3, "contrarian": 2, "sector": 1, "options_flow": 1, "gex": 0, "unknown": 0}
    posts.sort(
        key=lambda x: (
            -pass_priority.get(str(x.get("source_pass_type")), 0),
            int(x.get("buzz_rank")) if isinstance(x.get("buzz_rank"), int) else 999,
            -(x.get("pass_number") or 0),
        )
    )
    return posts


def _build_x_feed_context(x_feed_root: Path, tickers: list[str], max_posts_per_ticker: int) -> dict[str, Any]:
    merged = _read_json(x_feed_root / "merged.json", {})
    raw_dir = x_feed_root / "raw"
    all_posts: list[dict[str, Any]] = []
    for ticker in tickers:
        ticker_posts = _collect_x_posts_for_ticker(raw_dir, ticker)[:max_posts_per_ticker]
        all_posts.extend(ticker_posts)

    active_themes: list[dict[str, Any]] = []
    pass_12 = _read_json(raw_dir / "pass_12.json", {})
    for row in pass_12.get("active_themes", []) or []:
        active_themes.append(
            {
                "theme": row.get("theme"),
                "conviction": row.get("conviction"),
                "reasoning": row.get("reasoning"),
            }
        )

    covered = [t for t in tickers if t in merged]
    missing = [t for t in tickers if t not in merged]
    ticker_snapshot: dict[str, Any] = {}
    for ticker in covered:
        row = merged.get(ticker) or {}
        ticker_snapshot[ticker] = {
            "mentions_estimate": row.get("mentions_estimate"),
            "sentiment_score": row.get("sentiment"),
            "velocity_trend": row.get("velocity_trend"),
            "source_pass_number": row.get("pass_number"),
        }

    coverage_ratio = round(len(covered) / len(tickers), 4) if tickers else 0.0
    status = "READY" if coverage_ratio >= 1.0 else ("PARTIAL" if coverage_ratio > 0 else "MISSING")
    summary = (
        f"Manual X-feed coverage for basket: {len(covered)}/{len(tickers)} symbols. "
        f"Pass artifacts loaded from {x_feed_root.as_posix()}."
    )
    return {
        "summary": summary,
        "coverage": {
            "status": status,
            "target_tickers": tickers,
            "covered_tickers": covered,
            "missing_tickers": missing,
            "coverage_ratio": coverage_ratio,
            "source_artifact": (x_feed_root / "merged.json").as_posix(),
        },
        "active_themes": active_themes,
        "high_signal_posts": all_posts,
        "ticker_snapshot": ticker_snapshot,
    }


def _build_portfolio_context(
    as_of_date: str, positions: dict[str, Any], latest_plan: dict[str, Any], max_position_pct: float
) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    warnings: list[str] = []
    open_positions = ((positions or {}).get("open_positions") or {})
    current_positions: list[dict[str, Any]] = []
    invested_usd = 0.0
    for symbol, row in open_positions.items():
        market_value = _to_float(row.get("market_value_usd")) or 0.0
        invested_usd += market_value
        current_positions.append(
            {
                "symbol": symbol,
                "side": row.get("direction"),
                "quantity": row.get("net_quantity"),
                "avg_price": row.get("avg_price"),
                "last_mark_price": row.get("last_mark_price"),
                "market_value_usd": row.get("market_value_usd"),
                "portfolio_weight_estimate": None,
                "opened_at": row.get("opened_at"),
                "lane": row.get("lane"),
                "source_plan_id": (positions or {}).get("source_plan_id"),
            }
        )

    capital_usd = _to_float(latest_plan.get("capital_usd")) or invested_usd or 0.0
    invested_pct = round(invested_usd / capital_usd, 4) if capital_usd > 0 else 0.0
    cash_pct = round(max(0.0, 1.0 - invested_pct), 4)
    for row in current_positions:
        mv = _to_float(row.get("market_value_usd")) or 0.0
        row["portfolio_weight_estimate"] = round(mv / capital_usd, 4) if capital_usd > 0 else None

    risk_summary = latest_plan.get("portfolio_risk_summary") or {}
    plan_signal = ((latest_plan.get("hedge_context") or {}).get("signal") or {})
    updated_at = (positions or {}).get("updated_at")
    pos_dt = _parse_iso(updated_at)
    as_of_dt = _parse_iso(f"{as_of_date}T00:00:00+00:00")
    age_days = None
    if pos_dt is not None and as_of_dt is not None:
        age_days = max(0, (as_of_dt.date() - pos_dt.date()).days)
        if age_days >= 2:
            warnings.append(
                f"Portfolio snapshot is stale by {age_days} day(s): snapshot={updated_at}, as_of_date={as_of_date}."
            )

    freshness = {
        "portfolio_snapshot_as_of": updated_at,
        "portfolio_snapshot_age_days": age_days,
        "portfolio_snapshot_stale": bool(age_days is not None and age_days >= 2),
    }

    context = {
        "account_mode": latest_plan.get("execution_mode") or "paper",
        "as_of": updated_at,
        "capital_usd": capital_usd,
        "cash_pct": cash_pct,
        "invested_pct": invested_pct,
        "drawdown_mode": bool((risk_summary.get("drawdown_20d_pct") or 0) <= -0.08),
        "drawdown_20d_pct": risk_summary.get("drawdown_20d_pct"),
        "market_regime": risk_summary.get("market_regime") or plan_signal.get("market_regime"),
        "hedge_mode": risk_summary.get("hedge_mode") or plan_signal.get("mode"),
        "current_hedge_pct": risk_summary.get("current_hedge_pct"),
        "target_hedge_pct": risk_summary.get("target_hedge_pct"),
        "hedge_action": risk_summary.get("hedge_action"),
        "current_positions": current_positions,
        "plan_constraints": {
            "max_positions": latest_plan.get("max_positions"),
            "max_weight_per_position": latest_plan.get("max_weight_per_position"),
            "long_only": latest_plan.get("long_only"),
            "min_score": latest_plan.get("min_score"),
            "min_confidence": latest_plan.get("min_confidence"),
            "committee_cap_weight": max_position_pct,
        },
    }
    return context, warnings, freshness


def _build_prompt_text() -> str:
    return """Use the attached markdown packet as the only canonical input.

Run a 4-role investment committee in one conversation:
1) Bull Researcher
2) Bear Researcher
3) Trader
4) Risk Manager

Hard rules:
- Ground every claim in packet fields only. Do not invent prices, events, or metrics.
- Use inline `aeternus_packet.inline_evidence` as primary per-ticker evidence, not just headline scores.
- Respect `constraints.max_position_pct` and `constraints.allow_new_positions`.
- Treat stale context explicitly: if `data_freshness.portfolio_snapshot_stale=true`, reduce confidence and call out sizing risk.
- Do not use a brittle threshold-only policy. Apply `decision_policy.near_boundary_band` for score-boundary cases.
- Enforce gate policy: if `execution_readiness.status != "PASS"`, do not propose OPEN/INCREASE trades.
- If `search_policy.allow_external_search=true`, run an external enrichment pass with citations.
- External facts may enrich but never silently overwrite packet values; any conflict must be listed in `external_enrichment.conflicts_with_packet`.

Decision discipline:
- If score is inside boundary band and evidence is mixed, prefer `HOLD`/`WATCHLIST` over hard `AVOID`.
- Every BUY/ADD must include: entry trigger, invalidation trigger, and review trigger.
- Every AVOID must include the specific disqualifier(s) and what would change the decision.
- WATCHLIST decisions must still include thesis-invalidating conditions.
- Triggers must be numeric and machine-checkable (metric/operator/value), not prose-only.

Required output format (strict JSON only):
{
  "as_of_date": "...",
  "input_tickers": ["..."],
  "execution_gate": {
    "status": "PASS|BLOCKED_STALE_CONTEXT|BLOCKED_MISSING_LIVE_MARKS|BLOCKED_OTHER",
    "reasons": ["..."]
  },
  "external_enrichment": {
    "used": true,
    "queries": ["..."],
    "citations": [
      {
        "id": "C1",
        "url": "https://...",
        "source": "...",
        "published_at": "YYYY-MM-DD",
        "claim": "...",
        "supports": ["ticker:CF", "portfolio"]
      }
    ],
    "conflicts_with_packet": [
      {
        "field": "...",
        "packet_value": "...",
        "external_value": "...",
        "resolution": "..."
      }
    ]
  },
  "portfolio_snapshot_used": {
    "account_mode": "...",
    "current_positions": [...],
    "cash_pct": ...,
    "market_regime": "...",
    "hedge_mode": "...",
    "snapshot_stale": true
  },
  "per_ticker_decisions": [
    {
      "ticker": "...",
      "action": "BUY|ADD|HOLD|WATCHLIST|TRIM|AVOID",
      "target_weight_pct": 0.0,
      "time_horizon_days": 20,
      "confidence": 0.0,
      "thesis_bull": "...",
      "thesis_bear": "...",
      "key_catalysts": ["..."],
      "key_risks": ["..."],
      "x_feed_support": ["..."],
      "score_context": {
        "pre_llm_score": 0.0,
        "final_score": 0.0,
        "score_delta": 0.0,
        "rating": "..."
      },
      "entry_trigger": "...",
      "entry_trigger_numeric": [
        {"metric": "vix_close", "operator": "<=", "value": 20.0}
      ],
      "invalidation_trigger": "...",
      "invalidation_trigger_numeric": [
        {"metric": "final_score", "operator": "<", "value": 60.0}
      ],
      "review_trigger": "...",
      "review_trigger_numeric": [
        {"metric": "days_since_decision", "operator": ">=", "value": 5}
      ],
      "decision_rationale": "..."
    }
  ],
  "portfolio_actions": {
    "keep_current_positions": true,
    "new_positions_allowed": true,
    "recommended_changes": [
      {
        "symbol": "...",
        "change_type": "OPEN|INCREASE|DECREASE|CLOSE|NONE",
        "weight_change_pct": 0.0,
        "reason": "..."
      }
    ],
    "hedge_view": {
      "action": "NO_CHANGE|INCREASE_HEDGE|DECREASE_HEDGE|DEFER_UNTIL_FRESH_CONTEXT",
      "instrument": "SPY|QQQ|NONE",
      "target_hedge_pct": 0.0,
      "reason": "..."
    }
  },
  "ranked_conviction": [
    {"ticker": "...", "rank": 1, "action": "...", "confidence": 0.0}
  ],
  "gaps_and_followups": {
    "known_gaps_from_packet": ["..."],
    "extra_data_needed_before_execution": ["..."]
  }
}
"""


def _build_markdown(packet: dict[str, Any]) -> str:
    prompt_text = _build_prompt_text()
    return (
        f"# Grok Committee Packet v2 (Upload-Ready) - {packet.get('as_of_date')}\n\n"
        "Use this single markdown file as the upload artifact.\n\n"
        "## Prompt (paste this)\n\n"
        "```text\n"
        f"{prompt_text}"
        "```\n\n"
        "## Canonical Input Packet\n\n"
        "```json\n"
        f"{json.dumps(packet, indent=2)}\n"
        "```\n"
    )


def _build_packet(
    as_of_date: str,
    tickers: list[str],
    max_posts_per_ticker: int,
    max_position_pct: float,
    allow_new_positions: bool,
    allow_external_search: bool,
    citation_recency_days: int,
    max_external_citations_per_ticker: int,
    primary_question: str,
) -> dict[str, Any]:
    x_feed_dir = Path("eval_results") / "x_feed" / as_of_date
    positions = _read_json(Path("eval_results/paper_execution/positions.json"), {})
    latest_plan = _read_json(Path("eval_results/paper_execution/latest_plan.json"), {})

    portfolio_context, warnings, freshness = _build_portfolio_context(
        as_of_date=as_of_date,
        positions=positions,
        latest_plan=latest_plan,
        max_position_pct=max_position_pct,
    )
    x_feed_context = _build_x_feed_context(x_feed_dir, tickers, max_posts_per_ticker=max_posts_per_ticker)

    baseline_scores: dict[str, Any] = {}
    inline_evidence: dict[str, Any] = {}
    source_reports: dict[str, str] = {}
    report_provenance: dict[str, Any] = {}
    missing_reports: list[str] = []
    fallback_reports: list[str] = []
    for ticker in tickers:
        report_path, report_date, is_fallback = _resolve_report_path(ticker=ticker, as_of_date=as_of_date)
        if report_path is None:
            missing_reports.append(ticker)
            continue
        source_reports[ticker] = report_path.as_posix()
        report_provenance[ticker] = {
            "report_path": report_path.as_posix(),
            "report_date": report_date,
            "as_of_date": as_of_date,
            "is_fallback_prior_date": bool(is_fallback),
        }
        if is_fallback and report_date:
            fallback_reports.append(f"{ticker}:{report_date}")
        report = _read_json(report_path, {})
        if not report:
            missing_reports.append(ticker)
            continue
        baseline_scores[ticker] = _extract_score_block(report)
        brief = _extract_report_brief(report)
        brief["report_date_used"] = report_date
        brief["report_fallback"] = bool(is_fallback)
        inline_evidence[ticker] = brief

    known_gaps: list[str] = []
    if missing_reports:
        known_gaps.append(f"Missing analysis_report.json for: {', '.join(missing_reports)}.")
    if fallback_reports:
        known_gaps.append(
            "Using latest prior analysis reports for: "
            + ", ".join(fallback_reports)
            + f" (as_of_date={as_of_date})."
        )
    if x_feed_context.get("coverage", {}).get("missing_tickers"):
        missing = x_feed_context["coverage"]["missing_tickers"]
        known_gaps.append(f"X-feed missing coverage for: {', '.join(missing)}.")
    known_gaps.extend(warnings)

    if not known_gaps:
        known_gaps.append("No material packet assembly gaps detected.")

    min_score = _to_float((latest_plan.get("min_score") if isinstance(latest_plan, dict) else None))
    if min_score is None:
        min_score = 62.0

    freshness_age_days = freshness.get("portfolio_snapshot_age_days")
    stale_days_gate = 2
    stale_block = bool(freshness.get("portfolio_snapshot_stale"))
    execution_readiness = {"status": "PASS", "reasons": []}
    if stale_block:
        execution_readiness["status"] = "BLOCKED_STALE_CONTEXT"
        execution_readiness["reasons"].append(
            (
                "Portfolio snapshot stale: "
                f"{freshness_age_days} day(s) old (threshold {stale_days_gate}). "
                "Refresh positions + live macro before executing new trades."
            )
        )
    if missing_reports:
        if execution_readiness["status"] == "PASS":
            execution_readiness["status"] = "BLOCKED_OTHER"
        execution_readiness["reasons"].append(
            "Missing per-ticker analysis reports for execution-grade decisioning."
        )

    packet = {
        "as_of_date": as_of_date,
        "generated_at_utc": datetime.now(tz=timezone.utc).isoformat(),
        "tickers": tickers,
        "primary_question": primary_question,
        "data_freshness": freshness,
        "execution_readiness": execution_readiness,
        "search_policy": {
            "allow_external_search": allow_external_search,
            "citation_recency_days": max(1, citation_recency_days),
            "max_external_citations_per_ticker": max(1, max_external_citations_per_ticker),
            "require_conflict_log": True,
            "require_citation_fields": ["id", "url", "source", "published_at", "claim", "supports"],
        },
        "decision_policy": {
            "score_policy": {
                "min_score": min_score,
                "near_boundary_band": 2.0,
                "guidance": {
                    "clear_candidate": f"final_score >= {round(min_score + 2.0, 2)} with sufficient evidence",
                    "boundary_case": f"{round(min_score - 2.0, 2)} <= final_score < {round(min_score + 2.0, 2)}",
                    "weak_case": f"final_score < {round(min_score - 2.0, 2)} unless asymmetry is explicitly proven",
                },
            },
            "execution_policy": {
                "require_triggers_for_new_positions": True,
                "require_invalidation_for_all_positions": True,
                "penalize_stale_portfolio_context": True,
                "block_new_positions_if_portfolio_snapshot_stale_days_gte": stale_days_gate,
                "require_numeric_triggers": True,
            },
        },
        "portfolio_context": portfolio_context,
        "baseline_scores": baseline_scores,
        "aeternus_packet": {
            "inline_evidence": inline_evidence,
            "source_reports": source_reports,
            "report_provenance": report_provenance,
        },
        "x_feed_context": x_feed_context,
        "web_search_allowed": True,
        "constraints": {
            "max_position_pct": max_position_pct,
            "allow_new_positions": allow_new_positions,
        },
        "known_gaps": known_gaps,
    }
    return packet


def main() -> None:
    parser = argparse.ArgumentParser(description="Build v2 Grok committee packet with inline evidence.")
    parser.add_argument("--date", required=True, help="As-of date (YYYY-MM-DD)")
    parser.add_argument(
        "--tickers",
        required=True,
        help="Comma-separated tickers, e.g. OXY,VRT,CF,CVX,RTX",
    )
    parser.add_argument(
        "--max-posts-per-ticker",
        type=int,
        default=2,
        help="Max number of X posts per ticker in packet.",
    )
    parser.add_argument(
        "--max-position-pct",
        type=float,
        default=0.10,
        help="Maximum position size pct for committee constraints.",
    )
    parser.add_argument(
        "--allow-new-positions",
        action="store_true",
        default=False,
        help="Allow new positions in committee constraints.",
    )
    parser.add_argument(
        "--allow-external-search",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Allow external enrichment search with required citations.",
    )
    parser.add_argument(
        "--citation-recency-days",
        type=int,
        default=7,
        help="Max recency window for external citations.",
    )
    parser.add_argument(
        "--max-external-citations-per-ticker",
        type=int,
        default=3,
        help="Max external citations to use per ticker in enrichment pass.",
    )
    parser.add_argument(
        "--primary-question",
        default="Given the latest signals, what action should we take and why?",
        help="Primary committee question.",
    )
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if not tickers:
        raise SystemExit("No valid tickers provided.")

    packet = _build_packet(
        as_of_date=args.date,
        tickers=tickers,
        max_posts_per_ticker=max(1, int(args.max_posts_per_ticker)),
        max_position_pct=args.max_position_pct,
        allow_new_positions=bool(args.allow_new_positions),
        allow_external_search=bool(args.allow_external_search),
        citation_recency_days=max(1, int(args.citation_recency_days)),
        max_external_citations_per_ticker=max(1, int(args.max_external_citations_per_ticker)),
        primary_question=args.primary_question,
    )

    json_path = Path("eval_results") / "deal_flow" / args.date / "grok_committee_input_v2.json"
    _write_json(json_path, packet)

    md_path = Path("docs/prompts/grok") / f"grok_committee_packet_{args.date}_v2.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(_build_markdown(packet), encoding="utf-8")

    print(json.dumps({"json": json_path.as_posix(), "markdown": md_path.as_posix()}, indent=2))


if __name__ == "__main__":
    main()
