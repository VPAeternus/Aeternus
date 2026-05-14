from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANY_TICKERS_EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_COMPANY_TICKERS_MF_URL = "https://www.sec.gov/files/company_tickers_mf.json"

IdentityLookup = Callable[[str], Mapping[str, Any] | None]


@dataclass(frozen=True)
class IdentityResolution:
    ticker: str
    sec_ticker: str
    yahoo_ticker: str
    symbol_alias_reason: str
    cik: str
    company_title: str
    identity_status: str
    rejection_reason: str

    def as_row(self) -> dict[str, str]:
        return {
            "ticker": self.ticker,
            "sec_ticker": self.sec_ticker,
            "yahoo_ticker": self.yahoo_ticker,
            "symbol_alias_reason": self.symbol_alias_reason,
            "cik": self.cik,
            "company_title": self.company_title,
            "identity_status": self.identity_status,
            "rejection_reason": self.rejection_reason,
        }


def resolve_ticker_identity(
    ticker: str,
    *,
    master_row: Mapping[str, Any] | None = None,
    local_sec_ticker_rows: Any = None,
    refreshed_sec_ticker_rows: Any = None,
    complete_panel_rows: Any = None,
    local_sec_facts: Mapping[str, Mapping[str, Any]] | None = None,
    sec_direct_lookup: IdentityLookup | None = None,
) -> IdentityResolution:
    canonical = _canonical_ticker(ticker)
    if not canonical:
        return _unresolved("", "ticker_or_name_unresolved", "empty_ticker")

    resolved = _resolve_from_row(master_row, canonical, status="resolved_from_master", source_label="master row")
    if resolved:
        return resolved

    resolved = _resolve_from_rows(local_sec_ticker_rows or [], canonical, status="resolved_from_sec_ticker_map", source_label="local SEC ticker map")
    if resolved:
        return resolved

    resolved = _resolve_from_rows(refreshed_sec_ticker_rows or [], canonical, status="resolved_from_refreshed_sec_ticker_map", source_label="refreshed official SEC ticker map")
    if resolved:
        return resolved

    resolved = _resolve_from_rows(complete_panel_rows or [], canonical, status="resolved_from_complete_panel", source_label="complete panel")
    if resolved:
        return resolved

    facts_row = (local_sec_facts or {}).get(canonical) or (local_sec_facts or {}).get(canonical.replace(".", "-"))
    if facts_row:
        resolved = _resolved_from_payload(canonical, facts_row, status="resolved_from_sec_facts", source_label="local SEC facts")
        if resolved:
            return resolved

    if sec_direct_lookup is not None:
        try:
            direct = sec_direct_lookup(canonical)
        except Exception as exc:  # noqa: BLE001 - identity lookup failure should reject one ticker, not crash the run.
            return _unresolved(canonical, "ticker_or_name_unresolved", f"SEC direct lookup failed: {exc}")
        if direct:
            resolved = _resolved_from_payload(canonical, direct, status="resolved_from_sec_direct", source_label="SEC direct lookup/search")
            if resolved:
                return resolved

    return _unresolved(canonical, "ticker_or_name_unresolved", "no local SEC identity match and SEC direct lookup returned nothing")


def _resolve_from_row(row: Mapping[str, Any] | None, canonical: str, *, status: str, source_label: str) -> IdentityResolution | None:
    if not row:
        return None
    row_ticker = _canonical_ticker(_clean_text(row.get("ticker") or row.get("symbol") or row.get("sec_ticker") or row.get("yahoo_ticker")))
    if row_ticker and row_ticker not in {_ticker_alias(canonical)}:
        return None
    return _resolved_from_payload(canonical, row, status=status, source_label=source_label)


def _resolve_from_rows(rows: Any, canonical: str, *, status: str, source_label: str) -> IdentityResolution | None:
    for row in load_sec_ticker_rows(rows):
        resolved = _resolve_from_row(row, canonical, status=status, source_label=source_label)
        if resolved:
            return resolved
    return None


