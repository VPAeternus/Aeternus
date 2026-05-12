"""Market regime snapshot provider for SPY/VIX based hedging logic."""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

import pandas as pd
import yfinance as yf

from .contracts import MarketRegimeSnapshot


class MarketRegimeProvider:
    """Fetches SPY/VIX history and computes a deterministic regime snapshot."""

    def __init__(self, downloader: Optional[Callable[..., pd.DataFrame]] = None):
        self._downloader = downloader or yf.download

    def get_market_regime_snapshot(self) -> Optional[MarketRegimeSnapshot]:
        spy = self._fetch_close_series("SPY")
        qqq = self._fetch_close_series("QQQ")
        vix = self._fetch_close_series("^VIX")

        if spy is None or qqq is None or vix is None:
            return None
        if len(spy) < 210 or len(qqq) < 210:
            return None

        frame = pd.DataFrame({"spy": spy, "qqq": qqq, "vix": vix}).dropna()
        if len(frame) < 210:
            return None

        frame["spy_sma20"] = frame["spy"].rolling(20).mean()
        frame["spy_sma200"] = frame["spy"].rolling(200).mean()
        frame["spy_sma200_5d_ago"] = frame["spy_sma200"].shift(5)
        frame["qqq_sma20"] = frame["qqq"].rolling(20).mean()
        frame["qqq_sma200"] = frame["qqq"].rolling(200).mean()
        frame["qqq_sma200_5d_ago"] = frame["qqq_sma200"].shift(5)
        frame = frame.dropna()
        if frame.empty:
            return None

        latest = frame.iloc[-1]
        spy_close = float(latest["spy"])
        spy_sma20 = float(latest["spy_sma20"])
        spy_sma200 = float(latest["spy_sma200"])
        spy_sma200_5d_ago = float(latest["spy_sma200_5d_ago"])
        qqq_close = float(latest["qqq"])
        qqq_sma20 = float(latest["qqq_sma20"])
        qqq_sma200 = float(latest["qqq_sma200"])
        qqq_sma200_5d_ago = float(latest["qqq_sma200_5d_ago"])
        vix_close = float(latest["vix"])
        if spy_sma20 == 0 or qqq_sma20 == 0:
            return None

        spy_deviation_pct = ((spy_close - spy_sma20) / spy_sma20) * 100.0
        qqq_deviation_pct = ((qqq_close - qqq_sma20) / qqq_sma20) * 100.0

        return {
            "timestamp": datetime.now().isoformat(),
            "spy_close": spy_close,
            "spy_sma20": spy_sma20,
            "spy_sma200": spy_sma200,
            "spy_sma200_5d_ago": spy_sma200_5d_ago,
            "spy_deviation_pct": float(spy_deviation_pct),
            "qqq_close": qqq_close,
            "qqq_sma20": qqq_sma20,
            "qqq_sma200": qqq_sma200,
            "qqq_sma200_5d_ago": qqq_sma200_5d_ago,
            "qqq_deviation_pct": float(qqq_deviation_pct),
            "vix_close": vix_close,
        }

    def _fetch_close_series(self, symbol: str) -> Optional[pd.Series]:
        try:
            data = self._downloader(symbol, period="2y", interval="1d", progress=False)
        except Exception:
            return None

        if data is None or data.empty:
            return None

        if isinstance(data.columns, pd.MultiIndex):
            if ("Close", symbol) in data.columns:
                series = data[("Close", symbol)]
            elif "Close" in data.columns.get_level_values(0):
                series = data.xs("Close", axis=1, level=0).iloc[:, 0]
            else:
                return None
        else:
            if "Close" not in data.columns:
                return None
            series = data["Close"]

        series = pd.to_numeric(series, errors="coerce").dropna()
        if series.empty:
            return None
        return series
