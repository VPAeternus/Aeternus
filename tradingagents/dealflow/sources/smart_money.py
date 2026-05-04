"""Smart-money signal extraction from SEC 13F and Congress disclosures."""

from __future__ import annotations

import datetime as dt
import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import requests

from ..contracts import DealFlowSignal, UniverseRow

SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVE_INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/index.json"
SEC_ARCHIVE_FILE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{filename}"
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

DEFAULT_SEC_MANAGER_CIKS: Sequence[str] = (
    "1067983",  # Berkshire Hathaway
    "1350694",  # Bridgewater
    "1029160",  # Soros Fund Management
    "1603466",  # Scion Asset Management
)
DEFAULT_CONGRESS_SENATE_URL = (
    "https://raw.githubusercontent.com/timothycarambat/senate-stock-watcher-data/"
    "master/aggregate/all_transactions.json"
)


@dataclass
class _SmartMoneyMetric:
    score: float
    evidence_count: int
    freshness_hours: float
    direction: str


def collect_smart_money_signals(
    universe: Iterable[UniverseRow],
    as_of_date: Optional[str] = None,
    config: Optional[Dict] = None,
) -> List[DealFlowSignal]:
    rows = list(universe)
    cfg = config or {}
    as_of = _parse_as_of_date(as_of_date)

    symbols = {row["symbol"] for row in rows}
    sec_name_map = _build_universe_name_map(symbols, cfg)

    sec_metrics, sec_status = _collect_sec_13f_metrics(
        symbols=symbols,
        universe_name_map=sec_name_map,
        as_of=as_of,
        config=cfg,
    )
    congress_metrics, congress_status = _collect_congress_metrics(
        symbols=symbols,
        as_of=as_of,
        config=cfg,
    )

    signals: List[DealFlowSignal] = []
    for row in rows:
        symbol = row["symbol"]
        sec_metric = sec_metrics.get(symbol)
        congress_metric = congress_metrics.get(symbol)

        if sec_metric or congress_metric:
            metric = _combine_metrics(sec_metric, congress_metric)
            signals.append(
                {
                    "symbol": symbol,
                    "signal_family": "smart_money",
                    "raw_score": float(round(metric.score, 4)),
                    "z_score": 0.0,
                    "direction": metric.direction,
                    "evidence_count": int(metric.evidence_count),
                    "freshness_hours": float(round(metric.freshness_hours, 4)),
                    "source_status": "OK",
                    "source_name": "sec13f+congress",
                }
            )
            continue

        status = _derive_missing_status(sec_status, congress_status)
        signals.append(
            {
                "symbol": symbol,
                "signal_family": "smart_money",
                "raw_score": 0.0,
                "z_score": 0.0,
                "direction": "NEUTRAL",
                "evidence_count": 0,
                "freshness_hours": 9999.0,
                "source_status": status,
                "source_name": "sec13f+congress",
            }
        )

    return signals


