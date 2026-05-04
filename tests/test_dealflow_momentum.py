import json
import datetime as dt
import time
import pandas as pd

from tradingagents.dealflow.pipeline import DealFlowPipeline
from tradingagents.dealflow.ranking import rank_candidates
from tradingagents.dealflow.scoring import score_candidates
from tradingagents.dealflow.sources import price_momentum


def _universe_row(symbol: str):
    return {
        "symbol": symbol,
        "asset_class": "Equity",
        "sector": "Technology",
        "liquidity_score": 90.0,
        "aliases": [symbol.lower()],
    }


def _signal(symbol: str, family: str, score: float, evidence: int = 5):
    return {
        "symbol": symbol,
        "signal_family": family,
        "raw_score": score,
        "z_score": 0.0,
        "direction": "BULLISH" if score >= 60 else "BEARISH" if score <= 40 else "NEUTRAL",
        "evidence_count": evidence,
        "freshness_hours": 1.0,
        "source_status": "OK",
        "source_name": "test",
    }


def test_scoring_assigns_momentum_lane():
    universe = [_universe_row("PLTR")]
    signals = [
        _signal("PLTR", "social_momentum", 88, 6),
        _signal("PLTR", "news_catalyst", 75, 5),
        _signal("PLTR", "macro_regime_fit", 60, 5),
        _signal("PLTR", "smart_money", 55, 5),
        _signal("PLTR", "price_momentum", 92, 5),
    ]

    _, candidates = score_candidates(
        universe=universe,
        signals=signals,
        min_signal_families=3,
        min_evidence_count=5,
    )
    candidate = candidates[0]
    assert candidate["lane"] == "MOMENTUM"
    assert candidate["momentum_score"] >= 70.0


def test_scoring_assigns_momentum_lane_with_price_override_and_light_social_evidence():
    universe = [_universe_row("TSLA")]
    signals = [
        _signal("TSLA", "social_momentum", 74, 2),
        _signal("TSLA", "news_catalyst", 68, 4),
        _signal("TSLA", "macro_regime_fit", 58, 4),
        _signal("TSLA", "smart_money", 52, 3),
        _signal("TSLA", "price_momentum", 91, 4),
    ]

    _, candidates = score_candidates(
        universe=universe,
        signals=signals,
        min_signal_families=3,
        min_evidence_count=5,
    )
    candidate = candidates[0]
    assert candidate["lane"] == "MOMENTUM"
    assert candidate["momentum_score"] >= 70.0
    assert "theme-energy-transition" in candidate["trend_tags"]


def test_scoring_rebalances_lane_when_momentum_coverage_is_too_low():
    universe = [_universe_row("PLTR"), _universe_row("PROMO"), _universe_row("CORE1"), _universe_row("CORE2")]
    signals = [
        _signal("PLTR", "social_momentum", 82, 6),
        _signal("PLTR", "news_catalyst", 70, 5),
        _signal("PLTR", "macro_regime_fit", 61, 5),
        _signal("PLTR", "smart_money", 57, 5),
        _signal("PLTR", "price_momentum", 89, 5),
        _signal("PROMO", "social_momentum", 50, 1),
        _signal("PROMO", "news_catalyst", 65, 4),
        _signal("PROMO", "macro_regime_fit", 58, 4),
        _signal("PROMO", "smart_money", 53, 4),
        _signal("PROMO", "price_momentum", 72, 4),
        _signal("CORE1", "social_momentum", 45, 1),
        _signal("CORE1", "news_catalyst", 56, 4),
        _signal("CORE1", "macro_regime_fit", 55, 4),
        _signal("CORE1", "smart_money", 52, 4),
        _signal("CORE1", "price_momentum", 58, 4),
        _signal("CORE2", "social_momentum", 44, 1),
        _signal("CORE2", "news_catalyst", 54, 4),
        _signal("CORE2", "macro_regime_fit", 54, 4),
        _signal("CORE2", "smart_money", 53, 4),
        _signal("CORE2", "price_momentum", 57, 4),
    ]

    _, candidates = score_candidates(
        universe=universe,
        signals=signals,
        min_signal_families=3,
        min_evidence_count=5,
        momentum_lane_floor_ratio=0.50,
        momentum_lane_promotion_min_score=62.0,
        momentum_lane_promotion_min_price_score=70.0,
    )
    by_symbol = {c["symbol"]: c for c in candidates}

    assert by_symbol["PLTR"]["lane"] == "MOMENTUM"
    assert by_symbol["PROMO"]["lane"] == "MOMENTUM"
    assert "Momentum lane (calibrated)" in by_symbol["PROMO"]["risk_tags"]


