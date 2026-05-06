from __future__ import annotations

from typing import Any

from src.features.common import to_float


REVENUE_BUCKETS = {"<$100M", "$100M-$500M", "$500M-$1B", "$1B-$2B", "$2B-$10B"}


def first_present(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] not in {None, ""}:
            return row[key]
    return ""


def ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in {None, 0}:
        return None
    return numerator / denominator


def score_profitability(net_income_margin: float | None) -> int | str:
    if net_income_margin is None:
        return ""
    if net_income_margin > 0.10:
        return 2
    if net_income_margin >= 0:
        return 1
    return -1


def score_ocf(ocf_margin: float | None) -> int | str:
    if ocf_margin is None:
        return ""
    if ocf_margin > 0.10:
        return 2
    if ocf_margin >= 0:
        return 1
    return -1


def score_fcf_proxy(fcf_proxy_margin: float | None) -> int | str:
    if fcf_proxy_margin is None:
        return ""
    if fcf_proxy_margin > 0.05:
        return 2
    if fcf_proxy_margin >= 0:
        return 1
    return -1


def score_financing_dependence(financing_dependence: float | None) -> int | str:
    if financing_dependence is None:
        return ""
    if financing_dependence <= 0:
        return 1
    if financing_dependence <= 0.10:
        return 0
    return -1


def score_asset_efficiency(asset_turnover: float | None) -> int | str:
    if asset_turnover is None:
        return ""
    if asset_turnover > 1.0:
        return 2
    if asset_turnover >= 0.5:
        return 1
    return 0


def bucket(total: int | None) -> str:
    if total is None:
        return "not_scored"
    if total >= 6:
        return "strong"
    if total >= 3:
        return "good"
    if total >= 0:
        return "mixed"
    return "weak"


def revenue_bucket_for(revenue: float | None) -> str:
    if revenue is None:
        return ""
    if revenue < 100_000_000:
        return "<$100M"
    if revenue < 500_000_000:
        return "$100M-$500M"
    if revenue < 1_000_000_000:
        return "$500M-$1B"
    if revenue < 2_000_000_000:
        return "$1B-$2B"
    if revenue <= 10_000_000_000:
        return "$2B-$10B"
    return ">$10B"


def build_pre_llm_score(row: dict[str, Any]) -> dict[str, Any]:
    revenue = to_float(first_present(row, "revenue_value", "revenue"))
    net_income = to_float(first_present(row, "net_income_value", "net_income"))
    assets = to_float(first_present(row, "assets_value", "assets"))
    financing_cf = to_float(first_present(row, "financing_cash_flow_value", "financing_cash_flow"))
    investing_cf = to_float(first_present(row, "investing_cash_flow_value", "investing_cash_flow"))
    operating_cf = to_float(first_present(row, "operating_cash_flow_value", "operating_cash_flow"))

    net_income_margin = ratio(net_income, revenue)
    ocf_margin = ratio(operating_cf, revenue)
    fcf_proxy = None if operating_cf is None or investing_cf is None else operating_cf + investing_cf
    fcf_proxy_margin = ratio(fcf_proxy, revenue)
    financing_dependence = ratio(max(financing_cf, 0) if financing_cf is not None else None, revenue)
    asset_turnover = ratio(revenue, assets)

    components = {
        "profitability_score": score_profitability(net_income_margin),
        "operating_cash_flow_score": score_ocf(ocf_margin),
        "fcf_proxy_score": score_fcf_proxy(fcf_proxy_margin),
        "financing_dependence_score": score_financing_dependence(financing_dependence),
        "asset_efficiency_score": score_asset_efficiency(asset_turnover),
    }
    missing = [key for key, value in components.items() if value == ""]
    total = None if missing else sum(int(value) for value in components.values())
    return {
        **components,
        "pre_llm_fundamental_score": "" if total is None else total,
        "pre_llm_fundamental_bucket": bucket(total),
        "pre_llm_fundamental_missing_fields": ";".join(missing),
    }


def build_pre_llm_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        score = build_pre_llm_score(row)
        output.append(
            {
                **row,
                "ticker": row.get("ticker", ""),
                "quarter": row.get("quarter", ""),
                "tradable_date": row.get("tradable_date", ""),
                "entry_open": row.get("entry_open", ""),
                "revenue_bucket": row.get("revenue_bucket", "") or revenue_bucket_for(to_float(first_present(row, "revenue_value", "revenue"))),
                **score,
                "missing_fields": score["pre_llm_fundamental_missing_fields"],
            }
        )
    return output
