from cli.common import *  # noqa: F401,F403

import importlib.util
import json as _json
from functools import lru_cache
from pathlib import Path

from typing import List, Optional


DEFAULT_TECHNICAL_SIGNAL_DB_PATH = str(Path("eval_results") / "control" / "technical_signal_cache.db")
DEFAULT_TECHNICAL_UNIVERSE_DIR = str(Path("eval_results") / "control" / "technical_universe")


@lru_cache(maxsize=1)
def _load_cc_backtest_module():
    module_path = Path(__file__).resolve().parents[2] / "strategies" / "regime_exit" / "regime_exit_strategy.py"
    spec = importlib.util.spec_from_file_location("regime_exit_strategy_cli", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _build_cc_portfolio_metrics(df, holdout: int = 3, initial_shares: int = 100) -> dict:
    """Compute simple 100-share portfolio metrics using the standalone CC backtest math."""
    try:
        if df is None or len(df) < 300:
            return {}

        close_col = "close" if "close" in df.columns else ("Close" if "Close" in df.columns else None)
        if close_col is None:
            return {}

        raw = df.reset_index(drop=True).copy()
        raw["Close"] = raw[close_col]
        cols = ["Close"]
        if "Volume" in raw.columns:
            cols.append("Volume")
        elif "volume" in raw.columns:
            raw["Volume"] = raw["volume"]
            cols.append("Volume")

        raw = raw[cols].copy()

        mod = _load_cc_backtest_module()
        raw = mod.compute_indicators(raw)
        raw["accel"] = mod.compute_accel(raw["Close"], raw["sma3"], lb=5)
        result_df = mod.run_cc_overbought(raw, holdout=holdout)
        metrics = mod.compute_metrics(raw, result_df, initial_shares=initial_shares)

        return {
            "strategy_return_pct": metrics.get("strategy_return_pct"),
            "buy_hold_return_pct": metrics.get("buy_hold_return_pct"),
            "strategy_cagr_pct": metrics.get("strategy_cagr_pct"),
            "sharpe_strat": metrics.get("sharpe_strat"),
            "max_dd_strat": metrics.get("max_dd_strat"),
        }
    except Exception:
        return {}


def _display_backtest_result(result) -> None:
    """Display a BacktestResult as Rich tables."""
    table = Table(
        title=f"Backtest Results — {result.ticker}",
        box=box.ROUNDED, show_header=True,
    )
    table.add_column("Metric", style="bold cyan", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("Ticker", result.ticker)
    table.add_row("Period", f"{result.start_date} → {result.end_date}")
    table.add_row(
        "Capital",
        f"${result.start_capital:,.2f} → ${result.final_equity:,.2f}",
    )
    table.add_row("Total Return", f"{result.total_return_pct:.2f}%")
    table.add_row("CAGR", f"{result.cagr_pct:.2f}%")
    table.add_row("Sharpe", f"{result.sharpe:.2f}")
    table.add_row("Sortino", f"{result.sortino:.2f}")
    table.add_row("Max Drawdown", f"{result.max_drawdown_pct:.2f}%")
    table.add_row("Max DD Duration", f"{result.max_drawdown_duration_days} days")
    table.add_row("Total Trades", str(result.total_trades))
    table.add_row("Signal Win Rate", f"{result.signal_win_rate_pct:.1f}%")
    table.add_row("Avg Signal P&L", f"${result.avg_signal_pnl:.4f}")
    table.add_row("Benchmark Return", f"{result.benchmark_return_pct:.2f}%")
    table.add_row("Benchmark CAGR", f"{result.benchmark_cagr_pct:.2f}%")
    table.add_row("Alpha", f"{result.alpha_pct:.2f}%")

    console.print(table)

    # Signal breakdown sub-table
    if result.signal_breakdown:
        sub = Table(
            title="Signal Breakdown",
            box=box.SIMPLE_HEAVY, show_header=True,
        )
        sub.add_column("Signal", style="bold yellow")
        sub.add_column("Count", style="white")
        sub.add_column("Win Rate", style="white")
        sub.add_column("Total P&L", style="white")
        for sig_name, stats in result.signal_breakdown.items():
            sub.add_row(
                sig_name,
                str(stats.get("count", 0)),
                f"{stats.get('win_rate', 0):.1f}%",
                f"${stats.get('total_pnl', 0):.2f}",
            )
            console.print(sub)


def _display_fvg_backtest_result(result: dict) -> None:
    summary = Table(
        title=f"FVG Backtest — {result.get('universe_name', 'unknown')}",
        box=box.ROUNDED,
        show_header=True,
    )
    summary.add_column("Metric", style="bold cyan", no_wrap=True)
    summary.add_column("Value", style="white")
    summary.add_row("Benchmark", str(result.get("benchmark", "N/A")))
    summary.add_row("Artifact Dir", str(result.get("artifact_dir", "N/A")))

    event_summary = result.get("event_summary", {}) or {}
    basket_summary = result.get("basket_summary", {}) or {}
    summary.add_row("Event Count", str(event_summary.get("event_count", 0)))
    summary.add_row("Mean 20d Event Return", _pct_or_na(event_summary.get("mean_forward_return_20d")))
    summary.add_row("Mean 30d Event Return", _pct_or_na(event_summary.get("mean_forward_return_30d")))
    summary.add_row("Mean 60d Event Return", _pct_or_na(event_summary.get("mean_forward_return_60d")))
    summary.add_row("Top-N", str(basket_summary.get("top_n", 0)))
    summary.add_row("Avg 20d Basket Return", _pct_or_na(basket_summary.get("avg_forward_return_20d")))
    summary.add_row("Avg 30d Basket Return", _pct_or_na(basket_summary.get("avg_forward_return_30d")))
    summary.add_row("Avg 60d Basket Return", _pct_or_na(basket_summary.get("avg_forward_return_60d")))
    summary.add_row("Avg 20d Edge vs Benchmark", _pct_or_na(basket_summary.get("avg_edge_vs_benchmark_20d")))
    summary.add_row("Avg 30d Edge vs Benchmark", _pct_or_na(basket_summary.get("avg_edge_vs_benchmark_30d")))
    summary.add_row("Avg 60d Edge vs Benchmark", _pct_or_na(basket_summary.get("avg_edge_vs_benchmark_60d")))
    console.print(summary)

    top_tickers = result.get("top_tickers", []) or []
    if top_tickers:
        table = Table(title="Top Tickers", box=box.SIMPLE_HEAVY, show_header=True)
        table.add_column("Ticker", style="bold yellow")
        table.add_column("Events", style="white")
        table.add_column("20d", style="white")
        table.add_column("60d", style="white")
        for row in top_tickers[:5]:
            table.add_row(
                str(row.get("ticker", "")),
                str(row.get("event_count", 0)),
                _pct_or_na(row.get("mean_forward_return_20d")),
                _pct_or_na(row.get("mean_forward_return_60d")),
            )
        console.print(table)


def _display_fvg_strategy_backtest_result(result: dict) -> None:
    summary = Table(
        title=f"FVG Strategy Backtest — {result.get('ticker', 'N/A')}",
        box=box.ROUNDED,
        show_header=True,
    )
    summary.add_column("Metric", style="bold cyan", no_wrap=True)
    summary.add_column("Value", style="white")
    summary.add_row("Benchmark", str(result.get("benchmark", "N/A")))
    summary.add_row("Artifact Dir", str(result.get("artifact_dir", "N/A")))
    summary.add_row("Total Trades", str(result.get("total_trades", 0)))
    summary.add_row("Win Rate", _pct_or_na(result.get("win_rate")))
    summary.add_row("Avg Trade Return", _pct_or_na(result.get("avg_trade_return")))
    summary.add_row("Total Return", _pct_or_na(result.get("total_return")))
    summary.add_row("Max Drawdown", _pct_or_na(result.get("max_drawdown")))
    avg_hold = result.get("avg_hold_days")
    summary.add_row("Avg Hold Days", "N/A" if avg_hold is None else f"{float(avg_hold):.1f}")
    console.print(summary)

    reasons = result.get("exit_reason_counts", {}) or {}
    if reasons:
        table = Table(title="Exit Reasons", box=box.SIMPLE_HEAVY, show_header=True)
        table.add_column("Reason", style="bold yellow")
        table.add_column("Count", style="white")
        for reason, count in sorted(reasons.items()):
            table.add_row(str(reason), str(count))
        console.print(table)


def _display_fma_backtest_result(result: dict) -> None:
    summary = Table(
        title=f"FMA Backtest — {result.get('universe_name', 'unknown')}",
        box=box.ROUNDED,
        show_header=True,
    )
    summary.add_column("Metric", style="bold cyan", no_wrap=True)
    summary.add_column("Value", style="white")
    summary.add_row("Benchmark", str(result.get("benchmark", "N/A")))
    summary.add_row("Artifact Dir", str(result.get("artifact_dir", "N/A")))
    summary.add_row("Shadow Matches Live", "Yes" if bool(result.get("shadow_variant_matches_live")) else "No")
    console.print(summary)

    variant_summaries = result.get("variant_summaries", {}) or {}
    if variant_summaries:
        table = Table(title="Variant Summaries", box=box.SIMPLE_HEAVY, show_header=True)
        table.add_column("Variant", style="bold yellow")
        table.add_column("Events", style="white")
        table.add_column("20d", style="white")
        table.add_column("60d", style="white")
        table.add_column("20d Edge", style="white")
        table.add_column("60d Edge", style="white")
        for variant, stats in variant_summaries.items():
            event_summary = stats.get("event_summary", {}) or {}
            basket_summary = stats.get("basket_summary", {}) or {}
            table.add_row(
                str(variant),
                str(event_summary.get("event_count", 0)),
                _pct_or_na(event_summary.get("mean_forward_return_20d")),
                _pct_or_na(event_summary.get("mean_forward_return_60d")),
                _pct_or_na(basket_summary.get("avg_edge_vs_benchmark_20d")),
                _pct_or_na(basket_summary.get("avg_edge_vs_benchmark_60d")),
            )
        console.print(table)

    overlap_summary = result.get("overlap_summary", {}) or {}
    if overlap_summary:
        table = Table(title="Overlap Summary", box=box.SIMPLE_HEAVY, show_header=True)
        table.add_column("Bucket", style="bold yellow")
        table.add_column("Events", style="white")
        table.add_column("20d", style="white")
        table.add_column("30d", style="white")
        table.add_column("60d", style="white")
        for bucket, stats in overlap_summary.items():
            table.add_row(
                str(bucket),
                str(stats.get("event_count", 0)),
                _pct_or_na(stats.get("mean_forward_return_20d")),
                _pct_or_na(stats.get("mean_forward_return_30d")),
                _pct_or_na(stats.get("mean_forward_return_60d")),
            )
        console.print(table)


def _display_kama_backtest_result(result: dict) -> None:
    summary = Table(
        title=f"KAMA Backtest — {result.get('universe_name', 'unknown')}",
        box=box.ROUNDED,
        show_header=True,
    )
    summary.add_column("Metric", style="bold cyan", no_wrap=True)
    summary.add_column("Value", style="white")
    summary.add_row("Benchmark", str(result.get("benchmark", "N/A")))
    summary.add_row("Artifact Dir", str(result.get("artifact_dir", "N/A")))
    event_summary = result.get("event_summary", {}) or {}
    basket_summary = result.get("basket_summary", {}) or {}
    summary.add_row("Event Count", str(event_summary.get("event_count", 0)))
    summary.add_row("Mean 20d Event Return", _pct_or_na(event_summary.get("mean_forward_return_20d")))
    summary.add_row("Mean 60d Event Return", _pct_or_na(event_summary.get("mean_forward_return_60d")))
    summary.add_row("Top-N", str(basket_summary.get("top_n", 0)))
    summary.add_row("Avg 20d Basket Return", _pct_or_na(basket_summary.get("avg_forward_return_20d")))
    summary.add_row("Avg 60d Basket Return", _pct_or_na(basket_summary.get("avg_forward_return_60d")))
    summary.add_row("Avg 20d Edge vs Benchmark", _pct_or_na(basket_summary.get("avg_edge_vs_benchmark_20d")))
    summary.add_row("Avg 60d Edge vs Benchmark", _pct_or_na(basket_summary.get("avg_edge_vs_benchmark_60d")))
    console.print(summary)

    overlap_summary = result.get("overlap_summary", {}) or {}
    if overlap_summary:
        table = Table(title="Overlap Summary", box=box.SIMPLE_HEAVY, show_header=True)
        table.add_column("Bucket", style="bold yellow")
        table.add_column("Events", style="white")
        table.add_column("20d", style="white")
        table.add_column("60d", style="white")
        for bucket, stats in overlap_summary.items():
            table.add_row(
                str(bucket),
                str(stats.get("event_count", 0)),
                _pct_or_na(stats.get("mean_forward_return_20d")),
                _pct_or_na(stats.get("mean_forward_return_60d")),
            )
        console.print(table)


def _pct_or_na(value) -> str:
    if value is None:
        return "N/A"
    return f"{100.0 * float(value):.2f}%"


def _compact_scan_pct(value) -> str:
    if value is None:
        return "—"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "—"
    if numeric != numeric:
        return "—"

    abs_numeric = abs(numeric)
    if abs_numeric >= 1000:
        return f"{numeric / 1000:.1f}k%"
    if abs_numeric >= 100:
        return f"{numeric:.0f}%"
    return f"{numeric:.2f}%"


def _compact_scan_regime(regime: str) -> str:
    mapping = {
        "ABOVE_BOTH": "AbvBoth",
        "ABOVE_200_BELOW_50": "Abv200<50",
        "BELOW_200_ABOVE_50": "Blw200>50",
        "BELOW_BOTH": "BlwBoth",
    }
    return mapping.get(str(regime or "").upper(), str(regime or "—"))


def _render_scan_text(value: object, width: int, align: str = "left") -> str:
    text = str(value if value is not None else "—")
    if len(text) > width:
        text = text[: max(1, width - 1)] + "…"
    if align == "right":
        return text.rjust(width)
    return text.ljust(width)


def _display_buy_zone_state(result: dict) -> None:
    table = Table(title=f"Buy Zone — {result.get('ticker', 'N/A')}", box=box.ROUNDED, show_header=True)
    table.add_column("Metric", style="bold cyan", no_wrap=True)
    table.add_column("Value", style="white")
    table.add_row("Ticker", str(result.get("ticker", "")))
    table.add_row("Status", str(result.get("status_label", "")))
    table.add_row("As Of", str(result.get("as_of_date", "")))
    table.add_row("In Buy Zone", "Yes" if bool(result.get("in_buy_zone")) else "No")
    table.add_row("Reason", str(result.get("reason", "")))
    table.add_row("Last Cross Up", str(result.get("last_cross_up_date", "")))
    table.add_row("FVG Regime Active", "Yes" if bool(result.get("bullish_fvg_regime_active")) else "No")
    table.add_row("FVG Streak", str(result.get("bullish_fvg_streak", 0)))
    table.add_row("FVG Age Bars", str(result.get("bullish_fvg_regime_age_bars", 0)))
    table.add_row("Fast KAMA", f"{float(result.get('fast_kama', 0.0) or 0.0):.4f}")
    table.add_row("Slow KAMA", f"{float(result.get('slow_kama', 0.0) or 0.0):.4f}")
    table.add_row("Score", f"{float(result.get('score', 0.0) or 0.0):.2f}")
    console.print(table)


def _display_buy_zone_summary(rows: list[dict]) -> None:
    table = Table(title="Buy Zone Summary", box=box.ROUNDED, show_header=True)
    table.add_column("Ticker", style="bold yellow")
    table.add_column("Status", style="white")
    table.add_column("As Of", style="white")
    table.add_column("Score", style="white")
    table.add_column("Reason", style="white")
    for row in rows:
        table.add_row(
            str(row.get("ticker", "")),
            str(row.get("status_label", "")),
            str(row.get("as_of_date", "")),
            f"{float(row.get('score', 0.0) or 0.0):.2f}",
            str(row.get("reason", "")),
        )
    console.print(table)


@app.command()
def phase_scan(
    live: bool = typer.Option(False, "--live", help="Use real-time Alpaca data"),
    json: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
    tickers: Optional[List[str]] = typer.Option(
        None, "--tickers", help="Specific tickers to scan",
    ),
    refresh: bool = typer.Option(False, "--refresh", help="Force data refresh"),
) -> None:
    """Scan the universe for today's phase signals."""
    from tradingagents.phase_engine.scanner import run_scan

    # run_scan handles all output (pretty-print or JSON)
    run_scan(
        tickers=tickers if tickers else None,
        as_json=json,
        refresh=refresh,
        live=live,
    )


@app.command("technical-universe-refresh")
def technical_universe_refresh(
    sources: Optional[List[str]] = typer.Option(
        None,
        "--sources",
        help="Current-universe sources to refresh (repeatable): SPY, QQQ, DOW",
    ),
    as_of_date: str = typer.Option(
        datetime.date.today().isoformat(),
        "--as-of-date",
        help="As-of date for the current-universe snapshot",
    ),
    db_path: str = typer.Option(
        DEFAULT_TECHNICAL_SIGNAL_DB_PATH,
        "--db-path",
        help="SQLite cache path",
    ),
    artifact_dir: str = typer.Option(
        DEFAULT_TECHNICAL_UNIVERSE_DIR,
        "--artifact-dir",
        help="Snapshot artifact directory",
    ),
    format: str = typer.Option(
        "table", "--format", help="Output format: table or json",
    ),
) -> None:
    """Refresh the current SPY/QQQ/DOW universe snapshot and persist it into the technical signal cache."""
    from tradingagents.dealflow.current_universe import (
        dedupe_current_universe_tickers,
        fetch_current_universe,
        persist_current_universe_snapshot,
    )
    from tradingagents.dealflow.technical_signal_store import SQLiteTechnicalSignalStore

    effective_sources = [str(source).upper().strip() for source in (sources or ["SPY", "QQQ", "DOW"])]
    store = SQLiteTechnicalSignalStore(db_path)
    store.initialize()
    rows = fetch_current_universe(effective_sources, as_of_date=as_of_date)
    invalid_tickers = set(store.list_invalid_yahoo_tickers())
    if invalid_tickers:
        store.purge_tickers(
            sorted(
                {
                    str(row.get("ticker", "")).upper().strip()
                    for row in rows
                    if str(row.get("ticker", "")).upper().strip() in invalid_tickers
                }
            )
        )
        rows = [row for row in rows if str(row.get("ticker", "")).upper().strip() not in invalid_tickers]
    store.upsert_universe_membership_current(rows)
    snapshot_path = persist_current_universe_snapshot(
        rows,
        Path(artifact_dir) / as_of_date / f"current_universe_{'_'.join(source.lower() for source in effective_sources)}.json",
    )
    payload = {
        "sources": effective_sources,
        "as_of_date": as_of_date,
        "row_count": len(rows),
        "unique_ticker_count": len(dedupe_current_universe_tickers(rows)),
        "invalid_ticker_count": len(invalid_tickers),
        "artifact_path": str(snapshot_path),
        "db_path": str(db_path),
    }
    if str(format).lower() == "json":
        typer.echo(_json.dumps(payload, indent=2, default=str))
        return

    table = Table(title="Technical Universe Refresh", box=box.ROUNDED, show_header=True)
    table.add_column("Metric", style="bold cyan", no_wrap=True)
    table.add_column("Value", style="white")
    table.add_row("Sources", ", ".join(payload["sources"]))
    table.add_row("As Of", payload["as_of_date"])
    table.add_row("Rows", str(payload["row_count"]))
    table.add_row("Unique Tickers", str(payload["unique_ticker_count"]))
    table.add_row("Artifact", payload["artifact_path"])
    table.add_row("DB", payload["db_path"])
    console.print(table)


@app.command("technical-signal-sync")
def technical_signal_sync(
    tickers: Optional[List[str]] = typer.Option(
        None,
        "--tickers",
        "-t",
        help="Specific tickers to sync (defaults to deduped current-universe membership)",
    ),
    start_date: str = typer.Option(
        "2020-01-01",
        "--start-date",
        help="Initial backfill start date for uncached tickers",
    ),
    end_date: Optional[str] = typer.Option(
        None,
        "--end-date",
        help="Optional end date for the history sync",
    ),
    db_path: str = typer.Option(
        DEFAULT_TECHNICAL_SIGNAL_DB_PATH,
        "--db-path",
        help="SQLite cache path",
    ),
    format: str = typer.Option(
        "table", "--format", help="Output format: table or json",
    ),
) -> None:
    """Sync OHLCV history and recompute current KAMA/FVG signal state for the technical universe."""
    from tradingagents.dealflow.current_universe import dedupe_current_universe_tickers
    from tradingagents.dealflow.technical_market_cache import sync_market_history
    from tradingagents.dealflow.technical_signal_engine import recompute_signal_state
    from tradingagents.dealflow.technical_signal_store import SQLiteTechnicalSignalStore

    store = SQLiteTechnicalSignalStore(db_path)
    store.initialize()
    membership_rows = store.list_universe_membership_current(exclude_invalid=True)
    tickers_to_sync = [str(ticker).upper().strip() for ticker in (tickers or []) if str(ticker).strip()]
    if not tickers_to_sync:
        tickers_to_sync = dedupe_current_universe_tickers(membership_rows)

    market_sync = sync_market_history(
        store,
        tickers_to_sync,
        start_date=start_date,
        end_date=end_date,
    )
    signal_summaries = [
        recompute_signal_state(store, ticker, computed_at_utc=datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"))
        for ticker in tickers_to_sync
    ]
    status_counts: dict[str, int] = {}
    for row in signal_summaries:
        status = str(row.get("status_label", "UNKNOWN")).upper().strip()
        status_counts[status] = status_counts.get(status, 0) + 1
    buy_zone_count = len(store.list_buy_zone_states(status_labels=["BUY_TRIGGER", "BUY_ZONE"]))
    payload = {
        "ticker_count": len(tickers_to_sync),
        "market_sync": market_sync,
        "signal_summaries": signal_summaries,
        "status_counts": status_counts,
        "buy_zone_count": buy_zone_count,
        "db_path": str(db_path),
    }
    if str(format).lower() == "json":
        typer.echo(_json.dumps(payload, indent=2, default=str))
        return

    table = Table(title="Technical Signal Sync", box=box.ROUNDED, show_header=True)
    table.add_column("Metric", style="bold cyan", no_wrap=True)
    table.add_column("Value", style="white")
    table.add_row("Tickers", str(payload["ticker_count"]))
    table.add_row("Inserted Rows", str(payload["market_sync"].get("inserted_rows", 0)))
    table.add_row("Buy Zone Count", str(payload["buy_zone_count"]))
    table.add_row("DB", payload["db_path"])
    console.print(table)


@app.command("buy-zone")
def buy_zone(
    ticker: str = typer.Argument(..., help="Ticker to inspect"),
    db_path: str = typer.Option(
        DEFAULT_TECHNICAL_SIGNAL_DB_PATH,
        "--db-path",
        help="SQLite cache path",
    ),
    format: str = typer.Option(
        "table", "--format", help="Output format: table or json",
    ),
) -> None:
    """Show the current buy-zone state for one ticker."""
    from tradingagents.dealflow.technical_signal_store import SQLiteTechnicalSignalStore

    store = SQLiteTechnicalSignalStore(db_path)
    store.initialize()
    result = store.get_buy_zone_state(ticker)
    if result is None:
        raise typer.BadParameter(f"No buy-zone state found for {ticker}")
    if str(format).lower() == "json":
        typer.echo(_json.dumps(result, indent=2, default=str))
        return
    _display_buy_zone_state(result)


@app.command("buy-zone-summary")
def buy_zone_summary(
    status: Optional[List[str]] = typer.Option(
        None,
        "--status",
        help="Optional status filter (repeatable): BUY_TRIGGER, BUY_ZONE, TREND_UP_NOT_FRESH",
    ),
    db_path: str = typer.Option(
        DEFAULT_TECHNICAL_SIGNAL_DB_PATH,
        "--db-path",
        help="SQLite cache path",
    ),
    format: str = typer.Option(
        "table", "--format", help="Output format: table or json",
    ),
) -> None:
    """List current buy-zone states across the cached technical universe."""
    from tradingagents.dealflow.technical_signal_store import SQLiteTechnicalSignalStore

    store = SQLiteTechnicalSignalStore(db_path)
    store.initialize()
    rows = store.list_buy_zone_states(status_labels=status)
    payload = {
        "count": len(rows),
        "statuses": [str(item).upper().strip() for item in (status or [])],
        "items": rows,
    }
    if str(format).lower() == "json":
        typer.echo(_json.dumps(payload, indent=2, default=str))
        return
    _display_buy_zone_summary(rows)


@app.command()
def phase_backtest(
    ticker: Optional[str] = typer.Option(
        None, "--ticker", help="Single ticker to backtest",
    ),
    start: str = typer.Option(
        "2010-01-01", "--start", help="Backtest start date (YYYY-MM-DD)",
    ),
    capital: float = typer.Option(
        100_000.0, "--capital", help="Starting capital in USD",
    ),
) -> None:
    """Run a long/short backtest for a single ticker or full universe."""
    from tradingagents.phase_engine.backtest import (
        PhaseBacktest,
        run_portfolio_backtest,
    )

    if ticker:
        # Single ticker
        bt = PhaseBacktest(ticker=ticker, start_date=start, capital=capital)
        result = bt.run()
        _display_backtest_result(result)
    else:
        # Portfolio
        results = run_portfolio_backtest(start_date=start, capital=capital)
        per_ticker = results.get("per_ticker", {})
        portfolio = results.get("portfolio")

        # Per-ticker summary table
        summary = Table(
            title="Portfolio Backtest — Per-Ticker Summary",
            box=box.ROUNDED, show_header=True,
        )
        summary.add_column("Ticker", style="bold cyan", no_wrap=True)
        summary.add_column("Return %", style="white")
        summary.add_column("CAGR %", style="white")
        summary.add_column("Sharpe", style="white")
        summary.add_column("Max DD %", style="white")
        summary.add_column("Trades", style="white")
        summary.add_column("Alpha %", style="white")

        for t, r in sorted(per_ticker.items()):
            summary.add_row(
                r.ticker,
                f"{r.total_return_pct:.2f}",
                f"{r.cagr_pct:.2f}",
                f"{r.sharpe:.2f}",
                f"{r.max_drawdown_pct:.2f}",
                str(r.total_trades),
                f"{r.alpha_pct:.2f}",
            )
        console.print(summary)

        # Portfolio summary
        if portfolio:
            _display_backtest_result(portfolio)


@app.command()
def phase_status() -> None:
    """Show current Wyckoff phase classification for each ticker."""
    from tradingagents.phase_engine import (
        data_engine,
        phase_engine,
        config as pe_config,
    )

    table = Table(
        title="Phase Status — Current Universe",
        box=box.ROUNDED, show_header=True,
    )
    table.add_column("Ticker", style="bold cyan", no_wrap=True)
    table.add_column("Phase", style="white")
    table.add_column("Close", style="white")
    table.add_column("SMA10", style="white")
    table.add_column("SMA20", style="white")
    table.add_column("SMA50", style="white")
    table.add_column("VIX", style="white")

    for t in pe_config.UNIVERSE:
        try:
            df = data_engine.load(t)
            phases = phase_engine.classify_phases(df)
            row = df.iloc[-1]
            phase = phases.iloc[-1]

            def _fv(col):
                v = row.get(col, None)
                if v is None or (isinstance(v, float) and np.isnan(v)):
                    return "—"
                return f"{float(v):.2f}"

            table.add_row(
                t, str(phase),
                _fv("close"), _fv("sma10"), _fv("sma20"), _fv("sma50"), _fv("vix"),
            )
        except Exception as exc:
            table.add_row(t, f"ERROR: {exc}", "—", "—", "—", "—", "—")

    console.print(table)


@app.command("momentum-scan")
def momentum_scan(
    tickers: Optional[List[str]] = typer.Option(
        None, "--tickers", "-t", help="Tickers to scan (default: full universe)",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    top: int = typer.Option(0, "--top", help="Show only top N by accel_percentile (0=all)"),
) -> None:
    """
    Scan CC overbought momentum signals for stocks only + v3 index signals for QQQ/SPY.
    Shows: state (long/cash), SMA regime, accel percentile, days out, strategy return,
    buy-and-hold return, CAGR, Sharpe, and max drawdown.
    """
    import json as _json
    from datetime import date
    from tradingagents.phase_engine.cc_overbought import CCOverboughtEngine
    from tradingagents.phase_engine.index_overlay import IndexOverlayEngine
    from tradingagents.phase_engine import data_engine as pe_data_engine
    from tradingagents.phase_engine import config as pe_config

    today = date.today().isoformat()

    INDEX_SET = {"QQQ", "SPY"}

    # Resolve ticker list
    if tickers:
        all_tickers = [t.upper() for t in tickers]
    else:
        all_tickers = [t.upper() for t in pe_config.UNIVERSE]

    index_tickers = [t for t in all_tickers if t in INDEX_SET]
    stock_tickers = [t for t in all_tickers if t not in INDEX_SET]

    typer.echo(f"Scanning {len(all_tickers)} tickers ({len(index_tickers)} index, {len(stock_tickers)} stocks)...")

    # ── Section 1: Index signals ───────────────────────────────────────────────
    index_engine = IndexOverlayEngine()
    index_signals = []
    for t in index_tickers:
        try:
            sig = index_engine.get_signal(t)
            if sig:
                index_signals.append(sig)
        except Exception as exc:
            typer.echo(f"  Warning: index signal failed for {t}: {exc}", err=True)

    # ── Section 2: Stock signals ───────────────────────────────────────────────
    re_engine = CCOverboughtEngine()
    stock_signals = []
    for t in stock_tickers:
        try:
            df = pe_data_engine.load(t)
            sig = re_engine.get_signal(t, df=df)
            if sig:
                sig.update(_build_cc_portfolio_metrics(df, holdout=re_engine.holdout, initial_shares=100))
                stock_signals.append(sig)
        except Exception as exc:
            typer.echo(f"  Warning: stock signal failed for {t}: {exc}", err=True)

    # Sort stocks by accel_percentile descending (NaN last)
    def _accel_sort_key(s):
        v = s.get("accel_percentile")
        return -(v if v is not None and v == v else -1.0)

    stock_signals.sort(key=_accel_sort_key)

    # Apply --top filter
    if top > 0:
        stock_signals = stock_signals[:top]

    # ── JSON output ────────────────────────────────────────────────────────────
    if json_output:
        long_count = sum(1 for s in stock_signals if s.get("state") == "long")
        cash_count = sum(1 for s in stock_signals if s.get("state") == "cash")
        accel_vals = [
            s["accel_percentile"]
            for s in stock_signals
            if s.get("accel_percentile") is not None
        ]
        avg_accel = round(sum(accel_vals) / len(accel_vals), 4) if accel_vals else None
        payload = {
            "scan_date": today,
            "index_signals": index_signals,
            "stock_signals": stock_signals,
            "summary": {
                "long": long_count,
                "cash": cash_count,
                "total": len(stock_signals),
                "avg_accel_pct": avg_accel,
            },
        }
        typer.echo(_json.dumps(payload, indent=2, default=str))
        return

    # ── Pretty-print: Index table ──────────────────────────────────────────────
    idx_table = Table(
        title="INDEX OVERLAY — v3 VIX System",
        box=box.ROUNDED, show_header=True,
    )
    idx_table.add_column("Ticker", style="bold cyan", no_wrap=True)
    idx_table.add_column("RTH", no_wrap=True)
    idx_table.add_column("Overnight", no_wrap=True)
    idx_table.add_column("Active Leg", style="white")
    idx_table.add_column("VIX", style="white")
    idx_table.add_column("Regime", style="white")
    idx_table.add_column("Close", style="white")

    for sig in index_signals:
        rth_val = sig.get("rth", False)
        ovn_val = sig.get("overnight", False)
        rth_str = Text("YES", style="bold green") if rth_val else Text("no", style="dim")
        ovn_str = Text("YES", style="bold green") if ovn_val else Text("no", style="dim")
        active = sig.get("active_leg") or "—"
        vix = sig.get("vix")
        vix_str = f"{vix:.1f}" if vix is not None and vix == vix else "—"
        regime = sig.get("regime") or "—"
        close = sig.get("close")
        close_str = f"{close:.2f}" if close is not None and close == close else "—"
        idx_table.add_row(
            sig["ticker"], rth_str, ovn_str, active, vix_str, regime, close_str,
        )

    if index_signals:
        console.print(idx_table)
    else:
        console.print("[dim]No index signals (QQQ/SPY not in scan set)[/dim]")

    if stock_signals:
        console.print("[bold]CC OVERBOUGHT — Stock Momentum Signals[/bold]")
        columns = [
            ("Ticker", 6, "left"),
            ("State", 5, "left"),
            ("Regime", 9, "left"),
            ("Accel%", 6, "right"),
            ("Days", 4, "right"),
            ("Strategy", 8, "right"),
            ("BuyHold", 7, "right"),
            ("CAGR", 6, "right"),
            ("Sharpe", 6, "right"),
            ("MaxDD", 7, "right"),
        ]
        header = " ".join(_render_scan_text(label, width, align) for label, width, align in columns)
        divider = " ".join("─" * width for _, width, _ in columns)
        console.print(header)
        console.print(divider)

        for sig in stock_signals:
            raw_regime = sig.get("regime", "—")
            ap = sig.get("accel_percentile")
            accel_str = f"{int(round(ap * 100))}%" if ap is not None and ap == ap else "—"
            row = [
                (sig["ticker"], 6, "left"),
                ("LONG" if sig.get("state") == "long" else "CASH", 5, "left"),
                (_compact_scan_regime(raw_regime), 9, "left"),
                (accel_str, 6, "right"),
                (sig.get("days_out", 0), 4, "right"),
                (_compact_scan_pct(sig.get("strategy_return_pct")), 8, "right"),
                (_compact_scan_pct(sig.get("buy_hold_return_pct")), 7, "right"),
                (_compact_scan_pct(sig.get("strategy_cagr_pct")), 6, "right"),
                (f"{sig.get('sharpe_strat'):.2f}" if sig.get("sharpe_strat") is not None else "—", 6, "right"),
                (_compact_scan_pct(sig.get("max_dd_strat")), 7, "right"),
            ]
            console.print(" ".join(_render_scan_text(value, width, align) for value, width, align in row))

        long_count = sum(1 for s in stock_signals if s.get("state") == "long")
        cash_count = sum(1 for s in stock_signals if s.get("state") == "cash")
        total = len(stock_signals)
        accel_vals = [
            s["accel_percentile"]
            for s in stock_signals
            if s.get("accel_percentile") is not None
        ]
        avg_accel = round(sum(accel_vals) / len(accel_vals) * 100) if accel_vals else None
        avg_inv_vals = [
            s["invested_pct"]
            for s in stock_signals
            if s.get("invested_pct") is not None
        ]
        avg_inv = round(sum(avg_inv_vals) / len(avg_inv_vals), 1) if avg_inv_vals else None

        summary_parts = [
            f"  [bold green]LONG: {long_count}/{total}[/bold green]",
            f"  [bold yellow]CASH: {cash_count}/{total}[/bold yellow]",
        ]
        if avg_accel is not None:
            summary_parts.append(f"  Avg accel%: [white]{avg_accel}%[/white]")
        if avg_inv is not None:
            summary_parts.append(f"  Avg invested: [white]{avg_inv}%[/white]")
        console.print("  ".join(summary_parts))
    else:
        console.print("[dim]No stock signals computed.[/dim]")


@app.command("fvg-backtest")
def fvg_backtest(
    tickers: Optional[List[str]] = typer.Option(
        None, "--tickers", "-t", help="Tickers to backtest (default: semis/AI narrow universe)",
    ),
    universe: str = typer.Option(
        "semis-ai-narrow",
        "--universe",
        help="Universe preset: semis-ai-narrow or qqq-top20-proxy",
    ),
    benchmark: str = typer.Option(
        "SMH",
        "--benchmark",
        help="Benchmark ticker for relative edge comparison",
    ),
    start: str = typer.Option(
        "2020-01-01", "--start", help="Backtest start date (YYYY-MM-DD)",
    ),
    end: Optional[str] = typer.Option(
        None, "--end", help="Backtest end date (YYYY-MM-DD)",
    ),
    top_n: int = typer.Option(
        3, "--top-n", help="Daily top-N basket size",
    ),
    format: str = typer.Option(
        "table", "--format", help="Output format: table or json",
    ),
    artifact_dir: Optional[str] = typer.Option(
        None, "--artifact-dir", help="Optional artifact directory override",
    ),
) -> None:
    """Run the bullish FVG Step 1 recall backtest on the narrow semis/AI universe."""
    from tradingagents.dealflow.fvg_recall import normalize_universe_name, run_fvg_backtest

    result = run_fvg_backtest(
        tickers=tickers,
        universe_name=normalize_universe_name(universe),
        benchmark=benchmark,
        start=start,
        end=end,
        top_n=top_n,
        artifact_dir=artifact_dir,
    )

    if str(format).lower() == "json":
        typer.echo(_json.dumps(result, indent=2, default=str))
        return

    _display_fvg_backtest_result(result)


@app.command("fma-backtest")
def fma_backtest(
    tickers: Optional[List[str]] = typer.Option(
        None, "--tickers", "-t", help="Tickers to backtest (default: semis/AI narrow universe)",
    ),
    universe: str = typer.Option(
        "semis-ai-narrow",
        "--universe",
        help="Universe preset: semis-ai-narrow or qqq-top20-proxy",
    ),
    benchmark: str = typer.Option(
        "SMH",
        "--benchmark",
        help="Benchmark ticker for relative edge comparison",
    ),
    start: str = typer.Option(
        "2020-01-01", "--start", help="Backtest start date (YYYY-MM-DD)",
    ),
    end: Optional[str] = typer.Option(
        None, "--end", help="Backtest end date (YYYY-MM-DD)",
    ),
    top_n: int = typer.Option(
        3, "--top-n", help="Daily top-N basket size",
    ),
    format: str = typer.Option(
        "table", "--format", help="Output format: table or json",
    ),
    artifact_dir: Optional[str] = typer.Option(
        None, "--artifact-dir", help="Optional artifact directory override",
    ),
) -> None:
    """Run the F=MA Step 1 recall backtest on the narrow semis/AI universe or QQQ proxy."""
    from tradingagents.dealflow.fma_recall import run_fma_backtest
    from tradingagents.dealflow.fvg_recall import normalize_universe_name

    result = run_fma_backtest(
        tickers=tickers,
        universe_name=normalize_universe_name(universe),
        benchmark=benchmark,
        start=start,
        end=end,
        top_n=top_n,
        artifact_dir=artifact_dir,
    )

    if str(format).lower() == "json":
        typer.echo(_json.dumps(result, indent=2, default=str))
        return

    _display_fma_backtest_result(result)


@app.command("kama-backtest")
def kama_backtest(
    tickers: Optional[List[str]] = typer.Option(
        None, "--tickers", "-t", help="Tickers to backtest (default: semis/AI narrow universe)",
    ),
    universe: str = typer.Option(
        "semis-ai-narrow",
        "--universe",
        help="Universe preset: semis-ai-narrow or qqq-top20-proxy",
    ),
    benchmark: str = typer.Option(
        "SMH",
        "--benchmark",
        help="Benchmark ticker for relative edge comparison",
    ),
    start: str = typer.Option(
        "2020-01-01", "--start", help="Backtest start date (YYYY-MM-DD)",
    ),
    end: Optional[str] = typer.Option(
        None, "--end", help="Backtest end date (YYYY-MM-DD)",
    ),
    top_n: int = typer.Option(
        3, "--top-n", help="Daily top-N basket size",
    ),
    format: str = typer.Option(
        "table", "--format", help="Output format: table or json",
    ),
    artifact_dir: Optional[str] = typer.Option(
        None, "--artifact-dir", help="Optional artifact directory override",
    ),
) -> None:
    """Run the KAMA cross replay on the narrow semis/AI universe or QQQ proxy."""
    from tradingagents.dealflow.fvg_recall import normalize_universe_name
    from tradingagents.dealflow.kama_recall import run_kama_backtest

    result = run_kama_backtest(
        tickers=tickers,
        universe_name=normalize_universe_name(universe),
        benchmark=benchmark,
        start=start,
        end=end,
        top_n=top_n,
        artifact_dir=artifact_dir,
    )

    if str(format).lower() == "json":
        typer.echo(_json.dumps(result, indent=2, default=str))
        return

    _display_kama_backtest_result(result)


@app.command("fvg-qqq-backtest")
def fvg_qqq_backtest(
    start: str = typer.Option(
        "1999-01-01", "--start", help="Backtest start date (YYYY-MM-DD)",
    ),
    end: Optional[str] = typer.Option(
        None, "--end", help="Backtest end date (YYYY-MM-DD)",
    ),
    format: str = typer.Option(
        "table", "--format", help="Output format: table or json",
    ),
    artifact_dir: Optional[str] = typer.Option(
        None, "--artifact-dir", help="Optional artifact directory override",
    ),
    max_hold_days: int = typer.Option(
        90, "--max-hold-days", help="Maximum holding period in trading days",
    ),
    compare_exits: bool = typer.Option(
        False, "--compare-exits", help="Compare Exit C, SMA50-only, 90d-only, and buy-and-hold",
    ),
    execution_timing: str = typer.Option(
        "next_open", "--execution-timing", help="Execution timing: next_open or signal_close",
    ),
) -> None:
    """Run the confirmed bullish FVG strategy on QQQ using SPY for relative strength."""
    from tradingagents.dealflow.fvg_recall import run_fvg_strategy_backtest, run_fvg_strategy_exit_comparison

    if compare_exits:
        result = run_fvg_strategy_exit_comparison(
            ticker="QQQ",
            benchmark="SPY",
            start=start,
            end=end,
            artifact_dir=artifact_dir,
            max_hold_days=max_hold_days,
            execution_timing=execution_timing,
        )
    else:
        result = run_fvg_strategy_backtest(
            ticker="QQQ",
            benchmark="SPY",
            start=start,
            end=end,
            artifact_dir=artifact_dir,
            max_hold_days=max_hold_days,
            execution_timing=execution_timing,
        )

    if str(format).lower() == "json":
        typer.echo(_json.dumps(result, indent=2, default=str))
        return

    if compare_exits:
        table = Table(title="FVG QQQ Exit Comparison", box=box.ROUNDED, show_header=True)
        table.add_column("Strategy", style="bold cyan")
        table.add_column("Total Return", style="white")
        table.add_column("Max Drawdown", style="white")
        for name, stats in (result.get("strategies", {}) or {}).items():
            table.add_row(
                str(name),
                _pct_or_na(stats.get("total_return")),
                _pct_or_na(stats.get("max_drawdown")),
            )
        console.print(table)
        return

    _display_fvg_strategy_backtest_result(result)
