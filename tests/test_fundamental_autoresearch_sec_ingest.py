from tradingagents.research.fundamental_autoresearch.sec_ingest import (
    extract_companyfacts_units,
    extract_supported_filings,
)


def test_extract_supported_filings_parses_recent_10q_and_10k_rows():
    submissions_payload = {
        "cik": "0000320193",
        "filings": {
            "recent": {
                "form": ["10-Q", "8-K", "10-K"],
                "filingDate": ["2026-01-29", "2026-01-30", "2025-11-01"],
                "acceptanceDateTime": [
                    "2026-01-29T16:32:10Z",
                    "2026-01-30T22:32:10Z",
                    "2025-11-01T13:10:00Z",
                ],
                "reportDate": ["2025-12-27", "2026-01-30", "2025-09-27"],
                "accessionNumber": ["a", "b", "c"],
            }
        },
    }

    rows = extract_supported_filings(
        submissions_payload,
        ticker="AAPL",
        sector="Technology",
    )

    assert [row.filing_type for row in rows] == ["10-Q", "10-K"]
    assert rows[0].ticker == "AAPL"
    assert rows[0].cik == "0000320193"
    assert rows[0].period_end == "2025-12-27"
    assert rows[0].effective_market_date == "2026-01-30"
    assert rows[1].period_end == "2025-09-27"


def test_extract_supported_filings_ignores_unsupported_forms():
    submissions_payload = {
        "cik": "0000000001",
        "filings": {"recent": {"form": ["8-K"], "filingDate": ["2026-01-30"]}},
    }

    rows = extract_supported_filings(submissions_payload, ticker="TEST")

    assert rows == []


def test_extract_companyfacts_units_returns_requested_taxonomy():
    companyfacts_payload = {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {"USD": [{"end": "2025-12-27", "val": 124300000000}]}
                }
            }
        }
    }

    units = extract_companyfacts_units(companyfacts_payload)

    assert "RevenueFromContractWithCustomerExcludingAssessedTax" in units
    assert units["RevenueFromContractWithCustomerExcludingAssessedTax"]["USD"][0]["val"] == 124300000000
