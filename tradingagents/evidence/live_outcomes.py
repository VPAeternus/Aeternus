"""Live outcome analysis — bridges execution results back to evidence pipeline.

Reads closed trades and track record entries, matches them to original
analysis predictions by rating_id, and computes realized-vs-predicted
performance metrics.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def build_live_outcome_report(
    closed_trades_paths: Optional[List[str]] = None,
    track_record_path: str = "eval_results/track_record.json",
    batch_analysis_dir: str = "eval_results/deal_flow",
) -> Dict[str, Any]:
    """Build a report comparing predicted analysis outcomes to actual trade results.

    Joins closed trades (from paper/live execution) with original batch analysis
    items via rating_id to compute prediction accuracy, directional hit rate,
    and slippage between predicted and actual returns.

    Returns a dict with overall metrics, breakdowns by lane/playbook/confidence,
    and individual matched trade records.
    """
    # Load closed trades from all execution paths.
    if closed_trades_paths is None:
        closed_trades_paths = [
            "eval_results/paper_execution/closed_trades.json",
            "eval_results/live_execution/closed_trades.json",
        ]

    all_closed: List[Dict[str, Any]] = []
    for path_str in closed_trades_paths:
        trades = _read_json_list(path_str)
        for trade in trades:
            trade["_source_path"] = path_str
        all_closed.extend(trades)

    if not all_closed:
        return _empty_report("NO_CLOSED_TRADES")

    # Load track record for enrichment.
    track_entries = _read_json_list(track_record_path)
    track_by_id: Dict[str, Dict[str, Any]] = {}
    for entry in track_entries:
        rid = str(entry.get("rating_id", "")).strip()
        if rid:
            track_by_id[rid] = entry

    # Load batch analysis items indexed by rating_id.
    analysis_by_id = _load_analysis_items_by_rating_id(batch_analysis_dir)

    # Match and compute metrics.
    matched: List[Dict[str, Any]] = []
    unmatched_count = 0

    for trade in all_closed:
        rating_ids = trade.get("rating_ids", [])
        if not isinstance(rating_ids, list):
            rating_ids = [str(rating_ids)] if rating_ids else []

        trade_record = _build_trade_record(trade)
        found_match = False

        for rid in rating_ids:
            rid = str(rid).strip()
            if not rid:
                continue

            analysis_item = analysis_by_id.get(rid)
            track_entry = track_by_id.get(rid)

            if analysis_item or track_entry:
                found_match = True
                trade_record["rating_id"] = rid
                trade_record["analysis"] = _extract_analysis_prediction(
                    analysis_item, track_entry
                )
                trade_record["comparison"] = _compute_comparison(
                    trade_record, trade_record["analysis"]
                )
                break

        if found_match:
            matched.append(trade_record)
        else:
            unmatched_count += 1

    if not matched:
        return _empty_report("NO_MATCHED_TRADES")

    # Aggregate metrics.
    overall = _aggregate_metrics(matched)
    by_lane = _group_and_aggregate(matched, "lane")
    by_playbook = _group_and_aggregate(matched, "research_playbook")
    by_confidence = _group_and_aggregate(matched, "_confidence_bucket")
    by_exit_rule = _group_and_aggregate(matched, "exit_rule")

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": "COMPLETE",
        "total_closed_trades": len(all_closed),
        "matched_to_analysis": len(matched),
        "unmatched_trades": unmatched_count,
        "overall": overall,
        "by_lane": by_lane,
        "by_playbook": by_playbook,
        "by_confidence": by_confidence,
        "by_exit_rule": by_exit_rule,
        "trades": matched,
    }


def _build_trade_record(trade: Dict[str, Any]) -> Dict[str, Any]:
    """Extract normalized fields from a closed trade event."""
    return {
        "symbol": str(trade.get("symbol", "")).upper(),
        "close_date": str(trade.get("close_date", "")),
        "close_price": _to_float(trade.get("close_price")),
        "avg_entry_price": _to_float(trade.get("avg_entry_price")),
        "pnl_usd": _to_float(trade.get("pnl_usd")),
        "return_pct": _to_float(trade.get("return_pct")),
        "net_quantity": _to_float(trade.get("net_quantity")),
        "lane": str(trade.get("lane") or "UNKNOWN").upper(),
        "research_playbook": str(trade.get("research_playbook") or "UNKNOWN"),
        "exit_rule": str(trade.get("exit_rule") or "MANUAL"),
        "exit_reason": str(trade.get("exit_reason") or ""),
        "close_source": str(trade.get("close_source") or ""),
        "rating_ids": trade.get("rating_ids", []),
    }


def _extract_analysis_prediction(
    analysis_item: Optional[Dict[str, Any]],
    track_entry: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Extract the original prediction from analysis item and/or track record."""
    prediction: Dict[str, Any] = {
        "rating": None,
        "recommendation": None,
        "confidence": None,
        "price_at_rating": None,
        "price_target": None,
        "predicted_direction": None,
        "predicted_return_pct": None,
    }

    source = track_entry or analysis_item or {}

    recommendation = source.get("recommendation")
    if recommendation:
        rec_label = str(recommendation).upper()
        prediction["recommendation"] = str(recommendation)
        if "BUY" in rec_label:
            prediction["predicted_direction"] = "LONG"
        elif "SELL" in rec_label:
            prediction["predicted_direction"] = "SHORT"
        elif "HOLD" in rec_label:
            prediction["predicted_direction"] = "NEUTRAL"

    rating = source.get("rating") or source.get("aeternus_rating")
    if rating:
        prediction["rating"] = str(rating)
        if prediction["predicted_direction"] is None and "Buy" in str(rating):
            prediction["predicted_direction"] = "LONG"
        elif prediction["predicted_direction"] is None and "Sell" in str(rating):
            prediction["predicted_direction"] = "SHORT"
        elif prediction["predicted_direction"] is None:
            prediction["predicted_direction"] = "NEUTRAL"

    confidence = source.get("confidence") or source.get("aeternus_confidence")
    if confidence is not None:
        prediction["confidence"] = _to_float(confidence)

    price_at = source.get("price_at_rating") or source.get("entry_price")
    if price_at is not None:
        prediction["price_at_rating"] = _to_float(price_at)

    target = source.get("price_target")
    if target is not None:
        prediction["price_target"] = _to_float(target)

    if prediction["price_at_rating"] and prediction["price_target"]:
        predicted_return = (
            (prediction["price_target"] - prediction["price_at_rating"])
            / prediction["price_at_rating"]
        ) * 100.0
        prediction["predicted_return_pct"] = round(predicted_return, 4)

    return prediction


