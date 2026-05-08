import json

from tradingagents.dealflow.collect_artifacts import write_collect_artifacts


def test_write_collect_artifacts_persists_core_json_and_latest_queue(tmp_path):
    base_root = tmp_path / "deal_flow"
    research_queue = {"run_id": "r1", "items": [{"symbol": "GLW"}]}
    shortlist = {"candidates": [{"symbol": "GLW", "rank": 1}], "top_k": 1}

    write_collect_artifacts(
        as_of_date="2026-05-05",
        normalized_signals=[{"symbol": "GLW"}],
        shortlist=shortlist,
        research_queue=research_queue,
        cashtag_events=[{"ticker": "GLW"}],
        momentum_board={"leaders": ["GLW"]},
        connector_health=[{"source": "x", "status": "OK"}],
        family_contribution_report={"families": []},
        manual_merge={"inserted": []},
        all_scored_candidates=[{"symbol": "GLW", "status": "ACTIVE", "momentum_score": 88, "core_score": 70}],
        deal_flow_root=base_root,
    )

    day = base_root / "2026-05-05"
    assert json.loads((day / "signals_raw.json").read_text()) == [{"symbol": "GLW"}]
    assert json.loads((day / "research_queue.json").read_text()) == research_queue
    assert json.loads((base_root / "latest_research_queue.json").read_text()) == research_queue
    scored = json.loads((day / "all_scored_candidates.json").read_text())
    assert scored[0]["symbol"] == "GLW"
    assert scored[0]["in_shortlist"] is True
    final_tickers = json.loads((day / "final_dealflow_tickers.json").read_text())
    assert final_tickers["contract"] == "AUTHORITATIVE_DEALFLOW_TICKER_HANDOFF_V1"
    assert final_tickers["source_stage"] == "all_scored_candidates"
    assert final_tickers["count"] == 1
    assert final_tickers["tickers"] == ["GLW"]
    assert (day / "final_dealflow_tickers.txt").read_text() == "GLW\n"
    assert json.loads((base_root / "latest_final_dealflow_tickers.json").read_text())["tickers"] == ["GLW"]
    assert (base_root / "latest_final_dealflow_tickers.txt").read_text() == "GLW\n"


def test_write_collect_artifacts_overwrites_stale_scored_file_with_empty_list(tmp_path):
    base_root = tmp_path / "deal_flow"
    day = base_root / "2026-05-05"
    day.mkdir(parents=True)
    (day / "all_scored_candidates.json").write_text(json.dumps([{"symbol": "STALE"}]))

    write_collect_artifacts(
        as_of_date="2026-05-05",
        normalized_signals=[],
        shortlist={"candidates": []},
        research_queue={"items": []},
        cashtag_events=[],
        momentum_board={},
        connector_health=[],
        family_contribution_report={},
        manual_merge={},
        all_scored_candidates=[],
        deal_flow_root=base_root,
    )

    assert json.loads((day / "all_scored_candidates.json").read_text()) == []


def test_write_collect_artifacts_tolerates_bad_momentum_score(tmp_path):
    base_root = tmp_path / "deal_flow"

    write_collect_artifacts(
        as_of_date="2026-05-05",
        normalized_signals=[],
        shortlist={"candidates": [{"symbol": "GLW"}]},
        research_queue={"items": []},
        cashtag_events=[],
        momentum_board={},
        connector_health=[],
        family_contribution_report={},
        manual_merge={},
        all_scored_candidates=[{"symbol": "BAD", "momentum_score": None}, {"symbol": "GLW", "momentum_score": "bad"}],
        deal_flow_root=base_root,
    )

    scored = json.loads((base_root / "2026-05-05" / "all_scored_candidates.json").read_text())
    assert {row["symbol"] for row in scored} == {"BAD", "GLW"}


def test_write_collect_artifacts_dedupes_final_full_universe_tickers(tmp_path):
    base_root = tmp_path / "deal_flow"

    write_collect_artifacts(
        as_of_date="2026-05-05",
        normalized_signals=[],
        shortlist={"candidates": [{"symbol": "MSFT"}]},
        research_queue={"items": [{"symbol": "QUEUE_ONLY"}]},
        cashtag_events=[],
        momentum_board={},
        connector_health=[],
        family_contribution_report={},
        manual_merge={},
        all_scored_candidates=[
            {"symbol": "msft", "momentum_score": 3},
            {"symbol": "AAPL", "momentum_score": 2},
            {"symbol": "MSFT", "momentum_score": 1},
        ],
        deal_flow_root=base_root,
    )

    payload = json.loads((base_root / "2026-05-05" / "final_dealflow_tickers.json").read_text())
    assert payload["source_stage"] == "all_scored_candidates"
    assert payload["count"] == 2
    assert payload["tickers"] == ["MSFT", "AAPL"]


def test_write_collect_artifacts_joins_x_feed_provenance(tmp_path):
    base_root = tmp_path / "deal_flow"
    x_feed_root = tmp_path / "x_feed"
    merged_dir = x_feed_root / "2026-05-05"
    merged_dir.mkdir(parents=True)
    (merged_dir / "merged.json").write_text(json.dumps({"GLW": {"sentiment": 0.8, "catalyst": "optical"}}))

    write_collect_artifacts(
        as_of_date="2026-05-05",
        normalized_signals=[],
        shortlist={"candidates": [{"symbol": "GLW", "rank": 2, "lane": "CORE", "core_score": 75}]},
        research_queue={"items": []},
        cashtag_events=[],
        momentum_board={},
        connector_health=[],
        family_contribution_report={},
        manual_merge={},
        all_scored_candidates=[],
        deal_flow_root=base_root,
        x_feed_root=x_feed_root,
    )

    provenance = json.loads((base_root / "2026-05-05" / "grok_provenance.json").read_text())
    assert provenance["tickers_ingested"] == 1
    assert provenance["tickers"][0]["in_shortlist"] is True
    assert provenance["tickers"][0]["pipeline_rank"] == 2
