from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from src.config.cache_paths import market_cache_root, sec_cache_root


ROOT = Path(__file__).resolve().parents[1]
AKG_PATH = Path("/Users/aeternusholdings/Documents/AeternusAgents-codex/eval_results/control/knowledge_graph.json")
SEC_CACHE_DIR = sec_cache_root()
MARKET_CACHE_DIR = market_cache_root()
DEFAULT_OUTPUT = ROOT / "Growth" / "earnings_8k_sec_parser" / "akg_quarter_viability.csv"

REVENUE_FACTS = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
    "SalesRevenueServicesNet",
]

ETF_SOURCE_TAGS = {"broad_etf", "sector_etf", "em_etf", "commodity_etf"}


def quarter_start(quarter: str) -> date:
    year = int(quarter[:4])
    q = int(quarter[-1])
    return date(year, (q - 1) * 3 + 1, 1)


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


def load_akg_nodes(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("nodes", {})


def is_common_stock_candidate(node: dict[str, Any]) -> tuple[bool, str]:
    if node.get("node_type") != "company":
        return False, "not_company_node"
    asset_class = str(node.get("asset_class") or "Equity")
    if asset_class != "Equity":
        return False, f"asset_class_{asset_class}"
    sources = set(node.get("metadata", {}).get("seed_sources", []) or [])
    if sources & ETF_SOURCE_TAGS:
        return False, "etf_or_proxy_seed_source"
    symbol = str(node.get("id", "")).upper().strip()
    if not symbol or any(token in symbol for token in ["-WT", "-WS", "-U", "-R"]):
        return False, "warrant_unit_right_like_symbol"
    return True, ""


def latest_revenue_fact(ticker: str, asof: date) -> dict[str, Any]:
    path = SEC_CACHE_DIR / f"facts_{ticker}.json"
    if not path.exists():
        return {"sec_facts_status": "missing_local_sec_facts_file"}
    try:
        facts = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"sec_facts_status": "sec_facts_unreadable"}
    cik = facts.get("cik", "")
    if not cik:
        return {"sec_facts_status": "sec_facts_no_cik"}
    gaap = facts.get("facts", {}).get("us-gaap", {})
    if not gaap:
        return {
            "sec_facts_status": "sec_facts_no_us_gaap",
            "cik": cik,
            "entity_name": facts.get("entityName", ""),
        }
    best: dict[str, Any] = {}
    for fact_name in REVENUE_FACTS:
        units = gaap.get(fact_name, {}).get("units", {}).get("USD", [])
        for item in units:
            filed = str(item.get("filed", ""))
            form = str(item.get("form", ""))
            if form not in {"10-Q", "10-K"} or not filed:
                continue
            try:
                filed_date = date.fromisoformat(filed[:10])
            except ValueError:
                continue
            if filed_date > asof:
                continue
            if not best or filed_date > date.fromisoformat(str(best["filed"])[:10]):
                best = {
                    "fact_name": fact_name,
                    "filed": filed,
                    "form": form,
                    "period_end": item.get("end", ""),
                    "value": item.get("val", ""),
                    "cik": facts.get("cik", ""),
                    "entity_name": facts.get("entityName", ""),
                }
    if best:
        best["sec_facts_status"] = "ok"
        return best
    return {
        "sec_facts_status": "missing_required_revenue_fact_before_asof",
        "cik": cik,
        "entity_name": facts.get("entityName", ""),
    }


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
            needed = [field for field in ["Open", "High", "Low", "Close", "Volume"] if field in fields]
            if {"Close", "Volume"} - set(needed):
                continue
            panels[ticker] = frame[ticker][needed].copy()
    return panels


