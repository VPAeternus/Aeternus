from cli.common import *  # noqa: F401,F403

from tradingagents.dealflow.fma_recall import FMA_EVENT_SCORE_THRESHOLD, _build_fma_feature_frame, score_fma_cross_section
from tradingagents.dealflow.fma_recall import resolve_fma_artifact_dir, run_fma_backtest
from tradingagents.dealflow.fvg_recall import _build_feature_frame
from tradingagents.dealflow.fvg_recall import resolve_fvg_artifact_dir, run_fvg_backtest
from tradingagents.dealflow.pipeline import _coerce_liquidity_score


recall_app = typer.Typer(name="recall", help="Inspect standalone discovery recall channels.")
app.add_typer(recall_app, name="recall")


def _validate_output_format(raw_format: str) -> str:
    output_format = str(raw_format or "table").lower().strip()
    if output_format not in {"table", "json"}:
        console.print("[red]Error: format must be table or json[/red]")
        raise typer.Exit(1)
    return output_format


def _format_recall_value(value: object) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value is None:
        return "None"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _render_recall_summary(
    *,
    title: str,
    explanation: str,
    artifact: Dict[str, Any],
    selected_symbols: List[str],
) -> None:
    rule_snapshot = dict(artifact.get("rule_snapshot", {}) or {})
    summary = Table(title=title)
    summary.add_column("Field", style="cyan")
    summary.add_column("Value", style="green")
    summary.add_row("Date", str(artifact.get("date", "")))
    summary.add_row("Explanation", explanation)
    summary.add_row("Enabled", _format_recall_value(rule_snapshot.get("enabled")))
    summary.add_row("Quota", _format_recall_value(artifact.get("quota")))
    summary.add_row("Selected Count", str(len(selected_symbols)))
    summary.add_row("Selected Symbols", ", ".join(selected_symbols) if selected_symbols else "None")
    rule_items = [
        f"{key}={_format_recall_value(value)}"
        for key, value in rule_snapshot.items()
        if key != "enabled"
    ]
    summary.add_row("Rules", ", ".join(rule_items) if rule_items else "None")
    console.print(summary)


def _render_recall_rows(title: str, rows: List[Dict[str, Any]], columns: List[tuple[str, str]]) -> None:
    table = Table(title=title)
    for label, _key in columns:
        justify = "right" if _key != "symbol" else "left"
        style = "cyan" if _key == "symbol" else "green"
        table.add_column(label, style=style, justify=justify)

    for row in rows:
        table.add_row(*[_format_recall_value(row.get(key)) for _label, key in columns])

    console.print(table)


def _explanation_from_checks(*, selected: bool, passed_text: str, failed_text: str) -> str:
    return passed_text if selected else failed_text


def _render_single_symbol_payload(title: str, payload: Dict[str, Any]) -> None:
    metrics = dict(payload.get("metrics", {}) or {})
    thresholds = dict(payload.get("thresholds", {}) or {})
    checks = list(payload.get("checks", []) or [])

    summary = Table(title=title)
    summary.add_column("Field", style="cyan")
    summary.add_column("Value", style="green")
    summary.add_row("Symbol", str(payload.get("symbol", "")))
    summary.add_row("As Of", str(payload.get("as_of_date", "")))
    summary.add_row("Selected", "yes" if bool(payload.get("selected")) else "no")
    for key, value in metrics.items():
        summary.add_row(str(key), _format_recall_value(value))
    for key, value in thresholds.items():
        summary.add_row(f"threshold:{key}", _format_recall_value(value if not isinstance(value, list) else ", ".join(str(v) for v in value)))
    console.print(summary)
    explanation = str(payload.get("explanation", "") or "").strip()
    if explanation:
        console.print(f"[bold cyan]Explanation:[/bold cyan] {explanation}")

    if checks:
        table = Table(title="Pass / Fail Checks")
        table.add_column("Check", style="cyan")
        table.add_column("Passed", style="green")
        table.add_column("Observed", style="white")
        table.add_column("Threshold", style="yellow")
        for check in checks:
            table.add_row(
                str(check.get("name", "")),
                "yes" if bool(check.get("passed")) else "no",
                _format_recall_value(check.get("observed")),
                _format_recall_value(check.get("threshold")),
            )
        console.print(table)


