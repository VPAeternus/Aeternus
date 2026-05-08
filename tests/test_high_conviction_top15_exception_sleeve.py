import csv

from tradingagents.research.fundamental.src.selection.high_conviction_top10 import (
    RightTailExceptionConfig,
    _is_right_tail_exception_candidate,
    _right_tail_exception_score,
    select_high_conviction_top10,
    select_high_conviction_top15_exception_sleeve,
    select_top15_from_csv,
)


def row(ticker, score=80, confidence=4, **extra):
    base = {
        "ticker": ticker,
        "entry_score_0_100": str(score),
        "confidence": str(confidence),
        "cik": "123456",
        "cik_status": "resolved",
        "document_status": "CACHED_READY",
        "lane": "core",
    }
    base.update(extra)
    return base


def test_top15_preserves_top10_when_exception_disabled():
    rows = [row(f"C{i}", 100 - i) for i in range(12)]
    top10 = select_high_conviction_top10(rows, {"top_n": 10})["selected_rows"]
    top15 = select_high_conviction_top15_exception_sleeve(rows, RightTailExceptionConfig(enabled=False))["selected_rows"]
    assert [r["ticker"] for r in top15] == [r["ticker"] for r in top10]
    assert all(r["selected_sleeve"] == "core" for r in top15)


def test_top15_selects_10_core_plus_5_exceptions():
    rows = [row(f"C{i}", 100 - i) for i in range(10)] + [row(f"E{i}", 30 + i, rm1_low_price_dislocation_momentum="1", primary_theme=f"theme{i}") for i in range(5)]
    result = select_high_conviction_top15_exception_sleeve(rows, {"enabled": True})
    assert result["summary"]["core_count"] == 10
    assert result["summary"]["exception_count"] == 5
    assert len(result["selected_rows"]) == 15


def test_exception_candidate_requires_rm_or_hp_or_theme_or_akg_signal():
    ok, reasons = _is_right_tail_exception_candidate(row("NO", 50), RightTailExceptionConfig(enabled=True))
    assert ok is False
    assert reasons == ["NO_RIGHT_TAIL_SIGNAL"]


def test_exception_candidate_allows_low_entry_score_with_rm_signal():
    ok, reasons = _is_right_tail_exception_candidate(row("LOW", 20, rm1_low_price_dislocation_momentum="1"), RightTailExceptionConfig(enabled=True))
    assert ok is True
    assert "SINGLE_RM_SIGNAL_BUCKET" in reasons


def test_market_repricing_alone_allows_low_score_exception():
    ok, reasons = _is_right_tail_exception_candidate(row("MRKT", 50, market_repricing_score="10"), RightTailExceptionConfig(enabled=True))
    assert ok is True
    assert "MARKET_REPRICING" in reasons


def test_exception_candidate_blocks_post_llm_demote():
    ok, reasons = _is_right_tail_exception_candidate(row("BAD", 80, rm1_low_price_dislocation_momentum="1", post_llm_demote_flag="1"), RightTailExceptionConfig(enabled=True))
    assert ok is False
    assert "POST_LLM_DEMOTE" in reasons


def test_near_threshold_crdo_style_exception():
    candidate = row("CRDO", 65, rm_buy_review_flag="1", market_repricing_score="10")
    ok, reasons = _is_right_tail_exception_candidate(candidate, RightTailExceptionConfig(enabled=True))
    assert ok is True
    assert "NEAR_THRESHOLD_EXCEPTION" in reasons


def test_rm2plus_penalty_applies_without_confirmation():
    score, parts = _right_tail_exception_score(row("RM2", 50, rm1_low_price_dislocation_momentum="1", rm2_weak_acceleration="1"))
    assert parts["rm2plus_no_confirmation_penalty"] == -10
    assert score == 40


def test_single_rm_bucket_priority():
    rows = [row(f"C{i}", 100 - i) for i in range(10)] + [
        row("ONE", 50, rm1_low_price_dislocation_momentum="1"),
        row("TWO", 50, rm1_low_price_dislocation_momentum="1", rm2_weak_acceleration="1"),
    ]
    result = select_high_conviction_top15_exception_sleeve(rows, {"enabled": True, "exception_slots": 2})
    assert result["exception_rows"][0]["ticker"] == "ONE"


def test_two_available_single_rm_exceptions_selected_before_non_single_rm():
    rows = [row(f"C{i}", 100 - i) for i in range(10)] + [
        row("MULTI", 80, rm1_low_price_dislocation_momentum="1", rm2_weak_acceleration="1", primary_theme="ai"),
        row("ONE", 30, rm1_low_price_dislocation_momentum="1", primary_theme="software"),
        row("TWO", 29, rm2_weak_acceleration="1", primary_theme="energy"),
    ]
    result = select_high_conviction_top15_exception_sleeve(rows, {"enabled": True, "exception_slots": 3})
    assert [r["ticker"] for r in result["exception_rows"][:2]] == ["ONE", "TWO"]
    assert result["exception_rows"][2]["ticker"] == "MULTI"


