from __future__ import annotations

import csv
import gzip
import hashlib
import json
import re
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from tradingagents.research.fundamental.src.config.cache_paths import SEC_CACHE_ROOT
from tradingagents.research.fundamental.src.config.paths import FUNDAMENTAL_RUNS_ROOT

OUT = FUNDAMENTAL_RUNS_ROOT / 'manual' / 'sec_pipeline'
LIVE = SEC_CACHE_ROOT / 'live_sec'
MANIFEST_CSV = OUT / 'sec_coverage_manifest_2021Q4_2026Q1.csv'
VALIDATION_JSON = OUT / 'sec_complete_submission_validation.json'
VALIDATION_CSV = OUT / 'sec_complete_submission_validation_rows.csv'
COMPLETE_DIR = LIVE / 'complete_submissions'
USER_AGENT = 'AeternusAutoResearch/1.0 contact@aeternus.local'
MAX_WORKERS = 8
MAX_REQUESTS_PER_SECOND = 8.0
RETRIES = 4
TIMEOUT = 30

_rate_lock = threading.Lock()
_next_request_at = 0.0


def configure(*, out: Path | str | None = None, live: Path | str | None = None) -> None:
    global OUT, LIVE, MANIFEST_CSV, VALIDATION_JSON, VALIDATION_CSV, COMPLETE_DIR
    if out is not None:
        OUT = Path(out)
    if live is not None:
        LIVE = Path(live)
    MANIFEST_CSV = OUT / 'sec_coverage_manifest_2021Q4_2026Q1.csv'
    VALIDATION_JSON = OUT / 'sec_complete_submission_validation.json'
    VALIDATION_CSV = OUT / 'sec_complete_submission_validation_rows.csv'
    COMPLETE_DIR = LIVE / 'complete_submissions'


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_payload(data: bytes) -> bytes:
    payload = data.replace(b'\r\n', b'\n').replace(b'\r', b'\n').strip()
    # Some SEC direct document URLs return a SGML <DOCUMENT> envelope instead of
    # raw HTML. Compare the actual filing body, not transport wrappers.
    doc_match = re.search(br'<DOCUMENT>.*?<TEXT>\s*(.*?)\s*</TEXT>.*?</DOCUMENT>', payload, flags=re.I | re.S)
    if doc_match:
        payload = doc_match.group(1).strip()
    # Complete submission .txt wraps inline XBRL HTML bodies in <XBRL>...</XBRL>.
    # Direct archive document URLs may return the inner HTML/XML only. Treat
    # wrapper-only differences as equivalent; preserve inner content byte-for-byte.
    if payload.upper().startswith(b'<XBRL>') and payload.upper().endswith(b'</XBRL>'):
        payload = payload[6:-7].strip()
    return payload


def throttle() -> None:
    global _next_request_at
    interval = 1.0 / MAX_REQUESTS_PER_SECOND
    with _rate_lock:
        now = time.monotonic()
        if now < _next_request_at:
            time.sleep(_next_request_at - now)
            now = time.monotonic()
        _next_request_at = now + interval


def fetch_bytes(url: str) -> bytes:
    headers = {'User-Agent': USER_AGENT, 'Accept-Encoding': 'gzip, deflate'}
    last_error: BaseException | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            throttle()
            req = Request(url, headers=headers)
            with urlopen(req, timeout=TIMEOUT) as response:
                payload = response.read()
                if response.headers.get('Content-Encoding', '').lower() == 'gzip' or payload[:2] == b'\x1f\x8b':
                    payload = gzip.decompress(payload)
                return payload
        except HTTPError as exc:
            last_error = exc
            if exc.code in {403, 429}:
                time.sleep(min(60.0, 5.0 * attempt))
            elif attempt < RETRIES:
                time.sleep(0.5 * attempt)
        except (URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < RETRIES:
                time.sleep(0.5 * attempt)
    raise RuntimeError(f'fetch failed: {url}: {last_error}') from last_error


def complete_url(cik: str, accession: str) -> str:
    compact = accession.replace('-', '')
    return f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{compact}/{accession}.txt'


def complete_path(cik: str, accession: str) -> Path:
    compact = accession.replace('-', '')
    return COMPLETE_DIR / str(cik).zfill(10) / f'{compact}.txt'


def get_complete_submission(cik: str, accession: str) -> bytes:
    path = complete_path(cik, accession)
    if path.exists():
        return path.read_bytes()
    payload = fetch_bytes(complete_url(cik, accession))
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('wb', dir=path.parent, delete=False) as tmp:
        tmp.write(payload)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)
    return payload