def _load_json(path: Path) -> Dict[str, Any]:
    return json_lib.loads(path.read_text(encoding="utf-8"))


def _pct_text(value: object) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{100.0 * float(value):.2f}%"
    except (TypeError, ValueError):
        return str(value)


def _build_recall_performance_payload(
    *,
    as_of_date: str,
    universe: str,
    benchmark: str,
    refresh: bool,
) -> Dict[str, Any]:
    normalized_universe = str(universe or "semis-ai-narrow").strip()
    benchmark_symbol = str(benchmark or "SMH").upper().strip()
    fvg_dir = resolve_fvg_artifact_dir(
        artifact_dir=None,
        run_date=as_of_date,
        universe_name=normalized_universe,
        benchmark=benchmark_symbol,
    )
    fma_dir = resolve_fma_artifact_dir(
        artifact_dir=None,
        run_date=as_of_date,
        universe_name=normalized_universe,
        benchmark=benchmark_symbol,
    )
    fvg_summary_path = fvg_dir / "summary.json"
    fma_summary_path = fma_dir / "summary.json"

    if refresh or not fvg_summary_path.exists():
        fvg_summary = run_fvg_backtest(
            universe_name=normalized_universe,
            benchmark=benchmark_symbol,
            artifact_dir=fvg_dir,
        )
        fvg_source = "refresh"
    else:
        fvg_summary = _load_json(fvg_summary_path)
        fvg_source = "artifact"

    if refresh or not fma_summary_path.exists():
        fma_summary = run_fma_backtest(
            universe_name=normalized_universe,
            benchmark=benchmark_symbol,
            artifact_dir=fma_dir,
        )
        fma_source = "refresh"
    else:
        fma_summary = _load_json(fma_summary_path)
        fma_source = "artifact"

    fvg_event = dict(fvg_summary.get("event_summary", {}) or {})
    fvg_basket = dict(fvg_summary.get("basket_summary", {}) or {})
    fma_live = dict((dict(fma_summary.get("variant_summaries", {}) or {}).get("fma_live", {}) or {}))
    fma_event = dict(fma_live.get("event_summary", {}) or {})
    fma_basket = dict(fma_live.get("basket_summary", {}) or {})

    comparison_parts: list[str] = []
    fvg_edge_20 = fvg_basket.get("avg_edge_vs_benchmark_20d")
    fma_edge_20 = fma_basket.get("avg_edge_vs_benchmark_20d")
    if fvg_edge_20 is not None and fma_edge_20 is not None:
        if float(fma_edge_20) > float(fvg_edge_20):
            comparison_parts.append("FMA leads on 20d edge")
        elif float(fvg_edge_20) > float(fma_edge_20):
            comparison_parts.append("FVG leads on 20d edge")
    fvg_edge_60 = fvg_basket.get("avg_edge_vs_benchmark_60d")
    fma_edge_60 = fma_basket.get("avg_edge_vs_benchmark_60d")
    if fvg_edge_60 is not None and fma_edge_60 is not None:
        if float(fvg_edge_60) > float(fma_edge_60):
            comparison_parts.append("FVG leads on 60d follow-through")
        elif float(fma_edge_60) > float(fvg_edge_60):
            comparison_parts.append("FMA leads on 60d follow-through")

    return {
        "as_of_date": as_of_date,
        "universe": normalized_universe,
        "benchmark": benchmark_symbol,
        "methodology": {
            "study_type": "historical_signal_study",
            "data_source": "Yahoo Finance daily OHLCV",
            "note": "Signal study, not execution-adjusted PnL.",
        },
        "fvg": {
            "source": fvg_source,
            "artifact_dir": str(fvg_dir),
            "event_summary": fvg_event,
            "basket_summary": fvg_basket,
            "top_tickers": list(fvg_summary.get("top_tickers", []) or []),
        },
        "fma": {
            "source": fma_source,
            "artifact_dir": str(fma_dir),
            "variant_summaries": dict(fma_summary.get("variant_summaries", {}) or {}),
            "overlap_summary": dict(fma_summary.get("overlap_summary", {}) or {}),
            "union_summary": dict(fma_summary.get("union_summary", {}) or {}),
        },
        "comparison": {
            "summary": "; ".join(comparison_parts) if comparison_parts else "Comparison available after both studies are loaded.",
        },
    }


