"""CSP Tactical Overlay — regime detector and recommendation builder.

Implements the backtested strategy: sell 10% OTM QQQ cash secured puts when:
  1. QQQ < SMA200  (bear regime active)
  2. 25 < VIX < 40  (fat premiums, not panic)
  3. QQQ 20-day ROC > -8%  (slow grind, not fast crash)

Backtest result (2010-2024, 171 months):
  CSP VIX+ROC: +1,140% total, +19.3% ann, -27.3% DD, 0.886 Sharpe
  Buy & Hold:  +1,040% total, +18.6% ann, -33.7% DD, 0.818 Sharpe
  Assignment rate: 0% across 8 CSP-active months
"""

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import yfinance as yf


class CspRecommendation(str, Enum):
    SELL_CSP = "SELL_CSP"
    ABOVE_SMA200 = "ABOVE_SMA200"            # primary gate not met
    HOLD_THIN_PREMIUM = "HOLD_THIN_PREMIUM"  # below SMA200 but VIX < 25
    HOLD_PANIC = "HOLD_PANIC"                # below SMA200 but VIX > 40
    HOLD_FAST_CRASH = "HOLD_FAST_CRASH"      # below SMA200 + ROC < -8%
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"    # yfinance failed


@dataclass
class CspOverlayResult:
    recommendation: CspRecommendation
    as_of_date: str               # ISO date
    qqq_price: float
    sma200: float
    below_sma200: bool
    vix: float
    roc_20d_pct: float            # (price_today - price_20d_ago) / price_20d_ago * 100
    vix_in_band: bool             # 25 < VIX < 40
    roc_ok: bool                  # roc_20d_pct > -8.0
    csp_strike: float             # qqq_price * 0.90 (10% OTM)
    estimated_premium_usd: float  # Black-Scholes estimate per contract (× 100)
    alpha_window_days: int        # 12 (technology sector default)
    rationale: str                # 1-2 sentence human explanation
    filter_reason: str            # which filter blocked CSP (empty if SELL_CSP)


def _bs_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes put price."""
    if T <= 0 or sigma <= 0:
        return 0.0
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    nd1 = _norm_cdf(-d1)
    nd2 = _norm_cdf(-d2)
    return K * math.exp(-r * T) * nd2 - S * nd1


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via math.erfc."""
    return 0.5 * math.erfc(-x / math.sqrt(2))


