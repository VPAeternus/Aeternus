"""CC Wyckoff Phase — Covered Call Wyckoff phase engine: converts scanner signals to portfolio order intents.

REGIME GATE (added after backtest 2026-03-02):
  S2 (rth_avoid) has 46.5% bleed rate across 20 years — coin flip.
  S4 (markdown_crush) has 51-57% but is rare (45-57 trades/20yr).
  Bleed rates are regime-dependent: 55-65% in bear, 28-41% in bull.

  Order intents are now ONLY emitted when close < SMA200 (bear regime),
  where the short edge is statistically meaningful. In bull regime,
  signals are available via CoveredCallScanner for display-only CC timing.

  Default: portfolio_include_cc_wyckoff=false (disabled entirely).
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TypedDict

from tradingagents.phase_engine import scanner


def _coerce_order_quantity(raw_qty: float, whole_shares: bool) -> float:
    qty = max(0.0, float(raw_qty))
    return float(int(qty)) if whole_shares else qty


def _build_client_order_id(plan_id: str, symbol: str, ordinal: int) -> str:
    compact = str(plan_id).replace("-", "")[:10]
    ticker = str(symbol or "").upper().strip()[:8]
    return f"{compact}-{ticker}-{int(ordinal):03d}"


def _fetch_reference_price_from_market(symbol: str, analysis_date: str):
    """Lazy import to avoid heavy tradingagents.graph import chain."""
    from tradingagents.graph import paper_execution as _pe
    return _pe._fetch_reference_price_from_market(symbol, analysis_date)


def _is_bear_regime(ticker: str) -> bool:
    """Check if ticker is below SMA200 (bear regime where short signals have edge).

    Returns True (pass gate) if:
      - close < SMA200 (bear regime, bleed rates 55-65%)
      - data unavailable (fail-open for safety)
    Returns False (block order) if close >= SMA200 (bull, bleed rates < 50%).
    """
    try:
        from tradingagents.phase_engine import data_engine
        df = data_engine.load(ticker)
        if df is None or len(df) < 200:
            return True  # insufficient data → fail-open
        sma200 = df["close"].rolling(200).mean().iloc[-1]
        close = df["close"].iloc[-1]
        if sma200 != sma200:  # NaN check
            return True
        return close < sma200
    except Exception:
        return True  # fail-open


class CCWyckoffPhaseSignal(TypedDict):
    ticker: str
    signal_name: str       # "rth_avoid", "markup_fade", etc.
    phase: str             # "MARK_UP", "MARK_DOWN", "DIST_ACCUM"
    close_price: float
    generated_at: str


class CCWyckoffPhaseEngine:
    def __init__(self, live: bool = False, require_bear_regime: bool = True):
        """live=True uses Alpaca real-time data instead of yfinance cache.
        require_bear_regime=True (default) gates order intents behind SMA200 bear check."""
        self._live = live
        self._require_bear_regime = require_bear_regime

    def get_signals(self, tickers: list[str] | None = None) -> list[CCWyckoffPhaseSignal]:
        """Run scanner for given tickers (default: config.UNIVERSE).
        Returns one signal per ticker that fires. Only RTH signals are
        included — overnight signals use a different execution model
        (close-to-open) that the portfolio pipeline doesn't support yet."""
        result = scanner.run_scan(tickers=tickers, live=self._live)
        signals: list[CCWyckoffPhaseSignal] = []
        now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
        for sig in result.get("signals", []):
            if sig.get("session", "rth") != "rth":
                continue
            signals.append(
                CCWyckoffPhaseSignal(
                    ticker=sig["ticker"],
                    signal_name=sig["signal"],
                    phase=sig["phase"],
                    close_price=sig["close"],
                    generated_at=now_iso,
                )
            )
        return signals

    def build_order_intents(
        self,
        signals: list[CCWyckoffPhaseSignal],
        plan_id: str,
        run_date: str,
        capital_usd: float,
        max_overlay_pct: float = 1.0,
        enforce_whole_shares: bool = False,
    ) -> list[dict]:
        """Convert signals → ExecutionOrderIntent dicts.

        Regime gate: only emits order intents for tickers below SMA200
        (bear regime) where short signals have statistical edge.
        """
        if not signals:
            return []

        per_signal_notional = (capital_usd * max_overlay_pct) / len(signals)
        now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
        intents: list[dict] = []
        ordinal = 0

        for sig in signals:
            # Regime gate: skip bull-regime tickers where bleed rate < 50%
            if self._require_bear_regime and not _is_bear_regime(sig["ticker"]):
                continue

            ref_price = _fetch_reference_price_from_market(sig["ticker"], run_date)
            if ref_price is None or ref_price <= 0:
                continue

            raw_qty = per_signal_notional / ref_price
            qty = _coerce_order_quantity(raw_qty, enforce_whole_shares)
            if qty <= 0:
                continue

            ordinal += 1
            order_intent_id = str(uuid.uuid4())
            intent = {
                "order_intent_id": order_intent_id,
                "client_order_id": _build_client_order_id(plan_id, sig["ticker"], ordinal),
                "idempotency_key": order_intent_id,
                "symbol": sig["ticker"],
                "side": "SELL",
                "order_type": "MARKET",
                "time_in_force": "DAY",
                "execution_mode": "",  # filled downstream
                "target_weight": 0.0,
                "target_notional_usd": round(qty * ref_price, 2),
                "reference_price": round(ref_price, 6),
                "reference_price_source": "market_snapshot",
                "target_quantity": qty,
                "quantity_policy": "WHOLE_SHARES" if enforce_whole_shares else "FRACTIONAL_OK",
                "aeternus_score": 0.0,
                "confidence": 0,
                "lane": "HEDGE",
                "intent_category": "HEDGE",
                "research_playbook": "CC_WYCKOFF_PHASE",
                "dominant_signal_family": sig["signal_name"],
                "queue_id": "",
                "rating_id": f"PHASE:{run_date}:{sig['ticker']}",
                "generated_at": now_iso,
            }
            intents.append(intent)

        return intents
