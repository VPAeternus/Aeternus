import sys
from pathlib import Path

FUNDAMENTAL_ROOT = Path(__file__).resolve().parents[1] / "tradingagents" / "research" / "fundamental"
if str(FUNDAMENTAL_ROOT) not in sys.path:
    sys.path.insert(0, str(FUNDAMENTAL_ROOT))

from src.features.hp_subtiers import HP_LABELS
from src.features.scoring import compute_entry_score, hp_structure_score
from src.pipeline.run_on_new_filing import build_signal_tables
from src.pipeline.run_quarter import _add_entry_qoq_pct


def _base_row(**extra):
    row = {
        "ticker": "HPX",
        "quarter": "2026Q1",
        "tradable_date": "2026-05-01",
        "entry_open": "30",
        "revenue_bucket": "$1B-$10B",
        "pre_llm_fundamental_score": "-1",
        "pre_llm_fundamental_bucket": "weak",
    }
    row.update(extra)
    return row


def test_hp_candidate_uses_total_structure_score_in_entry_raw_score():
    scored = compute_entry_score(_base_row(entry_qoq_pct="25", hp2_dislocation_momentum_priority=1, hp_structure_score=18))

    assert scored["tier_structure_score"] == 0
    assert scored["hp_structure_score"] == 18
    assert scored["total_structure_score"] == 18
    assert scored["entry_raw_score"] == 21


def test_forbidden_future_and_monitoring_columns_do_not_change_entry_score():
    row = _base_row(entry_qoq_pct="25", hp2_dislocation_momentum_priority=1, hp_structure_score=18)
    baseline = compute_entry_score(row)
    injected = compute_entry_score(
        {
            **row,
            "return_10d_pct": "999",
            "return_20d_pct": "999",
            "return_30d_pct": "999",
            "return_60d_pct": "999",
            "return_90d_pct": "999",
            "current_return_pct": "999",
            "return_since_signal_pct": "999",
            "return_since_purchase_pct": "999",
            "active_monitoring_score_0_100": "100",
            "monitoring_score_0_100": "100",
        }
    )

    assert injected["entry_raw_score"] == baseline["entry_raw_score"]
    assert injected["entry_score_0_100"] == baseline["entry_score_0_100"]
    assert "return_since_signal_pct" not in injected["entry_score_inputs"]
    assert "return_since_purchase_pct" not in injected["entry_score_inputs"]


def test_hp_structure_score_uses_strict_hp_boolean_fields():
    for false_value in ["0", "False", "false", ""]:
        assert hp_structure_score({"hp2_dislocation_momentum_priority": false_value}) == 0

    assert hp_structure_score({"hp2_dislocation_momentum_priority": 1}) == 18
    assert hp_structure_score({"hp2_dislocation_momentum_priority": "true"}) == 18


def test_hp_structure_score_allows_only_known_hp_label_strings():
    label = HP_LABELS["hp2_dislocation_momentum_priority"]

    assert hp_structure_score({"hp2_dislocation_momentum_priority": label}) == 18
    assert hp_structure_score({"hp2_dislocation_momentum_priority": "arbitrary non-empty label"}) == 0


def test_build_signal_tables_expands_hp_features_before_scoring():
    signal_rows, _, _ = build_signal_tables([_base_row(entry_qoq_pct="25")], as_of="2026-05-08")

    row = signal_rows[0]
    assert bool(row["hp2_dislocation_momentum_priority"])
    assert row["hp_structure_score"] == 18
    assert row["total_structure_score"] == 18
    assert row["entry_raw_score"] >= 18


def test_build_signal_tables_preserves_input_row_order_after_batch_expansion():
    rows = [
        _base_row(ticker="ZZZ", entry_qoq_pct="25"),
        _base_row(ticker="AAA", entry_qoq_pct="5"),
        _base_row(ticker="MMM", entry_qoq_pct="40"),
    ]

    signal_rows, tier_rows, pre_rows = build_signal_tables(rows, as_of="2026-05-08")

    assert [row["ticker"] for row in signal_rows] == ["ZZZ", "AAA", "MMM"]
    assert [row["ticker"] for row in tier_rows] == ["ZZZ", "AAA", "MMM"]
    assert [row["ticker"] for row in pre_rows] == ["ZZZ", "AAA", "MMM"]


def test_add_entry_qoq_pct_persists_prior_entry_qoq_pct_from_prior_row():
    rows = [_base_row(quarter="2026Q1", entry_open="156", pre_llm_fundamental_score="1")]
    prior_rows = [
        _base_row(quarter="2025Q4", entry_open="120", entry_qoq_pct="20", pre_llm_fundamental_score="-1"),
    ]

    result = _add_entry_qoq_pct(rows, prior_rows)

    assert result[0]["entry_qoq_pct"] == 30.0
    assert result[0]["prior_entry_qoq_pct"] == "20"
