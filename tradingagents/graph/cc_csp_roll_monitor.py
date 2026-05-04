"""CC/CSP Roll Monitor — evaluates registered short-option positions for roll decisions.

0DTE design: QQQ CCs and CSPs expire same day. The roll axis is *time to close*
(minutes left in session) rather than DTE. Position register is
eval_results/control/options_positions.json.

Usage:
    from tradingagents.graph.cc_csp_roll_monitor import evaluate_position, load_positions
"""

import datetime
import json
import math
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

import yfinance as yf

from tradingagents.graph.options_math import _bs_delta_call

_DEFAULT_PATH = Path("eval_results/control/options_positions.json")


class RollDecision(str, Enum):
    CC_HOLD_OTM = "CC_HOLD_OTM"                    # OTM, theta working
    CC_CLOSE_EARLY = "CC_CLOSE_EARLY"              # ≥75% premium captured
    CC_WATCH_ITM = "CC_WATCH_ITM"                  # ITM but extrinsic remains
    CC_ROLL_UP = "CC_ROLL_UP"                      # ITM, extrinsic depleted → roll same-day
    CC_ACCEPT_ASSIGNMENT = "CC_ACCEPT_ASSIGNMENT"  # < 60 min, let it expire ITM
    CSP_HOLD_OTM = "CSP_HOLD_OTM"
    CSP_CLOSE_EARLY = "CSP_CLOSE_EARLY"            # ≥80% premium captured
    CSP_WATCH_APPROACH = "CSP_WATCH_APPROACH"      # within 1% above strike
    CSP_ROLL_DOWN = "CSP_ROLL_DOWN"                # price below strike
    CSP_ACCEPT_ASSIGNMENT = "CSP_ACCEPT_ASSIGNMENT"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"


@dataclass
class RollResult:
    position: dict
    decision: RollDecision
    underlying_price: float
    option_mark: float          # (bid+ask)/2
    option_bid: float
    option_ask: float
    intrinsic: float
    extrinsic: float
    dte: int
    pct_captured: float         # 0.0–1.0
    roll_target_strike: Optional[float]
    roll_target_expiry: Optional[str]
    roll_target_bid: Optional[float]
    roll_net_debit: Optional[float]  # positive = pay, negative = collect
    rationale: str


def _session_minutes_remaining() -> int:
    """Minutes left in the NYSE regular session (9:30–16:00 ET)."""
    try:
        import pytz
        et = pytz.timezone("America/New_York")
    except ImportError:
        # Fallback: use UTC-5 approximation (close enough for display)
        et = datetime.timezone(datetime.timedelta(hours=-5))

    now_et = datetime.datetime.now(et)
    session_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    session_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)

    if now_et < session_open:
        return 390  # Before market open — full session remaining
    if now_et >= session_close:
        return 0
    return int((session_close - now_et).total_seconds() / 60)


def _is_expired(pos: dict) -> bool:
    """Return True if position expiry date is before today."""
    expiry_str = pos.get("expiry", "")
    if not expiry_str:
        return False
    try:
        expiry_date = datetime.date.fromisoformat(expiry_str)
        return expiry_date < datetime.date.today()
    except ValueError:
        return False


