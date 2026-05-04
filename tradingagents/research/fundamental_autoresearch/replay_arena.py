from tradingagents.research.fundamental_autoresearch.evaluate import evaluate_scored_rows
from tradingagents.research.fundamental_autoresearch.score import score_feature_row, score_feature_row_with_weights
from tradingagents.research.fundamental_autoresearch.search import constrained_strategy_weights


def _score_for_strategy(row: dict, *, strategy: str):
    try:
        return score_feature_row(row, strategy=strategy)
    except ValueError:
        return score_feature_row_with_weights(
            row,
            component_weights=constrained_strategy_weights(strategy),
            strategy_name=strategy,
        )


def _evaluate_for_horizon(
    rows: list[dict],
    *,
    strategy: str,
    horizon: str,
    dataset_name: str,
) -> dict:
    remapped_rows = []
    return_key = f"return_{horizon}"
    for row in rows:
        score = _score_for_strategy(row, strategy=strategy)
        remapped_rows.append(
            {
                **row,
                "fundamental_score": score.fundamental_score,
                "return_60d": row.get(return_key),
            }
        )
    summary = evaluate_scored_rows(
        remapped_rows,
        dataset_name=dataset_name,
        score_version=strategy,
    )
    return {
        "primary_metric_name": summary.primary_metric_name.replace("60d", horizon),
        "primary_metric_value": summary.primary_metric_value,
        "coverage_ratio": summary.coverage_ratio,
        "observations": summary.observations,
    }


def run_replay_arena(
    rows: list[dict],
    *,
    strategies: list[str],
    baseline_strategy: str,
    dataset_name: str,
) -> dict:
    horizons = ("20d", "60d", "120d", "252d")
    by_strategy: dict[str, dict] = {}
    for strategy in strategies:
        by_strategy[strategy] = {
            "by_horizon": {
                horizon: _evaluate_for_horizon(
                    rows,
                    strategy=strategy,
                    horizon=horizon,
                    dataset_name=dataset_name,
                )
                for horizon in horizons
            }
        }

    winners_by_horizon = {}
    for horizon in horizons:
        winner_strategy = max(
            strategies,
            key=lambda candidate: float(by_strategy[candidate]["by_horizon"][horizon]["primary_metric_value"]),
        )
        winners_by_horizon[horizon] = {
            "strategy": winner_strategy,
            **by_strategy[winner_strategy]["by_horizon"][horizon],
        }

    baseline_horizons = by_strategy[baseline_strategy]["by_horizon"]
    vs_baseline: dict[str, dict] = {}
    for strategy in strategies:
        if strategy == baseline_strategy:
            continue
        vs_baseline[strategy] = {}
        for horizon in horizons:
            baseline_row = baseline_horizons[horizon]
            strategy_row = by_strategy[strategy]["by_horizon"][horizon]
            vs_baseline[strategy][horizon] = {
                "primary_metric_delta": round(
                    float(strategy_row["primary_metric_value"]) - float(baseline_row["primary_metric_value"]),
                    6,
                ),
                "coverage_ratio_delta": round(
                    float(strategy_row["coverage_ratio"]) - float(baseline_row["coverage_ratio"]),
                    6,
                ),
                "observation_delta": int(strategy_row["observations"]) - int(baseline_row["observations"]),
            }

    return {
        "baseline_strategy": baseline_strategy,
        "strategies": strategies,
        "by_strategy": by_strategy,
        "winners_by_horizon": winners_by_horizon,
        "vs_baseline": vs_baseline,
    }
