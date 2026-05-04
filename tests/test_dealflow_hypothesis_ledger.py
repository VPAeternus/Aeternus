import json
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from tradingagents.dealflow.hypothesis_ledger import ledger_rows_path


def _minimal_config(extra: dict | None = None) -> dict:
    cfg = {
        "dealflow_min_signal_families": 1,
        "dealflow_momentum_lane_threshold": 68.0,
        "dealflow_momentum_lane_price_override_threshold": 82.0,
        "dealflow_momentum_lane_social_confirmation_threshold": 60.0,
        "dealflow_momentum_lane_floor_ratio": 0.20,
        "dealflow_momentum_lane_promotion_min_score": 62.0,
        "dealflow_momentum_lane_promotion_min_price_score": 70.0,
        "dealflow_core_quota": 12,
        "dealflow_momentum_quota": 8,
        "dealflow_deep_k": 2,
        "dealflow_deep_core_quota": 1,
        "dealflow_deep_momentum_quota": 1,
        "dealflow_deep_reserve_quota": 0,
        "dealflow_manual_slots_target": 0,
        "dealflow_manual_slots_min": 0,
        "dealflow_manual_slots_max": 0,
        "dealflow_manual_min_adv_usd": 0.0,
        "dealflow_manual_force_insert": False,
        "dealflow_max_sector_count": 10,
        "dealflow_max_asset_class_count": 10,
        "dealflow_connector_timeout_seconds": 1.0,
        "dealflow_connector_max_attempts": 1,
    }
    if extra:
        cfg.update(extra)
    return cfg


def _candidate(symbol: str, score: float, lane: str = "CORE") -> dict:
    return {
        "symbol": symbol,
        "lane": lane,
        "status": "ACTIVE",
        "source": "AUTO",
        "source_detail": "AUTO_MODEL",
        "manual_note": "",
        "manual_priority": 0,
        "deal_flow_score": score,
        "core_score": score,
        "momentum_score": score,
        "asymmetry_score": score - 5.0,
        "subscores": {
            "price_momentum": score,
            "social_momentum": score - 2.0,
            "news_catalyst": score - 3.0,
            "macro_regime_fit": score - 4.0,
            "smart_money": score - 5.0,
            "liquidity_tradability": score - 6.0,
        },
        "risk_tags": [],
        "trend_tags": [],
        "active_families": 4,
        "evidence_count": 6,
        "freshness_hours": 4.0,
        "sector": "Technology",
        "asset_class": "Equity",
    }


def test_collect_writes_shortlist_cut_ledger_row(tmp_path: Path, monkeypatch):
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    monkeypatch.chdir(tmp_path)

    candidates = [
        _candidate("AAPL", 92.0),
        _candidate("NVDA", 88.0),
        _candidate("MU", 74.0),
    ]

    with ExitStack() as stack:
        stack.enter_context(patch("tradingagents.dealflow.pipeline._AKG_AVAILABLE", False))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_social_news_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_price_momentum_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_macro_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_smart_money_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_sector_rotation_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_insider_cluster_signals", return_value=[]))
        stack.enter_context(
            patch(
                "tradingagents.dealflow.pipeline.score_candidates",
                return_value=([], [dict(row) for row in candidates]),
            )
        )
        stack.enter_context(
            patch(
                "tradingagents.dealflow.pipeline.rank_candidates",
                return_value=[dict(candidates[0]), dict(candidates[1])],
            )
        )

        pipeline = DealFlowPipeline(config=_minimal_config())
        pipeline._last_universe = ["AAPL", "NVDA", "MU"]
        pipeline._last_event_state = {
            "triggered": False,
            "reasons": [],
            "metrics": {"vix_jump_pct": None, "spy_move_pct": None},
        }
        pipeline._last_manual_ideas = []

        shortlist, _, _, _ = pipeline.collect(
            as_of_date="2026-03-06",
            trigger="manual",
            top_k=2,
        )

    rows_path = ledger_rows_path(
        base_dir=tmp_path / "eval_results" / "deal_flow" / "2026-03-06",
        lane="shared",
    )
    rows = json.loads(rows_path.read_text())

    row = next(entry for entry in rows if entry["stage_id"] == "shortlist_cut")
    assert row["stage_id"] == "shortlist_cut"
    assert row["kept_count"] == len(shortlist["candidates"])
    assert row["dropped_count"] == 1
    assert row["rule_snapshot"]["top_k"] == 2
    assert set(json.loads(Path(row["kept_symbols_path"]).read_text())) == {"AAPL", "NVDA"}
    assert json.loads(Path(row["dropped_symbols_path"]).read_text()) == ["MU"]
    metadata = json.loads(Path(row["dropped_symbols_metadata_path"]).read_text())
    assert metadata["MU"]["reason_code"] == "RANK_BELOW_SHORTLIST_CUT"
    assert metadata["MU"]["observed_value"]["rank"] == 3


