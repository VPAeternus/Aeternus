"""Tests for Insider Sweep Scout — discovery-first Form 4 EDGAR sweep."""

from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.dealflow.sources.insider_cluster import (
    ROLLING_STORE_PATH,
    _detect_clusters_from_store,
    _find_text,
    _is_10b5_1,
    _is_csuite_title,
    _load_rolling_store,
    _parse_form4_xml,
    _prune_transactions,
    _save_rolling_store,
    _sec_headers,
    _strip_ns,
    collect_insider_cluster_signals,
    scan_insider_sweep,
)


# ---------------------------------------------------------------------------
# Fixtures: synthetic Form 4 XML
# ---------------------------------------------------------------------------

_CEO_BUY_XML = """\
<?xml version="1.0"?>
<ownershipDocument>
  <issuer><issuerTradingSymbol>ACME</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>John Doe</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship>
      <officerTitle>CEO</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>5000</value></transactionShares>
        <transactionPricePerShare><value>42.50</value></transactionPricePerShare>
      </transactionAmounts>
      <transactionDate><value>2026-02-15</value></transactionDate>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""

_CFO_SELL_XML = """\
<?xml version="1.0"?>
<ownershipDocument>
  <issuer><issuerTradingSymbol>ACME</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Jane Smith</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship>
      <officerTitle>CFO</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>3000</value></transactionShares>
        <transactionPricePerShare><value>55.00</value></transactionPricePerShare>
      </transactionAmounts>
      <transactionDate><value>2026-02-16</value></transactionDate>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""

_VP_BUY_XML = """\
<?xml version="1.0"?>
<ownershipDocument>
  <issuer><issuerTradingSymbol>ACME</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Bob VP</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship>
      <officerTitle>Vice President</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>40.00</value></transactionPricePerShare>
      </transactionAmounts>
      <transactionDate><value>2026-02-15</value></transactionDate>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""

_10B5_1_EQUITY_SWAP_XML = """\
<?xml version="1.0"?>
<ownershipDocument>
  <issuer><issuerTradingSymbol>XSELL</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Plan Seller</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship>
      <officerTitle>CEO</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>10000</value></transactionShares>
        <transactionPricePerShare><value>100.00</value></transactionPricePerShare>
      </transactionAmounts>
      <transactionDate><value>2026-02-15</value></transactionDate>
      <equitySwapInvolved>1</equitySwapInvolved>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""

_10B5_1_FOOTNOTE_XML = """\
<?xml version="1.0"?>
<ownershipDocument>
  <issuer><issuerTradingSymbol>FPLN</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Footnote Seller</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship>
      <officerTitle>CFO</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>8000</value></transactionShares>
        <transactionPricePerShare><value>75.00</value></transactionPricePerShare>
      </transactionAmounts>
      <transactionDate><value>2026-02-15</value></transactionDate>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
  <footnotes>
    <footnote id="F1">Sold pursuant to a Rule 10b5-1 trading plan.</footnote>
  </footnotes>
</ownershipDocument>
"""


# ---------------------------------------------------------------------------
# Test: Rolling Store
# ---------------------------------------------------------------------------

class TestRollingStore:
    """Tests for _load_rolling_store, _save_rolling_store, _prune_transactions."""

    def test_load_missing_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "tradingagents.dealflow.sources.insider_cluster.ROLLING_STORE_PATH",
            str(tmp_path / "nonexistent.json"),
        )
        store = _load_rolling_store()
        assert store == {"last_sweep_date": "", "transactions": []}

    def test_save_and_load_roundtrip(self, monkeypatch, tmp_path):
        path = tmp_path / "store.json"
        monkeypatch.setattr(
            "tradingagents.dealflow.sources.insider_cluster.ROLLING_STORE_PATH",
            str(path),
        )
        store = {
            "last_sweep_date": "2026-02-15",
            "transactions": [{"ticker": "AAPL", "code": "P", "date": "2026-02-15"}],
        }
        _save_rolling_store(store)
        loaded = _load_rolling_store()
        assert loaded == store

    def test_prune_drops_old_transactions(self):
        today = dt.datetime.now().date()
        old_date = (today - dt.timedelta(days=40)).isoformat()
        recent_date = (today - dt.timedelta(days=5)).isoformat()
        txns = [
            {"ticker": "OLD", "date": old_date},
            {"ticker": "NEW", "date": recent_date},
        ]
        result = _prune_transactions(txns, window_days=30)
        assert len(result) == 1
        assert result[0]["ticker"] == "NEW"

    def test_prune_keeps_all_within_window(self):
        today = dt.datetime.now().date()
        txns = [{"ticker": "A", "date": (today - dt.timedelta(days=i)).isoformat()} for i in range(5)]
        result = _prune_transactions(txns, window_days=30)
        assert len(result) == 5


