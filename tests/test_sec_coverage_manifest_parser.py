import csv
import json
from pathlib import Path

from tradingagents.research.fundamental.src.sec_pipeline import cache_coverage_manifest as manifest


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _submission(*, form: str, filing_date: str, accession: str, primary_document: str, items: str = "") -> dict:
    return {
        "filings": {
            "recent": {
                "form": [form],
                "filingDate": [filing_date],
                "reportDate": [filing_date],
                "acceptanceDateTime": [filing_date + "T16:00:00.000Z"],
                "accessionNumber": [accession],
                "items": [items],
                "primaryDocument": [primary_document],
            }
        }
    }


def _seed_manifest_inputs(tmp_path: Path, *, ticker: str, cik: str, submission: dict, docs: list[tuple[str, str]]) -> Path:
    out = tmp_path / "out"
    live = tmp_path / "live_sec"
    out.mkdir(); live.mkdir()
    (out / "final_dealflow_tickers_sec_eligible.json").write_text(json.dumps({"items": [{"ticker": ticker, "symbol": ticker, "cik": cik, "company_title": ticker, "cik_status": "resolved"}]}), encoding="utf-8")
    (out / "dealflow_universe.csv").write_text(f"ticker,cik,company_title,cik_status\n{ticker},{cik},{ticker},resolved\n", encoding="utf-8")
    cik10 = str(int(cik)).zfill(10)
    _write_json(live / "submissions" / f"CIK{cik10}.json", submission)
    _write_json(live / "companyfacts" / f"CIK{cik10}.json", {"facts": {}})
    for accession, doc in docs:
        path = live / "documents" / f"{ticker}_{accession.replace('-', '')}_{doc}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<html>usable filing text</html>", encoding="utf-8")
    manifest.configure(out=out, live=live, quarters=["2026Q2"])
    return out


def _read_single_manifest_row(out: Path, slug: str = "2026Q2") -> dict:
    with (out / f"sec_coverage_manifest_{slug}.csv").open(newline="", encoding="utf-8") as handle:
        return next(csv.DictReader(handle))


def test_periodic_10q_is_llm_ready_without_earnings_8k(tmp_path):
    accession = "0000000001-26-000001"
    doc = "aaa-20260331.htm"
    out = _seed_manifest_inputs(
        tmp_path,
        ticker="AAA",
        cik="1",
        submission=_submission(form="10-Q", filing_date="2026-05-01", accession=accession, primary_document=doc),
        docs=[(accession, doc)],
    )
    manifest.main()
    row = _read_single_manifest_row(out)
    assert row["coverage_status"] == "CACHED_READY"
    assert row["periodic_accession"] == accession
    assert "8k_item_202_metadata" not in row["missing_inputs"]


def test_selected_8k_without_archive_index_queues_direct_sec_index_check(tmp_path):
    q_acc = "0000000002-26-000001"
    q_doc = "bbb-20260331.htm"
    k_acc = "0000000002-26-000002"
    k_doc = "bbb-earnings.htm"
    submission = {
        "filings": {
            "recent": {
                "form": ["8-K", "10-Q"],
                "filingDate": ["2026-04-30", "2026-05-01"],
                "reportDate": ["2026-04-30", "2026-05-01"],
                "acceptanceDateTime": ["2026-04-30T16:00:00.000Z", "2026-05-01T16:00:00.000Z"],
                "accessionNumber": [k_acc, q_acc],
                "items": ["2.02", ""],
                "primaryDocument": [k_doc, q_doc],
            }
        }
    }
    out = _seed_manifest_inputs(
        tmp_path,
        ticker="BBB",
        cik="2",
        submission=submission,
        docs=[(q_acc, q_doc), (k_acc, k_doc)],
    )
    manifest.main()
    queue = json.loads((out / "sec_fetch_queue_resumable.json").read_text())
    assert any(item["kind"] == "archive_index" and item["accession"] == k_acc for item in queue["items"])


def test_primary_8k_plus_periodic_is_llm_ready_without_press_release_exhibit_after_index_checked(tmp_path):
    q_acc = "0000000002-26-000001"
    q_doc = "bbb-20260331.htm"
    k_acc = "0000000002-26-000002"
    k_doc = "bbb-earnings.htm"
    submission = {
        "filings": {
            "recent": {
                "form": ["8-K", "10-Q"],
                "filingDate": ["2026-04-30", "2026-05-01"],
                "reportDate": ["2026-04-30", "2026-05-01"],
                "acceptanceDateTime": ["2026-04-30T16:00:00.000Z", "2026-05-01T16:00:00.000Z"],
                "accessionNumber": [k_acc, q_acc],
                "items": ["2.02", ""],
                "primaryDocument": [k_doc, q_doc],
            }
        }
    }
    out = _seed_manifest_inputs(
        tmp_path,
        ticker="BBB",
        cik="2",
        submission=submission,
        docs=[(q_acc, q_doc), (k_acc, k_doc)],
    )
    _write_json(tmp_path / "live_sec" / "archive_indexes" / "0000000002" / f"{k_acc.replace('-', '')}.json", {"directory": {"item": [{"name": k_doc}]}})
    manifest.main()
    row = _read_single_manifest_row(out)
    assert row["coverage_status"] == "CACHED_READY"
    assert row["earnings_8k_primary_document"] == k_doc
    assert row["earnings_exhibit_document"] == ""
    assert "earnings_exhibit_metadata" not in row["missing_inputs"]


def test_daily_as_of_uses_latest_earnings_event_not_calendar_quarter_start(tmp_path):
    k_acc = "0001045810-26-000019"
    q_acc = "0001045810-26-000021"
    k_doc = "nvda-earnings.htm"
    q_doc = "nvda-20260125.htm"
    ex_doc = "nvda-ex991.htm"
    submission = {
        "filings": {
            "recent": {
                "form": ["8-K", "10-K", "8-K"],
                "filingDate": ["2026-02-25", "2026-02-25", "2026-05-27"],
                "reportDate": ["2026-02-25", "2026-01-25", "2026-05-27"],
                "acceptanceDateTime": ["2026-02-25T16:00:00.000Z", "2026-02-25T16:01:00.000Z", "2026-05-27T16:00:00.000Z"],
                "accessionNumber": [k_acc, q_acc, "0001045810-26-000099"],
                "items": ["2.02", "", "2.02"],
                "primaryDocument": [k_doc, q_doc, "future-earnings.htm"],
            }
        }
    }
    out = _seed_manifest_inputs(
        tmp_path,
        ticker="NVDA",
        cik="1045810",
        submission=submission,
        docs=[(k_acc, k_doc), (k_acc, ex_doc), (q_acc, q_doc)],
    )
    _write_json(tmp_path / "live_sec" / "archive_indexes" / "0001045810" / f"{k_acc.replace('-', '')}.json", {"directory": {"item": [{"name": k_doc}, {"name": ex_doc}]}})
    manifest.configure(out=out, live=tmp_path / "live_sec", quarters=["2026Q2"], as_of="2026-05-15")

    manifest.main()

    row = _read_single_manifest_row(out)
    assert row["coverage_status"] == "CACHED_READY"
    assert row["earnings_8k_accession"] == k_acc
    assert row["earnings_exhibit_document"] == ex_doc
    assert row["periodic_accession"] == q_acc
