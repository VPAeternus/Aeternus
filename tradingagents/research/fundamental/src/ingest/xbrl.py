from __future__ import annotations

from typing import Any


FACT_TAGS = {
    "revenue_value": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "net_income_value": ["NetIncomeLoss"],
    "assets_value": ["Assets"],
    "operating_cash_flow_value": ["NetCashProvidedByUsedInOperatingActivities"],
    "investing_cash_flow_value": ["NetCashProvidedByUsedInInvestingActivities"],
    "financing_cash_flow_value": ["NetCashProvidedByUsedInFinancingActivities"],
}


def latest_fact_value(companyfacts: dict[str, Any], tags: list[str], *, end: str | None = None) -> Any:
    facts = companyfacts.get("facts", {}).get("us-gaap", {})
    best = None
    for tag in tags:
        units = facts.get(tag, {}).get("units", {})
        for values in units.values():
            for item in values:
                if "val" not in item:
                    continue
                if end and str(item.get("end", "")) > end:
                    continue
                if best is None or str(item.get("end", "")) > str(best.get("end", "")):
                    best = item
    return "" if best is None else best.get("val", "")


def companyfacts_to_pre_llm_input(companyfacts: dict[str, Any], *, ticker: str, quarter: str, end: str | None = None) -> dict[str, Any]:
    row = {"ticker": ticker, "quarter": quarter}
    for field, tags in FACT_TAGS.items():
        row[field] = latest_fact_value(companyfacts, tags, end=end)
    return row