# ---------------------------------------------------------------------------
# Test: C-suite Title Filter
# ---------------------------------------------------------------------------

class TestCsuiteTitle:
    """Tests for _is_csuite_title."""

    @pytest.mark.parametrize("title", [
        "CEO", "CFO", "COO", "CTO", "CAO", "CRO", "CMO",
        "PRESIDENT", "CHAIRMAN", "CHAIR",
        "Chief Executive Officer", "Chief Financial Officer",
    ])
    def test_csuite_titles_match(self, title):
        assert _is_csuite_title(title) is True

    @pytest.mark.parametrize("title", [
        "Vice President", "Director", "Senior VP", "General Counsel",
        "Secretary", "Treasurer", "10% Owner", "",
    ])
    def test_non_csuite_titles_rejected(self, title):
        assert _is_csuite_title(title) is False


# ---------------------------------------------------------------------------
# Test: XML Parsing
# ---------------------------------------------------------------------------

class TestXMLParsing:
    """Tests for _parse_form4_xml."""

    def test_ceo_buy_parsed(self):
        txns = _parse_form4_xml(_CEO_BUY_XML)
        assert len(txns) == 1
        t = txns[0]
        assert t["ticker"] == "ACME"
        assert t["person"] == "John Doe"
        assert t["title"] == "CEO"
        assert t["code"] == "P"
        assert t["shares"] == 5000.0
        assert t["price"] == 42.50
        assert t["date"] == "2026-02-15"
        assert t["is_10b5_1"] is False

    def test_cfo_sell_parsed(self):
        txns = _parse_form4_xml(_CFO_SELL_XML)
        assert len(txns) == 1
        assert txns[0]["code"] == "S"
        assert txns[0]["shares"] == 3000.0

    def test_vp_filtered_out(self):
        txns = _parse_form4_xml(_VP_BUY_XML)
        assert txns == []

    def test_malformed_xml_returns_empty(self):
        assert _parse_form4_xml("not xml") == []

    def test_missing_ticker_returns_empty(self):
        xml = "<ownershipDocument><issuer></issuer></ownershipDocument>"
        assert _parse_form4_xml(xml) == []


# ---------------------------------------------------------------------------
# Test: 10b5-1 Detection
# ---------------------------------------------------------------------------

class Test10b51Detection:
    """Tests for 10b5-1 pre-scheduled plan filtering."""

    def test_equity_swap_flag_detected(self):
        txns = _parse_form4_xml(_10B5_1_EQUITY_SWAP_XML)
        assert len(txns) == 1
        assert txns[0]["is_10b5_1"] is True

    def test_footnote_10b5_1_detected(self):
        txns = _parse_form4_xml(_10B5_1_FOOTNOTE_XML)
        assert len(txns) == 1
        assert txns[0]["is_10b5_1"] is True

    def test_normal_buy_not_10b5_1(self):
        txns = _parse_form4_xml(_CEO_BUY_XML)
        assert txns[0]["is_10b5_1"] is False

    def test_normal_sell_not_10b5_1(self):
        txns = _parse_form4_xml(_CFO_SELL_XML)
        assert txns[0]["is_10b5_1"] is False

    def test_is_10b5_1_function_equity_swap(self):
        import xml.etree.ElementTree as ET
        node = ET.fromstring("<txn><equitySwapInvolved>1</equitySwapInvolved></txn>")
        assert _is_10b5_1(node, "") is True

    def test_is_10b5_1_function_footnote(self):
        import xml.etree.ElementTree as ET
        node = ET.fromstring("<txn></txn>")
        assert _is_10b5_1(node, "Sold under Rule 10b5-1 plan") is True


# ---------------------------------------------------------------------------
# Test: Cluster Detection
# ---------------------------------------------------------------------------

