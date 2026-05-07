"""Execution adapter classes with injected paper_execution dependencies."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Protocol

from tradingagents.graph.track_record import TrackRecord

from .constants import (
    EXECUTION_MODE_ALPACA_LIVE,
    EXECUTION_MODE_ALPACA_PAPER,
    EXECUTION_MODE_LIVE,
    EXECUTION_MODE_PAPER,
)
from .modes import normalize_execution_mode


class ExecutionAdapter(Protocol):
    """Execution adapter interface for future broker integrations."""

    mode: str

    def execute_plan(
        self,
        plan: Dict[str, Any],
        orders_path: str,
        positions_path: str,
        fill_price_slippage_bps: float,
    ) -> Dict[str, Any]:
        ...

    def close_position(
        self,
        symbol: str,
        close_price: float,
        close_date: str,
        positions_path: str,
        closed_trades_path: str,
        track_record: Optional[TrackRecord],
    ) -> Dict[str, Any]:
        ...


class PaperExecutionAdapter:
    """Paper execution adapter with broker-compatible method signatures."""

    mode = EXECUTION_MODE_PAPER

    def __init__(
        self,
        *,
        execute_paper_plan_fn: Callable[..., Dict[str, Any]],
        close_paper_position_fn: Callable[..., Dict[str, Any]],
    ):
        self._execute_paper_plan = execute_paper_plan_fn
        self._close_paper_position = close_paper_position_fn

    def execute_plan(
        self,
        plan: Dict[str, Any],
        orders_path: str,
        positions_path: str,
        fill_price_slippage_bps: float,
    ) -> Dict[str, Any]:
        return self._execute_paper_plan(
            plan=plan,
            orders_path=orders_path,
            positions_path=positions_path,
            fill_price_slippage_bps=fill_price_slippage_bps,
        )

    def close_position(
        self,
        symbol: str,
        close_price: float,
        close_date: str,
        positions_path: str,
        closed_trades_path: str,
        track_record: Optional[TrackRecord],
    ) -> Dict[str, Any]:
        return self._close_paper_position(
            symbol=symbol,
            close_price=close_price,
            close_date=close_date,
            positions_path=positions_path,
            closed_trades_path=closed_trades_path,
            track_record=track_record,
        )


class LiveExecutionAdapter:
    """Safe live adapter scaffold: queue intents, do not place broker orders yet."""

    mode = EXECUTION_MODE_LIVE

    def __init__(
        self,
        *,
        execute_live_plan_fn: Callable[..., Dict[str, Any]],
        close_alpaca_position_fn: Callable[..., Dict[str, Any]],
    ):
        self._execute_live_plan = execute_live_plan_fn
        self._close_alpaca_position = close_alpaca_position_fn

    def execute_plan(
        self,
        plan: Dict[str, Any],
        orders_path: str,
        positions_path: str,
        fill_price_slippage_bps: float,
    ) -> Dict[str, Any]:
        return self._execute_live_plan(
            plan=plan,
            outbox_path=orders_path,
        )

    def close_position(
        self,
        symbol: str,
        close_price: float,
        close_date: str,
        positions_path: str,
        closed_trades_path: str,
        track_record: Optional[TrackRecord],
    ) -> Dict[str, Any]:
        return self._close_alpaca_position(
            symbol=symbol,
            mode=EXECUTION_MODE_ALPACA_PAPER,
        )


class AlpacaExecutionAdapter:
    """Alpaca adapter for direct order submission (paper/live)."""

    def __init__(
        self,
        mode: str,
        *,
        execute_alpaca_plan_fn: Callable[..., Dict[str, Any]],
        close_alpaca_position_fn: Callable[..., Dict[str, Any]],
    ):
        self.mode = normalize_execution_mode(mode)
        self.is_paper = self.mode == EXECUTION_MODE_ALPACA_PAPER
        self._execute_alpaca_plan = execute_alpaca_plan_fn
        self._close_alpaca_position = close_alpaca_position_fn

    def execute_plan(
        self,
        plan: Dict[str, Any],
        orders_path: str,
        positions_path: str,
        fill_price_slippage_bps: float,
    ) -> Dict[str, Any]:
        del positions_path, fill_price_slippage_bps  # Not used for broker submission.
        return self._execute_alpaca_plan(
            plan=plan,
            outbox_path=orders_path,
            mode=self.mode,
        )

    def close_position(
        self,
        symbol: str,
        close_price: float,
        close_date: str,
        positions_path: str,
        closed_trades_path: str,
        track_record: Optional[TrackRecord],
    ) -> Dict[str, Any]:
        return self._close_alpaca_position(
            symbol=symbol,
            mode=self.mode,
        )


def get_execution_adapter(mode: str, *, deps: Dict[str, Callable[..., Dict[str, Any]]]) -> ExecutionAdapter:
    """Resolve execution adapter by mode using injected execution callables."""
    normalized = normalize_execution_mode(mode)
    if normalized == EXECUTION_MODE_PAPER:
        return PaperExecutionAdapter(
            execute_paper_plan_fn=deps["execute_paper_plan"],
            close_paper_position_fn=deps["close_paper_position"],
        )
    if normalized == EXECUTION_MODE_LIVE:
        return LiveExecutionAdapter(
            execute_live_plan_fn=deps["execute_live_plan"],
            close_alpaca_position_fn=deps["close_alpaca_position"],
        )
    if normalized in {EXECUTION_MODE_ALPACA_PAPER, EXECUTION_MODE_ALPACA_LIVE}:
        return AlpacaExecutionAdapter(
            mode=normalized,
            execute_alpaca_plan_fn=deps["execute_alpaca_plan"],
            close_alpaca_position_fn=deps["close_alpaca_position"],
        )
    raise ValueError(f"Unsupported execution mode: {mode}")
