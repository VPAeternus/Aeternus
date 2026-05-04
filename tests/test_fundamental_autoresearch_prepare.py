import json

from tradingagents.research.fundamental_autoresearch.prepare import (
    build_prepared_rows_from_cache,
    load_prepared_rows,
    prepared_rows_artifact_path,
    write_prepared_rows,
)


def test_build_prepared_rows_from_cache_builds_latest_supported_snapshot(tmp_path):
    cache_root = tmp_path / "sec_cache"
    submissions_dir = cache_root / "submissions"
    companyfacts_dir = cache_root / "companyfacts"
    submissions_dir.mkdir(parents=True)
    companyfacts_dir.mkdir(parents=True)

    (submissions_dir / "AAPL.json").write_text(
        json.dumps(
            {
                "cik": "0000320193",
                "filings": {
                    "recent": {
                        "form": ["10-Q"],
                        "filingDate": ["2026-01-29"],
                        "acceptanceDateTime": ["2026-01-29T16:32:10Z"],
                        "reportDate": ["2025-12-27"],
                        "accessionNumber": ["a"],
                    }
                },
            }
        )
    )
    (companyfacts_dir / "AAPL.json").write_text(
        json.dumps(
            {
                "facts": {
                    "us-gaap": {
                        "RevenueFromContractWithCustomerExcludingAssessedTax": {
                            "units": {
                                "USD": [
                                    {"end": "2025-12-27", "fy": 2026, "fp": "Q1", "val": 124300000000},
                                    {"end": "2024-12-28", "fy": 2025, "fp": "Q1", "val": 119600000000},
                                ]
                            }
                        },
                        "GrossProfit": {
                            "units": {
                                "USD": [
                                    {"end": "2025-12-27", "fy": 2026, "fp": "Q1", "val": 58300000000}
                                ]
                            }
                        },
                        "OperatingIncomeLoss": {
                            "units": {
                                "USD": [
                                    {"end": "2025-12-27", "fy": 2026, "fp": "Q1", "val": 42800000000}
                                ]
                            }
                        },
                        "NetCashProvidedByUsedInOperatingActivities": {
                            "units": {
                                "USD": [
                                    {"end": "2025-12-27", "fy": 2026, "fp": "Q1", "val": 34000000000},
                                    {"end": "2024-12-28", "fy": 2025, "fp": "Q1", "val": 30200000000},
                                ]
                            }
                        },
                        "PaymentsToAcquirePropertyPlantAndEquipment": {
                            "units": {
                                "USD": [
                                    {"end": "2025-12-27", "fy": 2026, "fp": "Q1", "val": -2500000000},
                                    {"end": "2024-12-28", "fy": 2025, "fp": "Q1", "val": -2000000000},
                                ]
                            }
                        },
                        "LongTermDebtAndFinanceLeaseObligations": {
                            "units": {"USD": [{"end": "2025-12-27", "fy": 2026, "fp": "Q1", "val": 98200000000}]}
                        },
                        "StockholdersEquity": {
                            "units": {
                                "USD": [
                                    {"end": "2025-12-27", "fy": 2026, "fp": "Q1", "val": 74100000000},
                                    {"end": "2024-12-28", "fy": 2025, "fp": "Q1", "val": 70000000000},
                                ]
                            }
                        },
                        "AssetsCurrent": {
                            "units": {"USD": [{"end": "2025-12-27", "fy": 2026, "fp": "Q1", "val": 152400000000}]}
                        },
                        "LiabilitiesCurrent": {
                            "units": {"USD": [{"end": "2025-12-27", "fy": 2026, "fp": "Q1", "val": 139100000000}]}
                        },
                        "CommonStocksIncludingAdditionalPaidInCapitalSharesOutstanding": {
                            "units": {
                                "shares": [
                                    {"end": "2025-12-27", "fy": 2026, "fp": "Q1", "val": 15100000000},
                                    {"end": "2024-12-28", "fy": 2025, "fp": "Q1", "val": 15400000000},
                                ]
                            }
                        },
                        "NetIncomeLoss": {
                            "units": {"USD": [{"end": "2025-12-27", "fy": 2026, "fp": "Q1", "val": 36300000000}]}
                        },
                    }
                }
            }
        )
    )

    rows = build_prepared_rows_from_cache(
        cache_root=cache_root,
        universe=["AAPL"],
        sector_map={"AAPL": "Technology"},
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["ticker"] == "AAPL"
    assert row["sector"] == "Technology"
    assert row["effective_market_date"] == "2026-01-30"
    assert row["revenue_growth_yoy_pct"] > 0
    assert row["fcf_growth_yoy_pct"] > 0


def test_build_prepared_rows_from_cache_skips_symbols_with_missing_payloads(tmp_path):
    rows = build_prepared_rows_from_cache(
        cache_root=tmp_path / "missing",
        universe=["AAPL"],
        sector_map={"AAPL": "Technology"},
    )

    assert rows == []


def test_prepared_rows_artifact_round_trips(tmp_path):
    rows = [{"ticker": "AAPL", "fundamental_score": 0.75}]

    path = write_prepared_rows(
        rows,
        cache_root=tmp_path / "sec_cache",
        run_name="large_cap_v1-latest",
    )

    assert path == prepared_rows_artifact_path("large_cap_v1-latest", cache_root=tmp_path / "sec_cache")
    assert load_prepared_rows(path) == rows


def test_build_prepared_rows_from_cache_can_backfill_all_supported_filings_since_start_year(tmp_path):
    cache_root = tmp_path / "sec_cache"
    submissions_dir = cache_root / "submissions"
    companyfacts_dir = cache_root / "companyfacts"
    history_dir = cache_root / "submissions_history" / "AAPL"
    submissions_dir.mkdir(parents=True)
    companyfacts_dir.mkdir(parents=True)
    history_dir.mkdir(parents=True)

    (submissions_dir / "AAPL.json").write_text(
        json.dumps(
            {
                "cik": "0000320193",
                "filings": {
                    "recent": {
                        "form": ["10-Q"],
                        "filingDate": ["2026-01-29"],
                        "acceptanceDateTime": ["2026-01-29T16:32:10Z"],
                        "reportDate": ["2025-12-27"],
                        "accessionNumber": ["recent-a"],
                    },
                    "files": [{"name": "CIK0000320193-submissions-001.json"}],
                },
            }
        )
    )
    (history_dir / "CIK0000320193-submissions-001.json").write_text(
        json.dumps(
            {
                "form": ["10-Q", "10-Q"],
                "filingDate": ["2012-01-25", "2008-01-25"],
                "acceptanceDateTime": ["2012-01-25T16:32:10Z", "2008-01-25T16:32:10Z"],
                "reportDate": ["2011-12-31", "2007-12-31"],
                "accessionNumber": ["old-a", "too-old"],
            }
        )
    )
    (companyfacts_dir / "AAPL.json").write_text(
        json.dumps(
            {
                "facts": {
                    "us-gaap": {
                        "RevenueFromContractWithCustomerExcludingAssessedTax": {
                            "units": {
                                "USD": [
                                    {"end": "2025-12-27", "fy": 2026, "fp": "Q1", "val": 124300000000},
                                    {"end": "2024-12-28", "fy": 2025, "fp": "Q1", "val": 119600000000},
                                    {"end": "2011-12-31", "fy": 2012, "fp": "Q1", "val": 46330000000},
                                    {"end": "2010-12-31", "fy": 2011, "fp": "Q1", "val": 26740000000},
                                ]
                            }
                        },
                        "GrossProfit": {
                            "units": {"USD": [{"end": "2025-12-27", "fy": 2026, "fp": "Q1", "val": 58300000000}, {"end": "2011-12-31", "fy": 2012, "fp": "Q1", "val": 21400000000}]}
                        },
                        "OperatingIncomeLoss": {
                            "units": {"USD": [{"end": "2025-12-27", "fy": 2026, "fp": "Q1", "val": 42800000000}, {"end": "2011-12-31", "fy": 2012, "fp": "Q1", "val": 17300000000}]}
                        },
                        "NetCashProvidedByUsedInOperatingActivities": {
                            "units": {
                                "USD": [
                                    {"end": "2025-12-27", "fy": 2026, "fp": "Q1", "val": 34000000000},
                                    {"end": "2024-12-28", "fy": 2025, "fp": "Q1", "val": 30200000000},
                                    {"end": "2011-12-31", "fy": 2012, "fp": "Q1", "val": 17500000000},
                                    {"end": "2010-12-31", "fy": 2011, "fp": "Q1", "val": 12800000000},
                                ]
                            }
                        },
                        "PaymentsToAcquirePropertyPlantAndEquipment": {
                            "units": {
                                "USD": [
                                    {"end": "2025-12-27", "fy": 2026, "fp": "Q1", "val": -2500000000},
                                    {"end": "2024-12-28", "fy": 2025, "fp": "Q1", "val": -2000000000},
                                    {"end": "2011-12-31", "fy": 2012, "fp": "Q1", "val": -1200000000},
                                    {"end": "2010-12-31", "fy": 2011, "fp": "Q1", "val": -900000000},
                                ]
                            }
                        },
                        "StockholdersEquity": {
                            "units": {
                                "USD": [
                                    {"end": "2025-12-27", "fy": 2026, "fp": "Q1", "val": 74100000000},
                                    {"end": "2024-12-28", "fy": 2025, "fp": "Q1", "val": 70000000000},
                                    {"end": "2011-12-31", "fy": 2012, "fp": "Q1", "val": 76600000000},
                                    {"end": "2010-12-31", "fy": 2011, "fp": "Q1", "val": 62100000000},
                                ]
                            }
                        },
                    }
                }
            }
        )
    )

    rows = build_prepared_rows_from_cache(
        cache_root=cache_root,
        universe=["AAPL"],
        sector_map={"AAPL": "Technology"},
        include_history=True,
        latest_only=False,
        start_year=2009,
    )

    assert len(rows) == 2
    assert rows[0]["effective_market_date"] == "2026-01-30"
    assert rows[1]["effective_market_date"] == "2012-01-26"
    assert all(int(row["effective_market_date"][:4]) >= 2009 for row in rows)
