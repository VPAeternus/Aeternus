import json
from pathlib import Path


def _write_summary(
    root: Path,
    source_date: str,
    *,
    filename: str,
    stages: list[dict],
) -> None:
    base = root / source_date
    base.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_date": source_date,
        "hypothesis_stage_summary": {
            "lane": "shared",
            "stages": stages,
        },
    }
    (base / filename).write_text(json.dumps(payload, indent=2))


def test_compute_stage_diagnosis_prefers_performance_review_summary(tmp_path):
    from tradingagents.dealflow.stage_diagnosis import compute_stage_diagnosis

    root = tmp_path / "eval_results" / "deal_flow"
    _write_summary(
        root,
        "2026-03-01",
        filename="hindsight.json",
        stages=[
            {
                "stage_id": "shortlist_cut",
                "kept_count": 2,
                "dropped_count": 3,
                "edge_5d": 0.01,
                "edge_20d": None,
                "edge_3m": None,
                "future_winner_recall": 1.0,
                "false_negative_cost": 0.0,
                "sample_size": 5,
            }
        ],
    )
    _write_summary(
        root,
        "2026-03-01",
        filename="performance_review.json",
        stages=[
            {
                "stage_id": "shortlist_cut",
                "kept_count": 2,
                "dropped_count": 3,
                "edge_5d": 0.015,
                "edge_20d": 0.045,
                "edge_3m": 0.12,
                "future_winner_recall": 1.0,
                "false_negative_cost": 0.0,
                "sample_size": 5,
            }
        ],
    )

    result = compute_stage_diagnosis(base_dir=root, last=5)

    assert result["cycles"][0]["artifact"] == "performance_review.json"
    assert result["stages"][0]["stage_id"] == "shortlist_cut"
    assert result["stages"][0]["avg_edge_20d"] == 0.045
    assert result["stages"][0]["avg_edge_3m"] == 0.12


def test_compute_stage_diagnosis_ranks_high_false_negative_cost_stage_first(tmp_path):
    from tradingagents.dealflow.stage_diagnosis import compute_stage_diagnosis

    root = tmp_path / "eval_results" / "deal_flow"
    _write_summary(
        root,
        "2026-03-01",
        filename="performance_review.json",
        stages=[
            {
                "stage_id": "universe_gate_haystack",
                "kept_count": 300,
                "dropped_count": 4200,
                "edge_5d": 0.004,
                "edge_20d": 0.012,
                "edge_3m": 0.03,
                "future_winner_recall": 0.35,
                "false_negative_cost": 0.31,
                "sample_size": 4500,
            },
            {
                "stage_id": "evidence_gate",
                "kept_count": 280,
                "dropped_count": 120,
                "edge_5d": 0.02,
                "edge_20d": 0.05,
                "edge_3m": 0.09,
                "future_winner_recall": 0.82,
                "false_negative_cost": 0.04,
                "sample_size": 400,
            },
        ],
    )
    _write_summary(
        root,
        "2026-03-02",
        filename="performance_review.json",
        stages=[
            {
                "stage_id": "universe_gate_haystack",
                "kept_count": 305,
                "dropped_count": 4180,
                "edge_5d": -0.003,
                "edge_20d": 0.001,
                "edge_3m": None,
                "future_winner_recall": 0.42,
                "false_negative_cost": 0.22,
                "sample_size": 4485,
            },
            {
                "stage_id": "evidence_gate",
                "kept_count": 290,
                "dropped_count": 130,
                "edge_5d": 0.015,
                "edge_20d": 0.035,
                "edge_3m": None,
                "future_winner_recall": 0.75,
                "false_negative_cost": 0.03,
                "sample_size": 420,
            },
        ],
    )

    result = compute_stage_diagnosis(base_dir=root, last=10)

    assert result["stages"][0]["stage_id"] == "universe_gate_haystack"
    assert result["stages"][0]["total_false_negative_cost"] == 0.53
    assert result["stages"][0]["avg_recall"] == 0.385
    assert result["worst_cycles"][0]["stage_id"] == "universe_gate_haystack"
    assert result["diagnosis"].startswith("Inspect universe_gate_haystack first")
