"""Tests for manual X Feed Scout — 16-pass sector sweep."""

import json
import os

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_JSON = json.dumps({
    "trending": [
        {"ticker": "NVDA", "buzz_rank": 1, "sentiment": "BULLISH", "velocity": "ACCELERATING", "catalyst": "Blackwell demand", "sector": "Technology"},
        {"ticker": "AMD", "buzz_rank": 2, "sentiment": "NEUTRAL", "velocity": "STEADY", "catalyst": "AI competition", "sector": "Technology"},
        {"ticker": "INTC", "buzz_rank": 3, "sentiment": "BEARISH", "velocity": "FADING", "catalyst": "Foundry delays", "sector": "Technology"},
    ]
})

VALID_JSON_WITH_THEMES = json.dumps({
    "trending": [
        {"ticker": "NVDA", "buzz_rank": 1, "sentiment": "BULLISH", "velocity": "ACCELERATING", "catalyst": "AI capex", "sector": "Technology"},
    ],
    "active_themes": [
        {"theme": "ai_infrastructure", "sectors": ["Technology"], "conviction": 0.9, "reasoning": "Hyperscaler capex"}
    ]
})

CRYPTO_JSON = json.dumps({
    "trending": [
        {"ticker": "BTC", "buzz_rank": 1, "sentiment": "BULLISH", "velocity": "ACCELERATING", "catalyst": "Bitcoin ETF", "sector": "Crypto"},
        {"ticker": "ETH", "buzz_rank": 2, "sentiment": "BULLISH", "velocity": "STEADY", "catalyst": "Merge", "sector": "Crypto"},
        {"ticker": "AAPL", "buzz_rank": 3, "sentiment": "NEUTRAL", "velocity": "STEADY", "catalyst": "iPhone sales", "sector": "Technology"},
    ]
})

FENCED_JSON = "```json\n" + VALID_JSON + "\n```"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_generate_prompts_returns_16():
    from tradingagents.dealflow.sources.x_feed_manual import generate_prompts
    prompts = generate_prompts()
    assert len(prompts) == 16
    for pnum, label, text in prompts:
        assert 1 <= pnum <= 16
        assert len(label) > 0
        assert len(text) > 50  # non-trivial prompt


def test_pass16_blindspot_prompt_includes_existing_context(tmp_path, monkeypatch):
    from tradingagents.dealflow.sources import x_feed_manual as mod

    merged_path = tmp_path / "merged.json"
    merged_path.write_text(json.dumps({
        "MP": {"ticker": "MP", "co_mentions": ["USAR"], "theme_links": ["critical_minerals_supply_chain"]},
        "LITE": {"ticker": "LITE", "co_mentions": ["AAOI"], "theme_links": ["ai_data_center_infrastructure"]},
    }))
    monkeypatch.setattr(mod, "_merged_path", lambda d: str(merged_path))

    prompts = mod.generate_prompts("2026-05-11")
    pass_16 = [p for p in prompts if p[0] == 16]

    assert len(pass_16) == 1
    _, label, text = pass_16[0]
    assert label == "Blindspot & Unmapped Ticker Audit"
    assert "already_seen_status" in text
    assert "ticker_disambiguation" in text
    assert "US-listed common stocks and ADRs" in text
    assert "MP" in text
    assert "AAOI" in text


