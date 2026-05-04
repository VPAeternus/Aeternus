import json
from unittest.mock import patch

from typer.testing import CliRunner

from cli.main import app


runner = CliRunner()


def _valid_payload():
    return {
        "trending": [
            {
                "ticker": "mu",
                "buzz_rank": 1,
                "sentiment": "BULLISH",
                "velocity": "ACCELERATING",
                "catalyst": "Micron earnings with public bullish call flow",
                "sector": "Technology",
                "earnings_date": "2026-03-18",
                "setup_type": "earnings_options",
                "flow_summary": "$3.2M call sweep",
                "accounts_flagged": 3,
            }
        ]
    }


def test_earnings_options_prompt_generate_renders_date():
    result = runner.invoke(app, ["earnings-options-prompt", "--generate", "--date", "2026-03-11"])

    assert result.exit_code == 0
    assert "Grok earnings/options prompt for 2026-03-11" in result.stdout
    assert "DATE: 2026-03-11" in result.stdout


def test_earnings_options_prompt_ingest_saves_validated_payload(tmp_path):
    payload = _valid_payload()
    artifact_path = tmp_path / "earnings_options_scout_2026-03-11.json"

    with patch(
        "tradingagents.dealflow.sources.earnings_options_scout._artifact_path",
        return_value=str(artifact_path),
    ):
        result = runner.invoke(
            app,
            ["earnings-options-prompt", "--ingest", "--date", "2026-03-11"],
            input=json.dumps(payload),
        )

    assert result.exit_code == 0
    assert artifact_path.exists()
    saved = json.loads(artifact_path.read_text())
    assert saved["trending"][0]["ticker"] == "MU"
    assert saved["trending"][0]["accounts_flagged"] == 3


def test_earnings_options_prompt_validation_requires_trending_list():
    result = runner.invoke(
        app,
        ["earnings-options-prompt", "--ingest", "--date", "2026-03-11"],
        input=json.dumps({"wrong": []}),
    )

    assert result.exit_code == 1
    assert "JSON must contain a 'trending' list" in result.stdout
