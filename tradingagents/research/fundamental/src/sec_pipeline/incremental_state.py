from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingagents.research.fundamental.src.config.cache_paths import SEC_CACHE_ROOT
from tradingagents.research.fundamental.src.config.paths import FUNDAMENTAL_RUNS_ROOT

OUT = FUNDAMENTAL_RUNS_ROOT / 'manual' / 'sec_pipeline'
LIVE = SEC_CACHE_ROOT / 'live_sec'
STATE_DB = OUT / 'sec_incremental_state.sqlite'
MANIFEST_CSV = OUT / 'sec_coverage_manifest_2021Q4_2026Q1.csv'
QUEUE_JSON = OUT / 'sec_fetch_queue_resumable.json'
ELIGIBLE_JSON = OUT / 'final_dealflow_tickers_sec_eligible.json'
UNIVERSE_CSV = OUT / 'dealflow_universe.csv'
PARSER_VERSION = 'sec-delta-v2-wrapper-aware-complete-submission-object-gated'


def configure(*, out: Path | str | None = None, live: Path | str | None = None) -> None:
    global OUT, LIVE, STATE_DB, MANIFEST_CSV, QUEUE_JSON, ELIGIBLE_JSON, UNIVERSE_CSV
    if out is not None:
        OUT = Path(out)
    if live is not None:
        LIVE = Path(live)
    STATE_DB = OUT / 'sec_incremental_state.sqlite'
    MANIFEST_CSV = OUT / 'sec_coverage_manifest_2021Q4_2026Q1.csv'
    QUEUE_JSON = OUT / 'sec_fetch_queue_resumable.json'
    ELIGIBLE_JSON = OUT / 'final_dealflow_tickers_sec_eligible.json'
    UNIVERSE_CSV = OUT / 'dealflow_universe.csv'


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            manifest_csv TEXT NOT NULL,
            queue_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ticker_fingerprints (
            ticker TEXT PRIMARY KEY,
            cik TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            submissions_files INTEGER NOT NULL,
            parser_version TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS quarter_coverage (
            ticker TEXT NOT NULL,
            quarter TEXT NOT NULL,
            cik TEXT NOT NULL,
            coverage_status TEXT NOT NULL,
            missing_inputs TEXT NOT NULL,
            earnings_8k_accession TEXT NOT NULL,
            earnings_8k_primary_document TEXT NOT NULL,
            earnings_exhibit_document TEXT NOT NULL,
            periodic_accession TEXT NOT NULL,
            periodic_form TEXT NOT NULL,
            periodic_primary_document TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (ticker, quarter)
        );
        CREATE TABLE IF NOT EXISTS sec_objects (
            cache_key TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            ticker TEXT NOT NULL,
            cik TEXT NOT NULL,
            accession TEXT NOT NULL,
            document TEXT NOT NULL,
            exists_on_disk INTEGER NOT NULL,
            size_bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            content_valid INTEGER NOT NULL DEFAULT 0,
            validation_error TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_quarter_coverage_status ON quarter_coverage(coverage_status);
        CREATE INDEX IF NOT EXISTS idx_sec_objects_ticker ON sec_objects(ticker);
        CREATE INDEX IF NOT EXISTS idx_sec_objects_accession ON sec_objects(accession);
        """
    )
    for table, column, ddl in [
        ('ticker_fingerprints', 'parser_version', "ALTER TABLE ticker_fingerprints ADD COLUMN parser_version TEXT NOT NULL DEFAULT ''"),
        ('sec_objects', 'content_valid', 'ALTER TABLE sec_objects ADD COLUMN content_valid INTEGER NOT NULL DEFAULT 0'),
        ('sec_objects', 'validation_error', "ALTER TABLE sec_objects ADD COLUMN validation_error TEXT NOT NULL DEFAULT ''"),
    ]:
        cols = {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}
        if column not in cols:
            conn.execute(ddl)


def load_universe() -> dict[str, dict[str, str]]:
    with UNIVERSE_CSV.open(newline='', encoding='utf-8') as f:
        return {row['ticker'].upper(): row for row in csv.DictReader(f)}


def eligible_items() -> list[dict[str, Any]]:
    data = json.loads(ELIGIBLE_JSON.read_text(encoding='utf-8'))
    universe = load_universe()
    items = []
    for item in data.get('items', []):
        ticker = str(item.get('symbol') or item.get('ticker')).upper()
        merged = dict(item)
        merged['ticker'] = ticker
        merged['cik'] = universe.get(ticker, {}).get('cik', item.get('cik', ''))
        items.append(merged)
    return items


def cik_for_item(item: dict[str, Any]) -> str:
    raw = item.get('cik') or item.get('metadata', {}).get('cik') or ''
    try:
        return str(int(float(str(raw))))
    except Exception:
        return str(raw).strip()


def ticker_fingerprint(cik: str) -> tuple[str, int]:
    cik10 = str(cik).zfill(10)
    paths = [LIVE / 'submissions' / f'CIK{cik10}.json']
    if paths[0].exists():
        try:
            sub = json.loads(paths[0].read_text(encoding='utf-8'))
            for info in sub.get('filings', {}).get('files', []) or []:
                name = str(info.get('name', ''))
                if name:
                    paths.append(LIVE / 'submissions' / name)
        except Exception:
            pass
    h = hashlib.sha256()
    h.update(PARSER_VERSION.encode())
    h.update(b'\n')
    count = 0
    for path in sorted(set(paths)):
        if not path.exists():
            h.update(f'MISSING:{path.name}\n'.encode())
            continue
        count += 1
        h.update(path.name.encode())
        h.update(b'\0')
        h.update(sha256_file(path).encode())
        h.update(b'\n')
    return h.hexdigest(), count


def object_path(cache_key: str) -> Path:
    return LIVE / cache_key.strip('/')


def validate_cached_object(path: Path) -> tuple[int, str]:
    if not path.exists():
        return 0, 'missing'
    if path.stat().st_size < 64:
        return 0, 'too_small'
    sample = path.read_bytes()[:4096].lower()
    denial_markers = [
        b'automated access to our sites must comply',
        b'you have reached a sec.gov rate limit',
        b'access denied',
        b'reference id:',
    ]
    if any(marker in sample for marker in denial_markers):
        return 0, 'sec_denial_or_rate_limit_payload'
    if path.suffix.lower() in {'.htm', '.html', '.txt'} and not any(token in sample for token in [b'<html', b'<xbrl', b'<document', b'<sec-document']):
        return 0, 'unexpected_text_shape'
    return 1, ''


def upsert_state(conn: sqlite3.Connection) -> dict[str, Any]:
    ts = now_iso()
    run_id = ts.replace(':', '').replace('+', 'Z')
    conn.execute('INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?)', (run_id, ts, str(MANIFEST_CSV), str(QUEUE_JSON)))

    ticker_count = 0
    for item in eligible_items():
        ticker = str(item.get('symbol') or item.get('ticker')).upper()
        cik = cik_for_item(item)
        if not ticker or not cik:
            continue
        fp, file_count = ticker_fingerprint(cik)
        conn.execute(
            '''INSERT OR REPLACE INTO ticker_fingerprints
               (ticker, cik, fingerprint, submissions_files, parser_version, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (ticker, cik, fp, file_count, PARSER_VERSION, ts),
        )
        ticker_count += 1

    coverage_rows = 0
    with MANIFEST_CSV.open(newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            conn.execute(
                '''INSERT OR REPLACE INTO quarter_coverage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    row['ticker'], row['quarter'], row['cik'], row['coverage_status'], row.get('missing_inputs', ''),
                    row.get('earnings_8k_accession', ''), row.get('earnings_8k_primary_document', ''), row.get('earnings_exhibit_document', ''),
                    row.get('periodic_accession', ''), row.get('periodic_form', ''), row.get('periodic_primary_document', ''), ts,
                ),
            )
            coverage_rows += 1

    object_rows = 0
    queue = json.loads(QUEUE_JSON.read_text(encoding='utf-8')) if QUEUE_JSON.exists() else {'items': []}
    object_candidates: dict[str, dict[str, Any]] = {}
    for item in queue.get('items', []):
        object_candidates[str(item['cache_key'])] = item
    # Also persist all materialized docs referenced by coverage manifest.
    with MANIFEST_CSV.open(newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            for role, doc_col, acc_col in [
                ('primary_8k', 'earnings_8k_primary_document', 'earnings_8k_accession'),
                ('earnings_exhibit', 'earnings_exhibit_document', 'earnings_8k_accession'),
                ('periodic_10q_10k', 'periodic_primary_document', 'periodic_accession'),
            ]:
                doc = row.get(doc_col, '')
                acc = row.get(acc_col, '')
                if not doc or not acc:
                    continue
                key = f"documents/{row['ticker'].upper()}_{acc.replace('-', '')}_{doc}"
                object_candidates[key] = {
                    'kind': 'document', 'ticker': row['ticker'], 'cik': row['cik'], 'accession': acc,
                    'document': doc, 'document_type': role, 'cache_key': key,
                }
    for key, item in object_candidates.items():
        path = object_path(key)
        exists = path.exists()
        size = path.stat().st_size if exists else 0
        digest = sha256_file(path) if exists and size < 50_000_000 else ''
        content_valid, validation_error = validate_cached_object(path)
        conn.execute(
            '''INSERT OR REPLACE INTO sec_objects
               (cache_key, kind, ticker, cik, accession, document, exists_on_disk, size_bytes, sha256, content_valid, validation_error, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                key, str(item.get('kind', '')), str(item.get('ticker', '')).upper(), str(item.get('cik', '')),
                str(item.get('accession', '')), str(item.get('document', '')), int(exists), size, digest,
                content_valid, validation_error, ts,
            ),
        )
        object_rows += 1
    conn.commit()
    return {'run_id': run_id, 'ticker_fingerprints': ticker_count, 'coverage_rows': coverage_rows, 'sec_objects': object_rows}


def unchanged_tickers(conn: sqlite3.Connection) -> list[str]:
    unchanged = []
    for item in eligible_items():
        ticker = str(item.get('symbol') or item.get('ticker')).upper()
        cik = cik_for_item(item)
        if not ticker or not cik:
            continue
        current, _ = ticker_fingerprint(cik)
        row = conn.execute('SELECT fingerprint, parser_version FROM ticker_fingerprints WHERE ticker = ?', (ticker,)).fetchone()
        if row and row[0] == current and row[1] == PARSER_VERSION:
            unchanged.append(ticker)
    return unchanged


def main() -> None:
    conn = sqlite3.connect(STATE_DB)
    init_db(conn)
    before_unchanged = unchanged_tickers(conn)
    stats = upsert_state(conn)
    after_unchanged = unchanged_tickers(conn)
    summary = {
        'status': 'complete',
        'state_db': str(STATE_DB),
        'stats': stats,
        'unchanged_tickers_before_update': len(before_unchanged),
        'unchanged_tickers_after_update': len(after_unchanged),
        'daily_delta_policy': 'If ticker fingerprint is unchanged, reuse quarter_coverage rows and skip historical SEC discovery/fetch for that ticker.',
    }
    (OUT / 'sec_incremental_state_summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True), encoding='utf-8')
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
