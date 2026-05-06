from pathlib import Path
import sys

from tradingagents.dealflow.theme_aliases import canonicalize_theme_id, load_theme_aliases, match_theme_aliases

ROOT = Path(__file__).resolve().parents[1]
FUNDAMENTAL_ROOT = ROOT / "tradingagents" / "research" / "fundamental"
if str(FUNDAMENTAL_ROOT) not in sys.path:
    sys.path.insert(0, str(FUNDAMENTAL_ROOT))

from src.features.themes import assign_theme_tailwind_score, detect_candidate_themes


def test_canonicalize_theme_id_maps_theme_name_and_alias():
    assert canonicalize_theme_id("AI Data Center Infrastructure") == "ai_data_center"
    assert canonicalize_theme_id("800G") == "optical_networking"
    assert canonicalize_theme_id("AI-Data Center/Infrastructure") == "ai_data_center_infrastructure"


def test_match_theme_aliases_from_config():
    matches = match_theme_aliases("Company cited 800G optical transceiver demand from AI data centers.")
    ids = {m["theme_id"] for m in matches}
    assert "optical_networking" in ids
    assert "ai_data_center" in ids


def test_match_theme_aliases_uses_boundaries_for_short_aliases():
    aliases = {"ai_short": {"theme_name": "AI", "aliases": ["AI"]}}
    assert match_theme_aliases("AI demand is rising", aliases)[0]["theme_id"] == "ai_short"
    assert match_theme_aliases("said paid demand is rising", aliases) == []


def test_detect_candidate_themes_includes_alias_matches():
    rows = detect_candidate_themes({
        "ticker": "GLW",
        "quarter": "2026Q1",
        "primary_theme": "",
        "secondary_themes": [],
        "theme_tags": [],
        "theme_role": "supplier",
        "theme_confidence": "medium",
        "theme_evidence": ["Management cited 1.6T optical communications demand."],
    })
    assert "optical_networking" in {row["theme_id"] for row in rows}


def test_tailwind_score_uses_canonical_primary_theme_for_cohort_strength():
    score = assign_theme_tailwind_score(
        {
            "ticker": "GLW",
            "primary_theme": "AI Data Center Infrastructure",
            "theme_role": "supplier",
            "theme_confidence": "high",
            "theme_evidence": ["AI data center demand drove revenue."],
            "causal_change": 3,
            "theme_driver_type": "revenue",
        },
        cohort_scores={"ai_data_center": {"theme_cohort_strength": "strong"}},
    )
    assert score >= 10


def test_detect_candidate_themes_uses_alias_role_hint_when_role_missing():
    rows = detect_candidate_themes({
        "ticker": "AXTI",
        "quarter": "2026Q1",
        "theme_role": "none",
        "theme_confidence": "medium",
        "theme_evidence": ["800G optical demand."],
    })
    optical = next(row for row in rows if row["theme_id"] == "optical_networking")
    assert optical["theme_role"] in {"supplier", "infrastructure_provider", "bottleneck_supplier", "direct_beneficiary"}
    assert optical["theme_role"] != "none"


def test_detect_candidate_themes_does_not_fragment_canonical_theme_name():
    rows = detect_candidate_themes({
        "ticker": "GLW",
        "quarter": "2026Q1",
        "primary_theme": "AI Data Center Infrastructure",
        "secondary_themes": ["800G"],
        "theme_role": "supplier",
        "theme_confidence": "medium",
        "theme_evidence": ["AI data center and 800G demand."],
    })
    ids = {row["theme_id"] for row in rows}
    assert "ai_data_center" in ids
    assert "optical_networking" in ids
    assert "ai_data_center_infrastructure" not in ids
