# tradingagents/graph/track_record.py

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .aeternus_scoring import AeternusRating
from tradingagents.dealflow.control_io import read_json_locked, write_json_locked
from tradingagents.default_config import DEFAULT_CONFIG


class TrackRecord:
    """Manages track record logging for Aeternus ratings."""

    def __init__(self, path: str = "eval_results/track_record.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]")
        self.log_path = Path(str(self.path) + ".log")

    def append(self, rating: AeternusRating) -> None:
        """Append a rating event to the track record."""
        history = self._load()

        # Ensure rating has an ID (backwards compatibility)
        if "rating_id" not in rating:
             # In production, we might want to generate one here if missing
             pass

        # Append instead of overwrite (Log Logic)
        history.append(rating)
        self._save(history)
        self._append_log(rating, "APPEND")

    def update_outcome(self, rating_id: str, close_price: float, date: str) -> bool:
        """
        Log a trade closure event for a specific rating.
        This does NOT overwrite the original rating, but appends a 'closure' event?
        Actually, for simplicity in Phase 1, we will update the outcome in place but keep a separate audit log in audit.py.
        Here we just find and update for the dashboard view.
        """
        history = self._load()
        updated = False
        for entry in history:
            if entry.get("rating_id") == rating_id:
                entry["close_price"] = close_price
                entry["close_date"] = date
                entry["status"] = "CLOSED"
                updated = True
                break
        
        if updated:
            self._save(history)
            # Log the mutated entry state to the immutable append log.
            mutated_entry = next(
                (e for e in history if e.get("rating_id") == rating_id), {}
            )
            self._append_log(mutated_entry, "UPDATE_OUTCOME")
            try:
                from .audit import RatingAuditLog

                RatingAuditLog().log_event(
                    "TRADE_CLOSED",
                    rating_id,
                    {
                        "close_price": close_price,
                        "close_date": date,
                        "status": "CLOSED",
                    },
                )
            except Exception:
                # Audit logging should not block outcome updates.
                pass

        return updated

    def get_stats(self) -> Dict[str, Any]:
        """Compute basic track record statistics."""
        history = self._load()
        if not history:
            return {"count": 0, "ratings": {}}

        rating_counts = {}
        for entry in history:
            # Filter distinct ratings if multiple events exist per ID (Phase 1 simplification: 1 entry = 1 rating)
            r = entry.get("rating", "Unknown")
            rating_counts[r] = rating_counts.get(r, 0) + 1

        return {
            "count": len(history),
            "ratings": rating_counts,
        }

    def get_history(self, ticker: Optional[str] = None) -> List[AeternusRating]:
        """Get rating history, optionally filtered by ticker."""
        history = self._load()
        if ticker:
            return [r for r in history if r.get("ticker") == ticker]
        return history

    def compute_performance(self, current_prices: Dict[str, float]) -> Dict[str, Any]:
        """
        Compute win rate and average return based on price targets.
        
        Args:
            current_prices: Dict mapping ticker -> current price for outcome evaluation
            
        Returns:
            Dict with win_rate, avg_return, total_evaluated
        """
        history = self._load()
        if not history:
            return {"win_rate": 0.0, "avg_return": 0.0, "total_evaluated": 0}
        
        wins = 0
        total_return = 0.0
        evaluated = 0
        
        for entry in history:
            ticker = entry.get("ticker")
            price_at_rating = entry.get("price_at_rating")
            price_target = entry.get("price_target")
            
            # Skip if missing required data
            if not ticker or not price_at_rating or not price_target:
                continue
                
            # Get current price implementation
            # 1. Use explicit close price (Realized P&L)
            if entry.get("status") == "CLOSED" and entry.get("close_price"):
                current_price = entry.get("close_price")
            # 2. Or use current market price (Unrealized P&L)
            else:
                 current_price = current_prices.get(ticker)
                 
            if not current_price:
                continue
            
            evaluated += 1
            
            # Calculate return
            ret = (current_price - price_at_rating) / price_at_rating
            total_return += ret
            
            # Check if target was reached (win condition)
            if self._is_win(entry, ret):
                wins += 1
            # Hold is neutral
        
        if evaluated == 0:
            return {"win_rate": 0.0, "avg_return": 0.0, "total_evaluated": 0}
        
        return {
            "win_rate": wins / evaluated,
            "avg_return": total_return / evaluated,
            "total_evaluated": evaluated
        }

    def get_accuracy_by_sector(self, sector: str) -> Optional[float]:
        """Return historical win rate for closed trades in a sector."""
        if not sector:
            return None

        history = self._load()
        wins = 0
        evaluated = 0

        for entry in history:
            if entry.get("status") != "CLOSED":
                continue
            if entry.get("sector") != sector:
                continue

            open_price = entry.get("price_at_rating")
            close_price = entry.get("close_price")
            if not open_price or not close_price:
                continue

            ret = (close_price - open_price) / open_price
            evaluated += 1
            if self._is_win(entry, ret):
                wins += 1

        if evaluated == 0:
            return None
        return wins / evaluated

    def get_accuracy_by_confidence(self, confidence_level: int) -> Optional[float]:
        """Return historical win rate for closed trades at a given confidence."""
        history = self._load()
        wins = 0
        evaluated = 0

        for entry in history:
            if entry.get("status") != "CLOSED":
                continue

            try:
                if int(entry.get("confidence")) != int(confidence_level):
                    continue
            except (TypeError, ValueError):
                continue

            open_price = entry.get("price_at_rating")
            close_price = entry.get("close_price")
            if not open_price or not close_price:
                continue

            ret = (close_price - open_price) / open_price
            evaluated += 1
            if self._is_win(entry, ret):
                wins += 1

        if evaluated == 0:
            return None
        return wins / evaluated

    def _is_win(self, entry: Dict[str, Any], ret: float) -> bool:
        """Apply rating-direction win logic consistently across metrics."""
        rating_type = entry.get("rating", "Hold")
        if "Buy" in rating_type:
            return ret > 0
        if "Sell" in rating_type:
            return ret < 0
        return False

    # ------------------------------------------------------------------
    # Immutable append log helpers
    # ------------------------------------------------------------------

    def _append_log(self, entry: Dict[str, Any], event_type: str) -> None:
        """Append a single NDJSON line to the immutable log file."""
        record = {
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "entry": entry,
        }
        try:
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
        except Exception:
            # Log write failures must not block the primary write path.
            pass

    def _load_log(self) -> List[Dict[str, Any]]:
        """Parse every NDJSON line from the append log."""
        if not self.log_path.exists():
            return []
        records = []
        with self.log_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return records

    def verify_integrity(self) -> Dict[str, Any]:
        """
        Compare the mutable JSON view against the append log.

        Returns a dict with:
          - ok (bool): True if no discrepancies were found.
          - json_count: number of entries in the JSON view.
          - log_event_count: total NDJSON events in the log.
          - log_unique_ids: unique rating_ids seen in the log.
          - missing_from_json: rating_ids present in the log but absent from JSON.
          - extra_in_json: rating_ids present in JSON but absent from the log.
        """
        json_entries = self._load()
        log_records = self._load_log()

        json_ids = {e.get("rating_id") for e in json_entries if e.get("rating_id")}
        log_ids = {
            r["entry"].get("rating_id")
            for r in log_records
            if r.get("entry", {}).get("rating_id")
        }

        missing_from_json = sorted(log_ids - json_ids)
        extra_in_json = sorted(json_ids - log_ids)

        return {
            "ok": not missing_from_json and not extra_in_json,
            "json_count": len(json_entries),
            "log_event_count": len(log_records),
            "log_unique_ids": len(log_ids),
            "missing_from_json": missing_from_json,
            "extra_in_json": extra_in_json,
        }

    def compute_v3_benchmark(
        self, date_start: str = None, date_end: str = None
    ) -> Dict[str, Any]:
        """
        Compute V3 QQQ benchmark over the track record's date range.

        Returns {v3_total_pts, v3_annualized, bh_total_pts, bh_annualized,
                 period_days} or {} on failure.
        """
        try:
            from tradingagents.phase_engine.index_overlay import v3_benchmark_stats

            history = self._load()
            if not history and not date_start:
                return {}

            # Determine date range from track record if not provided
            if not date_start and history:
                dates = [self._coerce_record_date(h) for h in history]
                dates = [d for d in dates if d]
                if dates:
                    date_start = min(dates)
            if not date_end and history:
                dates = [self._coerce_record_date(h) for h in history]
                dates = [d for d in dates if d]
                if dates:
                    date_end = max(dates)

            ticker = str(DEFAULT_CONFIG.get("v3_benchmark_ticker", "QQQ")).strip().upper() or "QQQ"
            # Same-window benchmark over the actual track-record dates.
            stats = v3_benchmark_stats(
                ticker=ticker,
                lookback_days=0,
                date_start=date_start,
                date_end=date_end,
            )
            if not stats:
                return {}

            return {
                "ticker": stats.get("ticker", ticker),
                "date_start": stats.get("date_start", date_start),
                "date_end": stats.get("date_end", date_end),
                "v3_total_pts": stats.get("total_pts", 0.0),
                "bh_total_pts": stats.get("bh_pts", 0.0),
                "v3_total_return_pct": stats.get("v3_total_return_pct", 0.0),
                "bh_total_return_pct": stats.get("bh_total_return_pct", 0.0),
                "v3_cagr_pct": stats.get("v3_cagr_pct", 0.0),
                "bh_cagr_pct": stats.get("bh_cagr_pct", 0.0),
                "period_days": stats.get("period_days", 0),
            }
        except Exception:
            return {}

    def _coerce_record_date(self, entry: Dict[str, Any]) -> Optional[str]:
        raw = str(entry.get("date") or entry.get("trade_date") or "").strip()
        if not raw:
            return None
        return raw[:10]

    def _load(self) -> List[Dict[str, Any]]:
        """Load track record from file."""
        result = read_json_locked(self.path, default_factory=list)
        return result if isinstance(result, list) else []

    def _save(self, history: List[Dict[str, Any]]) -> None:
        """Save track record to file atomically."""
        write_json_locked(self.path, history)
