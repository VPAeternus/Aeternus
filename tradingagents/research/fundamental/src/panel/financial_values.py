from __future__ import annotations

from datetime import date
from typing import Any


FINANCIAL_VALUE_FIELDS = (
    "revenue_value",
    "net_income_value",
    "assets_value",
    "operating_cash_flow_value",
    "investing_cash_flow_value",
    "financing_cash_flow_value",
)

MISSING_REASON_UNAVAILABLE_AS_OF = "source_fact_unavailable_as_of"

CONCEPTS_BY_NAMESPACE = {
    "us-gaap": {
        "revenue_value": (
            "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "SalesRevenueNet",
            "HomebuildingRevenue",
            "RevenueFromHomebuilding",
            "RevenuesFromHomebuilding",
            "HomebuildingAndLandSalesRevenue",
            "PremiumsEarnedNet",
            "InsurancePremiumsEarned",
            "PremiumsWrittenNet",
            "InsuranceRevenue",
            "RentalIncome",
            "OperatingLeasesIncomeStatementLeaseRevenue",
            "RealEstateRevenueNet",
            "InvestmentAdvisoryFees",
            "AssetManagementFees",
            "InvestmentManagementFees",
            "ManagementFees",
        ),
        "net_income_value": (
            "NetIncomeLoss",
            "ProfitLoss",
            "NetIncomeLossAvailableToCommonStockholdersBasic",
        ),
        "assets_value": ("Assets",),
        "operating_cash_flow_value": ("NetCashProvidedByUsedInOperatingActivities",),
        "investing_cash_flow_value": ("NetCashProvidedByUsedInInvestingActivities",),
        "financing_cash_flow_value": ("NetCashProvidedByUsedInFinancingActivities",),
    },
    "ifrs-full": {
        "revenue_value": (
            "Revenue",
            "RevenueFromContractsWithCustomers",
            "InsuranceRevenue",
            "InsuranceServiceRevenue",
            "RentalIncome",
            "InvestmentManagementFees",
            "ManagementFees",
        ),
        "net_income_value": (
            "ProfitLoss",
            "ProfitLossAttributableToOwnersOfParent",
            "ProfitLossFromContinuingOperations",
            "ProfitLossFromContinuingOperationsAttributableToOwnersOfParent",
        ),
        "assets_value": ("Assets",),
        "operating_cash_flow_value": ("CashFlowsFromUsedInOperatingActivities",),
        "investing_cash_flow_value": ("CashFlowsFromUsedInInvestingActivities",),
        "financing_cash_flow_value": ("CashFlowsFromUsedInFinancingActivities",),
    },
}


def fill_financial_values(
    rows: list[dict[str, Any]],
    *,
    facts_by_ticker: dict[str, dict[str, Any]],
    as_of: date,
    allow_relaxed_filed_date: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Fill canonical complete-panel financial values from companyfacts JSON."""
    out = []
    rows_with_missing = 0
    rows_with_relaxed = 0

    for row in rows:
        filled = dict(row)
        row_as_of = _row_as_of(row, default=as_of)
        ticker = str(row.get("ticker", ""))
        companyfacts = facts_by_ticker.get(ticker) or facts_by_ticker.get(ticker.upper(), {})
        selected: dict[str, _SelectedFact] = {}
        missing_fields = []
        used_relaxed = False

        for field in FINANCIAL_VALUE_FIELDS:
            fact = _select_fact(companyfacts, field, row_as_of, allow_relaxed=False)
            if fact is None and allow_relaxed_filed_date:
                fact = _select_fact(companyfacts, field, row_as_of, allow_relaxed=True)
                used_relaxed = fact is not None

            if fact is None:
                filled[field] = ""
                filled[f"{field}_missing_reason"] = MISSING_REASON_UNAVAILABLE_AS_OF
                missing_fields.append(field)
                continue

            selected[field] = fact
            filled[field] = _stringify_value(fact.value)
            filled[f"{field}_missing_reason"] = ""

        namespaces = sorted({fact.namespace for fact in selected.values()})
        concepts = [f"{field}:{fact.namespace}:{fact.concept}" for field, fact in selected.items()]
        filled["financial_values_source"] = (
            "companyfacts_relaxed_filed_date" if used_relaxed else "companyfacts"
        )
        filled["financial_values_namespace"] = ";".join(namespaces)
        filled["financial_values_concepts"] = ";".join(concepts)
        filled["financial_values_missing_fields"] = ",".join(missing_fields)

        if missing_fields:
            rows_with_missing += 1
        if used_relaxed:
            rows_with_relaxed += 1
        out.append(filled)

    summary = {
        "rows": len(out),
        "rows_with_any_missing_financial_value": rows_with_missing,
        "rows_with_relaxed_filed_date": rows_with_relaxed,
    }
    return out, summary


class _SelectedFact:
    def __init__(
        self,
        *,
        namespace: str,
        concept: str,
        unit: str,
        filed: str,
        end: str,
        value: Any,
    ) -> None:
        self.namespace = namespace
        self.concept = concept
        self.unit = unit
        self.filed = filed
        self.end = end
        self.value = value


def _select_fact(
    companyfacts: dict[str, Any],
    field: str,
    row_as_of: date,
    *,
    allow_relaxed: bool,
) -> _SelectedFact | None:
    candidates: list[_SelectedFact] = []
    facts = companyfacts.get("facts", {})

    for namespace, fields in CONCEPTS_BY_NAMESPACE.items():
        namespace_facts = facts.get(namespace, {})
        for concept in fields[field]:
            units = namespace_facts.get(concept, {}).get("units", {})
            for unit, values in units.items():
                for item in values:
                    fact = _candidate_fact(namespace, concept, unit, item, row_as_of, allow_relaxed)
                    if fact is not None:
                        candidates.append(fact)

    if not candidates:
        return None
    return max(candidates, key=_fact_sort_key)


def _candidate_fact(
    namespace: str,
    concept: str,
    unit: str,
    item: dict[str, Any],
    row_as_of: date,
    allow_relaxed: bool,
) -> _SelectedFact | None:
    if "val" not in item:
        return None

    filed = str(item.get("filed", ""))
    end = str(item.get("end", ""))
    filed_date = _parse_iso_date(filed)
    end_date = _parse_iso_date(end)
    if filed_date is None or end_date is None:
        return None
    if end_date > row_as_of:
        return None
    if allow_relaxed:
        if filed_date <= row_as_of:
            return None
    elif filed_date > row_as_of:
        return None

    return _SelectedFact(
        namespace=namespace,
        concept=concept,
        unit=unit,
        filed=filed,
        end=end,
        value=item["val"],
    )


def _fact_sort_key(fact: _SelectedFact) -> tuple[str, str, int]:
    namespace_rank = {"us-gaap": 1, "ifrs-full": 0}.get(fact.namespace, -1)
    return fact.end, fact.filed, namespace_rank


def _row_as_of(row: dict[str, Any], *, default: date) -> date:
    entry_open_date = row.get("entry_open_date")
    if entry_open_date:
        parsed = _parse_iso_date(str(entry_open_date))
        if parsed is not None:
            return parsed
    return default


def _parse_iso_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _stringify_value(value: Any) -> str:
    return str(value)
