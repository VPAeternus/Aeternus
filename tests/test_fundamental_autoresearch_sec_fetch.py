import json
from pathlib import Path

import pytest

from tradingagents.research.fundamental_autoresearch.sec_fetch import (
    cache_companyfacts_payload,
    cache_company_tickers_payload,
    cache_submissions_history_payload,
    cache_submissions_payload,
    company_tickers_cache_path,
    companyfacts_cache_path,
    fill_sec_cache_for_universe,
    fetch_company_tickers_payload,
    fetch_companyfacts_payload,
    fetch_submissions_history_payload,
    load_company_tickers_payload,
    resolve_ticker_cik_map,
    fetch_submissions_payload,
    submissions_history_cache_path,
    submissions_cache_path,
)


def test_submissions_cache_path_is_deterministic():
    path = submissions_cache_path("AAPL", cache_root="tmp/sec")

    assert path == Path("tmp/sec") / "submissions" / "AAPL.json"


def test_companyfacts_cache_path_is_deterministic():
    path = companyfacts_cache_path("AAPL", cache_root="tmp/sec")

    assert path == Path("tmp/sec") / "companyfacts" / "AAPL.json"


def test_company_tickers_cache_path_is_deterministic():
    path = company_tickers_cache_path(cache_root="tmp/sec")

    assert path == Path("tmp/sec") / "company_tickers.json"


def test_submissions_history_cache_path_is_deterministic():
    path = submissions_history_cache_path(
        "AAPL",
        "CIK0000320193-submissions-001.json",
        cache_root="tmp/sec",
    )

    assert path == Path("tmp/sec") / "submissions_history" / "AAPL" / "CIK0000320193-submissions-001.json"


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, response: _FakeResponse):
        self.response = response
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        return self.response


def test_fetch_submissions_payload_uses_sec_user_agent_header():
    session = _FakeSession(_FakeResponse(200, {"ok": True}))

    payload = fetch_submissions_payload("0000320193", session=session, user_agent="Aeternus test@test.com")

    assert payload == {"ok": True}
    assert "submissions/CIK0000320193.json" in session.calls[0]["url"]
    assert session.calls[0]["headers"]["User-Agent"] == "Aeternus test@test.com"


def test_fetch_companyfacts_payload_uses_sec_user_agent_header():
    session = _FakeSession(_FakeResponse(200, {"ok": True}))

    payload = fetch_companyfacts_payload("0000320193", session=session, user_agent="Aeternus test@test.com")

    assert payload == {"ok": True}
    assert "companyfacts/CIK0000320193.json" in session.calls[0]["url"]
    assert session.calls[0]["headers"]["User-Agent"] == "Aeternus test@test.com"


def test_fetch_submissions_history_payload_uses_sec_user_agent_header():
    session = _FakeSession(_FakeResponse(200, {"accessionNumber": ["a"]}))

    payload = fetch_submissions_history_payload(
        "CIK0000320193-submissions-001.json",
        session=session,
        user_agent="Aeternus test@test.com",
    )

    assert payload == {"accessionNumber": ["a"]}
    assert "submissions/CIK0000320193-submissions-001.json" in session.calls[0]["url"]
    assert session.calls[0]["headers"]["User-Agent"] == "Aeternus test@test.com"


def test_fetch_company_tickers_payload_uses_sec_user_agent_header():
    session = _FakeSession(_FakeResponse(200, {"0": {"ticker": "AAPL", "cik_str": 320193}}))

    payload = fetch_company_tickers_payload(session=session, user_agent="Aeternus test@test.com")

    assert payload["0"]["ticker"] == "AAPL"
    assert "company_tickers.json" in session.calls[0]["url"]
    assert session.calls[0]["headers"]["User-Agent"] == "Aeternus test@test.com"


def test_fetch_submissions_payload_raises_on_non_200():
    session = _FakeSession(_FakeResponse(429, {"error": "rate_limited"}))

    with pytest.raises(RuntimeError, match="SEC fetch failed"):
        fetch_submissions_payload("0000320193", session=session, user_agent="Aeternus test@test.com")


def test_cache_submissions_payload_writes_json(tmp_path):
    payload = {"cik": "0000320193", "name": "Apple Inc."}

    path = cache_submissions_payload("AAPL", payload, cache_root=tmp_path)

    assert path == tmp_path / "submissions" / "AAPL.json"
    assert json.loads(path.read_text()) == payload


def test_cache_companyfacts_payload_writes_json(tmp_path):
    payload = {"facts": {"us-gaap": {}}}

    path = cache_companyfacts_payload("AAPL", payload, cache_root=tmp_path)

    assert path == tmp_path / "companyfacts" / "AAPL.json"
    assert json.loads(path.read_text()) == payload


def test_cache_submissions_history_payload_writes_json(tmp_path):
    payload = {"accessionNumber": ["a"]}

    path = cache_submissions_history_payload(
        "AAPL",
        "CIK0000320193-submissions-001.json",
        payload,
        cache_root=tmp_path,
    )

    assert path == tmp_path / "submissions_history" / "AAPL" / "CIK0000320193-submissions-001.json"
    assert json.loads(path.read_text()) == payload


def test_cache_company_tickers_payload_writes_and_loads_json(tmp_path):
    payload = {"0": {"ticker": "AAPL", "cik_str": 320193}}

    path = cache_company_tickers_payload(payload, cache_root=tmp_path)

    assert path == tmp_path / "company_tickers.json"
    assert load_company_tickers_payload(cache_root=tmp_path) == payload


