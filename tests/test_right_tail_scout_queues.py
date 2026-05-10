import csv

from tradingagents.research.fundamental.src.selection.right_tail_queues import (
    classify_demote_severity,
    compute_right_tail_evidence_score,
    build_right_tail_queues,
    build_target_visibility_audit,
    rank_thin_signal_watchlist,
    select_right_tail_queues_from_csv,
    split_demote_review_priority,
)


def row(**extra):
    base = {"ticker": "TST", "entry_score_0_100": "30"}
    base.update(extra)
    return base


def clean_candidate_row(ticker="CAND", quarter="2025Q1", **extra):
    base = {
        "ticker": ticker,
        "quarter": quarter,
        "primary_theme": "AI optical supplier",
        "theme_role": "supplier",
        "market_repricing_score": "14",
        "theme_tailwind_score": "8",
        "filing_theme_growth_flag": "1",
        "repricing_momentum_priority": "1",
    }
    base.update(extra)
    return base


def high_score_soft_demote_row(**extra):
    base = clean_candidate_row(
        ticker="SOFT",
        post_llm_demote_flag="1",
        post_llm_demote_severity="soft",
        rm1_low_price_dislocation_momentum="1",
        rm_buy_review_flag="1",
        hp_LLM_best="1",
        theme_acceleration_research_visibility="1",
    )
    base.update(extra)
    return base


def high_score_unknown_demote_row(**extra):
    base = high_score_soft_demote_row(ticker="UNK", post_llm_demote_severity="unknown", post_llm_demote_overrideable="1")
    base.update(extra)
    return base


def high_score_hard_demote_row(**extra):
    base = high_score_soft_demote_row(ticker="BAD", post_llm_demote_severity="hard", post_llm_demote_reason_code="fraud_or_integrity", post_llm_demote_overrideable="1")
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
    assert classify_demote_severity({"post_llm_demote_flag": "1"}) == "unknown"


def test_demote_false_defaults_none():
    assert classify_demote_severity({"post_llm_demote_flag": "0"}) == "none"


def test_low_entry_theme_supplier_routes_to_scout_not_candidate():
    result = build_right_tail_queues([clean_candidate_row(ticker="ICHR", quarter="2026Q1", repricing_momentum_priority="")], top15_selected_keys=set())
    assert result["right_tail_scout_queue"][0]["ticker"] == "ICHR"
    assert result["top15_exception_candidate_queue"] == []


def test_repricing_momentum_flags_can_create_demote_review_candidate():
    rows = [{
        "ticker": "BE",
        "quarter": "2025Q3",
        "post_llm_demote_flag": "1",
        "post_llm_demote_severity": "unknown",
        "repricing_momentum_priority": "1",
    }]
    result = build_right_tail_queues(rows, top15_selected_keys=set())
    assert result["demote_review_queue"][0]["ticker"] == "BE"


def test_soft_demote_requires_overrideable_for_candidate_queue():
    candidate = high_score_soft_demote_row(post_llm_demote_overrideable="0")
    result = build_right_tail_queues([candidate], top15_selected_keys=set())
    assert result["top15_exception_candidate_queue"] == []
    assert result["right_tail_scout_queue"] or result["demote_review_queue"]

    candidate["post_llm_demote_overrideable"] = "1"
    result = build_right_tail_queues([candidate], top15_selected_keys=set())
    assert result["top15_exception_candidate_queue"][0]["ticker"] == candidate["ticker"]


def test_unknown_demote_never_enters_candidate_queue():
    result = build_right_tail_queues([high_score_unknown_demote_row()], top15_selected_keys=set())
    assert result["top15_exception_candidate_queue"] == []
    assert result["demote_review_queue"][0]["right_tail_queue_type"] == "demote_review"


def test_hard_demote_never_enters_candidate_queue():
    result = build_right_tail_queues([high_score_hard_demote_row()], top15_selected_keys=set())
    assert result["top15_exception_candidate_queue"] == []
    assert result["demote_review_queue"][0]["right_tail_queue_type"] == "blocked_hard_demote"


