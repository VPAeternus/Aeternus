import json
from pathlib import Path

from tradingagents.dealflow.x_budget import evaluate_x_budget_policy


def _write_summary(base: Path, date: str, by_family: dict):
    date_dir = base / date
    date_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": date,
        "attribution": {
            "by_signal_family": by_family,
        },
    }
    (date_dir / "batch_analyze_latest.json").write_text(json.dumps(payload))


def _family_block(eval_count: int, edge: float, win_rate: float):
    hz = {
        "evaluated_count": eval_count,
        "pending_count": 0,
        "no_data_count": 0,
        "avg_strategy_edge_vs_benchmark_pct": edge,
        "strategy_edge_win_rate": win_rate,
    }
    return {"realized_horizons": {"5d": hz, "20d": hz}}


def _family_block_split(
    eval_5d: int,
    edge_5d: float,
    win_5d: float,
    eval_20d: int,
    edge_20d: float,
    win_20d: float,
):
    hz5 = {
        "evaluated_count": eval_5d,
        "pending_count": 0,
        "no_data_count": 0,
        "avg_strategy_edge_vs_benchmark_pct": edge_5d,
        "strategy_edge_win_rate": win_5d,
    }
    hz20 = {
        "evaluated_count": eval_20d,
        "pending_count": 0,
        "no_data_count": 0,
        "avg_strategy_edge_vs_benchmark_pct": edge_20d,
        "strategy_edge_win_rate": win_20d,
    }
    return {"realized_horizons": {"5d": hz5, "20d": hz20}}


def test_x_budget_tuner_increases_when_edge_is_strong(tmp_path):
    base = tmp_path / "eval_results" / "deal_flow"
    _write_summary(
        base,
        "2026-02-05",
        {
            "cashtag_momentum": _family_block(4, 2.0, 0.75),
            "social_momentum": _family_block(3, 1.5, 0.67),
            "news_catalyst": _family_block(3, 1.2, 0.60),
        },
    )

    config = {
        "dealflow_x_auto_tune_enabled": True,
        "dealflow_x_auto_tune_apply": True,
        "dealflow_x_max_api_calls_per_run": 8,
        "dealflow_x_daily_budget_usd": 15.0,
        "dealflow_x_cost_per_api_call_usd": 1.0,
        "dealflow_x_tuner_min_calls": 1,
        "dealflow_x_tuner_max_calls": 12,
        "dealflow_x_tuner_min_evaluated": 6,
        "dealflow_x_tuner_edge_up_threshold": 1.0,
        "dealflow_x_tuner_edge_down_threshold": -1.0,
        "dealflow_x_tuner_win_rate_up": 0.55,
        "dealflow_x_tuner_win_rate_down": 0.45,
        "dealflow_x_tuner_lookback_days": 30,
    }
    policy = evaluate_x_budget_policy(config=config, as_of_date="2026-02-06", base_dir=base)

    assert policy["action"] == "INCREASE"
    assert policy["applied"] is True
    assert policy["recommended"]["max_api_calls_per_run"] == 9
    assert config["dealflow_x_max_api_calls_per_run"] == 9


def test_x_budget_tuner_decreases_when_edge_is_weak(tmp_path):
    base = tmp_path / "eval_results" / "deal_flow"
    _write_summary(
        base,
        "2026-02-05",
        {
            "cashtag_momentum": _family_block(4, -2.0, 0.2),
            "social_momentum": _family_block(3, -1.6, 0.3),
            "news_catalyst": _family_block(3, -1.1, 0.4),
        },
    )

    config = {
        "dealflow_x_auto_tune_enabled": True,
        "dealflow_x_auto_tune_apply": True,
        "dealflow_x_max_api_calls_per_run": 8,
        "dealflow_x_daily_budget_usd": 15.0,
        "dealflow_x_cost_per_api_call_usd": 1.0,
        "dealflow_x_tuner_min_calls": 1,
        "dealflow_x_tuner_max_calls": 12,
        "dealflow_x_tuner_min_evaluated": 6,
        "dealflow_x_tuner_edge_up_threshold": 1.0,
        "dealflow_x_tuner_edge_down_threshold": -1.0,
        "dealflow_x_tuner_win_rate_up": 0.55,
        "dealflow_x_tuner_win_rate_down": 0.45,
        "dealflow_x_tuner_lookback_days": 30,
    }
    policy = evaluate_x_budget_policy(config=config, as_of_date="2026-02-06", base_dir=base)

    assert policy["action"] == "DECREASE"
    assert policy["recommended"]["max_api_calls_per_run"] == 7
    assert config["dealflow_x_max_api_calls_per_run"] == 7


