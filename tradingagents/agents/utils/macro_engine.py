"""Pure Python macro regime computation engine.

No LLM calls. Fetches market data via yfinance and optionally FRED,
computes 4 sub-scores (regime fit, monetary stress, rate headwind,
commodity cycle), classifies the macro regime, and returns a typed
snapshot dict.

Entry point: build_macro_snapshot(ticker, sector, asset_class) -> dict
"""

import json
import logging
import os
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Session-level caches: macro data is market-wide; no need to re-fetch per ticker.
_MARKET_DATA_CACHE: dict | None = None
_FRED_CACHE: dict | None = None

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(value: Any) -> Optional[float]:
    """Convert value to float, returning None for missing/invalid."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned or cleaned.lower() in ("none", "n/a", "-", ".", ""):
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> int:
    """Clamp to [lo, hi] and return as int."""
    return int(max(lo, min(hi, value)))


def _20d_return(series) -> Optional[float]:
    """Compute 20-day return from a Close price series (pandas Series/list).

    Returns (close[-1] / close[-20] - 1) or None if insufficient data.
    """
    try:
        vals = series.dropna()
        if len(vals) < 21:
            return None
        return float(vals.iloc[-1] / vals.iloc[-20] - 1)
    except Exception:
        return None


def _rolling_mean(series, window: int) -> Optional[float]:
    """Return the most recent rolling mean of a pandas Series."""
    try:
        vals = series.dropna()
        if len(vals) < window:
            return None
        return float(vals.rolling(window).mean().iloc[-1])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Data Fetching
# ---------------------------------------------------------------------------

_TICKERS = ["SPY", "^VIX", "GLD", "SLV", "TLT", "UUP", "DBC", "BTC-USD", "HYG", "LQD", "EEM"]


def _fetch_market_data() -> Dict[str, Any]:
    """Download 6-month daily data for macro tickers via yfinance.

    Returns a dict mapping ticker -> Close price Series.
    On failure returns an empty dict.
    """
    global _MARKET_DATA_CACHE
    if _MARKET_DATA_CACHE is not None:
        return _MARKET_DATA_CACHE
    try:
        import yfinance as yf

        raw = yf.download(
            _TICKERS,
            period="6mo",
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=True,
        )

        # yf.download returns a MultiIndex DataFrame with (field, ticker) columns
        # Extract Close prices for each ticker
        close_data: Dict[str, Any] = {}
        if hasattr(raw.columns, "levels"):
            # MultiIndex
            if "Close" in raw.columns.get_level_values(0):
                close_frame = raw["Close"]
                for ticker in _TICKERS:
                    col = ticker
                    if col in close_frame.columns:
                        close_data[ticker] = close_frame[col].dropna()
            else:
                # Fallback: try first field level
                first_field = raw.columns.get_level_values(0)[0]
                close_frame = raw[first_field]
                for ticker in _TICKERS:
                    if ticker in close_frame.columns:
                        close_data[ticker] = close_frame[ticker].dropna()
        else:
            # Single ticker (shouldn't happen here but handle gracefully)
            if "Close" in raw.columns:
                close_data[_TICKERS[0]] = raw["Close"].dropna()

        _MARKET_DATA_CACHE = close_data
        return close_data

    except Exception as exc:
        logger.warning("macro_engine: yfinance download failed (%s)", exc)
        return {}


def _try_fetch_fred() -> Dict[str, Optional[float]]:
    """Fetch DGS10 and CPI YoY from FRED.

    Returns {"dgs10": float_or_None, "cpi_yoy": float_or_None}.
    Gracefully degrades to None values if FRED_API_KEY is absent or any error occurs.
    """
    global _FRED_CACHE
    if _FRED_CACHE is not None:
        return _FRED_CACHE
    result: Dict[str, Optional[float]] = {"dgs10": None, "dgs2": None, "cpi_yoy": None, "debt_to_gdp": None, "deficit_pct_gdp": None, "yield_curve_2s10s": None}

    api_key = os.getenv("FRED_API_KEY", "").strip()
    if not api_key:
        return result

    # --- DGS10 ---
    try:
        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id=DGS10&api_key={api_key}&file_type=json&sort_order=desc&limit=1"
        )
        with urllib.request.urlopen(url, timeout=5) as resp:
            payload = json.loads(resp.read().decode())

        observations = payload.get("observations", [])
        if observations:
            val_str = observations[0].get("value", ".")
            val = _safe_float(val_str)
            result["dgs10"] = val
    except Exception as exc:
        logger.warning("macro_engine: FRED DGS10 fetch failed (%s)", exc)

    # --- DGS2 ---
    try:
        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id=DGS2&api_key={api_key}&file_type=json&sort_order=desc&limit=1"
        )
        with urllib.request.urlopen(url, timeout=5) as resp:
            payload = json.loads(resp.read().decode())

        observations = payload.get("observations", [])
        if observations:
            val_str = observations[0].get("value", ".")
            val = _safe_float(val_str)
            result["dgs2"] = val
    except Exception as exc:
        logger.warning("macro_engine: FRED DGS2 fetch failed (%s)", exc)

    # --- Yield curve spread (2s10s) ---
    if result["dgs10"] is not None and result["dgs2"] is not None:
        result["yield_curve_2s10s"] = result["dgs10"] - result["dgs2"]
    else:
        result["yield_curve_2s10s"] = None

    # --- CPI YoY ---
    try:
        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id=CPIAUCSL&api_key={api_key}&file_type=json&sort_order=desc&limit=13"
        )
        with urllib.request.urlopen(url, timeout=5) as resp:
            payload = json.loads(resp.read().decode())

        observations = payload.get("observations", [])
        if len(observations) >= 13:
            current_str = observations[0].get("value", ".")
            prior_str = observations[12].get("value", ".")
            current = _safe_float(current_str)
            prior = _safe_float(prior_str)
            if current is not None and prior is not None and prior > 0:
                result["cpi_yoy"] = ((current - prior) / prior) * 100.0
    except Exception as exc:
        logger.warning("macro_engine: FRED CPI fetch failed (%s)", exc)

    # --- Debt-to-GDP ---
    try:
        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id=GFDEGDQ188S&api_key={api_key}&file_type=json&sort_order=desc&limit=1"
        )
        with urllib.request.urlopen(url, timeout=5) as resp:
            payload = json.loads(resp.read().decode())

        observations = payload.get("observations", [])
        if observations:
            val = _safe_float(observations[0].get("value", "."))
            result["debt_to_gdp"] = val
    except Exception as exc:
        logger.warning("macro_engine: FRED debt-to-GDP fetch failed (%s)", exc)

    # --- Federal Deficit % GDP ---
    try:
        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id=FYFSGDA188S&api_key={api_key}&file_type=json&sort_order=desc&limit=1"
        )
        with urllib.request.urlopen(url, timeout=5) as resp:
            payload = json.loads(resp.read().decode())

        observations = payload.get("observations", [])
        if observations:
            val = _safe_float(observations[0].get("value", "."))
            result["deficit_pct_gdp"] = val
    except Exception as exc:
        logger.warning("macro_engine: FRED deficit fetch failed (%s)", exc)

    _FRED_CACHE = result
    return result


# ---------------------------------------------------------------------------
# Regime Classification
# ---------------------------------------------------------------------------

def _classify_regime(
    spy_close: float,
    spy_sma20: float,
    spy_sma200: float,
    vix_close: float,
    spy_return_1d_pct: float,
    dgs10: Optional[float],
    cpi_yoy: Optional[float],
    yield_curve_2s10s: Optional[float] = None,
    hyg_vs_tlt: Optional[float] = None,
) -> Tuple[str, List[str]]:
    """Classify macro regime using ordered precedence rules.

    Returns (regime_label, list_of_trigger_strings).
    """
    triggers: List[str] = []

    spy_deviation_pct = (spy_close - spy_sma200) / spy_sma200 * 100 if spy_sma200 else 0.0

    # 1. VOL_SHOCK
    if vix_close >= 50 or abs(spy_return_1d_pct) >= 3.0:
        if vix_close >= 50:
            triggers.append(f"vix>={50}")
        if abs(spy_return_1d_pct) >= 3.0:
            triggers.append(f"|spy_1d_return|>={3}%")
        return "VOL_SHOCK", triggers

    # 2. BEAR
    if spy_close < spy_sma200:
        triggers.append("spy<sma200")
        return "BEAR", triggers

    # 3. HIGH_VOL
    if vix_close >= 30:
        triggers.append(f"vix>={30}")
        return "HIGH_VOL", triggers

    # 4. RISK_OFF
    if spy_close < spy_sma20 and vix_close >= 25:
        triggers.append("spy<sma20")
        triggers.append(f"vix>={25}")
        return "RISK_OFF", triggers

    # 5. INFLATION_SHOCK
    if cpi_yoy is not None and cpi_yoy >= 4.0:
        triggers.append(f"cpi_yoy>={4}%")
        return "INFLATION_SHOCK", triggers

    # 5.5 Yield curve inversion flag (augments triggers, does not override regime)
    if yield_curve_2s10s is not None and yield_curve_2s10s < -0.20:
        triggers.append("yield_curve_inverted")

    # 5.6 Credit spread stress flag (leading indicator — augments triggers only)
    if hyg_vs_tlt is not None and hyg_vs_tlt < -0.04:
        triggers.append("credit_spreads_widening")

    # 6. RATES_UPTREND
    if dgs10 is not None and dgs10 >= 4.5:
        triggers.append(f"dgs10>={4.5}%")
        return "RATES_UPTREND", triggers

    # 7. EUPHORIA
    if spy_deviation_pct >= 5.0 and vix_close <= 15:
        triggers.append(f"spy_deviation>={5}%")
        triggers.append(f"vix<={15}")
        return "EUPHORIA", triggers

    # 8. BULL
    if spy_close >= spy_sma200 and spy_sma20 >= spy_sma200 and vix_close <= 20:
        triggers.append("spy>=sma200")
        triggers.append("sma20>=sma200")
        triggers.append(f"vix<={20}")
        return "BULL", triggers

    # 9. NEUTRAL (fallback)
    triggers.append("no_primary_trigger")
    return "NEUTRAL", triggers


# ---------------------------------------------------------------------------
# Sub-score Computation
# ---------------------------------------------------------------------------

_REGIME_BASE_SCORES: Dict[str, int] = {
    "BULL": 78,
    "EUPHORIA": 68,
    "NEUTRAL": 52,
    "RATES_UPTREND": 42,
    "HIGH_VOL": 35,
    "RISK_OFF": 28,
    "INFLATION_SHOCK": 30,
    "BEAR": 22,
    "VOL_SHOCK": 12,
}


def _compute_regime_fit(regime: str, sector: str, asset_class: str) -> int:
    """Regime-fit sub-score (0-100), weight 0.25.

    Measures how favourable the current macro regime is for the asset.
    """
    base = _REGIME_BASE_SCORES.get(regime, 52)
    score = float(base)

    # Asset-class overrides for non-equities (applied first)
    if asset_class in ("Gold", "Silver"):
        if regime in ("BEAR", "VOL_SHOCK", "RISK_OFF"):
            score = 70.0
    elif asset_class == "Commodity":
        if regime == "INFLATION_SHOCK":
            score = 75.0
    elif asset_class == "Crypto":
        # Use equity base; bonus in inflation shock
        if regime == "INFLATION_SHOCK":
            score = base + 10.0

    # Sector adjustments for equities only
    if asset_class == "Equity" or asset_class not in ("Gold", "Silver", "Commodity", "Crypto"):
        if regime == "INFLATION_SHOCK":
            if "Energy" in sector or "Materials" in sector:
                score += 8.0
        if regime == "RATES_UPTREND":
            if "Technology" in sector or "Growth" in sector:
                score -= 5.0
        if regime in ("RISK_OFF", "BEAR"):
            if "Utilities" in sector or "Defensive" in sector or "Consumer Staples" in sector:
                score += 5.0

    return _clamp(score)


def _compute_monetary_stress(indicators: Dict[str, Optional[float]], asset_class: str) -> int:
    """Monetary-stress sub-score (0-100), weight 0.25.

    Positive stress = safe-haven demand rising, USD weakening, credit spreads widening.
    For equities: high stress is bearish. For gold/crypto: bullish.

    Credit spread signal: hyg_vs_tlt < 0 means HY underperforms Treasuries (spreads
    widening) → stress rising. Weight -0.15 means widening (negative) adds to composite.
    """
    gold_vs_spy = indicators.get("gold_vs_spy") or 0.0
    btc_vs_spy = indicators.get("btc_vs_spy") or 0.0
    usd_trend = indicators.get("usd_trend") or 0.0
    silver_vs_gold = indicators.get("silver_vs_gold") or 0.0
    hyg_vs_tlt = indicators.get("hyg_vs_tlt") or 0.0  # credit spread direction

    # Cap btc_vs_spy
    btc_vs_spy = max(-0.15, min(0.15, btc_vs_spy))

    composite = (
        0.35 * gold_vs_spy       # reduced from 0.45 to make room for credit signal
        + 0.15 * btc_vs_spy      # reduced from 0.20
        - 0.25 * usd_trend
        + 0.10 * silver_vs_gold
        - 0.15 * hyg_vs_tlt      # widening spreads (hyg_vs_tlt<0) → adds to stress
    )

    if asset_class in ("Gold", "Silver"):
        raw = 50.0 + 200.0 * composite
    elif asset_class == "Crypto":
        raw = 50.0 + 150.0 * composite
    elif asset_class == "Commodity":
        raw = 50.0 + 100.0 * composite
    else:
        # Equity default: stress is headwind
        raw = 50.0 - 200.0 * composite

    return _clamp(raw)


def _compute_rate_headwind(
    indicators: Dict[str, Optional[float]],
    sector: str,
    asset_class: str,
) -> int:
    """Rate-headwind sub-score (0-100), weight 0.25.

    Higher score = more rate-favourable environment.
    """
    dgs10 = indicators.get("dgs10")
    tlt_momentum = indicators.get("tlt_20d_return") or 0.0
    cpi_yoy = indicators.get("cpi_yoy")

    if dgs10 is not None:
        # Rate score from DGS10 level
        if dgs10 < 3.0:
            rate_score = 72.0
        elif dgs10 < 4.0:
            rate_score = 58.0
        elif dgs10 < 5.0:
            rate_score = 42.0
        else:
            rate_score = 28.0

        trend_score = float(_clamp(50.0 + 300.0 * tlt_momentum))

        if cpi_yoy is not None:
            if cpi_yoy < 2.0:
                inflation_score = 72.0
            elif cpi_yoy < 3.0:
                inflation_score = 58.0
            elif cpi_yoy < 4.0:
                inflation_score = 42.0
            else:
                inflation_score = 28.0
        else:
            inflation_score = 50.0

        yield_curve_2s10s = indicators.get("yield_curve_2s10s")
        if yield_curve_2s10s is not None:
            # Spread scoring: inverted is bad, steep is good
            if yield_curve_2s10s < 0:
                spread_score = 25.0
            elif yield_curve_2s10s < 0.5:
                spread_score = 40.0
            elif yield_curve_2s10s < 1.5:
                spread_score = 60.0
            else:
                spread_score = 75.0

            combined = (
                0.30 * rate_score
                + 0.25 * trend_score
                + 0.25 * inflation_score
                + 0.20 * spread_score
            )
        else:
            combined = 0.35 * rate_score + 0.30 * trend_score + 0.35 * inflation_score
    else:
        # FRED unavailable — use TLT as sole rate proxy
        combined = float(_clamp(50.0 + 300.0 * tlt_momentum))

    # Sector adjustments
    if "Technology" in sector or "Growth" in sector:
        combined *= 0.85
    elif "Value" in sector or "Financial" in sector:
        combined *= 1.05

    return _clamp(combined)


def _compute_commodity_cycle(
    indicators: Dict[str, Optional[float]],
    sector: str,
    asset_class: str,
) -> int:
    """Commodity-cycle sub-score (0-100), weight 0.25.

    Measures commodity tailwind/headwind for the asset.
    """
    dbc_momentum = indicators.get("dbc_20d_return") or 0.0
    gold_momentum = indicators.get("gld_20d_return") or 0.0

    if asset_class == "Gold":
        raw = 50.0 + 200.0 * gold_momentum
    elif asset_class == "Commodity":
        raw = 50.0 + 300.0 * dbc_momentum
    elif "Energy" in sector or "Materials" in sector:
        raw = 50.0 + 250.0 * dbc_momentum
    elif "Technology" in sector or "Consumer" in sector:
        raw = 50.0 - 150.0 * dbc_momentum
    else:
        # Default equities: mild commodity headwind
        raw = 50.0 - 80.0 * dbc_momentum

    return _clamp(raw)


# ---------------------------------------------------------------------------
# Cross-Asset Correlation Regime
# ---------------------------------------------------------------------------

# (label, ticker_a, ticker_b, expected_sign)
_CORR_PAIRS = [
    ("dollar_gold",   "UUP", "GLD", "negative"),
    ("dollar_em",     "UUP", "EEM", "negative"),
    ("equity_bond",   "SPY", "TLT", "negative"),
    ("equity_gold",   "SPY", "GLD", "negative"),
    ("gold_silver",   "GLD", "SLV", "positive"),
]


def _compute_correlation_regime(
    series_map: Dict[str, Any],
) -> Dict[str, Any]:
    """Compute rolling cross-asset correlations and classify each pair.

    Args:
        series_map: dict mapping ticker -> pandas Close price Series.

    Returns dict with 'pairs', 'broken_pairs', 'broken_count', 'summary'.
    """
    try:
        import pandas as pd
    except ImportError:
        return {"pairs": {}, "broken_pairs": [], "broken_count": 0, "summary": "pandas_unavailable"}

    pairs: Dict[str, Dict[str, Any]] = {}
    counts = {"NORMAL": 0, "WEAK": 0, "DECOUPLED": 0, "INVERTED": 0}

    for label, ticker_a, ticker_b, expected_sign in _CORR_PAIRS:
        sa = series_map.get(ticker_a)
        sb = series_map.get(ticker_b)
        if sa is None or sb is None:
            continue

        try:
            ra = sa.pct_change().dropna()
            rb = sb.pct_change().dropna()
            # Align on common index
            combined = pd.concat([ra, rb], axis=1, join="inner").dropna()
            if len(combined) < 25:
                continue

            col_a, col_b = combined.columns[0], combined.columns[1]
            corr_20 = combined[col_a].rolling(20).corr(combined[col_b]).iloc[-1]
            corr_60 = combined[col_a].rolling(60).corr(combined[col_b]).iloc[-1]

            if pd.isna(corr_20):
                continue

            # Classify state
            sign_matches = (
                (expected_sign == "negative" and corr_20 < 0)
                or (expected_sign == "positive" and corr_20 > 0)
            )
            abs_corr = abs(corr_20)

            if abs_corr < 0.15:
                state = "DECOUPLED"
            elif not sign_matches and abs_corr >= 0.30:
                state = "INVERTED"
            elif sign_matches and abs_corr >= 0.30:
                state = "NORMAL"
            else:
                state = "WEAK"

            counts[state] += 1
            pairs[label] = {
                "corr_20d": round(float(corr_20), 4),
                "corr_60d": round(float(corr_60), 4) if not pd.isna(corr_60) else None,
                "state": state,
                "expected_sign": expected_sign,
            }
        except Exception:
            continue

    broken = [lbl for lbl, info in pairs.items() if info["state"] in ("DECOUPLED", "INVERTED")]
    total = sum(counts.values())
    summary = (
        f"{counts['NORMAL']}/{total} NORMAL, {counts['WEAK']} WEAK, "
        f"{counts['DECOUPLED']} DECOUPLED, {counts['INVERTED']} INVERTED"
    ) if total > 0 else "no_pairs_computed"

    return {
        "pairs": pairs,
        "broken_pairs": broken,
        "broken_count": len(broken),
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Safe default snapshot
# ---------------------------------------------------------------------------

def _neutral_snapshot(ticker: str, sector: str, asset_class: str) -> Dict[str, Any]:
    """Return a safe neutral snapshot when market data is unavailable."""
    return {
        "regime": "NEUTRAL",
        "regime_triggers": ["data_unavailable"],
        "indicators": {
            "spy_close": None,
            "spy_sma20": None,
            "spy_sma200": None,
            "spy_deviation_pct": None,
            "spy_return_1d_pct": None,
            "vix_close": None,
            "gld_20d_return": None,
            "btc_20d_return": None,
            "tlt_20d_return": None,
            "uup_20d_return": None,
            "dbc_20d_return": None,
            "slv_20d_return": None,
            "dgs10": None,
            "dgs2": None,
            "yield_curve_2s10s": None,
            "cpi_yoy": None,
            "debt_to_gdp": None,
            "deficit_pct_gdp": None,
            "hyg_20d_return": None,
            "lqd_20d_return": None,
            "hyg_vs_tlt": None,
            "lqd_vs_tlt": None,
            "eem_20d_return": None,
            "credit_spread_regime": "STABLE",
            "real_rate": None,
        },
        "correlation_regime": {
            "pairs": {},
            "broken_pairs": [],
            "broken_count": 0,
            "summary": "data_unavailable",
        },
        "subscores": {
            "regime_fit": 50,
            "monetary_stress": 50,
            "rate_headwind": 50,
            "commodity_cycle": 50,
        },
        "composite_score": 50,
        "direction": "NEUTRAL",
        "asset_class": asset_class,
        "sector": sector,
        "data_coverage": 0.0,
        "fred_available": False,
    }


# ---------------------------------------------------------------------------
# Cache Pre-warming
# ---------------------------------------------------------------------------

def pre_warm_macro_cache() -> None:
    """Pre-warm market data and FRED caches before a batch run.

    Call once at batch start so all per-ticker Macro Reviewer nodes
    get cache hits instead of triggering network fetches mid-pipeline.
    Macro data is market-wide; it must not be fetched per-ticker.
    """
    _fetch_market_data()
    _try_fetch_fred()


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------

def build_macro_snapshot(
    ticker: str,
    sector: str = "",
    asset_class: str = "Equity",
) -> Dict[str, Any]:
    """Compute a macro regime snapshot for the given ticker context.

    Args:
        ticker: The ticker being analyzed (informational only; macro is market-wide).
        sector: Optional sector string for sector-level adjustments (e.g. "Technology").
        asset_class: One of "Equity", "Gold", "Silver", "Commodity", "Crypto".

    Returns:
        A dict with regime, indicators, subscores, composite_score, direction,
        asset_class, sector, data_coverage, and fred_available.
    """
    market_data = _fetch_market_data()

    if not market_data or "SPY" not in market_data or "^VIX" not in market_data:
        logger.warning("macro_engine: insufficient market data for %s — returning neutral snapshot", ticker)
        return _neutral_snapshot(ticker, sector, asset_class)

    fred = _try_fetch_fred()
    fred_available = fred.get("dgs10") is not None or fred.get("cpi_yoy") is not None or fred.get("dgs2") is not None
    dgs10 = fred.get("dgs10")
    cpi_yoy = fred.get("cpi_yoy")

    # --- Extract price series ---
    spy_series = market_data.get("SPY")
    vix_series = market_data.get("^VIX")
    gld_series = market_data.get("GLD")
    slv_series = market_data.get("SLV")
    tlt_series = market_data.get("TLT")
    uup_series = market_data.get("UUP")
    dbc_series = market_data.get("DBC")
    btc_series = market_data.get("BTC-USD")
    hyg_series = market_data.get("HYG")
    lqd_series = market_data.get("LQD")
    eem_series = market_data.get("EEM")

    # --- SPY scalars ---
    try:
        spy_close = float(spy_series.iloc[-1])
    except Exception:
        logger.warning("macro_engine: cannot read SPY close — returning neutral snapshot")
        return _neutral_snapshot(ticker, sector, asset_class)

    try:
        vix_close = float(vix_series.iloc[-1])
    except Exception:
        vix_close = 20.0  # benign default

    spy_sma20 = _rolling_mean(spy_series, 20) or spy_close
    spy_sma200 = _rolling_mean(spy_series, 200) or spy_close

    spy_deviation_pct = (spy_close - spy_sma200) / spy_sma200 * 100 if spy_sma200 else 0.0

    try:
        spy_close_prev = float(spy_series.iloc[-2])
        spy_return_1d_pct = (spy_close / spy_close_prev - 1) * 100
    except Exception:
        spy_return_1d_pct = 0.0

    # --- 20-day returns ---
    def _r(series) -> Optional[float]:
        if series is None:
            return None
        return _20d_return(series)

    gld_ret = _r(gld_series)
    btc_ret = _r(btc_series)
    tlt_ret = _r(tlt_series)
    uup_ret = _r(uup_series)
    dbc_ret = _r(dbc_series)
    slv_ret = _r(slv_series)
    spy_ret_20d = _r(spy_series)
    hyg_ret = _r(hyg_series)
    lqd_ret = _r(lqd_series)
    eem_ret = _r(eem_series)

    # Derived relative returns (default 0 when component missing)
    gold_vs_spy = (gld_ret or 0.0) - (spy_ret_20d or 0.0)
    btc_vs_spy = (btc_ret or 0.0) - (spy_ret_20d or 0.0)
    silver_vs_gold = (slv_ret or 0.0) - (gld_ret or 0.0)
    usd_trend = uup_ret or 0.0
    # Credit spread direction: HYG/LQD vs TLT (widening = negative = stress)
    hyg_vs_tlt = (hyg_ret or 0.0) - (tlt_ret or 0.0)
    lqd_vs_tlt = (lqd_ret or 0.0) - (tlt_ret or 0.0)
    # Real interest rate proxy (requires both FRED series)
    real_rate = (dgs10 - cpi_yoy) if (dgs10 is not None and cpi_yoy is not None) else None

    indicators: Dict[str, Any] = {
        "spy_close": round(spy_close, 4),
        "spy_sma20": round(spy_sma20, 4),
        "spy_sma200": round(spy_sma200, 4),
        "spy_deviation_pct": round(spy_deviation_pct, 4),
        "spy_return_1d_pct": round(spy_return_1d_pct, 4),
        "vix_close": round(vix_close, 4),
        "gld_20d_return": round(gld_ret, 6) if gld_ret is not None else None,
        "btc_20d_return": round(btc_ret, 6) if btc_ret is not None else None,
        "tlt_20d_return": round(tlt_ret, 6) if tlt_ret is not None else None,
        "uup_20d_return": round(uup_ret, 6) if uup_ret is not None else None,
        "dbc_20d_return": round(dbc_ret, 6) if dbc_ret is not None else None,
        "slv_20d_return": round(slv_ret, 6) if slv_ret is not None else None,
        "eem_20d_return": round(eem_ret, 6) if eem_ret is not None else None,
        "dgs10": round(dgs10, 4) if dgs10 is not None else None,
        "dgs2": round(fred.get("dgs2"), 4) if fred.get("dgs2") is not None else None,
        "yield_curve_2s10s": round(fred.get("yield_curve_2s10s"), 4) if fred.get("yield_curve_2s10s") is not None else None,
        "cpi_yoy": round(cpi_yoy, 4) if cpi_yoy is not None else None,
        "debt_to_gdp": round(fred.get("debt_to_gdp"), 2) if fred.get("debt_to_gdp") is not None else None,
        "deficit_pct_gdp": round(fred.get("deficit_pct_gdp"), 2) if fred.get("deficit_pct_gdp") is not None else None,
        # Credit spread signals (Capital Flows framework)
        "hyg_20d_return": round(hyg_ret, 6) if hyg_ret is not None else None,
        "lqd_20d_return": round(lqd_ret, 6) if lqd_ret is not None else None,
        "hyg_vs_tlt": round(hyg_vs_tlt, 6),
        "lqd_vs_tlt": round(lqd_vs_tlt, 6),
        "credit_spread_regime": (
            "TIGHTENING" if hyg_vs_tlt > 0.02
            else "WIDENING" if hyg_vs_tlt < -0.02
            else "STABLE"
        ),
        "real_rate": round(real_rate, 4) if real_rate is not None else None,
    }

    # Stress composite inputs dict
    stress_inputs: Dict[str, Optional[float]] = {
        "gold_vs_spy": gold_vs_spy,
        "btc_vs_spy": btc_vs_spy,
        "usd_trend": usd_trend,
        "silver_vs_gold": silver_vs_gold,
        "tlt_20d_return": tlt_ret,
        "gld_20d_return": gld_ret,
        "dbc_20d_return": dbc_ret,
        "dgs10": dgs10,
        "cpi_yoy": cpi_yoy,
        "yield_curve_2s10s": fred.get("yield_curve_2s10s"),
        "hyg_vs_tlt": hyg_vs_tlt,   # credit spread direction signal
        "lqd_vs_tlt": lqd_vs_tlt,   # IG spread direction signal
    }

    # --- Cross-asset correlation regime ---
    correlation_regime = _compute_correlation_regime(market_data)

    # --- Regime classification ---
    regime, regime_triggers = _classify_regime(
        spy_close=spy_close,
        spy_sma20=spy_sma20,
        spy_sma200=spy_sma200,
        vix_close=vix_close,
        spy_return_1d_pct=spy_return_1d_pct,
        dgs10=dgs10,
        cpi_yoy=cpi_yoy,
        yield_curve_2s10s=fred.get("yield_curve_2s10s"),
        hyg_vs_tlt=hyg_vs_tlt,
    )

    # --- Sub-scores ---
    regime_fit = _compute_regime_fit(regime, sector, asset_class)
    monetary_stress = _compute_monetary_stress(stress_inputs, asset_class)
    rate_headwind = _compute_rate_headwind(stress_inputs, sector, asset_class)
    commodity_cycle = _compute_commodity_cycle(stress_inputs, sector, asset_class)

    # --- Composite (equal weights 0.25 each) ---
    composite_score = _clamp(
        0.25 * regime_fit
        + 0.25 * monetary_stress
        + 0.25 * rate_headwind
        + 0.25 * commodity_cycle
    )

    # --- Direction ---
    if composite_score >= 60:
        direction = "BULLISH"
    elif composite_score <= 40:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    # --- Data coverage ---
    all_indicator_values = list(indicators.values())
    populated = sum(1 for v in all_indicator_values if v is not None)
    data_coverage = round(populated / len(all_indicator_values), 2) if all_indicator_values else 0.0

    return {
        "regime": regime,
        "regime_triggers": regime_triggers,
        "indicators": indicators,
        "correlation_regime": correlation_regime,
        "subscores": {
            "regime_fit": regime_fit,
            "monetary_stress": monetary_stress,
            "rate_headwind": rate_headwind,
            "commodity_cycle": commodity_cycle,
        },
        "composite_score": composite_score,
        "direction": direction,
        "asset_class": asset_class,
        "sector": sector,
        "data_coverage": data_coverage,
        "fred_available": fred_available,
    }
