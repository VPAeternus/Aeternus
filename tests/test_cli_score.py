# tests/test_cli_score.py
# Smoke tests for CLI scoring commands

import sys
import types

# Stub chromadb before it can be imported (pydantic v1 incompatible with Python 3.14)
if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []  # make it look like a package
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub


def test_cli_score_command_imports():
    """Test that the score command module can be imported without errors."""
    try:
        from cli.commands.scoring import score, analyze
        assert callable(score)
        assert callable(analyze)
    except ImportError as e:
        raise AssertionError(f"Failed to import CLI scoring commands: {e}")


def test_cli_main_imports_scoring():
    """Test that cli.main successfully imports cli.commands.scoring."""
    try:
        import cli.main  # This triggers import of scoring.py
        import cli.commands.scoring
        # If we get here, the import was successful
        assert True
    except Exception as e:
        raise AssertionError(f"Failed to import cli.main or scoring commands: {e}")


def test_analyze_batch_command_removed():
    """Dealflow must not expose a pre-fundamental batch analysis command."""
    from cli.main import app
    commands = [cmd.name for cmd in app.registered_commands if cmd.name is not None]
    removed_command = "analyze" + "-batch"
    assert removed_command not in commands, f"Removed command still registered. Available: {commands}"
