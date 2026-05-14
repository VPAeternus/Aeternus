import csv
import json
from datetime import date, timedelta


def _coverage_row(ticker, *, status="CACHED_READY", eight_k=True, exhibit=True, periodic=True):
    return {
        "ticker": ticker,
        "quarter": "2026Q2",
        "coverage_status": status,
        "missing_inputs": "" if status == "CACHED_READY" else "earnings_exhibit_document",
        "earnings_8k_accession": f"00000000-{ticker}" if eight_k else "",
        "earnings_8k_filing_date": "2026-02-02" if eight_k else "",
        "earnings_8k_primary_document": "8k.htm" if eight_k else "",
        "earnings_exhibit_document": "ex99.htm" if exhibit else "",
        "periodic_accession": f"00000000-{ticker}Q" if periodic else "",
        "periodic_form": "10-Q" if periodic else "",
        "periodic_filing_date": "2026-02-02" if periodic else "",
        "periodic_primary_document": "10q.htm" if periodic else "",
    }


def _companyfacts_payload():
    return {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [{"end": "2026-03-31", "val": 1_000_000_000}]}},
                "NetIncomeLoss": {"units": {"USD": [{"end": "2026-03-31", "val": 120_000_000}]}},
                "Assets": {"units": {"USD": [{"end": "2026-03-31", "val": 800_000_000}]}},
                "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [{"end": "2026-03-31", "val": 150_000_000}]}},
                "NetCashProvidedByUsedInInvestingActivities": {"units": {"USD": [{"end": "2026-03-31", "val": -50_000_000}]}},
                "NetCashProvidedByUsedInFinancingActivities": {"units": {"USD": [{"end": "2026-03-31", "val": -10_000_000}]}},
            }
        }
    }


def _price_rows(ticker, *, close=10, volume=600_000, days=60):
    return [
        {
            "ticker": ticker,
            "date": (date(2026, 3, 1) + timedelta(days=idx)).isoformat(),
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": volume,
        }
        for idx in range(days)
    ]


def test_review_list_filter_keeps_only_sec_ready_liquid_raw_price_tickers(tmp_path):
    from tradingagents.research.fundamental.src.daily_run.review_list_filter import filter_review_list_rows

    companyfacts_root = tmp_path / "companyfacts"
    companyfacts_root.mkdir()
    candidates = [
        {"ticker": "PASS", "symbol": "PASS", "cik": "1", "company_title": "Pass Inc"},
        {"ticker": "NO8K", "symbol": "NO8K", "cik": "2", "company_title": "No 8K Inc"},
        {"ticker": "NOEX", "symbol": "NOEX", "cik": "3", "company_title": "No Exhibit Inc"},
        {"ticker": "NOPRICE", "symbol": "NOPRICE", "cik": "4", "company_title": "No Price Inc"},
        {"ticker": "LOWPX", "symbol": "LOWPX", "cik": "5", "company_title": "Low Price Inc"},
        {"ticker": "LOWVOL", "symbol": "LOWVOL", "cik": "6", "company_title": "Low Volume Inc"},
        {"ticker": "NOFUND", "symbol": "NOFUND", "cik": "7", "company_title": "No Fundamentals Inc"},
    ]
    for cik in range(1, 7):
        (companyfacts_root / f"CIK{str(cik).zfill(10)}.json").write_text(json.dumps(_companyfacts_payload()))
    coverage_rows = [
        _coverage_row("PASS"),
        _coverage_row("NO8K", eight_k=False),
        _coverage_row("NOEX", exhibit=False),
        _coverage_row("NOPRICE"),
        _coverage_row("LOWPX"),
        _coverage_row("LOWVOL"),
        _coverage_row("NOFUND"),
    ]
    price_rows = (
        _price_rows("PASS")
        + _price_rows("NO8K")
        + _price_rows("NOEX")
        + _price_rows("LOWPX", close=1.99)
        + _price_rows("LOWVOL", volume=499_999)
        + _price_rows("NOFUND")
    )

    result = filter_review_list_rows(
        candidate_rows=candidates,
        coverage_rows=coverage_rows,
        price_rows=price_rows,
        companyfacts_root=companyfacts_root,
        quarter="2026Q2",
        as_of="2026-05-12",
        output_root=tmp_path,
    )

    assert [row["ticker"] for row in result.rows] == ["PASS"]
    rejected = {row["ticker"]: row["rejection_reason"] for row in result.rejected_rows}
    assert rejected["NO8K"] == "missing_earnings_8k"
    assert rejected["NOEX"] == "missing_press_release_exhibit"
    assert rejected["NOPRICE"] == "raw_yahoo_ohlcv_missing"
    assert rejected["LOWPX"] == "raw_close_below_2"
    assert rejected["LOWVOL"] == "adv60_below_500000"
    assert rejected["NOFUND"] == "missing_core_fundamental_data"
    assert result.summary["sec_universe_count"] == 7
    assert result.summary["kept_count"] == 1
    assert result.summary["rejected_count"] == 6
    assert (tmp_path / "review_stock_list_2026Q2.csv").exists()
    assert (tmp_path / "review_stock_list_2026Q2.json").exists()
    assert (tmp_path / "review_stock_list_rejections_2026Q2.csv").exists()


