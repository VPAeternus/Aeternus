"""Aeternus CLI — entry point.

This module is intentionally thin. All commands are implemented in
cli/commands/ submodules and shared infrastructure lives in cli/common.py.

Importing cli.common triggers load_dotenv() and all tradingagents imports,
so the call order here is intentional: common first, then command modules
to register their @app.command() decorators on the shared app instance.
"""
import importlib

from cli.common import app  # noqa: E402 — loads dotenv + tradingagents imports

# Import command modules to trigger @app.command() / @watchlist_app.command()
# registration on the shared app/watchlist_app instances.
# Use importlib.import_module() to ensure proper module binding even in circular import scenarios
_auth = importlib.import_module("cli.commands.auth")  # login
app.add_typer(_auth.app, name="login")
importlib.import_module("cli.commands.operator")      # hedge-evaluate, hedge-status
importlib.import_module("cli.commands.performance")   # track-record, performance, rating-history
importlib.import_module("cli.commands.dealflow")      # watchlist, source, orchestrate, queue, workflow-*, evidence-*, x-discovery, step1-readiness
importlib.import_module("cli.commands.portfolio")     # portfolio-plan
importlib.import_module("cli.commands.execution")     # execute-paper, panic-liquidate, reconciliation-loop, pull-broker-*, positions-drift, reconcile-execution, execution-sync, manage-exits, execution-readiness, manage-open-orders, sync-positions-from-broker, paper-positions, live-positions, close-paper
importlib.import_module("cli.commands.scoring")       # score, analyze, analyze-batch
importlib.import_module("cli.commands.technical")     # phase-scan, phase-backtest, phase-status, momentum-scan
importlib.import_module("cli.commands.scheduler")     # scheduler-start, scheduler-status, scheduler-stop, scheduler-trigger
importlib.import_module("cli.commands.commodity_shock")  # commodity-scan
# importlib.import_module("cli.commands.insider_sweep")    # insider-sweep — deleted (insider_cluster collector runs in pipeline automatically)
importlib.import_module("cli.commands.dod_scan")         # dod-scan
importlib.import_module("cli.commands.content")       # content-review, content-generate, track-record-dashboard
importlib.import_module("cli.commands.brief")         # brief, brief-html
importlib.import_module("cli.commands.dashboard")     # dashboard
importlib.import_module("cli.commands.multi_account") # accounts, execute-accounts
importlib.import_module("cli.commands.forces")        # forces list, forces show, forces dark-matter
importlib.import_module("cli.commands.roll_monitor")  # options-add, options-list, options-close, roll-check
importlib.import_module("cli.commands.universe_seeder")  # akg-seed
# importlib.import_module("cli.commands.x_feed_scout")     # x-discover — disabled (xAI API not used, replaced by x-feed manual workflow)
importlib.import_module("cli.commands.breakout_scanner")  # breakout-scan
# importlib.import_module("cli.commands.social_prompt")      # social-prompt — deleted (replaced by x-feed 13-pass workflow)
importlib.import_module("cli.commands.x_feed_manual")      # x-feed
importlib.import_module("cli.commands.research_analysts") # research-analysts
importlib.import_module("cli.commands.position_review")    # position-review
importlib.import_module("cli.commands.manual_positions")   # add-position, remove-position
importlib.import_module("cli.commands.cohort_compare")     # cohort-compare
importlib.import_module("cli.commands.symphony")           # symphony-status
importlib.import_module("cli.commands.fundamental")        # fundamental
importlib.import_module("cli.commands.context")            # event-state
importlib.import_module("cli.commands.recall")             # recall fvg, recall fma


def main() -> None:
    """Entry point for the Aeternus CLI."""
    app()


if __name__ == "__main__":
    main()