class TestClusterDetection:
    """Tests for _detect_clusters_from_store."""

    def _make_txns(self, ticker, code, persons):
        return [
            {"ticker": ticker, "code": code, "person": p, "value_usd": 100000.0}
            for p in persons
        ]

    def test_buy_cluster_2_insiders(self):
        txns = self._make_txns("AAPL", "P", ["CEO John", "CFO Jane"])
        clusters = _detect_clusters_from_store(txns, code_filter="P", min_insiders=2)
        assert len(clusters) == 1
        assert clusters[0]["ticker"] == "AAPL"
        assert clusters[0]["direction"] == "BULLISH"
        assert clusters[0]["score"] == 72.0

    def test_buy_cluster_3_insiders(self):
        txns = self._make_txns("MSFT", "P", ["CEO", "CFO", "COO"])
        clusters = _detect_clusters_from_store(txns, code_filter="P", min_insiders=2)
        assert clusters[0]["score"] == 80.0

    def test_buy_cluster_4_insiders(self):
        txns = self._make_txns("GOOG", "P", ["CEO", "CFO", "COO", "CTO"])
        clusters = _detect_clusters_from_store(txns, code_filter="P", min_insiders=2)
        assert clusters[0]["score"] == 88.0

    def test_sell_cluster_3_insiders(self):
        txns = self._make_txns("TSLA", "S", ["CEO", "CFO", "COO"])
        clusters = _detect_clusters_from_store(txns, code_filter="S", min_insiders=3)
        assert len(clusters) == 1
        assert clusters[0]["direction"] == "BEARISH"
        assert clusters[0]["score"] == 65.0

    def test_sell_cluster_4_insiders(self):
        txns = self._make_txns("TSLA", "S", ["CEO", "CFO", "COO", "CTO"])
        clusters = _detect_clusters_from_store(txns, code_filter="S", min_insiders=3)
        assert clusters[0]["score"] == 72.0

    def test_sell_cluster_5_insiders(self):
        txns = self._make_txns("TSLA", "S", ["CEO", "CFO", "COO", "CTO", "CMO"])
        clusters = _detect_clusters_from_store(txns, code_filter="S", min_insiders=3)
        assert clusters[0]["score"] == 80.0

    def test_2_sellers_no_cluster(self):
        txns = self._make_txns("TSLA", "S", ["CEO", "CFO"])
        clusters = _detect_clusters_from_store(txns, code_filter="S", min_insiders=3)
        assert clusters == []

    def test_total_value_summed(self):
        txns = [
            {"ticker": "XYZ", "code": "P", "person": "CEO", "value_usd": 50000},
            {"ticker": "XYZ", "code": "P", "person": "CFO", "value_usd": 75000},
        ]
        clusters = _detect_clusters_from_store(txns, code_filter="P", min_insiders=2)
        assert clusters[0]["total_value_usd"] == 125000.0


# ---------------------------------------------------------------------------
# Test: Sweep Dry Run
# ---------------------------------------------------------------------------

class TestSweepDryRun:
    """Tests for scan_insider_sweep with mocked HTTP."""

    def test_disabled_returns_skipped(self):
        result = scan_insider_sweep(
            config={"dealflow_insider_cluster_enabled": False},
            sweep_date="2026-02-15",
        )
        assert result.get("skipped") is True
        assert result.get("reason") == "disabled"

    def test_already_swept_skips(self, monkeypatch, tmp_path):
        store_path = tmp_path / "store.json"
        store_path.write_text(json.dumps({
            "last_sweep_date": "2026-02-15",
            "transactions": [{"ticker": "X", "code": "P", "date": "2026-02-15"}],
        }))
        monkeypatch.setattr(
            "tradingagents.dealflow.sources.insider_cluster.ROLLING_STORE_PATH",
            str(store_path),
        )
        result = scan_insider_sweep(sweep_date="2026-02-15", config={})
        assert result.get("skipped") is True
        assert result.get("reason") == "already_swept_today"

    def test_dry_run_no_file_written(self, monkeypatch, tmp_path):
        store_path = tmp_path / "store.json"
        monkeypatch.setattr(
            "tradingagents.dealflow.sources.insider_cluster.ROLLING_STORE_PATH",
            str(store_path),
        )
        # Mock HTTP to return empty hits
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"hits": {"total": {"value": 0}, "hits": []}}
        mock_resp.raise_for_status = MagicMock()
        with patch("tradingagents.dealflow.sources.insider_cluster.requests.get", return_value=mock_resp):
            result = scan_insider_sweep(
                sweep_date="2026-02-15",
                dry_run=True,
                config={"dealflow_edgar_sleep_seconds": 0},
            )
        assert not store_path.exists()
        assert result["new_transactions"] == 0


# ---------------------------------------------------------------------------
# Test: Connector from Store
# ---------------------------------------------------------------------------