def _render_recall_performance_payload(payload: Dict[str, Any]) -> None:
    methodology = dict(payload.get("methodology", {}) or {})
    fvg = dict(payload.get("fvg", {}) or {})
    fma = dict(payload.get("fma", {}) or {})
    fvg_event = dict(fvg.get("event_summary", {}) or {})
    fvg_basket = dict(fvg.get("basket_summary", {}) or {})
    fma_live = dict((dict(fma.get("variant_summaries", {}) or {}).get("fma_live", {}) or {}))
    fma_event = dict(fma_live.get("event_summary", {}) or {})
    fma_basket = dict(fma_live.get("basket_summary", {}) or {})

    summary = Table(title="Recall Performance")
    summary.add_column("Field", style="cyan")
    summary.add_column("Value", style="green")
    summary.add_row("As Of", str(payload.get("as_of_date", "")))
    summary.add_row("Universe", str(payload.get("universe", "")))
    summary.add_row("Benchmark", str(payload.get("benchmark", "")))
    summary.add_row("Study Type", str(methodology.get("study_type", "")))
    summary.add_row("Data Source", str(methodology.get("data_source", "")))
    console.print(summary)
    note = str(methodology.get("note", "") or "").strip()
    if note:
        console.print(f"[bold cyan]Methodology Note:[/bold cyan] {note}")

    scorecard = Table(title="Signal Scorecard")
    scorecard.add_column("System", style="cyan")
    scorecard.add_column("Events", style="white")
    scorecard.add_column("20d Return", style="white")
    scorecard.add_column("60d Return", style="white")
    scorecard.add_column("20d Edge", style="white")
    scorecard.add_column("60d Edge", style="white")
    scorecard.add_row(
        "FVG",
        str(fvg_event.get("event_count", 0)),
        _pct_text(fvg_event.get("mean_forward_return_20d")),
        _pct_text(fvg_event.get("mean_forward_return_60d")),
        _pct_text(fvg_basket.get("avg_edge_vs_benchmark_20d")),
        _pct_text(fvg_basket.get("avg_edge_vs_benchmark_60d")),
    )
    scorecard.add_row(
        "FMA",
        str(fma_event.get("event_count", 0)),
        _pct_text(fma_event.get("mean_forward_return_20d")),
        _pct_text(fma_event.get("mean_forward_return_60d")),
        _pct_text(fma_basket.get("avg_edge_vs_benchmark_20d")),
        _pct_text(fma_basket.get("avg_edge_vs_benchmark_60d")),
    )
    console.print(scorecard)

    top_tickers = list(fvg.get("top_tickers", []) or [])
    if top_tickers:
        table = Table(title="Top FVG Names")
        table.add_column("Ticker", style="cyan")
        table.add_column("Events", style="white")
        for row in top_tickers[:5]:
            table.add_row(str(row.get("ticker", "")), str(row.get("event_count", 0)))
        console.print(table)

    overlap_summary = dict(fma.get("overlap_summary", {}) or {})
    if overlap_summary:
        table = Table(title="FMA Overlap")
        table.add_column("Bucket", style="cyan")
        table.add_column("Events", style="white")
        table.add_column("20d", style="white")
        table.add_column("60d", style="white")
        for bucket, stats in overlap_summary.items():
            table.add_row(
                str(bucket),
                str((stats or {}).get("event_count", 0)),
                _pct_text((stats or {}).get("mean_forward_return_20d")),
                _pct_text((stats or {}).get("mean_forward_return_60d")),
            )
        console.print(table)

    comparison = dict(payload.get("comparison", {}) or {})
    summary_text = str(comparison.get("summary", "") or "").strip()
    if summary_text:
        console.print(f"[bold cyan]Investor Summary:[/bold cyan] {summary_text}")


