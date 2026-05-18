from pathlib import Path


def test_score_paths_do_not_import_or_call_unsafe_companyfacts_converter():
    path = Path("tradingagents/research/fundamental/src/daily_run/scoring_inputs.py")
    text = path.read_text(encoding="utf-8")

    assert "ingest.xbrl import companyfacts_to_pre_llm_input" not in text
    assert " companyfacts_to_pre_llm_input(" not in text
