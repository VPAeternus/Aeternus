from tradingagents.research.fundamental.src.panel.validate import validate_complete_panel
from tradingagents.research.fundamental.src.selection.high_conviction_top10 import (
    SELECTION_ALLOWED_INPUT_COLUMNS,
    SELECTION_FORBIDDEN_INPUT_COLUMNS,
    SELECTION_FORBIDDEN_PREFIXES,
    select_high_conviction_top15_core_deterioration_refill_shadow,
    select_high_conviction_top15_exception_sleeve,
)


def _row(ticker, score, **extra):
    row = {
        "ticker": ticker,
        "quarter": "2026Q2",
        "entry_score_0_100": str(score),
        "confidence": "4",
        "cik": "123",
        "cik_status": "resolved",
        "document_status": "CACHED_READY",
        "revenue_bucket": "$1B-$2B",
    }
    row.update(extra)
    return row


def _rows():
    rows = [_row(f"C{i}", 100 - i) for i in range(12)]
    rows[10].update(
        {
            "ticker": "RMX",
            "entry_score_0_100": "55",
            "rm_buy_review_flag": "1",
            "repricing_momentum_priority": "1",
            "market_repricing_score": "12",
            "primary_theme": "AI infrastructure",
        }
    )
    rows[7].update(
        {
            "score_change": "-2",
            "negative_revision_risk": "2",
            "pre_llm_fundamental_bucket": "weak",
            "primary_theme": "",
            "rm1_low_price_dislocation_momentum": "1",
            "rm2_weak_acceleration": "1",
            "rm4_persistent_repricing_wave": "1",
        }
    )
    for idx, row in enumerate(rows):
        row.update(
            {
                "return_10d_pct": str(999 - idx),
                "return_20d_pct": str(999 - idx),
                "return_30d_pct": str(999 - idx),
                "return_60d_pct": str(999 - idx),
                "return_90d_pct": str(999 - idx),
                "winner_90d_30pct": "1",
                "loser_90d_minus30pct": "0",
                "monitoring_score_0_100": str(1000 - idx),
                "final_rank_score_0_100": str(2000 - idx),
                "rank_score_label": "future_label",
                "monitoring_status": "future_status",
            }
        )
    return rows


def _logged_columns(result):
    seen = set()
    for row in result["selected_rows"]:
        seen.update(part.strip() for part in str(row.get("selection_ranking_source_columns") or "").split(",") if part.strip())
    return seen


def _selected_identity(result):
    return [
        (
            row.get("ticker"),
            row.get("selected_sleeve"),
            str(row.get("selection_rank") or row.get("selected_sleeve_rank") or ""),
        )
        for row in result["selected_rows"]
    ]


def test_top15_selection_unchanged_when_future_labels_change():
    baseline = select_high_conviction_top15_exception_sleeve(
        _rows(),
        {"enabled": True, "core_n": 10, "exception_slots": 2},
    )
    mutated = _rows()
    for idx, row in enumerate(mutated):
        row["return_90d_pct"] = str(-999 + idx)
        row["winner_90d_30pct"] = "0"
        row["loser_90d_minus30pct"] = "1"
        row["monitoring_score_0_100"] = str(idx)
        row["final_rank_score_0_100"] = str(idx)
        row["rank_score_label"] = "mutated_future_label"
        row["monitoring_status"] = "mutated_future_status"
    changed = select_high_conviction_top15_exception_sleeve(
        mutated,
        {"enabled": True, "core_n": 10, "exception_slots": 2},
    )

    assert _selected_identity(changed) == _selected_identity(baseline)


def test_top15_selection_uses_only_allowed_pit_columns():
    result = select_high_conviction_top15_exception_sleeve(
        _rows(),
        {"enabled": True, "core_n": 10, "exception_slots": 2},
    )

    columns = _logged_columns(result)
    assert columns
    assert columns <= SELECTION_ALLOWED_INPUT_COLUMNS
    assert not columns.intersection(SELECTION_FORBIDDEN_INPUT_COLUMNS)
    assert not any(column.startswith(SELECTION_FORBIDDEN_PREFIXES) for column in columns)


def test_shadow_selection_uses_only_allowed_pit_columns():
    result = select_high_conviction_top15_core_deterioration_refill_shadow(
        _rows(),
        {"enabled": True, "exception_slots": 1, "core_deterioration_refill": {"enabled": True, "mode": "downgrade"}},
    )

    columns = _logged_columns(result)
    assert columns
    assert columns <= SELECTION_ALLOWED_INPUT_COLUMNS
    assert not columns.intersection(SELECTION_FORBIDDEN_INPUT_COLUMNS)
    assert not any(column.startswith(SELECTION_FORBIDDEN_PREFIXES) for column in columns)


def test_selection_gate_fails_if_final_rank_or_return_column_used():
    result = validate_complete_panel(
        [
            {
                "ticker": "AAA",
                "quarter": "2026Q2",
                "selection_ranking_source_columns": "entry_score_0_100,final_rank_score_0_100,return_90d_pct",
            }
        ],
        forbidden_selection_columns=SELECTION_FORBIDDEN_INPUT_COLUMNS,
    )

    assert result["passed"] is False
    rejected = {error.get("column") for error in result["errors"] if error["code"] == "forbidden_selection_column"}
    assert {"final_rank_score_0_100", "return_90d_pct"} <= rejected


def test_selection_gate_default_rejects_rank_score_label():
    result = validate_complete_panel(
        [
            {
                "ticker": "AAA",
                "quarter": "2026Q2",
                "selection_ranking_source_columns": "entry_score_0_100,rank_score_label",
            }
        ]
    )

    assert result["passed"] is False
    assert any(error.get("column") == "rank_score_label" for error in result["errors"])
