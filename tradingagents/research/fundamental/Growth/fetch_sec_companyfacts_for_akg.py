from __future__ import annotations

import argparse
import csv
import gzip
import json
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.config.cache_paths import sec_cache_root


ROOT = Path(__file__).resolve().parents[1]
AKG_PATH = Path("/Users/aeternusholdings/Documents/AeternusAgents-codex/eval_results/control/knowledge_graph.json")
CACHE_DIR = sec_cache_root()
COMPANY_TICKERS_CACHE = CACHE_DIR / "sec_company_tickers.json"
DEFAULT_OUTPUT = ROOT / "Growth" / "earnings_8k_sec_parser" / "sec_companyfacts_fetch_report.csv"

SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"
USER_AGENT = "AeternusAutoResearch/1.0 contact@aeternus.local"
ETF_SOURCE_TAGS = {"broad_etf", "sector_etf", "em_etf", "commodity_etf"}


def request_json(url: str, *, timeout: int = 30) -> dict[str, Any]:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"})
    with urlopen(req, timeout=timeout) as response:
        payload = response.read()
        if response.headers.get("Content-Encoding", "").lower() == "gzip" or payload[:2] == b"\x1f\x8b":
            payload = gzip.decompress(payload)
        return json.loads(payload.decode("utf-8"))


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


def is_common_stock_candidate(node: dict[str, Any]) -> bool:
    if node.get("node_type") != "company":
        return False
    if str(node.get("asset_class") or "Equity") != "Equity":
        return False
    sources = set(node.get("metadata", {}).get("seed_sources", []) or [])
    if sources & ETF_SOURCE_TAGS:
        return False
    symbol = str(node.get("id", "")).upper().strip()
    if not symbol or any(token in symbol for token in ["-WT", "-WS", "-U", "-R"]):
        return False
    return True


def load_company_ticker_map(refresh: bool) -> dict[str, dict[str, Any]]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if refresh or not COMPANY_TICKERS_CACHE.exists():
        data = request_json(SEC_TICKER_URL)
        COMPANY_TICKERS_CACHE.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    else:
        data = json.loads(COMPANY_TICKERS_CACHE.read_text(encoding="utf-8"))
    by_ticker: dict[str, dict[str, Any]] = {}
    for row in data.values():
        ticker = str(row.get("ticker", "")).upper().replace(".", "-")
        if not ticker:
            continue
        by_ticker[ticker] = row
    return by_ticker


def candidate_tickers(limit: int | None = None) -> list[str]:
    nodes = load_akg_nodes(AKG_PATH)
    tickers = [
        str(node.get("id", "")).upper().strip()
        for node in nodes.values()
        if is_common_stock_candidate(node)
    ]
    tickers = sorted(ticker for ticker in tickers if ticker)
    if limit is not None:
        return tickers[:limit]
    return tickers


def fetch_facts_for_tickers(
    tickers: list[str],
    ticker_map: dict[str, dict[str, Any]],
    *,
    sleep_seconds: float,
    force: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, ticker in enumerate(tickers, start=1):
        out_path = CACHE_DIR / f"facts_{ticker}.json"
        sec_row = ticker_map.get(ticker)
        row: dict[str, Any] = {
            "ticker": ticker,
            "status": "",
            "cik": "",
            "company_title": "",
            "output_path": str(out_path),
        }
        if out_path.exists() and not force:
            row["status"] = "already_cached"
            rows.append(row)
            continue
        if not sec_row:
            row["status"] = "no_sec_ticker_match"
            rows.append(row)
            continue
        cik = str(sec_row.get("cik_str", "")).strip()
        if not cik:
            row["status"] = "no_cik_in_sec_map"
            rows.append(row)
            continue
        cik10 = cik.zfill(10)
        row["cik"] = cik
        row["company_title"] = sec_row.get("title", "")
        try:
            facts = request_json(SEC_FACTS_URL.format(cik10=cik10))
            out_path.write_text(json.dumps(facts, sort_keys=True), encoding="utf-8")
            row["status"] = "fetched"
        except HTTPError as exc:
            row["status"] = f"http_{exc.code}"
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            row["status"] = f"error_{type(exc).__name__}"
        rows.append(row)
        print(f"{index}/{len(tickers)} {ticker} {row['status']}", flush=True)
        time.sleep(sleep_seconds)
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch SEC companyfacts JSON for AKG common-stock candidates")
    parser.add_argument("--refresh-ticker-map", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--sleep", type=float, default=0.12)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ticker_map = load_company_ticker_map(refresh=args.refresh_ticker_map)
    tickers = candidate_tickers(limit=args.limit)
    rows = fetch_facts_for_tickers(tickers, ticker_map, sleep_seconds=args.sleep, force=args.force)
    write_csv(args.output, rows)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print(f"tickers={len(rows)} wrote={args.output}")
    for status, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"{status}: {count}")


if __name__ == "__main__":
    main()
