"""Flow toxicity engine — BVC-based VPIN proxy.

Pure Python engine (no LLM) that computes flow toxicity signals from daily
OHLCV using Bulk Volume Classification (Easley/López de Prado).

Entry point: build_flow_toxicity_snapshot(ticker) -> dict or None
"""

import logging
import numpy as np
import pandas as pd
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _bvc_imbalance(df: pd.DataFrame) -> pd.Series:
    """Compute daily BVC order flow imbalance from OHLCV.

    buy_fraction = (close - low) / (high - low)
    Flat bars (high == low) → buy_fraction = 0.5, imbalance = 0.
    Zero volume → NaN.
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]
    volume = df["volume"]

    price_range = high - low
    buy_fraction = pd.Series(np.where(price_range > 0, (close - low) / price_range, 0.5), index=df.index)

    buy_vol = buy_fraction * volume
    sell_vol = volume - buy_vol

    imbalance = pd.Series(np.where(volume > 0, (buy_vol - sell_vol).abs() / volume, np.nan), index=df.index)
    return imbalance


def _score_flow_imbalance(vpin: float) -> int:
    """Convert VPIN proxy to 0-100 score (inverted: high toxicity = low score)."""
    if vpin >= 0.7:
        return 15  # EXTREME toxicity
    elif vpin >= 0.5:
        return 30  # HIGH
    elif vpin >= 0.3:
        return 50  # MODERATE
    elif vpin >= 0.15:
        return 65  # LOW
    else:
        return 80  # MINIMAL


def _score_accumulation_distribution(cmf: float) -> int:
    """Convert 20d Chaikin Money Flow to 0-100 score."""
    if cmf >= 0.15:
        return 80  # strong accumulation
    elif cmf >= 0.05:
        return 65
    elif cmf >= -0.05:
        return 50  # neutral
    elif cmf >= -0.15:
        return 35
    else:
        return 20  # strong distribution


def _score_volume_anomaly(ratio: float) -> int:
    """Convert volume/20d SMA ratio to 0-100 score."""
    if ratio >= 3.0:
        return 25  # extreme = ambiguous
    elif ratio >= 2.0:
        return 40
    elif ratio >= 0.8:
        return 60  # normal = healthy
    elif ratio >= 0.5:
        return 50
    else:
        return 35  # low volume = thin


def _score_price_volume_divergence(corr: float) -> int:
    """Convert 10d Pearson(close_returns, volume_changes) to 0-100 score."""
    if corr >= 0.5:
        return 70  # strong positive = confirming
    elif corr >= 0.1:
        return 60
    elif corr >= -0.1:
        return 50  # uncorrelated
    elif corr >= -0.5:
        return 35
    else:
        return 20  # strong negative = divergence = bearish


def _compute_cmf(df: pd.DataFrame, window: int = 20) -> float:
    """Compute Chaikin Money Flow over a rolling window."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    volume = df["volume"]

    price_range = high - low
    mfm = pd.Series(
        np.where(price_range > 0, ((close - low) - (high - close)) / price_range, 0.0),
        index=df.index,
    )
    mf_volume = mfm * volume

    cmf = mf_volume.rolling(window).sum() / volume.rolling(window).sum()
    return float(cmf.iloc[-1])


def _load_data(ticker: str):
    """Load OHLCV data. Separate function for testability."""
    from tradingagents.phase_engine.data_engine import load as load_ohlcv
    return load_ohlcv(ticker)


def build_flow_toxicity_snapshot(ticker: str) -> Optional[Dict[str, Any]]:
    """Compute flow toxicity snapshot for a ticker using BVC-based VPIN proxy.

    Returns a dict with VPIN proxy, CMF, volume anomaly ratio, composite score,
    toxicity level, and direction. Returns None if data is unavailable or
    insufficient (<25 bars).
    """
    try:
        df = _load_data(ticker)
    except Exception as exc:
        logger.warning("flow_toxicity_engine: failed to load data for %s (%s)", ticker, exc)
        return None

    if df is None or len(df) < 25:
        logger.debug("flow_toxicity_engine: insufficient bars for %s", ticker)
        return None

    try:
        # --- VPIN proxy via BVC ---
        imbalance = _bvc_imbalance(df)
        vpin_proxy = float(np.nanmean(imbalance.iloc[-20:]))

        # --- Volume ratio ---
        if "vol_sma20" in df.columns:
            vol_sma = float(df["vol_sma20"].iloc[-1])
        else:
            vol_sma = float(df["volume"].rolling(20).mean().iloc[-1])
        volume_ratio = float(df["volume"].iloc[-1]) / vol_sma if vol_sma > 0 else 1.0

        # --- Chaikin Money Flow ---
        cmf = _compute_cmf(df)
        if not np.isfinite(cmf):
            cmf = 0.0

        # --- Price-volume correlation (10d) ---
        close_ret = df["close"].pct_change().iloc[-10:]
        vol_chg = df["volume"].pct_change().iloc[-10:]
        pv_corr = close_ret.corr(vol_chg)
        if not np.isfinite(pv_corr):
            pv_corr = 0.0

        # --- Subscores ---
        flow_imbalance_score = _score_flow_imbalance(vpin_proxy)
        ad_score = _score_accumulation_distribution(cmf)
        vol_score = _score_volume_anomaly(volume_ratio)
        pv_score = _score_price_volume_divergence(pv_corr)

        # --- Composite (weighted sum) ---
        composite = (
            flow_imbalance_score * 0.40
            + ad_score * 0.25
            + vol_score * 0.20
            + pv_score * 0.15
        )
        composite = int(round(max(0.0, min(100.0, composite))))

        # --- Toxicity level (based on raw VPIN, not score) ---
        if vpin_proxy >= 0.7:
            toxicity_level = "EXTREME"
        elif vpin_proxy >= 0.5:
            toxicity_level = "HIGH"
        elif vpin_proxy >= 0.3:
            toxicity_level = "MODERATE"
        else:
            toxicity_level = "LOW"

        # --- Direction (based on composite score) ---
        if composite >= 60:
            direction = "BULLISH"
        elif composite <= 40:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        # --- Data coverage: fraction of signals that are non-NaN/non-default ---
        signals_valid = [
            np.isfinite(vpin_proxy),
            np.isfinite(cmf) and cmf != 0.0,
            np.isfinite(volume_ratio),
            np.isfinite(pv_corr) and pv_corr != 0.0,
        ]
        coverage = round(sum(signals_valid) / len(signals_valid), 2)

        return {
            "vpin_proxy": round(float(vpin_proxy), 4),
            "volume_ratio": round(float(volume_ratio), 4),
            "cmf": round(float(cmf), 4),
            "toxicity_level": toxicity_level,
            "subscores": {
                "flow_imbalance": flow_imbalance_score,
                "accumulation_distribution": ad_score,
                "volume_anomaly": vol_score,
                "price_volume_divergence": pv_score,
            },
            "composite_score": composite,
            "direction": direction,
            "data_coverage": coverage,
        }

    except Exception as exc:
        logger.warning("flow_toxicity_engine: computation failed for %s (%s)", ticker, exc)
        return None
