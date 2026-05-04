from tradingagents.research.fundamental_autoresearch import replay_arena as replay_arena_module


def test_run_replay_arena_ranks_strategies_by_horizon(monkeypatch):
    rows = [
        {"ticker": "AAPL", "sector": "Technology", "effective_market_date": "2024-01-01", "return_20d": 0.04, "return_60d": 0.08, "return_120d": 0.10, "return_252d": 0.14},
        {"ticker": "MSFT", "sector": "Technology", "effective_market_date": "2024-01-01", "return_20d": 0.03, "return_60d": 0.07, "return_120d": 0.09, "return_252d": 0.12},
        {"ticker": "XOM", "sector": "Energy", "effective_market_date": "2024-01-01", "return_20d": 0.01, "return_60d": 0.03, "return_120d": 0.04, "return_252d": 0.06},
        {"ticker": "CVX", "sector": "Energy", "effective_market_date": "2024-01-01", "return_20d": 0.00, "return_60d": 0.02, "return_120d": 0.03, "return_252d": 0.05},
    ]

    strategy_scores = {
        "baseline_v1": {"AAPL": 50.0, "MSFT": 52.0, "XOM": 70.0, "CVX": 68.0},
        "health_only": {"AAPL": 85.0, "MSFT": 82.0, "XOM": 72.0, "CVX": 70.0},
        "quality_only_inverted": {"AAPL": 78.0, "MSFT": 76.0, "XOM": 60.0, "CVX": 62.0},
    }

    def _fake_score_feature_row(row, *, strategy="baseline_v1"):
        score = strategy_scores[strategy][row["ticker"]]
        return type(
            "ScoreResult",
            (),
            {
                "fundamental_score": score,
                "ticker": row["ticker"],
                "effective_market_date": row["effective_market_date"],
                "growth_score": score,
                "quality_score": score,
                "health_score": score,
                "capital_discipline_score": score,
                "valuation_score": score,
                "score_version": strategy,
            },
        )()

    monkeypatch.setattr(replay_arena_module, "score_feature_row", _fake_score_feature_row)

    payload = replay_arena_module.run_replay_arena(
        rows,
        strategies=["baseline_v1", "health_only", "quality_only_inverted"],
        baseline_strategy="baseline_v1",
        dataset_name="prepared_json",
    )

    assert payload["baseline_strategy"] == "baseline_v1"
    assert payload["winners_by_horizon"]["60d"]["strategy"] == "health_only"
    assert payload["by_strategy"]["health_only"]["by_horizon"]["60d"]["primary_metric_value"] >= payload["by_strategy"]["baseline_v1"]["by_horizon"]["60d"]["primary_metric_value"]
    assert payload["vs_baseline"]["quality_only_inverted"]["60d"]["primary_metric_delta"] >= 0.0


def test_run_replay_arena_supports_constrained_strategy_names(monkeypatch):
    rows = [
        {"ticker": "AAPL", "sector": "Technology", "effective_market_date": "2024-01-01", "return_20d": 0.04, "return_60d": 0.08, "return_120d": 0.10, "return_252d": 0.14},
        {"ticker": "MSFT", "sector": "Technology", "effective_market_date": "2024-01-01", "return_20d": 0.03, "return_60d": 0.07, "return_120d": 0.09, "return_252d": 0.12},
        {"ticker": "XOM", "sector": "Energy", "effective_market_date": "2024-01-01", "return_20d": 0.01, "return_60d": 0.03, "return_120d": 0.04, "return_252d": 0.06},
        {"ticker": "CVX", "sector": "Energy", "effective_market_date": "2024-01-01", "return_20d": 0.00, "return_60d": 0.02, "return_120d": 0.03, "return_252d": 0.05},
    ]

    monkeypatch.setattr(
        replay_arena_module,
        "score_feature_row",
        lambda row, *, strategy="baseline_v1": (_ for _ in ()).throw(ValueError("unknown")),
    )
    monkeypatch.setattr(
        replay_arena_module,
        "constrained_strategy_weights",
        lambda strategy: {"growth": -0.1, "quality": -0.4, "health": 0.5, "capital_discipline": 0.0, "valuation": 0.0},
    )

    def _fake_score_with_weights(row, *, component_weights, strategy_name):
        score_map = {"AAPL": 85.0, "MSFT": 82.0, "XOM": 72.0, "CVX": 70.0}
        return type(
            "ScoreResult",
            (),
            {
                "fundamental_score": score_map[row["ticker"]],
                "ticker": row["ticker"],
                "effective_market_date": row["effective_market_date"],
                "growth_score": score_map[row["ticker"]],
                "quality_score": score_map[row["ticker"]],
                "health_score": score_map[row["ticker"]],
                "capital_discipline_score": score_map[row["ticker"]],
                "valuation_score": score_map[row["ticker"]],
                "score_version": strategy_name,
            },
        )()

    monkeypatch.setattr(replay_arena_module, "score_feature_row_with_weights", _fake_score_with_weights)

    payload = replay_arena_module.run_replay_arena(
        rows,
        strategies=["health_0p5__inv_growth_0p1__inv_quality_0p4"],
        baseline_strategy="health_0p5__inv_growth_0p1__inv_quality_0p4",
        dataset_name="prepared_json",
    )

    assert payload["winners_by_horizon"]["60d"]["strategy"] == "health_0p5__inv_growth_0p1__inv_quality_0p4"