def test_already_selected_top15_name_is_suppressed_from_visibility_queues():
    candidate = clean_candidate_row(ticker="CRDO", quarter="2024Q3")
    result = build_right_tail_queues([candidate], top15_selected_keys={("CRDO", "2024Q3")})
    assert result["top15_exception_candidate_queue"] == []
    assert result["right_tail_scout_queue"] == []
    assert result["right_tail_evidence_score_diagnostics"][0]["right_tail_queue_type"] == "already_selected_top15"


def test_forbidden_columns_are_removed_before_scoring():
    candidate = {"ticker": "A", "rm_buy_review_flag": "1", "return_90d_pct": "999", "final_rank_score_0_100": "100", "winner_reason": "PIT note", "final_quality_score": "7"}
    result = build_right_tail_queues([candidate], top15_selected_keys=set())
    diag = result["right_tail_evidence_score_diagnostics"][0]
    input_columns = diag["right_tail_score_input_columns"].split(";")
    assert "return_90d_pct" not in input_columns
    assert "final_rank_score_0_100" not in input_columns
    assert "winner_reason" in input_columns
    assert "final_quality_score" in input_columns


def test_extreme_forward_looking_columns_do_not_change_queue_routing():
    base_rows = [
        clean_candidate_row(ticker="SCOUT", market_repricing_score="10", repricing_momentum_priority=""),
        high_score_soft_demote_row(post_llm_demote_overrideable="1"),
        {"ticker": "THIN", "quarter": "2026Q1", "rm_buy_review_flag": "1"},
    ]
    injected_rows = []
    for row_data in base_rows:
        item = dict(row_data)
        item.update({
            "return_999d_pct": "999999",
            "return_since_signal_extreme_pct": "999999",
            "future_return_pct": "999999",
            "winner_future_label": "1",
            "target_label": "BUY_NOW",
            "final_current_return_rank": "1",
            "monitoring_score_shadow": "100",
        })
        injected_rows.append(item)

    assert build_right_tail_queues(base_rows, top15_selected_keys=set()) == build_right_tail_queues(injected_rows, top15_selected_keys=set())


def test_split_demote_review_priority_bands_pm_view():
    rows = [
        {"ticker": "AKG", "right_tail_evidence_score": "-3", "right_tail_reason_codes": "akg_t5_rescan"},
        {"ticker": "TEN", "right_tail_evidence_score": "10", "right_tail_reason_codes": ""},
        {"ticker": "POS", "right_tail_evidence_score": "5", "right_tail_reason_codes": "rm_buy_review_flag"},
        {"ticker": "NEG", "right_tail_evidence_score": "-5", "right_tail_reason_codes": "hard_demote"},
    ]

    bands = split_demote_review_priority(rows)

    assert {r["ticker"] for r in bands["priority_1"]} == {"AKG", "TEN"}
    assert [r["ticker"] for r in bands["priority_2"]] == ["POS"]
    assert [r["ticker"] for r in bands["low_priority"]] == ["NEG"]


def test_rank_thin_signal_watchlist_caps_and_sorts_for_pm_consumption():
    rows = [
        {"ticker": "ZZZ", "right_tail_evidence_score": "20", "market_repricing_score": "9", "entry_qoq_pct": "3"},
        {"ticker": "AAA", "right_tail_evidence_score": "20", "market_repricing_score": "9", "entry_qoq_pct": "3"},
        {"ticker": "MID", "right_tail_evidence_score": "20", "market_repricing_score": "8", "entry_qoq_pct": "99"},
        {"ticker": "TOP", "right_tail_evidence_score": "30", "market_repricing_score": "1", "entry_qoq_pct": "1"},
        {"ticker": "QOQ", "right_tail_evidence_score": "20", "market_repricing_score": "9", "entry_qoq_pct": "8"},
    ]

    ranked = rank_thin_signal_watchlist(rows, limit=3)

    assert [r["ticker"] for r in ranked] == ["TOP", "QOQ", "AAA"]


