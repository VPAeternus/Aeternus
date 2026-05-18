from tradingagents.research.fundamental.src.ingest.period_context import (
    derive_period_context,
    normalize_accession,
)


def _companyfacts_with_accession_fact():
    return {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "accn": "0001193125-22-123456",
                                "form": "10-Q",
                                "fy": 2022,
                                "fp": "Q1",
                                "start": "2021-11-01",
                                "end": "2022-01-31",
                                "filed": "2022-03-10",
                                "val": 1_000,
                            },
                            {
                                "accn": "0001193125-22-999999",
                                "form": "10-Q",
                                "fy": 2022,
                                "fp": "Q1",
                                "start": "2022-01-01",
                                "end": "2022-03-31",
                                "filed": "2022-05-01",
                                "val": 2_000,
                            },
                        ]
                    }
                }
            }
        }
    }


def test_accession_comparison_handles_dashed_and_undashed():
    assert normalize_accession("0001193125-22-123456") == "000119312522123456"
    assert normalize_accession(" 000119312522123456 ") == "000119312522123456"
    assert normalize_accession(None) == ""


def test_period_context_derived_from_accession_not_calendar_quarter():
    context = derive_period_context(
        _companyfacts_with_accession_fact(),
        periodic_accession="000119312522123456",
        periodic_form="10-Q",
        periodic_filing_date="2022-03-10",
    )

    assert context["fiscal_period_start"] == "2021-11-01"
    assert context["fiscal_period_end"] == "2022-01-31"
    assert context["target_period_end"] == "2022-01-31"
    assert context["fiscal_year"] == "2022"
    assert context["fiscal_period"] == "Q1"
    assert context["period_context_source"] == "companyfacts_accession"
    assert context["period_context_confidence"] == "high"
    assert context["period_context_missing_reason"] == ""