def _collect_sec_13f_metrics(
    symbols: set[str],
    universe_name_map: Dict[str, List[str]],
    as_of: dt.date,
    config: Dict,
) -> Tuple[Dict[str, _SmartMoneyMetric], str]:
    manager_ciks = _manager_ciks(config)
    if not manager_ciks:
        return {}, "NOT_CONFIGURED"

    headers = _sec_headers(config)
    aggregates: Dict[str, Dict[str, object]] = {}
    successful_managers = 0
    request_failures = 0

    for cik in manager_ciks:
        try:
            submissions = _http_get_json(SEC_SUBMISSIONS_URL.format(cik=cik.zfill(10)), headers=headers)
            successful_managers += 1
        except Exception:
            request_failures += 1
            continue

        filing = _latest_13f_filing(submissions)
        if not filing:
            continue

        filing_date_str, accession = filing
        holdings = _load_13f_holdings(cik=cik, accession=accession, headers=headers)
        if not holdings:
            continue

        filing_date = _parse_iso_date(filing_date_str) or as_of
        for issuer_name, value_usd in holdings:
            symbol = _match_universe_symbol(issuer_name, universe_name_map)
            if not symbol or symbol not in symbols:
                continue

            bucket = aggregates.setdefault(
                symbol,
                {
                    "value_usd": 0.0,
                    "manager_set": set(),
                    "holding_count": 0,
                    "latest_date": filing_date,
                },
            )
            bucket["value_usd"] = float(bucket["value_usd"]) + float(value_usd)
            cast_manager_set = bucket["manager_set"]
            if isinstance(cast_manager_set, set):
                cast_manager_set.add(cik)
            bucket["holding_count"] = int(bucket["holding_count"]) + 1
            latest_date = bucket.get("latest_date")
            if isinstance(latest_date, dt.date):
                bucket["latest_date"] = max(latest_date, filing_date)

    if successful_managers == 0:
        return {}, "ERROR" if request_failures > 0 else "NO_DATA"

    if not aggregates:
        return {}, "NO_DATA"

    max_value = max(float(v.get("value_usd", 0.0)) for v in aggregates.values()) if aggregates else 0.0
    metrics: Dict[str, _SmartMoneyMetric] = {}
    for symbol, data in aggregates.items():
        value_usd = float(data.get("value_usd", 0.0))
        manager_set = data.get("manager_set")
        manager_count = len(manager_set) if isinstance(manager_set, set) else 0
        holding_count = int(data.get("holding_count", 0))
        latest_date = data.get("latest_date")
        latest_dt = latest_date if isinstance(latest_date, dt.date) else as_of

        value_component = 70.0 * (value_usd / max_value) if max_value > 0 else 0.0
        breadth_component = min(20.0, manager_count * 7.5)
        density_component = min(10.0, holding_count * 2.0)
        score = _clamp(value_component + breadth_component + density_component, 0.0, 100.0)

        freshness = _freshness_hours(as_of, latest_dt)
        evidence = max(1, manager_count + holding_count)
        metrics[symbol] = _SmartMoneyMetric(
            score=score,
            evidence_count=evidence,
            freshness_hours=freshness,
            direction=_direction_from_score(score),
        )

    return metrics, "OK"


def _collect_congress_metrics(
    symbols: set[str],
    as_of: dt.date,
    config: Dict,
) -> Tuple[Dict[str, _SmartMoneyMetric], str]:
    senate_url = _senate_url(config)
    lookback_days = int(config.get("dealflow_smart_money_lookback_days", 120))
    max_staleness_days = int(config.get("dealflow_congress_max_staleness_days", lookback_days))

    if not senate_url:
        return {}, "NOT_CONFIGURED"

    lower_bound = as_of - dt.timedelta(days=lookback_days)
    aggregates: Dict[str, Dict[str, object]] = {}
    seen_transactions: set[Tuple[str, str, str, str]] = set()
    successful_sources = 0
    had_non_error_source = False
    source_errors = 0

    senate_outcome = _load_congress_source(
        url=senate_url,
        as_of=as_of,
        lower_bound=lower_bound,
        max_staleness_days=max_staleness_days,
        symbols=symbols,
        aggregates=aggregates,
        seen_transactions=seen_transactions,
    )
    if senate_outcome == "OK":
        successful_sources += 1
        had_non_error_source = True
    elif senate_outcome in {"NO_DATA", "STALE"}:
        had_non_error_source = True
    elif senate_outcome == "ERROR":
        source_errors += 1

    if successful_sources == 0:
        if source_errors > 0 and not had_non_error_source:
            return {}, "ERROR"
        return {}, "NO_DATA"

    if not aggregates:
        return {}, "NO_DATA"

    metrics: Dict[str, _SmartMoneyMetric] = {}
    for symbol, data in aggregates.items():
        buy_usd = float(data.get("buy_usd", 0.0))
        sell_usd = float(data.get("sell_usd", 0.0))
        trade_count = int(data.get("trade_count", 0))
        latest_date = data.get("latest_date")
        latest_dt = latest_date if isinstance(latest_date, dt.date) else as_of

        gross = buy_usd + sell_usd
        bias = ((buy_usd - sell_usd) / gross) if gross > 0 else 0.0
        activity_component = min(25.0, math.log10(max(1.0, gross)) * 5.0)
        count_component = min(20.0, trade_count * 2.5)
        score = _clamp(50.0 + 20.0 * bias + activity_component + 0.3 * count_component, 0.0, 100.0)

        direction = "BULLISH" if bias > 0.1 else "BEARISH" if bias < -0.1 else _direction_from_score(score)
        freshness = _freshness_hours(as_of, latest_dt)
        evidence = max(1, trade_count)

        metrics[symbol] = _SmartMoneyMetric(
            score=score,
            evidence_count=evidence,
            freshness_hours=freshness,
            direction=direction,
        )

    return metrics, "OK"