def _resolved_from_payload(canonical: str, payload: Mapping[str, Any], *, status: str, source_label: str) -> IdentityResolution | None:
    negative_status = _clean_text(payload.get("identity_status"))
    if negative_status in {
        "no_sec_filer_found",
        "foreign_or_no_us_sec_filing",
        "fund_or_special_case",
        "ticker_or_name_unresolved",
    }:
        reason = _clean_text(payload.get("rejection_reason")) or _default_negative_reason(negative_status)
        return _unresolved(canonical, negative_status, reason)

    sec_ticker = _normalize_external_ticker(payload.get("sec_ticker") or payload.get("ticker") or payload.get("symbol") or canonical)
    yahoo_ticker = _normalize_external_ticker(payload.get("yahoo_ticker") or payload.get("ticker") or payload.get("symbol") or canonical)
    cik = _clean_text(payload.get("cik") or payload.get("cik_str"))
    company_title = _clean_text(
        payload.get("company_title")
        or payload.get("title")
        or payload.get("entityName")
        or payload.get("name")
    )
    if not cik or not company_title:
        return None
    alias_reason = _alias_reason(canonical, sec_ticker=sec_ticker, yahoo_ticker=yahoo_ticker, source_label=source_label)
    return _resolved(canonical, sec_ticker=sec_ticker, yahoo_ticker=yahoo_ticker, company_title=company_title, cik=cik, status=status, source_label=source_label, alias_reason=alias_reason)


def _resolved(
    canonical: str,
    *,
    sec_ticker: str,
    yahoo_ticker: str,
    company_title: str,
    cik: str,
    status: str,
    source_label: str,
    alias_reason: str | None = None,
) -> IdentityResolution:
    alias_reason = alias_reason or _alias_reason(canonical, sec_ticker=sec_ticker or canonical, yahoo_ticker=yahoo_ticker or canonical, source_label=source_label)
    return IdentityResolution(
        ticker=canonical,
        sec_ticker=sec_ticker or canonical,
        yahoo_ticker=yahoo_ticker or canonical,
        symbol_alias_reason=alias_reason,
        cik=cik,
        company_title=company_title,
        identity_status=status,
        rejection_reason="",
    )


def _unresolved(ticker: str, status: str, reason: str) -> IdentityResolution:
    return IdentityResolution(
        ticker=ticker,
        sec_ticker="",
        yahoo_ticker="",
        symbol_alias_reason="",
        cik="",
        company_title="",
        identity_status=status,
        rejection_reason=reason,
    )


def _default_negative_reason(status: str) -> str:
    return {
        "no_sec_filer_found": "no SEC filer found",
        "foreign_or_no_us_sec_filing": "foreign issuer or no US SEC filing",
        "fund_or_special_case": "fund or special case",
        "ticker_or_name_unresolved": "ticker or name unresolved",
    }.get(status, "identity unresolved")


def _alias_reason(canonical: str, *, sec_ticker: str, yahoo_ticker: str, source_label: str) -> str:
    aliases: list[str] = []
    if sec_ticker and sec_ticker != canonical:
        aliases.append(f"sec_ticker={sec_ticker}")
    if yahoo_ticker and yahoo_ticker != canonical and yahoo_ticker != sec_ticker:
        aliases.append(f"yahoo_ticker={yahoo_ticker}")
    if not aliases:
        return ""
    return f"{source_label}; " + ", ".join(aliases)


def _canonical_ticker(value: Any) -> str:
    return _clean_text(value).upper().replace(".", "-").replace("/", "-")


def _normalize_external_ticker(value: Any) -> str:
    return _clean_text(value).upper().replace(".", "-").replace("/", "-")


def _clean_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _ticker_alias(value: str) -> str:
    return value.replace(".", "-").replace("/", "-")


def load_sec_ticker_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("fields"), list) and isinstance(payload.get("data"), list):
        fields = [str(field or "").strip() for field in payload.get("fields", [])]
        rows: list[dict[str, Any]] = []
        for item in payload.get("data", []):
            if not isinstance(item, list) or len(item) != len(fields):
                continue
            row = {fields[idx]: item[idx] for idx in range(min(len(fields), len(item))) if fields[idx]}
            if isinstance(row, dict):
                rows.append(row)
        return rows
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        payload = payload["items"]
    if isinstance(payload, dict):
        rows = [row for row in payload.values() if isinstance(row, Mapping)]
        return [dict(row) for row in rows]
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, Mapping)]
    return []
