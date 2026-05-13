from __future__ import annotations

import gzip
import json
import sys
import tempfile
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from tradingagents.research.fundamental.src.config.cache_paths import SEC_CACHE_ROOT
from tradingagents.research.fundamental.src.config.paths import FUNDAMENTAL_RUNS_ROOT

OUT = FUNDAMENTAL_RUNS_ROOT / 'manual' / 'sec_pipeline'
QUEUE_PATH = OUT / 'sec_fetch_queue_resumable.json'
ELIGIBLE_PATH = OUT / 'final_dealflow_tickers_sec_eligible.json'
PROGRESS_PATH = OUT / 'sec_download_progress.json'
DOWNLOAD_MANIFEST_PATH = OUT / 'sec_download_manifest_2021Q4_2026Q1.json'
LIVE = SEC_CACHE_ROOT / 'live_sec'
SEC_ARCHIVE_BASE = 'https://www.sec.gov/Archives/edgar/data'
SEC_SUBMISSIONS_BASE = 'https://data.sec.gov/submissions'
USER_AGENT = 'AeternusAutoResearch/1.0 contact@aeternus.local'
MAX_WORKERS = 8
MAX_REQUESTS_PER_SECOND = 8.0
RETRIES = 4
TIMEOUT = 30
CHECKPOINT_EVERY = 25

_rate_lock = threading.Lock()
_next_request_at = 0.0


def configure(*, out: Path | str | None = None, live: Path | str | None = None) -> None:
    global OUT, QUEUE_PATH, ELIGIBLE_PATH, PROGRESS_PATH, DOWNLOAD_MANIFEST_PATH, LIVE
    if out is not None:
        OUT = Path(out)
    if live is not None:
        LIVE = Path(live)
    QUEUE_PATH = OUT / 'sec_fetch_queue_resumable.json'
    ELIGIBLE_PATH = OUT / 'final_dealflow_tickers_sec_eligible.json'
    PROGRESS_PATH = OUT / 'sec_download_progress.json'
    DOWNLOAD_MANIFEST_PATH = OUT / 'sec_download_manifest_2021Q4_2026Q1.json'


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as tmp:
        json.dump(payload, tmp, indent=2, sort_keys=True)
        tmp.write('\n')
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def eligible_tickers() -> set[str]:
    data = json.loads(ELIGIBLE_PATH.read_text(encoding='utf-8'))
    return {str(item.get('symbol') or item.get('ticker')).upper() for item in data.get('items', [])}


def item_url(item: dict[str, Any]) -> str:
    kind = item.get('kind')
    cik = str(item.get('cik', '')).zfill(10)
    cik_int = int(str(item.get('cik', '0')))
    if kind == 'submissions':
        return f'{SEC_SUBMISSIONS_BASE}/CIK{cik}.json'
    if kind == 'historical_submission_file':
        return f"{SEC_SUBMISSIONS_BASE}/{item['name']}"
    if kind == 'companyfacts':
        return f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json'
    if kind == 'archive_index':
        compact = str(item['accession']).replace('-', '')
        return f'{SEC_ARCHIVE_BASE}/{cik_int}/{compact}/index.json'
    if kind == 'complete_submission':
        compact = str(item['accession']).replace('-', '')
        return f'{SEC_ARCHIVE_BASE}/{cik_int}/{compact}/{item["accession"]}.txt'
    if kind == 'document':
        compact = str(item['accession']).replace('-', '')
        return f"{SEC_ARCHIVE_BASE}/{cik_int}/{compact}/{item['document']}"
    raise ValueError(f'unknown queue item kind: {kind}')


def cache_path(item: dict[str, Any]) -> Path:
    safe = ''.join(ch if ch.isalnum() or ch in '/_.-' else '_' for ch in str(item['cache_key']).strip('/'))
    return LIVE / safe


def load_done() -> set[str]:
    if not PROGRESS_PATH.exists():
        return set()
    data = json.loads(PROGRESS_PATH.read_text(encoding='utf-8'))
    return set(data.get('done_cache_keys', []))


def save_progress(done: set[str], stats: dict[str, Any]) -> None:
    atomic_write_json(PROGRESS_PATH, {
        'updated_at': now_iso(),
        'done_count': len(done),
        'done_cache_keys': sorted(done),
        'stats': stats,
    })


