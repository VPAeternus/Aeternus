from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tradingagents.research.fundamental.src.features.llm_packets import build_llm_packets
from tradingagents.research.fundamental.src.features.investment_decisions import build_investment_decision
from tradingagents.research.fundamental.src.features.positions import build_position_row
from tradingagents.research.fundamental.src.features.pre_llm_scores import build_pre_llm_rows
from tradingagents.research.fundamental.src.ingest.filings import (
    SecClient,
    discover_required_filings,
    fetch_required_documents,
    parse_date,
    quarter_bounds,
    recent_filings,
)
from tradingagents.research.fundamental.src.ingest.prices import compute_return_checkpoints, fetch_yahoo_ohlcv
from tradingagents.research.fundamental.src.ingest.xbrl import companyfacts_to_pre_llm_input
from tradingagents.research.fundamental.src.reporting.investment_memo import build_memo_row
from tradingagents.research.fundamental.src.pipeline.run_on_new_filing import build_signal_tables
from tradingagents.research.fundamental.src.storage import add_run_lineage, make_pipeline_run_id, read_rows, read_table, source_file_hash, write_table


def _prior_quarter(quarter: str) -> str:
    year = int(quarter[:4])
    q = int(quarter[-1])
    if q == 1:
        return f"{year - 1}Q4"
    return f"{year}Q{q - 1}"


