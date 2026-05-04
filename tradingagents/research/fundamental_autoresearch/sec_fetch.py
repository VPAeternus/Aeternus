import json
from pathlib import Path
from typing import Callable


_SEC_BASE = "https://data.sec.gov"
_SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


def submissions_cache_path(ticker: str, *, cache_root: str | Path) -> Path:
    return Path(cache_root) / "submissions" / f"{ticker}.json"


def companyfacts_cache_path(ticker: str, *, cache_root: str | Path) -> Path:
    return Path(cache_root) / "companyfacts" / f"{ticker}.json"


def company_tickers_cache_path(*, cache_root: str | Path) -> Path:
    return Path(cache_root) / "company_tickers.json"


def submissions_history_cache_path(ticker: str, file_name: str, *, cache_root: str | Path) -> Path:
    return Path(cache_root) / "submissions_history" / f"{ticker}" / file_name


def _write_cached_payload(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return path


def _sec_get(url: str, *, session, user_agent: str, timeout: int = 30) -> dict:
    response = session.get(url, headers={"User-Agent": user_agent}, timeout=timeout)
    if response.status_code != 200:
        raise RuntimeError(f"SEC fetch failed: {response.status_code} for {url}")
    return response.json()


def fetch_submissions_payload(cik: str, *, session, user_agent: str, timeout: int = 30) -> dict:
    padded_cik = str(cik).zfill(10)
    url = f"{_SEC_BASE}/submissions/CIK{padded_cik}.json"
    return _sec_get(url, session=session, user_agent=user_agent, timeout=timeout)


def fetch_companyfacts_payload(cik: str, *, session, user_agent: str, timeout: int = 30) -> dict:
    padded_cik = str(cik).zfill(10)
    url = f"{_SEC_BASE}/api/xbrl/companyfacts/CIK{padded_cik}.json"
    return _sec_get(url, session=session, user_agent=user_agent, timeout=timeout)


def fetch_company_tickers_payload(*, session, user_agent: str, timeout: int = 30) -> dict:
    return _sec_get(_SEC_COMPANY_TICKERS_URL, session=session, user_agent=user_agent, timeout=timeout)


def fetch_submissions_history_payload(file_name: str, *, session, user_agent: str, timeout: int = 30) -> dict:
    url = f"{_SEC_BASE}/submissions/{file_name}"
    return _sec_get(url, session=session, user_agent=user_agent, timeout=timeout)


def cache_submissions_payload(ticker: str, payload: dict, *, cache_root: str | Path) -> Path:
    path = submissions_cache_path(ticker, cache_root=cache_root)
    return _write_cached_payload(path, payload)


def cache_companyfacts_payload(ticker: str, payload: dict, *, cache_root: str | Path) -> Path:
    path = companyfacts_cache_path(ticker, cache_root=cache_root)
    return _write_cached_payload(path, payload)


def cache_company_tickers_payload(payload: dict, *, cache_root: str | Path) -> Path:
    path = company_tickers_cache_path(cache_root=cache_root)
    return _write_cached_payload(path, payload)


def cache_submissions_history_payload(
    ticker: str,
    file_name: str,
    payload: dict,
    *,
    cache_root: str | Path,
) -> Path:
    path = submissions_history_cache_path(ticker, file_name, cache_root=cache_root)
    return _write_cached_payload(path, payload)


def load_company_tickers_payload(*, cache_root: str | Path) -> dict:
    return json.loads(company_tickers_cache_path(cache_root=cache_root).read_text())


def _ticker_aliases(ticker: str) -> set[str]:
    upper = ticker.upper()
    return {
        upper,
        upper.replace(".", "-"),
        upper.replace("-", "."),
    }


def resolve_ticker_cik_map(
    tickers: list[str],
    *,
    cache_root: str | Path,
    session,
    user_agent: str,
    timeout: int = 30,
) -> dict[str, str]:
    try:
        payload = fetch_company_tickers_payload(session=session, user_agent=user_agent, timeout=timeout)
        cache_company_tickers_payload(payload, cache_root=cache_root)
    except Exception:
        cache_path = company_tickers_cache_path(cache_root=cache_root)
        if not cache_path.exists():
            raise RuntimeError("Unable to resolve ticker-to-CIK map from live or cached SEC data")
        payload = load_company_tickers_payload(cache_root=cache_root)

    alias_to_cik: dict[str, str] = {}
    for entry in payload.values():
        ticker = str(entry.get("ticker", "")).upper().strip()
        cik_raw = entry.get("cik_str", entry.get("cik", ""))
        if not ticker or not cik_raw:
            continue
        padded_cik = str(cik_raw).zfill(10)
        for alias in _ticker_aliases(ticker):
            alias_to_cik[alias] = padded_cik

    resolved: dict[str, str] = {}
    for ticker in tickers:
        for alias in _ticker_aliases(ticker):
            cik = alias_to_cik.get(alias)
            if cik:
                resolved[ticker.upper()] = cik
                break

    return resolved


def fill_sec_cache_for_universe(
    universe: list[str],
    *,
    ticker_to_cik: dict[str, str],
    cache_root: str | Path,
    session,
    user_agent: str,
    continue_on_error: bool = True,
    fetch_submissions: Callable[..., dict] = fetch_submissions_payload,
    fetch_companyfacts: Callable[..., dict] = fetch_companyfacts_payload,
    fetch_submissions_history: Callable[..., dict] = fetch_submissions_history_payload,
    include_history: bool = False,
    timeout: int = 30,
) -> dict[str, list[str]]:
    summary = {
        "cached": [],
        "skipped_missing_cik": [],
        "failed": [],
    }

    for ticker in universe:
        cik = ticker_to_cik.get(ticker)
        if not cik:
            if continue_on_error:
                summary["skipped_missing_cik"].append(ticker)
                continue
            raise RuntimeError(f"Missing CIK mapping for {ticker}")

        try:
            submissions_payload = fetch_submissions(
                cik,
                session=session,
                user_agent=user_agent,
                timeout=timeout,
            )
            companyfacts_payload = fetch_companyfacts(
                cik,
                session=session,
                user_agent=user_agent,
                timeout=timeout,
            )
            cache_submissions_payload(ticker, submissions_payload, cache_root=cache_root)
            cache_companyfacts_payload(ticker, companyfacts_payload, cache_root=cache_root)
            if include_history:
                for history_file in submissions_payload.get("filings", {}).get("files", []):
                    file_name = history_file.get("name")
                    if not file_name:
                        continue
                    historical_payload = fetch_submissions_history(
                        file_name,
                        session=session,
                        user_agent=user_agent,
                        timeout=timeout,
                    )
                    cache_submissions_history_payload(
                        ticker,
                        file_name,
                        historical_payload,
                        cache_root=cache_root,
                    )
            summary["cached"].append(ticker)
        except Exception:
            if continue_on_error:
                summary["failed"].append(ticker)
                continue
            raise

    return summary
