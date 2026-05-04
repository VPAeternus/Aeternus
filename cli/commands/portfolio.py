from cli.common import *  # noqa: F401,F403
from cli.common import _detect_s7_active, run_kerberos_cycle, format_kerberos_overlay_panel
from tradingagents.graph.csp_overlay import evaluate_csp_regime, CspRecommendation

@app.command("portfolio-plan")
def portfolio_plan(
    queue_date: Optional[str] = typer.Option(
        None,
        "--queue-date",
        help="Queue date (YYYY-MM-DD) used to locate batch summary.",
    ),
    summary_path: Optional[Path] = typer.Option(
        None,
        "--summary-path",
        help="Optional explicit batch summary path.",
    ),
    capital_usd: float = typer.Option(
        float(DEFAULT_CONFIG.get("portfolio_capital_usd", 100000.0)),
        "--capital-usd",
        min=1000.0,
        help="Portfolio capital used for target notional sizing.",
    ),
    max_positions: int = typer.Option(
        int(DEFAULT_CONFIG.get("portfolio_max_positions", 8)),
        "--max-positions",
        min=1,
        help="Maximum number of positions in the generated plan.",
    ),
    min_score: float = typer.Option(
        float(DEFAULT_CONFIG.get("portfolio_min_score", 55.0)),
        "--min-score",
        help="Minimum Aeternus score to include a candidate.",
    ),
    min_confidence: int = typer.Option(
        int(DEFAULT_CONFIG.get("portfolio_min_confidence", 3)),
        "--min-confidence",
        min=1,
        max=5,
        help="Minimum confidence (1-5) to include a candidate.",
    ),
    long_only: bool = typer.Option(
        True,
        "--long-only/--allow-shorts",
        help="Restrict plan to long recommendations only.",
    ),
    execution_mode: str = typer.Option(
        str(DEFAULT_CONFIG.get("execution_broker_mode", "paper")),
        "--execution-mode",
        help="Execution adapter mode used for plan quantity policy (paper, alpaca-paper, alpaca-live).",
    ),
    max_weight_per_position: float = typer.Option(
        float(DEFAULT_CONFIG.get("portfolio_max_weight_per_position", 0.25)),
        "--max-weight-per-position",
        min=0.01,
        max=1.0,
        help="Maximum weight cap per position (0.01-1.00).",
    ),
    include_hedges: bool = typer.Option(
        bool(DEFAULT_CONFIG.get("portfolio_include_hedges", True)),
        "--include-hedges/--skip-hedges",
        help="Add a deterministic hedge intent using current portfolio risk + regime context.",
    ),
    include_cc_wyckoff: bool = typer.Option(
        bool(DEFAULT_CONFIG.get("portfolio_include_cc_wyckoff", True)),
        "--include-cc-wyckoff/--skip-cc-wyckoff",
        help="Add Covered Call Wyckoff phase intents (1-day RTH shorts).",
    ),
    include_cc_scanner: bool = typer.Option(
        bool(DEFAULT_CONFIG.get("portfolio_include_cc_scanner", True)),
        "--include-cc-scanner/--skip-cc-scanner",
        help="Scan portfolio holdings for covered call timing signals.",
    ),
    include_kerberos: bool = typer.Option(
        bool(DEFAULT_CONFIG.get("portfolio_include_kerberos", True)),
        "--include-kerberos/--skip-kerberos",
        help="Include Kerberos %B VXX put overlay advisory panel.",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Build a deterministic portfolio plan from analyze-batch outcomes."""
    output_format = str(format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)

    try:
        batch_summary, resolved_summary_path = _load_batch_summary(
            queue_date=queue_date,
            summary_path=summary_path,
        )
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    execution_mode = str(execution_mode or "paper").lower().strip()
    enforce_whole_shares = bool(DEFAULT_CONFIG.get("alpaca_enforce_whole_shares", True))
    use_whole_shares = execution_mode.startswith("alpaca") and enforce_whole_shares

    plan = build_portfolio_plan(
        batch_summary=batch_summary,
        capital_usd=float(capital_usd),
        max_positions=int(max_positions),
        min_score=float(min_score),
        min_confidence=int(min_confidence),
        long_only=bool(long_only),
        max_weight_per_position=float(max_weight_per_position),
        enforce_whole_shares=use_whole_shares,
        ledger_base_dir=(
            Path("eval_results") / "deal_flow" / str(batch_summary.get("date", "")).strip()
            if str(batch_summary.get("date", "")).strip()
            else None
        ),
    )

    # ── Held Position Review ────────────────────────────────────────────────
    held_reviews = []
    try:
        from tradingagents.graph.position_review import review_positions
        positions_data = _load_json(Path(
            DEFAULT_CONFIG.get("paper_positions_path", "eval_results/paper_execution/positions.json")
        ))
        open_positions = positions_data.get("open_positions", {}) if isinstance(positions_data, dict) else {}
        if open_positions:
            akg = None
            try:
                from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
                akg = AeternusKnowledgeGraph.load()
            except Exception:
                pass
            held_reviews = review_positions(
                positions=open_positions,
                akg=akg,
                pipeline_candidates=batch_summary.get("items", []),
            )
    except Exception:
        pass
    plan["held_position_review"] = held_reviews

    hedge_context: Dict[str, Any] = {"enabled": bool(include_hedges)}
    hedge_order = None
    if include_hedges:
        try:
            portfolio_snapshot = build_portfolio_risk_snapshot(
                positions_path=str(
                    DEFAULT_CONFIG.get(
                        "paper_positions_path",
                        "eval_results/paper_execution/positions.json",
                    )
                )
            )
            market_snapshot = MarketRegimeProvider().get_market_regime_snapshot()
            hedge_engine = AdaptiveHedgeEngine()
            s7_active = _detect_s7_active()
            hedge_signal = hedge_engine.compute_hedge_signal(portfolio_snapshot, market_snapshot, s7_active=s7_active)
            hedge_decision = hedge_engine.decide_hedge(hedge_signal, portfolio_snapshot)
            hedge_order = build_hedge_order_intent(
                plan_id=str(plan.get("plan_id") or ""),
                run_date=str(plan.get("date") or ""),
                capital_usd=float(capital_usd),
                portfolio_snapshot=portfolio_snapshot,
                hedge_signal=hedge_signal,
                hedge_decision=hedge_decision,
                enforce_whole_shares=use_whole_shares,
            )
            if isinstance(hedge_order, dict):
                plan.setdefault("orders", []).append(hedge_order)
            hedge_context.update(
                {
                    "portfolio_snapshot": portfolio_snapshot,
                    "market_snapshot": market_snapshot or {},
                    "signal": hedge_signal,
                    "decision": hedge_decision,
                    "order_added": bool(hedge_order),
                }
            )
        except Exception as exc:
            hedge_context.update(
                {
                    "error": str(exc),
                    "order_added": False,
                }
            )
    plan["hedge_context"] = hedge_context
    # CC Wyckoff Phase — advisory only (no automated order intents).
    # Backtest (2026-03-02): S2 bleed rate 46.5% = coin flip, not execution-grade.
    # Signals are displayed for manual covered call timing decisions on QQQ/SPY.
    cc_wyckoff_context: Dict[str, Any] = {"enabled": bool(include_cc_wyckoff)}
    if include_cc_wyckoff:
        try:
            from tradingagents.phase_engine.cc_wyckoff_phase import CCWyckoffPhaseEngine
            pe = CCWyckoffPhaseEngine(live=execution_mode.startswith("alpaca"))
            pe_signals = pe.get_signals()
            cc_eligible_symbols = {o["symbol"] for o in plan.get("orders", []) if o.get("cc_eligible")}
            pe_signals = [s for s in pe_signals if s.get("ticker") in cc_eligible_symbols]
            cc_wyckoff_context["signals"] = len(pe_signals)
            cc_wyckoff_context["details"] = [
                {"ticker": s["ticker"], "signal": s["signal_name"], "phase": s["phase"]}
                for s in pe_signals
            ]
        except Exception as exc:
            cc_wyckoff_context["error"] = str(exc)
    plan["cc_wyckoff_context"] = cc_wyckoff_context
    # ── Covered Call Scanner (cc_overbought + wyckoff + v3 rth skip) ────────────
    cc_scanner_context: dict = {"enabled": bool(include_cc_scanner)}
    if include_cc_scanner:
        try:
            from tradingagents.phase_engine.cc_scanner import CoveredCallScanner
            scanner = CoveredCallScanner(live=execution_mode.startswith("alpaca"))
            scan_tickers = list({o["symbol"] for o in plan.get("orders", []) if o.get("symbol") and o.get("cc_eligible")})
            cc_signals = scanner.get_signals(
                tickers=scan_tickers or None,
                max_signals=int(DEFAULT_CONFIG.get("cc_scanner_max_signals", 10)),
            )
            cc_scanner_context["signals"] = len(cc_signals)
            cc_scanner_context["details"] = cc_signals
        except Exception as exc:
            cc_scanner_context["error"] = str(exc)
    plan["cc_scanner_context"] = cc_scanner_context
    # --- CSP Tactical Overlay ---
    run_date = str(plan.get("date") or "")
    csp_result = None
    overnight_cc_result = None
    try:
        csp_result = evaluate_csp_regime(as_of_date=run_date)
        plan["csp_overlay"] = {
            "recommendation": csp_result.recommendation.value,
            "qqq_price": csp_result.qqq_price,
            "sma200": csp_result.sma200,
            "below_sma200": csp_result.below_sma200,
            "vix": csp_result.vix,
            "roc_20d_pct": csp_result.roc_20d_pct,
            "vix_in_band": csp_result.vix_in_band,
            "roc_ok": csp_result.roc_ok,
            "csp_strike": csp_result.csp_strike,
            "estimated_premium_usd": csp_result.estimated_premium_usd,
            "alpha_window_days": csp_result.alpha_window_days,
            "rationale": csp_result.rationale,
            "filter_reason": csp_result.filter_reason,
        }
    except Exception as _csp_exc:
        plan["csp_overlay"] = {"recommendation": "DATA_UNAVAILABLE", "rationale": str(_csp_exc)}
        csp_result = None
    try:
        from tradingagents.graph.overnight_cc_overlay import evaluate_overnight_cc
        overnight_cc_result = evaluate_overnight_cc(
            as_of_date=run_date,
            config=DEFAULT_CONFIG,
        )
        plan["overnight_cc_overlay"] = {
            "recommendation": overnight_cc_result.recommendation.value,
            "qqq_price": overnight_cc_result.qqq_price,
            "vix_intraday_chg_pct": overnight_cc_result.vix_intraday_chg_pct,
            "qqq_day_ret_pct": overnight_cc_result.qqq_day_ret_pct,
            "suggested_strike": overnight_cc_result.suggested_strike,
            "rationale": overnight_cc_result.rationale,
        }
        if overnight_cc_result.regime_stats:
            rs = overnight_cc_result.regime_stats
            plan["overnight_cc_overlay"]["regime_stats"] = {
                "n": rs.n,
                "mean_overnight_pct": rs.mean_overnight_pct,
                "median_overnight_pct": rs.median_overnight_pct,
                "pct_positive": rs.pct_positive,
                "pct_flat_down": rs.pct_flat_down,
                "std_dev": rs.std_dev,
                "p10": rs.p10,
                "p90": rs.p90,
                "best": rs.best,
                "worst": rs.worst,
                "vix_regime_label": rs.vix_regime_label,
                "vix_regime_n": rs.vix_regime_n,
                "vix_regime_mean": rs.vix_regime_mean,
                "vix_regime_pct_flat_down": rs.vix_regime_pct_flat_down,
                "pct_below_strike": rs.pct_below_strike,
                "cc_edge_vs_signal": rs.cc_edge_vs_signal,
                "gate_profile": rs.gate_profile,
            }
    except Exception as _oncc_exc:
        plan["overnight_cc_overlay"] = {"recommendation": "DATA_UNAVAILABLE", "rationale": str(_oncc_exc)}
        overnight_cc_result = None
    # ── Kerberos %B Vol Overlay ─────────────────────────────────────────────
    kerberos_context: dict = {"enabled": bool(include_kerberos)}
    if include_kerberos:
        try:
            k_signal, k_decision, k_order = run_kerberos_cycle()
            kerberos_context.update({
                "signal": k_signal,
                "decision": k_decision,
                "order": k_order,
            })
            plan["kerberos_overlay"] = {
                "signal": k_signal,
                "decision": k_decision,
                "order": k_order,
            }
        except Exception as exc:
            kerberos_context["error"] = str(exc)
            plan["kerberos_overlay"] = {"error": str(exc)}
    plan["kerberos_context"] = kerberos_context

    if isinstance(hedge_context.get("portfolio_snapshot"), dict):
        plan["portfolio_risk_summary"] = build_portfolio_risk_summary(
            portfolio_snapshot=hedge_context.get("portfolio_snapshot", {}),
            hedge_signal=hedge_context.get("signal", {}),
            hedge_decision=hedge_context.get("decision", {}),
            market_snapshot=hedge_context.get("market_snapshot", {}),
        )
    else:
        plan["portfolio_risk_summary"] = {}
    plan["quantity_policy"] = "WHOLE_SHARES" if use_whole_shares else "FRACTIONAL_OK"
    plan["execution_mode"] = execution_mode
    plan["source_summary_path"] = str(resolved_summary_path)
    plan_path = _persist_portfolio_plan(plan)
    plan["plan_path"] = str(plan_path)

    try:
        RatingAuditLog().log_event(
            "PORTFOLIO_PLAN_CREATED",
            str(plan.get("plan_id") or plan.get("source_run_id") or "portfolio-plan"),
            {
                "plan_path": str(plan_path),
                "source_summary_path": str(resolved_summary_path),
                "orders": len(plan.get("orders", [])),
                "capital_usd": float(capital_usd),
                "max_positions": int(max_positions),
                "execution_mode": execution_mode,
                "hedges_enabled": bool(include_hedges),
                "hedge_order_added": bool(hedge_order),
            },
        )
        if isinstance(hedge_order, dict):
            audit_payload = {
                "plan_id": str(plan.get("plan_id") or ""),
                "plan_path": str(plan_path),
                "symbol": str(hedge_order.get("symbol") or ""),
                "side": str(hedge_order.get("side") or ""),
                "target_notional_usd": float(hedge_order.get("target_notional_usd", 0.0) or 0.0),
                "hedge_target_pct": float(hedge_order.get("hedge_target_pct", 0.0) or 0.0),
                "hedge_delta_pct": float(hedge_order.get("hedge_delta_pct", 0.0) or 0.0),
                "hedge_market_regime": str(hedge_order.get("hedge_market_regime") or "UNKNOWN"),
            }
            RatingAuditLog().log_event(
                "HEDGE_INTENT_CREATED",
                str(hedge_order.get("order_intent_id") or plan.get("plan_id") or "hedge-intent"),
                audit_payload,
            )
    except Exception:
        pass
    if include_cc_wyckoff and int(cc_wyckoff_context.get("signals", 0) or 0) > 0:
        try:
            RatingAuditLog().log_event(
                "CC_WYCKOFF_SIGNALS",
                str(plan.get("plan_id") or "cc-wyckoff"),
                {
                    "plan_id": str(plan.get("plan_id") or ""),
                    "plan_path": str(plan_path),
                    "signals": int(cc_wyckoff_context.get("signals", 0)),
                },
            )
        except Exception:
            pass
    if cc_scanner_context.get("signals", 0) > 0:
        try:
            RatingAuditLog().log_event(
                "CC_SCANNER_SIGNALS",
                str(plan.get("plan_id") or "cc-scanner"),
                {
                    "signals": cc_scanner_context.get("signals", 0),
                    "plan_id": plan.get("plan_id"),
                },
            )
        except Exception:
            pass

    if output_format == "json":
        print(json_lib.dumps(plan, indent=2))
        return

    # ── GEX regime staleness warning ────────────────────────────────────
    try:
        gex_state = _load_json(Path("eval_results/control/gex_regime_state.json"))
        if isinstance(gex_state, dict):
            gex_updated = gex_state.get("gex_updated_at", "") or gex_state.get("data_freshness", "")
            if gex_updated:
                from datetime import datetime
                gex_dt = datetime.strptime(gex_updated[:10], "%Y-%m-%d")
                gex_age = (datetime.now() - gex_dt).days
                if gex_age > 1:
                    console.print(
                        "[bold red]GEX DATA STALE[/bold red] — run: "
                        "[cyan]aeternus x-feed --generate --pass 15[/cyan]"
                    )
            else:
                console.print(
                    "[bold red]GEX DATA MISSING[/bold red] — run: "
                    "[cyan]aeternus x-feed --generate --pass 15[/cyan]"
                )
        else:
            console.print(
                "[bold red]GEX DATA MISSING[/bold red] — run: "
                "[cyan]aeternus x-feed --generate --pass 15[/cyan]"
            )
    except Exception:
        console.print(
            "[bold red]GEX DATA MISSING[/bold red] — run: "
            "[cyan]aeternus x-feed --generate --pass 15[/cyan]"
        )

    console.print(
        f"[green]Portfolio plan created[/green] | plan_id={plan.get('plan_id')} | "
        f"orders={len(plan.get('orders', []))}"
    )
    if include_hedges:
        decision = plan.get("hedge_context", {}).get("decision", {})
        if isinstance(decision, dict):
            console.print(
                "[cyan]Hedge context:[/cyan] "
                f"status={decision.get('status', 'UNKNOWN')} | "
                f"action={decision.get('action', 'NO_CHANGE')} | "
                f"instrument={decision.get('instrument', 'N/A')}"
            )
    pe_ctx = plan.get("cc_wyckoff_context", {})
    if isinstance(pe_ctx, dict) and pe_ctx.get("enabled"):
        if pe_ctx.get("error"):
            console.print(f"[yellow]CC Wyckoff phase:[/yellow] error={pe_ctx['error']}")
        else:
            console.print(
                f"[cyan]CC Wyckoff phase (advisory):[/cyan] "
                f"signals={pe_ctx.get('signals', 0)}"
            )
    cc_ctx = plan.get("cc_scanner_context", {})
    if cc_ctx.get("signals"):
        console.print(f"[cyan]CC Scanner:[/cyan] {cc_ctx['signals']} covered call signals")
    elif cc_ctx.get("error"):
        console.print(f"[red]CC Scanner: ERROR — {cc_ctx['error']}[/red]")
    kerb_ctx_info = plan.get("kerberos_context", {})
    if kerb_ctx_info.get("enabled"):
        k_dec_info = kerb_ctx_info.get("decision", {})
        if kerb_ctx_info.get("error"):
            console.print(f"[red]Kerberos overlay: ERROR — {kerb_ctx_info['error']}[/red]")
        else:
            console.print(
                f"[cyan]Kerberos overlay:[/cyan] "
                f"action={k_dec_info.get('action', 'NO_SIGNAL')} | "
                f"status={k_dec_info.get('status', 'UNKNOWN')}"
            )
    console.print(f"[cyan]Plan path:[/cyan] {plan_path}")
    hedge_context_for_render = plan.get("hedge_context", {})
    if include_hedges and isinstance(hedge_context_for_render, dict):
        portfolio_snapshot = (
            hedge_context_for_render.get("portfolio_snapshot", {})
            if isinstance(hedge_context_for_render.get("portfolio_snapshot", {}), dict)
            else {}
        )
        market_snapshot = (
            hedge_context_for_render.get("market_snapshot", {})
            if isinstance(hedge_context_for_render.get("market_snapshot", {}), dict)
            else {}
        )
        hedge_signal = (
            hedge_context_for_render.get("signal", {})
            if isinstance(hedge_context_for_render.get("signal", {}), dict)
            else {}
        )
        hedge_decision = (
            hedge_context_for_render.get("decision", {})
            if isinstance(hedge_context_for_render.get("decision", {}), dict)
            else {}
        )
        if portfolio_snapshot or hedge_decision:
            console.print(
                Panel(
                    Markdown(
                        format_portfolio_risk_hedge_markdown(
                            portfolio_snapshot=portfolio_snapshot,
                            market_regime=market_snapshot,
                            hedge_signal=hedge_signal,
                            hedge_decision=hedge_decision,
                        )
                    ),
                    title="Portfolio Risk & Hedge Recommendation",
                    border_style="yellow",
                    padding=(1, 2),
                )
            )
    if DEFAULT_CONFIG.get("v3_benchmark_enabled", True):
        try:
            from tradingagents.phase_engine.index_overlay import v3_benchmark_stats
            v3_stats = v3_benchmark_stats(
                ticker=str(DEFAULT_CONFIG.get("v3_benchmark_ticker", "QQQ")),
                lookback_days=int(DEFAULT_CONFIG.get("v3_benchmark_lookback_days", 252)),
            )
            _render_v3_benchmark_panel(v3_stats)
        except Exception:
            pass

    _render_portfolio_plan_table(plan)

    # ── Held Position Review panel ───────────────────────────────────────────
    if held_reviews:
        hr_table = Table(title="Held Position Review", show_header=True, header_style="bold cyan")
        hr_table.add_column("Symbol", style="green")
        hr_table.add_column("Entry", justify="right")
        hr_table.add_column("Current", justify="right")
        hr_table.add_column("Δ%", justify="right")
        hr_table.add_column("PnL%", justify="right")
        hr_table.add_column("AnnRet%", justify="right")
        hr_table.add_column("AnnVol%", justify="right")
        hr_table.add_column("MaxDD%", justify="right")
        hr_table.add_column("Hold", justify="right")
        hr_table.add_column("Stress", style="cyan")
        hr_table.add_column("Action", style="bold")
        hr_table.add_column("Reason")
        action_colors = {"EXIT": "red", "WATCH": "yellow", "ROTATE": "magenta", "HOLD": "green"}
        for r in held_reviews:
            entry = r["entry_score"]
            current = r["current_score"]
            score_delta_pct = ((current - entry) / entry * 100) if entry > 0 else 0
            color = action_colors.get(r["recommendation"], "white")
            pnl = r["pnl_pct"]
            ann_ret = r.get("ann_return_pct", 0.0)
            ann_vol = r.get("ann_vol_pct", 0.0)
            max_dd = r.get("max_dd_pct", 0.0)
            hr_table.add_row(
                r["symbol"],
                f"{entry:.0f}",
                f"{current:.0f}",
                f"{score_delta_pct:+.0f}%",
                f"{'[green]' if pnl >= 0 else '[red]'}{pnl:+.1f}%{'[/green]' if pnl >= 0 else '[/red]'}",
                f"{'[green]' if ann_ret >= 0 else '[red]'}{ann_ret:+.0f}%{'[/green]' if ann_ret >= 0 else '[/red]'}",
                f"{ann_vol:.0f}%",
                f"[red]{max_dd:.1f}%[/red]" if max_dd < 0 else f"{max_dd:.1f}%",
                f"{r['hold_days']}d",
                r["thesis_stress"],
                f"[{color}]{r['recommendation']}[/{color}]",
                r["reason"],
            )
        console.print(hr_table)

    # ── Covered Call Opportunities panel ─────────────────────────────────────
    cc_details = plan.get("cc_scanner_context", {}).get("details", [])
    if cc_details:
        _render_cc_scanner_panel(cc_details)

    # ── CSP Tactical Overlay panel ────────────────────────────────────────────
    if csp_result is not None:
        from cli.common import format_csp_overlay_panel
        format_csp_overlay_panel(csp_result)

    # ── Overnight CC Tactical Overlay panel ───────────────────────────────────
    if overnight_cc_result is not None:
        from cli.common import format_overnight_cc_panel
        format_overnight_cc_panel(overnight_cc_result)

    # ── Kerberos %B Vol Overlay panel ──────────────────────────────────────
    kerb_ctx = plan.get("kerberos_context", {})
    if kerb_ctx.get("enabled") and not kerb_ctx.get("error"):
        k_sig = kerb_ctx.get("signal", {})
        k_dec = kerb_ctx.get("decision", {})
        state_path = Path("eval_results/kerberos_state.json")
        k_state = _read_json(state_path) if state_path.exists() else {}
        if not isinstance(k_state, dict):
            k_state = {}
        format_kerberos_overlay_panel(k_sig, k_dec, state=k_state)
    elif kerb_ctx.get("error"):
        console.print(f"[red]Kerberos overlay: {kerb_ctx['error']}[/red]")

