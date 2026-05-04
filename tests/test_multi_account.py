"""Tests for multi-account execution, V3 residual QQQ, and cc_eligible annotation."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_batch_summary(items, date="2026-03-01"):
    """Build a minimal batch summary dict."""
    return {
        "date": date,
        "run_id": "test-run-001",
        "items": items,
    }


def _make_item(symbol, score=75.0, confidence=4, recommendation="BUY", status="SUCCESS"):
    """Build a batch item dict."""
    return {
        "symbol": symbol,
        "aeternus_score": score,
        "confidence": confidence,
        "recommendation": recommendation,
        "status": status,
        "lane": "CORE",
        "research_playbook": "N/A",
        "dominant_signal_family": "unknown",
    }


def _mock_ref_price(symbol, analysis_date=""):
    """Return a fake reference price per symbol."""
    prices = {"AAPL": 175.0, "NVDA": 140.0, "XOM": 112.0, "QQQ": 500.0, "MSFT": 420.0, "TQQQ": 58.0}
    return prices.get(symbol, 100.0)


# ── V3 Residual QQQ Tests ────────────────────────────────────────────────────

class TestV3ResidualQQQ:
    """V3 residual: undeployed capital → QQQ BUY order."""

    @patch("tradingagents.graph.paper_execution._fetch_reference_price_from_market", side_effect=_mock_ref_price)
    def test_residual_creates_qqq_order(self, mock_price):
        from tradingagents.graph.paper_execution import build_portfolio_plan

        batch = _make_batch_summary([_make_item("AAPL", score=80)])
        plan = build_portfolio_plan(batch, capital_usd=100000, max_positions=5, enforce_whole_shares=True)

        orders = plan["orders"]
        qqq_orders = [o for o in orders if o["symbol"] == "QQQ"]
        assert len(qqq_orders) == 1, "Expected exactly one QQQ V3 residual order"

        qqq = qqq_orders[0]
        assert qqq["lane"] == "MOMENTUM"
        assert qqq["research_playbook"] == "V3_INDEX"
        assert qqq["dominant_signal_family"] == "v3_benchmark"
        assert qqq["side"] == "BUY"
        assert qqq["aeternus_score"] == 0.0
        assert qqq["confidence"] == 0

    @patch("tradingagents.graph.paper_execution._fetch_reference_price_from_market", side_effect=_mock_ref_price)
    def test_residual_math(self, mock_price):
        from tradingagents.graph.paper_execution import build_portfolio_plan

        batch = _make_batch_summary([_make_item("AAPL", score=80)])
        plan = build_portfolio_plan(batch, capital_usd=140000, max_positions=5, enforce_whole_shares=True)

        core_orders = [o for o in plan["orders"] if o["lane"] == "CORE"]
        qqq_orders = [o for o in plan["orders"] if o["symbol"] == "QQQ"]
        core_notional = sum(o["target_notional_usd"] for o in core_orders)
        qqq_notional = qqq_orders[0]["target_notional_usd"]

        # Core + QQQ should approximately equal total capital (within rounding from whole shares)
        total_deployed = core_notional + qqq_notional
        assert total_deployed <= 140000 + 1.0, "Deployed cannot exceed capital"
        assert plan["v3_residual_usd"] > 0

    @patch("tradingagents.graph.paper_execution._fetch_reference_price_from_market", side_effect=_mock_ref_price)
    def test_v3_residual_field_in_plan(self, mock_price):
        from tradingagents.graph.paper_execution import build_portfolio_plan

        batch = _make_batch_summary([_make_item("AAPL", score=80)])
        plan = build_portfolio_plan(batch, capital_usd=100000, max_positions=5)

        assert "v3_residual_usd" in plan
        assert "v3_ticker" in plan
        assert plan["v3_ticker"] == "QQQ"

    @patch("tradingagents.graph.paper_execution._fetch_reference_price_from_market", side_effect=_mock_ref_price)
    def test_zero_qualifying_stocks_full_qqq(self, mock_price):
        """0 qualifying stocks → entire capital goes to QQQ."""
        from tradingagents.graph.paper_execution import build_portfolio_plan

        batch = _make_batch_summary([_make_item("AAPL", score=40)])  # Below min_score
        plan = build_portfolio_plan(batch, capital_usd=100000, max_positions=5, enforce_whole_shares=True)

        core_orders = [o for o in plan["orders"] if o["lane"] == "CORE"]
        qqq_orders = [o for o in plan["orders"] if o["symbol"] == "QQQ"]

        assert len(core_orders) == 0
        assert len(qqq_orders) == 1
        assert qqq_orders[0]["target_quantity"] == 200.0  # 100000 / 500 = 200 shares

    @patch("tradingagents.graph.paper_execution._fetch_reference_price_from_market")
    def test_qqq_price_fetch_fails_no_v3_order(self, mock_price):
        """QQQ price fetch fails → no V3 order, plan still valid."""
        def _fail_qqq(symbol, analysis_date=""):
            if symbol == "QQQ":
                return None
            return _mock_ref_price(symbol, analysis_date)

        mock_price.side_effect = _fail_qqq
        from tradingagents.graph.paper_execution import build_portfolio_plan

        batch = _make_batch_summary([_make_item("AAPL", score=80)])
        plan = build_portfolio_plan(batch, capital_usd=100000, max_positions=5)

        qqq_orders = [o for o in plan["orders"] if o["symbol"] == "QQQ"]
        assert len(qqq_orders) == 0
        assert plan["v3_residual_usd"] > 0  # Residual calculated but no order


# ── cc_eligible Tests ─────────────────────────────────────────────────────────

class TestCCEligible:
    """cc_eligible annotation on orders: qty >= 100."""

    @patch("tradingagents.graph.paper_execution._fetch_reference_price_from_market", side_effect=_mock_ref_price)
    def test_all_orders_have_cc_eligible(self, mock_price):
        from tradingagents.graph.paper_execution import build_portfolio_plan

        batch = _make_batch_summary([_make_item("AAPL"), _make_item("NVDA")])
        plan = build_portfolio_plan(batch, capital_usd=100000, max_positions=5, enforce_whole_shares=True)

        for order in plan["orders"]:
            assert "cc_eligible" in order, f"Missing cc_eligible on {order['symbol']}"
            assert isinstance(order["cc_eligible"], bool)

    @patch("tradingagents.graph.paper_execution._fetch_reference_price_from_market", side_effect=_mock_ref_price)
    def test_large_qty_is_eligible(self, mock_price):
        from tradingagents.graph.paper_execution import build_portfolio_plan

        # With $100k and 1 stock at $175, we get ~285 shares (50k / 175 ≈ 285) → cc_eligible=true
        batch = _make_batch_summary([_make_item("AAPL", score=80)])
        plan = build_portfolio_plan(batch, capital_usd=100000, max_positions=5, enforce_whole_shares=True)

        aapl_orders = [o for o in plan["orders"] if o["symbol"] == "AAPL"]
        assert len(aapl_orders) == 1
        assert aapl_orders[0]["target_quantity"] >= 100
        assert aapl_orders[0]["cc_eligible"] is True

    @patch("tradingagents.graph.paper_execution._fetch_reference_price_from_market", side_effect=_mock_ref_price)
    def test_small_qty_not_eligible(self, mock_price):
        from tradingagents.graph.paper_execution import build_portfolio_plan

        # $5000 into MSFT at $420 → ~11 shares → not eligible
        batch = _make_batch_summary([
            _make_item("MSFT", score=80),
            _make_item("AAPL", score=78),
            _make_item("NVDA", score=76),
            _make_item("XOM", score=74),
        ])
        plan = build_portfolio_plan(batch, capital_usd=5000, max_positions=4, enforce_whole_shares=True)

        for order in plan["orders"]:
            if order["symbol"] == "MSFT":
                assert order["target_quantity"] < 100
                assert order["cc_eligible"] is False

    @patch("tradingagents.graph.paper_execution._fetch_reference_price_from_market", side_effect=_mock_ref_price)
    def test_qqq_v3_cc_eligible(self, mock_price):
        """QQQ V3 residual with enough quantity is cc_eligible."""
        from tradingagents.graph.paper_execution import build_portfolio_plan

        # 1 stock → large residual → QQQ gets 100+ shares
        batch = _make_batch_summary([_make_item("XOM", score=80)])
        plan = build_portfolio_plan(batch, capital_usd=100000, max_positions=5, enforce_whole_shares=True)

        qqq_orders = [o for o in plan["orders"] if o["symbol"] == "QQQ"]
        assert len(qqq_orders) == 1
        assert qqq_orders[0]["target_quantity"] >= 100
        assert qqq_orders[0]["cc_eligible"] is True


# ── Account Config Tests ──────────────────────────────────────────────────────

class TestAccountConfig:
    def test_load_accounts(self, tmp_path):
        from cli.commands.multi_account import load_accounts

        config = {
            "accounts": [
                {"name": "test", "label": "Test", "capital_usd": 50000, "env_prefix": "TEST"},
            ]
        }
        path = tmp_path / "accounts.json"
        path.write_text(json.dumps(config))

        accounts = load_accounts(path)
        assert len(accounts) == 1
        assert accounts[0]["name"] == "test"
        assert accounts[0]["capital_usd"] == 50000

    def test_load_accounts_missing_file(self, tmp_path):
        from cli.commands.multi_account import load_accounts

        with pytest.raises(FileNotFoundError):
            load_accounts(tmp_path / "nonexistent.json")

    def test_load_accounts_empty(self, tmp_path):
        from cli.commands.multi_account import load_accounts

        path = tmp_path / "accounts.json"
        path.write_text(json.dumps({"accounts": []}))

        with pytest.raises(ValueError, match="No accounts defined"):
            load_accounts(path)


# ── Credential Routing Tests ─────────────────────────────────────────────────

class TestCredentialRouting:
    def test_with_account_credentials_sets_env(self):
        from cli.commands.multi_account import _with_account_credentials

        os.environ["JOINT_APCA_API_KEY_ID"] = "joint-key"
        os.environ["JOINT_APCA_API_SECRET_KEY"] = "joint-secret"
        orig_key = os.environ.get("APCA_API_KEY_ID")
        orig_secret = os.environ.get("APCA_API_SECRET_KEY")

        try:
            with _with_account_credentials("JOINT"):
                assert os.environ["APCA_API_KEY_ID"] == "joint-key"
                assert os.environ["APCA_API_SECRET_KEY"] == "joint-secret"

            # After context, originals restored
            if orig_key is not None:
                assert os.environ.get("APCA_API_KEY_ID") == orig_key
            if orig_secret is not None:
                assert os.environ.get("APCA_API_SECRET_KEY") == orig_secret
        finally:
            os.environ.pop("JOINT_APCA_API_KEY_ID", None)
            os.environ.pop("JOINT_APCA_API_SECRET_KEY", None)

    def test_with_account_credentials_fallback_to_global(self):
        from cli.commands.multi_account import _with_account_credentials

        os.environ["APCA_API_KEY_ID"] = "global-key"
        os.environ["APCA_API_SECRET_KEY"] = "global-secret"
        # Remove any prefixed keys
        os.environ.pop("TEST_APCA_API_KEY_ID", None)
        os.environ.pop("TEST_APCA_API_SECRET_KEY", None)

        try:
            with _with_account_credentials("TEST"):
                # Falls back to global
                assert os.environ["APCA_API_KEY_ID"] == "global-key"
                assert os.environ["APCA_API_SECRET_KEY"] == "global-secret"
        finally:
            os.environ["APCA_API_KEY_ID"] = "global-key"
            os.environ["APCA_API_SECRET_KEY"] = "global-secret"


# ── Execution Path Tests ─────────────────────────────────────────────────────

class TestExecutionPaths:
    def test_account_execution_paths_alpaca(self):
        from cli.commands.multi_account import _resolve_account_execution_paths

        base, orders, positions = _resolve_account_execution_paths("joint", "alpaca-paper")
        assert base == "eval_results/joint_execution"
        assert orders == "eval_results/joint_execution/outbox.json"
        assert positions == "eval_results/joint_execution/positions_shadow.json"

    def test_account_execution_paths_paper(self):
        from cli.commands.multi_account import _resolve_account_execution_paths

        base, orders, positions = _resolve_account_execution_paths("ira", "paper")
        assert base == "eval_results/ira_execution"
        assert orders == "eval_results/ira_execution/orders.json"
        assert positions == "eval_results/ira_execution/positions.json"


# ── Build Account Plan Tests ──────────────────────────────────────────────────

class TestBuildAccountPlan:
    @patch("tradingagents.graph.paper_execution._fetch_reference_price_from_market", side_effect=_mock_ref_price)
    def test_build_account_plan_adds_metadata(self, mock_price):
        from cli.commands.multi_account import build_account_plan

        acct = {"name": "joint", "label": "Family Joint", "capital_usd": 140000, "max_positions": 5}
        batch = _make_batch_summary([_make_item("AAPL", score=80)])
        plan = build_account_plan(acct, batch)

        assert plan["account_name"] == "joint"
        assert plan["account_label"] == "Family Joint"
        assert plan["capital_usd"] == 140000

    @patch("tradingagents.graph.paper_execution._fetch_reference_price_from_market", side_effect=_mock_ref_price)
    def test_different_accounts_different_sizing(self, mock_price):
        from cli.commands.multi_account import build_account_plan

        batch = _make_batch_summary([_make_item("AAPL", score=80)])

        plan_joint = build_account_plan(
            {"name": "joint", "capital_usd": 140000, "max_positions": 5}, batch
        )
        plan_ira = build_account_plan(
            {"name": "ira", "capital_usd": 56000, "max_positions": 6}, batch
        )

        joint_aapl = [o for o in plan_joint["orders"] if o["symbol"] == "AAPL"][0]
        ira_aapl = [o for o in plan_ira["orders"] if o["symbol"] == "AAPL"][0]

        # Joint gets more shares (more capital)
        assert joint_aapl["target_quantity"] > ira_aapl["target_quantity"]


# ── TQQQ Instrument Swap Tests ──────────────────────────────────────────────

class TestTQQQInstrumentSwap:
    """V3 trade instrument config: QQQ → TQQQ for small accounts."""

    @patch("tradingagents.graph.paper_execution._fetch_reference_price_from_market", side_effect=_mock_ref_price)
    @patch("tradingagents.graph.paper_execution.DEFAULT_CONFIG", {
        **__import__("tradingagents.default_config", fromlist=["DEFAULT_CONFIG"]).DEFAULT_CONFIG,
        "v3_trade_instrument": "TQQQ",
    })
    def test_tqqq_order_created(self, mock_price):
        """With v3_trade_instrument=TQQQ, V3 residual uses TQQQ."""
        from tradingagents.graph.paper_execution import build_portfolio_plan

        batch = _make_batch_summary([_make_item("AAPL", score=80)])
        plan = build_portfolio_plan(batch, capital_usd=25000, max_positions=5, enforce_whole_shares=True)

        tqqq_orders = [o for o in plan["orders"] if o["symbol"] == "TQQQ"]
        assert len(tqqq_orders) == 1, "Expected exactly one TQQQ V3 residual order"

        tqqq = tqqq_orders[0]
        assert tqqq["lane"] == "MOMENTUM"
        assert tqqq["research_playbook"] == "V3_INDEX"
        assert tqqq["v3_underlying"] == "QQQ"
        assert tqqq["v3_effective_leverage"] == 2.1
        assert tqqq["side"] == "BUY"
        assert plan["v3_ticker"] == "TQQQ"
        assert plan["v3_underlying"] == "QQQ"
        assert plan["v3_effective_leverage"] == 2.1
        # Leverage-adjusted: only residual/2.1 deployed, rest is cash reserve
        assert plan["v3_cash_reserve_usd"] > 0

    @patch("tradingagents.graph.paper_execution._fetch_reference_price_from_market", side_effect=_mock_ref_price)
    @patch("tradingagents.graph.paper_execution.DEFAULT_CONFIG", {
        **__import__("tradingagents.default_config", fromlist=["DEFAULT_CONFIG"]).DEFAULT_CONFIG,
        "v3_trade_instrument": "TQQQ",
    })
    def test_tqqq_cc_eligible_small_account(self, mock_price):
        """TQQQ at $58: 25k/2.1 ≈ $11,905 deployed → 205 shares → cc_eligible=True."""
        from tradingagents.graph.paper_execution import build_portfolio_plan

        batch = _make_batch_summary([_make_item("AAPL", score=40)])  # Below min → all residual
        plan = build_portfolio_plan(batch, capital_usd=25000, max_positions=5, enforce_whole_shares=True)

        tqqq_orders = [o for o in plan["orders"] if o["symbol"] == "TQQQ"]
        assert len(tqqq_orders) == 1
        # 25000 / 2.1 ≈ 11905 → 11905 / 58 ≈ 205 shares
        assert tqqq_orders[0]["target_quantity"] >= 100
        assert tqqq_orders[0]["cc_eligible"] is True
