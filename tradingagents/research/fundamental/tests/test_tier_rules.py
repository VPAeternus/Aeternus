from src.features.post_llm_subtiers import add_post_llm_subtiers
from src.features.tiers import assign_subtiers, assign_tiers
from src.features.hp_subtiers import add_hp_subtiers


def test_tier_rules_match_live_framework():
    row = {
        "pre_llm_fundamental_bucket": "mixed",
        "pre_llm_fundamental_score": "0",
        "entry_open": "4.99",
        "revenue_bucket": "$2B-$10B",
    }

    tiers = assign_tiers(row)

    assert tiers["tier_0_bucket"]
    assert tiers["tier_1_bucket"]
    assert tiers["tier_2_bucket"]
    assert tiers["tier_3_bucket"]
    assert tiers["tier_4_bucket"]


def test_not_scored_never_enters_tiers():
    row = {
        "pre_llm_fundamental_bucket": "not_scored",
        "pre_llm_fundamental_score": "0",
        "entry_open": "4.99",
        "revenue_bucket": "$100M-$500M",
    }

    assert not any(assign_tiers(row).values())


def test_hp0_high_price_broad_tracks_high_price_names_without_buyable_tier():
    row = {
        "pre_llm_fundamental_bucket": "strong",
        "pre_llm_fundamental_score": "8",
        "entry_open": "41.85",
        "revenue_bucket": ">$10B",
    }

    tiers = assign_tiers(row)

    assert tiers["hp0_high_price_broad"] == "HP0 - High-price broad watchlist"
    assert tiers["tier_0_bucket"] == ""
    assert tiers["tier_1_bucket"] == ""


def test_hp1_quality_pullback_tracks_high_price_quality_pullbacks():
    row = {
        "pre_llm_fundamental_bucket": "strong",
        "pre_llm_fundamental_score": "8",
        "entry_open": "30",
        "entry_qoq_pct": "-25",
        "revenue_bucket": ">$10B",
    }

    tiers = assign_tiers(row)

    assert tiers["hp1_quality_pullback"] == "HP1 - Quality pullback re-rater"
    assert tiers["hp0_high_price_broad"]
    assert tiers["tier_0_bucket"] == ""


def test_hp1_quality_pullback_requires_quality_and_twenty_pct_pullback():
    weak_row = {
        "pre_llm_fundamental_bucket": "mixed",
        "pre_llm_fundamental_score": "0",
        "entry_open": "30",
        "entry_qoq_pct": "-25",
        "revenue_bucket": ">$10B",
    }
    shallow_row = {
        "pre_llm_fundamental_bucket": "good",
        "pre_llm_fundamental_score": "4",
        "entry_open": "30",
        "entry_qoq_pct": "-19.9",
        "revenue_bucket": ">$10B",
    }

    assert assign_tiers(weak_row)["hp1_quality_pullback"] == ""
    assert assign_tiers(shallow_row)["hp1_quality_pullback"] == ""


def test_hp2_dislocation_momentum_tracks_high_price_weak_reraters():
    row = {
        "pre_llm_fundamental_bucket": "mixed",
        "pre_llm_fundamental_score": "0",
        "entry_open": "35",
        "entry_qoq_pct": "20",
        "revenue_bucket": ">$10B",
    }

    tiers = assign_tiers(row)

    assert tiers["hp2_dislocation_momentum_priority"] == "HP2 - Dislocation momentum re-rater"
    assert tiers["hp2_dislocation_momentum_watch"] == ""
    assert tiers["hp0_high_price_broad"]
    assert tiers["tier_0_bucket"] == ""


def test_hp2_dislocation_momentum_requires_dislocation_and_positive_momentum():
    strong_row = {
        "pre_llm_fundamental_bucket": "strong",
        "pre_llm_fundamental_score": "8",
        "entry_open": "35",
        "entry_qoq_pct": "20",
        "revenue_bucket": ">$10B",
    }
    flat_row = {
        "pre_llm_fundamental_bucket": "mixed",
        "pre_llm_fundamental_score": "0",
        "entry_open": "35",
        "entry_qoq_pct": "14.9",
        "revenue_bucket": ">$10B",
    }

    assert assign_tiers(strong_row)["hp2_dislocation_momentum_priority"] == ""
    assert assign_tiers(flat_row)["hp2_dislocation_momentum_priority"] == ""


