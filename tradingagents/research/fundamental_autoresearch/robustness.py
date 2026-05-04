from datetime import date

from tradingagents.research.fundamental_autoresearch.evaluate import evaluate_scored_rows
from tradingagents.research.fundamental_autoresearch.score import score_feature_row_with_weights
from tradingagents.research.fundamental_autoresearch.search import constrained_strategy_weights


def _year_bucket(iso_date: str) -> str:
    year = date.fromisoformat(iso_date).year
    if year < 2010:
        return "pre_2010"
    if year <= 2019:
        return "2010_2019"
    return "2020_2026"


def _evaluate_for_horizon(rows: list[dict], horizon: str, strategy: str) -> dict:
    remapped = []
    return_key = f"return_{horizon}"
    for row in rows:
        remapped.append(
            {
                **row,
                "return_60d": row.get(return_key),
            }
        )
    summary = evaluate_scored_rows(remapped, dataset_name="robustness", score_version=strategy)
    return {
        "primary_metric_name": summary.primary_metric_name.replace("60d", horizon),
        "primary_metric_value": summary.primary_metric_value,
        "coverage_ratio": summary.coverage_ratio,
        "observations": summary.observations,
    }


def evaluate_strategy_robustness(rows: list[dict], *, strategy: str) -> dict:
    weights = constrained_strategy_weights(strategy)
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

    by_horizon = {
        horizon: _evaluate_for_horizon(scored_rows, horizon, strategy)
        for horizon in ("20d", "60d", "120d", "252d")
    }

    by_era = {}
    era_buckets = {}
    for row in scored_rows:
        era_buckets.setdefault(_year_bucket(row["effective_market_date"]), []).append(row)
    for era, era_rows in era_buckets.items():
        by_era[era] = _evaluate_for_horizon(era_rows, "60d", strategy)

    by_sector = {}
    sector_buckets = {}
    for row in scored_rows:
        sector_buckets.setdefault(row["sector"], []).append(row)
    for sector, sector_rows in sector_buckets.items():
        by_sector[sector] = _evaluate_for_horizon(sector_rows, "60d", strategy)

    return {
        "strategy": strategy,
        "by_horizon": by_horizon,
        "by_era": by_era,
        "by_sector": by_sector,
    }
