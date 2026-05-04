from __future__ import annotations

from tradingagents.dealflow.question_compiler import compile_question


def test_compile_question_reverse_forensic_classification() -> None:
    payload = compile_question(
        question="MU went up 10% today, why did we miss it?",
        as_of_date="2026-03-17",
    )

    assert payload["query_type"] == "reverse_forensic"
    assert payload["intent"] == "missed_alpha_diagnosis"
    assert payload["manual_only"] is True


def test_compile_question_forward_scenario_classification() -> None:
    payload = compile_question(
        question="Trump announced war on Iran, what happens to our portfolio?",
        as_of_date="2026-03-17",
    )

    assert payload["query_type"] == "forward_scenario"
    assert payload["intent"] == "scenario_impact_analysis"
    assert payload["manual_only"] is True


def test_compile_question_extracts_ticker_and_percent_move() -> None:
    payload = compile_question(
        question="MU went up 10% today, why did we miss it?",
        as_of_date="2026-03-17",
    )

    assert payload["target_entities"] == ["MU"]
    assert payload["observation"]["kind"] == "price_move"
    assert payload["observation"]["value"] == "+10%"


def test_compile_question_falls_back_to_as_of_date() -> None:
    payload = compile_question(
        question="Why did we miss NVDA?",
        as_of_date="2026-03-17",
    )

    assert payload["observation"]["date"] == "2026-03-17"