def test_collect_writes_universe_gate_rows(tmp_path: Path, monkeypatch):
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    monkeypatch.chdir(tmp_path)

    candidates = [
        _candidate("AAPL", 92.0),
        _candidate("NVDA", 88.0),
    ]

    with ExitStack() as stack:
        stack.enter_context(patch("tradingagents.dealflow.pipeline._AKG_AVAILABLE", False))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_social_news_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_price_momentum_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_macro_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_smart_money_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_sector_rotation_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_insider_cluster_signals", return_value=[]))
        stack.enter_context(
            patch(
                "tradingagents.dealflow.pipeline.score_candidates",
                return_value=([], [dict(row) for row in candidates]),
            )
        )
        stack.enter_context(
            patch(
                "tradingagents.dealflow.pipeline.rank_candidates",
                return_value=[dict(candidates[0]), dict(candidates[1])],
            )
        )

        pipeline = DealFlowPipeline(config=_minimal_config())
        pipeline._last_universe = [
            {"symbol": "AAPL", "asset_class": "Equity", "sector": "Technology", "liquidity_score": 90.0, "aliases": []},
            {"symbol": "NVDA", "asset_class": "Equity", "sector": "Technology", "liquidity_score": 88.0, "aliases": []},
        ]
        pipeline._last_universe_ledger = {
            "kept_symbols": ["AAPL", "NVDA"],
            "candidate_drop_symbols": ["MU", "PLTR"],
            "haystack_drop_symbols": ["MU", "PLTR", "XYZ"],
            "rule_snapshot": {
                "filter_enabled": True,
                "tier_counts": {"T1_ANCHOR": 1, "T3_SCOUT": 1, "T3B_FVG_RECALL": 1},
                "kept_count": 2,
                "candidate_drop_count": 2,
                "haystack_drop_count": 3,
                "fvg_recall_selected_count": 1,
            },
        }
        pipeline._last_event_state = {
            "triggered": False,
            "reasons": [],
            "metrics": {"vix_jump_pct": None, "spy_move_pct": None},
        }
        pipeline._last_manual_ideas = []

        pipeline.collect(
            as_of_date="2026-03-06",
            trigger="manual",
            top_k=2,
        )

    rows_path = ledger_rows_path(
        base_dir=tmp_path / "eval_results" / "deal_flow" / "2026-03-06",
        lane="shared",
    )
    rows = json.loads(rows_path.read_text())

    edge_row = next(entry for entry in rows if entry["stage_id"] == "universe_gate_edge")
    haystack_row = next(entry for entry in rows if entry["stage_id"] == "universe_gate_haystack")

    assert edge_row["kept_count"] == 2
    assert edge_row["dropped_count"] == 2
    assert edge_row["rule_snapshot"]["candidate_drop_count"] == 2
    assert set(json.loads(Path(edge_row["kept_symbols_path"]).read_text())) == {"AAPL", "NVDA"}
    assert set(json.loads(Path(edge_row["dropped_symbols_path"]).read_text())) == {"MU", "PLTR"}
    edge_metadata = json.loads(Path(edge_row["dropped_symbols_metadata_path"]).read_text())
    assert edge_metadata["MU"]["reason_code"] == "UNIVERSE_CANDIDATE_GATE_EXCLUDED"

    assert haystack_row["kept_count"] == 2
    assert haystack_row["dropped_count"] == 3
    assert haystack_row["rule_snapshot"]["haystack_drop_count"] == 3
    assert haystack_row["rule_snapshot"]["fvg_recall_selected_count"] == 1
    assert set(json.loads(Path(haystack_row["kept_symbols_path"]).read_text())) == {"AAPL", "NVDA"}
    assert set(json.loads(Path(haystack_row["dropped_symbols_path"]).read_text())) == {"MU", "PLTR", "XYZ"}
    haystack_metadata = json.loads(Path(haystack_row["dropped_symbols_metadata_path"]).read_text())
    assert haystack_metadata["MU"]["reason_code"] == "UNIVERSE_NOT_IN_ACTIVE_TIERS"


