from tradingagents.research.fundamental.src.ingest.companyfacts_pit import select_pit_financials


def _row(**overrides):
    row = {
        "ticker": "ABC",
        "quarter": "2022Q2",
        "periodic_accession": "0001193125-22-222222",
        "periodic_form": "10-Q",
        "target_period_end": "2022-06-30",
        "source_available_date": "2022-08-01",
        "financial_cutoff_date": "2022-08-01",
        "score_producing_flag": "1",
    }
    row.update(overrides)
    return row


def _facts(items_by_concept):
    concepts = {}
    for concept, units in items_by_concept.items():
        concepts[concept] = {"units": units}
    return {"facts": {"us-gaap": concepts}}


def _fact(**overrides):
    item = {
        "accn": "0001193125-22-222222",
        "form": "10-Q",
        "fy": 2022,
        "fp": "Q2",
        "start": "2022-01-01",
        "end": "2022-06-30",
        "filed": "2022-08-01",
        "val": 200,
    }
    item.update(overrides)
    return item


def test_selector_rejects_future_filed_fact():
    companyfacts = _facts(
        {
            "Revenues": {
                "USD": [
                    _fact(start="2022-04-01", filed="2022-08-15", val=999),
                    _fact(start="2022-04-01", filed="2022-07-20", val=100),
                ]
            }
        }
    )

    selected = select_pit_financials(
        companyfacts,
        _row(source_available_date="2022-08-01"),
        fields=["revenue_value"],
    )

    assert selected["revenue_value"] == 100
    assert selected["revenue_value_fact_filed"] == "2022-07-20"


def test_selector_requires_periodic_accession_for_score_rows():
    companyfacts = _facts(
        {
            "Revenues": {
                "USD": [
                    _fact(accn="0001193125-22-999999", filed="2022-07-20", val=100),
                ]
            }
        }
    )

    selected = select_pit_financials(companyfacts, _row(), fields=["revenue_value"])

    assert selected["revenue_value"] == ""
    assert selected["revenue_value_fact_missing_reason"] == "missing_exact_accession_fact"


def test_q2_ytd_minus_q1_ytd_derives_qtd_revenue():
    companyfacts = _facts(
        {
            "Revenues": {
                "USD": [
                    _fact(start="2022-01-01", end="2022-06-30", filed="2022-08-01", val=300),
                    _fact(start="2022-01-01", end="2022-03-31", filed="2022-05-01", val=100),
                ]
            }
        }
    )

    selected = select_pit_financials(companyfacts, _row(), fields=["revenue_value"])

    assert selected["revenue_value"] == 200
    assert selected["revenue_value_fact_period_type"] == "derived_qtd_from_ytd"
    assert selected["revenue_value_derivation_formula"] == "current_ytd_minus_prior_ytd"


def test_q2_ytd_minus_q1_ytd_derives_qtd_net_income():
    companyfacts = _facts(
        {
            "NetIncomeLoss": {
                "USD": [
                    _fact(start="2022-01-01", end="2022-06-30", filed="2022-08-01", val=75),
                    _fact(start="2022-01-01", end="2022-03-31", filed="2022-05-01", val=25),
                ]
            }
        }
    )

    selected = select_pit_financials(companyfacts, _row(), fields=["net_income_value"])

    assert selected["net_income_value"] == 50
    assert selected["net_income_value_fact_period_type"] == "derived_qtd_from_ytd"


def test_q4_annual_minus_q3_ytd_uses_target_year_not_comparative_year():
    companyfacts = _facts(
        {
            "Revenues": {
                "USD": [
                    _fact(
                        accn="0001193125-22-333333",
                        form="10-K",
                        fy=2021,
                        fp="FY",
                        start="2019-01-01",
                        end="2019-12-31",
                        filed="2022-02-24",
                        val=100,
                    ),
                    _fact(
                        accn="0001193125-22-333333",
                        form="10-K",
                        fy=2021,
                        fp="FY",
                        start="2020-01-01",
                        end="2020-12-31",
                        filed="2022-02-24",
                        val=200,
                    ),
                    _fact(
                        accn="0001193125-22-333333",
                        form="10-K",
                        fy=2021,
                        fp="FY",
                        start="2021-01-01",
                        end="2021-12-31",
                        filed="2022-02-24",
                        val=1000,
                    ),
                    _fact(
                        accn="0001193125-21-222222",
                        form="10-Q",
                        fy=2021,
                        fp="Q3",
                        start="2021-01-01",
                        end="2021-09-30",
                        filed="2021-11-04",
                        val=700,
                    ),
                ]
            }
        }
    )

    selected = select_pit_financials(
        companyfacts,
        _row(
            periodic_accession="0001193125-22-333333",
            periodic_form="10-K",
            target_period_end="2021-12-31",
            source_available_date="2022-02-24",
            financial_cutoff_date="2022-02-24",
        ),
        fields=["revenue_value"],
    )

    assert selected["revenue_value"] == 300
    assert selected["revenue_value_fact_period_type"] == "derived_qtd_from_ytd"


