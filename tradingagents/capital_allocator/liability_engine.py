"""Liability and hurdle-rate engine for allocator net-edge decisions."""

from __future__ import annotations

import datetime as dt
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional, Protocol

from .contracts import IMPACT_K_BY_LANE, Lane, RegimeShock, ValuationMethodology

logger = logging.getLogger(__name__)

_SOFR_DEFAULT_BPS = 500.0
_DGS10_DEFAULT_PCT = 4.0
_CPI_YOY_DEFAULT_PCT = 3.0
_SOFR_CACHE_TTL_SECONDS = 86400  # 24 hours
_MACRO_CACHE_TTL_SECONDS = 86400  # 24 hours

_sofr_cache: dict = {}  # keys: "value_bps", "fetched_at"
_dgs10_cache: dict = {}  # keys: "value_pct", "fetched_at"
_cpi_cache: dict = {}  # keys: "yoy_pct", "fetched_at"


def _fetch_sofr_bps() -> float:
    """Fetch the latest SOFR rate from FRED and return it in basis points.

    Returns the cached value if fetched within the last 24 hours.
    Falls back to _SOFR_DEFAULT_BPS on any error or missing API key.
    """
    now = time.monotonic()
    if _sofr_cache.get("fetched_at") and now - _sofr_cache["fetched_at"] < _SOFR_CACHE_TTL_SECONDS:
        return float(_sofr_cache["value_bps"])

    api_key = os.getenv("FRED_API_KEY", "")
    if not api_key:
        return _SOFR_DEFAULT_BPS

    try:
        import urllib.request
        import json as _json

        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id=SOFR&api_key={api_key}&file_type=json&sort_order=desc&limit=1"
        )
        with urllib.request.urlopen(url, timeout=5) as resp:
            payload = _json.loads(resp.read().decode())

        observations = payload.get("observations", [])
        if not observations:
            return _SOFR_DEFAULT_BPS

        value_str = observations[0].get("value", ".")
        if value_str == ".":
            return _SOFR_DEFAULT_BPS

        rate_pct = float(value_str)  # FRED returns percentage, e.g. 5.30
        rate_bps = rate_pct * 100.0
        _sofr_cache["value_bps"] = rate_bps
        _sofr_cache["fetched_at"] = now
        return rate_bps
    except Exception as exc:
        logger.warning("FredSofrProvider: fetch failed (%s), using default %.0f bps", exc, _SOFR_DEFAULT_BPS)
        return _SOFR_DEFAULT_BPS


def _fetch_dgs10_pct() -> float:
    """Fetch the latest DGS10 (10-Year Treasury) rate from FRED and return it as a percentage.

    Returns the cached value if fetched within the last 24 hours.
    Falls back to _DGS10_DEFAULT_PCT on any error or missing API key.
    """
    now = time.monotonic()
    if _dgs10_cache.get("fetched_at") and now - _dgs10_cache["fetched_at"] < _MACRO_CACHE_TTL_SECONDS:
        return float(_dgs10_cache["value_pct"])

    api_key = os.getenv("FRED_API_KEY", "")
    if not api_key:
        return _DGS10_DEFAULT_PCT

    try:
        import urllib.request
        import json as _json

        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id=DGS10&api_key={api_key}&file_type=json&sort_order=desc&limit=1"
        )
        with urllib.request.urlopen(url, timeout=5) as resp:
            payload = _json.loads(resp.read().decode())

        observations = payload.get("observations", [])
        if not observations:
            return _DGS10_DEFAULT_PCT

        value_str = observations[0].get("value", ".")
        if value_str == ".":
            return _DGS10_DEFAULT_PCT

        rate_pct = float(value_str)  # FRED returns percentage, e.g. 4.25
        _dgs10_cache["value_pct"] = rate_pct
        _dgs10_cache["fetched_at"] = now
        return rate_pct
    except Exception as exc:
        logger.warning("FredDgs10Provider: fetch failed (%s), using default %.1f pct", exc, _DGS10_DEFAULT_PCT)
        return _DGS10_DEFAULT_PCT