def _compute_comparison(
    trade: Dict[str, Any],
    analysis: Dict[str, Any],
) -> Dict[str, Any]:
    """Compare actual trade outcome to analysis prediction."""
    comparison: Dict[str, Any] = {
        "direction_correct": None,
        "return_vs_predicted_pct": None,
        "entry_slippage_pct": None,
    }

    actual_return = trade.get("return_pct")
    predicted_direction = analysis.get("predicted_direction")

    if actual_return is not None and predicted_direction:
        if predicted_direction == "LONG":
            comparison["direction_correct"] = actual_return > 0
        elif predicted_direction == "SHORT":
            comparison["direction_correct"] = actual_return < 0

    predicted_return = analysis.get("predicted_return_pct")
    if actual_return is not None and predicted_return is not None:
        comparison["return_vs_predicted_pct"] = round(
            actual_return - predicted_return, 4
        )

    price_at_rating = analysis.get("price_at_rating")
    avg_entry = trade.get("avg_entry_price")
    if price_at_rating and avg_entry and price_at_rating > 0:
        slippage = ((avg_entry - price_at_rating) / price_at_rating) * 100.0
        comparison["entry_slippage_pct"] = round(slippage, 4)

    # Confidence bucket for grouping.
    confidence = analysis.get("confidence")
    if confidence is not None:
        try:
            c = int(float(confidence))
            if c >= 8:
                trade["_confidence_bucket"] = "HIGH_8_10"
            elif c >= 5:
                trade["_confidence_bucket"] = "MED_5_7"
            else:
                trade["_confidence_bucket"] = "LOW_1_4"
        except (TypeError, ValueError):
            trade["_confidence_bucket"] = "UNKNOWN"
    else:
        trade["_confidence_bucket"] = "UNKNOWN"

    return comparison


