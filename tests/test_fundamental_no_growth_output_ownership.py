from pathlib import Path


def test_src_panel_and_daily_run_do_not_import_growth_scripts():
    root = Path("tradingagents/research/fundamental/src")
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "tradingagents.research.fundamental.Growth" in text or "fundamental/Growth" in text:
            offenders.append(str(path))
    assert offenders == []


def test_complete_panel_exporter_is_under_src_not_growth():
    path = Path("tradingagents/research/fundamental/src/panel/exporter.py")
    assert path.exists()


def test_complete_candidate_panel_contract_assigns_growth_as_legacy_only():
    path = Path(
        "tradingagents/research/fundamental/docs/complete_candidate_panel_contract.md"
    )

    text = path.read_text(encoding="utf-8")

    assert "Growth/ scripts are historical research artifacts." in text
    assert "src.panel.exporter" in text
    assert "New publishable complete panels must come from" in text
    assert (
        "Legacy combined CSVs can be imported only by explicit migration tooling,"
        " not directly as `--prior-panel`."
    ) in text
