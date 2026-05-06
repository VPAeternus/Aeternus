import datetime as dt

from tradingagents.backtesting.thirteenf.manager_scan import filter_proper_managers, load_manager_quality_rules, manager_aum_summary, parse_13f_managers_from_form_index, recent_quarters


def test_recent_quarters_rolls_year():
    assert recent_quarters(3, today=dt.date(2026, 1, 15)) == [(2026, 1), (2025, 4), (2025, 3)]


def test_parse_13f_managers_from_form_index():
    text = """Form Type   Company Name   CIK   Date Filed   File Name
--------------------------------------------------------------------------------
13F-HR        ACME CAPITAL LP                         1234567890 2026-05-01 edgar/data/1234567890/0001234567-26-000001.txt
10-K          OTHER                                   1 2026-01-01 edgar/data/1/x.txt
"""
    rows = parse_13f_managers_from_form_index(text)
    assert len(rows) == 1
    assert rows[0]["manager_cik"] == "1234567890"
    assert rows[0]["manager_name"] == "ACME CAPITAL LP"
    assert rows[0]["accession"] == "0001234567-26-000001"


def test_filter_proper_managers_excludes_banks_and_pensions():
    rows = [
        {"manager_name": "Alpha Capital LP"},
        {"manager_name": "Example National Bank"},
        {"manager_name": "Employees Provident Fund Board"},
    ]
    assert [row["manager_name"] for row in filter_proper_managers(rows)] == ["Alpha Capital LP"]


def test_filter_proper_managers_honors_allowlist():
    rows = [{"manager_name": "Example National Bank", "manager_cik": "123"}]
    rules = {"allowlist_ciks": ["0000000123"], "deny_terms": ["bank"], "allow_terms": []}
    assert len(filter_proper_managers(rows, rules=rules)) == 1


def test_manager_aum_summary_uses_latest_report():
    rows = [
        {"manager_id": "m1", "manager_name": "M1", "manager_cik": "1", "report_date": "2024-03-31", "market_value": 100.0},
        {"manager_id": "m1", "manager_name": "M1", "manager_cik": "1", "report_date": "2024-06-30", "market_value": 200.0},
        {"manager_id": "m1", "manager_name": "M1", "manager_cik": "1", "report_date": "2024-06-30", "market_value": 300.0},
    ]
    out = manager_aum_summary(rows)["m1"]
    assert out["latest_report_date"] == "2024-06-30"
    assert out["latest_13f_aum_usd"] == 500.0
    assert out["latest_position_count"] == 2
