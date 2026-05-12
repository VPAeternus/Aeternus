from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path('/Users/aeternusholdings/Documents/Aeternus')
OUT = ROOT / 'eval_results/fundamental/2026-05-07_full'
TICKERS_JSON = OUT / 'final_dealflow_tickers_sec_eligible.json'
UNIVERSE_CSV = OUT / 'dealflow_universe.csv'
SEC_CACHE = Path('/Users/aeternusholdings/Documents/GitHub/AeternusHoldings/cache/sec')
LIVE = SEC_CACHE / 'live_sec'
QUARTERS = ['2021Q4'] + [f'{y}Q{q}' for y in range(2022, 2026) for q in range(1, 5)] + ['2026Q1']


def configure(*, out: Path | str | None = None, live: Path | str | None = None) -> None:
    global OUT, TICKERS_JSON, UNIVERSE_CSV, SEC_CACHE, LIVE
    if out is not None:
        OUT = Path(out)
    if live is not None:
        LIVE = Path(live)
        SEC_CACHE = LIVE.parent
    TICKERS_JSON = OUT / 'final_dealflow_tickers_sec_eligible.json'
    UNIVERSE_CSV = OUT / 'dealflow_universe.csv'


def q_bounds(q: str) -> tuple[date, date]:
    y = int(q[:4]); n = int(q[-1]); sm = (n - 1) * 3 + 1
    start = date(y, sm, 1)
    em = sm + 2
    end = date(y, 12, 31) if em == 12 else date(y, em + 1, 1) - timedelta(days=1)
    return start, end


def parse_date(v: Any) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10])
    except Exception:
        return None


def recent_rows(sub: dict[str, Any]) -> list[dict[str, str]]:
    recent = sub.get('filings', {}).get('recent', {})
    forms = recent.get('form', []) or []
    rows = []
    for i, form in enumerate(forms):
        def get(name: str) -> str:
            vals = recent.get(name, []) or []
            return str(vals[i]) if i < len(vals) and vals[i] is not None else ''
        rows.append({
            'form': str(form),
            'filing_date': get('filingDate'),
            'report_date': get('reportDate'),
            'acceptance_datetime': get('acceptanceDateTime'),
            'accession': get('accessionNumber'),
            'items': get('items'),
            'primary_document': get('primaryDocument'),
        })
    return rows


def filing_rows_with_cached_history(sub: dict[str, Any]) -> tuple[list[dict[str, str]], list[str]]:
    rows = recent_rows(sub)
    historical_files = [str(x.get('name', '')) for x in (sub.get('filings', {}).get('files', []) or []) if x.get('name')]
    missing_hist = []
    for name in historical_files:
        path = LIVE / 'submissions' / name
        if not path.exists():
            missing_hist.append(name)
            continue
        try:
            rows.extend(recent_rows({'filings': {'recent': json.loads(path.read_text(encoding='utf-8'))}}))
        except Exception:
            missing_hist.append(name)
    deduped = {}
    for row in rows:
        key = row.get('accession') or '|'.join([row.get('form', ''), row.get('filing_date', ''), row.get('primary_document', '')])
        deduped[key] = row
    return list(deduped.values()), missing_hist


def archive_doc_names(index: dict[str, Any]) -> list[str]:
    return [str(item.get('name', '')) for item in index.get('directory', {}).get('item', []) if item.get('name')]


def candidate_exhibit_documents(names: list[str]) -> list[str]:
    ignored_suffixes = ('.xml', '.xsd', '.css', '.js', '.jpg', '.png', '.xlsx', '.zip', '.txt')
    ignored_tokens = ('index', 'headers', 'filingsummary', 'metalinks', 'r1')
    strong_terms = ('ex99', 'exhibit99', 'press', 'release', 'earn', 'result', 'shareholder', 'letter', 'cfo', 'pr')
    html_docs, strong = [], []
    for name in names:
        low = name.lower()
        normalized = low.rsplit('.', 1)[0].replace('-', '').replace('_', '')
        if low.endswith(ignored_suffixes) or any(token in normalized for token in ignored_tokens):
            continue
        if not low.endswith(('.htm', '.html')):
            continue
        html_docs.append(name)
        if any(term in normalized for term in strong_terms):
            strong.append(name)
    return strong or html_docs


def load_universe() -> dict[str, dict[str, str]]:
    with UNIVERSE_CSV.open(newline='', encoding='utf-8') as f:
        return {r['ticker'].upper(): r for r in csv.DictReader(f)}


def doc_path(ticker: str, accession: str, doc: str) -> Path:
    return LIVE / 'documents' / f"{ticker.upper()}_{accession.replace('-', '')}_{doc}"


def complete_submission_path(cik10: str, accession: str) -> Path:
    return LIVE / 'complete_submissions' / cik10 / f"{accession.replace('-', '')}.txt"


