"""Tests for X Feed pass 15 — GEX regime parsing and ingestion."""

import json
import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from tradingagents.dealflow.sources.x_feed_manual import (
    generate_prompts,
    parse_pass,
    ingest_pass,
    PASS_CONFIGS,
)


SAMPLE_GEX_JSON = json.dumps({
    "gex_regime": {
        "net_gex": "LONG_GAMMA",
        "gex_magnitude": "elevated",
        "key_pin_strike": 570,
        "gamma_flip_strike": 555,
        "dix_reading": 0.45,
        "dix_signal": "accumulation",
        "vix_level": 18.5,
        "vix_term_structure": "contango",
        "regime_summary": "Dealers long gamma above 555.",
        "sources_cited": ["@spotgamma", "@SqueezeMetrics"],
        "data_freshness": "2026-03-07",
    }
})


class TestPassConfig:
    def test_pass_15_exists(self):
        assert any(c["pass"] == 15 for c in PASS_CONFIGS)

    def test_pass_15_is_gex_regime(self):
        cfg = [c for c in PASS_CONFIGS if c["pass"] == 15][0]
        assert cfg["type"] == "gex_regime"
        assert "GEX" in cfg["label"]


class TestGeneratePrompts:
    def test_pass_15_prompt_generated(self):
        prompts = generate_prompts()
        pass_15 = [p for p in prompts if p[0] == 15]
        assert len(pass_15) == 1
        _, label, text = pass_15[0]
        assert "GEX" in label
        assert "SqueezeMetrics" in text
        assert "gex_regime" in text


class TestParseGex:
    def test_parse_plain_json(self):
        """Pass 15 doesn't produce trending entries (it's a regime signal)."""
        entries = parse_pass(SAMPLE_GEX_JSON, pass_num=15)
        # GEX pass has no trending tickers — entries should be empty
        assert entries == []

    def test_parse_fenced_json(self):
        fenced = f"```json\n{SAMPLE_GEX_JSON}\n```"
        entries = parse_pass(fenced, pass_num=15)
        assert entries == []


class TestIngestGex:
    def test_dry_run_extracts_gex_regime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("tradingagents.dealflow.sources.x_feed_manual._raw_dir", return_value=tmpdir):
                with patch("tradingagents.dealflow.sources.x_feed_manual._merged_path",
                           return_value=os.path.join(tmpdir, "merged.json")):
                    result = ingest_pass(
                        as_of_date="2026-03-07",
                        raw_text=SAMPLE_GEX_JSON,
                        pass_num=15,
                        dry_run=True,
                    )

        assert result["pass_num"] == 15
        assert result["dry_run"] is True
        gex = result.get("gex_regime", {})
        assert gex.get("net_gex") == "LONG_GAMMA"
        assert gex.get("gex_magnitude") == "elevated"
        assert gex.get("key_pin_strike") == 570
        assert gex.get("gamma_flip_strike") == 555
        assert gex.get("dix_reading") == 0.45
        assert gex.get("dix_signal") == "accumulation"

    def test_dry_run_fenced_json(self):
        fenced = f"```json\n{SAMPLE_GEX_JSON}\n```"
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("tradingagents.dealflow.sources.x_feed_manual._raw_dir", return_value=tmpdir):
                with patch("tradingagents.dealflow.sources.x_feed_manual._merged_path",
                           return_value=os.path.join(tmpdir, "merged.json")):
                    result = ingest_pass(
                        as_of_date="2026-03-07",
                        raw_text=fenced,
                        pass_num=15,
                        dry_run=True,
                    )
        gex = result.get("gex_regime", {})
        assert gex.get("net_gex") == "LONG_GAMMA"

    def test_non_gex_pass_has_empty_gex(self):
        """A sector pass (pass 1) should not populate gex_regime."""
        sector_json = json.dumps({
            "trending": [
                {"ticker": "NVDA", "buzz_rank": 1, "sentiment": "BULLISH",
                 "velocity": "ACCELERATING", "catalyst": "AI demand", "sector": "Technology"}
            ]
        })
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("tradingagents.dealflow.sources.x_feed_manual._raw_dir", return_value=tmpdir):
                with patch("tradingagents.dealflow.sources.x_feed_manual._merged_path",
                           return_value=os.path.join(tmpdir, "merged.json")):
                    result = ingest_pass(
                        as_of_date="2026-03-07",
                        raw_text=sector_json,
                        pass_num=1,
                        dry_run=True,
                    )
        assert result.get("gex_regime") == {}
