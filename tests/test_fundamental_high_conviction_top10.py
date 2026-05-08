import csv

from tradingagents.research.fundamental.src.selection import HighConvictionConfig, select_from_csv, select_high_conviction_top10


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


def test_selection_package_exports_public_api():
    assert HighConvictionConfig().top_n == 10
    assert callable(select_high_conviction_top10)
    assert callable(select_from_csv)


def test_string_confidence_mapping_is_explicit():
    rows = [row("HI", 80, "high"), row("MED", 79, "medium"), row("LOW", 90, "low")]

    result = select_high_conviction_top10(rows, {"top_n": 10, "min_score": 70, "min_confidence": 3})

    assert [r["ticker"] for r in result["selected_rows"]] == ["HI", "MED"]
    assert [r["confidence_numeric"] for r in result["selected_rows"]] == [4.0, 3.0]
    low = next(r for r in result["rejected_rows"] if r["ticker"] == "LOW")
    assert "CONFIDENCE_BELOW_THRESHOLD" in low["reason_codes"]


def test_hard_gate_blocks_even_with_override():
    result = select_high_conviction_top10(
        [row("BAD", score=95, hard_reject_reason="fraud", theme_acceleration_score="99")],
        {"top_n": 10, "min_score": 70, "min_confidence": 3},
    )

    assert result["selected_rows"] == []
    rejected = result["rejected_rows"][0]
    assert "HARD_REJECT_REASON_PRESENT" in rejected["reason_codes"]
    assert "OVERRIDE_THEME_ACCELERATION_SCORE" in rejected["override_reason_codes"]


def test_override_bypasses_min_score_only_when_hard_gates_pass():
    result = select_high_conviction_top10(
        [row("OK", score=65, theme_acceleration_rescan_flag="true")],
        {"top_n": 10, "min_score": 70, "min_confidence": 3},
    )

    assert [r["ticker"] for r in result["selected_rows"]] == ["OK"]
    assert "SCORE_BELOW_THRESHOLD" not in result["selected_rows"][0]["reason_codes"]


def test_generic_rescan_does_not_override_score_but_t5_rescan_does():
    result = select_high_conviction_top10(
        [row("GEN", 65, source="manual rescan requested"), row("T5", 64, thesis_tags="T5_RESCAN")],
        {"top_n": 10, "min_score": 70, "min_confidence": 3},
    )

    assert [r["ticker"] for r in result["selected_rows"]] == ["T5"]
    assert "OVERRIDE_T5_RESCAN" in result["selected_rows"][0]["override_reason_codes"]
    gen = next(r for r in result["rejected_rows"] if r["ticker"] == "GEN")
    assert "SCORE_BELOW_THRESHOLD" in gen["reason_codes"]
    assert gen["override_reason_codes"] == []


def test_override_does_not_boost_ranking_over_higher_composite_non_override():
    result = select_high_conviction_top10(
        [
            row("OVR", 69, 4, repricing_momentum_priority="true"),
            row("HIGH", 70, 4),
        ],
        {"top_n": 2, "min_score": 70, "min_confidence": 3},
    )

    assert [r["ticker"] for r in result["selected_rows"]] == ["HIGH", "OVR"]
    override = next(r for r in result["selected_rows"] if r["ticker"] == "OVR")
    assert "override_bonus" not in override["composite_contributions"]


def test_arbitrary_prefixed_fields_do_not_bypass_min_score():
    result = select_high_conviction_top10(
        [
            row("TIER", 65, tier_flag="true"),
            row("HP", 65, hp_random="true"),
            row("RM", 65, rm_fake="true"),
        ],
        {"top_n": 10, "min_score": 70, "min_confidence": 3},
    )

    assert result["selected_rows"] == []
    assert {r["ticker"] for r in result["rejected_rows"]} == {"TIER", "HP", "RM"}
    assert all("SCORE_BELOW_THRESHOLD" in r["reason_codes"] for r in result["rejected_rows"])
    assert all(r["override_reason_codes"] == [] for r in result["rejected_rows"])


def test_output_includes_stable_aliases_summary_and_config():
    result = select_high_conviction_top10([row("A", 80)], {"top_n": 10})

    assert result["selected"] == result["selected_rows"]
    assert result["rejected"] == result["rejected_rows"]
    assert "summary" in result
    assert result["config"] == result["config_snapshot"]


def test_missing_confidence_fails_when_required():
    item = row("NOCONF", score=85)
    item.pop("confidence")

    result = select_high_conviction_top10([item], {"require_confidence": True})

    assert result["selected_rows"] == []
    assert "MISSING_CONFIDENCE" in result["rejected_rows"][0]["reason_codes"]


