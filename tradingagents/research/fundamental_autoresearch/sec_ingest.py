from tradingagents.research.fundamental_autoresearch.contracts import FilingSnapshotRow
from tradingagents.research.fundamental_autoresearch.time_utils import compute_effective_market_date


_SUPPORTED_FORMS = {"10-Q", "10-K"}


def _infer_fiscal_period(filing_type: str, period_end: str) -> str:
    if filing_type == "10-K":
        return "FY"
    month = int(period_end[5:7]) if period_end and len(period_end) >= 7 else 0
    if month <= 3:
        return "Q1"
    if month <= 6:
        return "Q2"
    if month <= 9:
        return "Q3"
    return "Q4"


def extract_supported_filings(
    submissions_payload: dict,
    *,
    ticker: str,
    sector: str = "Unknown",
) -> list[FilingSnapshotRow]:
    recent = submissions_payload.get("filings", {}).get("recent", submissions_payload)
    forms = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    acceptance_times = recent.get("acceptanceDateTime", [])
    report_dates = recent.get("reportDate", [])

    rows: list[FilingSnapshotRow] = []
    for index, form in enumerate(forms):
        if form not in _SUPPORTED_FORMS:
            continue
        filed_at = filing_dates[index]
        accepted_at = acceptance_times[index] if index < len(acceptance_times) else f"{filed_at}T00:00:00Z"
        period_end = report_dates[index] if index < len(report_dates) else filed_at
        rows.append(
            FilingSnapshotRow(
                ticker=ticker,
                cik=str(submissions_payload.get("cik", "")),
                filing_type=form,
                period_end=period_end,
                filed_at=filed_at,
                accepted_at=accepted_at,
                effective_market_date=compute_effective_market_date(accepted_at),
                fiscal_period=_infer_fiscal_period(form, period_end),
                fiscal_year=int(period_end[:4]),
                sector=sector,
                data_coverage_score=0.0,
                missing_fields=[],
                source_flags=["sec_submissions"],
                restatement_suspect=False,
            )
        )
    return rows


def extract_companyfacts_units(
    companyfacts_payload: dict,
    *,
    taxonomy: str = "us-gaap",
) -> dict:
    facts = companyfacts_payload.get("facts", {}).get(taxonomy, {})
    return {fact_name: fact_payload.get("units", {}) for fact_name, fact_payload in facts.items()}
