from pathlib import Path


def test_fundamental_cli_implementation_is_domain_owned():
    import cli.commands.fundamental as root_wrapper
    import tradingagents.research.fundamental.src.cli.commands as domain_commands

    assert root_wrapper.fundamental_top15 is domain_commands.fundamental_top15
    assert root_wrapper.fundamental_run_today is domain_commands.fundamental_run_today


def test_fundamental_framework_has_canonical_review_docs():
    root = Path("tradingagents/research/fundamental")
    required = [
        "FRAMEWORK_INDEX.md",
        "ARCHITECTURE.md",
        "ARTIFACTS.md",
        "docs/scoring_input_contract.md",
        "docs/daily_run_gate_sequence.md",
        "docs/daily_universe_llm_funnel_contract.md",
    ]
    missing = [path for path in required if not (root / path).is_file()]
    assert missing == []


def test_fundamental_default_run_roots_are_inside_framework_folder():
    from tradingagents.research.fundamental.src.config.paths import (
        FUNDAMENTAL_ROOT,
        default_daily_run_root,
        default_legacy_run_root,
        default_selection_output_root,
    )

    assert default_daily_run_root("2026-05-12", "2026Q2").is_relative_to(FUNDAMENTAL_ROOT)
    assert default_legacy_run_root("2026-05-12", "2026Q2").is_relative_to(FUNDAMENTAL_ROOT)
    assert default_selection_output_root("2026-05-12").is_relative_to(FUNDAMENTAL_ROOT)
