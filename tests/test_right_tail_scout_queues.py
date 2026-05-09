from tradingagents.research.fundamental.src.selection.right_tail_queues import (
    classify_demote_severity,
    compute_right_tail_evidence_score,
)


def row(**extra):
    base = {"ticker": "TST", "entry_score_0_100": "30"}
    base.update(extra)
    return base


def test_right_tail_evidence_score_formula_includes_rm_theme_hp_supplier_and_risk():
    score, parts = compute_right_tail_evidence_score(row(
        rm1_low_price_dislocation_momentum="1",
        rm_buy_review_flag="1",
        repricing_momentum_priority="1",
        repricing_momentum_extension="1",
        market_repricing_score="14",
        hp_LLM_best="1",
        primary_theme="AI optical supplier",
        theme_role="supplier",
        theme_tailwind_score="8",
        filing_theme_growth_flag="1",
        filing_theme_guidance_flag="1",
        risk_penalty_score="10",
    ))

    assert parts["single_rm_signal_bucket"] == 20
    assert parts["rm_buy_review_flag"] == 12
    assert parts["repricing_momentum_priority"] == 10
    assert parts["repricing_momentum_extension"] == 6
    assert parts["market_repricing_score_gte_10"] == 10
    assert parts["market_repricing_score_gte_14"] == 10
    assert parts["hp_signal_count_gt_0"] == 10
    assert parts["hp_LLM_best"] == 12
    assert parts["primary_theme"] == 10
    assert parts["theme_tailwind_score"] == 8
    assert parts["filing_theme_growth_flag"] == 8
    assert parts["filing_theme_guidance_flag"] == 8
    assert parts["active_theme_supplier_or_bottleneck_role"] == 10
    assert parts["risk_penalty_score_gte_10"] == -10
    assert score == sum(parts.values())


def test_ichr_style_supplier_row_clears_scout_threshold():
    score, _ = compute_right_tail_evidence_score(row(
        ticker="ICHR",
        entry_score_0_100="3",
        primary_theme="semicap supplier",
        theme_role="supplier",
        market_repricing_score="14",
        theme_tailwind_score="8",
        filing_theme_growth_flag="1",
    ))
    assert score == 56
    assert score >= 50


def test_demote_flag_without_new_fields_defaults_unknown():
    severity = classify_demote_severity({"post_llm_demote_flag": "1"})
    assert severity == "unknown"


def test_demote_false_defaults_none():
    severity = classify_demote_severity({"post_llm_demote_flag": "0"})
    assert severity == "none"