def test_build_filtered_universe_records_fma_recall_counts(tmp_path: Path, monkeypatch):
    from tradingagents.dealflow.akg_universe import build_filtered_universe, get_last_universe_ledger

    class _AKG:
        def __init__(self):
            self._nodes = {
                "AAPL": {"id": "AAPL", "node_type": "company", "asset_class": "Equity", "sector_gics": "Technology", "liquidity_score": 90.0},
                "NVDA": {"id": "NVDA", "node_type": "company", "asset_class": "Equity", "sector_gics": "Technology", "liquidity_score": 95.0},
                "PLTR": {"id": "PLTR", "node_type": "company", "asset_class": "Equity", "sector_gics": "Technology", "liquidity_score": 70.0},
                "AMD": {"id": "AMD", "node_type": "company", "asset_class": "Equity", "sector_gics": "Technology", "liquidity_score": 75.0},
            }

        def get_centrality_scores(self):
            return None

        def get_supply_chain_neighbors(self, symbol, direction="both"):
            return []

        def get_emerging_planets(self, min_tier="ATMOSPHERE", top_k=200):
            return []

        def get_dark_nodes(self, min_centrality=0.3):
            return []

        def get_rescan_candidates(self, max_age_days=7):
            return []

        def get_open_positions(self):
            return []

    monkeypatch.setattr(
        "tradingagents.dealflow.akg_universe._build_anchor_set",
        lambda ttl_days=7: ["AAPL"],
    )

    rows, tier_map = build_filtered_universe(
        akg=_AKG(),
        fvg_recall_symbols=["NVDA", "PLTR"],
        fma_recall_symbols=["PLTR", "AMD"],
        config={"dealflow_universe_candidate_min_liquidity_score": 30.0},
    )

    ledger = get_last_universe_ledger()
    assert {row["symbol"] for row in rows} == {"AAPL", "NVDA", "PLTR", "AMD"}
    assert tier_map["AAPL"] == "T1_ANCHOR"
    assert tier_map["NVDA"] == "T3B_FVG_RECALL"
    assert tier_map["PLTR"] == "T3B_FVG_RECALL"
    assert tier_map["AMD"] == "T3C_FMA_RECALL"
    assert ledger["rule_snapshot"]["fvg_recall_selected_count"] == 2
    assert ledger["rule_snapshot"]["fma_recall_selected_count"] == 2
    assert ledger["rule_snapshot"]["fma_recall_overlap_with_fvg_count"] == 1


