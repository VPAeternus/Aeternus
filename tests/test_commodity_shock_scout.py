"""Tests for tradingagents/dealflow/sources/commodity_shock_scout.py (S-083)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tradingagents.dealflow.sources.commodity_shock_scout import (
    CLUSTERS,
    ClusterAlert,
    ClusterDef,
    _compute_instrument_anomaly,
    _evaluate_cluster,
    scan_commodity_shock_clusters,
)


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def _make_price_df(tickers_returns: dict[str, list[float]]) -> pd.DataFrame:
    """
    Build a mock price DataFrame with MultiIndex columns (Close, ticker).
    tickers_returns: {ticker: [list of close prices, oldest first]}
    """
    frames = {}
    for ticker, prices in tickers_returns.items():
        frames[("Close", ticker)] = prices
    df = pd.DataFrame(frames)
    df.columns = pd.MultiIndex.from_tuples(df.columns, names=["Price", "Ticker"])
    return df


def _make_volume_df(tickers_volumes: dict[str, list[float]]) -> pd.DataFrame:
    """
    Build a mock volume DataFrame with MultiIndex columns (Volume, ticker).
    """
    frames = {}
    for ticker, vols in tickers_volumes.items():
        frames[("Volume", ticker)] = vols
    df = pd.DataFrame(frames)
    df.columns = pd.MultiIndex.from_tuples(df.columns, names=["Price", "Ticker"])
    return df


def _high_volume_anomaly(n: int = 45, baseline_days: int = 30, lookback_days: int = 10) -> list[float]:
    """Return volume list where recent avg is 3 std above baseline → Z > 1.5."""
    # baseline: 30 values at 1_000_000
    # recent: 10 values at 4_000_000 (far above baseline)
    baseline = [1_000_000.0] * baseline_days
    recent = [4_000_000.0] * lookback_days
    return baseline + recent


def _normal_volume(n: int = 45, baseline_days: int = 30, lookback_days: int = 10) -> list[float]:
    """Return flat volume list — no anomaly."""
    return [1_000_000.0] * (baseline_days + lookback_days)


def _rising_prices(start: float = 100.0, n: int = 45, pct_rise: float = 0.01) -> list[float]:
    """Return prices rising at pct_rise per bar."""
    prices = []
    v = start
    for _ in range(n):
        prices.append(round(v, 4))
        v *= (1 + pct_rise)
    return prices


def _flat_prices(start: float = 100.0, n: int = 45) -> list[float]:
    return [start] * n


def _falling_prices(start: float = 100.0, n: int = 45, pct_fall: float = 0.01) -> list[float]:
    prices = []
    v = start
    for _ in range(n):
        prices.append(round(v, 4))
        v *= (1 - pct_fall)
    return prices


# ---------------------------------------------------------------------------
# Test 1: OIL_DISRUPTION fires on tanker anomaly with inverse confirmation
# ---------------------------------------------------------------------------

def test_oil_disruption_fires_on_tanker_anomaly():
    """DHT and NAT anomalous (volume spike) + UAL negative → OIL_DISRUPTION alert fires."""
    n = 40

    # Primary tankers: high volume + positive price momentum
    price_data = {
        "DHT": _rising_prices(n=n, pct_rise=0.015),
        "NAT": _rising_prices(n=n, pct_rise=0.012),
        "FRO": _flat_prices(n=n),
        "USO": _flat_prices(n=n),
    }
    volume_data = {
        "DHT": _high_volume_anomaly(baseline_days=30, lookback_days=10),
        "NAT": _high_volume_anomaly(baseline_days=30, lookback_days=10),
        "FRO": _normal_volume(baseline_days=30, lookback_days=10),
        "USO": _normal_volume(baseline_days=30, lookback_days=10),
        # Confirmation
        "TK": _normal_volume(baseline_days=30, lookback_days=10),
        "STNG": _normal_volume(baseline_days=30, lookback_days=10),
        # Inverse: UAL falling
        "UAL": _falling_prices(n=n, pct_fall=0.015),
        "DAL": _flat_prices(n=n),
    }
    # Add flat prices for confirmation + inverse
    for t in ["TK", "STNG", "UAL", "DAL"]:
        if t not in price_data:
            price_data[t] = _flat_prices(n=n)
    price_data["UAL"] = _falling_prices(n=n, pct_fall=0.015)

    price_df = _make_price_df(price_data)
    volume_df = _make_volume_df(volume_data)

    # Compute anomalies manually
    anomalies = {}
    for ticker in list(price_data.keys()):
        result = _compute_instrument_anomaly(
            ticker=ticker,
            price_df=price_df,
            volume_df=volume_df,
            baseline_days=30,
            lookback_days=10,
        )
        if result:
            anomalies[ticker] = result

    cluster_def = CLUSTERS["OIL_DISRUPTION"]
    alert = _evaluate_cluster("OIL_DISRUPTION", cluster_def, anomalies)

    assert alert is not None, "Expected OIL_DISRUPTION alert to fire"
    assert alert.cluster_name == "OIL_DISRUPTION"
    assert "DHT" in alert.triggered_instruments
    assert "NAT" in alert.triggered_instruments
    assert alert.direction == "POSITIVE"
    assert 0.0 < alert.confidence <= 1.0


# ---------------------------------------------------------------------------
# Test 2: Only 1 primary anomalous → no alert
# ---------------------------------------------------------------------------

def test_cluster_requires_2_primaries():
    """Only DHT anomalous (1 primary) → no alert for OIL_DISRUPTION."""
    n = 40

    price_data = {
        "DHT": _rising_prices(n=n, pct_rise=0.015),
        "NAT": _flat_prices(n=n),
        "FRO": _flat_prices(n=n),
        "USO": _flat_prices(n=n),
        "TK": _flat_prices(n=n),
        "STNG": _flat_prices(n=n),
        "UAL": _falling_prices(n=n, pct_fall=0.02),
        "DAL": _flat_prices(n=n),
    }
    volume_data = {t: _normal_volume(baseline_days=30, lookback_days=10) for t in price_data}
    volume_data["DHT"] = _high_volume_anomaly(baseline_days=30, lookback_days=10)

    price_df = _make_price_df(price_data)
    volume_df = _make_volume_df(volume_data)

    anomalies = {}
    for ticker in price_data:
        result = _compute_instrument_anomaly(
            ticker=ticker, price_df=price_df, volume_df=volume_df,
            baseline_days=30, lookback_days=10,
        )
        if result:
            anomalies[ticker] = result

    alert = _evaluate_cluster("OIL_DISRUPTION", CLUSTERS["OIL_DISRUPTION"], anomalies)
    assert alert is None, "Should not fire with only 1 primary anomaly"


# ---------------------------------------------------------------------------
# Test 3: 2 primaries but no inverse signal → no alert
# ---------------------------------------------------------------------------

def test_cluster_requires_inverse_confirmation():
    """DHT and NAT anomalous but UAL and DAL are flat → no inverse → no alert."""
    n = 40

    price_data = {
        "DHT": _rising_prices(n=n, pct_rise=0.015),
        "NAT": _rising_prices(n=n, pct_rise=0.012),
        "FRO": _flat_prices(n=n),
        "USO": _flat_prices(n=n),
        "TK": _flat_prices(n=n),
        "STNG": _flat_prices(n=n),
        "UAL": _flat_prices(n=n),   # no inverse movement
        "DAL": _flat_prices(n=n),   # no inverse movement
    }
    volume_data = {t: _normal_volume(baseline_days=30, lookback_days=10) for t in price_data}
    volume_data["DHT"] = _high_volume_anomaly(baseline_days=30, lookback_days=10)
    volume_data["NAT"] = _high_volume_anomaly(baseline_days=30, lookback_days=10)

    price_df = _make_price_df(price_data)
    volume_df = _make_volume_df(volume_data)

    anomalies = {}
    for ticker in price_data:
        result = _compute_instrument_anomaly(
            ticker=ticker, price_df=price_df, volume_df=volume_df,
            baseline_days=30, lookback_days=10,
        )
        if result:
            anomalies[ticker] = result

    alert = _evaluate_cluster("OIL_DISRUPTION", CLUSTERS["OIL_DISRUPTION"], anomalies)
    assert alert is None, "Should not fire without inverse confirmation"


# ---------------------------------------------------------------------------
# Test 4: No alert when all Z-scores < 1.0
# ---------------------------------------------------------------------------

def test_no_alert_when_all_normal():
    """All instruments have flat prices and normal volume → empty alert list."""
    all_tickers: set = set()
    for cdef in CLUSTERS.values():
        all_tickers.update(cdef.primary)
        all_tickers.update(cdef.confirmation)
        all_tickers.update(cdef.inverse)

    n = 40
    price_data = {t: _flat_prices(n=n) for t in all_tickers}
    volume_data = {t: _normal_volume(baseline_days=30, lookback_days=10) for t in all_tickers}

    price_df = _make_price_df(price_data)
    volume_df = _make_volume_df(volume_data)

    anomalies = {}
    for ticker in all_tickers:
        result = _compute_instrument_anomaly(
            ticker=ticker, price_df=price_df, volume_df=volume_df,
            baseline_days=30, lookback_days=10,
        )
        if result:
            anomalies[ticker] = result

    alerts_list = []
    for cluster_name, cluster_def in CLUSTERS.items():
        alert = _evaluate_cluster(cluster_name, cluster_def, anomalies)
        if alert:
            alerts_list.append(alert)

    assert len(alerts_list) == 0, f"Expected no alerts, got {alerts_list}"


# ---------------------------------------------------------------------------
# Test 5: Confidence calculation — 2/4 primaries + 0/2 confirmation = 0.35
# ---------------------------------------------------------------------------

def test_confidence_calculation():
    """
    OIL_DISRUPTION: 2 of 4 primaries triggered, 0 of 2 confirmations triggered.
    Expected confidence = (2/4) * 0.7 + (0/2) * 0.3 = 0.35
    """
    cluster_def = CLUSTERS["OIL_DISRUPTION"]
    # 4 primaries: DHT, NAT, FRO, USO
    # 2 confirmations: TK, STNG
    # 2 inverses: UAL, DAL

    anomalies = {
        "DHT": {"ticker": "DHT", "volume_z": 2.0, "price_momentum": 5.0, "is_anomalous": True},
        "NAT": {"ticker": "NAT", "volume_z": 2.5, "price_momentum": 4.0, "is_anomalous": True},
        "FRO": {"ticker": "FRO", "volume_z": 0.3, "price_momentum": 0.2, "is_anomalous": False},
        "USO": {"ticker": "USO", "volume_z": 0.1, "price_momentum": 0.1, "is_anomalous": False},
        "TK":   {"ticker": "TK",   "volume_z": 0.2, "price_momentum": 0.0, "is_anomalous": False},
        "STNG": {"ticker": "STNG", "volume_z": 0.3, "price_momentum": 0.0, "is_anomalous": False},
        # Inverse: UAL clearly falling
        "UAL": {"ticker": "UAL", "volume_z": 0.5, "price_momentum": -3.0, "is_anomalous": False},
        "DAL": {"ticker": "DAL", "volume_z": 0.2, "price_momentum": 0.0, "is_anomalous": False},
    }

    alert = _evaluate_cluster("OIL_DISRUPTION", cluster_def, anomalies)

    assert alert is not None
    expected_confidence = (2 / 4) * 0.7 + (0 / 2) * 0.3  # = 0.35
    assert abs(alert.confidence - expected_confidence) < 0.001, (
        f"Expected confidence {expected_confidence}, got {alert.confidence}"
    )


# ---------------------------------------------------------------------------
# Test 6: dry_run=True → akg.set_causal_event never called
# ---------------------------------------------------------------------------

def test_dry_run_does_not_write_akg():
    """dry_run=True must not call akg.set_causal_event even if alerts fire."""
    mock_akg = MagicMock()

    # yfinance is imported locally inside scan_commodity_shock_clusters.
    # Patch yfinance.download at the package level so the local import picks it up.
    with patch("yfinance.download", return_value=pd.DataFrame()):
        scan_commodity_shock_clusters(akg=mock_akg, dry_run=True)

    mock_akg.set_causal_event.assert_not_called()


# ---------------------------------------------------------------------------
# Test 7: Multiple clusters can fire simultaneously
# ---------------------------------------------------------------------------

def test_multiple_clusters_can_fire_simultaneously():
    """OIL_DISRUPTION and DEFENSE_BUILDUP both detect anomalies → two alerts returned."""

    # --- OIL_DISRUPTION setup ---
    oil_primaries = CLUSTERS["OIL_DISRUPTION"].primary      # DHT, NAT, FRO, USO
    oil_confirms = CLUSTERS["OIL_DISRUPTION"].confirmation  # TK, STNG
    oil_inverse = CLUSTERS["OIL_DISRUPTION"].inverse        # UAL, DAL

    # --- DEFENSE_BUILDUP setup ---
    def_primaries = CLUSTERS["DEFENSE_BUILDUP"].primary      # LMT, RTX, ITA
    def_confirms = CLUSTERS["DEFENSE_BUILDUP"].confirmation  # NOC, GD, LHX
    def_inverse = CLUSTERS["DEFENSE_BUILDUP"].inverse        # BA

    # Build anomaly dict: all oil + defense primaries anomalous, inverses opposite
    anomalies = {}

    for t in oil_primaries:
        anomalies[t] = {"ticker": t, "volume_z": 2.5, "price_momentum": 5.0, "is_anomalous": True}
    for t in oil_confirms:
        anomalies[t] = {"ticker": t, "volume_z": 0.2, "price_momentum": 0.1, "is_anomalous": False}
    for t in oil_inverse:
        anomalies[t] = {"ticker": t, "volume_z": 0.3, "price_momentum": -2.0, "is_anomalous": False}

    for t in def_primaries:
        anomalies[t] = {"ticker": t, "volume_z": 2.0, "price_momentum": 4.0, "is_anomalous": True}
    for t in def_confirms:
        anomalies[t] = {"ticker": t, "volume_z": 0.1, "price_momentum": 0.0, "is_anomalous": False}
    for t in def_inverse:
        anomalies[t] = {"ticker": t, "volume_z": 0.2, "price_momentum": -1.5, "is_anomalous": False}

    alerts_list = []
    for cluster_name in ["OIL_DISRUPTION", "DEFENSE_BUILDUP"]:
        alert = _evaluate_cluster(cluster_name, CLUSTERS[cluster_name], anomalies)
        if alert:
            alerts_list.append(alert)

    cluster_names = [a.cluster_name for a in alerts_list]
    assert "OIL_DISRUPTION" in cluster_names, "OIL_DISRUPTION should have fired"
    assert "DEFENSE_BUILDUP" in cluster_names, "DEFENSE_BUILDUP should have fired"
    assert len(alerts_list) == 2


# ---------------------------------------------------------------------------
# Test 9: AKG auto-load when not passed + dry_run=False
# ---------------------------------------------------------------------------

def test_akg_auto_loaded_when_not_passed():
    """When akg=None and dry_run=False, scout loads AKG internally and saves after alerts."""
    mock_akg = MagicMock()

    # Create a scenario where OIL_DISRUPTION fires
    # We mock the entire _evaluate_cluster to return an alert, and mock yf.download
    fake_alert = ClusterAlert(
        cluster_name="OIL_DISRUPTION",
        confidence=0.7,
        triggered_instruments=["DHT", "NAT"],
        direction="POSITIVE",
        volume_z_max=3.5,
    )

    with patch("tradingagents.dealflow.sources.commodity_shock_scout._evaluate_cluster", return_value=fake_alert), \
         patch("yfinance.download", return_value=pd.DataFrame()), \
         patch("tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph") as MockAKG:
        MockAKG.load.return_value = mock_akg

        alerts = scan_commodity_shock_clusters()  # No akg passed, not dry_run

    # AKG should have been loaded
    MockAKG.load.assert_called_once()
    # set_causal_event should have been called (5 clusters evaluated, all return fake_alert)
    assert mock_akg.set_causal_event.call_count == 5
    # save() should have been called
    mock_akg.save.assert_called_once()