def _build_multi_universe_recall_performance_payload(
    *,
    as_of_date: str,
    refresh: bool,
) -> Dict[str, Any]:
    universe_specs = [
        ("semis_ai", "SMH"),
        ("qqq_top20", "QQQ"),
        ("spy_top20", "SPY"),
    ]
    rows = [
        _build_recall_performance_payload(
            as_of_date=as_of_date,
            universe=universe,
            benchmark=benchmark,
            refresh=refresh,
        )
        for universe, benchmark in universe_specs
    ]
    return {
        "as_of_date": as_of_date,
        "universes": rows,
    }


def _render_multi_universe_recall_performance_payload(payload: Dict[str, Any]) -> None:
    table = Table(title="Multi-Universe Recall Performance")
    table.add_column("Universe", style="cyan")
    table.add_column("Benchmark", style="white")
    table.add_column("System", style="white")
    table.add_column("Events", style="white")
    table.add_column("20d Edge", style="white")
    table.add_column("60d Edge", style="white")

    for row in list(payload.get("universes", []) or []):
        universe = str(row.get("universe", ""))
        benchmark = str(row.get("benchmark", ""))
        fvg = dict(row.get("fvg", {}) or {})
        fvg_event = dict(fvg.get("event_summary", {}) or {})
        fvg_basket = dict(fvg.get("basket_summary", {}) or {})
        fma = dict(row.get("fma", {}) or {})
        fma_live = dict((dict(fma.get("variant_summaries", {}) or {}).get("fma_live", {}) or {}))
        fma_event = dict(fma_live.get("event_summary", {}) or {})
        fma_basket = dict(fma_live.get("basket_summary", {}) or {})

        table.add_row(
            universe,
            benchmark,
            "FVG",
            str(fvg_event.get("event_count", 0)),
            _pct_text(fvg_basket.get("avg_edge_vs_benchmark_20d")),
            _pct_text(fvg_basket.get("avg_edge_vs_benchmark_60d")),
        )
        table.add_row(
            universe,
            benchmark,
            "FMA",
            str(fma_event.get("event_count", 0)),
            _pct_text(fma_basket.get("avg_edge_vs_benchmark_20d")),
            _pct_text(fma_basket.get("avg_edge_vs_benchmark_60d")),
        )

    console.print(table)


def _load_recall_market_data(*, symbol: str, as_of_date: str) -> Dict[str, Any]:
    pipeline = DealFlowPipeline(config=DEFAULT_CONFIG.copy())
    candidate_symbols: list[str] = [symbol]
    akg = None
    min_liquidity_score = float(DEFAULT_CONFIG.get("dealflow_fvg_recall_min_liquidity_score", 30.0))
    try:
        from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph

        akg = AeternusKnowledgeGraph.load()
        candidate_symbols = []
        for node in akg._nodes.values():
            if node.get("node_type") != "company":
                continue
            candidate = pipeline._normalize_symbol(node.get("id", ""))  # pylint: disable=protected-access
            if not candidate:
                continue
            asset_class = str(node.get("asset_class") or "Equity")
            liquidity_score = _coerce_liquidity_score(node.get("liquidity_score"))
            if asset_class != "Equity" or liquidity_score is None or liquidity_score < min_liquidity_score:
                continue
            candidate_symbols.append(candidate)
    except Exception:
        akg = None

    if symbol not in candidate_symbols:
        candidate_symbols.append(symbol)
    market_data = pipeline._prepare_recall_market_data(  # pylint: disable=protected-access
        akg=akg,
        candidate_symbols=sorted(dict.fromkeys(candidate_symbols)),
        as_of_date=as_of_date,
    )
    return market_data


