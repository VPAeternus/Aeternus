import json

from tradingagents.research.fundamental_autoresearch.registry import (
    choose_canonical_winner,
    get_active_strategy,
    load_signal_registry,
    promote_strategy,
    save_signal_registry,
)


def test_save_and_load_signal_registry_round_trip(tmp_path):
    rows = [
        {
            "strategy": "health_0p5__inv_growth_0p1__inv_quality_0p4",
            "primary_metric_name": "rank_ic_60d_sector_neutral",
            "primary_metric_value": 0.087029,
            "coverage_ratio": 0.99,
            "observations": 1588,
            "status": "candidate",
            "gate_status": "PENDING",
        }
    ]

    path = save_signal_registry(
        rows,
        results_root=tmp_path,
        run_date="2026-03-09",
        registry_name="fundamental_signals",
    )

    assert path.name == "fundamental_signals.json"

    loaded = load_signal_registry(
        results_root=tmp_path,
        run_date="2026-03-09",
        registry_name="fundamental_signals",
    )

    assert loaded == rows
    assert json.loads(path.read_text())[0]["strategy"] == rows[0]["strategy"]


def test_choose_canonical_winner_prefers_top_promotable_signal():
    rows = [
        {
            "strategy": "baseline_v1",
            "primary_metric_name": "rank_ic_60d_sector_neutral",
            "primary_metric_value": 0.05,
            "coverage_ratio": 0.99,
            "observations": 1588,
            "status": "candidate",
            "gate_status": "FAILED",
        },
        {
            "strategy": "health_0p5__inv_growth_0p1__inv_quality_0p4",
            "primary_metric_name": "rank_ic_60d_sector_neutral",
            "primary_metric_value": 0.087029,
            "coverage_ratio": 0.99,
            "observations": 1588,
            "status": "shadow",
            "gate_status": "PASSED",
        },
    ]

    winner = choose_canonical_winner(rows)

    assert winner["strategy"] == "health_0p5__inv_growth_0p1__inv_quality_0p4"
    assert winner["gate_status"] == "PASSED"


def test_get_active_strategy_prefers_promoted_then_shadow(tmp_path):
    rows = [
        {
            "strategy": "shadow_a",
            "primary_metric_value": 0.08,
            "recommended_status": "shadow",
            "weights": {"health": 0.5, "growth": -0.1, "quality": -0.4, "capital_discipline": 0.0, "valuation": 0.0},
        },
        {
            "strategy": "promoted_b",
            "primary_metric_value": 0.07,
            "status": "promoted",
            "weights": {"health": 0.6, "growth": -0.1, "quality": -0.3, "capital_discipline": 0.0, "valuation": 0.0},
        },
    ]
    save_signal_registry(rows, results_root=tmp_path, run_date="2026-03-09")

    active = get_active_strategy(results_root=tmp_path, run_date="2026-03-09")

    assert active is not None
    assert active["strategy"] == "promoted_b"
    assert active["resolved_status"] == "promoted"


def test_get_active_strategy_falls_back_to_latest_shadow_registry(tmp_path):
    save_signal_registry(
        [
            {
                "strategy": "shadow_old",
                "primary_metric_value": 0.06,
                "recommended_status": "shadow",
                "weights": {"health": 0.5, "growth": -0.1, "quality": -0.4, "capital_discipline": 0.0, "valuation": 0.0},
            }
        ],
        results_root=tmp_path,
        run_date="2026-03-08",
    )
    save_signal_registry(
        [
            {
                "strategy": "shadow_new",
                "primary_metric_value": 0.09,
                "recommended_status": "shadow",
                "weights": {"health": 0.4, "growth": -0.1, "quality": -0.5, "capital_discipline": 0.0, "valuation": 0.0},
            }
        ],
        results_root=tmp_path,
        run_date="2026-03-09",
    )

    active = get_active_strategy(results_root=tmp_path)

    assert active is not None
    assert active["strategy"] == "shadow_new"
    assert active["resolved_status"] == "shadow"
    assert active["registry_run_date"] == "2026-03-09"


def test_promote_strategy_marks_selected_row_active_and_demotes_existing():
    rows = [
        {
            "strategy": "old_shadow",
            "primary_metric_value": 0.08,
            "status": "shadow",
            "recommended_status": "shadow",
        },
        {
            "strategy": "new_candidate",
            "primary_metric_value": 0.09,
            "status": "candidate",
            "recommended_status": "candidate",
        },
    ]

    updated = promote_strategy(
        rows,
        strategy="new_candidate",
        status="shadow",
        robustness={"by_horizon": {"60d": {"primary_metric_value": 0.02}}},
    )

    promoted = next(row for row in updated if row["strategy"] == "new_candidate")
    demoted = next(row for row in updated if row["strategy"] == "old_shadow")

    assert promoted["status"] == "shadow"
    assert promoted["recommended_status"] == "shadow"
    assert promoted["manual_override"] is True
    assert "robustness_summary" in promoted
    assert demoted["status"] == "candidate"
    assert demoted["recommended_status"] == "candidate"