def test_collect_writes_evidence_gate_row(tmp_path: Path, monkeypatch):
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    monkeypatch.chdir(tmp_path)

    candidates = [
        _candidate("AAPL", 92.0),
        _candidate("NVDA", 88.0),
        {**_candidate("MU", 74.0), "status": "LOW_DATA", "active_families": 1, "evidence_count": 2},
    ]

    with ExitStack() as stack:
        stack.enter_context(patch("tradingagents.dealflow.pipeline._AKG_AVAILABLE", False))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_social_news_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_price_momentum_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_macro_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_smart_money_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_sector_rotation_signals", return_value=[]))
        stack.enter_context(patch("tradingagents.dealflow.pipeline.collect_insider_cluster_signals", return_value=[]))
        stack.enter_context(
            patch(
                "tradingagents.dealflow.pipeline.score_candidates",
                return_value=([], [dict(row) for row in candidates]),
            )
        )
        stack.enter_context(
            patch(
                "tradingagents.dealflow.pipeline.rank_candidates",
                return_value=[dict(candidates[0]), dict(candidates[1])],
            )
        )

        pipeline = DealFlowPipeline(config=_minimal_config({"dealflow_min_signal_families": 3}))
        pipeline._last_universe = ["AAPL", "NVDA", "MU"]
        pipeline._last_event_state = {
            "triggered": False,
            "reasons": [],
            "metrics": {"vix_jump_pct": None, "spy_move_pct": None},
        }
        pipeline._last_manual_ideas = []

        pipeline.collect(
            as_of_date="2026-03-06",
            trigger="manual",
            top_k=2,
        )

    rows_path = ledger_rows_path(
        base_dir=tmp_path / "eval_results" / "deal_flow" / "2026-03-06",
        lane="shared",
    )
    rows = json.loads(rows_path.read_text())

    row = next(entry for entry in rows if entry["stage_id"] == "evidence_gate")
    assert row["kept_count"] == 2
    assert row["dropped_count"] == 1
    assert row["rule_snapshot"]["min_signal_families"] == 3
    assert row["rule_snapshot"]["min_evidence_count"] == 5
    assert set(json.loads(Path(row["kept_symbols_path"]).read_text())) == {"AAPL", "NVDA"}
    assert json.loads(Path(row["dropped_symbols_path"]).read_text()) == ["MU"]
    metadata = json.loads(Path(row["dropped_symbols_metadata_path"]).read_text())
    assert metadata["MU"]["reason_code"] == "EVIDENCE_GATE_FAMILIES_AND_COUNT_BELOW_MIN"
    assert metadata["MU"]["delta_to_pass"]["signal_families"] == 2


def test_build_research_queue_writes_deep_selection_ledger_row(tmp_path: Path, monkeypatch):
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    monkeypatch.chdir(tmp_path)

    pipeline = DealFlowPipeline(config=_minimal_config())
    shortlist = {
        "run_id": "2026-03-06-120000-manual",
        "date": "2026-03-06",
        "candidates": [
            _candidate("AAPL", 92.0, lane="CORE"),
            _candidate("NVDA", 88.0, lane="MOMENTUM"),
            _candidate("MU", 74.0, lane="CORE"),
        ],
    }

    research_queue = pipeline._build_research_queue(
        shortlist,
        ledger_base_dir=tmp_path,
    )

    rows = json.loads(ledger_rows_path(base_dir=tmp_path, lane="shared").read_text())
    row = next(entry for entry in rows if entry["stage_id"] == "deep_selection_cut")

    assert row["kept_count"] == len(research_queue["selected_queue_ids"])
    assert row["dropped_count"] == 1
    assert row["rule_snapshot"]["deep_k"] == 2
    assert set(json.loads(Path(row["kept_symbols_path"]).read_text())) == {"AAPL", "NVDA"}
    assert json.loads(Path(row["dropped_symbols_path"]).read_text()) == ["MU"]
    metadata = json.loads(Path(row["dropped_symbols_metadata_path"]).read_text())
    assert metadata["MU"]["reason_code"] == "TRIAGE_RANK_BELOW_DEEP_CUT"
