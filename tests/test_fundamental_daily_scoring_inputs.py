import json
from tradingagents.research.fundamental.src.daily_run.scoring_inputs import build_pre_llm_from_companyfacts_cache, derive_tradable_date_from_coverage, materialize_companyfacts_fallbacks


def _companyfacts_payload():
    return {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [{"end": "2026-03-31", "val": 1_000_000_000}]}}, "NetIncomeLoss": {"units": {"USD": [{"end": "2026-03-31", "val": 120_000_000}]}}, "Assets": {"units": {"USD": [{"end": "2026-03-31", "val": 800_000_000}]}}, "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [{"end": "2026-03-31", "val": 150_000_000}]}}, "NetCashProvidedByUsedInInvestingActivities": {"units": {"USD": [{"end": "2026-03-31", "val": -50_000_000}]}}, "NetCashProvidedByUsedInFinancingActivities": {"units": {"USD": [{"end": "2026-03-31", "val": -10_000_000}]}}}}}


def test_build_pre_llm_from_companyfacts_does_not_require_earnings_exhibit(tmp_path):
    facts_root = tmp_path / "companyfacts"; facts_root.mkdir()
    (facts_root / "CIK0000000001.json").write_text(json.dumps(_companyfacts_payload()))
    rows, summary = build_pre_llm_from_companyfacts_cache(universe_rows=[{"ticker": "AAA", "cik": "1", "quarter": "2026Q2"}], companyfacts_root=facts_root, quarter="2026Q2")
    assert summary["companyfacts_cached"] == 1
    assert summary["pre_llm_scored"] == 1
    assert rows[0]["pre_llm_fundamental_bucket"] in {"strong", "good", "mixed", "weak"}
    assert rows[0]["revenue_bucket"] == "$1B-$2B"


def test_companyfacts_fallback_materializes_shared_cache_before_scoring(tmp_path):
    facts_root = tmp_path / "live" / "companyfacts"
    fallback_root = tmp_path / "shared_sec"
    fallback_root.mkdir()
    (fallback_root / "facts_AAA.json").write_text(json.dumps(_companyfacts_payload()))

    summary = materialize_companyfacts_fallbacks(
        universe_rows=[{"ticker": "AAA", "cik": "1"}],
        companyfacts_root=facts_root,
        fallback_root=fallback_root,
    )
    rows, score_summary = build_pre_llm_from_companyfacts_cache(
        universe_rows=[{"ticker": "AAA", "cik": "1", "quarter": "2026Q2"}],
        companyfacts_root=facts_root,
        fallback_root=fallback_root,
        quarter="2026Q2",
    )

    assert summary["companyfacts_fallback_copied_count"] == 1
    assert (facts_root / "CIK0000000001.json").exists()
    assert score_summary["companyfacts_cached"] == 1
    assert rows[0]["pre_llm_fundamental_bucket"] != "not_scored"


def test_derive_tradable_date_uses_next_trading_day_after_latest_filing_date():
    row = {"earnings_8k_filing_date": "2026-05-08", "periodic_filing_date": "2026-05-08"}
    assert derive_tradable_date_from_coverage(row) == "2026-05-11"


def test_attach_entry_prices_quarantines_missing_price_rows():
    from tradingagents.research.fundamental.src.daily_run.scoring_inputs import attach_entry_prices
    rows = [{"ticker": "AAA", "quarter": "2026Q2", "tradable_date": "2026-05-11"}, {"ticker": "BBB", "quarter": "2026Q2", "tradable_date": "2026-05-11"}]
    def fake_price_provider(tickers, *, start, end):
        assert start == "2026-05-11"; assert end == "2026-05-13"
        return [{"ticker": "AAA", "date": "2026-05-11", "open": 12.34, "close": 13.0}]
    priced, quarantine, summary = attach_entry_prices(rows, as_of="2026-05-12", price_provider=fake_price_provider)
    assert next(row for row in priced if row["ticker"] == "AAA")["entry_open"] == 12.34
    assert [row["ticker"] for row in quarantine] == ["BBB"]
    assert quarantine[0]["quarantine_reason"] == "missing_entry_open"
    assert summary["entry_open_ready"] == 1


def test_split_score_ready_rows_quarantines_missing_fundamental_inputs():
    from tradingagents.research.fundamental.src.daily_run.scoring_inputs import split_score_ready_rows
    rows = [
        {"ticker": "AAA", "quarter": "2026Q2", "tradable_date": "2026-05-12", "entry_open": 10, "periodic_accession": "1", "periodic_primary_document": "10q.htm", "revenue_bucket": "$1B-$2B", "pre_llm_fundamental_bucket": "good", "pre_llm_fundamental_score": 3},
        {"ticker": "BBB", "quarter": "2026Q2", "tradable_date": "2026-05-12", "entry_open": 10, "periodic_accession": "2", "periodic_primary_document": "10q.htm", "revenue_bucket": "", "pre_llm_fundamental_bucket": "not_scored", "pre_llm_fundamental_score": ""},
    ]
    ready, quarantine, summary = split_score_ready_rows(rows)
    assert [row["ticker"] for row in ready] == ["AAA"]
    assert [row["ticker"] for row in quarantine] == ["BBB"]
    assert "missing_fundamental_score_inputs" in quarantine[0]["score_input_quarantine_reason"]
    assert "missing_revenue_bucket" in quarantine[0]["score_input_quarantine_reason"]
    assert summary == {"score_input_ready": 1, "score_input_quarantine_count": 1}


def test_attach_entry_prices_uses_next_available_market_open():
    from tradingagents.research.fundamental.src.daily_run.scoring_inputs import attach_entry_prices
    rows = [{"ticker": "AAA", "quarter": "2026Q2", "tradable_date": "2026-02-16"}]
    def fake_price_provider(tickers, *, start, end):
        return [{"ticker": "AAA", "date": "2026-02-17", "open": 15.0, "close": 15.5}]
    priced, quarantine, summary = attach_entry_prices(rows, as_of="2026-05-12", price_provider=fake_price_provider)
    assert priced[0]["entry_open"] == 15.0
    assert priced[0]["entry_open_date"] == "2026-02-17"
    assert quarantine == []
    assert summary["entry_open_ready"] == 1