def test_review_list_filter_marks_missing_cache_as_needs_fetch_not_rejected(tmp_path):
    from tradingagents.research.fundamental.src.daily_run.review_list_filter import filter_review_list_rows

    companyfacts_root = tmp_path / "companyfacts"
    companyfacts_root.mkdir()
    candidates = [
        {"ticker": "NOSEC", "symbol": "NOSEC", "cik": "1", "company_title": "No SEC Cache Inc"},
        {"ticker": "NOPX", "symbol": "NOPX", "cik": "2", "company_title": "No Price Cache Inc"},
    ]
    (companyfacts_root / "CIK0000000002.json").write_text(json.dumps(_companyfacts_payload()))
    coverage_rows = [
        {
            "ticker": "NOSEC",
            "quarter": "2026Q2",
            "coverage_status": "BLOCKED_METADATA_OR_ISSUER_REALITY",
            "missing_inputs": "submissions;companyfacts;10q_10k_metadata",
        },
        _coverage_row("NOPX"),
    ]

    result = filter_review_list_rows(
        candidate_rows=candidates,
        coverage_rows=coverage_rows,
        price_rows=[],
        companyfacts_root=companyfacts_root,
        quarter="2026Q2",
        as_of="2026-05-12",
        output_root=tmp_path,
        sec_fetch_attempted=False,
        price_fetch_attempted=False,
    )

    assert result.rows == []
    assert result.rejected_rows == []
    pending = {row["ticker"]: row["pending_reason"] for row in result.pending_rows}
    assert pending == {"NOSEC": "needs_sec_fetch", "NOPX": "needs_price_fetch"}
    assert result.summary["pending_count"] == 2
    assert (tmp_path / "review_stock_list_pending_2026Q2.csv").exists()


def test_load_sec_ticker_map_rows_reads_sec_company_tickers_json(tmp_path):
    from tradingagents.research.fundamental.src.daily_run.review_list_filter import load_sec_ticker_map_rows

    sec_map = tmp_path / "sec_company_tickers.json"
    sec_map.write_text(
        json.dumps(
            {
                "0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
                "1": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
            }
        )
    )

    rows = load_sec_ticker_map_rows(sec_map, quarter="2026Q2")

    assert rows == [
        {"ticker": "AAPL", "symbol": "AAPL", "cik": "320193", "company_title": "Apple Inc.", "cik_status": "resolved", "quarter": "2026Q2", "stock_source_type": "sec_ticker_map"},
        {"ticker": "NVDA", "symbol": "NVDA", "cik": "1045810", "company_title": "NVIDIA CORP", "cik_status": "resolved", "quarter": "2026Q2", "stock_source_type": "sec_ticker_map"},
    ]