def _normalize_cik(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.lower() == "nan":
        return ""
    if text.endswith(".0"):
        text = text[:-2]
    try:
        return str(int(float(text)))
    except (TypeError, ValueError):
        return text


def _to_float(value: Any) -> float | None:
    try:
        if value in {"", None}:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _add_entry_qoq_pct(rows: list[dict[str, Any]], prior_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current_by_key = {(str(row.get("ticker", "")).upper(), str(row.get("quarter", ""))): row for row in rows}
    prior_by_key = {(str(row.get("ticker", "")).upper(), str(row.get("quarter", ""))): row for row in prior_rows}
    for row in rows:
        ticker = str(row.get("ticker", "")).upper()
        quarter = str(row.get("quarter", ""))
        prior = current_by_key.get((ticker, _prior_quarter(quarter))) or prior_by_key.get((ticker, _prior_quarter(quarter))) or {}
        current_entry = _to_float(row.get("entry_open"))
        prior_entry = _to_float(prior.get("entry_open"))
        if current_entry is not None and prior_entry is not None and prior_entry > 0:
            row["entry_qoq_pct"] = round((current_entry / prior_entry - 1) * 100, 4)
        else:
            row.setdefault("entry_qoq_pct", "")
        if prior.get("entry_qoq_pct") not in {None, ""}:
            row["prior_entry_qoq_pct"] = prior.get("entry_qoq_pct")
        else:
            row.setdefault("prior_entry_qoq_pct", "")
        current_score = _to_float(row.get("pre_llm_fundamental_score"))
        prior_score = _to_float(prior.get("pre_llm_fundamental_score"))
        if current_score is not None and prior_score is not None:
            row["score_change"] = round(current_score - prior_score, 4)
        else:
            row.setdefault("score_change", "")
    return rows


def _load_optional(path: Path | None) -> list[dict[str, Any]]:
    return read_rows(path) if path else []


def run_quarter_pipeline(
    *,
    quarter: str,
    universe_path: Path,
    as_of: str,
    lake_root: Path,
    post_llm_path: Path | None = None,
    skip_sec_fetch: bool = False,
    skip_llm: bool = False,
    skip_price_fetch: bool = False,
) -> dict[str, Any]:
    run_id = make_pipeline_run_id("quarter")
    source_hash = source_file_hash(universe_path)
    universe = [row for row in read_rows(universe_path) if str(row.get("quarter", quarter)) == quarter]
    if not skip_sec_fetch:
        client = SecClient()
        filing_events = []
        raw_documents = []
        enriched_universe = []
        for row in universe:
            ticker = str(row.get("ticker", "")).upper()
            cik = _normalize_cik(row.get("cik", ""))
            if cik:
                submissions = client.submissions(cik)
                start, end = quarter_bounds(quarter)
                item_202 = [
                    filing
                    for filing in recent_filings(submissions)
                    if filing["form"] in {"8-K", "8-K/A"}
                    and "2.02" in filing.get("items", "")
                    and parse_date(filing["filing_date"])
                    and start <= parse_date(filing["filing_date"]) <= end
                ]
                item_202.sort(key=lambda filing: filing["filing_date"])
                indexes = {}
                if item_202:
                    accession = str(item_202[0].get("accession", ""))
                    if accession:
                        try:
                            indexes[accession] = client.archive_index(cik, accession)
                        except Exception:
                            indexes[accession] = {}
                event = discover_required_filings(ticker, cik, quarter, submissions, indexes)
                filing_events.append(event)
                raw_documents.extend(fetch_required_documents(client, event))
                row = {**row, **{key: value for key, value in event.items() if value not in {"", None}}}
                if not row.get("revenue_value"):
                    try:
                        row = {**companyfacts_to_pre_llm_input(client.companyfacts(cik), ticker=ticker, quarter=quarter), **row}
                    except Exception:
                        pass
            enriched_universe.append(row)
        universe = enriched_universe
        write_table(lake_root, "filing_events", add_run_lineage(filing_events, pipeline_run_id=run_id, as_of_date=as_of, source_hash=source_hash))
        write_table(lake_root, "raw_documents", add_run_lineage(raw_documents, pipeline_run_id=run_id, as_of_date=as_of, source_hash=source_hash))
    write_table(lake_root, "universe", add_run_lineage(universe, pipeline_run_id=run_id, as_of_date=as_of, source_hash=source_hash))

    pre_rows = build_pre_llm_rows(universe)
    # Preserve event-derived tradable date / entry price if already present in universe input.
    by_key = {(str(row.get("ticker", "")).upper(), str(row.get("quarter", ""))): row for row in universe}
    for row in pre_rows:
        original = by_key.get((str(row.get("ticker", "")).upper(), str(row.get("quarter", ""))), {})
        for field in ["tradable_date", "entry_open", "signal_available_datetime", "entry_open_source"]:
            if original.get(field):
                row[field] = original[field]
    if not skip_price_fetch:
        needs_price = [row for row in pre_rows if row.get("ticker") and row.get("tradable_date") and not row.get("entry_open")]
        tickers = sorted({str(row.get("ticker", "")).upper() for row in needs_price})
        dates = [str(row.get("tradable_date")) for row in needs_price if row.get("tradable_date")]
        if tickers and dates:
            price_rows = fetch_yahoo_ohlcv(tickers, start=min(dates), end=as_of)
            if price_rows:
                write_table(lake_root, "price_history", add_run_lineage(price_rows, pipeline_run_id=run_id, as_of_date=as_of, source_hash=source_hash))
                prices_by_ticker = {ticker: [row for row in price_rows if str(row.get("ticker", "")).upper() == ticker] for ticker in tickers}
                for row in pre_rows:
                    ticker = str(row.get("ticker", "")).upper()
                    if row.get("tradable_date") and not row.get("entry_open"):
                        row.update(compute_return_checkpoints(prices_by_ticker.get(ticker, []), tradable_date=str(row["tradable_date"])))
    existing_pre_rows = read_table(lake_root, "pre_llm_scores").fillna("").to_dict("records")
    pre_rows = _add_entry_qoq_pct(pre_rows, existing_pre_rows)
    write_table(lake_root, "pre_llm_scores", add_run_lineage(pre_rows, pipeline_run_id=run_id, as_of_date=as_of, source_hash=source_hash))

    docs = read_table(lake_root, "raw_documents").fillna("").to_dict("records")
    packets = build_llm_packets(pre_rows, docs)
    packet_path = lake_root / "artifacts" / f"{quarter}_llm_packets.jsonl"
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    packet_path.write_text("\n".join(json.dumps(packet, ensure_ascii=False) for packet in packets), encoding="utf-8")

    post_llm_rows = _load_optional(post_llm_path)
    theme_acceleration_akg_writeback_count = 0
    theme_acceleration_akg_writeback_attempted_count = 0
    theme_acceleration_akg_edge_write_count = 0
    theme_acceleration_akg_writeback_error = ""
    if post_llm_rows:
        write_table(lake_root, "post_llm_scores", add_run_lineage(post_llm_rows, pipeline_run_id=run_id, as_of_date=as_of, source_hash=source_file_hash(post_llm_path)))
        try:
            from tradingagents.dealflow.theme_acceleration_writeback import write_theme_acceleration_to_akg
            from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph

            akg = AeternusKnowledgeGraph.load()
            writeback_stats = write_theme_acceleration_to_akg(akg, post_llm_rows, as_of)
            theme_acceleration_akg_writeback_attempted_count = int(writeback_stats.get("attempted_count", 0))
            theme_acceleration_akg_writeback_count = int(writeback_stats.get("effective_signal_count", 0))
            theme_acceleration_akg_edge_write_count = int(writeback_stats.get("edge_write_count", 0))
            if theme_acceleration_akg_writeback_attempted_count:
                akg.save()
        except Exception as exc:
            theme_acceleration_akg_writeback_count = 0
            theme_acceleration_akg_writeback_attempted_count = 0
            theme_acceleration_akg_edge_write_count = 0
            theme_acceleration_akg_writeback_error = str(exc)
    elif not skip_llm:
        raise RuntimeError("post_llm_path required unless skip_llm=True")

    signal_rows, tier_rows, persisted_pre = build_signal_tables(pre_rows, as_of=as_of, post_llm_rows=post_llm_rows)
    write_table(lake_root, "tier_classification", add_run_lineage(tier_rows, pipeline_run_id=run_id, as_of_date=as_of, source_hash=source_hash))
    write_table(lake_root, "candidate_scores", add_run_lineage(signal_rows, pipeline_run_id=run_id, as_of_date=as_of, source_hash=source_hash))
    write_table(lake_root, "pre_llm_scores", add_run_lineage(persisted_pre, pipeline_run_id=run_id, as_of_date=as_of, source_hash=source_hash))
    decisions = [build_investment_decision(row, decision_date=as_of) for row in signal_rows]
    memos = [build_memo_row(row) for row in decisions]
    positions = [build_position_row(row) for row in decisions if row.get("decision_type") in {"buy", "starter", "approved_buy"}]
    write_table(lake_root, "investment_decisions", add_run_lineage(decisions, pipeline_run_id=run_id, as_of_date=as_of, source_hash=source_hash))
    write_table(lake_root, "research_memos", add_run_lineage(memos, pipeline_run_id=run_id, as_of_date=as_of, source_hash=source_hash))
    if positions:
        write_table(lake_root, "positions", add_run_lineage(positions, pipeline_run_id=run_id, as_of_date=as_of, source_hash=source_hash))

    return {
        "pipeline_run_id": run_id,
        "universe_rows": len(universe),
        "pre_llm_rows": len(pre_rows),
        "llm_packets": len(packets),
        "candidate_rows": len(signal_rows),
        "investment_decisions": len(decisions),
        "research_memos": len(memos),
        "positions": len(positions),
        "theme_acceleration_akg_writeback_count": theme_acceleration_akg_writeback_count,
        "theme_acceleration_akg_writeback_attempted_count": theme_acceleration_akg_writeback_attempted_count,
        "theme_acceleration_akg_edge_write_count": theme_acceleration_akg_edge_write_count,
        "theme_acceleration_akg_writeback_error": theme_acceleration_akg_writeback_error,
        "skipped_sec_fetch": skip_sec_fetch,
        "skipped_llm": skip_llm,
        "skipped_price_fetch": skip_price_fetch,
        "packet_path": str(packet_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run full live fundamental quarter pipeline")
    parser.add_argument("--quarter", required=True)
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--lake-root", type=Path, default=Path("outputs/live/parquet"))
    parser.add_argument("--post-llm", type=Path, default=None)
    parser.add_argument("--skip-sec-fetch", action="store_true")
    parser.add_argument("--skip-llm", action="store_true")
    parser.add_argument("--skip-price-fetch", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_quarter_pipeline(
        quarter=args.quarter,
        universe_path=args.universe,
        as_of=args.as_of,
        lake_root=args.lake_root,
        post_llm_path=args.post_llm,
        skip_sec_fetch=args.skip_sec_fetch,
        skip_llm=args.skip_llm,
        skip_price_fetch=args.skip_price_fetch,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
