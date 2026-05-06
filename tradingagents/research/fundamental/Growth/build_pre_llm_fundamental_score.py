from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

import pandas as pd

from src.config.cache_paths import market_cache_root


ROOT = Path(__file__).resolve().parents[1]
MARKET_CACHE_DIR = market_cache_root()
DEFAULT_XBRL = ROOT / "Growth" / "earnings_8k_sec_parser" / "xbrl_universal_features_through_ocf_2024Q3_100m_plus_index_mandatory.csv"
DEFAULT_RETURNS = ROOT / "Growth" / "earnings_8k_sec_parser" / "no_llm_earnings_score_2024Q3.csv"
DEFAULT_EVENTS = ROOT / "Growth" / "earnings_8k_sec_parser" / "filing_coverage_audit_2024Q3.csv"
DEFAULT_OUTPUT = ROOT / "Growth" / "earnings_8k_sec_parser" / "pre_llm_fundamental_score_2024Q3.csv"
RETURN_HORIZONS = [10, 20, 30, 60, 90]
TIER_0_REVENUE_BUCKETS = {"<$100M", "$100M-$500M", "$500M-$1B", "$1B-$2B", "$2B-$10B"}
TIER_1_REVENUE_BUCKETS = TIER_0_REVENUE_BUCKETS
TIER_2_REVENUE_BUCKETS = TIER_0_REVENUE_BUCKETS
TIER_3_REVENUE_BUCKETS = TIER_0_REVENUE_BUCKETS
TIER_4_REVENUE_BUCKETS = TIER_0_REVENUE_BUCKETS


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


def to_float(value: Any) -> float | None:
    try:
        if value in {"", None}:
            return None
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


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


def tier_bucket(row: dict[str, Any], returns: dict[str, str]) -> str:
    entry_open = to_float(returns.get("entry_open"))
    if (
        entry_open is not None
        and entry_open < 25
        and row.get("revenue_bucket", "") in TIER_0_REVENUE_BUCKETS
        and row.get("pre_llm_fundamental_bucket", "") != "not_scored"
    ):
        return "Tier 0 - Broad right-tail scouting universe"
    return ""


def tier_1_bucket(row: dict[str, Any], returns: dict[str, str]) -> str:
    entry_open = to_float(returns.get("entry_open"))
    if (
        row.get("pre_llm_fundamental_bucket", "") != "not_scored"
        and entry_open is not None
        and entry_open < 15
        and row.get("revenue_bucket", "") in TIER_1_REVENUE_BUCKETS
    ):
        return "Tier 1 - Balanced priority feed"
    return ""


def tier_2_bucket(row: dict[str, Any], returns: dict[str, str]) -> str:
    entry_open = to_float(returns.get("entry_open"))
    if (
        row.get("pre_llm_fundamental_bucket", "") != "not_scored"
        and entry_open is not None
        and entry_open < 10
        and row.get("revenue_bucket", "") in TIER_2_REVENUE_BUCKETS
    ):
        return "Tier 2 - High-priority compact feed"
    return ""


def tier_3_bucket(row: dict[str, Any], returns: dict[str, str]) -> str:
    entry_open = to_float(returns.get("entry_open"))
    score = to_float(row.get("pre_llm_fundamental_score"))
    if (
        row.get("pre_llm_fundamental_bucket", "") != "not_scored"
        and entry_open is not None
        and entry_open < 15
        and row.get("revenue_bucket", "") in TIER_3_REVENUE_BUCKETS
        and score is not None
        and score <= 0
    ):
        return "Tier 3 - Revised dislocation feed"
    return ""


def tier_4_bucket(row: dict[str, Any], returns: dict[str, str]) -> str:
    entry_open = to_float(returns.get("entry_open"))
    if (
        row.get("pre_llm_fundamental_bucket", "") != "not_scored"
        and entry_open is not None
        and entry_open < 5
        and row.get("revenue_bucket", "") in TIER_4_REVENUE_BUCKETS
    ):
        return "Tier 4 - Ultra-distressed tag, not a production tier"
    return ""


def load_price_panels() -> dict[str, pd.DataFrame]:
    panels: dict[str, pd.DataFrame] = {}
    for path in sorted(MARKET_CACHE_DIR.glob("prices*.parquet")):
        try:
            frame = pd.read_parquet(path)
        except Exception:
            continue
        if not isinstance(frame.columns, pd.MultiIndex):
            continue
        for ticker in sorted(set(frame.columns.get_level_values(0))):
            if ticker in panels:
                continue
            fields = [field for sym, field in frame.columns if sym == ticker]
            if not {"Open", "Close"}.issubset(fields):
                continue
            panel = frame[ticker][["Open", "Close"]].copy()
            panel.index = pd.to_datetime(panel.index)
            if panel.index.tz is not None:
                panel.index = panel.index.tz_localize(None)
            panels[ticker] = panel
    return panels