def _combine_metrics(
    sec_metric: Optional[_SmartMoneyMetric],
    congress_metric: Optional[_SmartMoneyMetric],
) -> _SmartMoneyMetric:
    if sec_metric and not congress_metric:
        return sec_metric
    if congress_metric and not sec_metric:
        return congress_metric
    if not sec_metric and not congress_metric:
        return _SmartMoneyMetric(score=0.0, evidence_count=0, freshness_hours=9999.0, direction="NEUTRAL")

    sec = sec_metric if sec_metric else _SmartMoneyMetric(0.0, 0, 9999.0, "NEUTRAL")
    congress = congress_metric if congress_metric else _SmartMoneyMetric(0.0, 0, 9999.0, "NEUTRAL")

    score = _clamp(0.6 * sec.score + 0.4 * congress.score, 0.0, 100.0)
    evidence = int(sec.evidence_count + congress.evidence_count)
    freshness = min(sec.freshness_hours, congress.freshness_hours)
    return _SmartMoneyMetric(
        score=score,
        evidence_count=evidence,
        freshness_hours=freshness,
        direction=_direction_from_score(score),
    )


def _manager_ciks(config: Dict) -> List[str]:
    raw = config.get("dealflow_sec_manager_ciks", ",".join(DEFAULT_SEC_MANAGER_CIKS))
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",")]
    elif isinstance(raw, (list, tuple, set)):
        parts = [str(p).strip() for p in raw]
    else:
        parts = list(DEFAULT_SEC_MANAGER_CIKS)
    return [p for p in parts if p]


def _senate_url(config: Dict) -> str:
    return str(config.get("dealflow_congress_senate_url", DEFAULT_CONGRESS_SENATE_URL) or "").strip()


