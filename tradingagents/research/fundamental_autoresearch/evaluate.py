from tradingagents.research.fundamental_autoresearch.contracts import FundamentalEvaluationSummary
from tradingagents.research.fundamental_autoresearch.score import score_feature_row


def _rank(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    for rank, (index, _) in enumerate(ordered, start=1):
        ranks[index] = float(rank)
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 2 or len(xs) != len(ys):
        return 0.0
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = sum((x - mean_x) ** 2 for x in xs) ** 0.5
    den_y = sum((y - mean_y) ** 2 for y in ys) ** 0.5
    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)


def _sector_neutralize(rows: list[dict], value_key: str) -> list[float]:
    sector_values: dict[str, list[float]] = {}
    for row in rows:
        sector_values.setdefault(row["sector"], []).append(float(row[value_key]))
    sector_means = {sector: sum(values) / len(values) for sector, values in sector_values.items()}
    return [float(row[value_key]) - sector_means[row["sector"]] for row in rows]


def evaluate_scored_rows(
    rows: list[dict],
    *,
    dataset_name: str,
    score_version: str,
) -> FundamentalEvaluationSummary:
    usable_rows = [row for row in rows if row.get("return_60d") is not None]
    coverage_ratio = (len(usable_rows) / len(rows)) if rows else 0.0
    if len(usable_rows) < 2:
        return FundamentalEvaluationSummary(
            dataset_name=dataset_name,
            score_version=score_version,
            primary_metric_name="rank_ic_60d_sector_neutral",
            primary_metric_value=0.0,
            coverage_ratio=coverage_ratio,
            observations=len(usable_rows),
        )

    neutral_scores = _sector_neutralize(usable_rows, "fundamental_score")
    neutral_returns = _sector_neutralize(usable_rows, "return_60d")
    rank_ic = _pearson(_rank(neutral_scores), _rank(neutral_returns))
    return FundamentalEvaluationSummary(
        dataset_name=dataset_name,
        score_version=score_version,
        primary_metric_name="rank_ic_60d_sector_neutral",
        primary_metric_value=round(rank_ic, 6),
        coverage_ratio=round(coverage_ratio, 6),
        observations=len(usable_rows),
    )


def compare_baseline_strategies(
    rows: list[dict],
    *,
    dataset_name: str,
    strategies: list[str] | None = None,
) -> list[dict]:
    strategies = strategies or [
        "baseline_v1",
        "growth_only",
        "quality_only",
        "health_only",
        "capital_discipline_only",
        "valuation_only",
        "growth_quality",
        "quality_valuation",
        "growth_only_inverted",
        "quality_only_inverted",
        "growth_quality_inverted",
        "health_minus_growth",
        "health_minus_quality",
    ]

    results: list[dict] = []
    for strategy in strategies:
        scored_rows = []
        for row in rows:
            score = score_feature_row(row, strategy=strategy)
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
                "primary_metric_name": summary.primary_metric_name,
                "primary_metric_value": summary.primary_metric_value,
                "coverage_ratio": summary.coverage_ratio,
                "observations": summary.observations,
            }
        )

    return sorted(results, key=lambda row: row["primary_metric_value"], reverse=True)