def test_parse_pass16_preserves_blindspot_metadata():
    from tradingagents.dealflow.sources.x_feed_manual import parse_pass

    raw = json.dumps({"trending": [{
        "ticker": "NOK",
        "buzz_rank": 1,
        "sentiment": "BULLISH",
        "velocity": "ACCELERATING",
        "catalyst": "@acct cites US-listed ADR attention around private wireless/AI networking",
        "sector": "Technology",
        "accounts_cited": ["@acct"],
        "theme_links": ["networking_reacceleration"],
        "why_this_is_new": "ADR angle was missed by US-only sector sweep wording",
        "already_seen_status": "not_seen",
        "why_15_passes_missed_it": "Likely skipped because it is an ADR and telecom/networking cross-classification",
        "best_existing_pass": 1,
        "ticker_disambiguation": "Nokia Oyj ADR, NYSE:NOK",
        "target_seeded": True,
    }]})

    row = parse_pass(raw, 16)[0]

    assert row["source_pass_type"] == "blindspot"
    assert row["already_seen_status"] == "not_seen"
    assert row["why_15_passes_missed_it"].startswith("Likely skipped")
    assert row["best_existing_pass"] == 1
    assert row["ticker_disambiguation"] == "Nokia Oyj ADR, NYSE:NOK"
    assert row["target_seeded"] is True


def test_parse_pass_valid_json():
    from tradingagents.dealflow.sources.x_feed_manual import parse_pass
    entries = parse_pass(VALID_JSON, 1)
    assert len(entries) == 3
    assert entries[0]["ticker"] == "NVDA"
    assert entries[0]["buzz_rank"] == 1
    assert entries[0]["mentions_estimate"] == 1
    assert entries[0]["sentiment"] == 0.5  # BULLISH
    assert entries[0]["velocity_trend"] == "rising"  # ACCELERATING
    assert entries[0]["pass_number"] == 1
    assert entries[0]["source_pass_type"] == "sector"


def test_parse_pass_filters_crypto():
    from tradingagents.dealflow.sources.x_feed_manual import parse_pass
    entries = parse_pass(CRYPTO_JSON, 1)
    tickers = [e["ticker"] for e in entries]
    assert "BTC" not in tickers
    assert "ETH" not in tickers
    assert "AAPL" in tickers
    assert len(entries) == 1


def test_parse_pass_handles_markdown_fence():
    from tradingagents.dealflow.sources.x_feed_manual import parse_pass
    entries = parse_pass(FENCED_JSON, 1)
    assert len(entries) == 3
    assert entries[0]["ticker"] == "NVDA"


def test_merge_preserves_multi_pass_evidence(tmp_path, monkeypatch):
    from tradingagents.dealflow.sources import x_feed_manual as mod

    # Redirect artifact paths to tmp
    monkeypatch.setattr(mod, "_merged_path", lambda d: str(tmp_path / "merged.json"))
    monkeypatch.setattr(mod, "_raw_dir", lambda d: str(tmp_path / "raw"))
    monkeypatch.setattr(mod, "_theme_graph_path", lambda d: str(tmp_path / "theme_emergence_graph.json"))

    # Stub out AKG and cache writes
    monkeypatch.setattr(
        mod,
        "write_akg",
        lambda entries, d, themes=None, options_flow=None, gex_regime=None: {"written": len(entries), "new": 0},
    )

    # Pass 1: NVDA bullish
    pass1 = json.dumps({"trending": [
        {"ticker": "NVDA", "buzz_rank": 1, "sentiment": "BULLISH", "velocity": "ACCELERATING", "catalyst": "Pass 1", "sector": "Tech"},
    ]})
    mod.ingest_pass("2026-03-05", pass1, 1)

    # Pass 2: NVDA bearish (should add evidence without losing pass 1)
    pass2 = json.dumps({"trending": [
        {"ticker": "NVDA", "buzz_rank": 1, "sentiment": "BEARISH", "velocity": "FADING", "catalyst": "Pass 2", "sector": "Tech"},
    ]})
    mod.ingest_pass("2026-03-05", pass2, 2)

    merged = mod.load_merged("2026-03-05")
    assert merged["NVDA"]["pass_number"] == 2
    assert merged["NVDA"]["sentiment"] == -0.5  # latest scoring row
    assert merged["NVDA"]["pass_numbers"] == [1, 2]
    assert len(merged["NVDA"]["evidence"]) == 2
    assert (tmp_path / "theme_emergence_graph.json").exists()