def parse_complete_submission(payload: bytes) -> dict[str, dict[str, Any]]:
    text = payload.decode('utf-8', errors='ignore')
    docs: dict[str, dict[str, Any]] = {}
    for match in re.finditer(r'<DOCUMENT>(.*?)</DOCUMENT>', text, flags=re.I | re.S):
        block = match.group(1)
        filename = first_tag(block, 'FILENAME')
        doc_type = first_tag(block, 'TYPE')
        text_match = re.search(r'<TEXT>\s*(.*?)\s*</TEXT>', block, flags=re.I | re.S)
        body = text_match.group(1).encode('utf-8', errors='ignore') if text_match else b''
        if filename:
            docs[filename.lower()] = {'filename': filename, 'type': doc_type, 'body': body, 'body_sha256': sha256_bytes(normalize_payload(body))}
    return docs


def first_tag(block: str, tag: str) -> str:
    match = re.search(rf'<{tag}>\s*([^\n\r<]+)', block, flags=re.I)
    return match.group(1).strip() if match else ''


def doc_cache_path(ticker: str, accession: str, document: str) -> Path:
    return LIVE / 'documents' / f"{ticker.upper()}_{accession.replace('-', '')}_{document}"


def load_targets() -> list[dict[str, str]]:
    targets: dict[tuple[str, str, str], dict[str, str]] = {}
    with MANIFEST_CSV.open(newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            if not row.get('earnings_8k_accession'):
                continue
            if row.get('coverage_status') != 'CACHED_READY':
                continue
            key = (row['ticker'], row['cik'], row['earnings_8k_accession'])
            targets[key] = {
                'ticker': row['ticker'],
                'cik': row['cik'],
                'accession': row['earnings_8k_accession'],
                'primary_document': row.get('earnings_8k_primary_document', ''),
                'exhibit_document': row.get('earnings_exhibit_document', ''),
            }
    return list(targets.values())


def validate_target(target: dict[str, str]) -> dict[str, Any]:
    payload = get_complete_submission(target['cik'], target['accession'])
    docs = parse_complete_submission(payload)
    checks = []
    for role, document in [('primary_8k', target.get('primary_document', '')), ('earnings_exhibit', target.get('exhibit_document', ''))]:
        if not document:
            checks.append({'role': role, 'document': document, 'status': 'NOT_REQUIRED'})
            continue
        cache = doc_cache_path(target['ticker'], target['accession'], document)
        parsed = docs.get(document.lower())
        if not cache.exists():
            status = 'CACHE_MISSING'
        elif not parsed:
            status = 'MISSING_IN_COMPLETE_TXT'
        else:
            cached_bytes = normalize_payload(cache.read_bytes())
            parsed_bytes = normalize_payload(parsed['body'])
            status = 'EXACT_MATCH' if sha256_bytes(cached_bytes) == sha256_bytes(parsed_bytes) else 'CONTENT_MISMATCH'
        checks.append({
            'role': role,
            'document': document,
            'status': status,
            'cache_exists': cache.exists(),
            'complete_txt_has_document': bool(parsed),
            'complete_txt_type': parsed.get('type', '') if parsed else '',
        })
    statuses = {c['status'] for c in checks if c['status'] != 'NOT_REQUIRED'}
    return {
        **target,
        'complete_url': complete_url(target['cik'], target['accession']),
        'complete_cache_path': str(complete_path(target['cik'], target['accession'])),
        'complete_doc_count': len(docs),
        'checks': checks,
        'overall_status': 'PASS' if statuses <= {'EXACT_MATCH'} else 'FAIL',
    }


def main() -> None:
    targets = load_targets()
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [pool.submit(validate_target, target) for target in targets]
        for idx, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            if idx % 25 == 0:
                print(json.dumps({'validated': idx, 'target_count': len(targets)}), flush=True)
    results.sort(key=lambda r: (r['ticker'], r['accession']))
    flat_rows = []
    for result in results:
        for check in result['checks']:
            flat_rows.append({
                'ticker': result['ticker'],
                'cik': result['cik'],
                'accession': result['accession'],
                'role': check['role'],
                'document': check['document'],
                'status': check['status'],
                'complete_txt_type': check.get('complete_txt_type', ''),
                'complete_url': result['complete_url'],
            })
    status_counts: dict[str, int] = {}
    for row in flat_rows:
        status_counts[row['status']] = status_counts.get(row['status'], 0) + 1
    summary = {
        'generated_at': now_iso(),
        'target_8k_accessions': len(targets),
        'check_rows': len(flat_rows),
        'status_counts': status_counts,
        'overall_status': 'PASS' if all(r['overall_status'] == 'PASS' for r in results) else 'FAIL',
        'outputs': {'json': str(VALIDATION_JSON), 'csv': str(VALIDATION_CSV)},
        'results': results,
    }
    VALIDATION_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding='utf-8')
    with VALIDATION_CSV.open('w', newline='', encoding='utf-8') as f:
        fieldnames = ['ticker', 'cik', 'accession', 'role', 'document', 'status', 'complete_txt_type', 'complete_url']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(flat_rows)
    print(json.dumps({k: v for k, v in summary.items() if k != 'results'}, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
