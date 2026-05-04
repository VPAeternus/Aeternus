from tradingagents.research.fundamental_autoresearch.promotion_gate import evaluate_promotion_gate
from tradingagents.research.fundamental_autoresearch.registry import choose_canonical_winner
from tradingagents.research.fundamental_autoresearch.robustness import evaluate_strategy_robustness
from tradingagents.research.fundamental_autoresearch.search import run_constrained_search


def build_signal_registry_rows(
    rows: list[dict],
    *,
    top_robustness: dict[str, dict] | None = None,
) -> list[dict]:
    top_robustness = top_robustness or {}
    registry_rows: list[dict] = []
    for row in rows:
        robustness = top_robustness.get(row["strategy"])
        if robustness:
            registry_rows.append(evaluate_promotion_gate(row, robustness=robustness))
        else:
            registry_rows.append(
                {
                    **row,
                    "gate_status": "PENDING",
                    "recommended_status": "candidate",
                    "failed_checks": ["robustness_missing"],
                }
            )
    return registry_rows


def run_constrained_autoresearch(
    rows: list[dict],
    *,
    dataset_name: str,
    top_n: int = 10,
    robustness_top_n: int = 0,
) -> dict:
    ranked_results = run_constrained_search(rows, dataset_name=dataset_name)
    leaderboard = ranked_results[:top_n]
    top_robustness = {}
    for row in leaderboard[:robustness_top_n]:
        top_robustness[row["strategy"]] = evaluate_strategy_robustness(
            rows,
            strategy=row["strategy"],
        )
    registry_rows = build_signal_registry_rows(leaderboard, top_robustness=top_robustness)
    best_strategy = choose_canonical_winner(registry_rows)

    return {
        "strategy_count": len(ranked_results),
        "leaderboard": registry_rows,
        "best_strategy": best_strategy,
        "top_robustness": top_robustness,
        "registry_rows": registry_rows,
    }