def test_save_raw_never_overwrites(tmp_path, monkeypatch):
    from tradingagents.dealflow.sources import x_feed_manual as mod

    monkeypatch.setattr(mod, "_raw_dir", lambda d: str(tmp_path / "raw"))

    path1 = mod.save_raw_pass("2026-03-05", 1, '{"first": true}')
    path2 = mod.save_raw_pass("2026-03-05", 1, '{"second": true}')

    assert path1 != path2
    assert os.path.exists(path1)
    assert os.path.exists(path2)
    assert "_v2" in path2

    # Read back to confirm contents preserved
    with open(path1) as f:
        assert "first" in f.read()
    with open(path2) as f:
        assert "second" in f.read()


def test_velocity_z_within_cohort():
    from tradingagents.dealflow.sources.x_feed_manual import parse_pass
    from tradingagents.dealflow.sources.x_feed_scout import _compute_batch_velocity_z

    entries = parse_pass(VALID_JSON, 1)
    cohort = {e["ticker"]: e for e in entries}
    _compute_batch_velocity_z(cohort)

    # Rank 1 (NVDA) should have highest z, rank 3 (INTC) lowest
    assert cohort["NVDA"]["velocity_z"] > cohort["AMD"]["velocity_z"]
    assert cohort["AMD"]["velocity_z"] > cohort["INTC"]["velocity_z"]
    assert cohort["NVDA"]["velocity_z"] > 0
    assert cohort["INTC"]["velocity_z"] < 0


def test_ingest_pass_does_not_write_xai_cache_mirror(tmp_path, monkeypatch):
    from tradingagents.dealflow.sources import x_feed_manual as mod

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod, "_merged_path", lambda d: str(tmp_path / "merged.json"))
    monkeypatch.setattr(mod, "_raw_dir", lambda d: str(tmp_path / "raw"))
    monkeypatch.setattr(
        mod,
        "write_akg",
        lambda entries, d, themes=None, options_flow=None, gex_regime=None: {"written": len(entries), "new": 0},
    )

    raw = json.dumps(
        {
            "trending": [
                {
                    "ticker": "MSFT",
                    "buzz_rank": 1,
                    "sentiment": "BULLISH",
                    "velocity": "ACCELERATING",
                    "catalyst": "Azure growth",
                    "sector": "Technology",
                }
            ]
        }
    )

    mod.ingest_pass("2026-03-05", raw, 1)

    xai_cache_path = tmp_path / "eval_results" / "deal_flow" / "xai_social_cache_2026-03-05.json"
    assert not xai_cache_path.exists()


def test_get_readiness_reports_missing_passes(tmp_path, monkeypatch):
    from tradingagents.dealflow.sources import x_feed_manual as mod

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "pass_01.json").write_text("{}")
    (raw_dir / "pass_15.json").write_text("{}")
    merged_path = tmp_path / "merged.json"
    merged_path.write_text(json.dumps({"NVDA": {"ticker": "NVDA"}}))

    monkeypatch.setattr(mod, "_raw_dir", lambda d: str(raw_dir))
    monkeypatch.setattr(mod, "_merged_path", lambda d: str(merged_path))

    readiness = mod.get_readiness("2026-03-09")
    assert readiness["ready"] is False
    assert readiness["completed_passes"] == [1, 15]
    assert 2 in readiness["missing_passes"]
    assert readiness["merged_symbol_count"] == 1


def test_get_readiness_requires_finalized_manifest(tmp_path, monkeypatch):
    from tradingagents.dealflow.sources import x_feed_manual as mod

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    for pass_num in range(1, 17):
        (raw_dir / f"pass_{pass_num:02d}.json").write_text("{}")
    merged_path = tmp_path / "merged.json"
    graph_path = tmp_path / "theme_emergence_graph.json"
    manifest_path = tmp_path / "final_manifest.json"
    merged_path.write_text(json.dumps({"NVDA": {"ticker": "NVDA"}, "MSFT": {"ticker": "MSFT"}}))

    monkeypatch.setattr(mod, "_raw_dir", lambda d: str(raw_dir))
    monkeypatch.setattr(mod, "_merged_path", lambda d: str(merged_path))
    monkeypatch.setattr(mod, "_theme_graph_path", lambda d: str(graph_path))
    monkeypatch.setattr(mod, "_final_manifest_path", lambda d: str(manifest_path))

    readiness = mod.get_readiness("2026-03-09")
    assert readiness["ready"] is False
    assert readiness["finalized"] is False

    manifest = mod.finalize_x_feed("2026-03-09")
    readiness = mod.get_readiness("2026-03-09")
    assert manifest["finalized"] is True
    assert readiness["ready"] is True
    assert readiness["missing_passes"] == []
    assert readiness["merged_symbol_count"] == 2


