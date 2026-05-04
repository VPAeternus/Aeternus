"""Thematic sector rotation signal family for Deal Flow.

Measures 4-week vs 13-week performance acceleration of sector ETFs and
scores each universe symbol based on whether its sector is leading or lagging.
"""

from __future__ import annotations

import contextlib
import io
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd
import yfinance as yf

from ..contracts import DealFlowSignal, UniverseRow


# Hardcoded sector ETF map — covers all GICS sectors plus specialty sleeves.
SECTOR_ETF_MAP: Dict[str, str] = {
    "Technology": "XLK",
    "Semiconductors": "SMH",
    "Financials": "XLF",
    "Energy": "XLE",
    "Healthcare": "XLV",
    "Industrials": "XLI",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Materials": "XLB",
    "Communication Services": "XLC",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Biotechnology": "XBI",
    "Defense": "ITA",
}

# ETF ticker → sector reverse lookup (for ETFs in universe whose sector is in SECTOR_ETF_MAP).
_ETF_REVERSE: Dict[str, str] = {etf: sector for sector, etf in SECTOR_ETF_MAP.items()}

# Normalize variant sector names (yfinance, GICS official, etc.) → SECTOR_ETF_MAP keys.
_SECTOR_NORMALIZE: Dict[str, str] = {
    # Official GICS names → our keys
    "Information Technology": "Technology",
    "Health Care": "Healthcare",
    # yfinance names
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Defensive": "Consumer Staples",
    "Basic Materials": "Materials",
    "Financial Services": "Financials",
    "Financial": "Financials",
    # Other variants
    "Semiconductors & Semiconductor Equipment": "Semiconductors",
}


def collect_sector_rotation_signals(universe: Iterable[UniverseRow]) -> List[DealFlowSignal]:
    """Return one sector_rotation signal per universe symbol.

    Scores are anchored to sector ETF momentum (4w vs 13w acceleration).
    Sectors not covered by SECTOR_ETF_MAP receive a neutral score of 50.
    If the ETF download fails entirely, all signals are returned as NO_DATA.
    """
    rows = list(universe)
    if not rows:
        return []

    sector_scores, sector_meta = _compute_sector_scores()

    signals: List[DealFlowSignal] = []
    for row in rows:
        symbol = str(row.get("symbol", "")).upper().strip()
        if not symbol:
            continue

        sector = _resolve_sector(symbol, row)
        if sector_scores is None:
            # ETF download failed entirely.
            signals.append(_no_data_signal(symbol))
            continue

        if sector in sector_scores:
            raw = sector_scores[sector]
            meta = sector_meta.get(sector, {})
            rank_pct = meta.get("sector_rank_pct", 50.0)
            leadership = _leadership_tag(rank_pct)
            source_name = (
                f"sector_rotation:{sector}:{SECTOR_ETF_MAP.get(sector, 'N/A')}:"
                f"{leadership}"
            )
        else:
            # Unknown sector — neutral.
            raw = 50.0
            source_name = "sector_rotation:unknown"

        signals.append(
            {
                "symbol": symbol,
                "signal_family": "sector_rotation",
                "raw_score": float(round(raw, 4)),
                "z_score": 0.0,
                "direction": _direction_from_score(raw),
                "evidence_count": 1,
                "freshness_hours": 24.0,
                "source_status": "OK",
                "source_name": source_name,
            }
        )

    return signals


def _compute_sector_scores() -> tuple[Optional[Dict[str, float]], Dict[str, Dict[str, float]]]:
    """Download sector ETF data and compute acceleration-based scores.

    Returns:
        (sector_scores, sector_meta) where:
          sector_scores: sector name → 0-100 score, or None if download failed
          sector_meta:   sector name → dict with ret_4w_pct, ret_13w_pct,
                         acceleration, sector_rank_pct
    """
    etf_tickers = list(SECTOR_ETF_MAP.values())

    close_map = _download_sector_closes(etf_tickers)
    if close_map is None:
        return None, {}

    # Compute acceleration per sector ETF.
    acceleration_map: Dict[str, float] = {}
    raw_meta: Dict[str, Dict[str, float]] = {}

    for sector, etf in SECTOR_ETF_MAP.items():
        close = close_map.get(etf)
        if close is None or len(close) < 66:
            # Not enough data for 13-week return — skip this sector.
            continue

        ret_4w = _return_pct(close, 20)
        ret_13w = _return_pct(close, 65)
        if ret_4w is None or ret_13w is None:
            continue

        accel = ret_4w - ret_13w
        acceleration_map[sector] = accel
        raw_meta[sector] = {
            "ret_4w_pct": float(round(ret_4w, 4)),
            "ret_13w_pct": float(round(ret_13w, 4)),
            "acceleration": float(round(accel, 4)),
        }

    if not acceleration_map:
        return None, {}

    # Percentile-rank sectors by acceleration.
    rank_map = _percentile_rank_map(acceleration_map)

    sector_scores: Dict[str, float] = {}
    sector_meta: Dict[str, Dict[str, float]] = {}

    for sector, rank_pct in rank_map.items():
        score = _score_from_percentile(rank_pct)
        sector_scores[sector] = score
        meta = dict(raw_meta.get(sector, {}))
        meta["sector_rank_pct"] = float(round(rank_pct, 4))
        sector_meta[sector] = meta

    return sector_scores, sector_meta