def _build_fvg_single_symbol_payload(*, symbol: str, as_of_date: str) -> Dict[str, Any]:
    normalized_symbol = str(symbol or "").upper().strip().replace(".", "-")
    min_rs20 = float(DEFAULT_CONFIG.get("dealflow_fvg_recall_min_rs20", 0.03))
    min_liquidity_score = float(DEFAULT_CONFIG.get("dealflow_fvg_recall_min_liquidity_score", 30.0))
    required_confirmation = [
        "bullish_fvg_present",
        "relative_strength_20d",
        "sma50_above_sma200",
    ]

    market_data = _load_recall_market_data(symbol=normalized_symbol, as_of_date=as_of_date)
    frame = dict(market_data.get("symbol_frames", {}) or {}).get(normalized_symbol)
    benchmark_frame = market_data.get("benchmark_frame")
    if frame is None or frame.empty or benchmark_frame is None or benchmark_frame.empty:
        return {
            "mode": "single_symbol",
            "channel": "fvg",
            "symbol": normalized_symbol,
            "as_of_date": as_of_date,
            "selected": False,
            "explanation": "No market history was available to evaluate this symbol for FVG recall.",
            "metrics": {},
            "thresholds": {
                "min_rs20": min_rs20,
                "min_liquidity_score": min_liquidity_score,
                "required_confirmation": required_confirmation,
            },
            "checks": [],
        }

    features = _build_feature_frame(frame, benchmark_frame=benchmark_frame, atr_floor=0.25)
    if features.empty:
        return {
            "mode": "single_symbol",
            "channel": "fvg",
            "symbol": normalized_symbol,
            "as_of_date": as_of_date,
            "selected": False,
            "explanation": "No valid feature frame was available for this symbol.",
            "metrics": {},
            "thresholds": {
                "min_rs20": min_rs20,
                "min_liquidity_score": min_liquidity_score,
                "required_confirmation": required_confirmation,
            },
            "checks": [],
        }

    row = features.iloc[-1]
    score = float(row.get("score", 0.0) or 0.0)
    bullish_fvg_present = bool(row.get("bullish_fvg_present", False))
    rs20 = float(row.get("relative_strength_20d", 0.0) or 0.0)
    sma50_above_sma200 = bool(row.get("sma50_above_sma200", False))
    selected = bullish_fvg_present and rs20 >= min_rs20 and sma50_above_sma200
    checks = [
        {"name": "bullish_fvg_present", "passed": bullish_fvg_present, "observed": bullish_fvg_present, "threshold": True},
        {"name": "relative_strength_20d", "passed": rs20 >= min_rs20, "observed": rs20, "threshold": min_rs20},
        {"name": "sma50_above_sma200", "passed": sma50_above_sma200, "observed": sma50_above_sma200, "threshold": True},
    ]
    explanation = _explanation_from_checks(
        selected=selected,
        passed_text="Selected because bullish FVG is present, RS20 exceeds threshold, and SMA50 is above SMA200.",
        failed_text="Not selected because one or more FVG confirmation checks failed.",
    )
    return {
        "mode": "single_symbol",
        "channel": "fvg",
        "symbol": normalized_symbol,
        "as_of_date": as_of_date,
        "selected": selected,
        "explanation": explanation,
        "metrics": {
            "score": score,
            "bullish_fvg_present": bullish_fvg_present,
            "relative_strength_20d": rs20,
            "sma50_above_sma200": sma50_above_sma200,
            "trend_alignment_20_50_200": float(row.get("trend_alignment_20_50_200", 0.0) or 0.0),
            "volume_zscore_20d": float(row.get("volume_zscore_20d", 0.0) or 0.0),
        },
        "thresholds": {
            "min_rs20": min_rs20,
            "min_liquidity_score": min_liquidity_score,
            "required_confirmation": required_confirmation,
        },
        "checks": checks,
    }


