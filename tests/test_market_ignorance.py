"""
Tests for S-056: Real Market Ignorance Scoring.

1. Ticker not in AKG → returns 1.0 immediately (no yfinance call)
2. 7-day cache hit → returns cached value without calling yfinance
3. Cache miss → calls yfinance, computes score, writes back to node
4. analyst_count=0, inst_pct=0.0, news=0 → score = 1.0 (fully invisible)
5. analyst_count=30, inst_pct=0.9, news=20 → score = 0.0 (fully known)
6. analyst_count=15, inst_pct=0.45, news=10 → score = 0.50 (midpoint, verify arithmetic)
7. yfinance raises exception → falls back to centrality proxy, does NOT raise
8. derive_dark_matter() uses compute_market_ignorance() (mock it, verify called per ticker)
9. _backfill_node_defaults() sets new fields to None on old nodes
"""

import datetime as dt
from unittest.mock import MagicMock, patch, call

import pytest

from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
from tradingagents.graph.market_ignorance import compute_market_ignorance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_empty_akg() -> AeternusKnowledgeGraph:
    """Return a fresh, in-memory AKG with no nodes (no disk I/O)."""
    return AeternusKnowledgeGraph()


def _make_akg_with_node(ticker: str, **node_fields) -> AeternusKnowledgeGraph:
    """Return an AKG with a single company node, with optional field overrides."""
    akg = _make_empty_akg()
    akg.add_node(ticker, node_type="company")
    for k, v in node_fields.items():
        akg._nodes[ticker][k] = v
    return akg


# ---------------------------------------------------------------------------
# Test 1: Ticker not in AKG → returns 1.0, no yfinance call
# ---------------------------------------------------------------------------

def test_unknown_ticker_returns_max_ignorance():
    """Ticker not in AKG._nodes → 1.0 immediately, no yfinance call."""
    akg = _make_empty_akg()
    with patch("yfinance.Ticker") as mock_yf:
        score = compute_market_ignorance("UNKNWN", akg)
    assert score == 1.0, f"Expected 1.0 for unknown ticker, got {score}"
    mock_yf.assert_not_called()


# ---------------------------------------------------------------------------
# Test 2: 7-day cache hit → returns cached value, no yfinance call
# ---------------------------------------------------------------------------

def test_cache_hit_returns_cached_without_yfinance():
    """If market_ignorance_cached_at is within 7 days, return cached score, skip yfinance."""
    today = dt.date.today().isoformat()
    akg = _make_akg_with_node(
        "AAPL",
        market_ignorance_score_real=0.42,
        market_ignorance_cached_at=today,  # fresh cache (age = 0 days)
    )
    with patch("yfinance.Ticker") as mock_yf:
        score = compute_market_ignorance("AAPL", akg)
    assert abs(score - 0.42) < 1e-9, f"Expected cached score 0.42, got {score}"
    mock_yf.assert_not_called()


def test_cache_6_days_old_returns_cached_without_yfinance():
    """Cache 6 days old (< 7) → still a cache hit."""
    six_days_ago = (dt.date.today() - dt.timedelta(days=6)).isoformat()
    akg = _make_akg_with_node(
        "MSFT",
        market_ignorance_score_real=0.25,
        market_ignorance_cached_at=six_days_ago,
    )
    with patch("yfinance.Ticker") as mock_yf:
        score = compute_market_ignorance("MSFT", akg)
    assert abs(score - 0.25) < 1e-9
    mock_yf.assert_not_called()


def test_cache_7_days_old_is_stale_and_calls_yfinance():
    """Cache exactly 7 days old (>= 7) → stale, yfinance is called."""
    seven_days_ago = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    akg = _make_akg_with_node(
        "NVDA",
        market_ignorance_score_real=0.99,
        market_ignorance_cached_at=seven_days_ago,
        news_count_30d=20,  # fully covered news too
    )
    mock_info = {
        "numberOfAnalystOpinions": 30,
        "heldPercentInstitutions": 0.9,
    }
    mock_ticker = MagicMock()
    mock_ticker.info = mock_info
    with patch("yfinance.Ticker", return_value=mock_ticker):
        score = compute_market_ignorance("NVDA", akg)
    # score should now be 0.0 (fully known), not the stale 0.99
    assert abs(score - 0.0) < 1e-4, f"Expected 0.0 after stale cache refresh, got {score}"