def _fetch_cpi_yoy_pct() -> float:
    """Fetch the latest CPIAUCSL series from FRED, compute year-over-year % change, return as percentage.

    Returns the cached value if fetched within the last 24 hours.
    Falls back to _CPI_YOY_DEFAULT_PCT on any error or missing API key.
    """
    now = time.monotonic()
    if _cpi_cache.get("fetched_at") and now - _cpi_cache["fetched_at"] < _MACRO_CACHE_TTL_SECONDS:
        return float(_cpi_cache["yoy_pct"])

    api_key = os.getenv("FRED_API_KEY", "")
    if not api_key:
        return _CPI_YOY_DEFAULT_PCT

    try:
        import urllib.request
        import json as _json

        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id=CPIAUCSL&api_key={api_key}&file_type=json&sort_order=desc&limit=13"
        )
        with urllib.request.urlopen(url, timeout=5) as resp:
            payload = _json.loads(resp.read().decode())

        observations = payload.get("observations", [])
        if len(observations) < 2:
            return _CPI_YOY_DEFAULT_PCT

        # observations are in descending order (most recent first)
        current_val_str = observations[0].get("value", ".")
        prior_year_val_str = observations[12].get("value", ".")

        if current_val_str == "." or prior_year_val_str == ".":
            return _CPI_YOY_DEFAULT_PCT

        current_val = float(current_val_str)
        prior_year_val = float(prior_year_val_str)

        if prior_year_val <= 0:
            return _CPI_YOY_DEFAULT_PCT

        yoy_pct = ((current_val - prior_year_val) / prior_year_val) * 100.0
        _cpi_cache["yoy_pct"] = yoy_pct
        _cpi_cache["fetched_at"] = now
        return yoy_pct
    except Exception as exc:
        logger.warning("FredCpiProvider: fetch failed (%s), using default %.1f pct", exc, _CPI_YOY_DEFAULT_PCT)
        return _CPI_YOY_DEFAULT_PCT


@dataclass(frozen=True)
class LiabilityConfig:
    """Configuration for deterministic liability and carry adjustments."""

    internal_spread_bps: float = 200.0
    stale_daily_haircut_bps: float = 5.0
    stale_max_haircut_bps: float = 600.0


@dataclass(frozen=True)
class AssetLiabilityProfile:
    """Asset liquidity and valuation profile used for hurdle computation."""

    asset_class_id: str
    valuation_methodology: ValuationMethodology
    liquidity_horizon_days: int
    revaluation_interval_days: int
    lockup_days: int = 0


@dataclass(frozen=True)
class LiabilityInputs:
    """Runtime inputs used for liability evaluation per intent."""

    as_of_utc: dt.datetime
    lane: Lane
    regime: RegimeShock
    notional_usd: float
    nav_usd: float
    adv30_notional_usd: Optional[float]
    vol20d_bps: Optional[float]
    spread_floor_bps: float
    tax_cost_bps: float
    expected_edge_bps: float
    last_valuation_at_utc: Optional[dt.datetime]


@dataclass(frozen=True)
class LiabilityBreakdown:
    """Detailed components for allocator auditability."""

    hurdle_bps: float
    liquidity_premium_bps: float
    regime_premium_bps: float
    impact_bps: float
    stale_haircut_bps: float
    tax_cost_bps: float
    net_edge_bps: float
    participation: float


class RiskFreeRateProvider(Protocol):
    """Provider for risk-free carry benchmark."""

    def get_rf_bps(self, as_of_utc: dt.datetime) -> float: ...


class RegimePremiumProvider(Protocol):
    """Provider for regime-specific hurdle spread."""

    def get_regime_premium_bps(self, regime: RegimeShock) -> float: ...


class ConstantRiskFreeRateProvider:
    """Simple deterministic risk-free provider for tests/local operation."""

    def __init__(self, rf_bps: float = 500.0):
        self.rf_bps = float(rf_bps)

    def get_rf_bps(self, as_of_utc: dt.datetime) -> float:
        _ = as_of_utc
        return self.rf_bps


class FredSofrProvider:
    """Live SOFR risk-free rate provider backed by the FRED API.

    Fetches the latest SOFR observation from FRED, caches it for 24 hours,
    and falls back to _SOFR_DEFAULT_BPS if the API key is absent or the
    request fails.
    """

    def get_rf_bps(self, as_of_utc: dt.datetime) -> float:
        _ = as_of_utc
        return _fetch_sofr_bps()


class ConstantRegimePremiumProvider:
    """Deterministic regime premium defaults."""

    def __init__(self, premiums_bps: Optional[dict[RegimeShock, float]] = None):
        self.premiums_bps = premiums_bps or {
            RegimeShock.NORMAL: 0.0,
            RegimeShock.STRESS: 50.0,
            RegimeShock.SHOCK: 120.0,
            RegimeShock.CRISIS: 250.0,
        }

    def get_regime_premium_bps(self, regime: RegimeShock) -> float:
        return float(self.premiums_bps.get(regime, 0.0))


