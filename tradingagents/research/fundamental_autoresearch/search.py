from tradingagents.research.fundamental_autoresearch.evaluate import evaluate_scored_rows
from tradingagents.research.fundamental_autoresearch.score import score_feature_row_with_weights


def _format_weight(value: float) -> str:
    return str(round(value, 1)).replace(".", "p")


def _strategy_name(weights: dict[str, float]) -> str:
    parts = [f"health_{_format_weight(weights['health'])}"]
    if weights["growth"] < 0:
        parts.append(f"inv_growth_{_format_weight(abs(weights['growth']))}")
    if weights["quality"] < 0:
        parts.append(f"inv_quality_{_format_weight(abs(weights['quality']))}")
    if weights["capital_discipline"] > 0:
        parts.append(
            f"capital_discipline_{_format_weight(weights['capital_discipline'])}"
        )
    if weights["valuation"] > 0:
        parts.append(f"valuation_{_format_weight(weights['valuation'])}")
    return "__".join(parts)


def _generate_constrained_weight_configs(step: float = 0.1) -> list[dict[str, float]]:
    configs: list[dict[str, float]] = []
    increments = [round(x * step, 1) for x in range(int(1 / step) + 1)]
    capital_discipline_increments = [0.0, 0.1, 0.2]
    for capital_discipline in capital_discipline_increments:
        for inv_growth in increments:
            for inv_quality in increments:
                health = round(1.0 - capital_discipline - inv_growth - inv_quality, 1)
                if health < 0.4:
                    continue
                if health < 0:
                    continue
                if capital_discipline > 0 and health < capital_discipline:
                    continue
                configs.append(
                    {
                        "growth": -inv_growth,
                        "quality": -inv_quality,
                        "health": health,
                        "capital_discipline": capital_discipline,
                        "valuation": 0.0,
                    }
                )
    return configs


def constrained_strategy_weights(strategy: str) -> dict[str, float]:
    for weights in _generate_constrained_weight_configs():
        if _strategy_name(weights) == strategy:
            return weights
    raise ValueError(f"Unknown constrained-search strategy: {strategy}")


def run_constrained_search(
    rows: list[dict],
    *,
    dataset_name: str,
) -> list[dict]:
    results: list[dict] = []
    for weights in _generate_constrained_weight_configs():
        strategy = _strategy_name(weights)
        scored_rows = []
        for row in rows:
            score = score_feature_row_with_weights(
                row,
                component_weights=weights,
                strategy_name=strategy,
            )
            scored_rows.append(
                {
                    **row,
                    "fundamental_score": score.fundamental_score,
                }
            )
        summary = evaluate_scored_rows(
            scored_rows,
            dataset_name=dataset_name,
            score_version=strategy,
        )
        results.append(
            {
                "strategy": strategy,
                "weights": weights,
                "primary_metric_name": summary.primary_metric_name,
                "primary_metric_value": summary.primary_metric_value,
                "coverage_ratio": summary.coverage_ratio,
                "observations": summary.observations,
            }
        )
    return sorted(results, key=lambda row: row["primary_metric_value"], reverse=True)
