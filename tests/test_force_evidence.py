"""Tests for _gather_force_evidence() in structural_forces.py.

Validates that forward-looking evidence (options, insider, macro) is gathered
and formatted correctly for force acceleration prompts.

All tests use monkeypatch — no live API calls or market data.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tradingagents.graph.structural_forces import (
    CausalStep,
    StructuralForce,
    _gather_force_evidence,
    update_force_acceleration,
)


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def _make_force(
    force_id: str = "test_force",
    tickers: list = None,
    necessity: float = 0.9,
) -> StructuralForce:
    if tickers is None:
        tickers = ["NVDA", "MU"]
    return StructuralForce(
        force_id=force_id,
        display_name=f"Test Force {force_id}",
        description="Test description",
        why_durable="Test durability",
        acceleration_rate="accelerating",
        horizon_months=24,
        conviction=0.9,
        must_be_true=["condition_a"],
        causal_chain=[
            CausalStep(1, "Step A", "sector_a", tickers, necessity, "Required for A"),
        ],
        anti_fragile_to=["factor_x"],
        last_reviewed="2026-02-28",
    )


# ---------------------------------------------------------------------------
# Test 1: _gather_force_evidence returns string with options data
# ---------------------------------------------------------------------------

def test_gather_evidence_includes_options_snapshot():
    """Evidence string includes [FORWARD] Options when options_engine returns data."""
    force = _make_force(tickers=["NVDA"])

    mock_opts = {
        "atm_iv": 0.45,
        "iv_skew": -0.120,
        "put_call_ratio": 0.85,
        "fear_greed": "GREED",
    }

    with patch("tradingagents.agents.utils.options_engine.build_options_snapshot",
               return_value=mock_opts):
        with patch("yfinance.Ticker", side_effect=Exception("no network")):
            evidence = _gather_force_evidence(force)

    assert "[FORWARD] Options:" in evidence
    assert "ATM IV=45.0%" in evidence
    assert "P/C=0.85" in evidence
    assert "mood=GREED" in evidence


# ---------------------------------------------------------------------------
# Test 2: _gather_force_evidence returns string with insider data
# ---------------------------------------------------------------------------

def test_gather_evidence_includes_insider_transactions():
    """Evidence string includes [FORWARD] Insider when yfinance returns transactions."""
    import pandas as pd
    import datetime as dt

    force = _make_force(tickers=["NVDA"])

    recent_date = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=10)).strftime("%Y-%m-%d")
    txn_df = pd.DataFrame([
        {"Text": "Purchase at price $120.00", "Start Date": recent_date, "Insider": "CEO", "Position": "CEO"},
        {"Text": "Purchase at price $118.00", "Start Date": recent_date, "Insider": "CFO", "Position": "CFO"},
        {"Text": "Sale at price $125.00", "Start Date": recent_date, "Insider": "CTO", "Position": "CTO"},
    ])

    mock_ticker = MagicMock()
    mock_ticker.insider_transactions = txn_df
    mock_ticker.history.return_value = pd.DataFrame()  # empty history

    with patch("tradingagents.agents.utils.options_engine.build_options_snapshot", return_value=None):
        with patch("yfinance.Ticker", return_value=mock_ticker):
            evidence = _gather_force_evidence(force)

    assert "[FORWARD] Insider 90d: 2 buys, 1 sells" in evidence


# ---------------------------------------------------------------------------
# Test 3: _gather_force_evidence returns string with 30d return
# ---------------------------------------------------------------------------

def test_gather_evidence_includes_price_return():
    """Evidence string includes [CONTEXT — ALREADY PRICED] with 30d return."""
    import pandas as pd

    force = _make_force(tickers=["MU"])

    mock_hist = pd.DataFrame({"Close": [100.0, 110.0]})
    mock_ticker = MagicMock()
    mock_ticker.insider_transactions = None
    mock_ticker.history.return_value = mock_hist

    with patch("tradingagents.agents.utils.options_engine.build_options_snapshot", return_value=None):
        with patch("yfinance.Ticker", return_value=mock_ticker):
            evidence = _gather_force_evidence(force)

    assert "[CONTEXT — ALREADY PRICED] 30d return: +10.0%" in evidence


# ---------------------------------------------------------------------------
# Test 4: _gather_force_evidence includes macro data
# ---------------------------------------------------------------------------

def test_gather_evidence_includes_macro_snapshot():
    """Evidence string includes [FORWARD] Macro when macro_engine returns data."""
    force = _make_force(tickers=["NVDA"])

    mock_macro = {
        "regime": "RISK_ON",
        "indicators": {
            "vix": 15.2,
            "credit_spread": 1.05,
            "yield_curve_2s10s": 0.45,
        },
    }

    with patch("tradingagents.agents.utils.options_engine.build_options_snapshot", return_value=None):
        with patch("yfinance.Ticker", side_effect=Exception("no network")):
            with patch("tradingagents.agents.utils.macro_engine.build_macro_snapshot",
                       return_value=mock_macro):
                evidence = _gather_force_evidence(force)

    assert "[FORWARD] Macro:" in evidence
    assert "regime=RISK_ON" in evidence
    assert "VIX=15.2" in evidence


# ---------------------------------------------------------------------------
# Test 5: _gather_force_evidence never raises even if all data fails
# ---------------------------------------------------------------------------

def test_gather_evidence_graceful_degradation():
    """_gather_force_evidence returns empty string when all data sources fail."""
    force = _make_force(tickers=["FAKE"])

    with patch("tradingagents.agents.utils.options_engine.build_options_snapshot",
               side_effect=Exception("boom")):
        with patch("yfinance.Ticker", side_effect=Exception("no network")):
            with patch("tradingagents.agents.utils.macro_engine.build_macro_snapshot",
                       side_effect=Exception("boom")):
                evidence = _gather_force_evidence(force)

    assert isinstance(evidence, str)
    # Should be empty or minimal — no crash
    # (May contain ticker headers but no evidence lines)


# ---------------------------------------------------------------------------
# Test 6: _gather_force_evidence caps at 5 tickers
# ---------------------------------------------------------------------------

def test_gather_evidence_caps_at_five_tickers():
    """Only top 5 tickers by necessity_score appear in evidence."""
    force = StructuralForce(
        force_id="many_tickers",
        display_name="Many Tickers Force",
        description="Test",
        why_durable="Test",
        acceleration_rate="stable",
        horizon_months=12,
        conviction=0.9,
        must_be_true=["test"],
        causal_chain=[
            CausalStep(1, "Step", "sec", ["T1", "T2", "T3"], 0.95, "High"),
            CausalStep(2, "Step", "sec", ["T4", "T5", "T6", "T7"], 0.80, "Mid"),
        ],
        anti_fragile_to=[],
        last_reviewed="2026-02-28",
    )

    with patch("tradingagents.agents.utils.options_engine.build_options_snapshot", return_value=None):
        with patch("yfinance.Ticker", side_effect=Exception("no network")):
            with patch("tradingagents.agents.utils.macro_engine.build_macro_snapshot", return_value=None):
                evidence = _gather_force_evidence(force)

    # Count ticker headers — should be at most 5
    header_count = evidence.count("### T")
    assert header_count <= 5


# ---------------------------------------------------------------------------
# Test 7: update_force_acceleration prompt includes evidence block
# ---------------------------------------------------------------------------

def test_update_acceleration_prompt_includes_evidence():
    """update_force_acceleration() passes evidence to the LLM prompt."""
    import json

    captured_prompts = []

    def _mock_quick_complete(prompt, max_tokens=250, temperature=0.2):
        captured_prompts.append(prompt)
        return json.dumps({
            "acceleration_rate": "accelerating",
            "conviction": 0.9,
            "rationale": "Strong forward signals",
        })

    with patch("tradingagents.graph.structural_forces._gather_force_evidence",
               return_value="[FORWARD] Options: ATM IV=45.0%"):
        with patch("tradingagents.dataflows.llm_quick.quick_complete",
                   side_effect=_mock_quick_complete):
            result = update_force_acceleration("ai_compute_demand")

    assert result is not None
    assert result["acceleration_rate"] == "accelerating"

    # Verify the prompt contains the evidence block and forward signal instruction
    assert len(captured_prompts) == 1
    prompt = captured_prompts[0]
    assert "[FORWARD] Options: ATM IV=45.0%" in prompt
    assert "Focus on FORWARD signals" in prompt
    assert "ALREADY PRICED" in prompt


# ---------------------------------------------------------------------------
# Test 8: update_force_acceleration uses max_tokens=250 (increased from 150)
# ---------------------------------------------------------------------------

def test_update_acceleration_uses_increased_max_tokens():
    """update_force_acceleration() calls quick_complete with max_tokens=250."""
    import json

    captured_kwargs = []

    def _mock_quick_complete(prompt, max_tokens=200, temperature=0.2):
        captured_kwargs.append({"max_tokens": max_tokens, "temperature": temperature})
        return json.dumps({
            "acceleration_rate": "stable",
            "conviction": 0.85,
            "rationale": "Mixed signals",
        })

    with patch("tradingagents.graph.structural_forces._gather_force_evidence", return_value=""):
        with patch("tradingagents.dataflows.llm_quick.quick_complete",
                   side_effect=_mock_quick_complete):
            update_force_acceleration("ai_compute_demand")

    assert len(captured_kwargs) == 1
    assert captured_kwargs[0]["max_tokens"] == 250
