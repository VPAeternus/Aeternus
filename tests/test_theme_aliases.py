from pathlib import Path
import sys

from tradingagents.dealflow.theme_aliases import load_theme_aliases, match_theme_aliases

ROOT = Path(__file__).resolve().parents[1]
FUNDAMENTAL_ROOT = ROOT / "tradingagents" / "research" / "fundamental"
if str(FUNDAMENTAL_ROOT) not in sys.path:
    sys.path.insert(0, str(FUNDAMENTAL_ROOT))

from src.features.themes import detect_candidate_themes


def test_match_theme_aliases_from_config():
    matches = match_theme_aliases("Company cited 800G optical transceiver demand from AI data centers.")
    ids = {m["theme_id"] for m in matches}
    assert "optical_networking" in ids
    assert "ai_data_center" in ids


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