def _candidate(idx: int, lane: str):
    symbol = f"C{idx}" if lane == "CORE" else f"M{idx}"
    score = 70.0 + idx
    return {
        "symbol": symbol,
        "asset_class": "Equity",
        "sector": f"S{idx}",
        "liquidity_score": 80.0,
        "subscores": {"macro_regime_fit": 60.0, "news_catalyst": 60.0},
        "deal_flow_score": score,
        "core_score": score if lane == "CORE" else 50.0,
        "momentum_score": score if lane == "MOMENTUM" else 55.0,
        "asymmetry_score": score if lane == "MOMENTUM" else 45.0,
        "active_families": 4,
        "evidence_count": 10,
        "freshness_hours": 1.0,
        "status": "ACTIVE",
        "risk_tags": ["Standard"],
        "trend_tags": ["balanced"],
        "lane": lane,
        "reason": "test",
    }


def test_rank_candidates_enforces_12_8_lane_split():
    candidates = [_candidate(i, "CORE") for i in range(12)] + [_candidate(i, "MOMENTUM") for i in range(8)]
    ranked = rank_candidates(
        candidates=candidates,
        top_k=20,
        max_sector_count=100,
        min_macro_hedge_candidates=0,
        core_quota=12,
        momentum_quota=8,
    )
    core = [c for c in ranked if c.get("lane") == "CORE"]
    momentum = [c for c in ranked if c.get("lane") == "MOMENTUM"]
    assert len(ranked) == 20
    assert len(core) == 12
    assert len(momentum) == 8


