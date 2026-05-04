"""System controller for operator gateway endpoints."""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Optional

from tradingagents.capital_allocator.contracts import RegimeShock
from tradingagents.capital_allocator.regime_override import write_regime_override

from .service import OperatorGatewayService


class SystemController:
    """Thread-safe façade used by FastAPI routes."""

    def __init__(self, service: OperatorGatewayService):
        self.service = service

    def get_schedule(self, *, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
        return self.service.get_schedule(now=now)

    def get_dealflow_feed(self, *, limit: Optional[int] = None, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
        return self.service.get_dealflow_feed(limit=limit, now=now)

    def get_bootstrap_data(self, *, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
        return self.service.get_bootstrap(now=now)

    def get_bootstrap_etag(self, *, now: Optional[dt.datetime] = None) -> str:
        return self.service.get_bootstrap_etag(now=now)

    def get_mission_control(
        self,
        *,
        as_of_date: Optional[str] = None,
        now: Optional[dt.datetime] = None,
    ) -> Dict[str, Any]:
        return self.service.get_mission_control(as_of_date=as_of_date, now=now)

    def get_scout_inventory(
        self,
        *,
        as_of_date: Optional[str] = None,
        now: Optional[dt.datetime] = None,
    ) -> Dict[str, Any]:
        return self.service.get_scout_inventory(as_of_date=as_of_date, now=now)

    def get_scout_detail(
        self,
        *,
        scout_id: str,
        as_of_date: Optional[str] = None,
        pass_num: Optional[int] = None,
        now: Optional[dt.datetime] = None,
    ) -> Dict[str, Any]:
        return self.service.get_scout_detail(
            scout_id=scout_id,
            as_of_date=as_of_date,
            pass_num=pass_num,
            now=now,
        )

    def get_scout_prompt(
        self,
        *,
        scout_id: str,
        as_of_date: Optional[str] = None,
        pass_num: Optional[int] = None,
    ) -> Dict[str, Any]:
        return self.service.get_scout_prompt(
            scout_id=scout_id,
            as_of_date=as_of_date,
            pass_num=pass_num,
        )

    def ingest_scout_payload(
        self,
        *,
        scout_id: str,
        as_of_date: Optional[str] = None,
        pass_num: Optional[int] = None,
        raw_payload: str,
    ) -> Dict[str, Any]:
        return self.service.ingest_scout_payload(
            scout_id=scout_id,
            as_of_date=as_of_date,
            pass_num=pass_num,
            raw_payload=raw_payload,
        )

    def get_candidate_detail(self, *, symbol: str, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
        return self.service.get_candidate_detail(symbol=symbol, now=now)

    def get_drift_sensitivity(self) -> Dict[str, float]:
        return self.service.get_drift_sensitivity()

    def update_drift_sensitivity(self, payload: Dict[str, Any]) -> Dict[str, float]:
        return self.service.update_drift_sensitivity(payload)

    def refresh_drift_snapshot(self, *, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
        return self.service.refresh_drift_snapshot(now=now)

    def get_drift_impact(self, *, max_items: int = 8, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
        return self.service.get_drift_impact(max_items=max_items, now=now)

    def create_triage_intent(self, payload: Dict[str, Any], *, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
        return self.service.create_triage_intent(payload, now=now)

    def undo_triage_intent(self, payload: Dict[str, Any], *, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
        return self.service.undo_triage_intent(payload, now=now)

    def create_mirror_challenge(
        self,
        *,
        intent_id: str,
        payload: Optional[Dict[str, Any]] = None,
        now: Optional[dt.datetime] = None,
    ) -> Dict[str, Any]:
        return self.service.create_mirror_challenge(intent_id=intent_id, payload=payload or {}, now=now)

    def confirm_mirror_intent(
        self,
        *,
        intent_id: str,
        payload: Dict[str, Any],
        now: Optional[dt.datetime] = None,
    ) -> Dict[str, Any]:
        return self.service.confirm_mirror_intent(intent_id=intent_id, payload=payload, now=now)

    def get_mirror_intent_preview(
        self,
        *,
        intent_id: str,
        now: Optional[dt.datetime] = None,
    ) -> Dict[str, Any]:
        return self.service.get_mirror_intent_preview(intent_id=intent_id, now=now)

    def list_triage_status(self, *, since_minutes: int = 60, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
        return self.service.list_triage_status(since_minutes=since_minutes, now=now)

    def list_allocator_status(self, *, since_minutes: int = 60, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
        return self.service.list_allocator_status(since_minutes=since_minutes, now=now)

    def allocator_report_card(self, *, lookback_days: int = 7, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
        return self.service.get_allocator_report_card(lookback_days=lookback_days, now=now)

    def activate_system_halt(
        self,
        *,
        reason: str,
        set_by: str = "operator",
        now: Optional[dt.datetime] = None,
    ) -> Dict[str, Any]:
        return self.service.activate_system_halt(reason=reason, set_by=set_by, now=now)

    def clear_system_halt(
        self,
        *,
        cleared_by: str = "operator",
        now: Optional[dt.datetime] = None,
    ) -> Dict[str, Any]:
        return self.service.clear_system_halt(cleared_by=cleared_by, now=now)

    def inject_regime_shock(
        self,
        *,
        regime: str,
        reason: str = "",
        source: str = "operator_gateway",
        now: Optional[dt.datetime] = None,
    ) -> Dict[str, Any]:
        path = self.service.regime_override_path()
        payload = write_regime_override(
            path=path,
            regime=RegimeShock(str(regime).upper()),
            reason=reason,
            source=source,
            now=now,
        )
        payload["override_path"] = str(path)
        return payload
