"""S-083: Commodity Shock Scout — geopolitical cluster pre-positioning anomaly detector.

Scans 5 named geopolitical clusters for unusual volume/price activity that signals
institutional pre-positioning before commodity shocks, conflicts, or safe-haven flights.
Uses a single batch yfinance download per scan (free, no API key required).
"""

from __future__ import annotations

import datetime as dt
import sys
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional

import pandas as pd

if TYPE_CHECKING:
    from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph

# ---------------------------------------------------------------------------
# Cluster definitions
# ---------------------------------------------------------------------------

@dataclass
class ClusterDef:
    description: str
    primary: List[str]
    confirmation: List[str]
    inverse: List[str]
    event_magnitude_base: float
    alpha_window_days: int


CLUSTERS: Dict[str, ClusterDef] = {
    "OIL_DISRUPTION": ClusterDef(
        description="Strait of Hormuz / OPEC supply shock / Middle East conflict",
        primary=["DHT", "NAT", "FRO", "USO"],
        confirmation=["TK", "STNG"],
        inverse=["UAL", "DAL"],
        event_magnitude_base=0.18,
        alpha_window_days=10,
    ),
    "TECH_CONFLICT": ClusterDef(
        description="Taiwan Strait / China semiconductor restrictions / TSMC risk",
        primary=["TSM", "ASML", "SOXX"],
        confirmation=["MU", "AMAT", "LRCX"],
        inverse=["AAPL"],
        event_magnitude_base=0.15,
        alpha_window_days=8,
    ),
    "AGRICULTURE_SQUEEZE": ClusterDef(
        description="Ukraine/Russia / Black Sea disruption / fertilizer supply",
        primary=["WEAT", "CORN", "MOS"],
        confirmation=["NTR", "UNG"],
        inverse=["CPB", "GIS"],
        event_magnitude_base=0.12,
        alpha_window_days=12,
    ),
    "DEFENSE_BUILDUP": ClusterDef(
        description="NATO escalation / European rearmament / general conflict cycle",
        primary=["LMT", "RTX", "ITA"],
        confirmation=["NOC", "GD", "LHX"],
        inverse=["BA"],
        event_magnitude_base=0.10,
        alpha_window_days=14,
    ),
    "SAFE_HAVEN_FLIGHT": ClusterDef(
        description="Cross-cluster meta signal / systemic risk / broad risk-off",
        primary=["GLD", "TLT"],
        confirmation=["UVXY"],
        inverse=["SPY"],
        event_magnitude_base=0.08,
        alpha_window_days=7,
    ),
}


# ---------------------------------------------------------------------------
# Alert dataclass
# ---------------------------------------------------------------------------

@dataclass
class ClusterAlert:
    cluster_name: str
    confidence: float           # 0.0–1.0
    triggered_instruments: List[str]
    direction: str              # "POSITIVE" or "NEGATIVE"
    volume_z_max: float         # highest volume Z-score in cluster


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------