def _load_congress_source(
    url: str,
    as_of: dt.date,
    lower_bound: dt.date,
    max_staleness_days: int,
    symbols: set[str],
    aggregates: Dict[str, Dict[str, object]],
    seen_transactions: set[Tuple[str, str, str, str]],
) -> str:
    try:
        payload = _http_get_json(url, headers=None)
    except Exception:
        return "ERROR"

    rows = _payload_rows(payload)
    if not rows:
        return "NO_DATA"

    latest = _latest_trade_date(rows)
    if latest is not None and max_staleness_days >= 0:
        if (as_of - latest).days > max_staleness_days:
            return "STALE"

    accepted = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = _extract_row_symbol(row)
        if not symbol or symbol not in symbols:
            continue

        trade_date = _parse_congress_date(
            row.get("transaction_date")
            or row.get("transactionDate")
            or row.get("disclosure_date")
            or row.get("traded")
            or ""
        )
        if not trade_date or trade_date > as_of or trade_date < lower_bound:
            continue

        amount_mid = _parse_amount_midpoint(str(row.get("amount") or row.get("amount_range") or ""))
        if amount_mid <= 0.0:
            amount_mid = 10_000.0

        trade_type = str(row.get("type") or row.get("transaction_type") or "").lower()
        tx_key = _transaction_key(row=row, symbol=symbol, trade_date=trade_date, amount_mid=amount_mid, trade_type=trade_type)
        if tx_key in seen_transactions:
            continue
        seen_transactions.add(tx_key)

        is_buy = "purchase" in trade_type or "buy" in trade_type
        is_sell = "sale" in trade_type or "sell" in trade_type

        bucket = aggregates.setdefault(
            symbol,
            {
                "buy_usd": 0.0,
                "sell_usd": 0.0,
                "trade_count": 0,
                "latest_date": trade_date,
            },
        )
        if is_buy and not is_sell:
            bucket["buy_usd"] = float(bucket["buy_usd"]) + amount_mid
        elif is_sell and not is_buy:
            bucket["sell_usd"] = float(bucket["sell_usd"]) + amount_mid
        else:
            bucket["buy_usd"] = float(bucket["buy_usd"]) + 0.5 * amount_mid
            bucket["sell_usd"] = float(bucket["sell_usd"]) + 0.5 * amount_mid

        bucket["trade_count"] = int(bucket["trade_count"]) + 1
        latest_date = bucket.get("latest_date")
        if isinstance(latest_date, dt.date):
            bucket["latest_date"] = max(latest_date, trade_date)
        accepted += 1

    return "OK" if accepted > 0 else "NO_DATA"


def _payload_rows(payload: object) -> List[Dict]:
    if isinstance(payload, dict):
        rows = (
            payload.get("results")
            or payload.get("data")
            or payload.get("transactions")
            or payload.get("items")
            or payload.get("rows")
            or []
        )
        if isinstance(rows, list):
            return rows
        return []
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def _latest_trade_date(rows: List[Dict]) -> Optional[dt.date]:
    latest: Optional[dt.date] = None
    for row in rows:
        trade_date = _parse_congress_date(
            row.get("transaction_date")
            or row.get("transactionDate")
            or row.get("disclosure_date")
            or row.get("traded")
            or ""
        )
        if trade_date is None:
            continue
        if latest is None or trade_date > latest:
            latest = trade_date
    return latest


def _transaction_key(
    row: Dict,
    symbol: str,
    trade_date: dt.date,
    amount_mid: float,
    trade_type: str,
) -> Tuple[str, str, str, str]:
    tx_id = str(
        row.get("transaction_id")
        or row.get("id")
        or row.get("tx_id")
        or row.get("ptr_link")
        or row.get("url")
        or ""
    ).strip()
    if tx_id:
        return ("id", symbol, trade_date.isoformat(), tx_id)
    normalized_type = re.sub(r"\s+", " ", trade_type).strip()
    rounded_amount = f"{float(amount_mid):.2f}"
    return ("fp", symbol, trade_date.isoformat(), f"{normalized_type}:{rounded_amount}")


def _sec_headers(config: Dict) -> Dict[str, str]:
    user_agent = str(
        config.get("dealflow_sec_user_agent", "")
        or "AeternusAgentsAG/1.0 (research@aeternus.ai)"
    )
    return {
        "User-Agent": user_agent,
        "Accept": "application/json, text/plain, */*",
    }


def _latest_13f_filing(submissions: Dict) -> Optional[Tuple[str, str]]:
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    for idx, form in enumerate(forms):
        if str(form).upper() not in {"13F-HR", "13F-HR/A"}:
            continue
        if idx >= len(accessions):
            continue
        filing_date = filing_dates[idx] if idx < len(filing_dates) else ""
        accession = str(accessions[idx]).replace("-", "")
        if accession:
            return str(filing_date), accession
    return None


