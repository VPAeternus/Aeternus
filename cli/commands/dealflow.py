"""Dealflow CLI command facade.

Command implementations live in family modules. Importing them registers
commands on the shared Typer apps from ``cli.common``. Re-export names here
for legacy tests/monkeypatch paths.
"""

from cli.common import *  # noqa: F401,F403
from cli.commands.dealflow_watchlist import *  # noqa: F401,F403
from cli.commands.dealflow_pipeline import *  # noqa: F401,F403
from cli.commands.dealflow_workflow_interactive import *  # noqa: F401,F403
from cli.commands.dealflow_workflow_interactive import (  # noqa: F401
    _interactive_complete_earnings_options,
    _interactive_complete_macro,
    _interactive_complete_x_feed,
    _read_multiline_until_end,
    _run_workflow_interactive,
)
from cli.commands.dealflow_workflow import *  # noqa: F401,F403
from cli.commands.dealflow_x_discovery import *  # noqa: F401,F403
from cli.commands.dealflow_evidence import *  # noqa: F401,F403
from cli.commands.dealflow_hindsight import *  # noqa: F401,F403
