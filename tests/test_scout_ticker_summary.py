import json

from tradingagents.dealflow.scout_ticker_summary import (
    build_scout_ticker_summary,
    persist_scout_ticker_summary,
)
from tradingagents.dealflow.pipeline import DealFlowPipeline


def _retired_artifact(*parts: str) -> str:
    return "".join(parts)


def test_build_scout_ticker_summary_counts_unique_union_and_overlap():
    scout_audit = {
        "breakout": {"alerts": [{"ticker": "aaoi"}, {"ticker": "$MP"}]},
        "iv": {"force_queue": ["PENG"]},
        "insider": {
            "buy_clusters": [{"ticker": "P"}],
            "sell_clusters": [{"ticker": "MP"}],
        },
        "technical_ignition": {"promoted_symbols": ["SKYX"]},
        "thirteenf_watchlist": {"symbols": ["NOK", "AAOI"]},
    }

    summary = build_scout_ticker_summary(
        "2026-05-11",
        x_feed_merged={"nok": {}, "MP": {}},
        scout_audit=scout_audit,
        fvg_recall={"selected_symbols": ["AAOI"]},
        fma_recall={"selected_symbols": ["MP"]},
    )

    assert summary["contract"] == "DEALFLOW_SCOUT_TICKER_TOTAL_V1"
    assert summary["scout_counts"] == {
        "x_manual_feed": 2,
        "breakout_scan": 2,
        "thirteenf_watchlist": 2,
        "insider_cluster": 2,
        "technical_ignition": 1,
        "iv_force_queue": 1,
        "fvg_recall": 1,
        "fma_recall": 1,
        "commodity_shock": 0,
        "dod_contract": 0,
    }
    assert summary["total_mentions"] == 12
    assert summary["total_unique_tickers"] == 6
    assert summary["tickers"] == ["NOK", "MP", "AAOI", "P", "SKYX", "PENG"]
    assert summary["overlap"]["MP"] == [
        "x_manual_feed",
        "breakout_scan",
        "insider_cluster",
        "fma_recall",
    ]


def test_persist_scout_ticker_summary_writes_only_scout_handoff(tmp_path):
    root = tmp_path / "deal_flow"
    stale = root / "2026-05-11"
    stale.mkdir(parents=True)
    (stale / _retired_artifact("research_", "queue.json")).write_text("{}")
    (stale / _retired_artifact("short", "list_", "top20.json")).write_text("{}")
    (stale / _retired_artifact("all_", "scored_candidates.json")).write_text("[]")
    (root / _retired_artifact("latest_", "research_", "queue.json")).write_text("{}")

    summary = build_scout_ticker_summary(
        "2026-05-11",
        x_feed_merged={"NOK": {}, "AAOI": {}},
        scout_audit={},
        fvg_recall={},
        fma_recall={},
    )

    persist_scout_ticker_summary(summary, deal_flow_root=root)

    day = root / "2026-05-11"
    assert not (day / _retired_artifact("research_", "queue.json")).exists()
    assert not (day / _retired_artifact("short", "list_", "top20.json")).exists()
    assert not (day / _retired_artifact("all_", "scored_candidates.json")).exists()
    assert not (root / _retired_artifact("latest_", "research_", "queue.json")).exists()

    persisted = json.loads((day / "scout_ticker_summary.json").read_text())
    assert persisted["total_unique_tickers"] == 2
    handoff = json.loads((day / "final_dealflow_tickers.json").read_text())
    assert handoff == {
        "date": "2026-05-11",
        "source_stage": "scout_ticker_summary",
        "count": 2,
        "tickers": ["NOK", "AAOI"],
        "metadata_by_ticker": {
            "NOK": {"scouts": ["x_manual_feed"]},
            "AAOI": {"scouts": ["x_manual_feed"]},
        },
        "contract": "AUTHORITATIVE_DEALFLOW_TICKER_HANDOFF_V2",
    }
    assert (day / "final_dealflow_tickers.txt").read_text() == "NOK\nAAOI\n"
    assert json.loads((root / "latest_scout_ticker_summary.json").read_text())["tickers"] == ["NOK", "AAOI"]
    assert json.loads((root / "latest_final_dealflow_tickers.json").read_text())["source_stage"] == "scout_ticker_summary"


def test_pipeline_collect_returns_scout_summary_without_queue_or_signals(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pipeline = DealFlowPipeline(config={})
    pipeline._last_scout_ticker_summary = build_scout_ticker_summary(
        "2026-05-11",
        x_feed_merged={"NOK": {}},
        scout_audit={"breakout": {"alerts": [{"ticker": "AAOI"}]}},
        fvg_recall={},
        fma_recall={},
    )
    pipeline._last_event_state = {"triggered": False, "reasons": [], "metrics": {}}

    summary, queue, signals, event_state = pipeline.collect(
        as_of_date="2026-05-11",
        trigger="manual",
        top_k=30,
    )

    assert queue == {}
    assert signals == []
    assert event_state == {"triggered": False, "reasons": [], "metrics": {}}
    assert summary["total_unique_tickers"] == 2
    assert not (
        tmp_path
        / "eval_results"
        / "deal_flow"
        / "2026-05-11"
        / _retired_artifact("research_", "queue.json")
    ).exists()