def test_hp2_dislocation_momentum_watch_tracks_15_to_20_pct_band_only():
    watch_row = {
        "pre_llm_fundamental_bucket": "weak",
        "pre_llm_fundamental_score": "-4",
        "entry_open": "35",
        "entry_qoq_pct": "18.5",
        "revenue_bucket": "$500M-$1B",
    }
    priority_row = {
        "pre_llm_fundamental_bucket": "weak",
        "pre_llm_fundamental_score": "-4",
        "entry_open": "35",
        "entry_qoq_pct": "20",
        "revenue_bucket": "$500M-$1B",
    }

    watch = assign_tiers(watch_row)
    priority = assign_tiers(priority_row)

    assert watch["hp2_dislocation_momentum_priority"] == ""
    assert watch["hp2_dislocation_momentum_watch"] == "HP2 - Dislocation momentum watch"
    assert priority["hp2_dislocation_momentum_priority"] == "HP2 - Dislocation momentum re-rater"
    assert priority["hp2_dislocation_momentum_watch"] == ""


def test_extended_candidate_and_research_universes_match_live_rules():
    tier0 = {
        "pre_llm_fundamental_bucket": "mixed",
        "pre_llm_fundamental_score": "0",
        "entry_open": "20",
        "revenue_bucket": "$2B-$10B",
    }
    hp4_only = {
        "pre_llm_fundamental_bucket": "good",
        "pre_llm_fundamental_score": "4",
        "score_change": "2",
        "entry_open": "35",
        "entry_qoq_pct": "10",
        "revenue_bucket": "$2B-$10B",
    }

    tier0_out = assign_tiers(tier0)
    hp4_out = assign_tiers(hp4_only)

    assert tier0_out["extended_candidate_universe"]
    assert tier0_out["extended_research_universe"]
    assert hp4_out["extended_candidate_universe"] == ""
    assert hp4_out["extended_research_universe"]


def test_extended_research_universe_includes_hp2_priority_via_hp_research_extension():
    hp2_priority = {
        "pre_llm_fundamental_bucket": "weak",
        "pre_llm_fundamental_score": "-2",
        "entry_open": "35",
        "entry_qoq_pct": "20",
        "revenue_bucket": "$500M-$1B",
    }

    out = assign_tiers(hp2_priority)

    assert out["hp2_dislocation_momentum_priority"]
    assert out["hp_research_extension"]
    assert out["extended_research_universe"]


def test_hp3_large_quality_theme_exception_tracks_large_quality_leaders():
    row = {
        "pre_llm_fundamental_bucket": "strong",
        "pre_llm_fundamental_score": "8",
        "entry_open": "250",
        "entry_qoq_pct": "435",
        "revenue_bucket": ">$10B",
    }

    tiers = assign_tiers(row)

    assert tiers["hp3_large_quality_theme_exception"] == "HP3 - Large-revenue theme-leader exception"
    assert tiers["hp0_high_price_broad"]
    assert tiers["tier_0_bucket"] == ""


def test_hp3_large_quality_theme_exception_requires_large_revenue_and_score_8():
    small_revenue_row = {
        "pre_llm_fundamental_bucket": "strong",
        "pre_llm_fundamental_score": "8",
        "entry_open": "250",
        "revenue_bucket": "$2B-$10B",
    }
    lower_score_row = {
        "pre_llm_fundamental_bucket": "good",
        "pre_llm_fundamental_score": "7",
        "entry_open": "250",
        "revenue_bucket": ">$10B",
    }

    assert assign_tiers(small_revenue_row)["hp3_large_quality_theme_exception"] == ""
    assert assign_tiers(lower_score_row)["hp3_large_quality_theme_exception"] == ""


def test_hp4_score_reacceleration_watch_tracks_high_price_reacceleration():
    row = {
        "pre_llm_fundamental_bucket": "good",
        "pre_llm_fundamental_score": "4",
        "score_change": "2",
        "entry_open": "35",
        "entry_qoq_pct": "10",
        "revenue_bucket": "$2B-$10B",
    }

    tiers = assign_tiers(row)

    assert tiers["hp4_score_reacceleration_watch"] == "HP4 - Fundamental reacceleration watch tag"
    assert tiers["hp0_high_price_broad"]
    assert tiers["tier_0_bucket"] == ""


def test_hp4_score_reacceleration_watch_requires_score_and_price_reacceleration():
    no_score_change_row = {
        "pre_llm_fundamental_bucket": "good",
        "pre_llm_fundamental_score": "4",
        "score_change": "1",
        "entry_open": "35",
        "entry_qoq_pct": "15",
        "revenue_bucket": "$2B-$10B",
    }
    no_price_momentum_row = {
        "pre_llm_fundamental_bucket": "good",
        "pre_llm_fundamental_score": "4",
        "score_change": "2",
        "entry_open": "35",
        "entry_qoq_pct": "9.9",
        "revenue_bucket": "$2B-$10B",
    }

    assert assign_tiers(no_score_change_row)["hp4_score_reacceleration_watch"] == ""
    assert assign_tiers(no_price_momentum_row)["hp4_score_reacceleration_watch"] == ""


