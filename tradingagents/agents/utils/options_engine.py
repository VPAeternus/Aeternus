"""Options positioning engine.

Pure Python engine (no LLM) that fetches options chain data via yfinance
and computes positioning signals from derivatives data.

Entry point: build_options_snapshot(ticker) -> dict or None
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _score_put_call_ratio(ratio: float) -> float:
    """Score put/call volume ratio. Higher ratio = more fear."""
    if ratio > 1.2:
        return 20.0
    elif ratio > 0.9:
        return 40.0
    elif ratio > 0.6:
        return 55.0
    else:
        return 75.0


def _score_iv_skew(skew: float) -> float:
    """Score IV skew. High skew = fear premium on downside."""
    if skew > 0.10:
        return 25.0
    elif skew > 0.03:
        return 55.0
    else:
        return 70.0


def _score_oi_ratio(ratio: float) -> float:
    """Score put/call OI ratio. Similar to volume ratio but more stable."""
    if ratio > 1.2:
        return 20.0
    elif ratio > 0.9:
        return 40.0
    elif ratio > 0.6:
        return 55.0
    else:
        return 75.0


def build_options_snapshot(ticker: str) -> Optional[Dict[str, Any]]:
    """Compute options-derived sentiment snapshot for a ticker.

    Returns a dict with put/call ratios, IV skew, composite score, and
    fear/greed classification. Returns None if options data is unavailable.
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("options_engine: yfinance not installed")
        return None

    try:
        stock = yf.Ticker(ticker)
        expirations = stock.options
        if not expirations:
            return None

        # Use nearest 2 expirations
        target_expirations = expirations[:2]

        total_call_volume = 0
        total_put_volume = 0
        total_call_oi = 0
        total_put_oi = 0
        atm_iv = None
        iv_skew = None

        current_price = None
        try:
            hist = stock.history(period="1d")
            if not hist.empty:
                current_price = float(hist["Close"].iloc[-1])
        except Exception:
            pass

        for exp in target_expirations:
            try:
                chain = stock.option_chain(exp)
            except Exception:
                continue

            calls = chain.calls
            puts = chain.puts

            # Aggregate volume and OI
            call_vol = calls["volume"].fillna(0).sum()
            put_vol = puts["volume"].fillna(0).sum()
            call_oi = calls["openInterest"].fillna(0).sum()
            put_oi = puts["openInterest"].fillna(0).sum()

            total_call_volume += int(call_vol)
            total_put_volume += int(put_vol)
            total_call_oi += int(call_oi)
            total_put_oi += int(put_oi)

            # ATM IV and skew from first expiration only
            if current_price is not None and atm_iv is None:
                try:
                    # Find ATM call (closest strike to current price)
                    calls_with_iv = calls[calls["impliedVolatility"] > 0].copy()
                    if not calls_with_iv.empty:
                        calls_with_iv["dist"] = abs(calls_with_iv["strike"] - current_price)
                        atm_call = calls_with_iv.loc[calls_with_iv["dist"].idxmin()]
                        atm_iv = float(atm_call["impliedVolatility"])

                    # Find OTM put (~95% of current price) for skew
                    otm_target = current_price * 0.95
                    puts_with_iv = puts[puts["impliedVolatility"] > 0].copy()
                    if not puts_with_iv.empty and atm_iv is not None:
                        puts_with_iv["dist"] = abs(puts_with_iv["strike"] - otm_target)
                        otm_put = puts_with_iv.loc[puts_with_iv["dist"].idxmin()]
                        otm_put_iv = float(otm_put["impliedVolatility"])
                        iv_skew = otm_put_iv - atm_iv
                except Exception:
                    pass

        # Compute ratios
        if total_call_volume == 0 and total_put_volume == 0:
            return None

        put_call_volume_ratio = (
            total_put_volume / total_call_volume
            if total_call_volume > 0
            else 2.0  # extreme fear if no call volume
        )
        put_call_oi_ratio = (
            total_put_oi / total_call_oi
            if total_call_oi > 0
            else 1.0  # neutral default
        )

        # Default skew if we couldn't compute it
        if iv_skew is None:
            iv_skew = 0.0
        if atm_iv is None:
            atm_iv = 0.0

        # Composite scoring
        pc_score = _score_put_call_ratio(put_call_volume_ratio)
        skew_score = _score_iv_skew(iv_skew)
        oi_score = _score_oi_ratio(put_call_oi_ratio)

        positioning_score = round(pc_score * 0.40 + skew_score * 0.30 + oi_score * 0.30)
        positioning_score = max(0, min(100, positioning_score))

        # Fear/Greed classification
        if positioning_score < 35:
            fear_greed = "FEAR"
        elif positioning_score > 65:
            fear_greed = "GREED"
        else:
            fear_greed = "NEUTRAL"

        # Data coverage: how many of our signals are non-default
        signals = [
            total_call_volume > 0,
            total_put_volume > 0,
            total_call_oi > 0,
            total_put_oi > 0,
            atm_iv > 0,
        ]
        data_coverage = round(sum(signals) / len(signals), 2)

        return {
            "put_call_volume_ratio": round(put_call_volume_ratio, 4),
            "put_call_oi_ratio": round(put_call_oi_ratio, 4),
            "iv_skew": round(iv_skew, 4),
            "atm_iv": round(atm_iv, 4),
            "positioning_score": positioning_score,
            "fear_greed": fear_greed,
            "expirations_analyzed": len(target_expirations),
            "data_coverage": data_coverage,
        }

    except Exception as exc:
        logger.warning("options_engine: failed for %s (%s)", ticker, exc)
        return None
