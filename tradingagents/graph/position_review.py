"""Position Review Engine — adaptive, thesis-driven hold/exit recommendations.

Checks each open position for:
1. Thesis stress (pillar scores vs entry claims)
2. Score decay below V3 hurdle
3. Opportunity cost vs researched candidates

Returns per-position recommendations: HOLD, WATCH, EXIT, or ROTATE.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any, Dict, List, Optional


def review_positions(
    positions: dict,
    akg=None,
    pipeline_candidates: Optional[List[dict]] = None,
    v3_hurdle: float = 62.0,
) -> List[dict]:
    """Review all open positions and return adaptive recommendations.

    Args:
        positions: Open positions dict keyed by symbol (from positions.json).
        akg: AeternusKnowledgeGraph instance (for thesis stress + latest scores).
        pipeline_candidates: Top researched candidates (for opportunity cost check).
        v3_hurdle: Minimum score for portfolio inclusion (default 62).

    Returns:
        List of review dicts with recommendation per position.
    """
    results = []
    now = dt.datetime.now(dt.timezone.utc)

    # Build best-candidate score for opportunity cost comparison.
    best_candidate_score = 0.0
    best_candidate_symbol = None
    held_symbols = set(positions.keys())
    for cand in pipeline_candidates or []:
        sym = cand.get("symbol") or cand.get("ticker", "")
        score = float(
            cand.get("aeternus_score")
            or cand.get("investment_decision_score")
            or cand.get("score")
            or 0
        )
        if sym not in held_symbols and score > best_candidate_score:
            best_candidate_score = score
            best_candidate_symbol = sym

    for symbol, pos in positions.items():
        if not isinstance(pos, dict):
            continue

        entry_score = float(pos.get("entry_aeternus_score", 0) or 0)
        avg_price = float(pos.get("avg_price", 0) or 0)
        mark_price = float(pos.get("last_mark_price", 0) or 0)
        net_qty = float(pos.get("net_quantity", 0) or 0)

        # P&L %
        if avg_price > 0 and mark_price > 0:
            side = 1.0 if net_qty > 0 else -1.0
            pnl_pct = ((mark_price - avg_price) / avg_price) * side * 100.0
        else:
            pnl_pct = 0.0

        # Hold days
        opened_at = pos.get("opened_at", "")
        hold_days = 0
        if opened_at:
            try:
                opened_dt = dt.datetime.fromisoformat(
                    str(opened_at).replace("Z", "+00:00")
                )
                hold_days = (now - opened_dt).days
            except (ValueError, TypeError):
                pass

        # Current score from AKG
        current_score = entry_score  # fallback
        thesis_stress_level = "NONE"
        if akg is not None:
            node = akg._nodes.get(symbol, {})
            akg_score = node.get("last_aeternus_score")
            if akg_score is not None:
                current_score = float(akg_score)
            stress = akg.get_thesis_stress_report(symbol)
            thesis_stress_level = stress.get("stress_level", "NONE")

        # Annualized return and volatility
        ann_return_pct = 0.0
        ann_vol_pct = 0.0
        if avg_price > 0 and mark_price > 0 and hold_days > 0:
            total_return = (mark_price - avg_price) / avg_price
            if net_qty < 0:
                total_return = -total_return
            periods_per_year = 365.0 / hold_days
            ann_return_pct = ((1.0 + total_return) ** periods_per_year - 1.0) * 100.0
            # Estimate annualized vol from daily price range if available,
            # otherwise approximate from absolute return / sqrt(hold_days) * sqrt(252)
            daily_vol_approx = abs(total_return) / math.sqrt(max(hold_days, 1))
            ann_vol_pct = daily_vol_approx * math.sqrt(252) * 100.0

        # Max drawdown from high watermark
        max_dd_pct = 0.0
        if net_qty > 0:
            hwm = float(pos.get("high_watermark_price", mark_price) or mark_price)
            if hwm > 0:
                max_dd_pct = min(0.0, (mark_price - hwm) / hwm) * 100.0
        elif net_qty < 0:
            lwm = float(pos.get("low_watermark_price", mark_price) or mark_price)
            if lwm > 0:
                max_dd_pct = min(0.0, (lwm - mark_price) / lwm) * 100.0

        # --- Decision logic (evaluated in priority order) ---
        recommendation = "HOLD"
        reason = "Score above V3 hurdle"
        rotate_to = None

        # 1. Thesis stress CRITICAL (3+ pillars)
        if thesis_stress_level == "CRITICAL":
            recommendation = "EXIT"
            reason = "3+ thesis pillars stressed"

        # 2. Score below V3 hurdle
        elif current_score < v3_hurdle and current_score > 0:
            recommendation = "EXIT"
            reason = f"Score {current_score:.0f} below V3 hurdle ({v3_hurdle:.0f})"

        # 3. Thesis stress STRESS (2 pillars)
        elif thesis_stress_level == "STRESS":
            recommendation = "WATCH"
            reason = "2 thesis pillars stressed"

        # 4. Score decay 20%+ from entry
        elif entry_score > 0 and (entry_score - current_score) / entry_score >= 0.20:
            recommendation = "WATCH"
            decay_pct = (entry_score - current_score) / entry_score * 100
            reason = f"Score down {decay_pct:.0f}% from entry"

        # 5. Opportunity cost — pipeline candidate scores 20+ pts higher
        elif (
            best_candidate_symbol
            and best_candidate_score >= current_score + 20
        ):
            recommendation = "ROTATE"
            rotate_to = best_candidate_symbol
            reason = f"{best_candidate_symbol} scores {best_candidate_score:.0f} vs {current_score:.0f}"

        results.append({
            "symbol": symbol,
            "recommendation": recommendation,
            "reason": reason,
            "entry_score": round(entry_score, 1),
            "current_score": round(current_score, 1),
            "v3_hurdle": v3_hurdle,
            "thesis_stress": thesis_stress_level,
            "hold_days": hold_days,
            "pnl_pct": round(pnl_pct, 2),
            "ann_return_pct": round(ann_return_pct, 1),
            "ann_vol_pct": round(ann_vol_pct, 1),
            "max_dd_pct": round(max_dd_pct, 1),
            "rotate_to": rotate_to,
        })

    # Sort: EXIT first, then WATCH, then ROTATE, then HOLD
    priority = {"EXIT": 0, "WATCH": 1, "ROTATE": 2, "HOLD": 3}
    results.sort(key=lambda r: priority.get(r["recommendation"], 9))
    return results
