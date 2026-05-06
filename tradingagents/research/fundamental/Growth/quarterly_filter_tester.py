from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVENT_PATH = ROOT / "Growth" / "earnings_8k_sec_parser" / "event_shock_scores.csv"
MANIFEST_PATH = ROOT / "Growth" / "earnings_8k_sec_parser" / "manifest.csv"
DEFAULT_OUTPUT = ROOT / "Growth" / "earnings_8k_sec_parser" / "quarterly_filter_audit.csv"
DEFAULT_VENTURE_SOURCES = [
    ROOT / "Growth" / "venture_scan_2021-06_2023-06_all_scored.csv",
    ROOT / "Growth" / "venture_scan_2026_inventory_all_scored.csv",
    ROOT / "Growth" / "be_lte_nvda_sndk_aaoi_venture_score_source.csv",
    ROOT / "Growth" / "be_lte_nvda_sndk_venture_score_source.csv",
]

THEME_TERMS = [
    "ai",
    "artificial intelligence",
    "data center",
    "datacenter",
    "cloud",
    "power",
    "energy",
    "network",
    "optical",
    "memory",
    "storage",
    "semiconductor",
    "infrastructure",
    "hyperscale",
    "400g",
    "800g",
    "catv",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return list(csv.DictReader(path.open(encoding="utf-8")))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def quarter_bounds(quarter: str) -> tuple[date, date]:
    year = int(quarter[:4])
    q = int(quarter[-1])
    start_month = (q - 1) * 3 + 1
    end_month = start_month + 2
    start = date(year, start_month, 1)
    if end_month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, end_month + 1, 1).replace(day=1)
        end = date.fromordinal(end.toordinal() - 1)
    return start, end


def to_int(value: object, default: int = 0) -> int:
    try:
        if value in {None, ""}:
            return default
        return int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def load_manifest() -> dict[tuple[str, str], dict[str, str]]:
    return {(row["ticker"], row["filed"]): row for row in read_csv(MANIFEST_PATH)}


def load_venture(paths: list[Path]) -> dict[str, list[dict[str, str]]]:
    dedupe: dict[tuple[str, str], dict[str, str]] = {}
    for path in paths:
        for row in read_csv(path):
            ticker = row.get("ticker", "").upper()
            filing_date = row.get("filing_date", "")
            if not ticker or not filing_date or not row.get("venture_score"):
                continue
            dedupe[(ticker, filing_date)] = row
    by_ticker: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in dedupe.values():
        by_ticker[row["ticker"].upper()].append(row)
    for rows in by_ticker.values():
        rows.sort(key=lambda row: row.get("filing_date", ""))
    return by_ticker


def latest_venture(ticker: str, asof: date, venture_by_ticker: dict[str, list[dict[str, str]]]) -> dict[str, str]:
    rows = [
        row for row in venture_by_ticker.get(ticker.upper(), [])
        if parse_date(row.get("filing_date", "")) and parse_date(row.get("filing_date", "")) <= asof
    ]
    return rows[-1] if rows else {}


def prior_8k_count(ticker: str, asof: date, events: list[dict[str, str]]) -> int:
    return sum(
        1 for row in events
        if row["ticker"] == ticker and parse_date(row.get("filed", "")) and parse_date(row["filed"]) < asof
    )


def theme_match(row: dict[str, str]) -> tuple[bool, str]:
    text = " ".join([
        row.get("positive_delta_drivers", ""),
        row.get("evidence_snippets", ""),
        row.get("venture_archetype_path", ""),
    ]).lower()
    hits = [term for term in THEME_TERMS if term in text]
    return bool(hits), ";".join(hits[:8])


def audit_quarter(quarter: str, min_venture_score: int, min_prior_8k: int, venture_sources: list[Path]) -> list[dict[str, object]]:
    start, end = quarter_bounds(quarter)
    events = read_csv(EVENT_PATH)
    manifest = load_manifest()
    venture_by_ticker = load_venture(venture_sources)
    rows: list[dict[str, object]] = []
    for event in events:
        decision_date = parse_date(event.get("tradable_date", "")) or parse_date(event.get("filed", ""))
        if decision_date is None or decision_date < start or decision_date > end:
            continue
        ticker = event["ticker"]
        manifest_row = manifest.get((ticker, event["filed"]), {})
        venture = latest_venture(ticker, decision_date, venture_by_ticker)
        combined = dict(event)
        combined["venture_archetype_path"] = venture.get("archetype_path", "")
        has_theme, theme_hits = theme_match(combined)
        prior_count = prior_8k_count(ticker, decision_date, events)
        has_ex99 = bool(manifest_row.get("ex99_1_document"))
        venture_score = to_int(venture.get("venture_score"))
        wave = to_int(venture.get("wave_exposure"))
        asym = to_int(venture.get("asymmetric_upside"))

        reasons: list[str] = []
        if not has_ex99:
            reasons.append("missing_ex99")
        if prior_count < min_prior_8k:
            reasons.append("insufficient_prior_8k")
        if not venture:
            reasons.append("missing_venture")
        if not (venture_score >= min_venture_score or wave >= 3 or asym >= 3):
            reasons.append("weak_venture_prefilter")
        if not has_theme:
            reasons.append("no_theme_match")

        included = not reasons
        rows.append({
            "quarter": quarter,
            "decision_date": decision_date.isoformat(),
            "ticker": ticker,
            "included": str(included),
            "filter_reason": ";".join(reasons) if reasons else "included",
            "prior_8k_count": prior_count,
            "has_ex99": str(has_ex99),
            "theme_match": str(has_theme),
            "theme_hits": theme_hits,
            "venture_score": venture.get("venture_score", ""),
            "venture_filing_date": venture.get("filing_date", ""),
            "wave_exposure": venture.get("wave_exposure", ""),
            "asymmetric_upside": venture.get("asymmetric_upside", ""),
            "event_shock_bucket": event.get("event_shock_bucket", ""),
            "demand_shock_score": event.get("demand_shock_score", ""),
            "risk_shock_score": event.get("risk_shock_score", ""),
            "cyclicality_gate": event.get("cyclicality_gate", ""),
            "return_90d_pct": event.get("return_90d_pct", ""),
            "positive_delta_drivers": event.get("positive_delta_drivers", ""),
        })
    return sorted(rows, key=lambda row: (row["decision_date"], row["ticker"]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Quarterly filter candidate audit")
    parser.add_argument("--quarter", default="2024Q3")
    parser.add_argument("--min-venture-score", type=int, default=10)
    parser.add_argument("--min-prior-8k", type=int, default=3)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--venture-source", type=Path, action="append", default=[])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    venture_sources = args.venture_source or DEFAULT_VENTURE_SOURCES
    rows = audit_quarter(args.quarter, args.min_venture_score, args.min_prior_8k, venture_sources)
    write_csv(args.output, rows)
    included = sum(row["included"] == "True" for row in rows)
    print(f"quarter={args.quarter} candidates={len(rows)} included={included} excluded={len(rows)-included}")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