def _build_fma_single_symbol_payload(*, symbol: str, as_of_date: str) -> Dict[str, Any]:
    normalized_symbol = str(symbol or "").upper().strip().replace(".", "-")
    min_score = float(DEFAULT_CONFIG.get("dealflow_fma_recall_min_score", 60.0))
    min_liquidity_score = float(DEFAULT_CONFIG.get("dealflow_fvg_recall_min_liquidity_score", 30.0))
    required_confirmation = ["fma_live_score"]

    market_data = _load_recall_market_data(symbol=normalized_symbol, as_of_date=as_of_date)
    frame = dict(market_data.get("symbol_frames", {}) or {}).get(normalized_symbol)
    benchmark_frame = market_data.get("benchmark_frame")
    if frame is None or frame.empty or benchmark_frame is None or benchmark_frame.empty:
        return {
            "mode": "single_symbol",
            "channel": "fma",
            "symbol": normalized_symbol,
            "as_of_date": as_of_date,
            "selected": False,
            "explanation": "No market history was available to evaluate this symbol for FMA recall.",
            "metrics": {},
            "thresholds": {
                "min_score": min_score,
                "min_liquidity_score": min_liquidity_score,
                "required_confirmation": required_confirmation,
            },
            "checks": [],
        }

    features = _build_fma_feature_frame(frame, benchmark_frame=benchmark_frame, variant="fma_live")
    if features.empty:
        return {
            "mode": "single_symbol",
            "channel": "fma",
            "symbol": normalized_symbol,
            "as_of_date": as_of_date,
            "selected": False,
            "explanation": "No valid FMA feature frame was available for this symbol.",
            "metrics": {},
            "thresholds": {
                "min_score": min_score,
                "min_liquidity_score": min_liquidity_score,
                "required_confirmation": required_confirmation,
            },
            "checks": [],
        }

    row = features.iloc[-1]
    snapshots = []
    for candidate, candidate_frame in dict(market_data.get("symbol_frames", {}) or {}).items():
        candidate_features = _build_fma_feature_frame(candidate_frame, benchmark_frame=benchmark_frame, variant="fma_live")
        if candidate_features.empty:
            continue
        candidate_row = candidate_features.iloc[-1]
        snapshots.append(
            {
                "ticker": candidate,
                "variant": "fma_live",
                "valid": bool(candidate_row.get("valid", False)),
                "velocity_60d": float(candidate_row.get("velocity_60d", 0.0) or 0.0),
                "accel_value": float(candidate_row.get("accel_value", 0.0) or 0.0),
                "mass_ratio": float(candidate_row.get("mass_ratio", 0.0) or 0.0),
                "force_value": float(candidate_row.get("force_value", 0.0) or 0.0),
                "relative_strength_60d": float(candidate_row.get("relative_strength_60d", 0.0) or 0.0),
            }
        )
    scores = score_fma_cross_section(snapshots, variant="fma_live")
    score = float(scores.get(normalized_symbol, 0.0) or 0.0)
    selected = score >= FMA_EVENT_SCORE_THRESHOLD and bool(row.get("valid", False))
    checks = [
        {"name": "fma_live_score", "passed": score >= min_score, "observed": score, "threshold": min_score},
    ]
    explanation = _explanation_from_checks(
        selected=selected,
        passed_text="Selected because the live FMA score meets the minimum threshold.",
        failed_text="Not selected because FMA score is below the live minimum threshold.",
    )
    return {
        "mode": "single_symbol",
        "channel": "fma",
        "symbol": normalized_symbol,
        "as_of_date": as_of_date,
        "selected": selected,
        "explanation": explanation,
        "metrics": {
            "score": score,
            "velocity_60d": float(row.get("velocity_60d", 0.0) or 0.0),
            "accel_value": float(row.get("accel_value", 0.0) or 0.0),
            "mass_ratio": float(row.get("mass_ratio", 0.0) or 0.0),
            "force_value": float(row.get("force_value", 0.0) or 0.0),
            "relative_strength_60d": float(row.get("relative_strength_60d", 0.0) or 0.0),
        },
        "thresholds": {
            "min_score": min_score,
            "min_liquidity_score": min_liquidity_score,
            "required_confirmation": required_confirmation,
        },
        "checks": checks,
    }


