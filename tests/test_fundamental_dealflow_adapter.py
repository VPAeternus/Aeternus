import csv
import json
from pathlib import Path
from types import SimpleNamespace

from tradingagents.research.fundamental.src.pipeline import dealflow_adapter


def test_build_dealflow_universe_csv_uses_final_ticker_handoff_without_scores(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    handoff_dir = tmp_path / "eval_results" / "deal_flow" / "2026-05-11"
    handoff_dir.mkdir(parents=True)
    handoff_path = handoff_dir / "final_dealflow_tickers.json"
    handoff_path.write_text(
        json.dumps(
            {
                "date": "2026-05-11",
                "source_stage": "scout_ticker_summary",
                "tickers": ["NOK", "AAOI"],
                "metadata_by_ticker": {
                    "NOK": {"scouts": ["x_manual_feed"]},
                    "AAOI": {"scouts": ["breakout_scan"]},
                },
            }
        )
    )

    monkeypatch.setattr(
        dealflow_adapter,
        "resolve_ciks_for_tickers",
        lambda symbols, refresh=False: [
            SimpleNamespace(ticker=symbol, cik=f"CIK-{symbol}", company_title=f"{symbol} Inc", status="resolved")
            for symbol in symbols
        ],
    )

    output_path = tmp_path / "fundamental" / "dealflow_universe.csv"
    result = dealflow_adapter.build_dealflow_universe_csv(
        as_of_date="2026-05-11",
        handoff_path=handoff_path,
        output_path=output_path,
        quarter="2026Q2",
    )

    rows = list(csv.DictReader(output_path.open()))
    assert result["handoff_path"] == str(handoff_path)
    assert result["row_count"] == 2
    assert [row["ticker"] for row in rows] == ["NOK", "AAOI"]
    assert rows[0]["dealflow_source_stage"] == "scout_ticker_summary"
    assert rows[0]["scouts_json"] == "[\"x_manual_feed\"]"
    forbidden = {
        "deal_" + "flow_score",
        "core_" + "score",
        "momentum_" + "score",
        "asymmetry_" + "score",
        "triage_" + "score",
        "dealflow_" + "rank",
    }
    assert forbidden.isdisjoint(rows[0].keys())