def return_fields(panel: pd.DataFrame | None, filed: str) -> dict[str, str]:
    fields = {"tradable_date": "", "entry_open": ""}
    for horizon in RETURN_HORIZONS:
        fields[f"return_{horizon}d_pct"] = ""
    if panel is None or panel.empty or not filed:
        return fields
    frame = panel.dropna(subset=["Open", "Close"]).sort_index()
    target = pd.Timestamp(filed) + pd.Timedelta(days=1)
    entry_rows = frame[frame.index.normalize() >= target.normalize()]
    if entry_rows.empty:
        return fields
    entry_open = float(entry_rows.iloc[0]["Open"])
    fields["tradable_date"] = entry_rows.index[0].strftime("%Y-%m-%d")
    fields["entry_open"] = f"{entry_open:.6f}"
    for horizon in RETURN_HORIZONS:
        exit_target = entry_rows.index[0] + pd.Timedelta(days=horizon)
        exit_rows = frame[frame.index.normalize() >= exit_target.normalize()]
        if exit_rows.empty:
            continue
        exit_close = float(exit_rows.iloc[0]["Close"])
        fields[f"return_{horizon}d_pct"] = f"{((exit_close / entry_open) - 1) * 100:.4f}"
    return fields


def build_score(row: dict[str, str]) -> dict[str, Any]:
    revenue = to_float(row.get("revenue_value"))
    net_income = to_float(row.get("net_income_value"))
    assets = to_float(row.get("assets_value"))
    financing_cf = to_float(row.get("financing_cash_flow_value"))
    investing_cf = to_float(row.get("investing_cash_flow_value"))
    operating_cf = to_float(row.get("operating_cash_flow_value"))

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
        "pre_llm_fundamental_score": total if total is not None else "",
        "pre_llm_fundamental_bucket": bucket(total),
        "pre_llm_fundamental_missing_fields": ";".join(missing),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build pre-LLM fundamental score from universal XBRL fields")
    parser.add_argument("--xbrl", type=Path, default=DEFAULT_XBRL)
    parser.add_argument("--returns", type=Path, default=DEFAULT_RETURNS)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    xbrl_rows = {row["ticker"]: row for row in read_csv(args.xbrl)}
    return_rows = {row["ticker"]: row for row in read_csv(args.returns)}
    event_rows = {row["ticker"]: row for row in read_csv(args.events)} if args.events.exists() else {}
    prices = load_price_panels()
    rows: list[dict[str, Any]] = []
    for ticker, row in sorted(xbrl_rows.items()):
        returns = return_rows.get(ticker, {})
        if not returns.get("return_90d_pct"):
            event_date = (event_rows.get(ticker, {}).get("event_dates", "").split(";") or [""])[0]
            returns = return_fields(prices.get(ticker), event_date)
        score = build_score(row)
        tier = tier_bucket({**row, **score}, returns)
        tier_1 = tier_1_bucket({**row, **score}, returns)
        tier_2 = tier_2_bucket({**row, **score}, returns)
        tier_3 = tier_3_bucket({**row, **score}, returns)
        tier_4 = tier_4_bucket({**row, **score}, returns)
        rows.append({
            "quarter": row.get("quarter", ""),
            "ticker": ticker,
            "revenue_bucket": row.get("revenue_bucket", ""),
            **score,
            "tier_bucket": tier,
            "tier_1_bucket": tier_1,
            "tier_2_bucket": tier_2,
            "tier_3_bucket": tier_3,
            "tier_4_bucket": tier_4,
            "tradable_date": returns.get("tradable_date", ""),
            "entry_open": returns.get("entry_open", ""),
            "return_10d_pct": returns.get("return_10d_pct", ""),
            "return_20d_pct": returns.get("return_20d_pct", ""),
            "return_30d_pct": returns.get("return_30d_pct", ""),
            "return_60d_pct": returns.get("return_60d_pct", ""),
            "return_90d_pct": returns.get("return_90d_pct", ""),
        })
    write_csv(args.output, rows)
    scored = sum(row["pre_llm_fundamental_bucket"] != "not_scored" for row in rows)
    print(f"rows={len(rows)} scored={scored} not_scored={len(rows)-scored}")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
