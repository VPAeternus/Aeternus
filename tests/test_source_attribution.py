import json

from tradingagents.dealflow.source_attribution import build_source_attribution


def test_build_source_attribution_from_existing_artifacts(tmp_path):
    base = tmp_path / "eval_results" / "deal_flow" / "2026-02-07"
    base.mkdir(parents=True, exist_ok=True)
    (base / "discovery_delta.json").write_text(
        json.dumps(
            {
                "signals": [
                    {"symbol": "NVDA", "source": "fma_recall"},
                    {"symbol": "BABA", "source": "earnings_options"},
                ],
                "symbol_records": [
                    {"symbol": "NVDA", "sources_fired": ["fma_recall"]},
                    {"symbol": "BABA", "sources_fired": ["earnings_options"]},
                ],
            }
        )
    )
    (base / "scout_audit.json").write_text(
        json.dumps(
            {
                "signals": [{"symbol": "BABA", "source": "earnings_options"}],
                "breakout": {"alerts": [{"ticker": "NVDA"}]},
            }
        )
    )
    (base / "signals_raw.json").write_text(
        json.dumps(
            [
                {"symbol": "NVDA", "signal_family": "price_momentum"},
                {"symbol": "NVDA", "signal_family": "smart_money"},
                {"symbol": "BABA", "signal_family": "social_momentum"},
            ]
        )
    )
    (base / "research_queue.json").write_text(
        json.dumps(
            {
                "items": [
                    {"symbol": "NVDA", "selected_for_deep": True},
                    {"symbol": "BABA", "selected_for_deep": False},
                ]
            }
        )
    )
    (base / "shortlist_top20.json").write_text(
        json.dumps(
            {
                "candidates": [
                    {"symbol": "NVDA"},
                    {"symbol": "BABA"},
                ]
            }
        )
    )

    result = build_source_attribution("2026-02-07", base_dir=tmp_path / "eval_results" / "deal_flow")

    assert result["ticker_count"] == 2
    rows = {row["symbol"]: row for row in result["rows"]}
    assert rows["NVDA"]["collector_families_present"] == ["price_momentum", "smart_money"]
    assert "fma_recall" in rows["NVDA"]["discovery_sources"]
    assert rows["NVDA"]["selected_for_deep"] is True
    assert rows["BABA"]["entered_shortlist"] is True