def _download_sector_closes(tickers: Sequence[str]) -> Optional[Dict[str, pd.Series]]:
    """Download 100 days of daily close data for all sector ETFs in one batch.

    Returns a dict of ticker → close Series, or None if the download fails.
    """
    if not tickers:
        return None

    try:
        with _suppress_yf_noise():
            frame = yf.download(
                list(tickers),
                period="150d",
                interval="1d",
                auto_adjust=False,
                progress=False,
                group_by="ticker",
                threads=False,
            )
    except Exception:
        return None

    if frame is None or frame.empty:
        return None

    close_map: Dict[str, pd.Series] = {}
    for ticker in tickers:
        series = _extract_close_series(frame, ticker)
        if series is not None and not series.empty:
            close_map[ticker] = series

    return close_map if close_map else None


def _extract_close_series(frame: pd.DataFrame, symbol: str) -> Optional[pd.Series]:
    """Extract close price series for a single ticker from a multi-ticker frame."""
    if frame is None or frame.empty:
        return None

    try:
        if isinstance(frame.columns, pd.MultiIndex):
            if (symbol, "Close") in frame.columns:
                return pd.to_numeric(frame[(symbol, "Close")], errors="coerce").dropna()
            if ("Close", symbol) in frame.columns:
                return pd.to_numeric(frame[("Close", symbol)], errors="coerce").dropna()
            if symbol in frame.columns.get_level_values(0):
                sub = frame[symbol]
                if "Close" in sub.columns:
                    return pd.to_numeric(sub["Close"], errors="coerce").dropna()
            if "Close" in frame.columns.get_level_values(0):
                sub = frame.xs("Close", axis=1, level=0)
                if symbol in sub.columns:
                    return pd.to_numeric(sub[symbol], errors="coerce").dropna()
            return None

        if "Close" in frame.columns:
            return pd.to_numeric(frame["Close"], errors="coerce").dropna()
    except Exception:
        return None

    return None


def _return_pct(series: pd.Series, bars: int) -> Optional[float]:
    """Compute percentage return over the last `bars` trading days."""
    if series is None or len(series) <= bars:
        return None
    prev = float(series.iloc[-bars - 1])
    cur = float(series.iloc[-1])
    if prev == 0.0:
        return None
    return ((cur - prev) / prev) * 100.0


def _percentile_rank_map(values: Dict[str, float]) -> Dict[str, float]:
    """Map each key to its percentile rank (0-100) across all values."""
    if not values:
        return {}
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    if n == 1:
        return {items[0][0]: 50.0}
    return {key: (idx / float(n - 1)) * 100.0 for idx, (key, _) in enumerate(items)}


def _score_from_percentile(pct: float) -> float:
    """Convert a 0-100 percentile rank to a 0-100 signal score.

    Leading sectors (top third, pct > 66):  score in [60, 100]
    Lagging sectors (bottom third, pct < 33): score in [0, 40]
    Middle sectors (33 <= pct <= 66):         score in [40, 70]
    """
    if pct > 66.0:
        # Leading: 60 + 40 * (pct / 100)
        return _clamp(60.0 + 40.0 * (pct / 100.0), 60.0, 100.0)
    if pct < 33.0:
        # Lagging: 40 * (pct / 100)
        return _clamp(40.0 * (pct / 100.0), 0.0, 40.0)
    # Middle: 40 + 30 * (pct / 100)
    return _clamp(40.0 + 30.0 * (pct / 100.0), 40.0, 70.0)


def _resolve_sector(symbol: str, row: UniverseRow) -> str:
    """Resolve sector for a universe symbol.

    Universe rows now carry AKG-sourced GICS sector labels.
    Falls back to ETF reverse lookup for sector ETFs in the universe.
    """
    row_sector = str(row.get("sector", "")).strip()
    if row_sector and row_sector not in {"", "Unknown", "Unclassified Equity", "ETF", "Commodities"}:
        return _SECTOR_NORMALIZE.get(row_sector, row_sector)

    if symbol in _ETF_REVERSE:
        return _ETF_REVERSE[symbol]

    return _SECTOR_NORMALIZE.get(row_sector, row_sector) if row_sector else "Unknown"


def _leadership_tag(rank_pct: float) -> str:
    """Return LEADING, LAGGING, or NEUTRAL based on percentile rank."""
    if rank_pct > 66.0:
        return "LEADING"
    if rank_pct < 33.0:
        return "LAGGING"
    return "NEUTRAL"


def _no_data_signal(symbol: str) -> DealFlowSignal:
    return {
        "symbol": symbol,
        "signal_family": "sector_rotation",
        "raw_score": 0.0,
        "z_score": 0.0,
        "direction": "NEUTRAL",
        "evidence_count": 0,
        "freshness_hours": 9999.0,
        "source_status": "NO_DATA",
        "source_name": "sector_rotation_model",
    }


def _direction_from_score(score: float) -> str:
    if score >= 60.0:
        return "BULLISH"
    if score <= 40.0:
        return "BEARISH"
    return "NEUTRAL"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@contextlib.contextmanager
def _suppress_yf_noise():
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        yield
