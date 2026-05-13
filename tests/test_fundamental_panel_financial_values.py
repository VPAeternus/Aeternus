from datetime import date

from tradingagents.research.fundamental.src.panel.financial_values import fill_financial_values


def test_fill_financial_values_uses_gaap_and_ifrs_concepts():
    rows = [
        {"ticker": "AAA", "quarter": "2026Q2", "entry_open_date": "2026-05-12"},
        {"ticker": "NOK", "quarter": "2026Q2", "entry_open_date": "2026-05-12"},
    ]
    facts = {
        "AAA": {
            "facts": {"us-gaap": {
                "Revenues": {"units": {"USD": [{"form": "10-Q", "filed": "2026-05-01", "start": "2026-01-01", "end": "2026-03-31", "val": 100}]}},
                "NetIncomeLoss": {"units": {"USD": [{"form": "10-Q", "filed": "2026-05-01", "start": "2026-01-01", "end": "2026-03-31", "val": 10}]}},
                "Assets": {"units": {"USD": [{"form": "10-Q", "filed": "2026-05-01", "end": "2026-03-31", "val": 500}]}},
                "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [{"form": "10-Q", "filed": "2026-05-01", "start": "2026-01-01", "end": "2026-03-31", "val": 20}]}},
                "NetCashProvidedByUsedInInvestingActivities": {"units": {"USD": [{"form": "10-Q", "filed": "2026-05-01", "start": "2026-01-01", "end": "2026-03-31", "val": -5}]}},
                "NetCashProvidedByUsedInFinancingActivities": {"units": {"USD": [{"form": "10-Q", "filed": "2026-05-01", "start": "2026-01-01", "end": "2026-03-31", "val": -2}]}},
            }},
            "entityName": "AAA Inc",
            "cik": "1",
        },
        "NOK": {
            "facts": {"ifrs-full": {
                "Revenue": {"units": {"EUR": [{"form": "20-F", "filed": "2026-04-30", "start": "2026-01-01", "end": "2026-03-31", "val": 200}]}},
                "ProfitLoss": {"units": {"EUR": [{"form": "20-F", "filed": "2026-04-30", "start": "2026-01-01", "end": "2026-03-31", "val": 30}]}},
                "Assets": {"units": {"EUR": [{"form": "20-F", "filed": "2026-04-30", "end": "2026-03-31", "val": 800}]}},
                "CashFlowsFromUsedInOperatingActivities": {"units": {"EUR": [{"form": "20-F", "filed": "2026-04-30", "start": "2026-01-01", "end": "2026-03-31", "val": 40}]}},
                "CashFlowsFromUsedInInvestingActivities": {"units": {"EUR": [{"form": "20-F", "filed": "2026-04-30", "start": "2026-01-01", "end": "2026-03-31", "val": -15}]}},
                "CashFlowsFromUsedInFinancingActivities": {"units": {"EUR": [{"form": "20-F", "filed": "2026-04-30", "start": "2026-01-01", "end": "2026-03-31", "val": -3}]}},
            }},
            "entityName": "Nokia Corporation",
            "cik": "924613",
        },
    }

    out, summary = fill_financial_values(rows, facts_by_ticker=facts, as_of=date(2026, 5, 12))
    assert out[0]["revenue_value"] == "100"
    assert out[1]["revenue_value"] == "200"
    assert out[1]["financial_values_namespace"] == "ifrs-full"
    assert summary["rows_with_any_missing_financial_value"] == 0


def test_missing_financial_value_gets_reason_not_silent_blank():
    out, summary = fill_financial_values(
        [{"ticker": "CIFR", "quarter": "2022Q1", "entry_open_date": "2022-03-07"}],
        facts_by_ticker={"CIFR": {"facts": {"us-gaap": {}}}},
        as_of=date(2022, 3, 7),
    )
    assert out[0]["revenue_value"] == ""
    assert out[0]["revenue_value_missing_reason"] == "source_fact_unavailable_as_of"
    assert "revenue_value" in out[0]["financial_values_missing_fields"]
    assert summary["rows_with_any_missing_financial_value"] == 1


def test_relaxed_filed_date_fills_later_reported_comparative_facts():
    rows = [{"ticker": "LATE", "quarter": "2026Q2", "entry_open_date": "2026-04-15"}]
    facts = {
        "LATE": {
            "facts": {"us-gaap": {
                "Revenues": {"units": {"USD": [{"form": "10-Q", "filed": "2026-05-01", "start": "2026-01-01", "end": "2026-03-31", "val": 100}]}},
                "NetIncomeLoss": {"units": {"USD": [{"form": "10-Q", "filed": "2026-05-01", "start": "2026-01-01", "end": "2026-03-31", "val": 10}]}},
                "Assets": {"units": {"USD": [{"form": "10-Q", "filed": "2026-05-01", "end": "2026-03-31", "val": 500}]}},
                "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [{"form": "10-Q", "filed": "2026-05-01", "start": "2026-01-01", "end": "2026-03-31", "val": 20}]}},
                "NetCashProvidedByUsedInInvestingActivities": {"units": {"USD": [{"form": "10-Q", "filed": "2026-05-01", "start": "2026-01-01", "end": "2026-03-31", "val": -5}]}},
                "NetCashProvidedByUsedInFinancingActivities": {"units": {"USD": [{"form": "10-Q", "filed": "2026-05-01", "start": "2026-01-01", "end": "2026-03-31", "val": -2}]}},
            }},
        },
    }

    strict_out, strict_summary = fill_financial_values(
        rows,
        facts_by_ticker=facts,
        as_of=date(2026, 4, 15),
    )
    for field in (
        "revenue_value",
        "net_income_value",
        "assets_value",
        "operating_cash_flow_value",
        "investing_cash_flow_value",
        "financing_cash_flow_value",
    ):
        assert strict_out[0][field] == ""
        assert strict_out[0][f"{field}_missing_reason"] == "source_fact_unavailable_as_of"
    assert strict_summary["rows_with_any_missing_financial_value"] == 1

    relaxed_out, relaxed_summary = fill_financial_values(
        rows,
        facts_by_ticker=facts,
        as_of=date(2026, 4, 15),
        allow_relaxed_filed_date=True,
    )
    assert relaxed_out[0]["revenue_value"] == "100"
    assert relaxed_out[0]["net_income_value"] == "10"
    assert relaxed_out[0]["assets_value"] == "500"
    assert relaxed_out[0]["operating_cash_flow_value"] == "20"
    assert relaxed_out[0]["investing_cash_flow_value"] == "-5"
    assert relaxed_out[0]["financing_cash_flow_value"] == "-2"
    assert relaxed_out[0]["financial_values_source"] == "companyfacts_relaxed_filed_date"
    assert relaxed_summary["rows_with_relaxed_filed_date"] == 1