# ---------------------------------------------------------------------------
# Test 3: Cache miss → calls yfinance, computes score, writes back to node
# ---------------------------------------------------------------------------

def test_cache_miss_calls_yfinance_and_writes_back():
    """No cached value → yfinance called; result written to AKG node fields."""
    akg = _make_akg_with_node("TSLA", news_count_30d=5)
    mock_info = {
        "numberOfAnalystOpinions": 10,
        "heldPercentInstitutions": 0.45,
    }
    mock_ticker = MagicMock()
    mock_ticker.info = mock_info

    with patch("yfinance.Ticker", return_value=mock_ticker) as mock_yf:
        score = compute_market_ignorance("TSLA", akg)

    mock_yf.assert_called_once_with("TSLA")

    node = akg._nodes["TSLA"]
    assert node["market_ignorance_score_real"] == score
    assert node["analyst_count"] == 10
    assert abs(node["institutional_pct"] - 0.45) < 1e-9
    assert node["market_ignorance_cached_at"] == dt.date.today().isoformat()


# ---------------------------------------------------------------------------
# Test 4: analyst_count=0, inst_pct=0.0, news=0 → score = 1.0
# ---------------------------------------------------------------------------

def test_fully_invisible_company_scores_1():
    """0 analysts, 0% institutional, 0 news → score = 1.0."""
    akg = _make_akg_with_node("DARK", news_count_30d=0)
    mock_info = {
        "numberOfAnalystOpinions": 0,
        "heldPercentInstitutions": 0.0,
    }
    mock_ticker = MagicMock()
    mock_ticker.info = mock_info

    with patch("yfinance.Ticker", return_value=mock_ticker):
        score = compute_market_ignorance("DARK", akg)

    assert abs(score - 1.0) < 1e-4, f"Expected 1.0, got {score}"


# ---------------------------------------------------------------------------
# Test 5: analyst_count=30, inst_pct=0.9, news=20 → score = 0.0
# ---------------------------------------------------------------------------

def test_fully_known_company_scores_0():
    """30 analysts, 90% institutional, 20 news items → score = 0.0."""
    akg = _make_akg_with_node("WELL", news_count_30d=20)
    mock_info = {
        "numberOfAnalystOpinions": 30,
        "heldPercentInstitutions": 0.9,
    }
    mock_ticker = MagicMock()
    mock_ticker.info = mock_info

    with patch("yfinance.Ticker", return_value=mock_ticker):
        score = compute_market_ignorance("WELL", akg)

    assert abs(score - 0.0) < 1e-4, f"Expected 0.0, got {score}"


# ---------------------------------------------------------------------------
# Test 6: analyst_count=15, inst_pct=0.45, news=10 → score = 0.50 (midpoint)
# ---------------------------------------------------------------------------

def test_midpoint_score_arithmetic():
    """
    analyst_count=15 → analyst_ig = max(0, 1 - 15/30) = 0.50
    inst_pct=0.45    → inst_ig    = max(0, 1 - 0.45/0.90) = 0.50
    news_count=10    → news_ig    = max(0, 1 - min(10/20, 1.0)) = 0.50
    score = 0.50*0.50 + 0.35*0.50 + 0.15*0.50 = 0.50
    """
    akg = _make_akg_with_node("MIDT", news_count_30d=10)
    mock_info = {
        "numberOfAnalystOpinions": 15,
        "heldPercentInstitutions": 0.45,
    }
    mock_ticker = MagicMock()
    mock_ticker.info = mock_info

    with patch("yfinance.Ticker", return_value=mock_ticker):
        score = compute_market_ignorance("MIDT", akg)

    expected = round(0.50 * 0.50 + 0.35 * 0.50 + 0.15 * 0.50, 4)
    assert abs(score - expected) < 1e-4, (
        f"Expected {expected}, got {score}. "
        "Check formula: 0.50*analyst_ig + 0.35*inst_ig + 0.15*news_ig"
    )


# ---------------------------------------------------------------------------
# Test 7: yfinance raises exception → falls back to centrality proxy, no raise
# ---------------------------------------------------------------------------

def test_yfinance_exception_falls_back_to_centrality_proxy():
    """yfinance raises → fallback = max(0, 1 - min(centrality + times_surfaced/100, 1.0))."""
    akg = _make_akg_with_node("ERRR", centrality=0.6, times_surfaced=10)

    with patch("yfinance.Ticker", side_effect=Exception("Network error")):
        score = compute_market_ignorance("ERRR", akg)

    # Fallback formula: 1.0 - min(0.6 + 10/100, 1.0) = 1.0 - min(0.7, 1.0) = 0.3
    expected_fallback = max(0.0, 1.0 - min(0.6 + 10 / 100.0, 1.0))
    assert abs(score - expected_fallback) < 1e-9, (
        f"Expected fallback score {expected_fallback}, got {score}"
    )


