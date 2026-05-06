from tradingagents.backtesting.thirteenf.ingest import (
    discover_13f_filings,
    info_table_filenames,
    load_manager_seed,
    normalize_cik,
    parse_info_table_xml,
)


def test_normalize_cik_zero_pads():
    assert normalize_cik("1067983") == "0001067983"


def test_load_manager_seed_default_contains_curated_managers():
    managers = load_manager_seed()
    ids = {row["manager_id"] for row in managers}
    assert "berkshire_hathaway" in ids
    assert all(len(row["manager_cik"]) == 10 for row in managers)


def test_info_table_filenames_filters_primary_docs():
    payload = {"directory": {"item": [
        {"name": "primary_doc.xml"},
        {"name": "form13fInfoTable.xml"},
        {"name": "FilingSummary.xml"},
        {"name": "xslForm13F_X02.xml"},
    ]}}
    assert info_table_filenames(payload) == ["form13fInfoTable.xml"]


def test_parse_info_table_xml_normalizes_holdings_with_cusip_map():
    xml = '''<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
      <infoTable>
        <nameOfIssuer>APPLE INC</nameOfIssuer>
        <titleOfClass>COM</titleOfClass>
        <cusip>037833100</cusip>
        <value>123</value>
        <shrsOrPrnAmt><sshPrnamt>1000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
        <investmentDiscretion>SOLE</investmentDiscretion>
      </infoTable>
    </informationTable>'''
    rows = parse_info_table_xml(
        xml,
        manager={"manager_id": "m1", "manager_name": "M1", "manager_cik": "0000000001"},
        filing={"accession": "abc", "filing_date": "2024-02-14", "report_date": "2023-12-31"},
        cusip_ticker_map={"037833100": "AAPL"},
    )
    assert len(rows) == 1
    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["market_value"] == 123000.0
    assert rows[0]["shares"] == 1000.0
    assert rows[0]["ticker_status"] == "resolved"


def test_discover_13f_filings_from_submissions_payload():
    payload = {
        "filings": {
            "recent": {
                "form": ["10-K", "13F-HR", "13F-HR/A"],
                "accessionNumber": ["a", "b", "c"],
                "filingDate": ["2024-01-01", "2024-02-14", "2024-05-15"],
                "reportDate": ["2023-12-31", "2023-12-31", "2024-03-31"],
                "primaryDocument": ["a.htm", "b.htm", "c.htm"],
            }
        }
    }
    rows = discover_13f_filings(payload, manager={"manager_id": "m1", "manager_name": "M1", "manager_cik": "0000000001"})
    assert [row["form"] for row in rows] == ["13F-HR", "13F-HR/A"]
    assert rows[0]["accession"] == "b"
    assert rows[1]["report_date"] == "2024-03-31"
