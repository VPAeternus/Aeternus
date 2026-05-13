from tradingagents.research.fundamental.src.panel.schema import (
    REQUIRED_COMPLETE_PANEL_COLUMNS,
)
from tradingagents.research.fundamental.src.panel.validate import validate_complete_panel


def test_validate_complete_panel_fails_on_required_blank_without_reason():
    result = validate_complete_panel(
        [
            {
                "ticker": "AAA",
                "quarter": "2026Q2",
                "revenue_value": "",
                "revenue_value_missing_reason": "",
            }
        ]
    )

    assert result["passed"] is False
    assert result["errors"][0]["code"] == "required_blank_without_reason"


def test_validate_complete_panel_accepts_allowed_source_unavailable_reason():
    result = validate_complete_panel(
        [
            {
                "ticker": "CIFR",
                "quarter": "2022Q1",
                "revenue_value": "",
                "revenue_value_missing_reason": "source_fact_unavailable_as_of",
            }
        ]
    )

    assert result["passed"] is True


def test_validate_complete_panel_rejects_duplicate_ticker_quarter():
    result = validate_complete_panel(
        [
            {"ticker": "AAA", "quarter": "2026Q2"},
            {"ticker": "AAA", "quarter": "2026Q2"},
        ]
    )

    assert result["passed"] is False
    assert any(error["code"] == "duplicate_ticker_quarter" for error in result["errors"])


def test_validate_complete_panel_explicit_missing_required_column_hard_fails():
    result = validate_complete_panel(
        [{"ticker": "AAA", "quarter": "2026Q2"}],
        required_columns=REQUIRED_COMPLETE_PANEL_COLUMNS,
    )

    assert result["passed"] is False
    assert "revenue_value" in result["required_columns_missing"]
    assert any(error["code"] == "missing_required_column" for error in result["errors"])


def test_validate_complete_panel_rejects_blank_or_nonbinary_flag():
    result = validate_complete_panel(
        [
            {"ticker": "AAA", "quarter": "2026Q2", "top15_selected": ""},
            {"ticker": "BBB", "quarter": "2026Q2", "top15_selected": "yes"},
        ],
        required_nonblank_fields=(),
        flag_fields=("top15_selected",),
    )

    assert result["passed"] is False
    assert [error["code"] for error in result["errors"]] == [
        "invalid_flag_value",
        "invalid_flag_value",
    ]


def test_validate_complete_panel_expected_quarters_mismatch():
    result = validate_complete_panel(
        [{"ticker": "AAA", "quarter": "2026Q2"}],
        expected_quarters=("2026Q1", "2026Q2"),
    )

    assert result["passed"] is False
    assert any(error["code"] == "quarter_coverage_mismatch" for error in result["errors"])


def test_validate_complete_panel_top15_identity_mismatch():
    result = validate_complete_panel(
        [
            {"ticker": "AAA", "quarter": "2026Q2", "top15_selected": "1"},
            {"ticker": "BBB", "quarter": "2026Q2", "top15_selected": "0"},
        ],
        top15_rows=[{"ticker": "BBB", "quarter": "2026Q2"}],
    )

    assert result["passed"] is False
    assert any(error["code"] == "top15_identity_mismatch" for error in result["errors"])


def test_validate_complete_panel_top15_identity_uses_quarter_fallback():
    result = validate_complete_panel(
        [{"ticker": "AAA", "quarter": "2026Q2", "top15_selected": "1"}],
        top15_rows=[{"ticker": "AAA"}],
        quarter="2026Q2",
    )

    assert result["passed"] is True


def test_validate_complete_panel_shadow_identity_uses_quarter_fallback():
    result = validate_complete_panel(
        [{"ticker": "BBB", "quarter": "2026Q2", "shadow_selected": "1"}],
        shadow_rows=[{"ticker": "BBB"}],
        quarter="2026Q2",
    )

    assert result["passed"] is True


def test_validate_complete_panel_rejects_forbidden_selection_column():
    result = validate_complete_panel(
        [
            {
                "ticker": "AAA",
                "quarter": "2026Q2",
                "selection_ranking_source_columns": "entry_score_0_100,ticker",
            }
        ],
        forbidden_selection_columns=("entry_score_0_100",),
    )

    assert result["passed"] is False
    assert any(
        error["code"] == "forbidden_selection_column" for error in result["errors"]
    )
