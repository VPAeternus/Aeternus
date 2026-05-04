import json
from pathlib import Path

from tradingagents.research.fundamental_autoresearch.features import build_feature_row
from tradingagents.research.fundamental_autoresearch.sec_ingest import (
    extract_companyfacts_units,
    extract_supported_filings,
)


def prepared_rows_artifact_path(run_name: str, *, cache_root: str | Path) -> Path:
    return Path(cache_root) / "prepared" / f"{run_name}.json"


def write_prepared_rows(rows: list[dict], *, cache_root: str | Path, run_name: str) -> Path:
    path = prepared_rows_artifact_path(run_name, cache_root=cache_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2, sort_keys=True))
    return path


def load_prepared_rows(path: str | Path) -> list[dict]:
    return json.loads(Path(path).read_text())


def _latest_unit_value(
    units: dict,
    unit_name: str,
    period_end: str,
    *,
    fiscal_year: int | None = None,
    fiscal_period: str | None = None,
):
    values = units.get(unit_name, [])
    for entry in values:
        if (
            fiscal_year is not None
            and fiscal_period is not None
            and entry.get("fy") == fiscal_year
            and entry.get("fp") == fiscal_period
        ):
            return entry.get("val")
    for entry in values:
        if entry.get("end") == period_end:
            return entry.get("val")
    return None


def _infer_fiscal_identity(companyfacts_units: dict, period_end: str) -> tuple[int | None, str | None]:
    for fact_units in companyfacts_units.values():
        for values in fact_units.values():
            for entry in values:
                if entry.get("end") == period_end:
                    return entry.get("fy"), entry.get("fp")
    return None, None


def _build_metrics_for_period(
    companyfacts_units: dict,
    period_end: str,
    *,
    fiscal_year: int | None = None,
    fiscal_period: str | None = None,
) -> dict[str, float | None]:
    operating_cashflow = _latest_unit_value(
        companyfacts_units.get("NetCashProvidedByUsedInOperatingActivities", {}),
        "USD",
        period_end,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
    )
    capex = _latest_unit_value(
        companyfacts_units.get("PaymentsToAcquirePropertyPlantAndEquipment", {}),
        "USD",
        period_end,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
    )
    free_cash_flow = None
    if operating_cashflow is not None and capex is not None:
        free_cash_flow = float(operating_cashflow) - abs(float(capex))

    return {
        "revenue": _latest_unit_value(
            companyfacts_units.get("RevenueFromContractWithCustomerExcludingAssessedTax", {}),
            "USD",
            period_end,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
        ),
        "gross_profit": _latest_unit_value(
            companyfacts_units.get("GrossProfit", {}),
            "USD",
            period_end,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
        ),
        "operating_income": _latest_unit_value(
            companyfacts_units.get("OperatingIncomeLoss", {}),
            "USD",
            period_end,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
        ),
        "free_cash_flow": free_cash_flow,
        "total_debt": _latest_unit_value(
            companyfacts_units.get("LongTermDebtAndFinanceLeaseObligations", {}),
            "USD",
            period_end,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
        ),
        "shareholder_equity": _latest_unit_value(
            companyfacts_units.get("StockholdersEquity", {}),
            "USD",
            period_end,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
        ),
        "current_assets": _latest_unit_value(
            companyfacts_units.get("AssetsCurrent", {}),
            "USD",
            period_end,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
        ),
        "current_liabilities": _latest_unit_value(
            companyfacts_units.get("LiabilitiesCurrent", {}),
            "USD",
            period_end,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
        ),
        "shares_outstanding": _latest_unit_value(
            companyfacts_units.get("CommonStocksIncludingAdditionalPaidInCapitalSharesOutstanding", {}),
            "shares",
            period_end,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
        ),
        "enterprise_value": None,
        "market_cap": None,
        "net_income": _latest_unit_value(
            companyfacts_units.get("NetIncomeLoss", {}),
            "USD",
            period_end,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
        ),
    }


def _load_submission_payloads_from_cache(
    *,
    cache_root: str | Path,
    ticker: str,
    include_history: bool,
) -> list[dict]:
    root = Path(cache_root)
    base_path = root / "submissions" / f"{ticker}.json"
    if not base_path.exists():
        return []

    payloads = [json.loads(base_path.read_text())]
    if not include_history:
        return payloads

    history_dir = root / "submissions_history" / ticker
    if not history_dir.exists():
        return payloads

    for history_path in sorted(history_dir.glob("*.json")):
        payloads.append(json.loads(history_path.read_text()))
    return payloads


def build_prepared_rows_from_cache(
    *,
    cache_root: str | Path,
    universe: list[str],
    sector_map: dict[str, str] | None = None,
    include_history: bool = False,
    latest_only: bool = True,
    start_year: int | None = None,
) -> list[dict]:
    sector_map = sector_map or {}
    root = Path(cache_root)
    companyfacts_dir = root / "companyfacts"
    prepared_rows: list[dict] = []

    for ticker in universe:
        companyfacts_path = companyfacts_dir / f"{ticker}.json"
        submission_payloads = _load_submission_payloads_from_cache(
            cache_root=root,
            ticker=ticker,
            include_history=include_history,
        )
        if not submission_payloads or not companyfacts_path.exists():
            continue

        companyfacts_payload = json.loads(companyfacts_path.read_text())
        filings = []
        for submissions_payload in submission_payloads:
            filings.extend(
                extract_supported_filings(
                    submissions_payload,
                    ticker=ticker,
                    sector=sector_map.get(ticker, "Unknown"),
                )
            )
        if not filings:
            continue

        companyfacts_units = extract_companyfacts_units(companyfacts_payload)
        filings.sort(key=lambda row: row.accepted_at, reverse=True)
        seen: set[tuple[str, str, str]] = set()

        for filing in filings:
            dedupe_key = (filing.filing_type, filing.accepted_at, filing.period_end)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            if start_year is not None and filing.fiscal_year < start_year:
                continue

            inferred_fiscal_year, inferred_fiscal_period = _infer_fiscal_identity(
                companyfacts_units,
                filing.period_end,
            )
            current_metrics = _build_metrics_for_period(
                companyfacts_units,
                filing.period_end,
                fiscal_year=inferred_fiscal_year or filing.fiscal_year,
                fiscal_period=inferred_fiscal_period or filing.fiscal_period,
            )
            previous_metrics = _build_metrics_for_period(
                companyfacts_units,
                filing.period_end,
                fiscal_year=(inferred_fiscal_year or filing.fiscal_year) - 1,
                fiscal_period=inferred_fiscal_period or filing.fiscal_period,
            )

            prepared_rows.append(
                build_feature_row(
                    filing,
                    current_metrics=current_metrics,
                    previous_metrics=previous_metrics,
                )
            )
            if latest_only:
                break

    return prepared_rows