class TestConnectorFromStore:
    """Tests for collect_insider_cluster_signals reading from rolling store."""

    def _make_universe(self, symbols):
        return [{"symbol": s} for s in symbols]

    def test_buy_cluster_emits_bullish(self, monkeypatch, tmp_path):
        store_path = tmp_path / "store.json"
        store_path.write_text(json.dumps({
            "last_sweep_date": "2026-02-15",
            "transactions": [
                {"ticker": "AAPL", "code": "P", "person": "CEO", "value_usd": 100000, "date": "2026-02-15"},
                {"ticker": "AAPL", "code": "P", "person": "CFO", "value_usd": 200000, "date": "2026-02-15"},
            ],
        }))
        monkeypatch.setattr(
            "tradingagents.dealflow.sources.insider_cluster.ROLLING_STORE_PATH",
            str(store_path),
        )
        signals = collect_insider_cluster_signals(
            universe=self._make_universe(["AAPL", "MSFT"]),
            config={},
        )
        assert len(signals) == 1
        s = signals[0]
        assert s["symbol"] == "AAPL"
        assert s["direction"] == "BULLISH"
        assert s["signal_family"] == "insider_cluster"
        assert s["total_value_usd"] == 300000.0

    def test_sell_cluster_emits_bearish(self, monkeypatch, tmp_path):
        store_path = tmp_path / "store.json"
        store_path.write_text(json.dumps({
            "last_sweep_date": "2026-02-16",
            "transactions": [
                {"ticker": "TSLA", "code": "S", "person": "CEO", "value_usd": 50000, "date": "2026-02-16"},
                {"ticker": "TSLA", "code": "S", "person": "CFO", "value_usd": 60000, "date": "2026-02-16"},
                {"ticker": "TSLA", "code": "S", "person": "COO", "value_usd": 70000, "date": "2026-02-16"},
            ],
        }))
        monkeypatch.setattr(
            "tradingagents.dealflow.sources.insider_cluster.ROLLING_STORE_PATH",
            str(store_path),
        )
        signals = collect_insider_cluster_signals(
            universe=self._make_universe(["TSLA"]),
            config={},
        )
        assert len(signals) == 1
        assert signals[0]["direction"] == "BEARISH"

    def test_disabled_returns_empty(self):
        signals = collect_insider_cluster_signals(
            universe=[{"symbol": "AAPL"}],
            config={"dealflow_insider_cluster_enabled": False},
        )
        assert signals == []

    def test_empty_store_returns_empty(self, monkeypatch, tmp_path):
        store_path = tmp_path / "store.json"
        monkeypatch.setattr(
            "tradingagents.dealflow.sources.insider_cluster.ROLLING_STORE_PATH",
            str(store_path),
        )
        signals = collect_insider_cluster_signals(
            universe=[{"symbol": "AAPL"}],
            config={},
        )
        assert signals == []

    def test_filters_to_universe_only(self, monkeypatch, tmp_path):
        store_path = tmp_path / "store.json"
        store_path.write_text(json.dumps({
            "last_sweep_date": "2026-02-15",
            "transactions": [
                {"ticker": "AAPL", "code": "P", "person": "CEO", "value_usd": 100000, "date": "2026-02-15"},
                {"ticker": "AAPL", "code": "P", "person": "CFO", "value_usd": 200000, "date": "2026-02-15"},
                {"ticker": "XXXX", "code": "P", "person": "CEO", "value_usd": 100000, "date": "2026-02-15"},
                {"ticker": "XXXX", "code": "P", "person": "CFO", "value_usd": 100000, "date": "2026-02-15"},
            ],
        }))
        monkeypatch.setattr(
            "tradingagents.dealflow.sources.insider_cluster.ROLLING_STORE_PATH",
            str(store_path),
        )
        # Only AAPL in universe, not XXXX
        signals = collect_insider_cluster_signals(
            universe=self._make_universe(["AAPL"]),
            config={},
        )
        assert len(signals) == 1
        assert signals[0]["symbol"] == "AAPL"


# ---------------------------------------------------------------------------
# Test: Helper functions
# ---------------------------------------------------------------------------

class TestHelpers:
    """Tests for small utility functions."""

    def test_strip_ns_with_namespace(self):
        assert _strip_ns("{http://example.com}tag") == "tag"

    def test_strip_ns_without_namespace(self):
        assert _strip_ns("tag") == "tag"

    def test_sec_headers_default(self):
        h = _sec_headers(None)
        assert "AeternusAgentsAG" in h["User-Agent"]

    def test_sec_headers_custom(self):
        h = _sec_headers({"dealflow_sec_user_agent": "Custom/1.0"})
        assert h["User-Agent"] == "Custom/1.0"

    def test_find_text_with_match(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring("<root><child>hello</child></root>")
        assert _find_text(root, "child") == "hello"

    def test_find_text_no_match(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring("<root><child>hello</child></root>")
        assert _find_text(root, "missing") == ""