def test_instant_fact_uses_target_period_not_comparative_balance_sheet():
    companyfacts = _facts(
        {
            "Assets": {
                "USD": [
                    _fact(
                        accn="0001193125-22-333333",
                        form="10-K",
                        fy=2021,
                        fp="FY",
                        start="",
                        end="2021-01-02",
                        filed="2022-02-24",
                        val=900,
                    ),
                    _fact(
                        accn="0001193125-22-333333",
                        form="10-K",
                        fy=2021,
                        fp="FY",
                        start="",
                        end="2022-01-01",
                        filed="2022-02-24",
                        val=1200,
                    ),
                ]
            }
        }
    )

    selected = select_pit_financials(
        companyfacts,
        _row(
            periodic_accession="0001193125-22-333333",
            periodic_form="10-K",
            target_period_end="2022-01-01",
            source_available_date="2022-02-24",
            financial_cutoff_date="2022-02-24",
        ),
        fields=["assets_value"],
    )

    assert selected["assets_value"] == 1200
    assert selected["assets_value_fact_end"] == "2022-01-01"


def test_ytd_derivation_rejects_future_prior_ytd():
    companyfacts = _facts(
        {
            "NetIncomeLoss": {
                "USD": [
                    _fact(start="2022-01-01", end="2022-06-30", filed="2022-08-01", val=75),
                    _fact(start="2022-01-01", end="2022-03-31", filed="2022-09-01", val=25),
                ]
            }
        }
    )

    selected = select_pit_financials(companyfacts, _row(), fields=["net_income_value"])

    assert selected["net_income_value"] == ""
    assert selected["net_income_value_fact_missing_reason"] == "missing_prior_ytd_for_qtd_derivation"


def test_ytd_derivation_rejects_mixed_units():
    companyfacts = _facts(
        {
            "NetIncomeLoss": {
                "USD": [_fact(start="2022-01-01", end="2022-06-30", filed="2022-08-01", val=75)],
                "EUR": [_fact(start="2022-01-01", end="2022-03-31", filed="2022-05-01", val=25)],
            }
        }
    )

    selected = select_pit_financials(companyfacts, _row(), fields=["net_income_value"])

    assert selected["net_income_value"] == ""
    assert selected["net_income_value_fact_missing_reason"] == "missing_prior_ytd_for_qtd_derivation"


def test_selector_rejects_segment_revenue_when_consolidated_revenue_exists():
    companyfacts = _facts(
        {
            "Revenues": {
                "USD": [
                    _fact(start="2022-04-01", end="2022-06-30", filed="2022-08-01", val=40, segment="Cloud"),
                    _fact(start="2022-04-01", end="2022-06-30", filed="2022-08-01", val=100),
                ]
            }
        }
    )

    selected = select_pit_financials(companyfacts, _row(), fields=["revenue_value"])

    assert selected["revenue_value"] == 100
    assert selected["revenue_value_fact_is_consolidated"] == "1"


def test_selector_quarantines_segment_only_fact_for_score_field():
    companyfacts = _facts(
        {
            "Revenues": {
                "USD": [
                    _fact(start="2022-04-01", end="2022-06-30", filed="2022-08-01", val=40, dimensions={"Segment": "Cloud"}),
                ]
            }
        }
    )

    selected = select_pit_financials(companyfacts, _row(), fields=["revenue_value"])

    assert selected["revenue_value"] == ""
    assert selected["revenue_value_fact_missing_reason"] == "segment_only_fact_not_allowed"


def test_non_usd_revenue_does_not_assign_usd_bucket():
    companyfacts = _facts(
        {
            "Revenues": {
                "EUR": [
                    _fact(start="2022-04-01", end="2022-06-30", filed="2022-08-01", val=100),
                ]
            }
        }
    )

    selected = select_pit_financials(companyfacts, _row(), fields=["revenue_value"])

    assert selected["revenue_value"] == 100
    assert selected["financial_values_currency"] == "EUR"
    assert selected["revenue_bucket"] == ""
