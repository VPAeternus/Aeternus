import json


def test_scan_manual_earnings_options_setups_loads_promoted_symbols(tmp_path):
    from tradingagents.dealflow.sources import earnings_options_scout as mod

    artifact_path = tmp_path / "earnings_options_scout_2026-03-11.json"
    artifact_path.write_text(
        json.dumps(
            {
                "trending": [
                    {
                        "ticker": "MU",
                        "buzz_rank": 1,
                        "sentiment": "BULLISH",
                        "velocity": "ACCELERATING",
                        "catalyst": "Micron earnings with public bullish flow",
                        "sector": "Technology",
                        "accounts_flagged": 2,
                    },
                    {
                        "ticker": "BE",
                        "buzz_rank": 2,
                        "sentiment": "NEUTRAL",
                        "velocity": "STEADY",
                        "catalyst": "Bloom energy options attention",
                        "sector": "Industrials",
                    },
                ]
            }
        )
    )

    original = mod._artifact_path
    mod._artifact_path = lambda as_of_date: str(artifact_path)
    try:
        result = mod.scan_manual_earnings_options_setups("2026-03-11")
    finally:
        mod._artifact_path = original

    assert result["promoted_count"] == 2
    assert result["promoted_symbols"] == ["MU", "BE"]
    assert result["signals"][0]["source"] == "earnings_options"
    assert result["signals"][0]["delta_kind"] == "earnings_options"


def test_scan_manual_earnings_options_setups_returns_empty_when_missing(tmp_path):
    from tradingagents.dealflow.sources.earnings_options_scout import scan_manual_earnings_options_setups

    result = scan_manual_earnings_options_setups("2026-03-11")

    assert result["promoted_count"] == 0
    assert result["promoted_symbols"] == []
    assert result["signals"] == []
