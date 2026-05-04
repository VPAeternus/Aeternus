from tradingagents.dealflow.sources import smart_money


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text_data=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if self._json_data is None:
            raise ValueError("No JSON payload")
        return self._json_data


def test_collect_smart_money_signals_merges_sec_and_congress(monkeypatch):
    senate_url = "https://example.com/senate.json"

    def fake_get(url, headers=None, timeout=25):  # pylint: disable=unused-argument
        if url == smart_money.SEC_COMPANY_TICKERS_URL:
            return _FakeResponse(
                json_data={
                    "0": {"ticker": "AAPL", "title": "Apple Inc.", "cik_str": 320193},
                    "1": {"ticker": "MSFT", "title": "Microsoft Corporation", "cik_str": 789019},
                }
            )
        if "submissions/CIK0001067983.json" in url:
            return _FakeResponse(
                json_data={
                    "filings": {
                        "recent": {
                            "form": ["13F-HR"],
                            "accessionNumber": ["0001193125-25-282901"],
                            "filingDate": ["2026-01-31"],
                        }
                    }
                }
            )
        if "/Archives/edgar/data/1067983/000119312525282901/index.json" in url:
            return _FakeResponse(json_data={"directory": {"item": [{"name": "infotable.xml"}]}})
        if url.endswith("/Archives/edgar/data/1067983/000119312525282901/infotable.xml"):
            return _FakeResponse(
                text_data=(
                    "<informationTable>"
                    "<infoTable><nameOfIssuer>Apple Inc.</nameOfIssuer><value>1000</value></infoTable>"
                    "</informationTable>"
                )
            )
        if url == senate_url:
            return _FakeResponse(
                json_data=[
                    {
                        "transaction_date": "02/04/2026",
                        "ticker": "MSFT",
                        "type": "Purchase",
                        "amount": "$15,001 - $50,000",
                    }
                ]
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(smart_money.requests, "get", fake_get)

    universe = [
        {
            "symbol": "AAPL",
            "asset_class": "Equity",
            "sector": "Technology",
            "liquidity_score": 90.0,
            "aliases": ["apple"],
        },
        {
            "symbol": "MSFT",
            "asset_class": "Equity",
            "sector": "Technology",
            "liquidity_score": 88.0,
            "aliases": ["microsoft"],
        },
    ]
    config = {
        "dealflow_sec_manager_ciks": "1067983",
        "dealflow_congress_senate_url": senate_url,
        "dealflow_sec_user_agent": "AeternusTests/1.0 (qa@example.com)",
        "dealflow_smart_money_lookback_days": 180,
    }

    signals = smart_money.collect_smart_money_signals(universe, as_of_date="2026-02-06", config=config)
    by_symbol = {s["symbol"]: s for s in signals}

    assert by_symbol["AAPL"]["source_status"] == "OK"
    assert by_symbol["AAPL"]["raw_score"] > 0.0
    assert by_symbol["MSFT"]["source_status"] == "OK"
    assert by_symbol["MSFT"]["evidence_count"] >= 1


def test_collect_smart_money_signals_returns_not_configured_when_sources_absent():
    universe = [
        {
            "symbol": "AAPL",
            "asset_class": "Equity",
            "sector": "Technology",
            "liquidity_score": 90.0,
            "aliases": ["apple"],
        }
    ]
    config = {
        "dealflow_sec_manager_ciks": "",
        "dealflow_congress_senate_url": "",
    }

    signals = smart_money.collect_smart_money_signals(universe, as_of_date="2026-02-06", config=config)
    assert signals[0]["source_status"] == "NOT_CONFIGURED"


def test_collect_smart_money_signals_supports_local_path_sources(tmp_path, monkeypatch):
    senate_path = tmp_path / "senate.json"
    senate_path.write_text(
        """
        [
          {"transaction_date": "2026-02-04", "ticker": "MSFT", "type": "Purchase", "amount": "$15,001 - $50,000"}
        ]
        """
    )

    def fail_http(url, headers=None, timeout=25):  # pylint: disable=unused-argument
        raise AssertionError(f"No remote fetch expected for local-path test: {url}")

    monkeypatch.setattr(smart_money.requests, "get", fail_http)

    universe = [
        {
            "symbol": "MSFT",
            "asset_class": "Equity",
            "sector": "Technology",
            "liquidity_score": 88.0,
            "aliases": ["microsoft"],
        },
    ]
    config = {
        "dealflow_sec_manager_ciks": "",
        "dealflow_congress_senate_url": str(senate_path),
        "dealflow_smart_money_lookback_days": 120,
    }

    signals = smart_money.collect_smart_money_signals(universe, as_of_date="2026-02-06", config=config)
    assert signals[0]["source_status"] == "OK"
