"""Market/reference price helpers for execution planning."""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Optional

import yfinance as yf


def parse_analysis_date(raw: str) -> dt.date:
    text = str(raw or "").strip()
    if not text:
        return dt.datetime.now(dt.timezone.utc).date()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return dt.datetime.now(dt.timezone.utc).date()


def extract_reference_price(item: Dict[str, Any], analysis: Dict[str, Any]) -> Optional[float]:
    aet_score = analysis.get("aeternus_score", {}) if isinstance(analysis, dict) else {}
    if isinstance(aet_score, dict):
        value = aet_score.get("price_at_rating")
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            pass

    market_data = analysis.get("market_data", {}) if isinstance(analysis, dict) else {}
    if isinstance(market_data, dict):
        try:
            close = market_data.get("close")
            if close is not None:
                return float(close)
        except (TypeError, ValueError):
            pass

    return None


def extract_last_close_from_frame(frame: Any) -> Optional[float]:
    if frame is None:
        return None
    try:
        if getattr(frame, "empty", True):
            return None
        close_col = frame.get("Close")
        if close_col is None:
            return None

        # yfinance may return a Series or DataFrame depending on shape.
        if hasattr(close_col, "dropna"):
            close_non_null = close_col.dropna()
            if getattr(close_non_null, "empty", True):
                return None
            if hasattr(close_non_null, "iloc"):
                last = close_non_null.iloc[-1]
                if hasattr(last, "iloc"):
                    # DataFrame row: take the first value.
                    last = last.iloc[0]
                return float(last)
    except Exception:
        return None
    return None


def fetch_reference_price_from_market(symbol: str, analysis_date: str) -> Optional[float]:
    ticker = str(symbol or "").upper().strip()
    if not ticker:
        return None

    anchor_date = parse_analysis_date(analysis_date)
    start = (anchor_date - dt.timedelta(days=7)).isoformat()
    end = (anchor_date + dt.timedelta(days=5)).isoformat()

    try:
        frame = yf.download(
            ticker,
            start=start,
            end=end,
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
        )
    except Exception:
        frame = None

    close = extract_last_close_from_frame(frame)
    if close is not None and close > 0:
        return float(close)

    # Final fallback: latest month snapshot when date-window request is empty.
    try:
        hist = yf.Ticker(ticker).history(period="1mo", interval="1d", auto_adjust=False)
    except Exception:
        hist = None
    close = extract_last_close_from_frame(hist)
    if close is not None and close > 0:
        return float(close)
    return None