def _aggregate_metrics(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute aggregate metrics from a list of matched trade records."""
    count = len(trades)
    if count == 0:
        return {"count": 0}

    returns = [t["return_pct"] for t in trades if t.get("return_pct") is not None]
    pnls = [t["pnl_usd"] for t in trades if t.get("pnl_usd") is not None]
    direction_checks = [
        t["comparison"]["direction_correct"]
        for t in trades
        if t.get("comparison", {}).get("direction_correct") is not None
    ]
    slippages = [
        t["comparison"]["entry_slippage_pct"]
        for t in trades
        if t.get("comparison", {}).get("entry_slippage_pct") is not None
    ]

    winners = [r for r in returns if r > 0]
    losers = [r for r in returns if r < 0]

    return {
        "count": count,
        "avg_return_pct": round(sum(returns) / len(returns), 4) if returns else None,
        "total_pnl_usd": round(sum(pnls), 2) if pnls else None,
        "win_rate": round(len(winners) / len(returns), 4) if returns else None,
        "avg_winner_pct": round(sum(winners) / len(winners), 4) if winners else None,
        "avg_loser_pct": round(sum(losers) / len(losers), 4) if losers else None,
        "profit_factor": round(
            abs(sum(winners) / sum(losers)), 4
        ) if winners and losers and sum(losers) != 0 else None,
        "direction_accuracy": round(
            sum(1 for d in direction_checks if d) / len(direction_checks), 4
        ) if direction_checks else None,
        "avg_entry_slippage_pct": round(
            sum(slippages) / len(slippages), 4
        ) if slippages else None,
        "max_winner_pct": round(max(winners), 4) if winners else None,
        "max_loser_pct": round(min(losers), 4) if losers else None,
    }


def _group_and_aggregate(
    trades: List[Dict[str, Any]],
    key: str,
) -> Dict[str, Dict[str, Any]]:
    """Group trades by a field and compute aggregate metrics per group."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for trade in trades:
        group_key = str(trade.get(key) or "UNKNOWN")
        groups.setdefault(group_key, []).append(trade)

    return {
        group_key: _aggregate_metrics(group_trades)
        for group_key, group_trades in sorted(groups.items())
    }


def _load_analysis_items_by_rating_id(
    batch_dir: str,
) -> Dict[str, Dict[str, Any]]:
    """Scan batch analysis summaries and index items by rating_id."""
    base = Path(batch_dir)
    index: Dict[str, Dict[str, Any]] = {}

    if not base.exists():
        return index

    for day_dir in sorted(base.iterdir()):
        if not day_dir.is_dir():
            continue
        for summary_path in sorted(
            day_dir.glob("batch_analyze_summary_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            try:
                payload = json.loads(summary_path.read_text())
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            for item in payload.get("items", []):
                if not isinstance(item, dict):
                    continue
                rid = str(item.get("rating_id", "")).strip()
                if rid and rid not in index:
                    enriched = dict(item)
                    enriched["_analysis_date"] = day_dir.name
                    index[rid] = enriched

    return index


def _empty_report(reason: str) -> Dict[str, Any]:
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": reason,
        "total_closed_trades": 0,
        "matched_to_analysis": 0,
        "unmatched_trades": 0,
        "overall": {"count": 0},
        "by_lane": {},
        "by_playbook": {},
        "by_confidence": {},
        "by_exit_rule": {},
        "trades": [],
    }


def _read_json_list(path_str: str) -> List[Dict[str, Any]]:
    path = Path(path_str)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text())
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []
    except Exception:
        return []


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
