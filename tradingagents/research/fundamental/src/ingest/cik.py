from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from ..config.cache_paths import sec_cache_root


SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
USER_AGENT = "AeternusAgentsFundamental/1.0 contact@aeternus.local"
COMPANY_TICKERS_CACHE = sec_cache_root() / "sec_company_tickers.json"


@dataclass(frozen=True)
class CikResolution:
    ticker: str
    cik: str
    company_title: str
    status: str


def _request_json(url: str, *, timeout: int = 30) -> dict[str, Any]:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"})
    with urlopen(req, timeout=timeout) as response:
        payload = response.read()
        if response.headers.get("Content-Encoding", "").lower() == "gzip" or payload[:2] == b"\x1f\x8b":
            payload = gzip.decompress(payload)
        return json.loads(payload.decode("utf-8"))


def load_company_ticker_map(*, refresh: bool = False) -> dict[str, dict[str, Any]]:
    COMPANY_TICKERS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    if refresh or not COMPANY_TICKERS_CACHE.exists():
        data = _request_json(SEC_TICKER_URL)
        COMPANY_TICKERS_CACHE.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    else:
        data = json.loads(COMPANY_TICKERS_CACHE.read_text(encoding="utf-8"))

    by_ticker: dict[str, dict[str, Any]] = {}
    for row in data.values():
        ticker = str(row.get("ticker", "")).upper().replace(".", "-").strip()
        if ticker:
            by_ticker[ticker] = row
    return by_ticker


def resolve_cik_for_ticker(ticker: str, *, refresh: bool = False) -> CikResolution:
    symbol = str(ticker or "").upper().replace(".", "-").strip()
    if not symbol:
        return CikResolution(ticker="", cik="", company_title="", status="missing_ticker")
    row = load_company_ticker_map(refresh=refresh).get(symbol)
    if not row:
        return CikResolution(ticker=symbol, cik="", company_title="", status="no_sec_ticker_match")
    cik = str(row.get("cik_str", "")).strip()
    if not cik:
        return CikResolution(ticker=symbol, cik="", company_title=str(row.get("title", "")), status="no_cik_in_sec_map")
    return CikResolution(ticker=symbol, cik=cik, company_title=str(row.get("title", "")), status="resolved")


def resolve_ciks_for_tickers(tickers: list[str], *, refresh: bool = False) -> list[CikResolution]:
    ticker_map = load_company_ticker_map(refresh=refresh)
    out: list[CikResolution] = []
    for ticker in tickers:
        symbol = str(ticker or "").upper().replace(".", "-").strip()
        if not symbol:
            out.append(CikResolution(ticker="", cik="", company_title="", status="missing_ticker"))
            continue
        row = ticker_map.get(symbol)
        if not row:
            out.append(CikResolution(ticker=symbol, cik="", company_title="", status="no_sec_ticker_match"))
            continue
        cik = str(row.get("cik_str", "")).strip()
        out.append(
            CikResolution(
                ticker=symbol,
                cik=cik,
                company_title=str(row.get("title", "")),
                status="resolved" if cik else "no_cik_in_sec_map",
            )
        )
    return out