def complete_submission_item(ticker: str, cik: str, cik10: str, accession: str, docs: list[dict[str, str]]) -> dict[str, Any]:
    return {
        'kind': 'complete_submission',
        'ticker': ticker,
        'cik': cik,
        'accession': accession,
        'cache_key': str(complete_submission_path(cik10, accession).relative_to(LIVE)),
        'documents': docs,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    queue_data = json.loads(TICKERS_JSON.read_text(encoding='utf-8'))
    tickers = [str(item.get('symbol') or item.get('ticker')).upper() for item in queue_data.get('items', [])]
    universe = load_universe()
    rows: list[dict[str, Any]] = []
    fetch_queue: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    ticker_summary: dict[str, Counter] = defaultdict(Counter)

    for ticker in tickers:
        u = universe.get(ticker, {})
        cik_raw = str(u.get('cik', '')).strip()
        cik = str(int(float(cik_raw))) if cik_raw else ''
        cik10 = cik.zfill(10) if cik else ''
        title = u.get('company_title', '')
        cik_status = u.get('cik_status', '') or ('resolved' if cik else 'missing')
        if not cik:
            blockers.append({'ticker': ticker, 'blocker_type': 'unresolved_cik', 'cik_status': cik_status, 'company_title': title})
            for q in QUARTERS:
                rows.append({'ticker': ticker, 'quarter': q, 'cik': '', 'company_title': title, 'coverage_status': 'BLOCKED_UNRESOLVED_CIK', 'missing_inputs': 'cik'})
                ticker_summary[ticker]['BLOCKED_UNRESOLVED_CIK'] += 1
            continue

        sub_path = LIVE / 'submissions' / f'CIK{cik10}.json'
        facts_path = LIVE / 'companyfacts' / f'CIK{cik10}.json'
        if not sub_path.exists():
            blockers.append({'ticker': ticker, 'blocker_type': 'missing_cached_submissions', 'cik': cik, 'company_title': title})
            filings = []
            sub = {}
        else:
            sub = json.loads(sub_path.read_text(encoding='utf-8'))
            filings, missing_hist = filing_rows_with_cached_history(sub)
        if not sub_path.exists():
            missing_hist = []
        forms = {r['form'] for r in filings}
        has_foreign_forms = bool(forms & {'20-F', '40-F', '6-K', '20-F/A', '40-F/A'})
        has_domestic_periodic = bool(forms & {'10-Q', '10-K', '10-Q/A', '10-K/A'})
        if has_foreign_forms and not has_domestic_periodic:
            blockers.append({'ticker': ticker, 'blocker_type': 'foreign_issuer_no_10q_10k_in_cached_recent', 'cik': cik, 'company_title': title, 'forms': sorted(forms)})

        for q in QUARTERS:
            start, end = q_bounds(q)
            missing: list[str] = []
            notes: list[str] = []
            queue_items: list[dict[str, Any]] = []
            if not sub_path.exists():
                missing.append('submissions')
                queue_items.append({'kind': 'submissions', 'ticker': ticker, 'cik': cik, 'cache_key': f'submissions/CIK{cik10}.json'})
            if not facts_path.exists():
                missing.append('companyfacts')
                queue_items.append({'kind': 'companyfacts', 'ticker': ticker, 'cik': cik, 'cache_key': f'companyfacts/CIK{cik10}.json'})
            if missing_hist:
                missing.append('historical_submission_files')
                notes.append(f"missing_historical_submission_files={len(missing_hist)}")
                for name in missing_hist:
                    queue_items.append({'kind': 'historical_submission_file', 'ticker': ticker, 'cik': cik, 'name': name, 'cache_key': f'submissions/{name}'})

            item_202 = [r for r in filings if r['form'] in {'8-K', '8-K/A'} and '2.02' in r.get('items', '') and parse_date(r['filing_date']) and start <= parse_date(r['filing_date']) <= end]
            item_202.sort(key=lambda r: r['filing_date'])
            periodic = [r for r in filings if r['form'] in {'10-Q', '10-K'} and parse_date(r['filing_date']) and parse_date(r['filing_date']) <= end]
            periodic.sort(key=lambda r: r['filing_date'])
            selected_8k = item_202[0] if item_202 else {}
            selected_periodic = periodic[-1] if periodic else {}
            exhibit_doc = ''

            if not selected_8k:
                notes.append('no_item_2_02_8k_using_periodic_only')
            else:
                acc = selected_8k['accession']; compact = acc.replace('-', '')
                primary = selected_8k.get('primary_document', '')
                idx_path = LIVE / 'archive_indexes' / cik10 / f'{compact}.json'
                if idx_path.exists():
                    idx = json.loads(idx_path.read_text(encoding='utf-8'))
                    docs = [d for d in candidate_exhibit_documents(archive_doc_names(idx)) if d != primary]
                    exhibit_doc = docs[0] if docs else ''
                else:
                    exhibit_doc = ''
                    missing.append('archive_index')
                    notes.append('archive_index_missing_for_direct_earnings_exhibit_check')
                    queue_items.append({'kind': 'archive_index', 'ticker': ticker, 'cik': cik, 'accession': acc, 'cache_key': f'archive_indexes/{cik10}/{compact}.json'})
                if not exhibit_doc:
                    notes.append('earnings_exhibit_not_identified_using_primary_8k_or_periodic')
                docs_to_materialize = []
                if primary and not doc_path(ticker, acc, primary).exists():
                    missing.append('primary_8k_document')
                    docs_to_materialize.append({'document_type': 'primary_8k', 'document': primary, 'cache_key': str(doc_path(ticker, acc, primary).relative_to(LIVE))})
                if exhibit_doc:
                    p = doc_path(ticker, acc, exhibit_doc)
                    if not p.exists():
                        missing.append('earnings_exhibit_document')
                        docs_to_materialize.append({'document_type': 'earnings_exhibit', 'document': exhibit_doc, 'cache_key': str(p.relative_to(LIVE))})
                if docs_to_materialize:
                    queue_items.append(complete_submission_item(ticker, cik, cik10, acc, docs_to_materialize))

            if not selected_periodic:
                missing.append('10q_10k_metadata')
                if has_foreign_forms and not has_domestic_periodic:
                    notes.append('foreign_issuer_or_no_domestic_10q_10k')
            else:
                pacc = selected_periodic['accession']; pdoc = selected_periodic.get('primary_document', '')
                if pdoc and not doc_path(ticker, pacc, pdoc).exists():
                    missing.append('periodic_10q_10k_document')
                    queue_items.append({'kind': 'document', 'document_type': 'periodic_10q_10k', 'ticker': ticker, 'cik': cik, 'accession': pacc, 'document': pdoc, 'cache_key': str(doc_path(ticker, pacc, pdoc).relative_to(LIVE))})

            uniq_missing = sorted(set(missing))
            if not uniq_missing:
                status = 'CACHED_READY'
            elif any(x in uniq_missing for x in ['submissions', '10q_10k_metadata']):
                status = 'BLOCKED_METADATA_OR_ISSUER_REALITY'
            else:
                status = 'NEEDS_FETCH'
            ticker_summary[ticker][status] += 1
            for item in queue_items:
                item['quarter'] = q
                fetch_queue.append(item)
            rows.append({
                'ticker': ticker, 'quarter': q, 'cik': cik, 'company_title': title,
                'coverage_status': status,
                'missing_inputs': ';'.join(uniq_missing),
                'notes': ';'.join(notes),
                'earnings_8k_accession': selected_8k.get('accession', ''),
                'earnings_8k_filing_date': selected_8k.get('filing_date', ''),
                'earnings_8k_primary_document': selected_8k.get('primary_document', ''),
                'earnings_exhibit_document': exhibit_doc,
                'periodic_accession': selected_periodic.get('accession', ''),
                'periodic_form': selected_periodic.get('form', ''),
                'periodic_filing_date': selected_periodic.get('filing_date', ''),
                'periodic_primary_document': selected_periodic.get('primary_document', ''),
            })

    seen = set(); deduped = []
    for item in fetch_queue:
        doc_keys = tuple(sorted(str(doc.get('cache_key', '')) for doc in item.get('documents', []) or []))
        key = (item.get('kind'), item.get('cache_key'), item.get('accession'), item.get('document'), doc_keys)
        if key in seen: continue
        seen.add(key); deduped.append(item)

    manifest_csv = OUT / 'sec_coverage_manifest_2021Q4_2026Q1.csv'
    with manifest_csv.open('w', newline='', encoding='utf-8') as f:
        fieldnames = ['ticker','quarter','cik','company_title','coverage_status','missing_inputs','notes','earnings_8k_accession','earnings_8k_filing_date','earnings_8k_primary_document','earnings_exhibit_document','periodic_accession','periodic_form','periodic_filing_date','periodic_primary_document']
        w = csv.DictWriter(f, fieldnames=fieldnames); w.writeheader(); w.writerows(rows)
    queue_path = OUT / 'sec_fetch_queue_resumable.json'
    queue_path.write_text(json.dumps({'cache_root': str(SEC_CACHE), 'live_cache_root': str(LIVE), 'quarters': QUARTERS, 'count': len(deduped), 'items': deduped}, indent=2), encoding='utf-8')
    blockers_path = OUT / 'sec_coverage_blockers.json'
    blockers_path.write_text(json.dumps(blockers, indent=2, sort_keys=True), encoding='utf-8')
    status_counts = Counter(r['coverage_status'] for r in rows)
    missing_counts = Counter(x for r in rows for x in str(r.get('missing_inputs','')).split(';') if x)
    summary = {
        'ticker_count': len(tickers),
        'quarter_count': len(QUARTERS),
        'ticker_quarter_rows': len(rows),
        'status_counts': dict(status_counts),
        'missing_input_counts': dict(missing_counts),
        'fetch_queue_count': len(deduped),
        'blocker_count': len(blockers),
        'blockers_by_type': dict(Counter(b['blocker_type'] for b in blockers)),
        'blocked_tickers': sorted({b['ticker'] for b in blockers}),
        'outputs': {'manifest_csv': str(manifest_csv), 'fetch_queue': str(queue_path), 'blockers': str(blockers_path)},
    }
    (OUT / 'sec_coverage_summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True), encoding='utf-8')
    print(json.dumps(summary, indent=2, sort_keys=True))

if __name__ == '__main__':
    main()