def _load_13f_holdings(cik: str, accession: str, headers: Dict[str, str]) -> List[Tuple[str, float]]:
    cik_numeric = str(int(cik))
    index_url = SEC_ARCHIVE_INDEX_URL.format(cik=cik_numeric, accession=accession)
    try:
        index_payload = _http_get_json(index_url, headers=headers)
    except Exception:
        return []

    items = index_payload.get("directory", {}).get("item", [])
    xml_files: List[str] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", ""))
        lower = name.lower()
        if not lower.endswith(".xml"):
            continue
        if lower.startswith("xsl") or "primary_doc" in lower or "filingsummary" in lower:
            continue
        xml_files.append(name)

    for filename in xml_files:
        url = SEC_ARCHIVE_FILE_URL.format(cik=cik_numeric, accession=accession, filename=filename)
        try:
            xml_text = _http_get_text(url, headers=headers)
        except Exception:
            continue
        holdings = _parse_info_table_xml(xml_text)
        if holdings:
            return holdings

    return []


def _parse_info_table_xml(xml_text: str) -> List[Tuple[str, float]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    holdings: List[Tuple[str, float]] = []
    for node in root.iter():
        if _strip_ns(node.tag) != "infoTable":
            continue
        issuer = _find_child_text(node, "nameOfIssuer")
        value_str = _find_child_text(node, "value")
        if not issuer or not value_str:
            continue
        try:
            value_usd = float(value_str.replace(",", "")) * 1000.0
        except ValueError:
            continue
        holdings.append((issuer, value_usd))
    return holdings


def _find_child_text(node: ET.Element, target: str) -> str:
    for child in node.iter():
        if _strip_ns(child.tag) == target and child.text:
            return child.text.strip()
    return ""


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _build_universe_name_map(symbols: set[str], config: Dict) -> Dict[str, List[str]]:
    company_titles = _load_sec_company_titles(config)
    name_map: Dict[str, List[str]] = {}
    for symbol in symbols:
        titles = company_titles.get(symbol, [])
        normalized = {_normalize_name(t) for t in titles if t}
        normalized.add(_normalize_name(symbol))
        name_map[symbol] = [n for n in normalized if n]
    return name_map


@lru_cache(maxsize=1)
def _cached_sec_company_titles(user_agent: str) -> Dict[str, List[str]]:
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/json, text/plain, */*",
    }
    payload = _http_get_json(SEC_COMPANY_TICKERS_URL, headers=headers)
    result: Dict[str, List[str]] = {}
    if isinstance(payload, dict):
        iterator = payload.values()
    elif isinstance(payload, list):
        iterator = payload
    else:
        iterator = []

    for row in iterator:
        if not isinstance(row, dict):
            continue
        ticker = _normalize_ticker(row.get("ticker", ""))
        title = str(row.get("title") or row.get("name") or "").strip()
        if not ticker or not title:
            continue
        result.setdefault(ticker, []).append(title)
    return result


def _load_sec_company_titles(config: Dict) -> Dict[str, List[str]]:
    user_agent = _sec_headers(config).get("User-Agent", "AeternusAgentsAG/1.0 (research@aeternus.ai)")
    try:
        return _cached_sec_company_titles(user_agent)
    except Exception:
        return {}


def _match_universe_symbol(issuer_name: str, universe_name_map: Dict[str, List[str]]) -> Optional[str]:
    issuer_norm = _normalize_name(issuer_name)
    if not issuer_norm:
        return None

    for symbol, names in universe_name_map.items():
        if issuer_norm in names:
            return symbol

    for symbol, names in universe_name_map.items():
        for name in names:
            if len(name) < 6 or len(issuer_norm) < 6:
                continue
            if issuer_norm.startswith(name) or name.startswith(issuer_norm):
                return symbol
    return None


def _derive_missing_status(sec_status: str, congress_status: str) -> str:
    if sec_status == "NOT_CONFIGURED" and congress_status == "NOT_CONFIGURED":
        return "NOT_CONFIGURED"
    if sec_status == "ERROR" and congress_status == "ERROR":
        return "ERROR"
    if "ERROR" in {sec_status, congress_status} and "OK" not in {sec_status, congress_status}:
        return "ERROR"
    return "NO_DATA"


def _http_get_json(url: str, headers: Optional[Dict[str, str]]) -> Dict:
    local_payload = _read_local_payload(url)
    if local_payload is not None:
        return local_payload
    response = requests.get(url, headers=headers, timeout=25)
    response.raise_for_status()
    return response.json()


def _http_get_text(url: str, headers: Optional[Dict[str, str]]) -> str:
    local_payload = _read_local_payload(url, expect_json=False)
    if isinstance(local_payload, str):
        return local_payload
    response = requests.get(url, headers=headers, timeout=25)
    response.raise_for_status()
    return response.text


def _read_local_payload(url: str, expect_json: bool = True):
    raw = str(url or "").strip()
    if not raw:
        return None
    if raw.startswith("http://") or raw.startswith("https://"):
        return None

    if raw.startswith("file://"):
        parsed = urlparse(raw)
        path = Path(parsed.path)
    else:
        path = Path(raw).expanduser()

    if not path.exists():
        return None

    data = path.read_text()
    if not expect_json:
        return data
    return json.loads(data)


def _normalize_name(name: str) -> str:
    txt = str(name or "").upper()
    txt = re.sub(r"[^A-Z0-9 ]+", " ", txt)
    txt = re.sub(
        r"\b(INC|INCORPORATED|CORP|CORPORATION|COMPANY|CO|PLC|LTD|LIMITED|HOLDINGS|HOLDING|CLASS A|CLASS B|THE)\b",
        " ",
        txt,
    )
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def _normalize_ticker(raw: str) -> str:
    txt = str(raw or "").upper().strip()
    txt = txt.replace("$", "")
    txt = re.sub(r"[^A-Z.\-]", "", txt)
    if not txt or txt in {"N/A", "NA", "--"}:
        return ""
    return txt


def _extract_row_symbol(row: Dict) -> str:
    ticker_fields = (
        row.get("ticker")
        or row.get("symbol")
        or row.get("asset_ticker")
        or row.get("security_ticker")
        or ""
    )
    symbol = _normalize_ticker(str(ticker_fields))
    if symbol:
        return symbol

    # Fallback extraction from asset descriptions.
    text = str(
        row.get("asset_name")
        or row.get("asset_description")
        or row.get("asset")
        or row.get("description")
        or ""
    )
    if not text:
        return ""

    candidates = re.findall(r"\$([A-Za-z]{1,6})", text)
    if not candidates:
        candidates = re.findall(r"\(([A-Za-z]{1,6})\)", text)
    for candidate in candidates:
        normalized = _normalize_ticker(candidate)
        if normalized:
            return normalized
    return ""


def _parse_amount_midpoint(amount_text: str) -> float:
    numbers = re.findall(r"\$?([0-9][0-9,]*)", amount_text)
    if not numbers:
        return 0.0
    values = [float(v.replace(",", "")) for v in numbers]
    if len(values) == 1:
        return values[0]
    return (values[0] + values[-1]) / 2.0


def _parse_congress_date(value: str) -> Optional[dt.date]:
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    if "T" in raw:
        try:
            return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def _parse_iso_date(value: str) -> Optional[dt.date]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return dt.datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_as_of_date(as_of_date: Optional[str]) -> dt.date:
    if as_of_date:
        parsed = _parse_iso_date(as_of_date)
        if parsed:
            return parsed
    return dt.datetime.now().date()


def _freshness_hours(as_of_date: dt.date, signal_date: dt.date) -> float:
    delta_days = (as_of_date - signal_date).days
    return max(0.0, float(delta_days * 24.0))


def _direction_from_score(score: float) -> str:
    if score >= 60.0:
        return "BULLISH"
    if score <= 40.0:
        return "BEARISH"
    return "NEUTRAL"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