def test_orchestrator_can_build_review_list_from_sec_map_before_scoring(tmp_path, monkeypatch):
    from tradingagents.research.fundamental.src.daily_run.models import DailyRunConfig
    from tradingagents.research.fundamental.src.daily_run import orchestrator

    monkeypatch.setattr(orchestrator, "market_cache_root", lambda *args: tmp_path / "shared_cache")

    sec_map = tmp_path / "sec_company_tickers.json"
    sec_map.write_text(
        json.dumps(
            {
                "0": {"cik_str": 1, "ticker": "PASS", "title": "Pass Inc"},
                "1": {"cik_str": 2, "ticker": "FAIL", "title": "Fail Inc"},
            }
        )
    )
    live = tmp_path / "live_sec"
    companyfacts_root = live / "companyfacts"
    companyfacts_root.mkdir(parents=True)
    (companyfacts_root / "CIK0000000001.json").write_text(json.dumps(_companyfacts_payload()))
    (companyfacts_root / "CIK0000000002.json").write_text(json.dumps(_companyfacts_payload()))

    def fake_coverage(*, out_root, universe_csv, eligible_json, quarter, live_sec_root):
        assert eligible_json.suffix == ".json"
        json.loads(eligible_json.read_text())
        with universe_csv.open(newline="", encoding="utf-8") as handle:
            tickers = [row["ticker"] for row in csv.DictReader(handle)]
        manifest = out_root / f"sec_coverage_manifest_{quarter}.csv"
        rows = [
            _coverage_row(ticker, exhibit=ticker == "PASS")
            for ticker in tickers
        ]
        with manifest.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return {
            "ticker_count": len(tickers),
            "status_counts": {"CACHED_READY": len(tickers)},
            "missing_input_counts": {},
            "fetch_queue_count": 0,
            "blocked_tickers": [],
            "outputs": {"manifest_csv": str(manifest)},
        }

    def fake_prices(tickers, *, start, end):
        rows = []
        for ticker in tickers:
            close = 10 if ticker == "PASS" else 1
            rows.extend(_price_rows(ticker, close=close))
        return rows

    cfg = DailyRunConfig(
        as_of="2026-05-12",
        quarter="2026Q2",
        mode="diagnostic-only",
        output_root=tmp_path / "run",
        sec_live_root=live,
        skip_fetch=True,
        skip_llm=True,
        min_broad_universe_count=1,
        build_review_list_from_sec=True,
        sec_ticker_map_path=sec_map,
        review_allow_live_price_fetch=True,
    )

    result = orchestrator.run_daily_fundamental(
        cfg,
        services=orchestrator.DailyRunServices(price_provider=fake_prices, run_coverage=fake_coverage),
    )

    gate2 = next(gate for gate in result.gates if gate.gate_number == 2)
    assert gate2.status.value == "pass"
    assert gate2.summary["row_count"] == 1
    assert gate2.summary["review_list_filter"]["kept_count"] == 1
    assert gate2.summary["review_list_filter"]["rejected_count"] == 1
    assert result.artifacts["review_stock_list_csv"].endswith("review_stock_list_2026Q2.csv")


def test_load_cached_review_price_rows_reads_wide_yahoo_cache(tmp_path):
    import pandas as pd

    from tradingagents.research.fundamental.src.daily_run.review_list_filter import load_cached_review_price_rows

    cache_path = tmp_path / "prices_batch.parquet"
    dates = pd.date_range("2026-01-01", periods=90, freq="B")
    frame = pd.DataFrame(
        {
            ("PASS", "Open"): [10.0] * len(dates),
            ("PASS", "High"): [11.0] * len(dates),
            ("PASS", "Low"): [9.0] * len(dates),
            ("PASS", "Close"): [10.5] * len(dates),
            ("PASS", "Volume"): [600_000.0] * len(dates),
            ("OTHER", "Open"): [5.0] * len(dates),
            ("OTHER", "High"): [6.0] * len(dates),
            ("OTHER", "Low"): [4.0] * len(dates),
            ("OTHER", "Close"): [5.0] * len(dates),
            ("OTHER", "Volume"): [100_000.0] * len(dates),
        },
        index=dates,
    )
    frame.columns = pd.MultiIndex.from_tuples(frame.columns, names=["Ticker", "Price"])
    frame.to_parquet(cache_path)

    rows = load_cached_review_price_rows([cache_path], tickers=["PASS"], start="2026-01-01", end="2026-05-14")

    assert len(rows) == 90
    assert {row["ticker"] for row in rows} == {"PASS"}
    assert {"open", "high", "low", "close", "volume"} <= set(rows[0])


