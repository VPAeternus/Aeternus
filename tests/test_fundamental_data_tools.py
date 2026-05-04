import json

from tradingagents.agents.utils.fundamental_data_tools import _compact_fundamental_payload


def test_compact_fundamental_payload_limits_reports_and_fields():
    payload = {
        "symbol": "AAPL",
        "annualReports": [
            {
                "fiscalDateEnding": f"20{year:02d}-09-30",
                "reportedCurrency": "USD",
                "totalRevenue": "100",
                "grossProfit": "50",
                "operatingIncome": "20",
                "netIncome": "15",
                "extra1": "x",
                "extra2": "x",
                "extra3": "x",
                "extra4": "x",
            }
            for year in range(30)
        ],
        "quarterlyReports": [
            {
                "fiscalDateEnding": f"2025-0{q}-30",
                "reportedCurrency": "USD",
                "totalRevenue": "25",
                "netIncome": "4",
                "extraA": "x",
                "extraB": "x",
                "extraC": "x",
            }
            for q in range(1, 5)
        ],
    }
    raw = json.dumps(payload)
    compact = _compact_fundamental_payload(
        raw,
        max_chars=1200,
        max_reports=3,
        max_fields=4,
    )

    parsed = json.loads(compact)
    assert len(parsed["annualReports"]) <= 3
    assert len(parsed["quarterlyReports"]) <= 3
    assert all(len(row.keys()) <= 4 for row in parsed["annualReports"])
    assert all(len(row.keys()) <= 4 for row in parsed["quarterlyReports"])


def test_compact_fundamental_payload_truncates_non_json():
    raw = "A" * 2000
    compact = _compact_fundamental_payload(raw, max_chars=200)
    assert len(compact) <= 200
    assert compact.endswith("[truncated by Aeternus payload guard]")

