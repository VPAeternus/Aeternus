import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUNDAMENTAL_ROOT = ROOT / "tradingagents" / "research" / "fundamental"
if str(FUNDAMENTAL_ROOT) not in sys.path:
    sys.path.insert(0, str(FUNDAMENTAL_ROOT))

from src.features.llm_extraction import read_cached_llm_rows_for_packets, result_schema, save_llm_rows_to_cache, validate_llm_result
from src.features.theme_acceleration import compute_theme_acceleration_score


def _packet():
    return {"sample_id": "AAA_2026Q1", "quarter": "2026Q1", "ticker": "AAA", "event_date": "2026-05-01"}


def _payload(**overrides):
    base = {
        "sample_id": "AAA_2026Q1",
        "quarter": "2026Q1",
        "ticker": "AAA",
        "event_date": "2026-05-01",
        "causal_change": 2,
        "proof_alignment": 2,
        "durability": 1,
        "operating_leverage_quality": 1,
        "negative_revision_risk": 1,
        "story_vs_numbers_gap_penalty": 0,
        "narrative_delta_score": 5,
        "narrative_delta_bucket": "constructive",
        "score_addition": 1,
        "detected_driver_category": "demand",
        "detected_driver_name": "AI optical demand",
        "evidence_positive": "AI demand drove segment growth.",
        "evidence_risk": "",
        "confidence": "medium",
        "blocking_issues": "",
        "primary_theme": "optical_networking",
        "secondary_themes": ["ai_data_center"],
        "theme_tags": ["800G"],
        "theme_role": "supplier",
        "theme_confidence": "medium",
        "theme_driver_type": "revenue",
        "theme_momentum": "accelerating",
        "theme_evidence": ["Management said AI/data-center demand drove optical segment growth."],
        "filing_theme_growth_flag": 1,
        "filing_theme_guidance_flag": 1,
        "filing_theme_margin_flag": 0,
        "filing_theme_customer_win_flag": 1,
        "filing_theme_capacity_expansion_flag": 0,
        "theme_acceleration_score": 0,
        "theme_tailwind_score": 0,
        "theme_driver_summary": "AI optical demand is driving revenue.",
        "theme_evidence_summary": "AI/data-center demand drove optical segment growth.",
    }
    base.update(overrides)
    return base


def test_theme_acceleration_fields_are_required_in_schema():
    required = result_schema()["properties"]["results"]["items"]["required"]
    for field in [
        "filing_theme_growth_flag",
        "filing_theme_guidance_flag",
        "filing_theme_margin_flag",
        "filing_theme_customer_win_flag",
        "filing_theme_capacity_expansion_flag",
        "theme_acceleration_score",
    ]:
        assert field in required


def test_validate_llm_result_computes_theme_acceleration_score():
    row = validate_llm_result(_payload(), _packet())
    assert row["filing_theme_growth_flag"] == 1
    assert row["filing_theme_guidance_flag"] == 1
    assert row["filing_theme_customer_win_flag"] == 1
    assert row["theme_acceleration_score"] == 13


def test_missing_theme_evidence_zeroes_acceleration_score():
    row = validate_llm_result(_payload(theme_evidence=[]), _packet())
    assert row["theme_acceleration_score"] == 0


def test_theme_acceleration_score_is_capped():
    assert compute_theme_acceleration_score(_payload(
        filing_theme_growth_flag=1,
        filing_theme_guidance_flag=1,
        filing_theme_margin_flag=1,
        filing_theme_customer_win_flag=1,
        filing_theme_capacity_expansion_flag=1,
    )) == 15


def test_llm_cache_round_trips_validated_rows(tmp_path):
    cache_csv = tmp_path / "llm_cache.csv"
    packet = _packet()
    row = validate_llm_result(_payload(), packet)

    save_summary = save_llm_rows_to_cache([row], cache_csv=cache_csv)
    cached_rows, missing_packets, read_summary = read_cached_llm_rows_for_packets([packet], cache_csv=cache_csv)

    assert save_summary["llm_cache_upserted_count"] == 1
    assert read_summary["llm_cache_hit_count"] == 1
    assert missing_packets == []
    assert cached_rows[0]["sample_id"] == "AAA_2026Q1"
    assert cached_rows[0]["secondary_themes"] == "[\"ai_data_center\"]"
