from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

from src.config.cache_paths import sec_cache_root


ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = sec_cache_root()
DEFAULT_INPUT = ROOT / "Growth" / "earnings_8k_sec_parser" / "sec_document_quality_passed_2024Q3_revenue_buckets.csv"
DEFAULT_OUTPUT = ROOT / "Growth" / "earnings_8k_sec_parser" / "xbrl_universal_features_2024Q3.csv"
THROUGH_OPERATING_CASH_FLOW_OUTPUT = (
    ROOT / "Growth" / "earnings_8k_sec_parser" / "xbrl_universal_features_through_ocf_2024Q3.csv"
)

FIELD_GROUPS: dict[str, list[str]] = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "SalesRevenueServicesNet",
    ],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "assets": ["Assets"],
    "financing_cash_flow": ["NetCashProvidedByUsedInFinancingActivities"],
    "investing_cash_flow": ["NetCashProvidedByUsedInInvestingActivities"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "Cash",
    ],
    "equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "shares": [
        "EntityCommonStockSharesOutstanding",
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasic",
        "CommonStockSharesOutstanding",
    ],
    "eps": ["EarningsPerShareBasic", "EarningsPerShareDiluted"],
}

FIELD_SETS: dict[str, list[str]] = {
    "through_ocf": [
        "revenue",
        "net_income",
        "assets",
        "financing_cash_flow",
        "investing_cash_flow",
        "operating_cash_flow",
    ],
    "through_eps": list(FIELD_GROUPS),
}

FLOW_FIELDS = {
    "revenue",
    "net_income",
    "financing_cash_flow",
    "investing_cash_flow",
    "operating_cash_flow",
    "eps",
}

BALANCE_FIELDS = {"assets", "cash", "equity", "shares"}


def read_csv(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError):
        return None


def load_facts(ticker: str) -> dict[str, Any]:
    return json.loads((CACHE_DIR / f"facts_{ticker}.json").read_text(encoding="utf-8"))


def latest_fact(gaap: dict[str, Any], tags: list[str], asof: date, field_type: str) -> dict[str, Any]:
    best: dict[str, Any] = {}
    allowed_forms = {"10-Q", "10-K", "20-F", "6-K"}
    preferred_units = ["USD", "USD/shares", "shares"]
    for tag in tags:
        units = gaap.get(tag, {}).get("units", {})
        unit_items: list[tuple[str, list[dict[str, Any]]]] = []
        for unit in preferred_units:
            if unit in units:
                unit_items.append((unit, units[unit]))
        unit_items.extend((unit, items) for unit, items in units.items() if unit not in preferred_units)
        for unit, items in unit_items:
            for item in items:
                filed = parse_date(str(item.get("filed", "")))
                val = item.get("val")
                if filed is None or filed > asof or val is None:
                    continue
                if str(item.get("form", "")) not in allowed_forms:
                    continue
                # For balance sheet fields, prefer instant facts; for flows, allow duration facts.
                start = item.get("start")
                end = item.get("end", "")
                if field_type == "balance" and start:
                    continue
                if not end:
                    continue
                if not best or filed > best["filed_date"]:
                    best = {
                        "value": val,
                        "fact_name": tag,
                        "unit": unit,
                        "filed": filed.isoformat(),
                        "filed_date": filed,
                        "form": item.get("form", ""),
                        "period_start": start or "",
                        "period_end": end,
                    }
    if not best:
        return {}
    best.pop("filed_date", None)
    return best


def ratio(numerator: Any, denominator: Any) -> float | str:
    try:
        num = float(numerator)
        den = float(denominator)
    except (TypeError, ValueError):
        return ""
    if den == 0:
        return ""
    return round(num / den, 6)


def revenue_bucket(value: Any) -> str:
    try:
        revenue = float(value)
    except (TypeError, ValueError):
        return ""
    if revenue < 100_000_000:
        return "<$100M"
    if revenue < 500_000_000:
        return "$100M-$500M"
    if revenue < 1_000_000_000:
        return "$500M-$1B"
    if revenue < 2_000_000_000:
        return "$1B-$2B"
    if revenue < 10_000_000_000:
        return "$2B-$10B"
    return ">$10B"


