from __future__ import annotations

import argparse
from pathlib import Path

from tradingagents.research.fundamental.src.config.cache_paths import sec_cache_root
from tradingagents.research.fundamental.src.ingest.filings import SecClient, SecFetchConfig, discover_required_filings, fetch_required_documents
from tradingagents.research.fundamental.src.storage import add_run_lineage, make_pipeline_run_id, read_rows, source_file_hash, write_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch required SEC docs for ticker-quarter universe")
    parser.add_argument("--input", type=Path, required=True, help="CSV/Parquet with ticker,cik,quarter")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--lake-root", type=Path, default=Path("outputs/live/parquet"))
    parser.add_argument("--cache-root", type=Path, default=sec_cache_root("live_sec"))
    parser.add_argument("--user-agent", default="AeternusAutoResearch/1.0 contact@aeternus.local")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--pipeline-run-id", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = SecClient(SecFetchConfig(cache_root=args.cache_root, user_agent=args.user_agent, force=args.force))
    input_rows = read_rows(args.input)
    events = []
    docs = []
    for row in input_rows:
        ticker = str(row["ticker"]).upper()
        cik = str(row["cik"])
        quarter = str(row["quarter"])
        submissions = client.submissions(cik)
        recent = submissions.get("filings", {}).get("recent", {})
        accessions = [str(acc) for acc in recent.get("accessionNumber", []) if acc]
        indexes = {}
        for accession in accessions:
            try:
                indexes[accession] = client.archive_index(cik, accession)
            except Exception:
                indexes[accession] = {}
        event = discover_required_filings(ticker, cik, quarter, submissions, indexes)
        events.append(event)
        docs.extend(fetch_required_documents(client, event))
    run_id = args.pipeline_run_id or make_pipeline_run_id("secfetch")
    source_hash = source_file_hash(args.input)
    write_table(args.lake_root, "filing_events", add_run_lineage(events, pipeline_run_id=run_id, as_of_date=args.as_of, source_hash=source_hash))
    write_table(args.lake_root, "raw_documents", add_run_lineage(docs, pipeline_run_id=run_id, as_of_date=args.as_of, source_hash=source_hash))
    failures = sum(1 for doc in docs if int(doc.get("extraction_quality_failure", 0) or 0) == 1)
    print(f"wrote filing_events={len(events)} raw_documents={len(docs)} failures={failures} run_id={run_id}")


if __name__ == "__main__":
    main()