class LiabilityEngine:
    """Computes hurdle, impact, and stale-valuation penalties for net edge."""

    def __init__(
        self,
        config: Optional[LiabilityConfig] = None,
        risk_free_provider: Optional[RiskFreeRateProvider] = None,
        regime_provider: Optional[RegimePremiumProvider] = None,
    ):
        self.config = config or LiabilityConfig()
        self.risk_free_provider = risk_free_provider or FredSofrProvider()
        self.regime_provider = regime_provider or ConstantRegimePremiumProvider()

    @staticmethod
    def lane_k(lane: Lane) -> float:
        return float(IMPACT_K_BY_LANE[lane])

    @staticmethod
    def participation(notional_usd: float, adv30_notional_usd: Optional[float]) -> float:
        if adv30_notional_usd is None or float(adv30_notional_usd) <= 0:
            return float("inf")
        return max(0.0, float(notional_usd) / float(adv30_notional_usd))

    def impact_bps(
        self,
        *,
        lane: Lane,
        spread_floor_bps: float,
        vol20d_bps: Optional[float],
        participation: float,
    ) -> float:
        if participation == float("inf"):
            return float("inf")
        volatility = max(0.0, float(vol20d_bps or 0.0))
        return float(spread_floor_bps) + self.lane_k(lane) * volatility * (float(participation) ** 0.5)

    @staticmethod
    def liquidity_premium_bps(
        *,
        profile: AssetLiabilityProfile,
        notional_pct_nav: float,
    ) -> float:
        horizon_component = 40.0 * ((max(int(profile.liquidity_horizon_days), 1) / 30.0) ** 0.5)
        lockup_component = 60.0 * ((max(int(profile.lockup_days), 0) / 365.0) ** 0.5)
        size_component = 120.0 * (max(float(notional_pct_nav), 0.0) ** 0.5)
        return horizon_component + lockup_component + size_component

    def stale_haircut_bps(
        self,
        *,
        as_of_utc: dt.datetime,
        last_valuation_at_utc: Optional[dt.datetime],
        revaluation_interval_days: int,
    ) -> float:
        if last_valuation_at_utc is None:
            return float(self.config.stale_max_haircut_bps)
        overdue_days = (as_of_utc - last_valuation_at_utc).days - max(int(revaluation_interval_days), 1)
        if overdue_days <= 0:
            return 0.0
        haircut = float(overdue_days) * float(self.config.stale_daily_haircut_bps)
        return min(haircut, float(self.config.stale_max_haircut_bps))

    def hurdle_bps(
        self,
        *,
        as_of_utc: dt.datetime,
        regime: RegimeShock,
        liquidity_premium_bps: float,
    ) -> float:
        risk_free_bps = float(self.risk_free_provider.get_rf_bps(as_of_utc))
        regime_bps = float(self.regime_provider.get_regime_premium_bps(regime))
        return (
            risk_free_bps
            + float(self.config.internal_spread_bps)
            + float(liquidity_premium_bps)
            + regime_bps
        )

    def evaluate(
        self,
        *,
        profile: AssetLiabilityProfile,
        inputs: LiabilityInputs,
    ) -> LiabilityBreakdown:
        part = self.participation(inputs.notional_usd, inputs.adv30_notional_usd)
        impact = self.impact_bps(
            lane=inputs.lane,
            spread_floor_bps=inputs.spread_floor_bps,
            vol20d_bps=inputs.vol20d_bps,
            participation=part,
        )
        notional_pct_nav = (
            0.0 if float(inputs.nav_usd) <= 0.0 else float(inputs.notional_usd) / float(inputs.nav_usd)
        )
        liquidity = self.liquidity_premium_bps(
            profile=profile,
            notional_pct_nav=notional_pct_nav,
        )
        stale_haircut = self.stale_haircut_bps(
            as_of_utc=inputs.as_of_utc,
            last_valuation_at_utc=inputs.last_valuation_at_utc,
            revaluation_interval_days=profile.revaluation_interval_days,
        )
        hurdle = self.hurdle_bps(
            as_of_utc=inputs.as_of_utc,
            regime=inputs.regime,
            liquidity_premium_bps=liquidity,
        )
        net_edge = (
            float(inputs.expected_edge_bps)
            - impact
            - float(inputs.tax_cost_bps)
            - stale_haircut
            - hurdle
        )
        regime_premium = float(self.regime_provider.get_regime_premium_bps(inputs.regime))
        return LiabilityBreakdown(
            hurdle_bps=hurdle,
            liquidity_premium_bps=liquidity,
            regime_premium_bps=regime_premium,
            impact_bps=impact,
            stale_haircut_bps=stale_haircut,
            tax_cost_bps=float(inputs.tax_cost_bps),
            net_edge_bps=net_edge,
            participation=part,
        )