def evaluate_csp_regime(as_of_date: Optional[str] = None) -> CspOverlayResult:
    """Evaluate current market conditions against CSP entry criteria.

    Args:
        as_of_date: ISO date string for logging purposes (does not filter data).

    Returns:
        CspOverlayResult with recommendation and all supporting metrics.
    """
    import datetime

    date_str = as_of_date or datetime.date.today().isoformat()

    try:
        # Download QQQ price history (260 trading days ~ 1 year + buffer for SMA200)
        qqq_raw = yf.download(
            "QQQ", period="260d", interval="1d", auto_adjust=True, progress=False
        )
        # Handle MultiIndex columns from yfinance
        if hasattr(qqq_raw.columns, "levels"):
            qqq_close = qqq_raw["Close"].squeeze()
        else:
            qqq_close = qqq_raw["Close"]
        qqq_close = qqq_close.dropna()

        # Download VIX
        vix_raw = yf.download(
            "^VIX", period="30d", interval="1d", auto_adjust=True, progress=False
        )
        if hasattr(vix_raw.columns, "levels"):
            vix_close = vix_raw["Close"].squeeze()
        else:
            vix_close = vix_raw["Close"]
        vix_close = vix_close.dropna()

        if len(qqq_close) < 21:
            raise ValueError(f"Insufficient QQQ data: {len(qqq_close)} bars")
        if len(vix_close) < 1:
            raise ValueError("No VIX data returned")

        # Compute SMA200
        sma200_series = qqq_close.rolling(200).mean()
        qqq_price = float(qqq_close.iloc[-1])
        sma200 = float(sma200_series.iloc[-1])
        vix = float(vix_close.iloc[-1])

        # 20-day ROC: (close[-1] - close[-21]) / close[-21] * 100
        roc_20d_pct = float((qqq_close.iloc[-1] - qqq_close.iloc[-21]) / qqq_close.iloc[-21] * 100)

        # Gate evaluations
        below_sma200 = qqq_price < sma200
        vix_in_band = 25.0 < vix < 40.0
        roc_ok = roc_20d_pct > -8.0

        # CSP parameters
        csp_strike = qqq_price * 0.90
        estimated_premium_usd = _bs_put(
            S=qqq_price,
            K=csp_strike,
            T=30.0 / 365.0,
            r=0.04,
            sigma=vix / 100.0,
        ) * 100.0  # per contract = 100 shares

        alpha_window_days = 12  # technology sector default

        # Three-gate logic
        if not below_sma200:
            pct_above = (qqq_price - sma200) / sma200 * 100
            recommendation = CspRecommendation.ABOVE_SMA200
            rationale = (
                f"QQQ {pct_above:.1f}% above SMA200 — bull regime. "
                "Hold shares. CSP mode inactive."
            )
            filter_reason = "ABOVE_SMA200"
        elif vix < 25.0:
            recommendation = CspRecommendation.HOLD_THIN_PREMIUM
            rationale = (
                f"QQQ below SMA200 but VIX {vix:.1f} below 25 — "
                "premiums too thin (Q4 2018 pattern). Hold shares."
            )
            filter_reason = "VIX_TOO_LOW"
        elif vix > 40.0:
            recommendation = CspRecommendation.HOLD_PANIC
            rationale = (
                f"QQQ below SMA200 but VIX {vix:.1f} above 40 — "
                "panic crash, do not sell puts. Hold shares."
            )
            filter_reason = "VIX_TOO_HIGH"
        elif roc_20d_pct < -8.0:
            recommendation = CspRecommendation.HOLD_FAST_CRASH
            rationale = (
                f"QQQ below SMA200, VIX in band, but 20-day descent "
                f"{roc_20d_pct:.1f}% exceeds -8% threshold — fast crash active. Hold shares."
            )
            filter_reason = "ROC_CRASH"
        else:
            pct_below = (sma200 - qqq_price) / sma200 * 100
            recommendation = CspRecommendation.SELL_CSP
            rationale = (
                f"QQQ {pct_below:.1f}% below SMA200, VIX {vix:.1f} in optimal band (25-40), "
                f"20d descent {roc_20d_pct:.1f}% within tolerance. "
                f"Sell 10% OTM CSP (~${estimated_premium_usd:.0f}/contract). "
                "Backtest: +1,140% vs +1,040% B&H, 0% assignment rate."
            )
            filter_reason = ""

        return CspOverlayResult(
            recommendation=recommendation,
            as_of_date=date_str,
            qqq_price=qqq_price,
            sma200=sma200,
            below_sma200=below_sma200,
            vix=vix,
            roc_20d_pct=roc_20d_pct,
            vix_in_band=vix_in_band,
            roc_ok=roc_ok,
            csp_strike=csp_strike,
            estimated_premium_usd=estimated_premium_usd,
            alpha_window_days=alpha_window_days,
            rationale=rationale,
            filter_reason=filter_reason,
        )

    except Exception as exc:
        return CspOverlayResult(
            recommendation=CspRecommendation.DATA_UNAVAILABLE,
            as_of_date=date_str,
            qqq_price=0.0,
            sma200=0.0,
            below_sma200=False,
            vix=0.0,
            roc_20d_pct=0.0,
            vix_in_band=False,
            roc_ok=False,
            csp_strike=0.0,
            estimated_premium_usd=0.0,
            alpha_window_days=12,
            rationale=f"Data unavailable: {exc}",
            filter_reason="DATA_ERROR",
        )
