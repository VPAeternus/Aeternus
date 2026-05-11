import csv
import json

from tradingagents.research.fundamental.src.selection.high_conviction_top10 import (
    CORE_DETERIORATION_STRICT_ACTION,
    RightTailExceptionConfig,
    _is_right_tail_exception_candidate,
    _normalize_core_deterioration_refill_config,
    _rank_high_conviction_core_pool,
    _right_tail_exception_score,
    build_core_deterioration_review_rows,
    rank_high_conviction_core_pool,
    select_high_conviction_top10,
    select_high_conviction_top15_exception_sleeve,
    select_top15_core_deterioration_refill_shadow_from_csv,
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


def test_normalize_core_deterioration_refill_requires_nested_config():
    cfg = _normalize_core_deterioration_refill_config({"enabled": True})
    assert cfg.enabled is False


def test_normalize_core_deterioration_refill_parses_string_false_booleans():
    cfg = _normalize_core_deterioration_refill_config(
        {"core_deterioration_refill": {"enabled": "false", "block_deterioration_from_exceptions": "false"}}
    )
    assert cfg.enabled is False
    assert cfg.block_deterioration_from_exceptions is False


def test_normalize_core_deterioration_refill_parses_string_true_and_mode():
    cfg = _normalize_core_deterioration_refill_config({"core_deterioration_refill": {"enabled": "true", "mode": "downgrade"}})
    assert cfg.enabled is True
    assert cfg.mode == "downgrade"


def test_top15_preserves_top10_when_exception_disabled():
    rows = [row(f"C{i}", 100 - i) for i in range(12)]
    top10 = select_high_conviction_top10(rows, {"top_n": 10})["selected_rows"]
    top15 = select_high_conviction_top15_exception_sleeve(rows, RightTailExceptionConfig(enabled=False))["selected_rows"]
    assert [r["ticker"] for r in top15] == [r["ticker"] for r in top10]
    assert all(r["selected_sleeve"] == "core" for r in top15)


def test_rank_high_conviction_core_pool_matches_top10_contract():
    rows = [row(f"C{i}", 100 - i) for i in range(12)]
    pool = _rank_high_conviction_core_pool(rows, {"top_n": 10}, None)
    public_pool = rank_high_conviction_core_pool(rows, {"top_n": 10}, None)
    top10 = select_high_conviction_top10(rows, {"top_n": 10})

    assert [r["ticker"] for r in pool["ranked_rows"][:10]] == [r["ticker"] for r in top10["selected_rows"]]
    assert [r["core_candidate_rank"] for r in pool["ranked_rows"][:3]] == [1, 2, 3]
    assert [r["core_candidate_rank"] for r in public_pool["ranked_rows"][:3]] == [1, 2, 3]
    assert top10["summary"]["selected_count"] == 10
    assert all(r["selected"] is True for r in top10["selected_rows"])
    assert all("core_candidate_rank" not in r for r in top10["selected_rows"])


def test_public_core_pool_row_mutation_does_not_affect_selector():
    rows = [row(f"C{i}", 100 - i) for i in range(12)]
    expected_ticker = "C0"

    public_pool = rank_high_conviction_core_pool(rows, {"top_n": 10})
    public_pool["ranked_rows"][0]["ticker"] = "MUTATED"

    top10 = select_high_conviction_top10(rows, {"top_n": 10})
    public_pool_again = rank_high_conviction_core_pool(rows, {"top_n": 10})

    assert top10["selected_rows"][0]["ticker"] == expected_ticker
    assert public_pool_again["ranked_rows"][0]["ticker"] == expected_ticker


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


def test_top15_official_path_ignores_absent_or_disabled_refill_config():
    rows = [row(f"C{i}", 100 - i) for i in range(10)] + [
        row(
            "DETERIORATING",
            50,
            rm1_low_price_dislocation_momentum="1",
            score_change="-2",
            negative_revision_risk="2",
            pre_llm_fundamental_bucket="weak",
            primary_theme="",
        )
    ]

    absent_refill = select_high_conviction_top15_exception_sleeve(rows, {"enabled": True, "exception_slots": 1})
    disabled_refill = select_high_conviction_top15_exception_sleeve(
        rows,
        {"enabled": True, "exception_slots": 1, "core_deterioration_refill": {"enabled": False}},
    )

    assert [r["ticker"] for r in absent_refill["selected_rows"]] == [r["ticker"] for r in disabled_refill["selected_rows"]]


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


def test_core_deterioration_review_queue_flags_strict_core_rows():
    rows = [row(f"C{i}", 100 - i) for i in range(10)]
    rows[6].update(
        score_change="-2",
        negative_revision_risk="2",
        pre_llm_fundamental_bucket="weak",
        primary_theme="",
        rm1_low_price_dislocation_momentum="RM1 - Low-price dislocation momentum",
        rm2_weak_acceleration="RM2 - Weak-bucket acceleration",
        rm4_persistent_repricing_wave="RM4 - Persistent repricing wave",
    )

    result = select_high_conviction_top15_exception_sleeve(rows, {"enabled": False})
    review_rows = build_core_deterioration_review_rows(result["selected_rows"])

    assert len(review_rows) == 1
    flagged = review_rows[0]
    assert flagged["ticker"] == "C6"
    assert flagged["core_deterioration_review_flag"] == 1
    assert flagged["core_deterioration_downgrade_flag"] == 1
    assert flagged["core_deterioration_strict_override_required"] == 1
    assert flagged["core_deterioration_recommended_action"] == CORE_DETERIORATION_STRICT_ACTION


def test_core_deterioration_uses_zero_demoted_repricing_without_truthy_fallback():
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import core_deterioration_flags

    candidate = row(
        "ZERO",
        70,
        selected_sleeve="core",
        selected_sleeve_rank="4",
        selection_rank="4",
        score_change="0",
        negative_revision_risk="0",
        pre_llm_fundamental_bucket="weak",
        primary_theme="",
        hp_LLM_best="1",
        market_repricing_score="10",
        demoted_market_repricing_score=0,
    )

    flags = core_deterioration_flags(candidate)

    assert flags["weak_no_theme_repricing_stack_flag"] == 0
    assert flags["core_deterioration_review_flag"] == 0


def test_core_deterioration_flags_count_descriptive_rm_hp_labels():
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import core_deterioration_flags

    candidate = row(
        "STACK",
        82,
        selected_sleeve="core",
        selected_sleeve_rank="4",
        selection_rank="4",
        score_change="-2",
        negative_revision_risk="2",
        pre_llm_fundamental_bucket="weak",
        primary_theme="",
        rm1_low_price_dislocation_momentum="RM1 - Low-price dislocation momentum",
        rm2_weak_acceleration="RM2 - Weak-bucket acceleration",
        rm4_persistent_repricing_wave="RM4 - Persistent repricing wave",
    )

    flags = core_deterioration_flags(candidate)

    assert flags["core_deterioration_rm_count"] == 3
    assert flags["core_deterioration_hp_count"] == 0
    assert flags["high_score_deterioration_flag"] == 1
    assert flags["weak_no_theme_repricing_stack_flag"] == 1
    assert flags["core_deterioration_review_flag"] == 1
    assert flags["core_deterioration_downgrade_flag"] == 1
    assert flags["core_deterioration_strict_override_required"] == 1


def test_rank_7_8_alone_does_not_trigger_core_deterioration_flags():
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import core_deterioration_flags

    clean = row(
        "CLEAN",
        90,
        selected_sleeve="core",
        selected_sleeve_rank="7",
        selection_rank="7",
        score_change="1",
        negative_revision_risk="0",
        pre_llm_fundamental_bucket="strong",
        primary_theme="AI infrastructure",
    )

    flags = core_deterioration_flags(clean)

    assert flags["core_deterioration_rank_context_flag"] == 1
    assert "rank_7_8_context_only" in flags["core_deterioration_reason_codes"].split(";")
    assert flags["core_deterioration_review_flag"] == 0
    assert flags["core_deterioration_downgrade_flag"] == 0
    assert flags["core_deterioration_strict_override_required"] == 0


def test_core_deterioration_rank_zero_does_not_truthy_fallback_to_sleeve_rank():
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import core_deterioration_flags

    clean = row(
        "ZERO_RANK",
        90,
        selected_sleeve="core",
        selection_rank=0,
        selected_sleeve_rank=7,
        score_change="1",
        negative_revision_risk="0",
        pre_llm_fundamental_bucket="strong",
        primary_theme="AI infrastructure",
    )

    flags = core_deterioration_flags(clean)

    assert flags["core_deterioration_rank_context_flag"] == 0
    assert flags["core_deterioration_review_flag"] == 0
    assert flags["core_deterioration_downgrade_flag"] == 0
    assert flags["core_deterioration_strict_override_required"] == 0


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
    assert "Core deterioration review gate" in text
    assert result["output_paths"]["csv"].endswith("high_conviction_top15.csv")
    assert result["output_paths"]["core_deterioration_review_queue"].endswith("core_deterioration_review_queue.csv")


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


def test_should_refill_demote_core_row_uses_bad_feature_combos_not_rank():
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import should_refill_demote_core_row

    strict_combo = row(
        "STRICT",
        85,
        selected_sleeve="core",
        selection_rank="4",
        selected_sleeve_rank="4",
        score_change="-2",
        negative_revision_risk="2",
        pre_llm_fundamental_bucket="weak",
        primary_theme="",
        rm1_low_price_dislocation_momentum="RM1 - Low-price dislocation momentum",
        rm2_weak_acceleration="RM2 - Weak-bucket acceleration",
        rm4_persistent_repricing_wave="RM4 - Persistent repricing wave",
    )
    rank_only = row(
        "RANK7",
        90,
        selected_sleeve="core",
        selection_rank="7",
        selected_sleeve_rank="7",
        score_change="1",
        negative_revision_risk="0",
        pre_llm_fundamental_bucket="strong",
        primary_theme="AI infrastructure",
    )

    assert should_refill_demote_core_row(strict_combo, "strict") is True
    assert should_refill_demote_core_row(strict_combo, "downgrade") is True
    assert should_refill_demote_core_row(rank_only, "strict") is False
    assert should_refill_demote_core_row(rank_only, "downgrade") is False


def test_should_refill_demote_core_row_allows_downgrade_without_strict_stack():
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import should_refill_demote_core_row

    high_score_blank_weak = row(
        "DOWN",
        85,
        selected_sleeve="core",
        selection_rank="3",
        selected_sleeve_rank="3",
        score_change="-2",
        negative_revision_risk="2",
        pre_llm_fundamental_bucket="weak",
        primary_theme="",
    )

    assert should_refill_demote_core_row(high_score_blank_weak, "strict") is False
    assert should_refill_demote_core_row(high_score_blank_weak, "downgrade") is True


def test_exception_sleeve_blocks_explicit_deterioration_tickers():
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import RightTailExceptionConfig, _select_exception_sleeve

    core_rows = [row(f"C{i}", 100 - i) for i in range(10)]
    all_rows = core_rows + [
        row("BAD", 80, rm1_low_price_dislocation_momentum="1", primary_theme="AI"),
        row("GOOD", 50, rm1_low_price_dislocation_momentum="1", primary_theme="energy"),
    ]

    exceptions, _ = _select_exception_sleeve(
        core_rows,
        all_rows,
        RightTailExceptionConfig(enabled=True, exception_slots=1),
        blocked_tickers={" BAD ", ""},
    )

    assert [r["ticker"] for r in exceptions] == ["GOOD"]


def test_top15_refill_shadow_outputs_full_top15_with_replacement_and_exception():
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import select_high_conviction_top15_core_deterioration_refill_shadow

    rows = [row(f"C{i}", 100 - i) for i in range(9)]
    rows.insert(5, row(
        "BAD", 95,
        score_change="-2", negative_revision_risk="2", pre_llm_fundamental_bucket="weak", primary_theme="",
        rm1_low_price_dislocation_momentum="RM1 - Low-price dislocation momentum",
        rm2_weak_acceleration="RM2 - Weak-bucket acceleration",
        rm4_persistent_repricing_wave="RM4 - Persistent repricing wave",
    ))
    rows += [row("NEXT", 89)]
    rows += [row(f"GOOD{i}", 50 + i, rm1_low_price_dislocation_momentum="1", primary_theme=f"theme{i}") for i in range(5)]

    result = select_high_conviction_top15_core_deterioration_refill_shadow(
        rows,
        {"enabled": True, "exception_slots": 5, "core_deterioration_refill": {"enabled": True, "mode": "strict"}},
    )

    selected_tickers = [r["ticker"] for r in result["selected_rows"]]
    core_tickers = [r["ticker"] for r in result["core_rows"]]
    exception_tickers = [r["ticker"] for r in result["exception_rows"]]

    assert "BAD" not in selected_tickers
    assert "NEXT" in core_tickers
    assert set(exception_tickers) == {f"GOOD{i}" for i in range(5)}
    assert result["summary"]["core_count"] == 10
    assert result["summary"]["exception_count"] == 5
    assert result["summary"]["selected_count"] == 15
    assert result["core_deterioration_refill_rows"][0]["demoted_ticker"] == "BAD"
    assert result["core_deterioration_refill_rows"][0]["replacement_ticker"] == "NEXT"
    assert result["core_deterioration_refill_summary"]["demoted_count"] == 1
    assert result["core_deterioration_refill_summary"]["replacement_count"] >= 1


def test_top15_refill_shadow_replacement_uses_ex_ante_rank_not_return_labels():
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import select_high_conviction_top15_core_deterioration_refill_shadow

    rows = [row(f"C{i}", 100 - i) for i in range(9)]
    rows.insert(5, row(
        "BAD", 95, return_90d_pct="-40",
        score_change="-2", negative_revision_risk="2", pre_llm_fundamental_bucket="weak", primary_theme="",
        rm1_low_price_dislocation_momentum="RM1 - Low-price dislocation momentum",
        rm2_weak_acceleration="RM2 - Weak-bucket acceleration",
        rm4_persistent_repricing_wave="RM4 - Persistent repricing wave",
    ))
    rows += [row("NEXT", 89, return_90d_pct="100"), row("LOWER", 70, return_90d_pct="300")]

    result = select_high_conviction_top15_core_deterioration_refill_shadow(
        rows,
        {"enabled": True, "exception_slots": 0, "core_deterioration_refill": {"enabled": True, "mode": "strict"}},
    )

    diagnostic = result["core_deterioration_refill_rows"][0]
    assert diagnostic["replacement_ticker"] == "NEXT"
    assert "demoted_return_90d_pct" not in diagnostic
    assert "replacement_return_90d_pct" not in diagnostic
    assert "replacement_delta_90d_pct" not in diagnostic
    assert "LOWER" not in [r["ticker"] for r in result["selected_rows"]]


def test_top15_refill_shadow_writer_omits_outcome_headers(tmp_path):
    input_csv = tmp_path / "scores.csv"
    output_dir = tmp_path / "out"
    rows = [row(f"C{i}", 100 - i, return_90d_pct="10") for i in range(9)]
    rows.insert(5, row(
        "BAD", 95, return_90d_pct="-40", current_return_pct="-5", final_rank="99", winner_label="no", target_label="miss", replacement_delta_90d_pct="-140",
        score_change="-2", negative_revision_risk="2", pre_llm_fundamental_bucket="weak", primary_theme="",
        rm1_low_price_dislocation_momentum="RM1 - Low-price dislocation momentum",
        rm2_weak_acceleration="RM2 - Weak-bucket acceleration",
        rm4_persistent_repricing_wave="RM4 - Persistent repricing wave",
    ))
    rows.append(row("NEXT", 89, return_90d_pct="100", current_return_pct="3", final_rank="1", winner_label="yes", target_label="hit", replacement_delta_90d_pct="140"))
    rows.append(row("REJECT", 60, return_90d_pct="200", current_return_pct="4", final_rank="2", winner_label="yes", loser_label="no", target_label="hit", replacement_delta_90d_pct="90"))

    fieldnames = sorted({key for item in rows for key in item})
    with input_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    select_top15_core_deterioration_refill_shadow_from_csv(
        input_csv,
        output_dir,
        config={"enabled": True, "exception_slots": 0, "core_deterioration_refill": {"enabled": True, "mode": "strict"}},
    )

    selected_csv = output_dir / "high_conviction_top15_core_deterioration_refill_shadow.csv"
    with selected_csv.open(newline="", encoding="utf-8") as handle:
        selected_header = [column.lower() for column in next(csv.reader(handle))]
    assert all("return" not in column for column in selected_header)
    assert all("delta" not in column for column in selected_header)
    assert all("winner" not in column for column in selected_header)
    assert all("loser" not in column for column in selected_header)
    assert all("current_return" not in column for column in selected_header)
    assert all("final_rank" not in column for column in selected_header)

    json_artifact = json.loads((output_dir / "high_conviction_top15_core_deterioration_refill_shadow.json").read_text(encoding="utf-8"))
    forbidden_fragments = ("return", "delta", "winner", "loser", "current_return", "final_rank", "target_label")
    for array_key in ("selected_rows", "selected", "core_rows", "exception_rows", "rejected_rows", "rejected"):
        for artifact_row in json_artifact.get(array_key, []):
            assert all(not any(fragment in key.lower() for fragment in forbidden_fragments) for key in artifact_row)

    replacements_csv = output_dir / "core_deterioration_refill_shadow_replacements.csv"
    with replacements_csv.open(newline="", encoding="utf-8") as handle:
        replacement_header = [column.lower() for column in next(csv.reader(handle))]
    assert all("return" not in column for column in replacement_header)
    assert all("delta" not in column for column in replacement_header)


def test_top15_refill_shadow_pairs_multiple_demotions_with_replacements_in_rank_order():
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import select_high_conviction_top15_core_deterioration_refill_shadow

    rows = [row(f"C{i}", 100 - i) for i in range(8)]
    bad_kwargs = {
        "score_change": "-2",
        "negative_revision_risk": "2",
        "pre_llm_fundamental_bucket": "weak",
        "primary_theme": "",
        "rm1_low_price_dislocation_momentum": "RM1 - Low-price dislocation momentum",
        "rm2_weak_acceleration": "RM2 - Weak-bucket acceleration",
        "rm4_persistent_repricing_wave": "RM4 - Persistent repricing wave",
    }
    rows.insert(2, row("BAD1", 99, **bad_kwargs))
    rows.insert(6, row("BAD2", 98, **bad_kwargs))
    rows += [row("NEXT1", 89), row("NEXT2", 88), row("LOWER", 70)]

    result = select_high_conviction_top15_core_deterioration_refill_shadow(
        rows,
        {"enabled": True, "exception_slots": 0, "core_deterioration_refill": {"enabled": True, "mode": "strict"}},
    )

    diagnostics = result["core_deterioration_refill_rows"]
    assert len(diagnostics) == 2
    assert [(row["demoted_ticker"], row["replacement_ticker"]) for row in diagnostics] == [("BAD1", "NEXT1"), ("BAD2", "NEXT2")]


def test_top15_refill_shadow_blocks_below_cutoff_deterioration_from_exceptions():
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import select_high_conviction_top15_core_deterioration_refill_shadow

    rows = [row(f"C{i}", 100 - i) for i in range(10)]
    rows += [
        row("BADX", 85, score_change="-2", negative_revision_risk="2", pre_llm_fundamental_bucket="weak", primary_theme="", rm1_low_price_dislocation_momentum="RM1 - Low-price dislocation momentum", rm2_weak_acceleration="RM2 - Weak-bucket acceleration", rm4_persistent_repricing_wave="RM4 - Persistent repricing wave"),
        row("GOODX", 50, rm1_low_price_dislocation_momentum="1", primary_theme="AI"),
    ]
    result = select_high_conviction_top15_core_deterioration_refill_shadow(rows, {"enabled": True, "exception_slots": 1, "core_deterioration_refill": {"enabled": True, "mode": "strict"}})
    assert "BADX" not in [r["ticker"] for r in result["selected_rows"]]
    assert [r["ticker"] for r in result["exception_rows"]] == ["GOODX"]


def test_top15_refill_shadow_blocks_core_ineligible_deterioration_from_exceptions():
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import select_high_conviction_top15_core_deterioration_refill_shadow

    rows = [row(f"C{i}", 100 - i) for i in range(10)]
    rows += [
        row("BADX", 85, 1, score_change="-2", negative_revision_risk="2", pre_llm_fundamental_bucket="weak", primary_theme="", rm1_low_price_dislocation_momentum="RM1 - Low-price dislocation momentum", rm2_weak_acceleration="RM2 - Weak-bucket acceleration", rm4_persistent_repricing_wave="RM4 - Persistent repricing wave"),
        row("GOODX", 50, rm1_low_price_dislocation_momentum="1", primary_theme="AI"),
    ]
    result = select_high_conviction_top15_core_deterioration_refill_shadow(rows, {"enabled": True, "exception_slots": 1, "core_deterioration_refill": {"enabled": True, "mode": "strict"}})
    assert "BADX" not in [r["ticker"] for r in result["selected_rows"]]
    assert [r["ticker"] for r in result["exception_rows"]] == ["GOODX"]


def test_top15_refill_shadow_exception_sleeve_respects_coverage_gate():
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import select_high_conviction_top15_core_deterioration_refill_shadow

    rows = [row(f"C{i}", 100 - i) for i in range(10)] + [
        row("BAD", 80, rm1_low_price_dislocation_momentum="1", primary_theme="AI"),
        row("GOOD", 50, rm1_low_price_dislocation_momentum="1", primary_theme="energy"),
    ]
    coverage_rows = [*[{"ticker": f"C{i}", "status": "CACHED_READY"} for i in range(10)], {"ticker": "BAD", "status": "NEEDS_FETCH"}, {"ticker": "GOOD", "status": "CACHED_READY"}]
    result = select_high_conviction_top15_core_deterioration_refill_shadow(rows, {"enabled": True, "exception_slots": 1, "coverage_gating": True, "core_deterioration_refill": {"enabled": True, "mode": "strict"}}, coverage_rows)
    assert [r["ticker"] for r in result["exception_rows"]] == ["GOOD"]
