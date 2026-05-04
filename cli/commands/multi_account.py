"""Multi-account execution — build plans and execute across configured Alpaca accounts."""

from cli.common import *  # noqa: F401,F403

import json as json_lib
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple


ACCOUNTS_DEFAULT_PATH = Path("config/accounts.json")


def load_accounts(accounts_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Load account profiles from JSON config."""
    path = Path(accounts_path) if accounts_path else ACCOUNTS_DEFAULT_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"Accounts config not found: {path}. "
            f"Expected JSON with 'accounts' array at {ACCOUNTS_DEFAULT_PATH}"
        )
    data = json_lib.loads(path.read_text())
    accounts = data.get("accounts", [])
    if not accounts:
        raise ValueError(f"No accounts defined in {path}")
    return accounts


@contextmanager
def _with_account_credentials(env_prefix: str) -> Generator[None, None, None]:
    """Temporarily set APCA env vars for an account, restoring originals on exit."""
    keys = ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY")
    orig: Dict[str, Optional[str]] = {k: os.environ.get(k) for k in keys}
    try:
        for k in keys:
            prefixed = f"{env_prefix}_{k}"
            value = os.getenv(prefixed, orig.get(k) or "")
            os.environ[k] = value
        yield
    finally:
        for k, v in orig.items():
            if v is not None:
                os.environ[k] = v
            elif k in os.environ:
                del os.environ[k]


def _resolve_account_execution_paths(
    account_name: str, mode: str
) -> Tuple[str, str, str]:
    """Return (base_dir, orders_path, positions_path) for a named account."""
    normalized = str(mode or "paper").strip().lower().replace("_", "-")
    live_modes = {"live", "alpaca-paper", "alpaca-live"}
    if normalized in live_modes:
        base = f"eval_results/{account_name}_execution"
        return (
            base,
            f"{base}/outbox.json",
            f"{base}/positions_shadow.json",
        )
    base = f"eval_results/{account_name}_execution"
    return (
        base,
        f"{base}/orders.json",
        f"{base}/positions.json",
    )


def build_account_plan(
    account: Dict[str, Any],
    batch_summary: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a portfolio plan for a single account (includes V3 residual QQQ)."""
    from tradingagents.graph.paper_execution import build_portfolio_plan

    plan = build_portfolio_plan(
        batch_summary=batch_summary,
        capital_usd=float(account.get("capital_usd", 100000)),
        max_positions=int(account.get("max_positions", 8)),
        enforce_whole_shares=True,
    )
    plan["account_name"] = account.get("name", "unknown")
    plan["account_label"] = account.get("label", "")
    return plan


def _persist_account_plan(plan: Dict[str, Any], base_dir: str) -> Path:
    """Write plan JSON to account-specific directory."""
    import datetime

    plan_date = str(plan.get("date") or "unknown")
    plans_dir = Path(base_dir) / "plans" / plan_date
    plans_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%H%M%S")
    path = plans_dir / f"portfolio_plan_{stamp}.json"
    payload = dict(plan)
    payload["plan_path"] = str(path)
    path.write_text(json_lib.dumps(payload, indent=2))
    # Latest symlink
    latest = Path(base_dir) / "latest_plan.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json_lib.dumps(payload, indent=2))
    return path


@app.command("accounts")
def show_accounts(
    accounts_path: Optional[Path] = typer.Option(
        None,
        "--accounts-path",
        help="Path to accounts config JSON.",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Show configured accounts and CC eligibility projections."""
    output_format = str(format or "table").lower().strip()
    try:
        accounts = load_accounts(accounts_path)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    if output_format == "json":
        print(json_lib.dumps(accounts, indent=2))
        return

    table = Table(title="Configured Accounts")
    table.add_column("Name", style="cyan")
    table.add_column("Label", style="white")
    table.add_column("Capital", justify="right")
    table.add_column("Max Pos", justify="right")
    table.add_column("Mode", style="yellow")
    table.add_column("Hedge", justify="center")
    table.add_column("CC Wyckoff", justify="center")
    table.add_column("Env Prefix", style="magenta")
    table.add_column("Creds", justify="center")

    for acct in accounts:
        prefix = str(acct.get("env_prefix", ""))
        has_key = bool(os.getenv(f"{prefix}_APCA_API_KEY_ID") or os.getenv("APCA_API_KEY_ID"))
        table.add_row(
            str(acct.get("name", "")),
            str(acct.get("label", "")),
            f"${float(acct.get('capital_usd', 0)):,.0f}",
            str(acct.get("max_positions", "")),
            str(acct.get("execution_mode", "")),
            "[green]Y[/green]" if acct.get("hedge_enabled") else "N",
            "[green]Y[/green]" if acct.get("cc_wyckoff_enabled") else "N",
            prefix,
            "[green]OK[/green]" if has_key else "[red]MISS[/red]",
        )

    console.print(table)
    console.print(f"[dim]Total capital: ${sum(float(a.get('capital_usd', 0)) for a in accounts):,.0f}[/dim]")


@app.command("execute-accounts")
def execute_accounts(
    queue_date: Optional[str] = typer.Option(
        None,
        "--queue-date",
        help="Queue date (YYYY-MM-DD) used to locate batch summary.",
    ),
    accounts_path: Optional[Path] = typer.Option(
        None,
        "--accounts-path",
        help="Path to accounts config JSON.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run/--live",
        help="Build plans only, do not submit orders.",
    ),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Build plans and execute for all configured accounts."""
    from tradingagents.dealflow.system_halt import is_hands_off_active
    from tradingagents.graph.paper_execution import (
        build_rebalance_execution_plan,
        evaluate_pretrade_risk,
        execute_plan_with_adapter,
    )

    if is_hands_off_active():
        console.print("[bold red]SYSTEM HALT ACTIVE — aborting.[/bold red]")
        raise typer.Exit(code=1)

    output_format = str(format or "table").lower().strip()

    try:
        accounts = load_accounts(accounts_path)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    try:
        batch_summary, resolved_summary_path = _load_batch_summary(queue_date=queue_date)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    results: List[Dict[str, Any]] = []

    for acct in accounts:
        name = str(acct.get("name", "unknown"))
        label = str(acct.get("label", name))
        prefix = str(acct.get("env_prefix", ""))
        mode = str(acct.get("execution_mode", "paper"))
        console.print(f"\n[bold cyan]── {label} ({name}) ──[/bold cyan]")

        # Build plan (includes V3 residual QQQ automatically)
        plan = build_account_plan(acct, batch_summary)
        base_dir, orders_path, positions_path = _resolve_account_execution_paths(name, mode)
        plan_path = _persist_account_plan(plan, base_dir)
        console.print(f"  Plan: {len(plan.get('orders', []))} orders, plan_path={plan_path}")

        # CC eligible summary
        cc_orders = [o for o in plan.get("orders", []) if o.get("cc_eligible")]
        if cc_orders:
            cc_syms = ", ".join(o["symbol"] for o in cc_orders)
            console.print(f"  [green]CC eligible:[/green] {cc_syms}")

        v3_residual = plan.get("v3_residual_usd", 0)
        if v3_residual > 0:
            console.print(f"  [yellow]V3 residual:[/yellow] ${v3_residual:,.0f} → QQQ")

        acct_result: Dict[str, Any] = {
            "account": name,
            "label": label,
            "plan_id": plan.get("plan_id"),
            "plan_path": str(plan_path),
            "orders_count": len(plan.get("orders", [])),
            "cc_eligible_count": len(cc_orders),
            "v3_residual_usd": v3_residual,
            "executed": False,
        }

        if dry_run:
            console.print("  [dim]Dry run — skipping execution[/dim]")
            results.append(acct_result)
            continue

        # Execute with account-specific credentials
        try:
            with _with_account_credentials(prefix):
                normalized_mode = mode.strip().lower().replace("_", "-")

                # Rebalance
                execution_plan = build_rebalance_execution_plan(
                    plan=plan,
                    positions_path=positions_path,
                    min_rebalance_notional_usd=100.0,
                    close_missing_positions=False,
                )

                # Pre-trade risk
                risk_check = evaluate_pretrade_risk(
                    plan=execution_plan,
                    positions_path=positions_path,
                )
                execution_plan = dict(execution_plan)
                execution_plan["orders"] = list(risk_check.get("accepted_orders", []))

                if execution_plan["orders"]:
                    exec_result = execute_plan_with_adapter(
                        plan=execution_plan,
                        execution_mode=normalized_mode,
                        orders_path=orders_path,
                        positions_path=positions_path,
                    )
                    acct_result["executed"] = True
                    acct_result["submitted"] = exec_result.get("submitted_orders", 0)
                    acct_result["filled"] = exec_result.get("executed_orders", 0)
                    console.print(
                        f"  [green]Executed:[/green] "
                        f"{acct_result['submitted']} submitted, "
                        f"{acct_result['filled']} filled"
                    )
                else:
                    console.print("  [yellow]No orders accepted by risk gate[/yellow]")
                    acct_result["risk_status"] = str(risk_check.get("status", "UNKNOWN"))
        except Exception as exc:
            console.print(f"  [red]Error: {exc}[/red]")
            acct_result["error"] = str(exc)

        results.append(acct_result)

    # Summary
    if output_format == "json":
        print(json_lib.dumps(results, indent=2))
        return

    console.print("\n")
    summary = Table(title="Multi-Account Execution Summary")
    summary.add_column("Account", style="cyan")
    summary.add_column("Orders", justify="right")
    summary.add_column("CC Eligible", justify="right")
    summary.add_column("V3 Residual", justify="right")
    summary.add_column("Status", justify="center")

    for r in results:
        if r.get("error"):
            status = f"[red]ERROR[/red]"
        elif r.get("executed"):
            status = f"[green]FILLED {r.get('filled', 0)}[/green]"
        elif dry_run:
            status = "[yellow]DRY RUN[/yellow]"
        else:
            status = "[dim]NO ORDERS[/dim]"

        summary.add_row(
            f"{r['label']} ({r['account']})",
            str(r.get("orders_count", 0)),
            str(r.get("cc_eligible_count", 0)),
            f"${float(r.get('v3_residual_usd', 0)):,.0f}",
            status,
        )

    console.print(summary)
