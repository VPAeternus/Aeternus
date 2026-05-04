"""Automated reconciliation daemon for continuous order/position sync (P1-02, P1-05)."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .paper_execution import (
    build_exit_execution_plan,
    execute_plan_with_adapter,
    fetch_alpaca_orders_snapshot,
    fetch_alpaca_positions_snapshot,
    reconcile_live_execution,
)
from .track_record import TrackRecord
from tradingagents.capital_allocator.regime_override import regime_update_step
from tradingagents.default_config import DEFAULT_CONFIG

logger = logging.getLogger(__name__)

_ALPACA_MODES = {"alpaca-paper", "alpaca-live"}


def _normalize_mode(mode: str) -> str:
    return str(mode or "alpaca-paper").strip().lower().replace("_", "-")


class ReconciliationDaemon:
    """Poll broker, reconcile fills, and optionally enforce exit rules continuously.

    Parameters
    ----------
    config:
        Configuration dict, defaults to ``DEFAULT_CONFIG`` when omitted.
    mode:
        Execution mode (``"alpaca-paper"`` or ``"alpaca-live"``).
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        mode: str = "alpaca-paper",
    ) -> None:
        self._cfg: Dict[str, Any] = config if config is not None else DEFAULT_CONFIG
        self.mode = _normalize_mode(mode)

        # Path resolution — all defaults pulled from config with explicit fallbacks.
        self.outbox_path: str = str(
            self._cfg.get("live_execution_outbox_path", "eval_results/live_execution/outbox.json")
        )
        self.positions_path: str = str(
            self._cfg.get("live_positions_shadow_path", "eval_results/live_execution/positions_shadow.json")
        )
        self.fills_path: str = str(
            self._cfg.get("live_execution_fills_path", "eval_results/live_execution/fills.json")
        )
        self.closed_trades_path: str = str(
            self._cfg.get("live_execution_closed_trades_path", "eval_results/live_execution/closed_trades.json")
        )
        self.broker_orders_snapshot_path: str = str(
            self._cfg.get("live_broker_orders_snapshot_path", "eval_results/live_execution/broker_orders_latest.json")
        )
        self.broker_positions_snapshot_path: str = str(
            self._cfg.get(
                "live_broker_positions_snapshot_path",
                "eval_results/live_execution/broker_positions_latest.json",
            )
        )

        # Regime auto-update parameters (P2-03).
        self.auto_regime_update: bool = bool(self._cfg.get("reconciliation_auto_regime_update", False))
        self.regime_override_path: str = str(
            self._cfg.get(
                "operator_gateway_allocator_regime_override_path",
                "eval_results/control/allocator_regime_override.json",
            )
        )

        # Exit-rule parameters (P1-05).
        self.auto_exit_check: bool = bool(self._cfg.get("reconciliation_auto_exit_check", False))
        self.stop_loss_pct: float = float(self._cfg.get("execution_exit_stop_loss_pct", 0.08))
        self.take_profit_pct: float = float(self._cfg.get("execution_exit_take_profit_pct", 0.20))
        self.max_hold_days: int = int(self._cfg.get("execution_exit_max_hold_days", 20))
        self.trailing_stop_pct: float = float(self._cfg.get("execution_exit_trailing_stop_pct", 0.0))
        self.min_position_notional_usd: float = float(
            self._cfg.get("execution_exit_min_position_notional_usd", 250.0)
        )
        self.max_exit_orders_per_run: int = int(self._cfg.get("execution_exit_max_orders_per_run", 6))
        self.slippage_bps: float = float(self._cfg.get("paper_execution_slippage_bps", 0.0))
        self.enforce_whole_shares: bool = bool(self._cfg.get("alpaca_enforce_whole_shares", True))

    # ------------------------------------------------------------------
    # Core cycle
    # ------------------------------------------------------------------

    def run_once(self) -> Dict[str, Any]:
        """Run a single reconciliation cycle.

        Steps:
        1. Fetch broker orders snapshot.
        2. Fetch broker positions snapshot.
        3. Call ``reconcile_live_execution()``.
        4. If ``reconciliation_auto_exit_check`` is enabled, evaluate exit rules
           and submit any triggered exit orders via the adapter (P1-05).

        Returns the reconciliation result dict, optionally extended with
        ``"exit_check"`` data when step 4 runs.
        """
        logger.info("ReconciliationDaemon.run_once() starting | mode=%s", self.mode)

        # Step 1: fetch broker orders snapshot.
        try:
            broker_orders_snapshot = fetch_alpaca_orders_snapshot(
                out_path=self.broker_orders_snapshot_path,
                mode=self.mode,
            )
            logger.debug(
                "Broker orders snapshot fetched | orders=%d",
                len(broker_orders_snapshot.get("orders", [])),
            )
        except Exception as exc:
            logger.error("Failed to fetch broker orders snapshot: %s", exc)
            return {
                "ok": False,
                "error": f"broker_orders_fetch_failed: {exc}",
                "mode": self.mode,
            }

        # Step 2: fetch broker positions snapshot.
        try:
            fetch_alpaca_positions_snapshot(
                out_path=self.broker_positions_snapshot_path,
                mode=self.mode,
            )
            logger.debug("Broker positions snapshot fetched")
        except Exception as exc:
            # Positions fetch failure is non-fatal for reconciliation; log and continue.
            logger.warning("Failed to fetch broker positions snapshot: %s", exc)

        # Step 3: reconcile.
        try:
            result = reconcile_live_execution(
                broker_snapshot=broker_orders_snapshot,
                outbox_path=self.outbox_path,
                positions_path=self.positions_path,
                fills_path=self.fills_path,
                closed_trades_path=self.closed_trades_path,
                track_record=TrackRecord(),
            )
            result["ok"] = True
            result["mode"] = self.mode
            logger.info(
                "Reconciliation complete | matched=%s fills=%s status_updates=%s closed=%s",
                result.get("matched_orders", 0),
                result.get("fills_applied", 0),
                result.get("status_updates", 0),
                result.get("closed_positions", 0),
            )
        except Exception as exc:
            logger.error("Reconciliation failed: %s", exc)
            return {
                "ok": False,
                "error": f"reconcile_failed: {exc}",
                "mode": self.mode,
            }

        # Step 3b: P&L threshold check after reconciliation.
        self._check_pnl_thresholds()

        # Step 4 (P1-05): optional continuous exit rule check.
        if self.auto_exit_check:
            exit_result = self._run_exit_check()
            result["exit_check"] = exit_result

        # Step 5 (P2-03): optional regime re-evaluation from VIX.
        if self.auto_regime_update:
            try:
                regime_result = regime_update_step(self.regime_override_path)
                result["regime_update"] = regime_result
                logger.info(
                    "Regime update | ok=%s vix=%.2f regime=%s",
                    regime_result.get("ok"),
                    regime_result.get("vix_close", 0.0),
                    regime_result.get("regime", ""),
                )
            except Exception as exc:
                logger.error("Regime update step failed: %s", exc)
                result["regime_update"] = {"ok": False, "error": str(exc)}

        # Audit trail: append JSONL record for this cycle
        self._write_audit_line(result)

        return result

    def _run_exit_check(self) -> Dict[str, Any]:
        """Evaluate exit rules and submit triggered exit orders.

        Returns a summary dict with keys ``signals_generated``, ``orders_submitted``,
        ``failed_orders``, and optionally ``error``.
        """
        logger.info("Running exit rule check | mode=%s", self.mode)
        use_whole_shares = self.mode.startswith("alpaca") and self.enforce_whole_shares

        try:
            exit_plan = build_exit_execution_plan(
                execution_mode=self.mode,
                positions_path=self.positions_path,
                outbox_path=self.outbox_path,
                stop_loss_pct=self.stop_loss_pct,
                take_profit_pct=self.take_profit_pct,
                max_hold_days=self.max_hold_days,
                trailing_stop_pct=self.trailing_stop_pct,
                min_position_notional_usd=self.min_position_notional_usd,
                max_exit_orders_per_run=self.max_exit_orders_per_run,
                enforce_whole_shares=bool(use_whole_shares),
            )
        except Exception as exc:
            logger.error("build_exit_execution_plan failed: %s", exc)
            return {"ok": False, "error": f"exit_plan_failed: {exc}"}

        signals = list(exit_plan.get("signals", []))
        orders = list(exit_plan.get("orders", []))
        logger.info("Exit plan built | signals=%d orders=%d", len(signals), len(orders))

        if not orders:
            return {
                "ok": True,
                "signals_generated": len(signals),
                "orders_submitted": 0,
                "failed_orders": 0,
            }

        latency_threshold = float(self._cfg.get("alerting_execution_latency_threshold_seconds", 30))
        t0 = time.monotonic()
        try:
            execution_result = execute_plan_with_adapter(
                plan=exit_plan,
                execution_mode=self.mode,
                orders_path=self.outbox_path,
                positions_path=self.positions_path,
                fill_price_slippage_bps=self.slippage_bps,
            )
            elapsed = time.monotonic() - t0
            submitted = int(execution_result.get("submitted_orders", 0))
            failed = int(execution_result.get("failed_orders", 0) or 0)
            logger.info("Exit orders submitted=%d failed=%d elapsed=%.2fs", submitted, failed, elapsed)
            if elapsed > latency_threshold:
                try:
                    from tradingagents.alerting.dispatcher import AlertDispatcher
                    AlertDispatcher(config=self._cfg).latency_alert(
                        operation="execute_plan_with_adapter",
                        elapsed_seconds=elapsed,
                        threshold_seconds=latency_threshold,
                    )
                except Exception as alert_exc:
                    logger.warning("Latency alert dispatch failed: %s", alert_exc)
            return {
                "ok": True,
                "signals_generated": len(signals),
                "orders_submitted": submitted,
                "failed_orders": failed,
                "execution_result": execution_result,
            }
        except Exception as exc:
            logger.error("Exit order execution failed: %s", exc)
            return {
                "ok": False,
                "signals_generated": len(signals),
                "orders_submitted": 0,
                "failed_orders": len(orders),
                "error": f"exit_execution_failed: {exc}",
            }

    def _write_audit_line(self, cycle_result: Dict[str, Any]) -> None:
        """Append a single JSON line to the reconciliation audit trail."""
        import uuid
        from datetime import datetime, timezone

        audit_dir = Path("eval_results/live_execution")
        audit_dir.mkdir(parents=True, exist_ok=True)
        audit_path = audit_dir / "reconciliation_audit.jsonl"

        record: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cycle_id": str(uuid.uuid4()),
            "mode": self.mode,
            "ok": cycle_result.get("ok", False),
            "matched_orders": cycle_result.get("matched_orders", 0),
            "fills_applied": cycle_result.get("fills_applied", 0),
            "status_updates": cycle_result.get("status_updates", 0),
            "closed_positions": cycle_result.get("closed_positions", 0),
        }

        # Add position count and estimated NLV if available
        try:
            positions_file = Path(self.positions_path)
            if positions_file.exists():
                positions_state = json.loads(positions_file.read_text())
                if isinstance(positions_state, dict):
                    record["positions_count"] = len(positions_state)
                    total_nlv = sum(
                        abs(float(v.get("net_quantity", 0) or 0)) * float(v.get("last_mark_price", 0) or 0)
                        for v in positions_state.values()
                        if isinstance(v, dict)
                    )
                    record["estimated_nlv"] = round(total_nlv, 2)
        except Exception:
            pass  # audit enrichment is best-effort

        # Include exit check summary if present
        exit_check = cycle_result.get("exit_check")
        if exit_check:
            record["exit_signals"] = exit_check.get("signals_generated", 0)
            record["exit_orders_submitted"] = exit_check.get("orders_submitted", 0)

        # Include error if cycle failed
        if not cycle_result.get("ok", False):
            record["error"] = cycle_result.get("error", "unknown")

        try:
            with audit_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
        except Exception as exc:
            logger.warning("Failed to write reconciliation audit line: %s", exc)

    def _check_pnl_thresholds(self) -> None:
        """Check open positions for unrealized losses exceeding the configured threshold.

        Fires a ``pnl_threshold_alert`` for each position whose unrealized loss
        percentage exceeds ``alerting_pnl_loss_threshold_pct``.
        """
        import json
        from pathlib import Path

        threshold_pct = float(self._cfg.get("alerting_pnl_loss_threshold_pct", 0.10))
        positions_file = Path(self.positions_path)
        if not positions_file.exists():
            return

        try:
            positions_state = json.loads(positions_file.read_text())
        except Exception as exc:
            logger.warning("_check_pnl_thresholds: failed to load positions: %s", exc)
            return

        breaching: list = []
        for symbol, row in positions_state.items():
            if not isinstance(row, dict):
                continue
            unrealized_return_pct = float(row.get("unrealized_return_pct", 0.0) or 0.0)
            unrealized_pnl_usd = float(row.get("unrealized_pnl_usd", 0.0) or 0.0)
            # A loss is represented as a negative return_pct; breach when loss > threshold
            if unrealized_return_pct < -(threshold_pct * 100.0):
                breaching.append((symbol, unrealized_pnl_usd, unrealized_return_pct))

        if not breaching:
            return

        try:
            from tradingagents.alerting.dispatcher import AlertDispatcher
            dispatcher = AlertDispatcher(config=self._cfg)
            for symbol, pnl_usd, ret_pct in breaching:
                logger.warning(
                    "P&L threshold breach: %s return=%.2f%% pnl_usd=%.2f threshold=%.1f%%",
                    symbol, ret_pct, pnl_usd, threshold_pct * 100.0,
                )
                dispatcher.pnl_threshold_alert(
                    symbol=symbol,
                    unrealized_pnl_usd=pnl_usd,
                    unrealized_return_pct=ret_pct,
                    threshold_pct=threshold_pct,
                )
        except Exception as exc:
            logger.warning("P&L alert dispatch failed: %s", exc)

    # ------------------------------------------------------------------
    # Poll loop
    # ------------------------------------------------------------------

    def run_loop(
        self,
        interval_seconds: int = 60,
        max_cycles: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Poll broker and reconcile repeatedly.

        Parameters
        ----------
        interval_seconds:
            Sleep duration between cycles. Defaults to 60 s (overridden by
            ``reconciliation_poll_interval_seconds`` config if not passed explicitly).
        max_cycles:
            Maximum number of cycles to run. ``None`` means run indefinitely.

        Returns a list of per-cycle result dicts (useful in tests and bounded runs).
        Stops on ``max_cycles`` or ``KeyboardInterrupt``.
        """
        poll_interval = int(
            self._cfg.get("reconciliation_poll_interval_seconds", interval_seconds)
        )
        results: List[Dict[str, Any]] = []
        cycle = 0

        logger.info(
            "ReconciliationDaemon.run_loop() starting | mode=%s interval=%ds max_cycles=%s",
            self.mode,
            poll_interval,
            max_cycles if max_cycles is not None else "infinite",
        )

        try:
            while True:
                if max_cycles is not None and cycle >= max_cycles:
                    logger.info("Max cycles reached (%d), stopping loop.", max_cycles)
                    break

                cycle += 1
                logger.info("Cycle %d starting", cycle)
                cycle_result = self.run_once()
                cycle_result["cycle"] = cycle
                results.append(cycle_result)
                logger.info("Cycle %d complete | ok=%s", cycle, cycle_result.get("ok"))

                if max_cycles is not None and cycle >= max_cycles:
                    break

                logger.debug("Sleeping %ds before next cycle", poll_interval)
                time.sleep(poll_interval)

        except KeyboardInterrupt:
            logger.info("ReconciliationDaemon interrupted after %d cycle(s).", cycle)

        return results