def test_exception_sleeve_no_duplicate_core_tickers():
    rows = [row(f"C{i}", 100 - i, rm1_low_price_dislocation_momentum="1") for i in range(12)]
    result = select_high_conviction_top15_exception_sleeve(rows, {"enabled": True, "exception_slots": 2})
    tickers = [r["ticker"] for r in result["selected_rows"]]
    assert len(tickers) == len(set(tickers))


def test_exception_sleeve_missing_akg_macro_fields_are_neutral():
    rows = [row(f"C{i}", 100 - i) for i in range(10)] + [row("E", 25, hp_LLM_best="1")]
    result = select_high_conviction_top15_exception_sleeve(rows, {"enabled": True, "exception_slots": 1})
    assert [r["ticker"] for r in result["exception_rows"]] == ["E"]


def test_exception_sleeve_does_not_use_return_labels():
    rows = [row(f"C{i}", 100 - i) for i in range(10)] + [
        row("BADRET", 40, rm1_low_price_dislocation_momentum="1", return_90d_pct="999"),
        row("GOOD", 41, rm1_low_price_dislocation_momentum="1", return_90d_pct="-99"),
    ]
    result = select_high_conviction_top15_exception_sleeve(rows, {"enabled": True, "exception_slots": 1})
    assert result["exception_rows"][0]["ticker"] == "GOOD"


def test_exception_sleeve_applies_coverage_gate():
    rows = [row(f"C{i}", 100 - i) for i in range(10)] + [
        row("BAD", 80, rm1_low_price_dislocation_momentum="1", primary_theme="ai"),
        row("GOOD", 30, rm1_low_price_dislocation_momentum="1", primary_theme="energy"),
    ]
    coverage_rows = [
        *[{"ticker": f"C{i}", "status": "CACHED_READY"} for i in range(10)],
        {"ticker": "BAD", "status": "NEEDS_FETCH"},
        {"ticker": "GOOD", "status": "CACHED_READY"},
    ]
    result = select_high_conviction_top15_exception_sleeve(
        rows,
        {"enabled": True, "exception_slots": 1, "coverage_gating": True},
        coverage_rows,
    )
    assert [r["ticker"] for r in result["exception_rows"]] == ["GOOD"]


def test_daily_recommendation_labels_exceptions_as_starter_or_research(tmp_path):
    scores = tmp_path / "scores.csv"
    out = tmp_path / "out"
    rows = [row(f"C{i}", 100 - i) for i in range(10)] + [row(f"E{i}", 30 + i, rm1_low_price_dislocation_momentum="1", primary_theme=f"theme{i}") for i in range(5)]
    fieldnames = sorted({key for item in rows for key in item})
    with scores.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    result = select_top15_from_csv(scores, out, {"enabled": True, "selection_date": "2026-05-08"})
    text = (out / "high_conviction_top15_daily_recommendation.md").read_text(encoding="utf-8")
    assert "right-tail research / starter-underwriting candidates" in text
    assert "Do not equal-weight all 15 automatically" in text
    assert result["output_paths"]["csv"].endswith("high_conviction_top15.csv")


def test_daily_recommendation_uses_configured_queue_capacity(tmp_path):
    scores = tmp_path / "scores.csv"
    out = tmp_path / "out"
    rows = [row(f"C{i}", 100 - i) for i in range(2)] + [row("E", 30, rm1_low_price_dislocation_momentum="1", primary_theme="theme")]
    fieldnames = sorted({key for item in rows for key in item})
    with scores.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    select_top15_from_csv(scores, out, {"enabled": True, "core_n": 2, "exception_slots": 1, "selection_date": "2026-05-08"})

    text = (out / "high_conviction_top15_daily_recommendation.md").read_text(encoding="utf-8")
    assert "all 15" not in text
    assert "Do not equal-weight all 3 automatically" in text


def test_top15_rows_use_top15_operating_setting(tmp_path):
    scores = tmp_path / "scores.csv"
    out = tmp_path / "out"
    rows = [row(f"C{i}", 100 - i) for i in range(10)] + [row("E", 30, rm1_low_price_dislocation_momentum="1", primary_theme="ai")]
    fieldnames = sorted({key for item in rows for key in item})
    with scores.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    result = select_top15_from_csv(scores, out, {"enabled": True, "exception_slots": 1, "selection_date": "2026-05-08"})
    assert result["operating_recommendation"]["operating_setting"] == "high_conviction_top15_v3_exception_sleeve"
    assert {r["operating_setting"] for r in result["selected_rows"]} == {"high_conviction_top15_v3_exception_sleeve"}
    text = (out / "high_conviction_top15_daily_recommendation.md").read_text(encoding="utf-8")
    assert "Operating setting: `high_conviction_top15_v3_exception_sleeve`" in text
    assert "Exception sleeve selected 1 of 1 configured slots" in text
    assert "Exception 5" not in text
