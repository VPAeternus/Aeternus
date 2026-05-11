"""Attribution-driven X API budget tuner for deal-flow."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def evaluate_x_budget_policy(
    config: Dict[str, Any],
    as_of_date: str,
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Compute and optionally apply X budget/call recommendations from attribution artifacts."""
    enabled = bool(config.get("dealflow_x_auto_tune_enabled", False))
    policy: Dict[str, Any] = {
        "enabled": enabled,
        "applied": False,
        "action": "DISABLED" if not enabled else "HOLD",
        "reason": "auto tuner disabled" if not enabled else "",
        "as_of_date": str(as_of_date),
        "lookback_days": int(config.get("dealflow_x_tuner_lookback_days", 30)),
        "families": _x_family_list(config),
        "summaries_used": 0,
        "horizon_used": None,
        "metrics": {},
        "current": {
            "max_api_calls_per_run": int(config.get("dealflow_x_max_api_calls_per_run", 8)),
            "daily_budget_usd": float(config.get("dealflow_x_daily_budget_usd", 15.0)),
        },
        "recommended": {
            "max_api_calls_per_run": int(config.get("dealflow_x_max_api_calls_per_run", 8)),
            "daily_budget_usd": float(config.get("dealflow_x_daily_budget_usd", 15.0)),
        },
        "guardrails": {
            "min_calls": int(config.get("dealflow_x_tuner_min_calls", 1)),
            "max_calls": int(config.get("dealflow_x_tuner_max_calls", 15)),
            "min_budget_usd": float(config.get("dealflow_x_tuner_min_daily_budget_usd", 8.0)),
            "max_budget_usd": float(config.get("dealflow_x_tuner_max_daily_budget_usd", 30.0)),
            "max_step_calls": int(config.get("dealflow_x_tuner_max_step_calls", 1)),
            "require_horizon_alignment": bool(
                config.get("dealflow_x_tuner_require_horizon_alignment", True)
            ),
        },
    }
    if not enabled:
        return policy

    dealflow_dir = Path(base_dir or Path("eval_results") / "deal_flow")
    summaries = _load_recent_summaries(
        base_dir=dealflow_dir,
        as_of_date=as_of_date,
        lookback_days=int(policy["lookback_days"]),
    )
    policy["summaries_used"] = len(summaries)
    if not summaries:
        policy["reason"] = "no post-fundamental attribution summaries found"
        return policy

    by_horizon = {
        "5d": _aggregate_family_horizon(summaries, policy["families"], "5d"),
        "20d": _aggregate_family_horizon(summaries, policy["families"], "20d"),
    }
    policy["metrics"] = by_horizon

    min_eval = int(config.get("dealflow_x_tuner_min_evaluated", 6))
    if int(by_horizon["20d"]["evaluated_count"]) >= min_eval:
        horizon = "20d"
    elif int(by_horizon["5d"]["evaluated_count"]) >= min_eval:
        horizon = "5d"
    else:
        policy["reason"] = (
            f"insufficient evaluated samples (5d={by_horizon['5d']['evaluated_count']}, "
            f"20d={by_horizon['20d']['evaluated_count']}, min={min_eval})"
        )
        return policy

    policy["horizon_used"] = horizon
    selected = by_horizon[horizon]
    edge = float(selected.get("avg_strategy_edge_vs_benchmark_pct") or 0.0)
    win_rate = selected.get("strategy_edge_win_rate")
    win_rate_value = float(win_rate) if isinstance(win_rate, (int, float)) else 0.5

    current_calls = int(policy["current"]["max_api_calls_per_run"])
    current_budget = float(policy["current"]["daily_budget_usd"])
    min_calls = int(config.get("dealflow_x_tuner_min_calls", 1))
    max_calls = int(config.get("dealflow_x_tuner_max_calls", 15))
    max_step_calls = max(1, int(config.get("dealflow_x_tuner_max_step_calls", 1)))
    cost_per_call = float(config.get("dealflow_x_cost_per_api_call_usd", 1.0))
    up_edge = float(config.get("dealflow_x_tuner_edge_up_threshold", 1.0))
    down_edge = float(config.get("dealflow_x_tuner_edge_down_threshold", -1.0))
    up_win = float(config.get("dealflow_x_tuner_win_rate_up", 0.55))
    down_win = float(config.get("dealflow_x_tuner_win_rate_down", 0.45))
    min_budget = float(config.get("dealflow_x_tuner_min_daily_budget_usd", 8.0))
    max_budget = float(config.get("dealflow_x_tuner_max_daily_budget_usd", 30.0))
    if max_budget < min_budget:
        max_budget = min_budget

    action, reason = _decision_from_metrics(
        horizon=horizon,
        edge=edge,
        win_rate=win_rate_value,
        up_edge=up_edge,
        down_edge=down_edge,
        up_win=up_win,
        down_win=down_win,
    )

    require_alignment = bool(config.get("dealflow_x_tuner_require_horizon_alignment", True))
    if require_alignment:
        five = by_horizon["5d"]
        twenty = by_horizon["20d"]
        if int(five.get("evaluated_count", 0)) >= min_eval and int(twenty.get("evaluated_count", 0)) >= min_eval:
            action_5d, _ = _decision_from_metrics(
                horizon="5d",
                edge=float(five.get("avg_strategy_edge_vs_benchmark_pct") or 0.0),
                win_rate=float(five.get("strategy_edge_win_rate") or 0.5),
                up_edge=up_edge,
                down_edge=down_edge,
                up_win=up_win,
                down_win=down_win,
            )
            action_20d, _ = _decision_from_metrics(
                horizon="20d",
                edge=float(twenty.get("avg_strategy_edge_vs_benchmark_pct") or 0.0),
                win_rate=float(twenty.get("strategy_edge_win_rate") or 0.5),
                up_edge=up_edge,
                down_edge=down_edge,
                up_win=up_win,
                down_win=down_win,
            )
            if {action_5d, action_20d} == {"INCREASE", "DECREASE"}:
                action = "HOLD"
                reason = (
                    "5d/20d horizons disagree on direction; holding budget until alignment."
                )

    recommended_calls = current_calls
    if action == "INCREASE":
        recommended_calls = current_calls + max_step_calls
    elif action == "DECREASE":
        recommended_calls = current_calls - max_step_calls

    effective_max_calls = max_calls
    if cost_per_call > 0:
        effective_max_calls = min(max_calls, int(max_budget // cost_per_call))
    effective_max_calls = max(min_calls, effective_max_calls)

    recommended_calls = max(min_calls, min(effective_max_calls, recommended_calls))
    delta_calls = int(recommended_calls - current_calls)

    proposed_budget = current_budget + float(delta_calls * max(0.0, cost_per_call))
    budget_floor = float(cost_per_call * recommended_calls) if cost_per_call > 0 else 0.0
    recommended_budget = max(min_budget, proposed_budget, budget_floor)
    recommended_budget = round(min(max_budget, recommended_budget), 2)

    if action in {"INCREASE", "DECREASE"} and recommended_calls == current_calls:
        action = "HOLD"
        reason = "guardrails prevented a call-count change; holding."

    policy["action"] = action
    policy["reason"] = reason
    policy["recommended"] = {
        "max_api_calls_per_run": int(recommended_calls),
        "daily_budget_usd": float(recommended_budget),
    }

    changed = (
        int(recommended_calls) != int(current_calls)
        or abs(float(recommended_budget) - float(current_budget)) > 1e-9
    )
    if bool(config.get("dealflow_x_auto_tune_apply", True)) and changed:
        config["dealflow_x_max_api_calls_per_run"] = int(recommended_calls)
        config["dealflow_x_daily_budget_usd"] = float(recommended_budget)
        policy["applied"] = True

    return policy


def persist_x_budget_policy(policy: Dict[str, Any], as_of_date: str, base_dir: Optional[Path] = None) -> Path:
    root = Path(base_dir or Path("eval_results") / "deal_flow")
    dated = root / str(as_of_date)
    dated.mkdir(parents=True, exist_ok=True)
    dated_path = dated / "x_budget_policy.json"
    latest_path = root / "x_budget_policy_latest.json"
    payload = dict(policy)
    payload["as_of_date"] = str(as_of_date)
    payload["generated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    raw = json.dumps(payload, indent=2)
    dated_path.write_text(raw)
    latest_path.write_text(raw)
    return dated_path


def _x_family_list(config: Dict[str, Any]) -> List[str]:
    raw = str(config.get("dealflow_x_tuner_families", "social_momentum,news_catalyst"))
    values = [v.strip() for v in raw.split(",") if v.strip()]
    seen = []
    for val in values:
        if val not in seen:
            seen.append(val)
    return seen


def _load_recent_summaries(base_dir: Path, as_of_date: str, lookback_days: int) -> List[Dict[str, Any]]:
    del base_dir, as_of_date, lookback_days
    return []


def _aggregate_family_horizon(
    summaries: List[Dict[str, Any]],
    families: List[str],
    horizon: str,
) -> Dict[str, Any]:
    evaluated_total = 0
    pending_total = 0
    no_data_total = 0
    weighted_edge = 0.0
    weighted_win = 0.0

    for summary in summaries:
        attribution = summary.get("attribution") if isinstance(summary, dict) else {}
        by_family = attribution.get("by_signal_family", {}) if isinstance(attribution, dict) else {}
        if not isinstance(by_family, dict):
            continue
        for family in families:
            block = by_family.get(family, {})
            if not isinstance(block, dict):
                continue
            horizons = block.get("realized_horizons", {})
            if not isinstance(horizons, dict):
                continue
            hz = horizons.get(horizon, {})
            if not isinstance(hz, dict):
                continue

            evaluated = int(hz.get("evaluated_count", 0) or 0)
            pending = int(hz.get("pending_count", 0) or 0)
            no_data = int(hz.get("no_data_count", 0) or 0)
            evaluated_total += evaluated
            pending_total += pending
            no_data_total += no_data

            edge = hz.get("avg_strategy_edge_vs_benchmark_pct")
            if isinstance(edge, (int, float)) and evaluated > 0:
                weighted_edge += float(edge) * float(evaluated)

            win = hz.get("strategy_edge_win_rate")
            if isinstance(win, (int, float)) and evaluated > 0:
                weighted_win += float(win) * float(evaluated)

    avg_edge = round(weighted_edge / evaluated_total, 4) if evaluated_total > 0 else None
    avg_win = round(weighted_win / evaluated_total, 4) if evaluated_total > 0 else None
    return {
        "evaluated_count": int(evaluated_total),
        "pending_count": int(pending_total),
        "no_data_count": int(no_data_total),
        "avg_strategy_edge_vs_benchmark_pct": avg_edge,
        "strategy_edge_win_rate": avg_win,
    }


def _parse_iso_date(value: str) -> Optional[dt.date]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return dt.datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _decision_from_metrics(
    horizon: str,
    edge: float,
    win_rate: float,
    up_edge: float,
    down_edge: float,
    up_win: float,
    down_win: float,
) -> tuple[str, str]:
    if edge >= up_edge and win_rate >= up_win:
        return (
            "INCREASE",
            f"{horizon} edge {edge:.4f} and win_rate {win_rate:.4f} exceeded growth thresholds",
        )
    if edge <= down_edge and win_rate <= down_win:
        return (
            "DECREASE",
            f"{horizon} edge {edge:.4f} and win_rate {win_rate:.4f} breached cut thresholds",
        )
    return ("HOLD", "edge within hold band")