def test_fewer_than_10_returns_shortfall_no_force_fill():
    rows = [row("A", 80), row("B", 69)]

    result = select_high_conviction_top10(rows, {"top_n": 10, "min_score": 70})

    assert [r["ticker"] for r in result["selected_rows"]] == ["A"]
    assert result["summary"]["selected_count"] == 1
    assert any(w.startswith("SHORTFALL_SELECTED_1_OF_10") for w in result["summary"]["warnings"])
    assert "SCORE_BELOW_THRESHOLD" in result["rejected_rows"][0]["reason_codes"]


def test_deterministic_rank_by_composite_score_confidence_ticker():
    rows = [
        row("ZZZ", 80, 4, lane="core"),
        row("AAA", 80, 4, lane="core"),
        row("MOM", 79, 5, lane="momentum"),
        row("OPP", 78, 5, lane="opportunistic"),
        row("TOP", 90, 3, lane="core"),
    ]

    result = select_high_conviction_top10(rows, {"top_n": 4, "core_target": 1, "momentum_target": 1, "opportunistic_target": 1})

    assert [r["ticker"] for r in result["selected_rows"]] == ["TOP", "MOM", "AAA", "ZZZ"]
    assert "SOFT_BALANCE_ANNOTATION_ONLY_RANKING_DOMINATES" in result["summary"]["warnings"]
    assert [r["selection_rank"] for r in result["selected_rows"]] == [1, 2, 3, 4]


def test_soft_balance_never_forces_lower_composite_over_higher_composite():
    rows = [row(f"C{i}", 90 - i, 4, lane="core") for i in range(5)] + [row("MOMLOW", 70, 3, lane="momentum")]

    result = select_high_conviction_top10(rows, {"top_n": 3, "core_target": 1, "momentum_target": 2})

    assert [r["ticker"] for r in result["selected_rows"]] == ["C0", "C1", "C2"]
    assert "MOMLOW" not in [r["ticker"] for r in result["selected_rows"]]


def test_coverage_manifest_blocks_needs_fetch():
    result = select_high_conviction_top10(
        [row("A", 90), row("B", 90)],
        {"coverage_gating": True},
        coverage_rows=[
            {"ticker": "A", "status": "NEEDS_FETCH"},
            {"ticker": "B", "status": "CACHED_READY"},
        ],
    )

    assert [r["ticker"] for r in result["selected_rows"]] == ["B"]
    a = next(r for r in result["rejected_rows"] if r["ticker"] == "A")
    assert "SEC_COVERAGE_NEEDS_FETCH" in a["reason_codes"]
    assert "SEC_COVERAGE_ZERO_CACHED_READY" in a["reason_codes"]


def test_coverage_gating_blocks_when_no_coverage_rows():
    result = select_high_conviction_top10(
        [row("A", 90), row("B", 88)],
        {"coverage_gating": True},
        coverage_rows=[],
    )

    assert result["selected_rows"] == []
    assert {r["ticker"] for r in result["rejected_rows"]} == {"A", "B"}
    assert all("SEC_COVERAGE_ZERO_CACHED_READY" in r["reason_codes"] for r in result["rejected_rows"])


def test_invalid_present_cik_values_are_rejected_but_integerish_float_cik_passes():
    rows = [
        row("FLOAT", 91, cik="123456.0"),
        row("NAN", 90, cik="nan"),
        row("NONE", 90, cik=None),
        row("NULL", 90, cik="null"),
        row("JUNK", 90, cik="abc123"),
        row("STATUS", 90, cik="123456", cik_status="no_match"),
        row("OK", 90, cik="0001234567", cik_status="resolved"),
    ]

    result = select_high_conviction_top10(rows, {"top_n": 10})

    assert [r["ticker"] for r in result["selected_rows"]] == ["FLOAT", "OK"]
    rejected = {r["ticker"]: r for r in result["rejected_rows"]}
    for ticker in ["NAN", "NONE", "NULL", "JUNK", "STATUS"]:
        assert "BAD_CIK" in rejected[ticker]["reason_codes"]


def test_top_n_must_be_positive():
    for bad in [0, -1]:
        try:
            select_high_conviction_top10([row("A", 90)], {"top_n": bad})
        except ValueError as exc:
            assert "top_n must be > 0" in str(exc)
        else:
            raise AssertionError(f"top_n={bad} should raise ValueError")


def test_not_blocked_document_status_does_not_reject():
    result = select_high_conviction_top10(
        [row("A", 90, document_status="not_blocked")],
        {"top_n": 10},
    )

    assert [r["ticker"] for r in result["selected_rows"]] == ["A"]


def test_select_from_csv_writes_csv_and_json(tmp_path):
    scores = tmp_path / "scores.csv"
    with scores.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(row("A").keys()))
        writer.writeheader()
        writer.writerow(row("A", 80, "high"))

    result = select_from_csv(scores, tmp_path / "out", {"selection_date": "2026-05-08"})

    assert result["summary"]["selected_count"] == 1
    assert result["date"] == "2026-05-08"
    assert (tmp_path / "out" / "high_conviction_top10.csv").exists()
    assert (tmp_path / "out" / "high_conviction_top10.json").exists()