@recall_app.command("fvg")
def recall_fvg(
    symbol: Optional[str] = typer.Argument(None, help="Optional ticker symbol to explain individually."),
    date: Optional[str] = typer.Option(None, help="As-of date (YYYY-MM-DD), defaults to today"),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Inspect the Fair Value Gap recall channel outside the pipeline."""
    run_date = date or _today_str()
    output_format = _validate_output_format(format)

    if symbol:
        payload = _build_fvg_single_symbol_payload(symbol=symbol, as_of_date=run_date)
        if output_format == "json":
            typer.echo(json_lib.dumps(payload, indent=2, default=str))
            return
        _render_single_symbol_payload("Single-Symbol FVG Recall", payload)
        return

    pipeline = DealFlowPipeline(config=DEFAULT_CONFIG.copy())
    payload = pipeline._build_fvg_recall_channel(as_of_date=run_date)  # pylint: disable=protected-access

    if output_format == "json":
        typer.echo(json_lib.dumps(payload, indent=2, default=str))
        return

    artifact = dict(payload.get("artifact", {}) or {})
    selected_symbols = list(payload.get("selected_symbols", []) or [])
    _render_recall_summary(
        title="Fair Value Gap Recall",
        explanation="Bullish FVG recall scans liquid equities for active bullish fair value gaps with trend confirmation.",
        artifact=artifact,
        selected_symbols=selected_symbols,
    )
    _render_recall_rows(
        "Selected FVG Rows",
        list(artifact.get("rows", []) or []),
        [
            ("Symbol", "symbol"),
            ("Score", "score"),
            ("RS20", "relative_strength_20d"),
            ("SMA50>SMA200", "sma50_above_sma200"),
            ("Bullish FVG", "bullish_fvg_present"),
        ],
    )


@recall_app.command("fma")
def recall_fma(
    symbol: Optional[str] = typer.Argument(None, help="Optional ticker symbol to explain individually."),
    date: Optional[str] = typer.Option(None, help="As-of date (YYYY-MM-DD), defaults to today"),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Inspect the FMA recall channel outside the pipeline."""
    run_date = date or _today_str()
    output_format = _validate_output_format(format)

    if symbol:
        payload = _build_fma_single_symbol_payload(symbol=symbol, as_of_date=run_date)
        if output_format == "json":
            typer.echo(json_lib.dumps(payload, indent=2, default=str))
            return
        _render_single_symbol_payload("Single-Symbol FMA Recall", payload)
        return

    pipeline = DealFlowPipeline(config=DEFAULT_CONFIG.copy())
    payload = pipeline._build_fma_recall_channel(as_of_date=run_date)  # pylint: disable=protected-access

    if output_format == "json":
        typer.echo(json_lib.dumps(payload, indent=2, default=str))
        return

    artifact = dict(payload.get("artifact", {}) or {})
    selected_symbols = list(payload.get("selected_symbols", []) or [])
    _render_recall_summary(
        title="FMA Recall",
        explanation="FMA recall scores liquid equities on force, mass, acceleration, and cross-sectional momentum strength.",
        artifact=artifact,
        selected_symbols=selected_symbols,
    )
    _render_recall_rows(
        "Selected FMA Rows",
        list(artifact.get("rows", []) or []),
        [
            ("Symbol", "symbol"),
            ("Score", "score"),
            ("Velocity60", "velocity_60d"),
            ("Accel", "accel_value"),
            ("Mass", "mass_ratio"),
            ("Force", "force_value"),
            ("RS60", "relative_strength_60d"),
        ],
    )


@recall_app.command("performance")
def recall_performance(
    date: Optional[str] = typer.Option(None, help="As-of date / artifact date (YYYY-MM-DD), defaults to today"),
    universe: str = typer.Option("semis-ai-narrow", help="Backtest universe preset"),
    benchmark: str = typer.Option("SMH", help="Benchmark ticker"),
    multi: bool = typer.Option(False, "--multi", help="Show the standard multi-universe comparison set"),
    refresh: bool = typer.Option(False, "--refresh", help="Recompute instead of reading saved artifacts"),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Show historical FVG/FMA signal-performance summary for investor/operator review."""
    run_date = date or _today_str()
    output_format = _validate_output_format(format)
    if multi:
        payload = _build_multi_universe_recall_performance_payload(
            as_of_date=run_date,
            refresh=refresh,
        )
        if output_format == "json":
            typer.echo(json_lib.dumps(payload, indent=2, default=str))
            return
        _render_multi_universe_recall_performance_payload(payload)
        return

    payload = _build_recall_performance_payload(
        as_of_date=run_date,
        universe=universe,
        benchmark=benchmark,
        refresh=refresh,
    )
    if output_format == "json":
        typer.echo(json_lib.dumps(payload, indent=2, default=str))
        return
    _render_recall_performance_payload(payload)
