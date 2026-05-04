# Task: S-003

## Tier
sonnet

## Summary
Extract Alpaca-specific logic from `paper_execution.py` into a proper `broker_adapters/alpaca.py` adapter.

## Context
`tradingagents/graph/paper_execution.py` contains ~1,200 lines of Alpaca-specific code scattered across multiple functions. The `broker_adapters/` package already has a clean base class (`BaseBrokerAdapter` with `submit_order()`) and a `MockBrokerAdapter`. The goal is to consolidate all Alpaca logic into a single adapter that implements and extends the base interface.

### Code to extract from paper_execution.py:
| Function | Lines | Purpose |
|---|---|---|
| `AlpacaExecutionAdapter` | 122-157 | Existing adapter class (thin) |
| `execute_alpaca_plan()` | 591-753 | Bulk order submission |
| `fetch_alpaca_orders_snapshot()` | 755-802 | GET /v2/orders |
| `fetch_alpaca_positions_snapshot()` | 805-843 | GET /v2/positions |
| `cancel_alpaca_order()` | 846-879 | DELETE /v2/orders/{id} |
| `submit_alpaca_order()` | 882-931 | Single order POST |
| `_resolve_alpaca_credentials()` | 2453-2479 | Credential resolution |
| `_alpaca_headers()` | 2482-2487 | Auth headers |
| `_submit_alpaca_order()` | 2515-2538 | HTTP POST helper |
| `_alpaca_get_json()` | 2490-2512 | HTTP GET helper |
| `_normalize_alpaca_base_url()` | 2546-2550 | URL normalization |

### Current base interface (`broker_adapters/base.py`):
- `BrokerOrderRequest` dataclass — intent metadata
- `BrokerOrderResult` dataclass — normalized response
- `BaseBrokerAdapter.submit_order(request) -> BrokerOrderResult`

## Requirements
1. Create `tradingagents/broker_adapters/alpaca.py` with `AlpacaBrokerAdapter(BaseBrokerAdapter)`:
   - `__init__(execution_mode)` — resolve credentials, set base_url/timeout
   - `submit_order(request) -> BrokerOrderResult` — implements base contract
   - `fetch_orders(status, limit) -> List[Dict]`
   - `fetch_positions() -> List[Dict]`
   - `cancel_order(broker_order_id) -> Dict`
   - `check_health() -> Dict` — credentials, account status, market clock
   - Private: `_headers()`, `_get()`, `_post()`, `_delete()`, `_normalize_url()`
2. Extend `BaseBrokerAdapter` with optional abstract methods for fetch_orders, fetch_positions, cancel_order, check_health (with default NotImplementedError)
3. Update `MockBrokerAdapter` to implement the new methods with mock responses
4. In `paper_execution.py`, replace direct Alpaca calls with adapter calls. Import `AlpacaBrokerAdapter` and delegate.
5. Update `broker_adapters/__init__.py` exports
6. Do NOT change any external behavior — all CLI commands and tests must work identically

## Files to Touch
- `tradingagents/broker_adapters/alpaca.py` (new)
- `tradingagents/broker_adapters/base.py` (extend interface)
- `tradingagents/broker_adapters/mock.py` (implement new methods)
- `tradingagents/broker_adapters/__init__.py` (update exports)
- `tradingagents/graph/paper_execution.py` (replace Alpaca calls with adapter)

## Acceptance Criteria
- [ ] All Alpaca HTTP calls are in `broker_adapters/alpaca.py`, none remain in `paper_execution.py`
- [ ] `paper_execution.py` delegates to adapter instance
- [ ] `BaseBrokerAdapter` interface extended with new optional methods
- [ ] `MockBrokerAdapter` implements new methods
- [ ] `AlpacaBrokerAdapter` is importable from `tradingagents.broker_adapters`
- [ ] All existing tests pass: `python -m pytest tests/ -v`

## Status
pending