def test_add_hp_subtiers_matches_codex_ready_formulas():
    import pandas as pd

    df = pd.DataFrame(
        [
            {
                "ticker": "XYZ",
                "quarter": "2025Q1",
                "pre_llm_fundamental_score": 0,
                "pre_llm_fundamental_bucket": "mixed",
                "entry_open": 30,
                "entry_qoq_pct": 18,
                "revenue_bucket": "$500M-$1B",
                "post_llm_candidate_flag": 1,
                "causal_change": 3,
                "negative_revision_risk": 1,
            },
            {
                "ticker": "XYZ",
                "quarter": "2025Q2",
                "pre_llm_fundamental_score": 3,
                "pre_llm_fundamental_bucket": "good",
                "entry_open": 35,
                "entry_qoq_pct": 10,
                "revenue_bucket": "$500M-$1B",
                "post_llm_candidate_flag": 1,
                "causal_change": 3,
                "negative_revision_risk": 1,
            },
        ]
    )

    out = add_hp_subtiers(df)

    assert out.iloc[0]["hp2_dislocation_momentum_watch"]
    assert out.iloc[0]["hp2_watch_LLM_best"]
    assert out.iloc[0]["hp_structure_score"] == 8
    assert out.iloc[1]["score_change"] == 3
    assert out.iloc[1]["hp4_score_reacceleration_watch"]
    assert out.iloc[1]["hp4_LLM_supported"]


def test_hp_priority_watch_do_not_overlap_and_thresholds_are_explicit():
    import pandas as pd

    out = add_hp_subtiers(
        pd.DataFrame(
            [
                {
                    "ticker": "A",
                    "quarter": "2026Q1",
                    "pre_llm_fundamental_bucket": "weak",
                    "pre_llm_fundamental_score": -1,
                    "entry_open": 30,
                    "entry_qoq_pct": 20,
                    "revenue_bucket": "$500M-$1B",
                },
                {
                    "ticker": "B",
                    "quarter": "2026Q1",
                    "pre_llm_fundamental_bucket": "weak",
                    "pre_llm_fundamental_score": -1,
                    "entry_open": 30,
                    "entry_qoq_pct": 15,
                    "revenue_bucket": "$500M-$1B",
                },
                {
                    "ticker": "C",
                    "quarter": "2026Q1",
                    "pre_llm_fundamental_bucket": "weak",
                    "pre_llm_fundamental_score": -1,
                    "entry_open": 30,
                    "entry_qoq_pct": 19.999,
                    "revenue_bucket": "$500M-$1B",
                },
            ]
        )
    )

    assert out["hp2_dislocation_momentum_priority"].sum() == 1
    assert out["hp2_dislocation_momentum_watch"].sum() == 2
    assert not (out["hp2_dislocation_momentum_priority"] & out["hp2_dislocation_momentum_watch"]).any()


def test_hp_structure_score_uses_max_not_sum_and_total_structure_uses_max():
    import pandas as pd

    out = add_hp_subtiers(
        pd.DataFrame(
            [
                {
                    "ticker": "A",
                    "quarter": "2026Q1",
                    "pre_llm_fundamental_bucket": "strong",
                    "pre_llm_fundamental_score": 8,
                    "entry_open": 30,
                    "entry_qoq_pct": -25,
                    "revenue_bucket": ">$10B",
                    "tier_structure_score": 25,
                },
                {
                    "ticker": "B",
                    "quarter": "2026Q1",
                    "pre_llm_fundamental_bucket": "weak",
                    "pre_llm_fundamental_score": -1,
                    "entry_open": 30,
                    "entry_qoq_pct": 20,
                    "revenue_bucket": "$500M-$1B",
                    "tier_structure_score": 4,
                },
            ]
        )
    )

    assert out.iloc[0]["hp1_quality_pullback"]
    assert out.iloc[0]["hp3_large_quality_theme_exception"]
    assert out.iloc[0]["hp_structure_score"] == 15
    assert out.iloc[0]["total_structure_score"] == 25
    assert out.iloc[1]["hp_structure_score"] == 18
    assert out.iloc[1]["total_structure_score"] == 18


