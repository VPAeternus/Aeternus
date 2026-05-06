from tradingagents.backtesting.thirteenf.manager_classifier import classify_manager


def test_classify_manager_approves_active_profile():
    manager = {"manager_name": "Alpha Capital Management LP", "manager_cik": "123", "manager_id": "alpha"}
    stats = {"latest_13f_aum_usd": 2_000_000_000, "latest_position_count": 40, "top10_concentration": 0.55}
    out = classify_manager(manager, stats, rules={"allow_terms": ["capital management"], "deny_terms": []})
    assert out["status"] == "approved"


def test_classify_manager_rejects_bank_even_with_aum():
    manager = {"manager_name": "Example National Bank", "manager_cik": "123", "manager_id": "bank"}
    stats = {"latest_13f_aum_usd": 10_000_000_000, "latest_position_count": 40, "top10_concentration": 0.55}
    out = classify_manager(manager, stats, rules={"allow_terms": ["management"], "deny_terms": ["bank"]})
    assert out["status"] == "rejected"
    assert any("deny_terms" in item for item in out["rejects"])


def test_classify_manager_rejects_quasi_indexer():
    manager = {"manager_name": "Beta Asset Management LLC", "manager_cik": "123", "manager_id": "beta"}
    stats = {"latest_13f_aum_usd": 10_000_000_000, "latest_position_count": 220, "top10_concentration": 0.20}
    out = classify_manager(manager, stats, rules={"allow_terms": ["asset management"], "deny_terms": []})
    assert out["status"] == "rejected"
