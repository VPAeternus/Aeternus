"""Deal Flow orchestration scheduler with daily and event-triggered runs."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.dealflow.control_io import read_json_locked, write_json_locked

from .engine_heartbeat import emit_engine_heartbeat, estimate_next_preopen_run_utc
from .pipeline import DealFlowPipeline
from .triage_control import resolve_intents_for_run
from .x_budget import evaluate_x_budget_policy, persist_x_budget_policy


class DealFlowScheduler:
    """Single-cycle scheduler suitable for cron/external orchestrators."""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        state_path: Optional[Path] = None,
        pipeline: Optional[DealFlowPipeline] = None,
    ):
        self.config = dict(config or DEFAULT_CONFIG)
        self.pipeline = pipeline or DealFlowPipeline(config=self.config)
        self.state_path = state_path or Path("eval_results") / "deal_flow" / "scheduler_state.json"

    def run_once(
        self,
        now: Optional[dt.datetime] = None,
        force_trigger: Optional[str] = None,
        as_of_date: Optional[str] = None,
        top_k: Optional[int] = None,
    ) -> Dict[str, Any]:
        state = self._load_state()
        now_utc = self._normalize_now(now)
        now_local = now_utc.astimezone(self._timezone())
        run_date = as_of_date or now_local.date().isoformat()
        top_k_value = int(top_k or 1)
        # --- Geopolitical scouts (daily, free) ---
        _scout_interval_hours = 24.0
        for _scout_key, _scout_fn_path in [
            ("last_commodity_scout_ts", "tradingagents.dealflow.sources.commodity_shock_scout.scan_commodity_shock_clusters"),
            ("last_dod_scout_ts", "tradingagents.dealflow.sources.dod_contract_scout.scan_dod_contract_spikes"),
        ]:
            _last_ts_str = state.get(_scout_key)
            _elapsed = float("inf")
            if _last_ts_str:
                try:
                    _last_dt = dt.datetime.fromisoformat(_last_ts_str).replace(tzinfo=dt.timezone.utc)
                    _elapsed = (now_utc - _last_dt).total_seconds() / 3600.0
                except Exception:
                    pass
            if _elapsed >= _scout_interval_hours:
                try:
                    _mod, _fn = _scout_fn_path.rsplit(".", 1)
                    import importlib as _il
                    _fn_obj = getattr(_il.import_module(_mod), _fn)
                    _scout_result = _fn_obj()
                    state[_scout_key] = now_utc.isoformat()
                    # Append background scout audit entry
                    try:
                        import json as _json
                        _symbols = []
                        if isinstance(_scout_result, dict):
                            _symbols = _scout_result.get("symbols", _scout_result.get("tickers", []))
                        _audit_line = _json.dumps({
                            "scout": _fn,
                            "timestamp": now_utc.isoformat(),
                            "count": len(_symbols),
                            "symbols": list(_symbols)[:50],
                        })
                        _audit_path = Path("eval_results") / "deal_flow" / "scout_audit_background.jsonl"
                        _audit_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(_audit_path, "a") as _af:
                            _af.write(_audit_line + "\n")
                    except Exception:
                        pass
                except Exception:
                    pass  # Never block pipeline on scout failure

        trigger = ""
        reason = ""
        event_state: Dict[str, Any] = {"triggered": False, "reasons": [], "metrics": {}}

        forced = (force_trigger or "").strip().lower()
        if forced in {"daily", "event", "manual"}:
            trigger = forced
            reason = f"Forced {trigger} run."
            if trigger == "event":
                event_state = self.pipeline.evaluate_event_trigger(run_date)
        else:
            if self._is_daily_due(now_local, state, run_date):
                trigger = "daily"
                reason = "Daily pre-open window active and run not completed for date."
            elif self._can_run_event(now_utc, state):
                event_state = self.pipeline.evaluate_event_trigger(run_date)
                if event_state.get("triggered"):
                    trigger = "event"
                    reason = "Event trigger thresholds met."
                else:
                    reason = "Event trigger thresholds not met."
            else:
                reason = "Event cooldown active."

        if not trigger:
            emit_engine_heartbeat(
                run_state="IDLE",
                active_run_id="",
                active_run_started_at_utc="",
                next_run_at_utc_actual=estimate_next_preopen_run_utc(
                    config=self.config,
                    now=now_utc,
                ),
                queue_run_id_target=str(state.get("last_run_id") or ""),
                config=self.config,
                now=now_utc,
            )
            return {
                "ran": False,
                "trigger": "none",
                "reason": reason,
                "date": run_date,
                "state_path": str(self.state_path),
                "cooldown_minutes": int(self.config.get("dealflow_event_cooldown_minutes", 90)),
                "event_trigger": event_state,
            }

        run_started_at_utc = now_utc.isoformat()
        emit_engine_heartbeat(
            run_state="RUNNING",
            active_run_id="",
            active_run_started_at_utc=run_started_at_utc,
            next_run_at_utc_actual="",
            queue_run_id_target=str(state.get("last_run_id") or ""),
            config=self.config,
            now=now_utc,
        )
        scout_summary, _, normalized_signals, event_state = self.pipeline.run(
            as_of_date=run_date,
            trigger=trigger,
            top_k=top_k_value,
        )
        triage_resolution = resolve_intents_for_run(
            active_run_id=str(scout_summary.get("run_id") or ""),
            run_started_at_utc=run_started_at_utc,
            consumption_prices={},
            price_source_latency_ms=0.0,
            market_data_quality="DELAYED",
            regime_label_at_consumption="",
            config=self.config,
            now=now_utc,
        )

        x_budget_policy = evaluate_x_budget_policy(
            config=self.config,
            as_of_date=run_date,
        )
        policy_path = persist_x_budget_policy(
            policy=x_budget_policy,
            as_of_date=run_date,
        )

        state["last_run_ts"] = now_utc.isoformat()
        state["last_run_trigger"] = trigger
        state["last_run_id"] = scout_summary.get("run_id")
        state["last_signal_count"] = len(normalized_signals)
        state["last_event_reasons"] = scout_summary.get("event_reasons", [])
        state["last_total_unique_tickers"] = int(scout_summary.get("total_unique_tickers", 0) or 0)
        state["last_x_budget_policy"] = {
            "action": x_budget_policy.get("action"),
            "horizon_used": x_budget_policy.get("horizon_used"),
            "recommended": x_budget_policy.get("recommended"),
            "applied": bool(x_budget_policy.get("applied")),
            "path": str(policy_path),
        }
        if trigger == "daily":
            state["last_daily_run_date"] = run_date
        if trigger == "event":
            state["last_event_run_ts"] = now_utc.isoformat()
        self._save_state(state)
        emit_engine_heartbeat(
            run_state="IDLE",
            active_run_id="",
            active_run_started_at_utc="",
            next_run_at_utc_actual=estimate_next_preopen_run_utc(
                config=self.config,
                now=now_utc,
            ),
            queue_run_id_target=str(scout_summary.get("run_id") or ""),
            config=self.config,
            now=now_utc,
        )

        return {
            "ran": True,
            "trigger": trigger,
            "reason": reason,
            "date": run_date,
            "run_id": scout_summary.get("run_id"),
            "total_unique_tickers": int(scout_summary.get("total_unique_tickers", 0) or 0),
            "scout_counts": dict(scout_summary.get("scout_counts", {}) or {}),
            "signal_count": len(normalized_signals),
            "event_trigger": event_state,
            "state_path": str(self.state_path),
            "scout_ticker_summary": scout_summary,
            "x_budget_policy": x_budget_policy,
            "x_budget_policy_path": str(policy_path),
            "triage_resolution": triage_resolution,
        }

    def _is_daily_due(self, now_local: dt.datetime, state: Dict[str, Any], run_date: str) -> bool:
        if now_local.weekday() >= 5:
            return False
        if state.get("last_daily_run_date") == run_date:
            return False
        return self._is_within_preopen_window(now_local)

    def _is_within_preopen_window(self, now_local: dt.datetime) -> bool:
        start = str(self.config.get("dealflow_scheduler_preopen_start", "08:00"))
        end = str(self.config.get("dealflow_scheduler_preopen_end", "09:25"))
        start_time = self._parse_hhmm(start)
        end_time = self._parse_hhmm(end)
        now_time = now_local.time()
        return start_time <= now_time <= end_time

    def _can_run_event(self, now_utc: dt.datetime, state: Dict[str, Any]) -> bool:
        cooldown_min = int(self.config.get("dealflow_event_cooldown_minutes", 90))
        last_event_run = self._parse_iso_dt(state.get("last_event_run_ts"))
        if not last_event_run:
            return True
        elapsed = (now_utc - last_event_run).total_seconds() / 60.0
        return elapsed >= float(cooldown_min)

    def _timezone(self):
        tz_name = str(self.config.get("dealflow_scheduler_timezone", "America/New_York"))
        try:
            return ZoneInfo(tz_name)
        except Exception:
            return dt.timezone.utc

    def _load_state(self) -> Dict[str, Any]:
        return read_json_locked(self.state_path, default_factory=dict)

    def _save_state(self, state: Dict[str, Any]) -> None:
        write_json_locked(self.state_path, state)

    def _normalize_now(self, now: Optional[dt.datetime]) -> dt.datetime:
        if now is None:
            return dt.datetime.now(dt.timezone.utc)
        if now.tzinfo is None:
            return now.replace(tzinfo=dt.timezone.utc)
        return now.astimezone(dt.timezone.utc)

    def _parse_hhmm(self, value: str) -> dt.time:
        try:
            return dt.datetime.strptime(value, "%H:%M").time()
        except ValueError:
            return dt.time(hour=8, minute=0)

    def _parse_iso_dt(self, value: Any) -> Optional[dt.datetime]:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = dt.datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