def test_fill_sec_cache_for_universe_caches_multiple_symbols(tmp_path):
    def _fetch_submissions(cik, **kwargs):
        return {"cik": cik, "kind": "submissions"}

    def _fetch_companyfacts(cik, **kwargs):
        return {"cik": cik, "kind": "companyfacts"}

    summary = fill_sec_cache_for_universe(
        ["AAPL", "MSFT"],
        ticker_to_cik={"AAPL": "0000320193", "MSFT": "0000789019"},
        cache_root=tmp_path,
        session=object(),
        user_agent="Aeternus test@test.com",
        fetch_submissions=_fetch_submissions,
        fetch_companyfacts=_fetch_companyfacts,
    )

    assert summary["cached"] == ["AAPL", "MSFT"]
    assert summary["skipped_missing_cik"] == []
    assert summary["failed"] == []
    assert json.loads((tmp_path / "submissions" / "AAPL.json").read_text())["kind"] == "submissions"
    assert json.loads((tmp_path / "companyfacts" / "MSFT.json").read_text())["kind"] == "companyfacts"


def test_fill_sec_cache_for_universe_skips_missing_cik_when_allowed(tmp_path):
    summary = fill_sec_cache_for_universe(
        ["AAPL", "MSFT"],
        ticker_to_cik={"AAPL": "0000320193"},
        cache_root=tmp_path,
        session=object(),
        user_agent="Aeternus test@test.com",
        fetch_submissions=lambda cik, **kwargs: {"cik": cik},
        fetch_companyfacts=lambda cik, **kwargs: {"cik": cik},
        continue_on_error=True,
    )

    assert summary["cached"] == ["AAPL"]
    assert summary["skipped_missing_cik"] == ["MSFT"]
    assert summary["failed"] == []


def test_fill_sec_cache_for_universe_raises_on_fetch_failure_when_not_allowed(tmp_path):
    def _fetch_submissions(cik, **kwargs):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        fill_sec_cache_for_universe(
            ["AAPL"],
            ticker_to_cik={"AAPL": "0000320193"},
            cache_root=tmp_path,
            session=object(),
            user_agent="Aeternus test@test.com",
            fetch_submissions=_fetch_submissions,
            fetch_companyfacts=lambda cik, **kwargs: {"cik": cik},
            continue_on_error=False,
        )


def test_fill_sec_cache_for_universe_caches_historical_submission_files_when_enabled(tmp_path):
    def _fetch_submissions(cik, **kwargs):
        return {
            "cik": cik,
            "filings": {
                "recent": {"form": [], "filingDate": [], "acceptanceDateTime": [], "reportDate": []},
                "files": [{"name": "CIK0000320193-submissions-001.json"}],
            },
        }

    def _fetch_companyfacts(cik, **kwargs):
        return {"cik": cik, "kind": "companyfacts"}

    def _fetch_history(file_name, **kwargs):
        assert file_name == "CIK0000320193-submissions-001.json"
        return {"accessionNumber": ["a"]}

    summary = fill_sec_cache_for_universe(
        ["AAPL"],
        ticker_to_cik={"AAPL": "0000320193"},
        cache_root=tmp_path,
        session=object(),
        user_agent="Aeternus test@test.com",
        fetch_submissions=_fetch_submissions,
        fetch_companyfacts=_fetch_companyfacts,
        fetch_submissions_history=_fetch_history,
        include_history=True,
    )

    assert summary["cached"] == ["AAPL"]
    assert (tmp_path / "submissions_history" / "AAPL" / "CIK0000320193-submissions-001.json").exists()


def test_resolve_ticker_cik_map_uses_live_sec_payload_and_caches_it(tmp_path):
    session = _FakeSession(
        _FakeResponse(
            200,
            {
                "0": {"ticker": "AAPL", "cik_str": 320193},
                "1": {"ticker": "MSFT", "cik_str": 789019},
            },
        )
    )

    cik_map = resolve_ticker_cik_map(
        ["AAPL", "MSFT"],
        cache_root=tmp_path,
        session=session,
        user_agent="Aeternus test@test.com",
    )

    assert cik_map == {"AAPL": "0000320193", "MSFT": "0000789019"}
    assert (tmp_path / "company_tickers.json").exists()


def test_resolve_ticker_cik_map_falls_back_to_cached_sec_payload(tmp_path):
    cache_company_tickers_payload(
        {"0": {"ticker": "AAPL", "cik_str": 320193}},
        cache_root=tmp_path,
    )

    class _FailingSession:
        def get(self, *args, **kwargs):
            raise RuntimeError("network down")

    cik_map = resolve_ticker_cik_map(
        ["AAPL"],
        cache_root=tmp_path,
        session=_FailingSession(),
        user_agent="Aeternus test@test.com",
    )

    assert cik_map == {"AAPL": "0000320193"}


def test_resolve_ticker_cik_map_raises_when_no_live_or_cached_sec_payload(tmp_path):
    class _FailingSession:
        def get(self, *args, **kwargs):
            raise RuntimeError("network down")

    with pytest.raises(RuntimeError, match="Unable to resolve ticker-to-CIK map"):
        resolve_ticker_cik_map(
            ["AAPL"],
            cache_root=tmp_path,
            session=_FailingSession(),
            user_agent="Aeternus test@test.com",
        )


def test_resolve_ticker_cik_map_handles_dot_hyphen_aliases(tmp_path):
    session = _FakeSession(_FakeResponse(200, {"0": {"ticker": "BRK-B", "cik_str": 1067983}}))

    cik_map = resolve_ticker_cik_map(
        ["BRK.B"],
        cache_root=tmp_path,
        session=session,
        user_agent="Aeternus test@test.com",
    )

    assert cik_map == {"BRK.B": "0001067983"}
