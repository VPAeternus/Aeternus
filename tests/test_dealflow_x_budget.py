from tradingagents.dealflow.x_budget import evaluate_x_budget_policy


def test_x_budget_tuner_disabled(tmp_path):
    config = {
        "dealflow_x_auto_tune_enabled": False,
        "dealflow_x_max_api_calls_per_run": 8,
        "dealflow_x_daily_budget_usd": 15.0,
    }
    policy = evaluate_x_budget_policy(
        config=config,
        as_of_date="2026-02-06",
        base_dir=tmp_path / "deal_flow",
    )
    assert policy["action"] == "DISABLED"
    assert policy["applied"] is False


def test_x_budget_tuner_waits_for_post_fundamental_attribution(tmp_path):
    config = {
        "dealflow_x_auto_tune_enabled": True,
        "dealflow_x_auto_tune_apply": True,
        "dealflow_x_max_api_calls_per_run": 8,
        "dealflow_x_daily_budget_usd": 15.0,
    }
    policy = evaluate_x_budget_policy(
        config=config,
        as_of_date="2026-02-06",
        base_dir=tmp_path / "deal_flow",
    )
    assert policy["action"] == "HOLD"
    assert policy["applied"] is False
    assert "post-fundamental" in policy["reason"]
