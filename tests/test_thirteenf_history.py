import json

from tradingagents.backtesting.thirteenf.history import build_13f_deltas, fetch_historical_13f_holdings


def test_build_13f_deltas_computes_qoq_changes(tmp_path):
    holdings = tmp_path / "holdings.csv"
    holdings.write_text(
        "manager_id,manager_name,filing_date,report_date,ticker,shares,market_value,ticker_status\n"
        "m1,M1,2024-02-14,2023-12-31,AAA,100,1000,resolved\n"
        "m1,M1,2024-05-15,2024-03-31,AAA,150,1800,resolved\n"
        "m1,M1,2024-08-15,2024-06-30,AAA,25,400,resolved\n"
    )
    out = tmp_path / "delta.csv"
    manifest = build_13f_deltas(holdings_path=holdings, out_path=out)
    assert manifest["delta_rows"] == 3
    text = out.read_text()
    assert "previous_shares" in text
    assert "50.0" in text
    assert "-125.0" in text


def test_fetch_historical_13f_holdings_uses_discovery_and_parser(monkeypatch, tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps([{"manager_id": "m1", "manager_name": "M1", "manager_cik": "1"}]))

    def fake_fetch_submissions(cik, headers=None):
        return {"filings": {"recent": {
            "form": ["13F-HR"],
            "accessionNumber": ["acc"],
            "filingDate": ["2024-02-14"],
            "reportDate": ["2023-12-31"],
            "primaryDocument": ["doc.xml"],
        }}}

    def fake_rows(manager, filing, cusip_ticker_map=None, headers=None):
        return [{"manager_id": manager["manager_id"], "filing_date": filing["filing_date"], "report_date": filing["report_date"], "ticker": "AAA", "shares": 10, "market_value": 1000}]

    monkeypatch.setattr("tradingagents.backtesting.thirteenf.history.fetch_submissions", fake_fetch_submissions)
    monkeypatch.setattr("tradingagents.backtesting.thirteenf.history.fetch_13f_holding_rows", fake_rows)

    out = tmp_path / "holdings.csv"
    manifest = fetch_historical_13f_holdings(manager_seed_path=seed, out_path=out, sleep_seconds=0)
    assert manifest["row_count"] == 1
    assert "AAA" in out.read_text()