def test_orchestrator_sec_review_list_uses_price_cache_without_live_fetch(tmp_path):
    import pandas as pd

    from tradingagents.research.fundamental.src.daily_run.models import DailyRunConfig
    from tradingagents.research.fundamental.src.daily_run.orchestrator import DailyRunServices, run_daily_fundamental

    sec_map = tmp_path / "sec_company_tickers.json"
    sec_map.write_text(json.dumps({"0": {"cik_str": 1, "ticker": "PASS", "title": "Pass Inc"}}))
    live = tmp_path / "live_sec"
    companyfacts_root = live / "companyfacts"
    companyfacts_root.mkdir(parents=True)
    (companyfacts_root / "CIK0000000001.json").write_text(json.dumps(_companyfacts_payload()))

    dates = pd.date_range("2026-01-01", periods=90, freq="B")
    cache_path = tmp_path / "prices_single_name_PASS.parquet"
    frame = pd.DataFrame(
        {
            ("PASS", "Open"): [10.0] * len(dates),
            ("PASS", "High"): [11.0] * len(dates),
            ("PASS", "Low"): [9.0] * len(dates),
            ("PASS", "Close"): [10.5] * len(dates),
            ("PASS", "Volume"): [600_000.0] * len(dates),
        },
        index=dates,
    )
    frame.columns = pd.MultiIndex.from_tuples(frame.columns, names=["Ticker", "Price"])
    frame.to_parquet(cache_path)

    def fake_coverage(*, out_root, universe_csv, eligible_json, quarter, live_sec_root):
        assert eligible_json.suffix == ".json"
        json.loads(eligible_json.read_text())
        manifest = out_root / f"sec_coverage_manifest_{quarter}.csv"
        rows = [_coverage_row("PASS")]
        with manifest.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return {
            "ticker_count": 1,
            "status_counts": {"CACHED_READY": 1},
            "missing_input_counts": {},
            "fetch_queue_count": 0,
            "blocked_tickers": [],
            "outputs": {"manifest_csv": str(manifest)},
        }

    def fail_live_price_fetch(*args, **kwargs):
        raise AssertionError("live Yahoo price fetch should not be called")

    cfg = DailyRunConfig(
        as_of="2026-05-12",
        quarter="2026Q2",
        mode="diagnostic-only",
        output_root=tmp_path / "run",
        sec_live_root=live,
        skip_fetch=True,
        skip_llm=True,
        min_broad_universe_count=1,
        build_review_list_from_sec=True,
        sec_ticker_map_path=sec_map,
        review_price_cache_path=cache_path,
        review_allow_live_price_fetch=False,
    )

    result = run_daily_fundamental(
        cfg,
        services=DailyRunServices(price_provider=fail_live_price_fetch, run_coverage=fake_coverage),
    )

    gate2 = next(gate for gate in result.gates if gate.gate_number == 2)
    assert gate2.summary["review_list_filter"]["kept_count"] == 1