def evaluate_position(pos: dict, config: Optional[dict] = None) -> RollResult:
    """Evaluate a single registered CC or CSP position.

    Args:
        pos: Position dict from options_positions.json.
        config: Optional config overrides (keys: cc_roll_close_early_pct,
                csp_roll_close_early_pct, cc_roll_accept_assignment_mins).

    Returns:
        RollResult with decision and roll suggestion if applicable.
    """
    cfg = config or {}
    cc_close_pct = float(cfg.get("cc_roll_close_early_pct", 0.75))
    csp_close_pct = float(cfg.get("csp_roll_close_early_pct", 0.80))
    accept_mins = int(cfg.get("cc_roll_accept_assignment_mins", 60))

    ticker = pos.get("ticker", "")
    strike = float(pos.get("strike", 0))
    expiry = pos.get("expiry", "")
    credit = float(pos.get("credit_received", 0))
    pos_type = str(pos.get("type", "cc")).lower()

    _unavailable = lambda reason: RollResult(  # noqa: E731
        position=pos,
        decision=RollDecision.DATA_UNAVAILABLE,
        underlying_price=0.0,
        option_mark=0.0,
        option_bid=0.0,
        option_ask=0.0,
        intrinsic=0.0,
        extrinsic=0.0,
        dte=0,
        pct_captured=0.0,
        roll_target_strike=None,
        roll_target_expiry=None,
        roll_target_bid=None,
        roll_net_debit=None,
        rationale=f"Data unavailable: {reason}",
    )

    try:
        tkr = yf.Ticker(ticker)
        S = float(tkr.fast_info.last_price or 0)
        if S <= 0:
            # Fall back to previous close (always available)
            S = float(tkr.fast_info.previous_close or 0)
        if S <= 0:
            return _unavailable("could not fetch underlying price")

        # Fetch option chain for the given expiry
        chain = tkr.option_chain(expiry)
        calls_df = chain.calls
        puts_df = chain.puts

    except Exception as exc:
        return _unavailable(str(exc))

    # DTE calculation
    try:
        expiry_date = datetime.date.fromisoformat(expiry)
        dte = max(0, (expiry_date - datetime.date.today()).days)
    except ValueError:
        dte = 0

    mins_left = _session_minutes_remaining()

    # Look up our strike in the appropriate chain
    df = calls_df if pos_type == "cc" else puts_df
    row = df[df["strike"] == strike]
    if row.empty:
        return _unavailable(f"strike {strike} not found in {ticker} {expiry} chain")

    row = row.iloc[0]
    bid = float(row.get("bid", 0) or 0)
    ask = float(row.get("ask", 0) or 0)
    mark = (bid + ask) / 2.0

    if pos_type == "cc":
        intrinsic = max(S - strike, 0.0)
        extrinsic = max(mark - intrinsic, 0.0)
        pct_captured = max(0.0, (credit - mark) / credit) if credit > 0 else 0.0
        itm = S > strike

        if pct_captured >= cc_close_pct:
            decision = RollDecision.CC_CLOSE_EARLY
            rationale = (
                f"{pct_captured:.0%} of ${credit:.2f} credit captured (mark ${mark:.2f}). "
                "Buy to close and lock in profit."
            )
            return _build_result(pos, decision, S, mark, bid, ask, intrinsic, extrinsic,
                                 dte, pct_captured, None, None, None, None, rationale)

        if itm and mins_left < accept_mins:
            decision = RollDecision.CC_ACCEPT_ASSIGNMENT
            effective_sale = strike + credit
            rationale = (
                f"ACCEPT ASSIGNMENT (< {accept_mins} min to close). "
                f"{ticker} called away at ${strike:.2f}. "
                f"Effective sale: ${effective_sale:.2f} (strike + credit). "
                f"vs current ${S:.2f}. Not worth rolling — transaction cost > benefit."
            )
            return _build_result(pos, decision, S, mark, bid, ask, intrinsic, extrinsic,
                                 dte, pct_captured, None, None, None, None, rationale)

        if itm and extrinsic < 0.10 * credit:
            # 0DTE: roll to first OTM strike above S (ATM has max premium on 0DTE).
            # Multi-day: 2% OTM buffer gives enough room to avoid immediate re-test.
            roll_target_price = S if dte == 0 else S * 1.02
            target_row = calls_df[calls_df["strike"] >= roll_target_price].sort_values("strike").head(1)
            roll_strike = None
            roll_bid = None
            roll_debit = None
            if not target_row.empty:
                roll_strike = float(target_row.iloc[0]["strike"])
                roll_bid = float(target_row.iloc[0].get("bid", 0) or 0)
                roll_debit = ask - roll_bid  # pay ask to close, receive bid on new strike

            decision = RollDecision.CC_ROLL_UP
            debit_str = f"${roll_debit:.2f} {'debit' if roll_debit and roll_debit > 0 else 'credit'}" if roll_debit is not None else "N/A"
            rationale = (
                f"ITM by ${S - strike:.2f}. Extrinsic ${extrinsic:.2f} < 10% of credit. "
                f"Roll up to ${roll_strike} call ({debit_str}). "
                f"Expiry: {expiry}."
            )
            return _build_result(pos, decision, S, mark, bid, ask, intrinsic, extrinsic,
                                 dte, pct_captured, roll_strike, expiry, roll_bid, roll_debit, rationale)

        if itm:
            decision = RollDecision.CC_WATCH_ITM
            rationale = (
                f"ITM by ${S - strike:.2f} but extrinsic ${extrinsic:.2f} still > 10% of credit. "
                "Monitor. Roll if extrinsic continues to bleed."
            )
        else:
            decision = RollDecision.CC_HOLD_OTM
            rationale = (
                f"OTM by ${strike - S:.2f}. Theta decay working. "
                f"Mark ${mark:.2f}, {pct_captured:.0%} captured."
            )

        return _build_result(pos, decision, S, mark, bid, ask, intrinsic, extrinsic,
                             dte, pct_captured, None, None, None, None, rationale)

    else:  # csp
        intrinsic = max(strike - S, 0.0)
        extrinsic = max(mark - intrinsic, 0.0)
        pct_captured = max(0.0, (credit - mark) / credit) if credit > 0 else 0.0
        itm = S < strike  # put is ITM when price below strike
        near_strike = (strike * 0.99) < S < strike  # within 1% above strike

        if pct_captured >= csp_close_pct:
            decision = RollDecision.CSP_CLOSE_EARLY
            rationale = (
                f"{pct_captured:.0%} of ${credit:.2f} credit captured (mark ${mark:.2f}). "
                "Buy to close and lock in profit."
            )
            return _build_result(pos, decision, S, mark, bid, ask, intrinsic, extrinsic,
                                 dte, pct_captured, None, None, None, None, rationale)

        if itm and mins_left < accept_mins:
            decision = RollDecision.CSP_ACCEPT_ASSIGNMENT
            effective_cost = strike - credit
            rationale = (
                f"ACCEPT ASSIGNMENT (< {accept_mins} min to close). "
                f"{ticker} put to you at ${strike:.2f}. "
                f"Effective cost basis: ${effective_cost:.2f} (strike - credit). "
                f"vs current ${S:.2f}."
            )
            return _build_result(pos, decision, S, mark, bid, ask, intrinsic, extrinsic,
                                 dte, pct_captured, None, None, None, None, rationale)

        if near_strike:
            decision = RollDecision.CSP_WATCH_APPROACH
            rationale = (
                f"Price ${S:.2f} within 1% of put strike ${strike:.2f}. "
                "Monitor closely — approaching assignment territory."
            )
            return _build_result(pos, decision, S, mark, bid, ask, intrinsic, extrinsic,
                                 dte, pct_captured, None, None, None, None, rationale)

        if itm:
            # 0DTE: roll to first OTM put below S (ATM has max premium on 0DTE).
            # Multi-day: 5% buffer avoids immediately re-entering assignment risk.
            roll_target_price = S if dte == 0 else S * 0.95
            target_row = puts_df[puts_df["strike"] <= roll_target_price].sort_values("strike", ascending=False).head(1)
            roll_strike = None
            roll_bid = None
            roll_debit = None
            if not target_row.empty:
                roll_strike = float(target_row.iloc[0]["strike"])
                roll_bid = float(target_row.iloc[0].get("bid", 0) or 0)
                roll_debit = ask - roll_bid

            decision = RollDecision.CSP_ROLL_DOWN
            debit_str = f"${roll_debit:.2f} {'debit' if roll_debit and roll_debit > 0 else 'credit'}" if roll_debit is not None else "N/A"
            rationale = (
                f"ITM by ${strike - S:.2f}. "
                f"Roll down to ${roll_strike} put ({debit_str}). "
                f"Expiry: {expiry}."
            )
            return _build_result(pos, decision, S, mark, bid, ask, intrinsic, extrinsic,
                                 dte, pct_captured, roll_strike, expiry, roll_bid, roll_debit, rationale)

        else:
            decision = RollDecision.CSP_HOLD_OTM
            rationale = (
                f"OTM by ${S - strike:.2f}. Theta decay working. "
                f"Mark ${mark:.2f}, {pct_captured:.0%} captured."
            )

        return _build_result(pos, decision, S, mark, bid, ask, intrinsic, extrinsic,
                             dte, pct_captured, None, None, None, None, rationale)


