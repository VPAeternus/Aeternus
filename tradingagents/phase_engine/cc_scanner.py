"""
Aeternus Phase Engine — Covered Call Scanner
=============================================
Scans portfolio holdings for covered call timing signals from three sources:

1. CC Overbought: state == "cash" AND last_exit_type == "overbought"
   → momentum exhausted, stock will chop → sell covered call

2. CC Wyckoff Phase: S2 (rth_avoid) or S4 (markdown_crush)
   → stock will bleed in RTH → sell covered call

3. V3 Index RTH Skip: rth == False for QQQ/SPY
   → index covered call day

Outputs signal dicts for display (NOT order intents — can't execute options
through Alpaca). Displayed as a "Covered Call Opportunities" panel.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional

from .cc_overbought import CCOverboughtEngine
from .index_overlay import IndexOverlayEngine

# Index tickers handled by IndexOverlayEngine (not cc_overbought)
_INDEX_TICKERS: frozenset[str] = frozenset({"QQQ", "SPY"})


class CoveredCallScanner:
    """
    Scans tickers for covered call timing signals from CC Overbought,
    CC Wyckoff Phase, and V3 Index RTH Skip.  Returns signal dicts
    for display — no order intents (options can't be executed via Alpaca).
    """

    def __init__(self, live: bool = False) -> None:
        self.live = live
        self._regime_engine = CCOverboughtEngine()
        self._index_engine = IndexOverlayEngine()

    def get_signals(
        self,
        tickers: Optional[List[str]] = None,
        max_signals: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Scan tickers for covered call timing signals.

        For stocks: checks two conditions:
          1. CC Overbought: state == "cash" AND last_exit_type == "overbought"
          2. CC Wyckoff Phase: S2 (rth_avoid) or S4 (markdown_crush)

        For index tickers (QQQ/SPY): V3 RTH skip day (rth == False).

        Returns list of signal dicts capped at max_signals.
        """
        try:
            if tickers is None:
                from . import config
                tickers = config.UNIVERSE

            signals: List[Dict[str, Any]] = []
            now_iso = dt.datetime.now(dt.timezone.utc).isoformat()

            for ticker in tickers:
                if len(signals) >= max_signals:
                    break

                t = ticker.upper()

                if t in _INDEX_TICKERS:
                    self._check_index(t, signals, now_iso)
                else:
                    self._check_stock(t, signals, now_iso)

            return signals[:max_signals]

        except Exception:
            return []

    def _check_index(
        self, ticker: str, signals: List[Dict[str, Any]], now_iso: str
    ) -> None:
        """Check V3 RTH skip for index tickers."""
        sig = self._index_engine.get_signal(ticker)
        if not sig:
            return
        # V3 RTH skip day → sell covered call on index holding
        if not sig.get("rth"):
            signals.append({
                "ticker": ticker,
                "signal_type": "v3_rth_skip",
                "signal_detail": "rth_skip",
                "close": sig.get("close"),
                "regime": str(sig.get("active_leg") or ""),
                "date": sig.get("date", ""),
                "generated_at": now_iso,
            })

    def _check_stock(
        self, ticker: str, signals: List[Dict[str, Any]], now_iso: str
    ) -> None:
        """Check CC Overbought and CC Wyckoff for stock tickers."""
        # 1. CC Overbought: momentum exhaustion
        ob_sig = self._regime_engine.get_signal(ticker)
        if ob_sig and ob_sig.get("state") == "cash" and ob_sig.get("last_exit_type") == "overbought":
            signals.append({
                "ticker": ticker,
                "signal_type": "cc_overbought",
                "signal_detail": "overbought",
                "close": ob_sig.get("close"),
                "regime": ob_sig.get("regime", ""),
                "accel_percentile": ob_sig.get("accel_percentile"),
                "date": ob_sig.get("date", ""),
                "generated_at": now_iso,
            })
            return  # one signal per ticker

        # 2. CC Wyckoff Phase: S2/S4 signals
        try:
            from . import scanner as _scanner
            import io
            import sys
            # Suppress scanner's stdout output when called as a library
            old_stdout = sys.stdout
            sys.stdout = io.StringIO()
            try:
                scan_result = _scanner.run_scan(tickers=[ticker], live=self.live)
            finally:
                sys.stdout = old_stdout
            for ws in scan_result.get("signals", []):
                signal_name = ws.get("signal", "")
                if signal_name in ("rth_avoid", "markdown_crush"):
                    signals.append({
                        "ticker": ticker,
                        "signal_type": "cc_wyckoff",
                        "signal_detail": signal_name,
                        "close": ws.get("close"),
                        "regime": ws.get("phase", ""),
                        "date": ws.get("date", ""),
                        "generated_at": now_iso,
                    })
                    return  # one signal per ticker
        except Exception:
            pass

    def build_cc_recommendations(
        self, signals: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Format signals into a display-ready list of covered call recommendations.
        No order intents — options can't be executed through Alpaca paper mode.
        """
        return [
            {
                "ticker": s.get("ticker", ""),
                "signal_type": s.get("signal_type", ""),
                "signal_detail": s.get("signal_detail", ""),
                "close": s.get("close"),
                "regime": s.get("regime", ""),
                "date": s.get("date", ""),
            }
            for s in signals
        ]


# ─── Module-level convenience ──────────────────────────────────────────────────

def get_cc_signals(
    tickers: Optional[List[str]] = None,
    max_signals: int = 10,
    live: bool = False,
) -> List[Dict[str, Any]]:
    """One-call convenience. Scan → return covered call signal list."""
    try:
        scanner = CoveredCallScanner(live=live)
        return scanner.get_signals(tickers=tickers, max_signals=max_signals)
    except Exception:
        return []