def test_load_recent_merged_carries_forward_unprocessed_recent_dates(tmp_path, monkeypatch):
    from tradingagents.dealflow.sources import x_feed_manual as mod

    def _merged(date_str: str) -> str:
        return str(tmp_path / "eval_results" / "x_feed" / date_str / "merged.json")

    monkeypatch.setattr(mod, "_merged_path", _merged)

    prior_path = tmp_path / "eval_results" / "x_feed" / "2026-03-06" / "merged.json"
    prior_path.parent.mkdir(parents=True, exist_ok=True)
    prior_path.write_text(json.dumps({"BE": {"ticker": "BE"}}))

    merged = mod.load_recent_merged(
        "2026-03-09",
        lookback_days=3,
        dealflow_base_dir=str(tmp_path / "eval_results" / "deal_flow"),
    )

    assert "BE" in merged
    assert merged["BE"]["x_feed_source_date"] == "2026-03-06"
    assert merged["BE"]["x_feed_carryforward_days"] == 3


def test_load_recent_merged_skips_prior_dates_when_dealflow_cycle_exists(tmp_path, monkeypatch):
    from tradingagents.dealflow.sources import x_feed_manual as mod

    def _merged(date_str: str) -> str:
        return str(tmp_path / "eval_results" / "x_feed" / date_str / "merged.json")

    monkeypatch.setattr(mod, "_merged_path", _merged)

    prior_path = tmp_path / "eval_results" / "x_feed" / "2026-03-06" / "merged.json"
    prior_path.parent.mkdir(parents=True, exist_ok=True)
    prior_path.write_text(json.dumps({"BE": {"ticker": "BE"}}))
    (tmp_path / "eval_results" / "deal_flow" / "2026-03-06").mkdir(parents=True, exist_ok=True)

    merged = mod.load_recent_merged(
        "2026-03-09",
        lookback_days=3,
        dealflow_base_dir=str(tmp_path / "eval_results" / "deal_flow"),
    )

    assert "BE" not in merged


def test_ingest_pass14_options_flow_only_still_ingests_tickers(tmp_path, monkeypatch):
    from tradingagents.dealflow.sources import x_feed_manual as mod

    monkeypatch.setattr(mod, "_merged_path", lambda d: str(tmp_path / "merged.json"))
    monkeypatch.setattr(mod, "_raw_dir", lambda d: str(tmp_path / "raw"))
    monkeypatch.setattr(
        mod,
        "write_akg",
        lambda entries, d, themes=None, options_flow=None, gex_regime=None: {"written": len(entries), "new": 0},
    )

    raw = json.dumps(
        {
            "trending": [],
            "options_flow": [
                {
                    "ticker": "BABA",
                    "flow_type": "sweep",
                    "direction": "calls",
                    "accounts_flagged": 3,
                    "detail": "@unusual_whales: $4.2M in BABA 200C June swept at ask",
                }
            ],
        }
    )
    result = mod.ingest_pass("2026-03-18", raw, 14)

    assert result["tickers_parsed"] == 1
    assert result["tickers_merged"] == 1
    assert result["akg_written"] == 1
    assert len(result["options_flow"]) == 1
    merged = mod.load_merged("2026-03-18")
    assert "BABA" in merged
    assert merged["BABA"]["source_pass_type"] == "options_flow"


