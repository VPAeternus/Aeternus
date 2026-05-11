import json
from pathlib import Path

from tradingagents.context.company_context import get_company_context


def test_company_context_collects_internal_sources(tmp_path: Path):
    akg_path = tmp_path / "eval_results" / "control" / "knowledge_graph.json"
    akg_path.parent.mkdir(parents=True, exist_ok=True)
    akg_path.write_text(
        json.dumps(
            {
                "version": 1,
                "created_at": "2026-03-22T00:00:00Z",
                "updated_at": "2026-03-22T00:00:00Z",
                "nodes": {
                    "AAPL": {
                        "id": "AAPL",
                        "node_type": "company",
                        "sector": "semis_ai_infrastructure",
                        "display_name": "Apple Inc",
                        "signal_strength": 0.42,
                        "centrality": 0.18,
                        "times_surfaced": 4,
                        "last_surfaced": "2026-03-21T12:00:00Z",
                        "aeternus_score": 63.4,
                        "metadata": {"seed_sources": ["akg_seed"]},
                    }
                },
                "edges": [],
                "causal_events": {},
            }
        )
    )

    results_dir = tmp_path / "results" / "AAPL" / "2026-03-21"
    results_dir.mkdir(parents=True, exist_ok=True)
    results_dir.joinpath("analysis_report.json").write_text(
        json.dumps(
            {
                "ticker": "AAPL",
                "aeternus_score": {
                    "rating": "Buy",
                    "aeternus_score": 63.4,
                    "confidence": 4,
                }
            }
        )
    )

    dealflow_dir = tmp_path / "eval_results" / "deal_flow"
    handoff_dir = dealflow_dir / "2026-03-20"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    handoff_dir.joinpath("final_dealflow_tickers.json").write_text(
        json.dumps(
            {
                "run_id": "handoff-1",
                "date": "2026-03-20",
                "tickers": ["AAPL"],
                "source_stage": "scout_handoff",
                "metadata_by_ticker": {"AAPL": {"scouts": ["x_manual"], "mention_count": 2}},
            }
        )
    )

    positions_path = tmp_path / "eval_results" / "paper_execution" / "positions.json"
    positions_path.parent.mkdir(parents=True, exist_ok=True)
    positions_path.write_text(
        json.dumps(
            {
                "updated_at": "2026-03-22T00:00:00Z",
                "open_positions": {
                    "AAPL": {
                        "symbol": "AAPL",
                        "net_quantity": 25,
                        "avg_price": 201.5,
                        "last_mark_price": 204.1,
                        "direction": "LONG",
                    }
                },
            }
        )
    )

    x_feed_dir = tmp_path / "eval_results" / "x_feed" / "2026-03-18"
    x_feed_dir.mkdir(parents=True, exist_ok=True)
    x_feed_dir.joinpath("merged.json").write_text(
        json.dumps(
            {
                "AAPL": {
                    "ticker": "AAPL",
                    "sentiment": "BULLISH",
                    "velocity": "ACCELERATING",
                    "catalyst": "Services strength narrative",
                }
            }
        )
    )

    payload = get_company_context(
        "aapl",
        as_of_date="2026-03-22",
        knowledge_graph_path=akg_path,
        dealflow_base_dir=dealflow_dir,
        results_base_dir=tmp_path / "results",
        positions_path=positions_path,
        x_feed_base_dir=tmp_path / "eval_results" / "x_feed",
    )

    assert payload["symbol"] == "AAPL"
    assert payload["akg"]["found"] is True
    assert payload["akg"]["display_name"] == "Apple Inc"
    assert payload["analysis"]["found"] is True
    assert payload["analysis"]["latest_report_date"] == "2026-03-21"
    assert payload["analysis"]["rating"] == "Buy"
    assert payload["analysis"]["aeternus_score"] == 63.4
    assert payload["dealflow"]["scout_handoff"]["found"] is True
    assert payload["dealflow"]["scout_handoff"]["date"] == "2026-03-20"
    assert payload["portfolio"]["found"] is True
    assert payload["portfolio"]["position"]["net_quantity"] == 25
    assert payload["x_feed"]["found"] is True
    assert payload["x_feed"]["source_date"] == "2026-03-18"
    assert payload["known_gaps"] == []


def test_company_context_reports_missing_internal_sources(tmp_path: Path):
    akg_path = tmp_path / "eval_results" / "control" / "knowledge_graph.json"
    akg_path.parent.mkdir(parents=True, exist_ok=True)
    akg_path.write_text(
        json.dumps(
            {
                "version": 1,
                "created_at": "2026-03-22T00:00:00Z",
                "updated_at": "2026-03-22T00:00:00Z",
                "nodes": {
                    "AAPL": {
                        "id": "AAPL",
                        "node_type": "company",
                        "sector": "semis_ai_infrastructure",
                        "display_name": "Apple Inc",
                    }
                },
                "edges": [],
                "causal_events": {},
            }
        )
    )

    payload = get_company_context(
        "AAPL",
        as_of_date="2026-03-22",
        knowledge_graph_path=akg_path,
        dealflow_base_dir=tmp_path / "eval_results" / "deal_flow",
        results_base_dir=tmp_path / "results",
        positions_path=tmp_path / "eval_results" / "paper_execution" / "positions.json",
        x_feed_base_dir=tmp_path / "eval_results" / "x_feed",
    )

    assert payload["akg"]["found"] is True
    assert payload["analysis"]["found"] is False
    assert payload["dealflow"]["scout_handoff"]["found"] is False
    assert payload["portfolio"]["found"] is False
    assert payload["x_feed"]["found"] is False
    assert "No internal analysis report found." in payload["known_gaps"]
    assert "Ticker not present in latest scout ticker handoff." in payload["known_gaps"]
    assert "Ticker not present in current internal positions." in payload["known_gaps"]
    assert "Ticker not present in internal X-feed coverage." in payload["known_gaps"]
