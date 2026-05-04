"""Kerberos %B(20,2) Vol Overlay — mechanical VXX put signal engine.

Signal: VXX %B(20,2) crosses above 1 → OPEN_PUT (buy ATM put).
Exit:   VXX %B(20,1) crosses below 1 → CLOSE_PUT, or expiry.

Backtest (VXX 2018-2026, ATM puts, 14-day DTE):
  78% WR | PF 11.41 | avg +137%/trade

Architecture mirrors AdaptiveHedgeEngine in hedging.py:
  compute_signal() → decide() → persist_state_and_orders() → evaluate()

Position state self-tracked in eval_results/kerberos_state.json.
Trade log in eval_results/kerberos_orders.json.
This is advisory — no automated equity execution.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd
import yfinance as yf

from .contracts import KerberosDecision, KerberosOrder, KerberosSignal
from .options_math import _bs_put


# ── Helpers (same pattern as hedging.py) ─────────────────────────────────────

def _now_iso() -> str:
    return datetime.now().isoformat()


def _today_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


# ── Signal math (ported from scripts/backtest_kerberos_pctb.py) ──────────────

def _compute_pct_b(close: pd.Series, period: int, num_sd: float) -> pd.Series:
    """%B = (Close - LowerBand) / (UpperBand - LowerBand)."""
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = sma + num_sd * std
    lower = sma - num_sd * std
    band_width = upper - lower
    return (close - lower) / band_width.replace(0, float("nan"))


class KerberosOverlayEngine:
    """Mechanical VXX put overlay: %B(20,2) entry, %B(20,1) exit.

    Mirrors AdaptiveHedgeEngine lifecycle:
      signal → decision → persist → single evaluate() entry point.
    """

    def __init__(
        self,
        state_path: str = "eval_results/kerberos_state.json",
        orders_path: str = "eval_results/kerberos_orders.json",
        put_dte: int = 14,
        risk_free_rate: float = 0.04,
        iv_multiplier: float = 1.5,
    ):
        self.state_path = Path(state_path)
        self.orders_path = Path(orders_path)
        self.put_dte = put_dte
        self.risk_free_rate = risk_free_rate
        self.iv_multiplier = iv_multiplier

        if not self.state_path.exists():
            _save_json(self.state_path, {
                "position_open": False,
                "last_action_date": None,
                "last_updated": _now_iso(),
            })
        if not self.orders_path.exists():
            _save_json(self.orders_path, [])

    # ── Step 1: Compute Signal ───────────────────────────────────────────────

    def compute_signal(self) -> KerberosSignal:
        """Fetch VXX + VIX, compute %B(20,2) and %B(20,1), detect crossovers."""
        now = _now_iso()
        try:
            vxx = yf.download("VXX", period="60d", auto_adjust=True, progress=False)
            vix = yf.download("^VIX", period="60d", auto_adjust=True, progress=False)
        except Exception:
            return self._insufficient_signal(now, 0)

        # Flatten MultiIndex columns if present
        for df in [vxx, vix]:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

        if vxx.empty or len(vxx) < 21:
            return self._insufficient_signal(now, len(vxx) if not vxx.empty else 0)

        close = vxx["Close"]
        pct_b_2sd = _compute_pct_b(close, 20, 2)
        pct_b_1sd = _compute_pct_b(close, 20, 1)

        curr_2sd = float(pct_b_2sd.iloc[-1]) if pd.notna(pct_b_2sd.iloc[-1]) else 0.0
        prev_2sd = float(pct_b_2sd.iloc[-2]) if len(pct_b_2sd) > 1 and pd.notna(pct_b_2sd.iloc[-2]) else 0.0
        curr_1sd = float(pct_b_1sd.iloc[-1]) if pd.notna(pct_b_1sd.iloc[-1]) else 0.0
        prev_1sd = float(pct_b_1sd.iloc[-2]) if len(pct_b_1sd) > 1 and pd.notna(pct_b_1sd.iloc[-2]) else 0.0

        entry_triggered = curr_2sd > 1.0 and prev_2sd <= 1.0
        exit_triggered = curr_1sd < 1.0 and prev_1sd >= 1.0

        vxx_close = float(close.iloc[-1])
        vix_close = 0.0
        if not vix.empty and "Close" in vix.columns:
            vix_aligned = vix["Close"].reindex(vxx.index, method="ffill")
            if pd.notna(vix_aligned.iloc[-1]):
                vix_close = float(vix_aligned.iloc[-1])

        return {
            "timestamp": now,
            "vxx_close": vxx_close,
            "vix_close": vix_close,
            "pct_b_2sd": round(curr_2sd, 4),
            "pct_b_1sd": round(curr_1sd, 4),
            "entry_triggered": entry_triggered,
            "exit_triggered": exit_triggered,
            "data_sufficient": True,
            "bars_available": len(vxx),
        }

    # ── Step 2: Decide ───────────────────────────────────────────────────────

    def decide(self, signal: KerberosSignal) -> KerberosDecision:
        """Signal + state → trade decision + put params."""
        empty_decision: KerberosDecision = {
            "action": "NO_SIGNAL",
            "status": "NO_SIGNAL",
            "reason": "",
            "put_strike": 0.0,
            "put_premium": 0.0,
            "put_dte": 0,
            "put_iv": 0.0,
            "vxx_spot": 0.0,
        }

        if not signal.get("data_sufficient", False):
            empty_decision["status"] = "DATA_INSUFFICIENT"
            empty_decision["reason"] = f"Insufficient data: {signal.get('bars_available', 0)} bars."
            return empty_decision

        state = _load_json(self.state_path, {})
        position_open = bool(state.get("position_open", False))
        today = _today_date()

        # Daily cooldown
        if state.get("last_action_date") == today:
            empty_decision["status"] = "SKIPPED_COOLDOWN"
            empty_decision["reason"] = "One action per day; cooldown active."
            empty_decision["vxx_spot"] = signal["vxx_close"]
            return empty_decision

        vxx_spot = signal["vxx_close"]
        vix_close = signal["vix_close"]

        # ── EXIT check ────────────────────────────────────────────────────
        if position_open and signal["exit_triggered"]:
            return {
                "action": "CLOSE_PUT",
                "status": "EXECUTED",
                "reason": "%B(20,1) crossed below 1 — exit signal.",
                "put_strike": 0.0,
                "put_premium": 0.0,
                "put_dte": 0,
                "put_iv": 0.0,
                "vxx_spot": vxx_spot,
            }

        # Check expiry
        if position_open:
            entry_date_str = state.get("entry_date")
            if entry_date_str:
                try:
                    entry_dt = datetime.strptime(entry_date_str, "%Y-%m-%d")
                    days_held = (datetime.now() - entry_dt).days
                    entry_dte = int(state.get("entry_put_dte", self.put_dte))
                    if days_held >= entry_dte:
                        return {
                            "action": "CLOSE_PUT",
                            "status": "EXECUTED",
                            "reason": f"Put expired after {days_held} days (DTE={entry_dte}).",
                            "put_strike": 0.0,
                            "put_premium": 0.0,
                            "put_dte": 0,
                            "put_iv": 0.0,
                            "vxx_spot": vxx_spot,
                        }
                except (ValueError, TypeError):
                    pass

        # ── ENTRY check ───────────────────────────────────────────────────
        if not position_open and signal["entry_triggered"]:
            iv = (vix_close / 100.0 * self.iv_multiplier) if vix_close > 0 else 0.80
            iv = max(iv, 0.20)
            strike = round(vxx_spot)
            T = self.put_dte / 365.0
            premium = _bs_put(vxx_spot, float(strike), T, self.risk_free_rate, iv)

            if premium <= 0.01:
                empty_decision["status"] = "NO_SIGNAL"
                empty_decision["reason"] = "Degenerate put pricing (premium ≤ $0.01)."
                empty_decision["vxx_spot"] = vxx_spot
                return empty_decision

            return {
                "action": "OPEN_PUT",
                "status": "EXECUTED",
                "reason": "%B(20,2) crossed above 1 — entry signal.",
                "put_strike": float(strike),
                "put_premium": round(premium, 4),
                "put_dte": self.put_dte,
                "put_iv": round(iv, 4),
                "vxx_spot": vxx_spot,
            }

        if position_open and not signal["exit_triggered"]:
            empty_decision["action"] = "HOLD"
            empty_decision["status"] = "SKIPPED_POSITION_OPEN"
            empty_decision["reason"] = "Position open; no exit signal."
            empty_decision["vxx_spot"] = vxx_spot
            return empty_decision

        empty_decision["reason"] = "No entry or exit crossover detected."
        empty_decision["vxx_spot"] = vxx_spot
        return empty_decision

    # ── Step 3: Persist ──────────────────────────────────────────────────────

    def persist_state_and_orders(
        self,
        signal: KerberosSignal,
        decision: KerberosDecision,
    ) -> Optional[KerberosOrder]:
        """Update state file and append order record on EXECUTED decisions."""
        state = _load_json(self.state_path, {})
        order_record: Optional[KerberosOrder] = None
        today = _today_date()

        if decision["status"] != "EXECUTED":
            state["last_updated"] = _now_iso()
            _save_json(self.state_path, state)
            return None

        if decision["action"] == "OPEN_PUT":
            state["position_open"] = True
            state["entry_date"] = today
            state["entry_vxx_spot"] = decision["vxx_spot"]
            state["entry_put_strike"] = decision["put_strike"]
            state["entry_put_premium"] = decision["put_premium"]
            state["entry_put_dte"] = decision["put_dte"]
            state["entry_put_iv"] = decision["put_iv"]
            state["entry_expiry_date"] = (
                datetime.now() + timedelta(days=decision["put_dte"])
            ).strftime("%Y-%m-%d")
            state["last_action_date"] = today
            state["last_updated"] = _now_iso()

            order_record = {
                "timestamp": _now_iso(),
                "action": "OPEN_PUT",
                "vxx_spot": decision["vxx_spot"],
                "put_strike": decision["put_strike"],
                "put_premium": decision["put_premium"],
                "put_dte": decision["put_dte"],
                "put_iv": decision["put_iv"],
                "exit_vxx_spot": 0.0,
                "exit_put_value": 0.0,
                "pnl_per_contract": 0.0,
                "return_on_premium_pct": 0.0,
                "hold_days": 0,
                "exit_reason": "",
            }

        elif decision["action"] == "CLOSE_PUT":
            entry_premium = float(state.get("entry_put_premium", 0.0))
            entry_strike = float(state.get("entry_put_strike", 0.0))
            entry_date_str = state.get("entry_date", "")
            entry_dte = int(state.get("entry_put_dte", self.put_dte))
            vxx_spot = decision["vxx_spot"]

            # Calculate exit put value
            days_held = 0
            if entry_date_str:
                try:
                    entry_dt = datetime.strptime(entry_date_str, "%Y-%m-%d")
                    days_held = (datetime.now() - entry_dt).days
                except (ValueError, TypeError):
                    pass

            expired = days_held >= entry_dte
            if expired:
                # At expiry: intrinsic only
                exit_value = max(entry_strike - vxx_spot, 0.0)
                exit_reason = "EXPIRY"
            else:
                # Before expiry: BS with remaining time
                remaining_T = max((entry_dte - days_held), 1) / 365.0
                iv = float(state.get("entry_put_iv", 0.80))
                exit_value = _bs_put(vxx_spot, entry_strike, remaining_T, self.risk_free_rate, iv)
                exit_reason = "SIGNAL"

            pnl = exit_value - entry_premium
            ret_pct = (pnl / entry_premium * 100.0) if entry_premium > 0 else 0.0

            state["position_open"] = False
            state["last_action_date"] = today
            state["last_updated"] = _now_iso()
            # Clear entry fields
            for k in [
                "entry_date", "entry_vxx_spot", "entry_put_strike",
                "entry_put_premium", "entry_put_dte", "entry_put_iv",
                "entry_expiry_date",
            ]:
                state.pop(k, None)

            order_record = {
                "timestamp": _now_iso(),
                "action": "CLOSE_PUT",
                "vxx_spot": float(state.get("entry_vxx_spot", vxx_spot)),
                "put_strike": entry_strike,
                "put_premium": entry_premium,
                "put_dte": entry_dte,
                "put_iv": float(state.get("entry_put_iv", 0.0)),
                "exit_vxx_spot": vxx_spot,
                "exit_put_value": round(exit_value, 4),
                "pnl_per_contract": round(pnl, 4),
                "return_on_premium_pct": round(ret_pct, 2),
                "hold_days": days_held,
                "exit_reason": exit_reason,
            }

        if order_record is not None:
            orders = _load_json(self.orders_path, [])
            orders.append(order_record)
            _save_json(self.orders_path, orders)

        _save_json(self.state_path, state)
        return order_record

    # ── Entry Point ──────────────────────────────────────────────────────────

    def evaluate(self) -> Tuple[KerberosSignal, KerberosDecision, Optional[KerberosOrder]]:
        """Run one full evaluation cycle: signal → decide → persist."""
        signal = self.compute_signal()
        decision = self.decide(signal)
        order = self.persist_state_and_orders(signal, decision)
        return signal, decision, order

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _insufficient_signal(timestamp: str, bars: int) -> KerberosSignal:
        return {
            "timestamp": timestamp,
            "vxx_close": 0.0,
            "vix_close": 0.0,
            "pct_b_2sd": 0.0,
            "pct_b_1sd": 0.0,
            "entry_triggered": False,
            "exit_triggered": False,
            "data_sufficient": False,
            "bars_available": bars,
        }
