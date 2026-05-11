# Architecture Reference

Lazy-loaded reference for package locations, file paths, and subsystem details. Read this when you need to find something — not loaded by default.

## Core Packages

- **`tradingagents/graph/`** — LangGraph orchestration. Central class: `TradingAgentsGraph`. Key files: `aeternus_scoring.py` (5-pillar scorer), `coherence_engine.py` (cross-pillar meta-analysis), `regime_weights.py` (regime-adaptive weight tables), `paper_execution.py` (order lifecycle), `hedging.py`, `kerberos_overlay.py`, `track_record.py`, `audit.py`, `market_regime.py`, `options_math.py`.
- **`tradingagents/agents/`** — Agent definitions by role: `analysts/` (4 analysts + 4 deep-thinking reviewers), `researchers/`, `trader/`, `risk_mgmt/`, `managers/`, `utils/` (states, tools, memory, computation engines).
- **`tradingagents/dataflows/`** — Data vendor abstraction. `interface.py` defines the contract; implementations for yfinance, Alpha Vantage, xAI, Google, local.
- **`tradingagents/dealflow/`** — Scout sourcing pipeline. `pipeline.py` orchestrates connectors in `sources/` and writes the unscored ticker handoff for fundamental intake. Supporting: universe, scheduler, readiness.
- **`tradingagents/capital_allocator/`** — Portfolio construction with gates, liability engine, regime override, SQLite repository.
- **`tradingagents/evidence/`** — Validation: walkforward, regime slicing, ablation, telemetry.
- **`tradingagents/broker_adapters/`** — Broker abstraction (base + mock; Alpaca in `paper_execution.py`).
- **`tradingagents/phase_engine/`** — Wyckoff phase classification, momentum overlay, regime-exit signals. Independent from agent pipeline; overrides all signals during heightened risk.
- **`tradingagents/operator_gateway/`** — FastAPI control plane for operator UI (heartbeat, triage, drift, mirror handshake).
- **`cli/`** — Typer CLI, 34+ commands. Entry: `cli/main.py`. Commands split across `cli/commands/*.py`.
- **`operator_ui/`** — React Native (Expo) mobile dashboard.

## Data & State Paths

- Analysis results: `results/<ticker>/<date>/`
- Deal flow: `eval_results/deal_flow/`
- Paper execution: `eval_results/paper_execution/`
- Live execution: `eval_results/live_execution/`
- Control plane: `eval_results/control/`
- Capital allocator DB: `eval_results/control/capital_allocator.db`
- Data cache: `tradingagents/dataflows/data_cache/`
- Kerberos overlay: `eval_results/kerberos_state.json`, `eval_results/kerberos_orders.json`
- Hedge engine: `eval_results/hedge_state.json`, `eval_results/hedge_orders.json`

## Overlay Engines (advisory panels, not auto-executed)

| Overlay | Engine File | Signal | State File |
|---|---|---|---|
| Adaptive Hedge | `graph/hedging.py` | SPY < SMA200 | `hedge_state.json` |
| Kerberos %B | `graph/kerberos_overlay.py` | VXX %B(20,2) > 1 | `kerberos_state.json` |
| CSP Regime | `graph/csp_overlay.py` | QQQ < SMA200 + VIX 25-40 | — |
| Overnight CC | `graph/overnight_cc_overlay.py` | VIX drop + QQQ rally | — |
| CC Wyckoff | `phase_engine/cc_wyckoff_phase.py` | Wyckoff phase S2 | — |
| CC Scanner | `phase_engine/cc_scanner.py` | Overbought + timing | — |