def test_select_right_tail_queues_from_csv_writes_no_target_audit_by_default(tmp_path):
    scores = tmp_path / "scores.csv"
    out = tmp_path / "out"
    rows = [clean_candidate_row(ticker="ICHR", quarter="2026Q1", repricing_momentum_priority="")]
    with scores.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=sorted(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    result = select_right_tail_queues_from_csv(scores, out, selection_date="2026-05-09")

    assert (out / "right_tail_scout_queue.csv").exists()
    assert (out / "top15_exception_candidate_queue.csv").exists()
    assert (out / "demote_review_priority_1.csv").exists()
    assert (out / "demote_review_priority_2.csv").exists()
    assert (out / "demote_review_low_priority.csv").exists()
    assert (out / "thin_signal_watchlist_top100.csv").exists()
    assert not (out / "target_miss_rescue_audit.csv").exists()
    assert result["warnings"]


def test_target_events_csv_preserves_duplicate_tickers_across_quarters(tmp_path):
    target = tmp_path / "targets.csv"
    target.write_text("ticker,quarter\nAAOI,2023Q2\nAAOI,2024Q3\n", encoding="utf-8")
    from tradingagents.research.fundamental.src.selection.right_tail_queues import read_target_events_csv

    assert read_target_events_csv(target) == [("AAOI", "2023Q2"), ("AAOI", "2024Q3")]


def test_target_visibility_audit_splits_visibility_actionable_and_demote_review():
    diagnostics = [
        {"ticker": "HARD", "quarter": "2026Q1", "right_tail_queue_type": "blocked_hard_demote", "right_tail_reason_codes": "primary_theme"},
        {"ticker": "SOFT", "quarter": "2026Q1", "right_tail_queue_type": "demote_review", "right_tail_reason_codes": "primary_theme"},
        {"ticker": "EMPTY", "quarter": "2026Q1", "right_tail_queue_type": "demote_review", "right_tail_reason_codes": ""},
        {"ticker": "SCOUT", "quarter": "2026Q1", "right_tail_queue_type": "right_tail_scout", "right_tail_reason_codes": "primary_theme"},
    ]
    audit = {r["ticker"]: r for r in build_target_visibility_audit([], diagnostics, [("HARD", "2026Q1"), ("SOFT", "2026Q1"), ("EMPTY", "2026Q1"), ("SCOUT", "2026Q1")])}

    assert audit["HARD"]["target_visibility_routed"] == 1
    assert audit["HARD"]["target_actionable_research_routed"] == 0
    assert audit["HARD"]["target_demote_review_routed"] == 0
    assert audit["SOFT"]["target_actionable_research_routed"] == 1
    assert audit["SOFT"]["target_demote_review_routed"] == 1
    assert audit["EMPTY"]["target_visibility_routed"] == 1
    assert audit["EMPTY"]["target_actionable_research_routed"] == 0
    assert audit["SCOUT"]["target_scout_or_top15_routed"] == 1


def test_empty_queue_csv_uses_stable_headers(tmp_path):
    scores = tmp_path / "scores.csv"
    out = tmp_path / "out"
    scores.write_text("ticker,quarter\nEMPTY,2026Q1\n", encoding="utf-8")

    select_right_tail_queues_from_csv(scores, out)

    header = (out / "top15_exception_candidate_queue.csv").read_text(encoding="utf-8").splitlines()[0]
    assert "ticker" in header
    assert "right_tail_queue_type" in header


def test_rm_buy_review_market_repricing_override_routes_to_scout_below_threshold():
    row = {
        "ticker": "AXTI",
        "quarter": "2026Q1",
        "rm_buy_review_flag": "1",
        "market_repricing_score": "14",
    }
    result = build_right_tail_queues([row], top15_selected_keys=set())
    scout = result["right_tail_scout_queue"][0]
    assert scout["ticker"] == "AXTI"
    assert float(scout["right_tail_evidence_score"]) == 32.0
    assert "rm_buy_review_market_repricing_override" in scout["right_tail_reason_codes"]