def build_row(row: dict[str, str], asof: date, fields: list[str]) -> dict[str, Any]:
    ticker = row["ticker"]
    row_asof = parse_date(row.get("asof_date", "")) or asof
    facts = load_facts(ticker)
    gaap = facts.get("facts", {}).get("us-gaap", {})
    out: dict[str, Any] = {
        "quarter": row.get("quarter", ""),
        "asof_date": row_asof.isoformat(),
        "ticker": ticker,
        "cik": facts.get("cik", ""),
        "entity_name": facts.get("entityName", ""),
        "revenue_bucket": row.get("revenue_bucket", ""),
        "revenue_filter_keep_under_10b": row.get("revenue_filter_keep_under_10b", ""),
    }
    values: dict[str, Any] = {}
    missing: list[str] = []
    for field in fields:
        tags = FIELD_GROUPS[field]
        field_type = "balance" if field in BALANCE_FIELDS else "flow"
        fact = latest_fact(gaap, tags, row_asof, field_type)
        if not fact:
            missing.append(field)
            for suffix in ["value", "fact_name", "unit", "filed", "form", "period_end"]:
                out[f"{field}_{suffix}"] = ""
            continue
        values[field] = fact["value"]
        out[f"{field}_value"] = fact["value"]
        out[f"{field}_fact_name"] = fact["fact_name"]
        out[f"{field}_unit"] = fact["unit"]
        out[f"{field}_filed"] = fact["filed"]
        out[f"{field}_form"] = fact["form"]
        out[f"{field}_period_end"] = fact["period_end"]

    out["universal_feature_set"] = "through_ocf" if fields == FIELD_SETS["through_ocf"] else "through_eps"
    out["universal_feature_complete"] = str(not missing)
    # Backward-compatible name for old output consumers.
    out["universal_feature_complete_through_eps"] = str(not missing) if fields == FIELD_SETS["through_eps"] else ""
    out["missing_universal_features"] = ";".join(missing)
    out["net_income_margin"] = ratio(values.get("net_income"), values.get("revenue"))
    if not out["revenue_bucket"]:
        out["revenue_bucket"] = revenue_bucket(values.get("revenue"))
    out["operating_cash_flow_to_revenue"] = ratio(values.get("operating_cash_flow"), values.get("revenue"))
    out["assets_to_revenue"] = ratio(values.get("assets"), values.get("revenue"))
    out["financing_cash_flow_to_revenue"] = ratio(values.get("financing_cash_flow"), values.get("revenue"))
    out["investing_cash_flow_to_revenue"] = ratio(values.get("investing_cash_flow"), values.get("revenue"))
    if "cash" in fields:
        out["cash_to_revenue"] = ratio(values.get("cash"), values.get("revenue"))
    if "equity" in fields:
        out["equity_to_assets"] = ratio(values.get("equity"), values.get("assets"))
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build near-universal XBRL features through EPS")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--asof", default="2024-07-01")
    parser.add_argument("--field-set", choices=sorted(FIELD_SETS), default="through_eps")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asof = date.fromisoformat(args.asof)
    fields = FIELD_SETS[args.field_set]
    output = args.output or (THROUGH_OPERATING_CASH_FLOW_OUTPUT if args.field_set == "through_ocf" else DEFAULT_OUTPUT)
    rows = [build_row(row, asof, fields) for row in read_csv(args.input)]
    write_csv(output, rows)
    complete = sum(row["universal_feature_complete"] == "True" for row in rows)
    print(f"rows={len(rows)} field_set={args.field_set} complete={complete} missing={len(rows)-complete}")
    missing_counts: dict[str, int] = {}
    for row in rows:
        for field in str(row["missing_universal_features"]).split(";"):
            if field:
                missing_counts[field] = missing_counts.get(field, 0) + 1
    for field, count in sorted(missing_counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"{field}: {count}")
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