def price_viability(panel: pd.DataFrame | None, asof: date) -> dict[str, Any]:
    if panel is None or panel.empty:
        return {"has_price": False}
    frame = panel.copy()
    frame.index = pd.to_datetime(frame.index)
    frame = frame[frame.index.date <= asof]
    frame = frame.dropna(subset=["Close", "Volume"])
    if frame.empty:
        return {"has_price": False}
    frame = frame.tail(80).copy()
    last = frame.iloc[-1]
    frame["dollar_volume"] = pd.to_numeric(frame["Close"], errors="coerce") * pd.to_numeric(frame["Volume"], errors="coerce")
    return {
        "has_price": True,
        "price_date": frame.index[-1].date().isoformat(),
        "raw_close": float(last["Close"]),
        "avg_dollar_volume_60d": float(frame["dollar_volume"].tail(60).mean()),
    }


def build_rows(quarter: str, min_close: float, min_adv: float, low_liquidity_adv: float) -> list[dict[str, Any]]:
    asof = quarter_start(quarter)
    nodes = load_akg_nodes(AKG_PATH)
    prices = load_price_panels()
    rows: list[dict[str, Any]] = []
    for symbol, node in sorted(nodes.items()):
        symbol = symbol.upper()
        common_ok, common_reason = is_common_stock_candidate(node)
        revenue = latest_revenue_fact(symbol, asof) if common_ok else {}
        pv = price_viability(prices.get(symbol), asof) if common_ok else {"has_price": False}

        reasons: list[str] = []
        if not common_ok:
            reasons.append(common_reason)
        sec_facts_status = revenue.get("sec_facts_status", "") if common_ok else ""
        if common_ok and sec_facts_status and sec_facts_status != "ok":
            reasons.append(sec_facts_status)
        if common_ok and not pv.get("has_price"):
            reasons.append("missing_raw_yahoo_price")
        if pv.get("has_price") and float(pv.get("raw_close", 0)) < min_close:
            reasons.append("raw_close_below_floor")
        if pv.get("has_price") and float(pv.get("avg_dollar_volume_60d", 0)) < min_adv:
            reasons.append("adv_60d_below_hard_floor")

        included = not reasons
        liquidity_flag = ""
        if included and float(pv.get("avg_dollar_volume_60d", 0)) < low_liquidity_adv:
            liquidity_flag = "low_liquidity_keep"

        rows.append({
            "quarter": quarter,
            "asof_date": asof.isoformat(),
            "ticker": symbol,
            "included": str(included),
            "filter_reason": ";".join(reasons) if reasons else "included",
            "liquidity_flag": liquidity_flag,
            "asset_class": node.get("asset_class", ""),
            "sector_gics": node.get("sector_gics", ""),
            "seed_sources": ";".join(node.get("metadata", {}).get("seed_sources", []) or []),
            "sec_facts_status": sec_facts_status,
            "cik": revenue.get("cik", ""),
            "revenue_fact_name": revenue.get("fact_name", ""),
            "revenue_filed": revenue.get("filed", ""),
            "revenue_form": revenue.get("form", ""),
            "revenue_period_end": revenue.get("period_end", ""),
            "revenue_value": revenue.get("value", ""),
            "price_date": pv.get("price_date", ""),
            "raw_close": pv.get("raw_close", ""),
            "avg_dollar_volume_60d": pv.get("avg_dollar_volume_60d", ""),
        })
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AKG first-stage quarterly viability tester")
    parser.add_argument("--quarter", default="2024Q3")
    parser.add_argument("--min-close", type=float, default=2.0)
    parser.add_argument("--min-adv", type=float, default=500_000.0)
    parser.add_argument("--low-liquidity-adv", type=float, default=2_000_000.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = build_rows(args.quarter, args.min_close, args.min_adv, args.low_liquidity_adv)
    write_csv(args.output, rows)
    included = [row for row in rows if row["included"] == "True"]
    low_liq = [row for row in included if row.get("liquidity_flag")]
    reasons: dict[str, int] = {}
    for row in rows:
        if row["included"] == "True":
            continue
        for reason in str(row["filter_reason"]).split(";"):
            reasons[reason] = reasons.get(reason, 0) + 1
    print(f"quarter={args.quarter} total={len(rows)} included={len(included)} excluded={len(rows)-len(included)} low_liquidity_kept={len(low_liq)}")
    for reason, count in sorted(reasons.items(), key=lambda item: (-item[1], item[0]))[:12]:
        print(f"{reason}: {count}")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
