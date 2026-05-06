from __future__ import annotations

from typing import Any


MEMO_FIELDS = [
    "ticker",
    "decision_date",
    "decision_type",
    "one_sentence_thesis",
    "why_now",
    "main_causal_driver",
    "expected_upside",
    "expected_downside",
    "valuation_view",
    "liquidity_view",
    "macro_theme_view",
    "position_size_rationale",
    "invalidation_trigger",
    "next_review_date",
]


def build_memo_row(row: dict[str, Any]) -> dict[str, Any]:
    return {field: row.get(field, "") for field in MEMO_FIELDS}
