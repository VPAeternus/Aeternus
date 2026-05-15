# Fundamental Stock List Origin

This note explains the starting stock list for the fundamental run.

## Plain-English Summary

The main stock list now starts from:

- `tradingagents/research/fundamental/data/master_fundamental_universe_start_2021Q4.json`

Plain rule:

1. Start with unique tickers that have local 2021Q4 SEC evidence.
2. Attach CIK and company name from the SEC ticker map when available.
3. If the SEC ticker map misses, fill CIK and company name from trusted existing panel data or SEC facts.
4. Do not drop a ticker only because the local SEC ticker map misses it.
5. Future daily dealflow names get checked against this starting list, then SEC lookup/fetch fills gaps.

There are also two supporting files:

- `sec_company_tickers.json`: broad SEC ticker lookup table.
- `final_dealflow_tickers_sec_eligible.json`: older daily stock review list output.

The SEC lookup file is like a phone book. It maps tickers to SEC company IDs and company names.

The master start list is the set of stocks with 2021Q4 SEC evidence in local historical files.

## Current Counts

Latest checked counts:

- SEC ticker lookup: `10,348` tickers.
- Master fundamental universe start, 2021Q4 SEC evidence: `1,251` tickers.
- CIK/company identity resolved: `1,251` tickers.
- CIK not resolved: `0` tickers.
- Final review list used on `2026-05-12`: `1,313` tickers.

The three 2021Q4 start-list tickers missed by the local SEC ticker map, then filled from the existing complete panel, are:

- `CFLT`: CIK `1699838`, `CONFLUENT, INC.`
- `EXAS`: CIK `1124140`, `EXACT SCIENCES CORP`
- `TGNA`: CIK `39899`, `TEGNA INC.`

## How 10,348 Relates To 1,276

The old `1,276` list was not created by filtering all `10,348` SEC ticker-map rows.

These are two different lists.

- `10,348` is the broad SEC lookup table count.
- `1,276` is our historical fundamental review list after company-ID matching.

It came from historical fundamental coverage:

1. Start with the historical fundamental panel.
2. That historical panel had `22,304` stock-quarter rows.
3. Those rows represented `1,279` unique tickers.
4. Match those `1,279` tickers to company ID and company name using the local SEC ticker lookup.
5. Keep the tickers that matched.
6. This kept `1,276` tickers.
7. Save the base review list as:
   `eval_results/fundamental/2026-05-11_2026Q2_master_sec_fetch/final_dealflow_tickers_sec_eligible.json`

That file records:

- `source_stage`: `historical_fundamental_pit_panel_unique_tickers`
- `total_tickers`: `1,279`
- `count`: `1,276`

So the real path was:

`historical panel 1,279` -> `company-ID matched 1,276`

Not:

`SEC ticker lookup 10,348` -> `filtered to 1,276`

## Known Problem

Three tickers from the `1,279` historical list were dropped:

- `CFLT`
- `EXAS`
- `TGNA`

The local ticker lookup said these were `no_sec_ticker_match`.

That was wrong enough for our purposes because SEC filings exist for all three.

Correct rule:

Do not remove a ticker only because the local SEC ticker lookup misses it.

If the lookup misses, search SEC by ticker. If filings exist, keep the ticker and attach the company ID and company name.

## Why This Matters

The SEC lookup file is not the stock list.

The master start list is not today's dealflow list.

The daily review list should clearly show:

- what came from the base main list
- what came from today's dealflow
- which dealflow tickers were already in the main list
- which dealflow tickers were newly added
- which tickers were excluded and why

## Naming Cleanup Needed

Current name:

- `master_fundamental_universe_<quarter>.csv`

Better operator-facing name:

- `review_stock_list_<quarter>.csv`

Keep the old filename only as a compatibility copy while older code still expects it.
