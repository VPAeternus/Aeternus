"""Risk and execution gates for allocator validation."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

from .contracts import (
    ADV_PARTICIPATION_MAX,
    AssetClassId,
    ExecutionMode,
    GROUP_CAP_BY_REGIME,
    IMPACT_K_BY_LANE,
    MVC_VETO_THRESHOLD,
    AllocationIntent,
    FundingSourceStatus,
    IntentStatus,
    MarketSnapshot,
    PortfolioSnapshot,
    RegimeShock,
)


@dataclass
class GateResult:
    """Generic gate evaluation outcome."""

    allowed: bool
    code: str
    message: str = ""


@dataclass
class PriceSlipResult:
    """Execution latency/slippage guard result."""

    allowed: bool
    code: str
    delta_bps: Optional[float]


@dataclass
class ImpactGateResult:
    """ADV participation and impact estimate guard result."""

    allowed: bool
    code: str
    participation: float
    impact_bps: Optional[float]
    message: str = ""


class CovarianceGate:
    """Portfolio concentration and covariance veto logic."""

    def evaluate(
        self,
        intent: AllocationIntent,
        portfolio: PortfolioSnapshot,
        shock: RegimeShock,
    ) -> GateResult:
        if intent.symbol not in portfolio.symbols:
            return GateResult(
                allowed=False,
                code=IntentStatus.REJECTED_COVARIANCE_UNMODELED_SYMBOL.value,
                message=f"Symbol {intent.symbol} is not in covariance model universe.",
            )

        if len(portfolio.symbols) != len(portfolio.weights):
            return GateResult(allowed=False, code="REJECTED_INVALID_PORTFOLIO_SHAPE", message="weights mismatch")
        if len(portfolio.covariance) != len(portfolio.symbols):
            return GateResult(
                allowed=False,
                code="REJECTED_INVALID_COVARIANCE_SHAPE",
                message="covariance row count mismatch",
            )
        if any(len(row) != len(portfolio.symbols) for row in portfolio.covariance):
            return GateResult(
                allowed=False,
                code="REJECTED_INVALID_COVARIANCE_SHAPE",
                message="covariance matrix not square",
            )

        symbol_index = portfolio.symbols.index(intent.symbol)
        direction = 1.0 if intent.side.upper() == "BUY" else -1.0
        delta_weight = direction * (float(intent.target_notional_usd) / max(float(portfolio.nav_usd), 1e-9))
        weights_pre = list(float(value) for value in portfolio.weights)
        weights_post = list(weights_pre)
        weights_post[symbol_index] += delta_weight

        group_tag = intent.correlation_group_tag or "UNCLASSIFIED"
        group_indices = [
            idx
            for idx, symbol in enumerate(portfolio.symbols)
            if str(portfolio.group_tags.get(symbol, "UNCLASSIFIED")) == group_tag
        ]
        if not group_indices:
            group_indices = [symbol_index]

        cap = float(GROUP_CAP_BY_REGIME[shock])
        group_weight_pre = sum(abs(weights_pre[idx]) for idx in group_indices)
        group_weight_post = sum(abs(weights_post[idx]) for idx in group_indices)
        is_risk_reducing_trade = group_weight_post < (group_weight_pre - 1e-12)
        if group_weight_post > (cap + 1e-12) and not is_risk_reducing_trade:
            return GateResult(
                allowed=False,
                code=IntentStatus.REJECTED_COVARIANCE_VETO.value,
                message=f"group cap breached ({group_weight_post:.4f} > {cap:.4f})",
            )

        variance_pre = _portfolio_variance(weights_pre, portfolio.covariance)
        variance_post = _portfolio_variance(weights_post, portfolio.covariance)
        mvc_pre = _group_mvc_ratio(weights_pre, portfolio.covariance, group_indices, variance_pre)
        mvc_post = _group_mvc_ratio(weights_post, portfolio.covariance, group_indices, variance_post)
        if mvc_post > MVC_VETO_THRESHOLD and mvc_post > mvc_pre:
            return GateResult(
                allowed=False,
                code=IntentStatus.REJECTED_COVARIANCE_VETO.value,
                message=f"group MVC increased above threshold ({mvc_post:.4f})",
            )

        return GateResult(allowed=True, code="OK")


class ImpactGate:
    """Liquidity impact gate with hard ADV participation veto."""

    def __init__(self, participation_cap: float = ADV_PARTICIPATION_MAX):
        self.participation_cap = float(participation_cap)

    def evaluate(
        self,
        *,
        intent: AllocationIntent,
        market_snapshot: MarketSnapshot,
    ) -> ImpactGateResult:
        adv_notional = market_snapshot.adv30_notional_usd
        if adv_notional is None or float(adv_notional) <= 0.0:
            is_private_shadow = (
                intent.execution_mode == ExecutionMode.SHADOW
                and intent.asset_class_id == AssetClassId.PRIVATE_EQUITY
            )
            if is_private_shadow:
                return ImpactGateResult(
                    allowed=True,
                    code="OK",
                    participation=0.0,
                    impact_bps=float(market_snapshot.spread_bps),
                    message="ADV missing; private-equity shadow intent bypasses ADV participation veto.",
                )
            return ImpactGateResult(
                allowed=False,
                code=IntentStatus.REJECTED_IMPACT_VETO.value,
                participation=float("inf"),
                impact_bps=None,
                message="Missing/non-positive ADV30 notional in cached market snapshot.",
            )

        participation = max(0.0, float(intent.target_notional_usd) / float(adv_notional))
        volatility_bps = max(0.0, float(market_snapshot.vol20d_bps or 0.0))
        k_lane = float(IMPACT_K_BY_LANE[intent.lane])
        impact_bps = float(market_snapshot.spread_bps) + k_lane * volatility_bps * (participation**0.5)

        if participation > self.participation_cap:
            return ImpactGateResult(
                allowed=False,
                code=IntentStatus.REJECTED_IMPACT_VETO.value,
                participation=participation,
                impact_bps=impact_bps,
                message=(
                    f"ADV participation {participation:.6f} exceeds cap "
                    f"{self.participation_cap:.6f}."
                ),
            )

        return ImpactGateResult(
            allowed=True,
            code="OK",
            participation=participation,
            impact_bps=impact_bps,
        )


class FundingGate:
    """Settlement and funding readiness checks."""

    def evaluate(
        self,
        intent: AllocationIntent,
        *,
        now_utc: dt.datetime,
        margin_utilization_post: float,
        margin_cap: float,
    ) -> tuple[IntentStatus, str]:
        if now_utc > intent.expires_at_utc:
            return IntentStatus.EXPIRED_INTENT, IntentStatus.EXPIRED_INTENT.value

        if intent.funding_source_status == FundingSourceStatus.PENDING_SALE_PROCEEDS:
            if intent.funding_available_at_utc is None or now_utc < intent.funding_available_at_utc:
                return IntentStatus.VALIDATED_WAIT_FUNDING, IntentStatus.VALIDATED_WAIT_FUNDING.value

        if intent.funding_source_status == FundingSourceStatus.MARGIN_UTILIZED:
            if float(margin_utilization_post) > float(margin_cap):
                return IntentStatus.REJECTED_FUNDING, "REJECTED_MARGIN_CAP"

        if intent.funding_source_status not in {
            FundingSourceStatus.SETTLED_CASH,
            FundingSourceStatus.MARGIN_UTILIZED,
            FundingSourceStatus.PENDING_SALE_PROCEEDS,
        }:
            return IntentStatus.REJECTED_FUNDING, "REJECTED_UNFUNDED"

        return IntentStatus.VALIDATED, "OK"



def enforce_price_slip(
    *,
    snapshot_price: Optional[float],
    execution_price: Optional[float],
    price_source_latency_ms: Optional[float],
    max_slippage_bps: float,
    max_latency_ms: float = 2000.0,
) -> PriceSlipResult:
    """Latency/slippage veto for submission safety."""
    latency = float(price_source_latency_ms or 0.0)
    if latency > float(max_latency_ms):
        return PriceSlipResult(
            allowed=False,
            code=IntentStatus.REJECTED_PRICE_SLIP.value,
            delta_bps=None,
        )

    if snapshot_price is None or execution_price is None or float(snapshot_price) <= 0:
        return PriceSlipResult(
            allowed=False,
            code=IntentStatus.REJECTED_PRICE_SLIP.value,
            delta_bps=None,
        )

    delta_bps = ((float(execution_price) - float(snapshot_price)) / float(snapshot_price)) * 10_000.0
    if abs(delta_bps) > float(max_slippage_bps):
        return PriceSlipResult(
            allowed=False,
            code=IntentStatus.REJECTED_PRICE_SLIP.value,
            delta_bps=delta_bps,
        )
    return PriceSlipResult(allowed=True, code="OK", delta_bps=delta_bps)


def _portfolio_variance(weights: list[float], covariance: list[list[float]]) -> float:
    size = len(weights)
    return sum(weights[i] * sum(covariance[i][j] * weights[j] for j in range(size)) for i in range(size))


def _group_mvc_ratio(
    weights: list[float],
    covariance: list[list[float]],
    group_indices: list[int],
    total_variance: float,
) -> float:
    if total_variance <= 1e-12:
        return 0.0
    size = len(weights)
    contribution = 0.0
    for index in group_indices:
        contribution += weights[index] * sum(covariance[index][j] * weights[j] for j in range(size))
    return contribution / total_variance


def build_covariance_matrix(
    symbols: List[str],
    lookback_days: int = 252,
) -> Dict[str, Dict[str, float]]:
    """Build a covariance matrix for the given symbols using historical daily returns.

    Downloads daily close prices via yfinance, computes daily log-returns, then
    applies Ledoit-Wolf shrinkage (via sklearn if available, otherwise sample covariance).

    Args:
        symbols: List of ticker symbols.
        lookback_days: Number of trading days of history to use (default 252 = 1 year).

    Returns:
        A dict-of-dicts keyed by symbol pair: ``{sym_i: {sym_j: covariance}}``.
        Returns an empty dict if data cannot be fetched for any symbol.
    """
    import numpy as np

    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance is required for build_covariance_matrix")
        return {}

    if not symbols:
        return {}

    unique_symbols = list(dict.fromkeys(sym.upper().strip() for sym in symbols if sym))
    if not unique_symbols:
        return {}

    try:
        period = f"{max(lookback_days + 60, 365)}d"
        raw = yf.download(
            unique_symbols,
            period=period,
            interval="1d",
            progress=False,
            auto_adjust=True,
        )
    except Exception as exc:
        logger.error("yfinance download failed in build_covariance_matrix: %s", exc)
        return {}

    if raw is None or raw.empty:
        return {}

    # Extract close series for each symbol.
    import pandas as pd

    if isinstance(raw.columns, pd.MultiIndex):
        close_level = "Close"
        if close_level not in raw.columns.get_level_values(0):
            return {}
        prices = raw[close_level]
        if isinstance(prices, pd.Series):
            prices = prices.to_frame(name=unique_symbols[0])
    else:
        if "Close" not in raw.columns:
            return {}
        prices = raw[["Close"]].rename(columns={"Close": unique_symbols[0]})

    # Keep only requested symbols that are present.
    available = [s for s in unique_symbols if s in prices.columns]
    if not available:
        return {}

    prices = prices[available].dropna(how="all")
    # Trim to lookback window.
    prices = prices.tail(lookback_days + 1)
    # Log-returns.
    returns = np.log(prices / prices.shift(1)).dropna()

    if len(returns) < 2:
        return {}

    ret_matrix = returns.values  # shape: (T, N)
    n = ret_matrix.shape[1]

    # Attempt Ledoit-Wolf shrinkage.
    cov_matrix: np.ndarray
    try:
        from sklearn.covariance import LedoitWolf  # type: ignore

        lw = LedoitWolf()
        lw.fit(ret_matrix)
        cov_matrix = lw.covariance_
    except ImportError:
        # Fall back to sample covariance.
        logger.debug("sklearn not available; using sample covariance for build_covariance_matrix")
        cov_matrix = np.cov(ret_matrix, rowvar=False).reshape(n, n)

    # Build dict-of-dicts.
    result: Dict[str, Dict[str, float]] = {}
    for i, sym_i in enumerate(available):
        result[sym_i] = {}
        for j, sym_j in enumerate(available):
            result[sym_i][sym_j] = float(cov_matrix[i, j])

    return result
