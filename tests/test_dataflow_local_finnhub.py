from tradingagents.dataflows import local


def test_get_finnhub_news_prefers_live_api(monkeypatch):
    def fake_live(path, params):
        assert path == "/company-news"
        assert params["symbol"] == "AAPL"
        return [
            {
                "headline": "Apple headline",
                "summary": "Apple summary",
                "datetime": 1769980800,
            }
        ]

    monkeypatch.setattr(local, "_finnhub_get", fake_live)
    monkeypatch.setattr(
        local,
        "get_data_in_range",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not hit local files")),
    )

    out = local.get_finnhub_news("AAPL", "2026-01-30", "2026-02-06")
    assert "Apple headline" in out
    assert "Apple summary" in out


def test_get_finnhub_insider_sentiment_prefers_live_api(monkeypatch):
    def fake_live(path, params):
        assert path == "/stock/insider-sentiment"
        return {
            "data": [
                {"year": 2026, "month": 2, "change": 123, "mspr": 0.42},
            ]
        }

    monkeypatch.setattr(local, "_finnhub_get", fake_live)
    monkeypatch.setattr(
        local,
        "get_data_in_range",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not hit local files")),
    )

    out = local.get_finnhub_company_insider_sentiment("AAPL", "2026-02-06")
    assert "2026-2" in out
    assert "123" in out


def test_get_finnhub_insider_transactions_prefers_live_api(monkeypatch):
    def fake_live(path, params):
        assert path == "/stock/insider-transactions"
        return {
            "data": [
                {
                    "filingDate": "2026-02-05",
                    "name": "Insider Name",
                    "change": -100,
                    "share": 1000,
                    "transactionPrice": 210.5,
                    "transactionCode": "S",
                }
            ]
        }

    monkeypatch.setattr(local, "_finnhub_get", fake_live)
    monkeypatch.setattr(
        local,
        "get_data_in_range",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not hit local files")),
    )

    out = local.get_finnhub_company_insider_transactions("AAPL", "2026-02-06")
    assert "Insider Name" in out
    assert "Transaction Code: S" in out