def _compute_instrument_anomaly(
    ticker: str,
    price_df: pd.DataFrame,
    volume_df: pd.DataFrame,
    baseline_days: int = 30,
    lookback_days: int = 10,
) -> Optional[dict]:
    """
    Compute volume Z-score and price momentum for a single ticker.

    Volume Z-score: (recent_avg - baseline_avg) / max(baseline_std, baseline_avg * 0.01)
    Price momentum anomaly: recent cumulative return vs 2-std of daily baseline returns.

    Returns dict with keys: ticker, volume_z, price_momentum, is_anomalous.
    Returns None if insufficient data.
    """
    try:
        # Extract single-ticker series from potentially multi-ticker DataFrames
        if isinstance(price_df.columns, pd.MultiIndex):
            if ("Close", ticker) in price_df.columns:
                price_series = price_df[("Close", ticker)].dropna()
            elif ticker in price_df.columns.get_level_values(1):
                price_series = price_df.xs(ticker, axis=1, level=1)["Close"].dropna()
            else:
                return None
        elif ticker in price_df.columns:
            price_series = price_df[ticker].dropna()
        else:
            return None

        if isinstance(volume_df.columns, pd.MultiIndex):
            if ("Volume", ticker) in volume_df.columns:
                vol_series = volume_df[("Volume", ticker)].dropna()
            elif ticker in volume_df.columns.get_level_values(1):
                vol_series = volume_df.xs(ticker, axis=1, level=1)["Volume"].dropna()
            else:
                vol_series = pd.Series(dtype=float)
        elif ticker in volume_df.columns:
            vol_series = volume_df[ticker].dropna()
        else:
            vol_series = pd.Series(dtype=float)

        if len(price_series) < baseline_days + lookback_days:
            return None

        # Baseline: oldest baseline_days bars; recent: most recent lookback_days bars
        recent_price = price_series.iloc[-lookback_days:]
        baseline_price = price_series.iloc[-(baseline_days + lookback_days):-lookback_days]

        # Price momentum: cumulative return over lookback period (%)
        if len(recent_price) >= 2 and recent_price.iloc[0] != 0:
            price_momentum = (recent_price.iloc[-1] / recent_price.iloc[0] - 1.0) * 100.0
        else:
            price_momentum = 0.0

        # Volume Z-score
        # Use max(std, 1% of mean) as denominator to handle zero-variance baselines gracefully.
        volume_z = 0.0
        if len(vol_series) >= baseline_days + lookback_days:
            recent_vol = vol_series.iloc[-lookback_days:]
            baseline_vol = vol_series.iloc[-(baseline_days + lookback_days):-lookback_days]
            baseline_mean = baseline_vol.mean()
            baseline_std = baseline_vol.std()
            recent_avg = recent_vol.mean()
            # Floor std at 1% of mean to avoid zero-division with perfectly flat test data
            effective_std = max(baseline_std, baseline_mean * 0.01) if baseline_mean > 0 else max(baseline_std, 1.0)
            volume_z = (recent_avg - baseline_mean) / effective_std
        else:
            volume_z = 0.0

        # Price momentum anomaly: compare recent return to 2-std of baseline daily returns.
        # This avoids conflating trending baseline with recent anomaly.
        price_anomalous = False
        if len(baseline_price) >= 5:
            daily_returns = baseline_price.pct_change().dropna() * 100.0
            if len(daily_returns) >= 3:
                baseline_daily_std = daily_returns.std()
                # Annualize to a lookback_days period std (sqrt scaling)
                baseline_period_std = baseline_daily_std * (lookback_days ** 0.5)
                threshold = max(baseline_period_std * 2.0, 2.0)  # At least 2% absolute
                if abs(price_momentum) > threshold:
                    price_anomalous = True

        is_anomalous = volume_z > 1.5 or price_anomalous

        return {
            "ticker": ticker,
            "volume_z": round(volume_z, 4),
            "price_momentum": round(price_momentum, 4),
            "is_anomalous": is_anomalous,
        }

    except Exception as e:
        print(f"[commodity_shock_scout] anomaly error {ticker}: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Cluster evaluation
# ---------------------------------------------------------------------------

def _evaluate_cluster(
    cluster_name: str,
    cluster_def: ClusterDef,
    anomalies: Dict[str, dict],
) -> Optional[ClusterAlert]:
    """
    Alert if:
    - 2+ primary instruments are anomalous
    - 1+ inverse instrument shows OPPOSITE movement

    Confidence = (n_primary_triggered / len(primary)) * 0.7
              + (n_confirmation_triggered / max(1, len(confirmation))) * 0.3
    """
    primary_triggered = []
    primary_directions: List[float] = []  # positive momentum = POSITIVE cluster

    for ticker in cluster_def.primary:
        anom = anomalies.get(ticker)
        if anom and anom["is_anomalous"]:
            primary_triggered.append(ticker)
            primary_directions.append(anom["price_momentum"])

    # Need at least 2 primary anomalies
    if len(primary_triggered) < 2:
        return None

    # Determine cluster direction from primary momentum (majority vote)
    positive_votes = sum(1 for m in primary_directions if m >= 0)
    negative_votes = len(primary_directions) - positive_votes
    cluster_direction = "POSITIVE" if positive_votes >= negative_votes else "NEGATIVE"

    # Check inverse confirmation: at least 1 inverse shows opposite movement
    inverse_confirmed = False
    for ticker in cluster_def.inverse:
        anom = anomalies.get(ticker)
        if anom:
            if cluster_direction == "POSITIVE" and anom["price_momentum"] < -0.5:
                inverse_confirmed = True
                break
            elif cluster_direction == "NEGATIVE" and anom["price_momentum"] > 0.5:
                inverse_confirmed = True
                break

    if not inverse_confirmed:
        return None

    # Count confirmation triggers
    confirmation_triggered = []
    for ticker in cluster_def.confirmation:
        anom = anomalies.get(ticker)
        if anom and anom["is_anomalous"]:
            confirmation_triggered.append(ticker)

    # Confidence calculation
    n_primary = len(cluster_def.primary)
    n_confirmation = max(1, len(cluster_def.confirmation))
    confidence = (
        (len(primary_triggered) / n_primary) * 0.7
        + (len(confirmation_triggered) / n_confirmation) * 0.3
    )
    confidence = round(min(1.0, confidence), 6)

    triggered_instruments = primary_triggered + confirmation_triggered

    # Volume Z-max across all triggered instruments
    volume_z_max = max(
        (anomalies[t]["volume_z"] for t in triggered_instruments if t in anomalies),
        default=0.0,
    )

    return ClusterAlert(
        cluster_name=cluster_name,
        confidence=confidence,
        triggered_instruments=triggered_instruments,
        direction=cluster_direction,
        volume_z_max=round(volume_z_max, 4),
    )


# ---------------------------------------------------------------------------
# Main scan
# ---------------------------------------------------------------------------

def scan_commodity_shock_clusters(
    akg=None,
    lookback_days: int = 10,
    baseline_days: int = 30,
    dry_run: bool = False,
) -> List[ClusterAlert]:
    """
    Scans all 5 clusters for pre-positioning anomalies.

    1. Collect all unique tickers across all clusters
    2. Download price + volume history (90 days) in ONE yfinance batch call
    3. Compute anomaly scores per instrument
    4. Evaluate each cluster's alert rule
    5. For firing clusters: write CausalEvent to AKG (unless dry_run=True)
    6. Return list of ClusterAlert objects
    """
    import yfinance as yf

    # Collect all unique tickers
    all_tickers: set = set()
    for cdef in CLUSTERS.values():
        all_tickers.update(cdef.primary)
        all_tickers.update(cdef.confirmation)
        all_tickers.update(cdef.inverse)

    tickers_list = sorted(all_tickers)
    total_days = baseline_days + lookback_days + 5  # buffer for non-trading days
    history_days = max(90, total_days)

    # Single batch download
    price_df = pd.DataFrame()
    volume_df = pd.DataFrame()

    try:
        period_str = f"{history_days}d"
        raw = yf.download(
            tickers_list,
            period=period_str,
            auto_adjust=True,
            progress=False,
        )
        if not raw.empty:
            price_df = raw
            volume_df = raw
    except Exception as e:
        print(f"[commodity_shock_scout] batch download error: {e}", file=sys.stderr)

    # Compute anomaly scores for each instrument
    anomalies: Dict[str, dict] = {}
    for ticker in tickers_list:
        result = _compute_instrument_anomaly(
            ticker=ticker,
            price_df=price_df,
            volume_df=volume_df,
            baseline_days=baseline_days,
            lookback_days=lookback_days,
        )
        if result is not None:
            anomalies[ticker] = result

    # Load AKG if not provided (so CLI and scheduler callers don't need to pass it)
    if akg is None and not dry_run:
        try:
            from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
            akg = AeternusKnowledgeGraph.load()
        except Exception as e:
            print(f"[commodity_shock_scout] AKG load error: {e}", file=sys.stderr)

    # Evaluate each cluster
    alerts: List[ClusterAlert] = []
    today_str = dt.date.today().isoformat()

    for cluster_name, cluster_def in CLUSTERS.items():
        try:
            alert = _evaluate_cluster(cluster_name, cluster_def, anomalies)
        except Exception as e:
            print(f"[commodity_shock_scout] cluster eval error {cluster_name}: {e}", file=sys.stderr)
            alert = None

        if alert is None:
            continue

        alerts.append(alert)

        # Write CausalEvent to AKG
        if akg is not None and not dry_run:
            try:
                event_data = {
                    "ticker": f"CLUSTER_{cluster_name}",
                    "event_type": "COMMODITY_SHOCK",
                    "event_date": today_str,
                    "magnitude": alert.confidence,
                    "direction": alert.direction,
                    "source": "commodity_shock_scout",
                    "processed_at": dt.datetime.utcnow().isoformat(),
                    "cluster_name": cluster_name,
                    "triggered_instruments": alert.triggered_instruments,
                    "volume_z_max": alert.volume_z_max,
                }
                akg.set_causal_event(
                    event_id=f"CS_{cluster_name}_{today_str}",
                    data=event_data,
                )
            except Exception as e:
                print(
                    f"[commodity_shock_scout] AKG write error {cluster_name}: {e}",
                    file=sys.stderr,
                )

            # Enrich individual company nodes so emergence engine sees them
            for inst_ticker in alert.triggered_instruments:
                inst_ticker = inst_ticker.upper().strip()
                if not inst_ticker:
                    continue
                try:
                    vol_z = float(anomalies.get(inst_ticker, {}).get("volume_z", 0) or 0)
                    akg.enrich_node_cashtag(
                        ticker=inst_ticker,
                        velocity_z=vol_z,
                        mentions_7d=0,
                        velocity_trend=alert.direction or "neutral",
                        sentiment=0.0,
                        as_of_date=today_str,
                    )
                except Exception as e:
                    print(f"[commodity_shock_scout] ticker enrich error {inst_ticker}: {e}", file=sys.stderr)

    if akg is not None and alerts and not dry_run:
        try:
            akg.save()
        except Exception as e:
            print(f"[commodity_shock_scout] AKG save error: {e}", file=sys.stderr)

    return alerts
