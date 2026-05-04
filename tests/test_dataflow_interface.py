from tradingagents.dataflows import interface


def test_route_disables_rate_limited_vendor_for_process(monkeypatch):
    calls = {"xai": 0, "google": 0}

    def _xai_rate_limited(*_args, **_kwargs):
        calls["xai"] += 1
        raise RuntimeError("Exceeded retry limit, last status: 429 Too Many Requests")

    def _google_ok(*_args, **_kwargs):
        calls["google"] += 1
        return "GOOGLE_OK"

    interface._DISABLED_VENDOR_METHODS.clear()
    monkeypatch.setitem(interface.VENDOR_METHODS, "get_news", {"xai": _xai_rate_limited, "google": _google_ok})
    monkeypatch.setattr(interface, "get_vendor", lambda category, method=None: "xai")
    monkeypatch.setenv("XAI_API_KEY", "test-key")

    first = interface.route_to_vendor("get_news", "AAPL", "2026-02-01", "2026-02-06")
    second = interface.route_to_vendor("get_news", "MSFT", "2026-02-01", "2026-02-06")

    assert first == "GOOGLE_OK"
    assert second == "GOOGLE_OK"
    assert calls["xai"] == 1
    assert calls["google"] == 2
    assert ("get_news", "xai") in interface._DISABLED_VENDOR_METHODS