def _build_result(
    pos, decision, S, mark, bid, ask, intrinsic, extrinsic,
    dte, pct_captured, roll_strike, roll_expiry, roll_bid, roll_debit, rationale
) -> RollResult:
    return RollResult(
        position=pos,
        decision=decision,
        underlying_price=S,
        option_mark=mark,
        option_bid=bid,
        option_ask=ask,
        intrinsic=intrinsic,
        extrinsic=extrinsic,
        dte=dte,
        pct_captured=pct_captured,
        roll_target_strike=roll_strike,
        roll_target_expiry=roll_expiry,
        roll_target_bid=roll_bid,
        roll_net_debit=roll_debit,
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# Position register I/O
# ---------------------------------------------------------------------------

def _resolve_path(path: Optional[Path]) -> Path:
    return Path(path) if path else _DEFAULT_PATH


def load_positions(path: Optional[Path] = None) -> list:
    """Load active positions, auto-expiring stale ones."""
    p = _resolve_path(path)
    if not p.exists():
        return []
    try:
        positions = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(positions, list):
        return []

    # Auto-mark expired positions
    today = datetime.date.today().isoformat()
    changed = False
    for pos in positions:
        if pos.get("status") == "active" and _is_expired(pos):
            pos["status"] = "expired"
            pos["expired_at"] = today
            changed = True

    if changed:
        save_positions(positions, path)

    return positions


def save_positions(positions: list, path: Optional[Path] = None) -> None:
    p = _resolve_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(positions, indent=2), encoding="utf-8")


def add_position(pos_dict: dict, path: Optional[Path] = None) -> str:
    """Add a new position to the register. Returns the assigned ID."""
    positions = load_positions(path)
    pos_id = str(uuid.uuid4())[:8]
    pos_dict["id"] = pos_id
    pos_dict["registered_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    pos_dict.setdefault("status", "active")
    pos_dict.setdefault("notes", "")
    positions.append(pos_dict)
    save_positions(positions, path)
    return pos_id


def close_position(pos_id: str, path: Optional[Path] = None) -> bool:
    """Mark a position as closed. Returns True if found and updated."""
    positions = load_positions(path)
    for pos in positions:
        if pos.get("id") == pos_id:
            pos["status"] = "closed"
            pos["closed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            save_positions(positions, path)
            return True
    return False