def test_yfinance_exception_does_not_raise():
    """yfinance exception must be swallowed; compute_market_ignorance must return a float."""
    akg = _make_akg_with_node("SAFE")
    with patch("yfinance.Ticker", side_effect=RuntimeError("Timeout")):
        result = compute_market_ignorance("SAFE", akg)
    assert isinstance(result, float), f"Expected float, got {type(result)}"


# ---------------------------------------------------------------------------
# Test 8: derive_dark_matter() uses compute_market_ignorance() — called per ticker
# ---------------------------------------------------------------------------

def test_derive_dark_matter_calls_compute_market_ignorance(monkeypatch):
    """derive_dark_matter() must call compute_market_ignorance() for each derived ticker."""
    from tradingagents.graph.structural_forces import derive_dark_matter, CausalStep, StructuralForce
    import tradingagents.graph.market_ignorance as mi_module

    call_log = []

    def _mock_compute(ticker, akg):
        call_log.append(ticker)
        return 0.8  # arbitrary ignorance score

    monkeypatch.setattr(mi_module, "compute_market_ignorance", _mock_compute)

    force = StructuralForce(
        force_id="test_force",
        display_name="Test Force",
        description="desc",
        why_durable="durable",
        acceleration_rate="accelerating",
        horizon_months=12,
        conviction=0.9,
        must_be_true=["cond_a"],
        causal_chain=[
            CausalStep(1, "Step A", "sec_a", ["TICK1", "TICK2"], 0.9, "Reasoning A"),
            CausalStep(2, "Step B", "sec_b", ["TICK3"], 0.85, "Reasoning B"),
        ],
        anti_fragile_to=[],
        last_reviewed="2026-02-28",
    )

    akg = _make_empty_akg()
    candidates = derive_dark_matter(force, akg)

    # All 3 tickers from causal steps with necessity >= 0.7 must be in call_log
    assert "TICK1" in call_log, "compute_market_ignorance not called for TICK1"
    assert "TICK2" in call_log, "compute_market_ignorance not called for TICK2"
    assert "TICK3" in call_log, "compute_market_ignorance not called for TICK3"
    assert len(call_log) == 3, f"Expected 3 calls, got {len(call_log)}: {call_log}"

    # Candidates should use the mocked ignorance score (0.8)
    for c in candidates:
        assert abs(c.market_ignorance_score - 0.8) < 1e-9, (
            f"Expected ignorance=0.8 from mock for {c.ticker}, got {c.market_ignorance_score}"
        )


# ---------------------------------------------------------------------------
# Test 9: _backfill_node_defaults() sets new fields to None on old nodes
# ---------------------------------------------------------------------------

def test_backfill_sets_market_ignorance_fields_to_none():
    """
    _backfill_node_defaults() must initialize the 4 S-056 fields to None
    on nodes that were serialized before S-056 (i.e., missing the fields).
    """
    akg = _make_empty_akg()
    # Manually inject a node that is missing the S-056 fields (simulates old serialized node)
    akg._nodes["OLD"] = {
        "id": "OLD",
        "node_type": "company",
        "sector": None,
        "display_name": "Old Node",
        "signal_strength": 0.0,
        "centrality": 0.0,
        "times_surfaced": 0,
        "last_surfaced": None,
        "aeternus_score": None,
        "thesis_track_record": {"confirmed": 0, "invalidated": 0},
        "metadata": {},
        # Deliberately omitting all S-056 fields
    }

    # Run backfill
    akg._backfill_node_defaults()

    node = akg._nodes["OLD"]
    assert "market_ignorance_score_real" in node, "market_ignorance_score_real not backfilled"
    assert "analyst_count" in node, "analyst_count not backfilled"
    assert "institutional_pct" in node, "institutional_pct not backfilled"
    assert "market_ignorance_cached_at" in node, "market_ignorance_cached_at not backfilled"

    assert node["market_ignorance_score_real"] is None
    assert node["analyst_count"] is None
    assert node["institutional_pct"] is None
    assert node["market_ignorance_cached_at"] is None
