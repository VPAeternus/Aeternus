import os
import sys

DEFAULT_CONFIG = {
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", "./results"),
    "data_dir": os.getenv("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "dataflows", "data")),
    "data_cache_dir": os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
        "dataflows/data_cache",
    ),
    # LLM settings — all overridable via env vars.
    # AETERNUS_LLM_PROVIDER: openai | anthropic | minimax | xai | google | ollama
    # AETERNUS_BACKEND_URL: base URL for openai/ollama providers
    # AETERNUS_QUICK_MODEL / AETERNUS_DEEP_MODEL: model names
    "llm_provider": os.getenv("AETERNUS_LLM_PROVIDER", "minimax"),
    "deep_think_llm": os.getenv("AETERNUS_DEEP_MODEL", "MiniMax-M2.5"),
    "quick_think_llm": os.getenv("AETERNUS_QUICK_MODEL", "MiniMax-M2.5"),
    # If AETERNUS_QUICK_THINK_PROVIDER is unset, inherits llm_provider → no override triggered.
    "quick_think_provider": os.getenv(
        "AETERNUS_QUICK_THINK_PROVIDER",
        os.getenv("AETERNUS_LLM_PROVIDER", "minimax"),
    ),
    "backend_url": os.getenv("AETERNUS_BACKEND_URL", "https://api.minimax.io/anthropic"),
    # Claude CLI vendor (S-057) — subprocess wrapper for `claude -p`
    # Requires: npm install -g @anthropic-ai/claude-code + claude login
    "claude_cli_deep_model": "claude-sonnet-4-6",
    "claude_cli_quick_model": "claude-haiku-4-5-20251001",
    "claude_cli_fallback_model": "claude-haiku-4-5-20251001",
    "claude_cli_timeout": 120,  # seconds per subprocess call
    "claude_cli_analyst_timeout": int(
        os.getenv("AETERNUS_CLAUDE_CLI_ANALYST_TIMEOUT", "240")
    ),
    "claude_cli_retry_count": int(os.getenv("AETERNUS_CLAUDE_CLI_RETRY_COUNT", "1")),
    # Codex CLI vendor for local GPT-backed graph execution
    "codex_cli_deep_model": os.getenv("AETERNUS_CODEX_DEEP_MODEL", "gpt-5.4"),
    "codex_cli_quick_model": os.getenv("AETERNUS_CODEX_QUICK_MODEL", "gpt-5.4"),
    "codex_cli_deep_reasoning_effort": os.getenv("AETERNUS_CODEX_DEEP_REASONING_EFFORT", "high"),
    "codex_cli_quick_reasoning_effort": os.getenv("AETERNUS_CODEX_QUICK_REASONING_EFFORT", "medium"),
    # Deep research execution mode.
    # `session_engine` mirrors the simple Claude session path: one provider run over one packet,
    # then Python scoring/report writing. `codex_bridge` keeps the legacy graph bridge available.
    "research_execution_mode": os.getenv("AETERNUS_RESEARCH_EXECUTION_MODE", "session_engine"),
    "research_analyst_provider": os.getenv("AETERNUS_RESEARCH_ANALYST_PROVIDER", "claude"),
    "research_post_analyst_provider": os.getenv("AETERNUS_RESEARCH_POST_ANALYST_PROVIDER", "claude"),
    "codex_cli_binary": os.getenv("AETERNUS_CODEX_CLI_BINARY", "codex"),
    "codex_cli_model": os.getenv("AETERNUS_CODEX_MODEL", "gpt-5.4"),
    "codex_cli_reasoning_effort": os.getenv("AETERNUS_CODEX_REASONING_EFFORT", "xhigh"),
    "codex_cli_timeout_seconds": int(os.getenv("AETERNUS_CODEX_TIMEOUT_SECONDS", "300")),
    "codex_cli_retry_count": int(os.getenv("AETERNUS_CODEX_RETRY_COUNT", "1")),
    # Enable Anthropic adaptive thinking for deep_thinking_llm (Opus 4.6+ only).
    # Only applies when llm_provider == "anthropic". Set False to disable.
    "anthropic_adaptive_thinking": True,
    # Debate and discussion settings
    # 1 round = fastest (best case, judge decides after single exchange ~4 min discussion)
    # 3 rounds = most thorough (~10 min discussion). Use 1 for batch/live, 3 for high-conviction names.
    "max_tool_iterations_per_analyst": int(
        os.getenv("AETERNUS_MAX_TOOL_ITERATIONS_PER_ANALYST", "3")
    ),
    "max_recur_limit": 100,
    # Data vendor configuration
    # Category-level configuration (default for all tools in category)
    "data_vendors": {
        "core_stock_apis": "yfinance",       # Options: yfinance, alpha_vantage, local
        "technical_indicators": "yfinance",  # Options: yfinance, alpha_vantage, local
        "fundamental_data": "alpha_vantage", # Options: openai, alpha_vantage, local
        # Google web news primary, Alpha Vantage structured fallback.
        # xAI removed from news data — Grok live search is billed per-query, too expensive.
        # xAI is used only in deal flow cashtag LLM enrichment (hardcoded, budget-gated).
        "news_data": "google,alpha_vantage,local",  # Options: openai, alpha_vantage, google, local
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {},
    # Deal flow scout settings. Scout tickers are counted and handed to fundamental;
    # no pre-fundamental score or selection artifact is produced.
    "dealflow_trigger_vix_jump_pct": 15.0,
    "dealflow_trigger_spy_move_pct": 1.5,
    "dealflow_sec_user_agent": os.getenv(
        "SEC_API_USER_AGENT",
        "AeternusAgentsAG/1.0 (research@aeternus.ai)",
    ),
    # Legacy smart_money connector retired; 13F sourcing now uses the PIT-tested
    # thirteenf_watchlist scout. Congress trades require separate backtest before use.
    "dealflow_social_lookback_days": int(
        os.getenv("DEALFLOW_SOCIAL_LOOKBACK_DAYS", "7")
    ),
    "dealflow_manual_x_feed_carryforward_days": int(
        os.getenv("DEALFLOW_MANUAL_X_FEED_CARRYFORWARD_DAYS", "3")
    ),
    "dealflow_technical_ignition_enabled": os.getenv(
        "DEALFLOW_TECHNICAL_IGNITION_ENABLED", "true"
    ).lower()
    == "true",
    "dealflow_technical_signal_db_path": os.getenv(
        "DEALFLOW_TECHNICAL_SIGNAL_DB_PATH",
        str(os.path.join("eval_results", "control", "technical_signal_cache.db")),
    ),
    "dealflow_x_influencer_handles": os.getenv(
        "DEALFLOW_X_INFLUENCER_HANDLES",
        "TheTechInvest,KobeissiLetter,unusual_whales,markets,StockMKTNewz",
    ),
    "dealflow_x_daily_budget_usd": float(os.getenv("DEALFLOW_X_DAILY_BUDGET_USD", "15")),
    "dealflow_x_max_api_calls_per_run": int(
        os.getenv("DEALFLOW_X_MAX_API_CALLS_PER_RUN", "8")
    ),
    "dealflow_x_enrich_top_posts": int(os.getenv("DEALFLOW_X_ENRICH_TOP_POSTS", "20")),
    "dealflow_x_cost_per_api_call_usd": float(
        os.getenv("DEALFLOW_X_COST_PER_API_CALL_USD", "1.00")
    ),
    "dealflow_news_cost_per_run_usd": float(
        os.getenv("DEALFLOW_NEWS_COST_PER_RUN_USD", "0.00")
    ),
    "dealflow_macro_cost_per_run_usd": float(
        os.getenv("DEALFLOW_MACRO_COST_PER_RUN_USD", "0.00")
    ),
    "dealflow_x_auto_tune_enabled": os.getenv(
        "DEALFLOW_X_AUTO_TUNE_ENABLED",
        "true",
    ).lower()
    == "true",
    "dealflow_x_auto_tune_apply": os.getenv(
        "DEALFLOW_X_AUTO_TUNE_APPLY",
        "true",
    ).lower()
    == "true",
    "dealflow_x_tuner_lookback_days": int(
        os.getenv("DEALFLOW_X_TUNER_LOOKBACK_DAYS", "30")
    ),
    "dealflow_x_tuner_min_evaluated": int(
        os.getenv("DEALFLOW_X_TUNER_MIN_EVALUATED", "6")
    ),
    "dealflow_x_tuner_edge_up_threshold": float(
        os.getenv("DEALFLOW_X_TUNER_EDGE_UP_THRESHOLD", "1.0")
    ),
    "dealflow_x_tuner_edge_down_threshold": float(
        os.getenv("DEALFLOW_X_TUNER_EDGE_DOWN_THRESHOLD", "-1.0")
    ),
    "dealflow_x_tuner_win_rate_up": float(
        os.getenv("DEALFLOW_X_TUNER_WIN_RATE_UP", "0.55")
    ),
    "dealflow_x_tuner_win_rate_down": float(
        os.getenv("DEALFLOW_X_TUNER_WIN_RATE_DOWN", "0.45")
    ),
    "dealflow_x_tuner_min_calls": int(
        os.getenv("DEALFLOW_X_TUNER_MIN_CALLS", "1")
    ),
    "dealflow_x_tuner_max_calls": int(
        os.getenv("DEALFLOW_X_TUNER_MAX_CALLS", "15")
    ),
    "dealflow_x_tuner_max_step_calls": int(
        os.getenv("DEALFLOW_X_TUNER_MAX_STEP_CALLS", "1")
    ),
    "dealflow_x_tuner_min_daily_budget_usd": float(
        os.getenv("DEALFLOW_X_TUNER_MIN_DAILY_BUDGET_USD", "8.0")
    ),
    "dealflow_x_tuner_max_daily_budget_usd": float(
        os.getenv("DEALFLOW_X_TUNER_MAX_DAILY_BUDGET_USD", "30.0")
    ),
    "dealflow_x_tuner_require_horizon_alignment": os.getenv(
        "DEALFLOW_X_TUNER_REQUIRE_HORIZON_ALIGNMENT",
        "true",
    ).lower()
    == "true",
    "dealflow_x_tuner_families": os.getenv(
        "DEALFLOW_X_TUNER_FAMILIES",
        "social_momentum,news_catalyst",
    ),
    # Dormant-sector outlier z-score threshold (used by x_feed_scout)
    "sector_scout_outlier_velocity_z": 3.0,
    "dealflow_dynamic_universe_min_adv_usd": float(
        os.getenv("DEALFLOW_DYNAMIC_UNIVERSE_MIN_ADV_USD", "50000000")
    ),
    "dealflow_dynamic_universe_max_extra_symbols": int(
        os.getenv("DEALFLOW_DYNAMIC_UNIVERSE_MAX_EXTRA_SYMBOLS", "60")
    ),
    # AKG supply-chain universe expansion: any company node with centrality >= threshold
    # is added to the deal-flow universe even if absent from the hardcoded base list.
    # Uses a lower ADV floor (5M) than manual/cashtag extras (50M) to include mid-small
    # caps that are structurally important supply-chain nodes.
    "dealflow_akg_min_centrality": float(
        os.getenv("DEALFLOW_AKG_MIN_CENTRALITY", "0.1")
    ),
    "dealflow_akg_extra_min_adv_usd": float(
        os.getenv("DEALFLOW_AKG_EXTRA_MIN_ADV_USD", "5000000")
    ),
    "dealflow_connector_timeout_seconds": float(
        os.getenv("DEALFLOW_CONNECTOR_TIMEOUT_SECONDS", "45")
    ),
    "dealflow_connector_max_attempts": int(
        os.getenv("DEALFLOW_CONNECTOR_MAX_ATTEMPTS", "2")
    ),
    # Insider Sweep Scout (Form 4 EDGAR sweep)
    "dealflow_edgar_sleep_seconds": float(os.getenv("DEALFLOW_EDGAR_SLEEP_SECONDS", "0.15")),
    "dealflow_insider_cluster_enabled": os.getenv("DEALFLOW_INSIDER_CLUSTER_ENABLED", "true").lower() == "true",
    "dealflow_insider_sweep_window_days": int(os.getenv("DEALFLOW_INSIDER_SWEEP_WINDOW_DAYS", "30")),
    "dealflow_insider_sweep_max_staleness_days": int(os.getenv("DEALFLOW_INSIDER_SWEEP_MAX_STALENESS_DAYS", "2")),
    "dealflow_discovered_symbol_min_len": int(
        os.getenv("DEALFLOW_DISCOVERED_SYMBOL_MIN_LEN", "2")
    ),
    "dealflow_discovered_symbol_max_len": int(
        os.getenv("DEALFLOW_DISCOVERED_SYMBOL_MAX_LEN", "5")
    ),
    "dealflow_discovered_symbol_denylist": os.getenv(
        "DEALFLOW_DISCOVERED_SYMBOL_DENYLIST",
        "BTC,ETH,BNB,DOGE,SHIB,ICP,MATIC,AVAX,DOT,FIL,ARB,HYPE,SPX,NDX,DJIA,NQ,ES,VIX",
    ),
    "dealflow_manual_watchlist_path": os.getenv(
        "DEALFLOW_MANUAL_WATCHLIST_PATH",
        "eval_results/deal_flow/manual_watchlist.json",
    ),
    "dealflow_manual_slots_target": int(
        os.getenv("DEALFLOW_MANUAL_SLOTS_TARGET", "3")
    ),
    "dealflow_manual_slots_min": int(
        os.getenv("DEALFLOW_MANUAL_SLOTS_MIN", "2")
    ),
    "dealflow_manual_slots_max": int(
        os.getenv("DEALFLOW_MANUAL_SLOTS_MAX", "4")
    ),
    "dealflow_manual_min_adv_usd": float(
        os.getenv("DEALFLOW_MANUAL_MIN_ADV_USD", "50000000")
    ),
    "dealflow_manual_force_insert": os.getenv(
        "DEALFLOW_MANUAL_FORCE_INSERT",
        "true",
    ).lower()
    == "true",
    "dealflow_manual_default_ttl_days": int(
        os.getenv("DEALFLOW_MANUAL_DEFAULT_TTL_DAYS", "30")
    ),
    "dealflow_x_expansion_velocity_z": float(
        os.getenv("DEALFLOW_X_EXPANSION_VELOCITY_Z", "2.0")
    ),
    "dealflow_x_discovery_enabled": os.getenv(
        "DEALFLOW_X_DISCOVERY_ENABLED",
        "true",
    ).lower()
    == "true",
    "dealflow_x_discovery_weekday": int(
        os.getenv("DEALFLOW_X_DISCOVERY_WEEKDAY", "6")
    ),
    "dealflow_x_discovery_max_new_accounts": int(
        os.getenv("DEALFLOW_X_DISCOVERY_MAX_NEW_ACCOUNTS", "25")
    ),
    "dealflow_x_discovery_min_quality": float(
        os.getenv("DEALFLOW_X_DISCOVERY_MIN_QUALITY", "55")
    ),
    "dealflow_x_discovery_min_posts": int(
        os.getenv("DEALFLOW_X_DISCOVERY_MIN_POSTS", "3")
    ),
    # Centrality-gated universe filter (reduces ~5,000 AKG nodes to ~300-450)
    "dealflow_universe_filter_enabled": True,
    "dealflow_filter_dark_centrality": 0.3,
    "dealflow_filter_two_hop_centrality": 0.05,
    "dealflow_anchor_cache_ttl_days": 7,
    "dealflow_fvg_recall_enabled": os.getenv("DEALFLOW_FVG_RECALL_ENABLED", "true").lower() == "true",
    "dealflow_fvg_recall_quota": int(os.getenv("DEALFLOW_FVG_RECALL_QUOTA", "30")),
    "dealflow_fvg_recall_min_rs20": float(os.getenv("DEALFLOW_FVG_RECALL_MIN_RS20", "0.03")),
    "dealflow_fvg_recall_min_liquidity_score": float(
        os.getenv("DEALFLOW_FVG_RECALL_MIN_LIQUIDITY_SCORE", "30.0")
    ),
    "dealflow_fma_recall_enabled": os.getenv("DEALFLOW_FMA_RECALL_ENABLED", "true").lower() == "true",
    "dealflow_fma_recall_quota": int(os.getenv("DEALFLOW_FMA_RECALL_QUOTA", "20")),
    "dealflow_fma_recall_min_score": float(os.getenv("DEALFLOW_FMA_RECALL_MIN_SCORE", "60.0")),
    "dealflow_max_sector_count": int(os.getenv("DEALFLOW_MAX_SECTOR_COUNT", "5")),
    "dealflow_core_quota": int(os.getenv("DEALFLOW_CORE_QUOTA", "18")),
    "dealflow_momentum_quota": int(os.getenv("DEALFLOW_MOMENTUM_QUOTA", "12")),
    "dealflow_deep_core_quota": int(os.getenv("DEALFLOW_DEEP_CORE_QUOTA", "4")),
    "dealflow_deep_momentum_quota": int(os.getenv("DEALFLOW_DEEP_MOMENTUM_QUOTA", "4")),
    "dealflow_momentum_lane_threshold": float(
        os.getenv("DEALFLOW_MOMENTUM_LANE_THRESHOLD", "68.0")
    ),
    "dealflow_momentum_lane_price_override_threshold": float(
        os.getenv("DEALFLOW_MOMENTUM_LANE_PRICE_OVERRIDE_THRESHOLD", "82.0")
    ),
    "dealflow_momentum_lane_social_confirmation_threshold": float(
        os.getenv("DEALFLOW_MOMENTUM_LANE_SOCIAL_CONFIRMATION_THRESHOLD", "60.0")
    ),
    "dealflow_momentum_lane_floor_ratio": float(
        os.getenv("DEALFLOW_MOMENTUM_LANE_FLOOR_RATIO", "0.20")
    ),
    "dealflow_momentum_lane_promotion_min_score": float(
        os.getenv("DEALFLOW_MOMENTUM_LANE_PROMOTION_MIN_SCORE", "62.0")
    ),
    "dealflow_momentum_lane_promotion_min_price_score": float(
        os.getenv("DEALFLOW_MOMENTUM_LANE_PROMOTION_MIN_PRICE_SCORE", "70.0")
    ),
    "dealflow_scheduler_timezone": os.getenv(
        "DEALFLOW_SCHEDULER_TIMEZONE",
        "America/New_York",
    ),
    "dealflow_scheduler_preopen_start": os.getenv(
        "DEALFLOW_SCHEDULER_PREOPEN_START",
        "08:00",
    ),
    "dealflow_scheduler_preopen_end": os.getenv(
        "DEALFLOW_SCHEDULER_PREOPEN_END",
        "09:25",
    ),
    "dealflow_event_cooldown_minutes": int(
        os.getenv("DEALFLOW_EVENT_COOLDOWN_MINUTES", "90")
    ),
    # Operator gateway/control-plane defaults (Week 1 handshake)
    "operator_gateway_heartbeat_path": os.getenv(
        "OPERATOR_GATEWAY_HEARTBEAT_PATH",
        "eval_results/control/engine_heartbeat.json",
    ),
    "operator_gateway_system_halt_path": os.getenv(
        "OPERATOR_GATEWAY_SYSTEM_HALT_PATH",
        "eval_results/control/system_halt.json",
    ),
    "operator_gateway_triage_intents_path": os.getenv(
        "OPERATOR_GATEWAY_TRIAGE_INTENTS_PATH",
        "eval_results/deal_flow/ui/triage_intents.json",
    ),
    "operator_gateway_triage_receipts_path": os.getenv(
        "OPERATOR_GATEWAY_TRIAGE_RECEIPTS_PATH",
        "eval_results/deal_flow/ui/triage_receipts.json",
    ),
    "operator_gateway_negative_constraints_path": os.getenv(
        "OPERATOR_GATEWAY_NEGATIVE_CONSTRAINTS_PATH",
        "eval_results/deal_flow/ui/negative_constraints.json",
    ),
    "operator_gateway_allocator_db_path": os.getenv(
        "OPERATOR_GATEWAY_ALLOCATOR_DB_PATH",
        "eval_results/control/capital_allocator.db",
    ),
    "operator_gateway_allocator_regime_override_path": os.getenv(
        "OPERATOR_GATEWAY_ALLOCATOR_REGIME_OVERRIDE_PATH",
        "eval_results/control/allocator_regime_override.json",
    ),
    "operator_gateway_dealflow_base_dir": os.getenv(
        "OPERATOR_GATEWAY_DEALFLOW_BASE_DIR",
        "eval_results/deal_flow",
    ),
    "operator_gateway_scout_handoff_path": os.getenv(
        "OPERATOR_GATEWAY_SCOUT_HANDOFF_PATH",
        "",
    ),
    "operator_gateway_heartbeat_ttl_seconds": float(
        os.getenv("OPERATOR_GATEWAY_HEARTBEAT_TTL_SECONDS", "25")
    ),
    "operator_gateway_clock_offset_max_seconds": float(
        os.getenv("OPERATOR_GATEWAY_CLOCK_OFFSET_MAX_SECONDS", "5")
    ),
    "operator_gateway_intent_maturity_seconds": float(
        os.getenv("OPERATOR_GATEWAY_INTENT_MATURITY_SECONDS", "5")
    ),
    "operator_gateway_ingress_guard_seconds": float(
        os.getenv("OPERATOR_GATEWAY_INGRESS_GUARD_SECONDS", "2")
    ),
    "operator_gateway_price_slip_max_bps": float(
        os.getenv("OPERATOR_GATEWAY_PRICE_SLIP_MAX_BPS", "150")
    ),
    "operator_gateway_price_latency_max_ms": float(
        os.getenv("OPERATOR_GATEWAY_PRICE_LATENCY_MAX_MS", "2000")
    ),
    "operator_gateway_negative_constraint_ttl_days": int(
        os.getenv("OPERATOR_GATEWAY_NEGATIVE_CONSTRAINT_TTL_DAYS", "14")
    ),
    "operator_gateway_unknown_panic_seconds": float(
        os.getenv("OPERATOR_GATEWAY_UNKNOWN_PANIC_SECONDS", "30")
    ),
    "operator_gateway_thesis_summary_max_chars": int(
        os.getenv("OPERATOR_GATEWAY_THESIS_SUMMARY_MAX_CHARS", "140")
    ),
    "operator_gateway_detail_summary_max_chars": int(
        os.getenv("OPERATOR_GATEWAY_DETAIL_SUMMARY_MAX_CHARS", "320")
    ),
    "operator_gateway_bootstrap_since_minutes": int(
        os.getenv("OPERATOR_GATEWAY_BOOTSTRAP_SINCE_MINUTES", "60")
    ),
    "operator_gateway_bootstrap_top_candidates": int(
        os.getenv("OPERATOR_GATEWAY_BOOTSTRAP_TOP_CANDIDATES", "12")
    ),
    "operator_gateway_bootstrap_etag_bucket_seconds": int(
        os.getenv("OPERATOR_GATEWAY_BOOTSTRAP_ETAG_BUCKET_SECONDS", "20")
    ),
    "operator_gateway_model_allocation_path": os.getenv(
        "OPERATOR_GATEWAY_MODEL_ALLOCATION_PATH",
        "eval_results/control/model_allocation.json",
    ),
    "operator_gateway_broker_allocation_path": os.getenv(
        "OPERATOR_GATEWAY_BROKER_ALLOCATION_PATH",
        "eval_results/control/broker_allocation.json",
    ),
    "operator_gateway_drift_aligned_threshold_pct": float(
        os.getenv("OPERATOR_GATEWAY_DRIFT_ALIGNED_THRESHOLD_PCT", "5.0")
    ),
    "operator_gateway_drift_disconnected_threshold_pct": float(
        os.getenv("OPERATOR_GATEWAY_DRIFT_DISCONNECTED_THRESHOLD_PCT", "15.0")
    ),
    "operator_gateway_portfolio_sync_stale_seconds": float(
        os.getenv("OPERATOR_GATEWAY_PORTFOLIO_SYNC_STALE_SECONDS", "1200")
    ),
    "operator_gateway_non_model_min_pct": float(
        os.getenv("OPERATOR_GATEWAY_NON_MODEL_MIN_PCT", "1.0")
    ),
    "operator_gateway_drift_settings_path": os.getenv(
        "OPERATOR_GATEWAY_DRIFT_SETTINGS_PATH",
        "eval_results/control/drift_sensitivity.json",
    ),
    "operator_gateway_drift_snapshot_path": os.getenv(
        "OPERATOR_GATEWAY_DRIFT_SNAPSHOT_PATH",
        "eval_results/control/drift_snapshot.json",
    ),
    "operator_gateway_drift_background_enabled": os.getenv(
        "OPERATOR_GATEWAY_DRIFT_BACKGROUND_ENABLED",
        "true",
    ).lower()
    == "true",
    "operator_gateway_drift_background_interval_seconds": float(
        os.getenv("OPERATOR_GATEWAY_DRIFT_BACKGROUND_INTERVAL_SECONDS", "30")
    ),
    "operator_gateway_cors_origins": os.getenv(
        "OPERATOR_GATEWAY_CORS_ORIGINS",
        "",
    ),
    "operator_gateway_enforce_api_key": os.getenv(
        "OPERATOR_GATEWAY_ENFORCE_API_KEY",
        "true",
    ).lower()
    == "true",
    "operator_gateway_api_key_header": os.getenv(
        "OPERATOR_GATEWAY_API_KEY_HEADER",
        "X-Aeternus-Key",
    ),
    "operator_gateway_api_key": os.getenv(
        "OPERATOR_GATEWAY_API_KEY",
        "",
    ),
    "operator_gateway_mirror_challenge_ttl_seconds": float(
        os.getenv("OPERATOR_GATEWAY_MIRROR_CHALLENGE_TTL_SECONDS", "300")
    ),
    "operator_gateway_require_legal_consent": os.getenv(
        "OPERATOR_GATEWAY_REQUIRE_LEGAL_CONSENT",
        "true",
    ).lower()
    == "true",
    "operator_gateway_legal_version": os.getenv(
        "OPERATOR_GATEWAY_LEGAL_VERSION",
        "2026-02-08.v1",
    ),
    "operator_gateway_broker_adapter": os.getenv(
        "OPERATOR_GATEWAY_BROKER_ADAPTER",
        "disabled",
    ),
    # Step 1 readiness gates (go/no-go for moving to Step 2)
    "dealflow_step1_lookback_days": int(
        os.getenv("DEALFLOW_STEP1_LOOKBACK_DAYS", "60")
    ),
    "dealflow_step1_required_stable_cycles": int(
        os.getenv("DEALFLOW_STEP1_REQUIRED_STABLE_CYCLES", "3")
    ),
    "dealflow_step1_min_batch_executed_per_cycle": int(
        os.getenv("DEALFLOW_STEP1_MIN_BATCH_EXECUTED_PER_CYCLE", "1")
    ),
    "dealflow_step1_max_batch_failure_ratio": float(
        os.getenv("DEALFLOW_STEP1_MAX_BATCH_FAILURE_RATIO", "0.40")
    ),
    "dealflow_step1_max_connector_errors_per_cycle": int(
        os.getenv("DEALFLOW_STEP1_MAX_CONNECTOR_ERRORS_PER_CYCLE", "0")
    ),
    "dealflow_step1_min_evaluated_5d": int(
        os.getenv("DEALFLOW_STEP1_MIN_EVALUATED_5D", "2")
    ),
    "dealflow_step1_min_evaluated_20d": int(
        os.getenv("DEALFLOW_STEP1_MIN_EVALUATED_20D", "2")
    ),
    "dealflow_step1_target_evaluated_5d": int(
        os.getenv("DEALFLOW_STEP1_TARGET_EVALUATED_5D", "20")
    ),
    "dealflow_step1_target_evaluated_20d": int(
        os.getenv("DEALFLOW_STEP1_TARGET_EVALUATED_20D", "20")
    ),
    "dealflow_step1_required_connectors": os.getenv(
        "DEALFLOW_STEP1_REQUIRED_CONNECTORS",
        "social_news,price_momentum,macro",
    ),
    "dealflow_step1_optional_connectors": os.getenv(
        "DEALFLOW_STEP1_OPTIONAL_CONNECTORS",
        "",
    ),
    "dealflow_step1_required_connector_statuses": os.getenv(
        "DEALFLOW_STEP1_REQUIRED_CONNECTOR_STATUSES",
        "OK,NO_DATA",
    ),
    # Step 2 evidence-pack defaults
    "evidence_primary_benchmark": os.getenv(
        "EVIDENCE_PRIMARY_BENCHMARK",
        "SPY",
    ),
    "evidence_secondary_benchmark": os.getenv(
        "EVIDENCE_SECONDARY_BENCHMARK",
        "QQQ",
    ),
    "evidence_walkforward_train_days": int(
        os.getenv("EVIDENCE_WALKFORWARD_TRAIN_DAYS", "756")
    ),
    "evidence_walkforward_test_days": int(
        os.getenv("EVIDENCE_WALKFORWARD_TEST_DAYS", "252")
    ),
    "evidence_walkforward_step_days": int(
        os.getenv("EVIDENCE_WALKFORWARD_STEP_DAYS", "63")
    ),
    "evidence_walkforward_fallback_train_days": int(
        os.getenv("EVIDENCE_WALKFORWARD_FALLBACK_TRAIN_DAYS", "252")
    ),
    "evidence_walkforward_fallback_test_days": int(
        os.getenv("EVIDENCE_WALKFORWARD_FALLBACK_TEST_DAYS", "63")
    ),
    "evidence_min_walkforward_windows": int(
        os.getenv("EVIDENCE_MIN_WALKFORWARD_WINDOWS", "3")
    ),
    "evidence_min_regime_slices": int(
        os.getenv("EVIDENCE_MIN_REGIME_SLICES", "4")
    ),
    "evidence_complete_required_regimes": os.getenv(
        "EVIDENCE_COMPLETE_REQUIRED_REGIMES",
        "BEAR,HIGH_VOL,INFLATION_SHOCK",
    ),
    "evidence_complete_min_regime_days": int(
        os.getenv("EVIDENCE_COMPLETE_MIN_REGIME_DAYS", "180")
    ),
    "evidence_max_edge_decay_5d": float(
        os.getenv("EVIDENCE_MAX_EDGE_DECAY_5D", "2.0")
    ),
    "evidence_max_edge_decay_20d": float(
        os.getenv("EVIDENCE_MAX_EDGE_DECAY_20D", "2.0")
    ),
    "evidence_readiness_allow_partial_data": os.getenv(
        "EVIDENCE_READINESS_ALLOW_PARTIAL_DATA",
        "false",
    ).lower()
    == "true",
    "evidence_runtime_soft_cap_seconds": float(
        os.getenv("EVIDENCE_RUNTIME_SOFT_CAP_SECONDS", "600")
    ),
    "evidence_runtime_hard_cap_seconds": float(
        os.getenv("EVIDENCE_RUNTIME_HARD_CAP_SECONDS", "1200")
    ),
    "evidence_dgs10_series_path": os.getenv(
        "EVIDENCE_DGS10_SERIES_PATH",
        "",
    ),
    "evidence_cpi_series_path": os.getenv(
        "EVIDENCE_CPI_SERIES_PATH",
        "",
    ),
    # Step 2 portfolio construction + execution defaults
    "portfolio_capital_usd": float(
        os.getenv("PORTFOLIO_CAPITAL_USD", "100000")
    ),
    "portfolio_max_positions": int(
        os.getenv("PORTFOLIO_MAX_POSITIONS", "8")
    ),
    "portfolio_min_score": float(
        os.getenv("PORTFOLIO_MIN_SCORE", "62")
    ),
    "portfolio_min_confidence": int(
        os.getenv("PORTFOLIO_MIN_CONFIDENCE", "3")
    ),
    "portfolio_max_weight_per_position": float(
        os.getenv("PORTFOLIO_MAX_WEIGHT_PER_POSITION", "0.25")
    ),
    "portfolio_include_hedges": os.getenv(
        "PORTFOLIO_INCLUDE_HEDGES",
        "true",
    ).lower()
    == "true",
    "portfolio_include_cc_wyckoff": os.getenv(
        "PORTFOLIO_INCLUDE_CC_WYCKOFF",
        "true",
    ).lower()
    == "true",
    "cc_wyckoff_max_notional_pct": float(
        os.getenv("CC_WYCKOFF_MAX_NOTIONAL_PCT", "1.0")
    ),
    "portfolio_include_cc_scanner": os.getenv(
        "PORTFOLIO_INCLUDE_CC_SCANNER",
        "true",
    ).lower()
    == "true",
    "cc_scanner_max_signals": int(
        os.getenv("CC_SCANNER_MAX_SIGNALS", "10")
    ),
    "execution_broker_mode": os.getenv(
        "EXECUTION_BROKER_MODE",
        "paper",
    ),
    "alpaca_api_key_id": os.getenv(
        "APCA_API_KEY_ID",
        os.getenv("ALPACA_API_KEY_ID", ""),
    ),
    "alpaca_api_secret_key": os.getenv(
        "APCA_API_SECRET_KEY",
        os.getenv("ALPACA_API_SECRET_KEY", ""),
    ),
    "alpaca_api_base_url": os.getenv(
        "ALPACA_API_BASE_URL",
        "",
    ),
    "alpaca_paper_api_base_url": os.getenv(
        "ALPACA_PAPER_API_BASE_URL",
        "https://paper-api.alpaca.markets",
    ),
    "alpaca_live_api_base_url": os.getenv(
        "ALPACA_LIVE_API_BASE_URL",
        "https://api.alpaca.markets",
    ),
    "alpaca_request_timeout_seconds": float(
        os.getenv("ALPACA_REQUEST_TIMEOUT_SECONDS", "15")
    ),
    "alpaca_enforce_whole_shares": os.getenv(
        "ALPACA_ENFORCE_WHOLE_SHARES",
        "true",
    ).lower()
    == "true",
    "paper_execution_slippage_bps": float(
        os.getenv("PAPER_EXECUTION_SLIPPAGE_BPS", "5.0")
    ),
    "execution_min_adv_usd": float(
        os.getenv("EXECUTION_MIN_ADV_USD", "10000000")
    ),
    "execution_min_market_cap": float(
        os.getenv("EXECUTION_MIN_MARKET_CAP", "100000000")
    ),
    "execution_max_gross_exposure_pct": float(
        os.getenv("EXECUTION_MAX_GROSS_EXPOSURE_PCT", "1.00")
    ),
    "execution_max_single_position_pct": float(
        os.getenv("EXECUTION_MAX_SINGLE_POSITION_PCT", "0.25")
    ),
    "execution_max_open_positions": int(
        os.getenv("EXECUTION_MAX_OPEN_POSITIONS", "12")
    ),
    "execution_max_new_orders_per_run": int(
        os.getenv("EXECUTION_MAX_NEW_ORDERS_PER_RUN", "12")
    ),
    "execution_block_short_orders": os.getenv(
        "EXECUTION_BLOCK_SHORT_ORDERS",
        "true",
    ).lower()
    == "true",
    "execution_allow_hedge_short_orders": os.getenv(
        "EXECUTION_ALLOW_HEDGE_SHORT_ORDERS",
        "true",
    ).lower()
    == "true",
    "execution_max_hedge_notional_pct": float(
        os.getenv("EXECUTION_MAX_HEDGE_NOTIONAL_PCT", "1.50")
    ),
    "execution_rebalance_to_target": os.getenv(
        "EXECUTION_REBALANCE_TO_TARGET",
        "true",
    ).lower()
    == "true",
    # FRED API key for live SOFR risk-free rate (P1-01)
    "fred_api_key": os.getenv("FRED_API_KEY", ""),
    # Push alert settings (P1-03)
    "alerting_webhook_url": os.getenv("ALERTING_WEBHOOK_URL", ""),
    "alerting_enabled": os.getenv("ALERTING_ENABLED", "false").lower() in ("1", "true", "yes"),
    "alerting_pnl_loss_threshold_pct": float(os.getenv("ALERTING_PNL_LOSS_THRESHOLD_PCT", "0.10")),
    "alerting_execution_latency_threshold_seconds": float(os.getenv("ALERTING_EXECUTION_LATENCY_THRESHOLD_SECONDS", "30")),
    # Risk circuit breaker settings (P0-01, P2-01)
    "risk_max_daily_loss_pct": float(os.getenv("RISK_MAX_DAILY_LOSS_PCT", "0.02")),
    "risk_nlv_floor_usd": float(os.getenv("RISK_NLV_FLOOR_USD", "0")),
    "risk_max_drawdown_pct": float(os.getenv("RISK_MAX_DRAWDOWN_PCT", "0.10")),
    "risk_max_var_pct": float(os.getenv("RISK_MAX_VAR_PCT", "0.05")),
    "risk_high_water_mark_path": os.getenv("RISK_HIGH_WATER_MARK_PATH", "eval_results/control/hwm.json"),
    # Quantitative risk hard gates (P2-06)
    "risk_max_sector_pct": float(os.getenv("RISK_MAX_SECTOR_PCT", "0.40")),
    "risk_max_correlated_group_pct": float(os.getenv("RISK_MAX_CORRELATED_GROUP_PCT", "0.50")),
    "workflow_loop_default_cycles": int(
        os.getenv("WORKFLOW_LOOP_DEFAULT_CYCLES", "1")
    ),
    "workflow_loop_interval_seconds": int(
        os.getenv("WORKFLOW_LOOP_INTERVAL_SECONDS", "900")
    ),
    "execution_min_rebalance_notional_usd": float(
        os.getenv("EXECUTION_MIN_REBALANCE_NOTIONAL_USD", "100.0")
    ),
    "execution_close_missing_positions": os.getenv(
        "EXECUTION_CLOSE_MISSING_POSITIONS",
        "false",
    ).lower()
    == "true",
    "paper_orders_path": os.getenv(
        "PAPER_ORDERS_PATH",
        "eval_results/paper_execution/orders.json",
    ),
    "live_execution_outbox_path": os.getenv(
        "LIVE_EXECUTION_OUTBOX_PATH",
        "eval_results/live_execution/outbox.json",
    ),
    "live_positions_shadow_path": os.getenv(
        "LIVE_POSITIONS_SHADOW_PATH",
        "eval_results/live_execution/positions_shadow.json",
    ),
    "live_execution_fills_path": os.getenv(
        "LIVE_EXECUTION_FILLS_PATH",
        "eval_results/live_execution/fills.json",
    ),
    "live_execution_closed_trades_path": os.getenv(
        "LIVE_EXECUTION_CLOSED_TRADES_PATH",
        "eval_results/live_execution/closed_trades.json",
    ),
    "live_broker_orders_snapshot_path": os.getenv(
        "LIVE_BROKER_ORDERS_SNAPSHOT_PATH",
        "eval_results/live_execution/broker_orders_latest.json",
    ),
    "live_broker_positions_snapshot_path": os.getenv(
        "LIVE_BROKER_POSITIONS_SNAPSHOT_PATH",
        "eval_results/live_execution/broker_positions_latest.json",
    ),
    "execution_exit_stop_loss_pct": float(
        os.getenv("EXECUTION_EXIT_STOP_LOSS_PCT", "0.08")
    ),
    "execution_exit_take_profit_pct": float(
        os.getenv("EXECUTION_EXIT_TAKE_PROFIT_PCT", "0.20")
    ),
    "execution_exit_max_hold_days": int(
        os.getenv("EXECUTION_EXIT_MAX_HOLD_DAYS", "20")
    ),
    "execution_exit_trailing_stop_pct": float(
        os.getenv("EXECUTION_EXIT_TRAILING_STOP_PCT", "0.00")
    ),
    "execution_exit_min_position_notional_usd": float(
        os.getenv("EXECUTION_EXIT_MIN_POSITION_NOTIONAL_USD", "250.0")
    ),
    "execution_exit_max_orders_per_run": int(
        os.getenv("EXECUTION_EXIT_MAX_ORDERS_PER_RUN", "6")
    ),
    "execution_readiness_max_stale_submitted_minutes": int(
        os.getenv("EXECUTION_READINESS_MAX_STALE_SUBMITTED_MINUTES", "180")
    ),
    "execution_readiness_max_unmatched_open_orders": int(
        os.getenv("EXECUTION_READINESS_MAX_UNMATCHED_OPEN_ORDERS", "10")
    ),
    "execution_readiness_max_position_drift_notional_usd": float(
        os.getenv("EXECUTION_READINESS_MAX_POSITION_DRIFT_NOTIONAL_USD", "2500.0")
    ),
    "execution_readiness_min_buying_power_usd": float(
        os.getenv("EXECUTION_READINESS_MIN_BUYING_POWER_USD", "1.0")
    ),
    "execution_require_position_parity_for_live": os.getenv(
        "EXECUTION_REQUIRE_POSITION_PARITY_FOR_LIVE",
        "true",
    ).lower()
    == "true",
    "execution_block_on_position_drift": os.getenv(
        "EXECUTION_BLOCK_ON_POSITION_DRIFT",
        "true",
    ).lower()
    == "true",
    "execution_position_parity_refresh_snapshot": os.getenv(
        "EXECUTION_POSITION_PARITY_REFRESH_SNAPSHOT",
        "true",
    ).lower()
    == "true",
    "execution_position_parity_qty_tolerance": float(
        os.getenv("EXECUTION_POSITION_PARITY_QTY_TOLERANCE", "0.0001")
    ),
    "execution_position_parity_notional_tolerance_usd": float(
        os.getenv("EXECUTION_POSITION_PARITY_NOTIONAL_TOLERANCE_USD", "25.0")
    ),
    "execution_open_orders_max_age_minutes": int(
        os.getenv("EXECUTION_OPEN_ORDERS_MAX_AGE_MINUTES", "90")
    ),
    "execution_open_orders_replace_stale": os.getenv(
        "EXECUTION_OPEN_ORDERS_REPLACE_STALE",
        "false",
    ).lower()
    == "true",
    "execution_open_orders_replacement_order_type": os.getenv(
        "EXECUTION_OPEN_ORDERS_REPLACEMENT_ORDER_TYPE",
        "market",
    ),
    "execution_open_orders_limit_price_offset_bps": float(
        os.getenv("EXECUTION_OPEN_ORDERS_LIMIT_PRICE_OFFSET_BPS", "10.0")
    ),
    "execution_open_orders_max_retries_per_symbol_per_day": int(
        os.getenv("EXECUTION_OPEN_ORDERS_MAX_RETRIES_PER_SYMBOL_PER_DAY", "2")
    ),
    "execution_sync_manage_open_orders": os.getenv(
        "EXECUTION_SYNC_MANAGE_OPEN_ORDERS",
        "false",
    ).lower()
    == "true",
    "execution_sync_manage_open_orders_apply": os.getenv(
        "EXECUTION_SYNC_MANAGE_OPEN_ORDERS_APPLY",
        "false",
    ).lower()
    == "true",
    "execution_sync_sync_shadow_positions": os.getenv(
        "EXECUTION_SYNC_SYNC_SHADOW_POSITIONS",
        "false",
    ).lower()
    == "true",
    "execution_sync_sync_shadow_positions_apply": os.getenv(
        "EXECUTION_SYNC_SYNC_SHADOW_POSITIONS_APPLY",
        "false",
    ).lower()
    == "true",
    "execution_sync_auto_remediate_readiness": os.getenv(
        "EXECUTION_SYNC_AUTO_REMEDIATE_READINESS",
        "true",
    ).lower()
    == "true",
    "execution_sync_auto_remediate_drop_missing": os.getenv(
        "EXECUTION_SYNC_AUTO_REMEDIATE_DROP_MISSING",
        "true",
    ).lower()
    == "true",
    "paper_positions_path": os.getenv(
        "PAPER_POSITIONS_PATH",
        "eval_results/paper_execution/positions.json",
    ),
    "paper_closed_trades_path": os.getenv(
        "PAPER_CLOSED_TRADES_PATH",
        "eval_results/paper_execution/closed_trades.json",
    ),
    # Reconciliation daemon settings (P1-02, P1-05, P2-03)
    "reconciliation_poll_interval_seconds": int(
        os.getenv("RECONCILIATION_POLL_INTERVAL_SECONDS", "60")
    ),
    "reconciliation_auto_exit_check": os.getenv(
        "RECONCILIATION_AUTO_EXIT_CHECK", "false"
    ).lower() in ("1", "true", "yes"),
    "reconciliation_auto_regime_update": os.getenv(
        "RECONCILIATION_AUTO_REGIME_UPDATE", "false"
    ).lower() in ("1", "true", "yes"),
    # Stale data detection (P2-05)
    "max_data_staleness_hours": int(os.getenv("MAX_DATA_STALENESS_HOURS", "24")),
    # AKG Emerging Planets universe expansion (S-039)
    "akg_emerging_min_score": float(os.getenv("AKG_EMERGING_MIN_SCORE", "0.3")),
    "akg_emerging_min_tier": os.getenv("AKG_EMERGING_MIN_TIER", "ATMOSPHERE"),
    "akg_emerging_top_k": int(os.getenv("AKG_EMERGING_TOP_K", "50")),
    # AKG fundamentals cache (S-046): skip Alpha Vantage fetch if cached within 90 days
    "akg_fundamentals_cache_enabled": True,
    # AKG universe bootstrap (S-049): load S&P 500 + Russell 2000 as DARK nodes on first boot
    "akg_universe_bootstrap_enabled": True,  # Load S&P 500 + Russell 2000 on first boot
    # AKG cluster detection (S-050): min cluster_strength to flag a dormant sector as candidate
    "akg_cluster_strength_threshold": 0.3,
    # AKG cluster theme naming (S-050b): opt-in cheap xAI call to name detected clusters
    "akg_cluster_naming_enabled": False,
    # AKG Perplexity sonar enricher (S-051): opt-in, requires PERPLEXITY_API_KEY
    "akg_perplexity_enabled": False,              # opt-in: requires PERPLEXITY_API_KEY
    "akg_perplexity_top_k": 5,                   # max nodes to enrich per run
    "akg_perplexity_min_emergence": 0.5,         # min emergence_score to qualify
    "akg_perplexity_enricher_interval_h": 24,    # hours between enricher runs
    "akg_perplexity_ttl_days": 30,               # days before re-enriching same node
    # Position re-analysis engine (S-051): periodic score-based exit signals
    "reanalysis_min_hold_days": int(os.getenv("REANALYSIS_MIN_HOLD_DAYS", "5")),
    "reanalysis_exit_score_threshold": float(os.getenv("REANALYSIS_EXIT_SCORE_THRESHOLD", "40")),
    "reanalysis_exit_score_drop_pct": float(os.getenv("REANALYSIS_EXIT_SCORE_DROP_PCT", "0.30")),
    # Structural Force Engine (S-052): "What Must Be True" top-down force registry
    "structural_force_engine_enabled": False,    # gate: opt-in (never auto-enabled)
    "dark_matter_min_discovery_score": 0.5,      # threshold for surfacing candidates
    "dark_matter_top_k": 10,                     # max candidates per pipeline run
    # S-053: Force Acceleration Tracker — weekly xAI re-evaluation of each force
    "akg_force_tracker_enabled": False,          # opt-in: requires XAI_API_KEY
    "akg_force_tracker_interval_h": 168,         # once per week (168h)
    # S-055: Dark matter Perplexity enrichment — min discovery_score to trigger sonar
    "dark_matter_perplexity_min_score": 0.75,    # min discovery_score for enrichment
    # S-056: Real market ignorance scoring — yfinance TTL cache on AKG nodes
    "market_ignorance_cache_ttl_days": 7,        # days before refreshing yfinance data
    # V3 Index Benchmark — capital allocation hurdle (S-058/S-059)
    "v3_benchmark_enabled": os.getenv("V3_BENCHMARK_ENABLED", "true").lower() in ("1", "true", "yes"),
    "v3_benchmark_ticker": os.getenv("V3_BENCHMARK_TICKER", "QQQ"),
    "v3_trade_instrument": os.getenv("V3_TRADE_INSTRUMENT", "QQQ"),
    "v3_effective_leverage": float(os.getenv("V3_EFFECTIVE_LEVERAGE", "2.1")),  # drag-adjusted; nominal 3x, empirical ~2.1x
    "v3_benchmark_lookback_days": int(os.getenv("V3_BENCHMARK_LOOKBACK_DAYS", "252")),
    "v3_hurdle_min_score": float(os.getenv("V3_HURDLE_MIN_SCORE", "62.0")),
    # Overnight CC Tactical Overlay
    "overnight_cc_vix_drop_threshold_pct": float(os.getenv("OVERNIGHT_CC_VIX_DROP_THRESHOLD_PCT", "-5.0")),
    "overnight_cc_qqq_min_return_pct": float(os.getenv("OVERNIGHT_CC_QQQ_MIN_RETURN_PCT", "0.5")),
    "overnight_cc_p90_strike_multiplier": float(os.getenv("OVERNIGHT_CC_P90_STRIKE_MULTIPLIER", "1.00843")),
    # CC/CSP Roll Monitor (S-074)
    "cc_roll_close_early_pct": float(os.getenv("CC_ROLL_CLOSE_EARLY_PCT", "0.75")),
    "csp_roll_close_early_pct": float(os.getenv("CSP_ROLL_CLOSE_EARLY_PCT", "0.80")),
    "cc_roll_accept_assignment_mins": int(os.getenv("CC_ROLL_ACCEPT_MINS", "60")),
    "options_positions_path": os.getenv(
        "OPTIONS_POSITIONS_PATH",
        "eval_results/control/options_positions.json",
    ),
    # S-076: X Feed Discovery Scout — broad trending cashtag scanner
    "x_feed_scout_model": os.getenv("X_FEED_SCOUT_MODEL", "grok-4-1-fast-reasoning"),
    "x_feed_scout_enabled": os.getenv("X_FEED_SCOUT_ENABLED", "1") != "0",
    # Kerberos %B Vol Overlay — mechanical VXX put signal
    "portfolio_include_kerberos": os.getenv("PORTFOLIO_INCLUDE_KERBEROS", "true").lower() == "true",
    "kerberos_put_dte": int(os.getenv("KERBEROS_PUT_DTE", "14")),
    "kerberos_iv_multiplier": float(os.getenv("KERBEROS_IV_MULTIPLIER", "1.5")),
    "kerberos_risk_free_rate": float(os.getenv("KERBEROS_RISK_FREE_RATE", "0.04")),
}
