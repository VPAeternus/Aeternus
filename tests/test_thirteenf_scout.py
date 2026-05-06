from tradingagents.backtesting.thirteenf.scout import build_13f_delta_scout_candidates


def test_13f_delta_scout_uses_manager_quality_and_convergence():
    holdings = [
        {"manager_id": "m1", "manager_name": "M1", "filing_date": "2024-02-14", "report_date": "2023-12-31", "ticker": "AAA", "shares": 100, "previous_shares": 0, "market_value": 100_000_000},
        {"manager_id": "m2", "manager_name": "M2", "filing_date": "2024-02-15", "report_date": "2023-12-31", "ticker": "AAA", "shares": 50, "previous_shares": 10, "market_value": 50_000_000},
        {"manager_id": "bad", "manager_name": "Bad", "filing_date": "2024-02-15", "report_date": "2023-12-31", "ticker": "BBB", "shares": 50, "previous_shares": 0, "market_value": 50_000_000},
    ]
    quality = [
        {"manager_id": "m1", "manager_quality_score": 70},
        {"manager_id": "m2", "manager_quality_score": 80},
        {"manager_id": "bad", "manager_quality_score": 10},
    ]
    candidates = build_13f_delta_scout_candidates(holdings, quality, min_manager_quality=50)
    assert [c["ticker"] for c in candidates] == ["AAA"]
    assert candidates[0]["manager_count"] == 2
    assert candidates[0]["score"] > 80