def root_cause(exc: BaseException) -> BaseException:
    cur: BaseException = exc
    while cur.__cause__ is not None:
        cur = cur.__cause__
    return cur


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
            else:
                break
        except (URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < RETRIES:
                time.sleep(0.5 * attempt)
            else:
                break
    raise RuntimeError(f'fetch failed: {url}: {last_error}') from last_error


def first_tag(block: str, tag: str) -> str:
    import re
    match = re.search(rf'<{tag}>\s*([^\n\r<]+)', block, flags=re.I)
    return match.group(1).strip() if match else ''


def parse_complete_submission(payload: bytes) -> dict[str, bytes]:
    import re
    text = payload.decode('utf-8', errors='ignore')
    docs: dict[str, bytes] = {}
    for match in re.finditer(r'<DOCUMENT>(.*?)</DOCUMENT>', text, flags=re.I | re.S):
        block = match.group(1)
        filename = first_tag(block, 'FILENAME')
        text_match = re.search(r'<TEXT>\s*(.*?)\s*</TEXT>', block, flags=re.I | re.S)
        if filename and text_match:
            docs[filename.lower()] = text_match.group(1).encode('utf-8', errors='ignore')
    return docs


def validate_payload(path: Path, payload: bytes) -> None:
    if len(payload) < 64:
        raise RuntimeError(f'invalid SEC payload for {path}: too_small')
    sample = payload[:4096].lower()
    denial_markers = [
        b'automated access to our sites must comply',
        b'you have reached a sec.gov rate limit',
        b'access denied',
        b'reference id:',
    ]
    if any(marker in sample for marker in denial_markers):
        raise RuntimeError(f'invalid SEC payload for {path}: denial_or_rate_limit_page')


def write_atomic(path: Path, payload: bytes) -> None:
    validate_payload(path, payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('wb', dir=path.parent, delete=False) as tmp:
        tmp.write(payload)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def materialize_complete_submission_documents(item: dict[str, Any], payload: bytes) -> None:
    docs = parse_complete_submission(payload)
    for doc in item.get('documents', []) or []:
        name = str(doc.get('document', ''))
        body = docs.get(name.lower())
        if body is None:
            raise RuntimeError(f'complete submission missing document {name}')
        write_atomic(LIVE / str(doc['cache_key']).strip('/'), body)


def fetch_item(index: int, item: dict[str, Any]) -> dict[str, Any]:
    key = str(item['cache_key'])
    path = cache_path(item)
    if path.exists():
        cached_payload = path.read_bytes()
        validate_payload(path, cached_payload)
        if item.get('kind') == 'complete_submission':
            materialize_complete_submission_documents(item, cached_payload)
        return {'ok': True, 'cached': True, 'index': index, 'key': key, 'item': item}
    url = item_url(item)
    payload = fetch_bytes(url)
    write_atomic(path, payload)
    if item.get('kind') == 'complete_submission':
        materialize_complete_submission_documents(item, payload)
    return {'ok': True, 'cached': False, 'index': index, 'key': key, 'item': item, 'bytes': len(payload)}


def item_cache_complete(item: dict[str, Any]) -> bool:
    try:
        path = cache_path(item)
        if not path.exists():
            return False
        validate_payload(path, path.read_bytes())
        if item.get('kind') == 'complete_submission':
            for doc in item.get('documents', []) or []:
                doc_path = LIVE / str(doc.get('cache_key', '')).strip('/')
                if not doc_path.exists():
                    return False
                validate_payload(doc_path, doc_path.read_bytes())
        return True
    except Exception:
        return False


def load_items() -> list[dict[str, Any]]:
    queue = json.loads(QUEUE_PATH.read_text(encoding='utf-8'))
    eligible = eligible_tickers()
    raw_items = [item for item in queue.get('items', []) if str(item.get('ticker', '')).upper() in eligible]
    seen = set()
    items = []
    for item in raw_items:
        key = (item.get('kind'), item.get('cache_key'), item.get('accession'), item.get('document'))
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
    return items


def error_payload(index: int, item: dict[str, Any], exc: BaseException) -> dict[str, Any]:
    cause = root_cause(exc)
    code = getattr(cause, 'code', None)
    return {
        'stopped_at': now_iso(),
        'item_index': index,
        'ticker': item.get('ticker'),
        'kind': item.get('kind'),
        'cache_key': str(item.get('cache_key')),
        'url': item_url(item),
        'error_type': type(cause).__name__,
        'error': str(cause),
        'http_code': code,
        'rate_limited': code in {403, 429},
    }


def main() -> None:
    items = load_items()
    done = load_done()
    stats: dict[str, Any] = {
        'eligible_queue_items': len(items),
        'cached_existing': 0,
        'fetched': 0,
        'skipped_done': 0,
        'workers': MAX_WORKERS,
        'max_requests_per_second': MAX_REQUESTS_PER_SECOND,
    }
    pending = [(idx, item) for idx, item in enumerate(items, start=1) if str(item['cache_key']) not in done or not item_cache_complete(item)]
    errors: list[dict[str, Any]] = []
    completed_since_checkpoint = 0
    last_index = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_item, idx, item): (idx, item) for idx, item in pending}
        while futures:
            done_futures, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done_futures:
                idx, item = futures.pop(future)
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001 - stop on hard SEC/network failures.
                    err = error_payload(idx, item, exc)
                    errors.append(err)
                    save_progress(done, stats | {'last_index': idx, 'stopped': True, 'error': err})
                    atomic_write_json(DOWNLOAD_MANIFEST_PATH, {'status': 'stopped_error', 'stats': stats, 'errors': errors})
                    print(json.dumps(err, indent=2, sort_keys=True), flush=True)
                    executor.shutdown(cancel_futures=True)
                    raise SystemExit(2)
                done.add(result['key'])
                last_index = max(last_index, int(result['index']))
                if result.get('cached'):
                    stats['cached_existing'] += 1
                else:
                    stats['fetched'] += 1
                completed_since_checkpoint += 1
                if completed_since_checkpoint >= CHECKPOINT_EVERY:
                    completed_since_checkpoint = 0
                    save_progress(done, stats | {'last_index': last_index})
                    print(json.dumps({'progress': last_index, 'done_count': len(done), 'fetched': stats['fetched'], 'cached_existing': stats['cached_existing']}), flush=True)

    manifest = {
        'status': 'complete',
        'updated_at': now_iso(),
        'queue_path': str(QUEUE_PATH),
        'eligible_ticker_count': len(eligible_tickers()),
        'eligible_queue_items': len(items),
        'stats': stats,
        'errors': errors,
        'cache_root': str(LIVE),
    }
    save_progress(done, stats | {'last_index': len(items)})
    atomic_write_json(DOWNLOAD_MANIFEST_PATH, manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
