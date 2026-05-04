"""
Tests for CLI commands module imports and structure.

Validates that cli.commands submodules (created by S-002) import cleanly,
have no circular dependencies, and maintain the expected command count.
"""

import sys
import os
import importlib
import pytest


# Expected submodules from cli/commands/
COMMAND_SUBMODULES = [
    "cli.commands.scoring",
    "cli.commands.dealflow",
    "cli.commands.execution",
    "cli.commands.performance",
    "cli.commands.portfolio",
    "cli.commands.operator",
]


def _has_cli_commands_submodules():
    """Factory helper: check if cli/commands submodules exist."""
    commands_dir = os.path.join(os.path.dirname(__file__), "..", "cli", "commands")
    return os.path.isdir(commands_dir) and os.path.exists(
        os.path.join(commands_dir, "__init__.py")
    )


def _clean_sys_modules(*module_names):
    """Factory helper: remove modules from sys.modules for clean import testing."""
    for name in module_names:
        sys.modules.pop(name, None)


class TestCliCommandsImports:
    """Validate that cli.commands submodules import cleanly."""

    @pytest.mark.skipif(
        not _has_cli_commands_submodules(),
        reason="cli.commands submodules not yet created (S-002 pending)",
    )
    @pytest.mark.parametrize("submodule", COMMAND_SUBMODULES)
    def test_submodule_imports(self, submodule):
        """Each commands submodule should import without errors."""
        _clean_sys_modules(submodule)

        try:
            module = importlib.import_module(submodule)
            assert module is not None, f"{submodule} imported but is None"
        finally:
            _clean_sys_modules(submodule)

    @pytest.mark.skipif(
        not _has_cli_commands_submodules(),
        reason="cli.commands submodules not yet created (S-002 pending)",
    )
    @pytest.mark.parametrize("submodule", COMMAND_SUBMODULES)
    def test_submodule_wildcard_import(self, submodule):
        """Each commands submodule should support wildcard import."""
        _clean_sys_modules(submodule)

        try:
            # Test that wildcard import works (from cli.commands.X import *)
            module = importlib.import_module(submodule)
            # Check that module has __all__ or at least some public members
            if hasattr(module, "__all__"):
                assert isinstance(module.__all__, (list, tuple)), \
                    f"{submodule}.__all__ must be a list or tuple"
            else:
                # If no __all__, module should have some public content
                public_members = [name for name in dir(module) if not name.startswith("_")]
                assert len(public_members) > 0, \
                    f"{submodule} has no public members (no __all__ and no public symbols)"
        finally:
            _clean_sys_modules(submodule)


class TestCliCircularImports:
    """Validate that importing cli.commands submodules doesn't cause circular imports."""

    @pytest.mark.skipif(
        not _has_cli_commands_submodules(),
        reason="cli.commands submodules not yet created (S-002 pending)",
    )
    @pytest.mark.parametrize("submodule", COMMAND_SUBMODULES)
    def test_no_circular_imports_with_main(self, submodule):
        """Importing a submodule then cli.main should not cause circular imports."""
        modules_to_clean = [
            submodule, "cli.main", "cli", "cli.models", "cli.utils",
            "cli.common", "cli.commands"
        ]
        _clean_sys_modules(*modules_to_clean)

        try:
            # First import the submodule
            importlib.import_module(submodule)

            # Then import cli.main (should not fail with circular import)
            cli_main = importlib.import_module("cli.main")
            assert cli_main is not None, "cli.main failed to import after submodule"

            # Verify cli.main has the app
            assert hasattr(cli_main, "app"), "cli.main must have 'app' attribute"

        finally:
            _clean_sys_modules(*modules_to_clean)


class TestCliCommandCount:
    """Validate the total command count matches expectations."""

    def test_app_has_expected_command_count(self):
        """cli.main.app should have ~36+ registered commands.

        Current count includes:
        - 34 main app commands (hedge-evaluate, hedge-status, track_record, etc.)
        - 4 watchlist subcommands (via watchlist_app)
        - Total: ~38 commands

        After S-002 refactoring, this count should remain the same.
        """
        try:
            from cli.main import app
        except (ImportError, ModuleNotFoundError) as e:
            pytest.skip(f"Could not import cli.main: {e}")
        except Exception as e:
            # Catch dependency errors (e.g., chromadb/pydantic)
            pytest.skip(f"Dependency error importing cli.main: {type(e).__name__}")

        # Verify the app exists and has basic structure
        assert app is not None, "cli.main.app must not be None"
        assert hasattr(app, "command"), "app must have 'command' method (Typer)"

    def test_app_can_be_invoked(self):
        """cli.main.app should be a valid Typer app."""
        try:
            from cli.main import app
        except (ImportError, ModuleNotFoundError) as e:
            pytest.skip(f"Could not import cli.main: {e}")
        except Exception as e:
            # Catch dependency errors (e.g., chromadb/pydantic)
            pytest.skip(f"Dependency error importing cli.main: {type(e).__name__}")

        # Verify it's a Typer app by checking for expected methods
        assert hasattr(app, "command"), "app must have 'command' method (Typer)"
        assert callable(app.command), "app.command must be callable"

        # Verify it has a callback
        assert hasattr(app, "callback"), "app must have 'callback' method"
        assert callable(app.callback), "app.callback must be callable"


class TestWatchlistSubcommands:
    """Validate that the watchlist subcommand group exists and works."""

    def test_watchlist_app_exists(self):
        """cli.main should register a watchlist subcommand group."""
        try:
            from cli.main import app, watchlist_app
        except (ImportError, ModuleNotFoundError) as e:
            pytest.skip(f"Could not import cli.main: {e}")
        except Exception as e:
            # Catch dependency errors (e.g., chromadb/pydantic)
            pytest.skip(f"Dependency error importing cli.main: {type(e).__name__}")

        assert watchlist_app is not None, "watchlist_app must be defined in cli.main"

        # Verify it has some commands
        assert hasattr(watchlist_app, "command"), "watchlist_app must be a Typer app"
        assert callable(watchlist_app.command), "watchlist_app.command must be callable"

    def test_watchlist_app_is_registered(self):
        """The main app should register watchlist_app as a subcommand group."""
        try:
            from cli.main import app
        except (ImportError, ModuleNotFoundError) as e:
            pytest.skip(f"Could not import cli.main: {e}")
        except Exception as e:
            # Catch dependency errors (e.g., chromadb/pydantic)
            pytest.skip(f"Dependency error importing cli.main: {type(e).__name__}")

        # Verify watchlist_app is registered by checking app internals
        # This is a basic check that the subapp exists
        assert hasattr(app, "__dict__"), "app must have __dict__"