def test_orchestrator_fetches_sec_first_then_only_needed_prices(tmp_path, monkeypatch):
    import pandas as pd

    from tradingagents.research.fundamental.src.daily_run.models import DailyRunConfig
    from tradingagents.research.fundamental.src.daily_run import orchestrator

    monkeypatch.setattr(orchestrator, "market_cache_root", lambda *args: tmp_path / "shared_cache")
    sec_map = tmp_path / "sec_company_tickers.json"
    sec_map.write_text(
        json.dumps(
            {
                "0": {"cik_str": 1, "ticker": "PASS", "title": "Pass Inc"},
                "1": {"cik_str": 2, "ticker": "NEEDSEC", "title": "Needs Sec Inc"},
                "2": {"cik_str": 3, "ticker": "NO8K", "title": "No 8K Inc"},
                "3": {"cik_str": 4, "ticker": "NOPX", "title": "No Price Inc"},
            }
        )
    )
    live = tmp_path / "live_sec"
    companyfacts_root = live / "companyfacts"
    companyfacts_root.mkdir(parents=True)
    for cik in ("1", "3", "4"):
        (companyfacts_root / f"CIK{cik.zfill(10)}.json").write_text(json.dumps(_companyfacts_payload()))

    dates = pd.date_range("2026-01-01", periods=90, freq="B")
    cache_path = tmp_path / "prices_single_name_PASS.parquet"
    frame = pd.DataFrame(
        {
            ("PASS", "Open"): [10.0] * len(dates),
            ("PASS", "High"): [11.0] * len(dates),
            ("PASS", "Low"): [9.0] * len(dates),
            ("PASS", "Close"): [10.5] * len(dates),
            ("PASS", "Volume"): [600_000.0] * len(dates),
        },
        index=dates,
    )
    frame.columns = pd.MultiIndex.from_tuples(frame.columns, names=["Ticker", "Price"])
    frame.to_parquet(cache_path)

    coverage_calls = {"count": 0}
    fetched = {"count": 0}
    price_batches = []

    def fake_coverage(*, out_root, universe_csv, eligible_json, quarter, live_sec_root):
        assert eligible_json.suffix == ".json"
        json.loads(eligible_json.read_text())
        coverage_calls["count"] += 1
        with universe_csv.open(newline="", encoding="utf-8") as handle:
            tickers = [row["ticker"] for row in csv.DictReader(handle)]
        first_review_pass = coverage_calls["count"] == 1
        rows = []
        for ticker in tickers:
            if ticker == "NEEDSEC" and first_review_pass:
                rows.append(
                    {
                        "ticker": ticker,
                        "quarter": quarter,
                        "coverage_status": "BLOCKED_METADATA_OR_ISSUER_REALITY",
                        "missing_inputs": "submissions;companyfacts;10q_10k_metadata",
                        "earnings_8k_accession": "",
                        "earnings_8k_filing_date": "",
                        "earnings_8k_primary_document": "",
                        "earnings_exhibit_document": "",
                        "periodic_accession": "",
                        "periodic_form": "",
                        "periodic_filing_date": "",
                        "periodic_primary_document": "",
                    }
                )
            else:
                rows.append(_coverage_row(ticker, eight_k=ticker != "NO8K"))
        manifest = out_root / f"sec_coverage_manifest_{quarter}.csv"
        with manifest.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return {
            "ticker_count": len(tickers),
            "status_counts": {"CACHED_READY": len(tickers)},
            "missing_input_counts": {"companyfacts": 1} if first_review_pass else {},
            "fetch_queue_count": 1 if first_review_pass else 0,
            "blocked_tickers": ["NEEDSEC"] if first_review_pass else [],
            "outputs": {"manifest_csv": str(manifest)},
        }

    def fake_fetch(*, out_root, live_sec_root):
        fetched["count"] += 1
        (companyfacts_root / "CIK0000000002.json").write_text(json.dumps(_companyfacts_payload()))
        return {"fetched": ["NEEDSEC"]}

    def fake_prices(tickers, *, start, end):
        price_batches.append(list(tickers))
        rows = []
        for ticker in tickers:
            rows.extend(_price_rows(ticker, close=10, volume=600_000))
        return rows

    cfg = DailyRunConfig(
        as_of="2026-05-12",
        quarter="2026Q2",
        mode="diagnostic-only",
        output_root=tmp_path / "run",
        sec_live_root=live,
        skip_fetch=False,
        skip_llm=True,
        min_broad_universe_count=1,
        build_review_list_from_sec=True,
        sec_ticker_map_path=sec_map,
        review_price_cache_path=cache_path,
        review_allow_live_price_fetch=True,
    )

    result = orchestrator.run_daily_fundamental(
        cfg,
        services=orchestrator.DailyRunServices(price_provider=fake_prices, run_coverage=fake_coverage, run_fetch_once=fake_fetch),
    )

    gate2 = next(gate for gate in result.gates if gate.gate_number == 2)
    summary = gate2.summary["review_list_filter"]
    assert fetched["count"] == 1
    assert price_batches[0] == ["NEEDSEC", "NOPX"]
    assert summary["kept_count"] == 3
    assert summary["rejected_count"] == 1
    assert summary["price_needed_ticker_count"] == 3
    assert summary["missing_cached_price_ticker_count"] == 2
    assert summary["live_price_fetch_count"] == 120
    assert (tmp_path / "shared_cache" / "review_price_cache_2026Q2_2026-05-12.parquet").exists()


def test_store_review_price_rows_writes_live_yahoo_rows_to_cache(tmp_path):
    import pandas as pd

    from tradingagents.research.fundamental.src.daily_run.review_list_filter import load_cached_review_price_rows, store_review_price_rows

    rows = _price_rows("PASS", close=10.5, volume=600_000, days=60)
    cache_path = store_review_price_rows(rows, output_root=tmp_path, quarter="2026Q2", as_of="2026-05-12")

    assert cache_path.exists()
    frame = pd.read_parquet(cache_path)
    assert {"ticker", "date", "open", "high", "low", "close", "volume"} <= set(frame.columns)
    loaded = load_cached_review_price_rows([cache_path], tickers=["PASS"], start="2026-01-01", end="2026-05-14")
    assert len(loaded) == 60