def test_ingest_empty_pass_reports_existing_merged_total(tmp_path, monkeypatch):
    from tradingagents.dealflow.sources import x_feed_manual as mod

    monkeypatch.setattr(mod, "_merged_path", lambda d: str(tmp_path / "merged.json"))
    monkeypatch.setattr(mod, "_raw_dir", lambda d: str(tmp_path / "raw"))
    monkeypatch.setattr(
        mod,
        "write_akg",
        lambda entries, d, themes=None, options_flow=None, gex_regime=None: {"written": len(entries), "new": 0},
    )

    (tmp_path / "merged.json").write_text(json.dumps({"NVDA": {"ticker": "NVDA"}}))
    result = mod.ingest_pass("2026-03-18", json.dumps({"trending": [], "options_flow": []}), 14)

    assert result["tickers_parsed"] == 0
    assert result["tickers_merged"] == 1
    assert result["akg_written"] == 0


def test_theme_normalization_maps_raw_themes_and_catalyst_text():
    from tradingagents.dealflow.sources.x_feed_manual import parse_pass

    raw = json.dumps({"trending": [{
        "ticker": "MU",
        "buzz_rank": 1,
        "sentiment": "BULLISH",
        "velocity": "ACCELERATING",
        "catalyst": "@acct flags HBM and data center AI memory demand",
        "sector": "Technology",
        "theme_links": ["earnings", "hbm", "analyst_upgrade"],
    }]})

    row = parse_pass(raw, 1)[0]
    assert row["theme_links"] == ["ai_data_center_infrastructure"]
    assert row["catalyst_tags"] == ["earnings", "analyst_upgrade"]
    assert row["raw_theme_links"] == ["earnings", "hbm", "analyst_upgrade"]


def test_theme_graph_filters_noncanonical_one_ticker_themes():
    from tradingagents.dealflow.sources.x_feed_manual import build_theme_emergence_graph

    merged = {
        "ABC": {"ticker": "ABC", "theme_links": ["one_off_story"], "accounts_cited": ["@a"], "co_mentions": [], "evidence_count": 1},
        "MU": {"ticker": "MU", "theme_links": ["ai_data_center_infrastructure"], "accounts_cited": ["@b"], "co_mentions": [], "evidence_count": 1},
    }
    graph = build_theme_emergence_graph("2026-05-05", merged)
    assert "one_off_story" not in graph["themes"]
    assert "one_off_story" in graph["filtered_one_ticker_themes"]
    assert "ai_data_center_infrastructure" in graph["themes"]


def test_ingest_gex_only_pass_reports_existing_merged_total(tmp_path, monkeypatch):
    from tradingagents.dealflow.sources import x_feed_manual as mod

    monkeypatch.setattr(mod, "_merged_path", lambda d: str(tmp_path / "merged.json"))
    monkeypatch.setattr(mod, "_raw_dir", lambda d: str(tmp_path / "raw"))
    monkeypatch.setattr(
        mod,
        "write_akg",
        lambda entries, d, themes=None, options_flow=None, gex_regime=None: {"written": 99, "new": 0},
    )

    (tmp_path / "merged.json").write_text(json.dumps({"NVDA": {"ticker": "NVDA"}, "MU": {"ticker": "MU"}}))
    raw = json.dumps(
        {
            "gex_regime": {
                "net_gex": "NEUTRAL",
                "gex_magnitude": "low",
                "key_pin_strike": 0,
                "gamma_flip_strike": 0,
                "dix_reading": None,
                "dix_signal": "unknown",
                "vix_level": None,
                "vix_term_structure": "unknown",
                "regime_summary": "NO GEX DATA FOUND",
                "sources_cited": [],
                "data_freshness": "2026-03-18",
            }
        }
    )
    result = mod.ingest_pass("2026-03-18", raw, 15)

    assert result["tickers_parsed"] == 0
    assert result["tickers_merged"] == 2
    assert result["akg_written"] == 99
