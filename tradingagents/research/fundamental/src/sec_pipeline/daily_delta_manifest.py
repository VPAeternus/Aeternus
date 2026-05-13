from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path

from tradingagents.research.fundamental.src.config.paths import FUNDAMENTAL_RUNS_ROOT

try:
    from . import cache_coverage_manifest, incremental_state as state
except ImportError:  # direct script execution
    import cache_coverage_manifest  # type: ignore
    import incremental_state as state  # type: ignore

OUT = FUNDAMENTAL_RUNS_ROOT / 'manual' / 'sec_pipeline'
STATE_DB = OUT / 'sec_incremental_state.sqlite'
DELTA_CSV = OUT / 'sec_daily_delta_coverage_manifest.csv'
DELTA_SUMMARY = OUT / 'sec_daily_delta_summary.json'
DELTA_QUEUE = OUT / 'sec_daily_delta_fetch_queue.json'
CURRENT_LIVE: Path | str | None = None
PARSER_VERSION = state.PARSER_VERSION
QUARTERS = ['2021Q4'] + [f'{y}Q{q}' for y in range(2022, 2026) for q in range(1, 5)] + ['2026Q1']

FIELDNAMES = [
    'ticker','quarter','cik','company_title','coverage_status','missing_inputs','notes',
    'earnings_8k_accession','earnings_8k_filing_date','earnings_8k_primary_document',
    'earnings_exhibit_document','periodic_accession','periodic_form','periodic_filing_date','periodic_primary_document'
]


def configure(*, out: Path | str | None = None, live: Path | str | None = None) -> None:
    global OUT, STATE_DB, DELTA_CSV, DELTA_SUMMARY, DELTA_QUEUE, CURRENT_LIVE
    if out is not None:
        OUT = Path(out)
    CURRENT_LIVE = live
    state.configure(out=OUT, live=live)
    cache_coverage_manifest.configure(out=OUT, live=live)
    STATE_DB = OUT / 'sec_incremental_state.sqlite'
    DELTA_CSV = OUT / 'sec_daily_delta_coverage_manifest.csv'
    DELTA_SUMMARY = OUT / 'sec_daily_delta_summary.json'
    DELTA_QUEUE = OUT / 'sec_daily_delta_fetch_queue.json'


def reusable_tickers(conn: sqlite3.Connection) -> tuple[list[str], list[str]]:
    reused, recompute = [], []
    for item in state.eligible_items():
        ticker = str(item.get('ticker') or item.get('symbol')).upper()
        cik = state.cik_for_item(item)
        if not ticker or not cik:
            recompute.append(ticker)
            continue
        current, _ = state.ticker_fingerprint(cik)
        row = conn.execute(
            'SELECT fingerprint, parser_version FROM ticker_fingerprints WHERE ticker = ?',
            (ticker,),
        ).fetchone()
        rows = conn.execute('SELECT COUNT(*) FROM quarter_coverage WHERE ticker = ?', (ticker,)).fetchone()[0]
        invalid_objects = conn.execute(
            'SELECT COUNT(*) FROM sec_objects WHERE ticker = ? AND (exists_on_disk = 0 OR content_valid = 0)',
            (ticker,),
        ).fetchone()[0]
        if row and row[0] == current and row[1] == PARSER_VERSION and rows == len(QUARTERS) and invalid_objects == 0:
            reused.append(ticker)
        else:
            recompute.append(ticker)
    return reused, recompute


def write_reused_manifest(conn: sqlite3.Connection, tickers: list[str]) -> int:
    rows = []
    for ticker in tickers:
        for row in conn.execute(
            '''SELECT ticker, quarter, cik, '' AS company_title, coverage_status, missing_inputs, '' AS notes,
                      earnings_8k_accession, '' AS earnings_8k_filing_date, earnings_8k_primary_document,
                      earnings_exhibit_document, periodic_accession, periodic_form, '' AS periodic_filing_date,
                      periodic_primary_document
               FROM quarter_coverage WHERE ticker = ? ORDER BY quarter''',
            (ticker,),
        ):
            rows.append(dict(zip(FIELDNAMES, row)))
    with DELTA_CSV.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    if not STATE_DB.exists():
        state.main()
    conn = sqlite3.connect(STATE_DB)
    state.init_db(conn)
    reused, recompute = reusable_tickers(conn)

    if recompute:
        cache_coverage_manifest.configure(out=OUT, live=CURRENT_LIVE)
        cache_coverage_manifest.main()
        state.main()
        conn = sqlite3.connect(STATE_DB)
        state.init_db(conn)
        reused, recompute_after = reusable_tickers(conn)
    else:
        recompute_after = []

    row_count = write_reused_manifest(conn, reused)
    statuses = Counter()
    with DELTA_CSV.open(newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            statuses[row['coverage_status']] += 1
    DELTA_QUEUE.write_text(json.dumps({'count': 0, 'items': [], 'reason': 'all_tickers_reused_from_valid_incremental_state'}, indent=2), encoding='utf-8')
    summary = {
        'status': 'complete' if not recompute_after else 'recomputed_then_complete',
        'reused_tickers': len(reused),
        'recomputed_tickers_initial': len(recompute),
        'recomputed_tickers_after_refresh': len(recompute_after),
        'row_count': row_count,
        'status_counts': dict(statuses),
        'fetch_queue_count': 0,
        'quality_policy': 'Reuse only when submissions fingerprint, parser version, 18 coverage rows, and cached object validation all pass. Otherwise recompute/fallback.',
        'outputs': {'manifest_csv': str(DELTA_CSV), 'fetch_queue': str(DELTA_QUEUE), 'state_db': str(STATE_DB)},
    }
    DELTA_SUMMARY.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding='utf-8')
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