def test_x_budget_tuner_disabled(tmp_path):
    base = tmp_path / "eval_results" / "deal_flow"
    config = {
        "dealflow_x_auto_tune_enabled": False,
        "dealflow_x_max_api_calls_per_run": 8,
        "dealflow_x_daily_budget_usd": 15.0,
    }
    policy = evaluate_x_budget_policy(config=config, as_of_date="2026-02-06", base_dir=base)
    assert policy["action"] == "DISABLED"
    assert policy["applied"] is False


def test_x_budget_tuner_holds_when_horizons_disagree(tmp_path):
    base = tmp_path / "eval_results" / "deal_flow"
    _write_summary(
        base,
        "2026-02-05",
        {
            "cashtag_momentum": _family_block_split(4, 2.0, 0.75, 4, -2.0, 0.25),
            "social_momentum": _family_block_split(3, 1.5, 0.60, 3, -1.4, 0.30),
            "news_catalyst": _family_block_split(3, 1.2, 0.58, 3, -1.2, 0.35),
        },
    )
    config = {
        "dealflow_x_auto_tune_enabled": True,
        "dealflow_x_auto_tune_apply": True,
        "dealflow_x_max_api_calls_per_run": 8,
        "dealflow_x_daily_budget_usd": 15.0,
        "dealflow_x_cost_per_api_call_usd": 1.0,
        "dealflow_x_tuner_min_calls": 1,
        "dealflow_x_tuner_max_calls": 12,
        "dealflow_x_tuner_min_evaluated": 6,
        "dealflow_x_tuner_edge_up_threshold": 1.0,
        "dealflow_x_tuner_edge_down_threshold": -1.0,
        "dealflow_x_tuner_win_rate_up": 0.55,
        "dealflow_x_tuner_win_rate_down": 0.45,
        "dealflow_x_tuner_lookback_days": 30,
        "dealflow_x_tuner_require_horizon_alignment": True,
    }
    policy = evaluate_x_budget_policy(config=config, as_of_date="2026-02-06", base_dir=base)
    assert policy["action"] == "HOLD"
    assert "disagree" in policy["reason"].lower()
    assert policy["recommended"]["max_api_calls_per_run"] == 8


def test_x_budget_tuner_respects_budget_and_call_guardrails(tmp_path):
    base = tmp_path / "eval_results" / "deal_flow"
    _write_summary(
        base,
        "2026-02-05",
        {
            "cashtag_momentum": _family_block(4, 3.0, 0.8),
            "social_momentum": _family_block(3, 2.0, 0.7),
            "news_catalyst": _family_block(3, 1.8, 0.7),
        },
    )
    config = {
        "dealflow_x_auto_tune_enabled": True,
        "dealflow_x_auto_tune_apply": True,
        "dealflow_x_max_api_calls_per_run": 14,
        "dealflow_x_daily_budget_usd": 14.0,
        "dealflow_x_cost_per_api_call_usd": 1.0,
        "dealflow_x_tuner_min_calls": 1,
        "dealflow_x_tuner_max_calls": 15,
        "dealflow_x_tuner_max_step_calls": 3,
        "dealflow_x_tuner_min_evaluated": 6,
        "dealflow_x_tuner_edge_up_threshold": 1.0,
        "dealflow_x_tuner_edge_down_threshold": -1.0,
        "dealflow_x_tuner_win_rate_up": 0.55,
        "dealflow_x_tuner_win_rate_down": 0.45,
        "dealflow_x_tuner_lookback_days": 30,
        "dealflow_x_tuner_min_daily_budget_usd": 8.0,
        "dealflow_x_tuner_max_daily_budget_usd": 14.0,
    }
    policy = evaluate_x_budget_policy(config=config, as_of_date="2026-02-06", base_dir=base)
    assert policy["action"] == "HOLD"
    assert policy["recommended"]["max_api_calls_per_run"] == 14
    assert policy["recommended"]["daily_budget_usd"] == 14.0