def test_pipeline_queue_contains_lane_fields_and_4_4_deep_split(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    pipeline_module = __import__("tradingagents.dealflow.pipeline", fromlist=["DealFlowPipeline"])

    universe_rows = [_universe_row(f"T{i}") for i in range(20)]

    def fake_build_universe(extra_symbols=None, min_extra_adv_usd=0, config=None):  # pylint: disable=unused-argument
        return universe_rows

    def fake_collect(*args, **kwargs):  # pylint: disable=unused-argument
        return []

    candidates = []
    for i in range(12):
        c = _candidate(i, "CORE")
        c["symbol"] = f"C{i}"
        candidates.append(c)
    for i in range(8):
        c = _candidate(i, "MOMENTUM")
        c["symbol"] = f"M{i}"
        candidates.append(c)

    ranked = []
    for idx, c in enumerate(candidates, start=1):
        row = dict(c)
        row["rank"] = idx
        ranked.append(row)

    monkeypatch.setattr(pipeline_module, "build_universe_from_akg", fake_build_universe)
    monkeypatch.setattr(pipeline_module, "collect_social_news_signals", fake_collect)
    monkeypatch.setattr(pipeline_module, "collect_price_momentum_signals", fake_collect)
    monkeypatch.setattr(pipeline_module, "collect_macro_signals", fake_collect)
    monkeypatch.setattr(pipeline_module, "collect_smart_money_signals", fake_collect)
    monkeypatch.setattr(pipeline_module, "collect_sector_rotation_signals", fake_collect)
    monkeypatch.setattr(pipeline_module, "collect_insider_cluster_signals", fake_collect)
    monkeypatch.setattr(pipeline_module, "scan_breakout_discovery", fake_collect)
    monkeypatch.setattr(pipeline_module, "score_candidates", lambda **kwargs: ([], candidates))
    monkeypatch.setattr(pipeline_module, "rank_candidates", lambda *args, **kwargs: ranked)
    monkeypatch.setattr(DealFlowPipeline, "_market_shock_metrics", lambda self: (None, None))

    from tradingagents.dealflow.sources import iv_scanner, insider_cluster, breakout_scanner
    monkeypatch.setattr(iv_scanner, "scan_earnings_iv", lambda **kwargs: {"force_queue": [], "scanned": 0, "earnings_approaching": [], "covered_call_signals": [], "neutral": [], "akg_enriched": []})
    monkeypatch.setattr(insider_cluster, "scan_insider_sweep", lambda **kwargs: {"skipped": True})
    monkeypatch.setattr(breakout_scanner, "scan_breakout_discovery", lambda **kwargs: {"ran": True, "alerts": [], "count": 0})

    pipeline = DealFlowPipeline(
        config={
            "dealflow_top_k": 20,
            "dealflow_deep_k": 8,
            "dealflow_deep_core_quota": 4,
            "dealflow_deep_momentum_quota": 4,
            "dealflow_min_signal_families": 3,
            "dealflow_dynamic_universe_min_adv_usd": 0.0,
            "dealflow_core_quota": 12,
            "dealflow_momentum_quota": 8,
            "dealflow_trigger_vix_jump_pct": 15.0,
            "dealflow_trigger_spy_move_pct": 1.5,
        }
    )

    shortlist, queue, _, _ = pipeline.run(as_of_date="2026-02-06", trigger="manual", top_k=20)
    assert len(shortlist["candidates"]) == 20
    assert len(queue["items"]) == 20
    assert "canonical_sector_map" in queue
    assert queue["canonical_sector_map"]["C0"] == ranked[0]["sector"]
    assert all("lane" in item for item in queue["items"])
    assert all("research_playbook" in item for item in queue["items"])
    assert all("why_now" in item for item in queue["items"])

    selected = [i for i in queue["items"] if i["selected_for_deep"]]
    assert len(selected) == 8
    selected_core = [i for i in selected if i["lane"] == "CORE"]
    selected_momentum = [i for i in selected if i["lane"] == "MOMENTUM"]
    assert len(selected_core) == 4
    assert len(selected_momentum) == 4

    base = tmp_path / "eval_results" / "deal_flow" / "2026-02-06"
    connector_health_path = base / "connector_health.json"
    family_contrib_path = base / "family_contributions.json"
    assert connector_health_path.exists()
    assert family_contrib_path.exists()

    connector_health = json.loads(connector_health_path.read_text())
    family_contrib = json.loads(family_contrib_path.read_text())
    assert isinstance(connector_health, list)
    assert family_contrib["aggregate"]["CORE"]["count"] >= 0


def test_manual_merge_policy_reinforces_and_includes(monkeypatch):
    pipeline = DealFlowPipeline(
        config={
            "dealflow_manual_slots_target": 3,
            "dealflow_manual_slots_min": 2,
            "dealflow_manual_slots_max": 4,
            "dealflow_manual_min_adv_usd": 50_000_000.0,
        }
    )

    ranked_auto = [
        {
            "rank": 1,
            "symbol": "AAPL",
            "lane": "CORE",
            "core_score": 90.0,
            "asymmetry_score": 60.0,
            "freshness_hours": 1.0,
            "asset_class": "Equity",
            "sector": "Technology",
            "risk_tags": [],
        },
        {
            "rank": 2,
            "symbol": "MSFT",
            "lane": "CORE",
            "core_score": 89.0,
            "asymmetry_score": 58.0,
            "freshness_hours": 1.0,
            "asset_class": "Equity",
            "sector": "Technology",
            "risk_tags": [],
        },
    ]
    candidate_map = ranked_auto + [
        {
            "symbol": "TSLA",
            "lane": "MOMENTUM",
            "core_score": 55.0,
            "asymmetry_score": 88.0,
            "freshness_hours": 2.0,
            "asset_class": "Equity",
            "sector": "Automotive",
            "status": "ACTIVE",
            "risk_tags": [],
        }
    ]
    manual_ideas = [
        {
            "symbol": "AAPL",
            "priority": 5,
            "lane_preference": "CORE",
            "note": "manual reinforce",
            "created_at": "2026-02-05T00:00:00+00:00",
            "expires_at": "2026-03-05T00:00:00+00:00",
            "active": True,
        },
        {
            "symbol": "TSLA",
            "priority": 4,
            "lane_preference": "MOMENTUM",
            "note": "manual include",
            "created_at": "2026-02-05T00:00:00+00:00",
            "expires_at": "2026-03-05T00:00:00+00:00",
            "active": True,
        },
    ]

    monkeypatch.setattr(
        "tradingagents.dealflow.pipeline.validate_symbol_liquidity",
        lambda symbol, min_adv_usd: (True, float(min_adv_usd) + 1.0),  # pylint: disable=unused-argument
    )

    shortlist, summary = pipeline._apply_manual_merge_policy(  # pylint: disable=protected-access
        ranked_auto=ranked_auto,
        candidates=candidate_map,
        manual_ideas=manual_ideas,
        top_k=2,
    )

    assert len(shortlist) == 2
    assert summary["reinforced"] == 1
    assert summary["included"] == 1
    symbols = {row["symbol"] for row in shortlist}
    assert "AAPL" in symbols
    assert "TSLA" in symbols
    assert any(row.get("source") == "MANUAL" for row in shortlist)


def test_manual_merge_includes_low_data_and_missing_candidates(monkeypatch):
    pipeline = DealFlowPipeline(
        config={
            "dealflow_manual_slots_target": 3,
            "dealflow_manual_slots_min": 2,
            "dealflow_manual_slots_max": 4,
            "dealflow_manual_min_adv_usd": 50_000_000.0,
        }
    )

    ranked_auto = [
        {
            "rank": 1,
            "symbol": "AAPL",
            "lane": "CORE",
            "core_score": 90.0,
            "asymmetry_score": 60.0,
            "freshness_hours": 1.0,
            "asset_class": "Equity",
            "sector": "Technology",
            "risk_tags": [],
        },
        {
            "rank": 2,
            "symbol": "MSFT",
            "lane": "CORE",
            "core_score": 89.0,
            "asymmetry_score": 58.0,
            "freshness_hours": 1.0,
            "asset_class": "Equity",
            "sector": "Technology",
            "risk_tags": [],
        },
    ]

    candidate_map = ranked_auto + [
        {
            "symbol": "OKLO",
            "lane": "MOMENTUM",
            "core_score": 44.0,
            "asymmetry_score": 66.0,
            "freshness_hours": 3.0,
            "asset_class": "Equity",
            "sector": "Energy",
            "status": "LOW_DATA",
            "risk_tags": [],
        }
    ]

    manual_ideas = [
        {
            "symbol": "OKLO",
            "priority": 5,
            "lane_preference": "MOMENTUM",
            "note": "force include low-data",
            "created_at": "2026-02-05T00:00:00+00:00",
            "expires_at": "2026-03-05T00:00:00+00:00",
            "active": True,
        },
        {
            "symbol": "RGTI",
            "priority": 4,
            "lane_preference": "MOMENTUM",
            "note": "not in auto candidates",
            "created_at": "2026-02-05T00:00:00+00:00",
            "expires_at": "2026-03-05T00:00:00+00:00",
            "active": True,
        },
    ]

    monkeypatch.setattr(
        "tradingagents.dealflow.pipeline.validate_symbol_liquidity",
        lambda symbol, min_adv_usd: (True, float(min_adv_usd) + 1.0),  # pylint: disable=unused-argument
    )

    shortlist, summary = pipeline._apply_manual_merge_policy(  # pylint: disable=protected-access
        ranked_auto=ranked_auto,
        candidates=candidate_map,
        manual_ideas=manual_ideas,
        top_k=2,
    )

    symbols = {row["symbol"] for row in shortlist}
    assert "OKLO" in symbols or "RGTI" in symbols
    assert summary["included"] >= 1
    assert any("Manual override" in " ".join(row.get("risk_tags", [])) for row in shortlist if row.get("source") == "MANUAL")


def test_manual_merge_overrides_diversification_caps_when_forced(monkeypatch):
    pipeline = DealFlowPipeline(
        config={
            "dealflow_manual_slots_target": 3,
            "dealflow_manual_slots_min": 2,
            "dealflow_manual_slots_max": 4,
            "dealflow_manual_min_adv_usd": 50_000_000.0,
            "dealflow_max_sector_count": 1,
            "dealflow_max_asset_class_count": 8,
            "dealflow_manual_force_insert": True,
        }
    )

    ranked_auto = [
        {
            "rank": 1,
            "symbol": "AAPL",
            "lane": "CORE",
            "core_score": 90.0,
            "asymmetry_score": 60.0,
            "freshness_hours": 1.0,
            "asset_class": "Equity",
            "sector": "Technology",
            "risk_tags": [],
        },
        {
            "rank": 2,
            "symbol": "XLF",
            "lane": "CORE",
            "core_score": 80.0,
            "asymmetry_score": 55.0,
            "freshness_hours": 1.0,
            "asset_class": "ETF",
            "sector": "Financials",
            "risk_tags": [],
        },
    ]

    candidates = ranked_auto + [
        {
            "symbol": "PLTR",
            "lane": "MOMENTUM",
            "core_score": 64.0,
            "asymmetry_score": 84.0,
            "freshness_hours": 2.0,
            "asset_class": "Equity",
            "sector": "Technology",
            "status": "ACTIVE",
            "risk_tags": [],
        }
    ]

    manual_ideas = [
        {
            "symbol": "PLTR",
            "priority": 5,
            "lane_preference": "MOMENTUM",
            "note": "must include",
            "created_at": "2026-02-05T00:00:00+00:00",
            "expires_at": "2026-03-05T00:00:00+00:00",
            "active": True,
        }
    ]

    monkeypatch.setattr(
        "tradingagents.dealflow.pipeline.validate_symbol_liquidity",
        lambda symbol, min_adv_usd: (True, float(min_adv_usd) + 1.0),  # pylint: disable=unused-argument
    )

    shortlist, summary = pipeline._apply_manual_merge_policy(  # pylint: disable=protected-access
        ranked_auto=ranked_auto,
        candidates=candidates,
        manual_ideas=manual_ideas,
        top_k=2,
    )

    assert summary["included"] == 1
    symbols = {row["symbol"] for row in shortlist}
    assert "PLTR" in symbols
    pltr = next(row for row in shortlist if row["symbol"] == "PLTR")
    assert "Manual cap override" in pltr.get("risk_tags", [])


def test_manual_merge_overrides_liquidity_when_forced(monkeypatch):
    pipeline = DealFlowPipeline(
        config={
            "dealflow_manual_slots_target": 3,
            "dealflow_manual_slots_min": 2,
            "dealflow_manual_slots_max": 4,
            "dealflow_manual_min_adv_usd": 50_000_000.0,
            "dealflow_manual_force_insert": True,
        }
    )

    ranked_auto = [
        {
            "rank": 1,
            "symbol": "AAPL",
            "lane": "CORE",
            "core_score": 90.0,
            "asymmetry_score": 60.0,
            "freshness_hours": 1.0,
            "asset_class": "Equity",
            "sector": "Technology",
            "risk_tags": [],
        },
        {
            "rank": 2,
            "symbol": "MSFT",
            "lane": "CORE",
            "core_score": 88.0,
            "asymmetry_score": 58.0,
            "freshness_hours": 1.0,
            "asset_class": "Equity",
            "sector": "Technology",
            "risk_tags": [],
        },
    ]
    manual_ideas = [
        {
            "symbol": "TSLA",
            "priority": 5,
            "lane_preference": "MOMENTUM",
            "note": "operator thesis",
            "created_at": "2026-02-05T00:00:00+00:00",
            "expires_at": "2026-03-05T00:00:00+00:00",
            "active": True,
        }
    ]

    monkeypatch.setattr(
        "tradingagents.dealflow.pipeline.validate_symbol_liquidity",
        lambda symbol, min_adv_usd: (False, 0.0),  # pylint: disable=unused-argument
    )

    shortlist, summary = pipeline._apply_manual_merge_policy(  # pylint: disable=protected-access
        ranked_auto=ranked_auto,
        candidates=ranked_auto,
        manual_ideas=manual_ideas,
        top_k=2,
    )

    assert summary["included"] == 1
    tsla = next(row for row in shortlist if row["symbol"] == "TSLA")
    assert "Manual liquidity unchecked" in tsla.get("risk_tags", [])


def test_collect_connector_signals_times_out_and_reports_error():
    pipeline = DealFlowPipeline(
        config={
            "dealflow_connector_timeout_seconds": 0.05,
            "dealflow_connector_max_attempts": 1,
        }
    )

    def _slow_collector(*args, **kwargs):  # pylint: disable=unused-argument
        time.sleep(0.2)
        return [{"symbol": "AAPL"}]

    signals, health = pipeline._collect_connector_signals(  # pylint: disable=protected-access
        "slow_connector",
        _slow_collector,
    )
    assert signals == []
    assert health["status"] == "ERROR"
    assert "timed out" in str(health.get("error", "")).lower()


def test_price_momentum_handles_unavailable_batch_download(monkeypatch):
    monkeypatch.setattr(price_momentum, "_download_prices_batch", lambda symbols, period="180d": None)
    signals = price_momentum.collect_price_momentum_signals([_universe_row("AAPL"), _universe_row("TSLA")])
    assert len(signals) == 2
    assert all(signal["source_status"] == "NO_DATA" for signal in signals)


def test_price_momentum_uses_shared_market_cache(monkeypatch):
    idx = pd.date_range("2026-01-01", periods=120, freq="D")
    captured = {}

    def _frame(offset: float):
        base = pd.Series(range(len(idx)), index=idx, dtype=float) + offset
        return pd.DataFrame(
            {
                "Open": base + 100,
                "High": base + 101,
                "Low": base + 99,
                "Close": base + 100,
                "Adj Close": base + 100,
                "Volume": (base + 1) * 1000,
            }
        )

    monkeypatch.setattr(
        price_momentum,
        "ensure_ohlcv_history",
        lambda symbols, **kwargs: captured.update({"symbols": list(symbols), **kwargs}) or {
            "AAPL": _frame(0.0),
            "TSLA": _frame(10.0),
            "SPY": _frame(5.0),
        },
    )
    monkeypatch.setattr(
        price_momentum,
        "_download_prices_batch",
        lambda symbols, period="380d": (_ for _ in ()).throw(AssertionError("raw yf path should not be used")),
    )

    signals = price_momentum.collect_price_momentum_signals([_universe_row("AAPL"), _universe_row("TSLA")])

    assert len(signals) == 2
    assert all(signal["source_status"] == "OK" for signal in signals)
    assert captured["symbols"] == ["AAPL", "TSLA", "SPY"]
    assert captured["min_bars"] == 90
    assert captured["full_period"] == "180d"