def test_hp_llm_best_requires_production_extension_and_llm_best():
    import pandas as pd

    out = add_hp_subtiers(
        pd.DataFrame(
            [
                {
                    "ticker": "A",
                    "quarter": "2026Q1",
                    "pre_llm_fundamental_bucket": "weak",
                    "pre_llm_fundamental_score": -1,
                    "entry_open": 30,
                    "entry_qoq_pct": 20,
                    "revenue_bucket": "$500M-$1B",
                    "post_llm_candidate_flag": 1,
                    "causal_change": 3,
                    "negative_revision_risk": 2,
                },
                {
                    "ticker": "B",
                    "quarter": "2026Q1",
                    "pre_llm_fundamental_bucket": "weak",
                    "pre_llm_fundamental_score": -1,
                    "entry_open": 30,
                    "entry_qoq_pct": 18,
                    "revenue_bucket": "$500M-$1B",
                    "post_llm_candidate_flag": 1,
                    "causal_change": 3,
                    "negative_revision_risk": 2,
                },
                {
                    "ticker": "C",
                    "quarter": "2026Q1",
                    "pre_llm_fundamental_bucket": "weak",
                    "pre_llm_fundamental_score": -1,
                    "entry_open": 30,
                    "entry_qoq_pct": 20,
                    "revenue_bucket": "$500M-$1B",
                    "post_llm_candidate_flag": 1,
                    "causal_change": 2,
                    "negative_revision_risk": 2,
                },
            ]
        )
    )

    assert out.iloc[0]["hp_LLM_best"]
    assert not out.iloc[1]["hp_LLM_best"]
    assert out.iloc[1]["hp2_watch_LLM_best"]
    assert not out.iloc[2]["hp_LLM_best"]


def test_subtiers_require_llm_fields():
    row = {
        "tier_1_bucket": "Tier 1 - Balanced priority feed",
        "tier_2_bucket": "Tier 2 - High-priority compact feed",
        "tier_3_bucket": "Tier 3 - Revised dislocation feed",
        "tier_4_bucket": "Tier 4 - Ultra-distressed tag, not a production tier",
        "post_llm_candidate_flag": "1",
        "causal_change": "3",
        "negative_revision_risk": "2",
        "post_llm_high_priority_flag": "1",
        "narrative_delta_bucket": "inflecting",
        "score_addition": "3",
    }
    prior = {"score_addition": "2"}

    subtiers = assign_subtiers(row, prior)

    assert subtiers["tier1_L3_best_balanced"]
    assert subtiers["tier2_L3_best_balanced"]
    assert subtiers["tier3_L4_persistent_high_priority"]
    assert subtiers["tier4_L3_clean_high_priority"]


def test_post_llm_subtier_flags_are_formula_clean_for_tiers_2_3_4():
    import pandas as pd

    out = add_post_llm_subtiers(
        pd.DataFrame(
            [
                {
                    "ticker": "AAA",
                    "quarter": "2025Q1",
                    "tier_2_bucket": "Tier 2 - High-priority compact feed",
                    "post_llm_candidate_flag": 1,
                    "causal_change": 3,
                    "negative_revision_risk": 2,
                },
                {
                    "ticker": "BBB",
                    "quarter": "2025Q1",
                    "tier_3_bucket": "Tier 3 - Revised dislocation feed",
                    "post_llm_candidate_flag": 1,
                    "causal_change": 2,
                    "negative_revision_risk": 1,
                    "narrative_delta_bucket": "inflecting",
                    "score_addition": 2,
                },
                {
                    "ticker": "BBB",
                    "quarter": "2025Q2",
                    "tier_3_bucket": "Tier 3 - Revised dislocation feed",
                    "post_llm_candidate_flag": 0,
                    "post_llm_high_priority_flag": 1,
                    "causal_change": 1,
                    "negative_revision_risk": 3,
                    "narrative_delta_bucket": "neutral",
                    "score_addition": 1,
                },
                {
                    "ticker": "CCC",
                    "quarter": "2025Q1",
                    "tier_4_bucket": "Tier 4 - Ultra-distressed tag, not a production tier",
                    "post_llm_candidate_flag": 1,
                    "post_llm_high_priority_flag": 0,
                    "causal_change": 3,
                    "negative_revision_risk": 2,
                },
                {
                    "ticker": "DDD",
                    "quarter": "2025Q1",
                    "tier_4_bucket": "Tier 4 - Ultra-distressed tag, not a production tier",
                    "post_llm_candidate_flag": 0,
                    "post_llm_high_priority_flag": 1,
                    "causal_change": 3,
                    "negative_revision_risk": 2,
                },
            ]
        )
    )

    assert out.iloc[0]["post_llm_tier_2_1_flag"] == 1
    assert out.iloc[0]["post_llm_tier_2_2_flag"] == 1
    assert out.iloc[0]["post_llm_tier_2_3_flag"] == 1
    assert out.iloc[1]["post_llm_tier_3_1_flag"] == 1
    assert out.iloc[1]["post_llm_tier_3_2_flag"] == 1
    assert out.iloc[2]["post_llm_tier_3_3_flag"] == 1
    assert out.iloc[2]["post_llm_tier_3_4_flag"] == 1
    assert out.iloc[3]["post_llm_tier_4_1_flag"] == 1
    assert out.iloc[3]["post_llm_tier_4_2_flag"] == 1
    assert out.iloc[3]["post_llm_tier_4_3_flag"] == 1
    assert out.iloc[4]["post_llm_tier_4_2_flag"] == 1
    assert out.iloc[4]["post_llm_tier_4_3_flag"] == 0
