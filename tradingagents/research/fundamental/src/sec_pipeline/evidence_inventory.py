from __future__ import annotations

import argparse
import ast
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping

from tradingagents.research.fundamental.src.daily_run.artifacts import write_csv, write_json_atomic


DEFAULT_SEC_ROOT = Path("/Users/aeternusholdings/Documents/GitHub/AeternusHoldings/cache/sec")
DEFAULT_PARSER_ROOT = Path("tradingagents/research/fundamental/Growth/earnings_8k_sec_parser")
DEFAULT_PANEL_ROOT = Path("outputs/fundamental_backtest/full_complete_panel_2021Q4_2026Q2")
DEFAULT_PRICE_ROOT = Path("/Users/aeternusholdings/.cache/autoresearch_fundamentals")

DEFAULT_COMBINED_SCORE_CSV = DEFAULT_PARSER_ROOT / "combined_all_tiers_hp_extensions_llm_rank_scores_2021Q4_2026Q1_partial.csv"
DEFAULT_PRE_LLM_CSV = DEFAULT_PARSER_ROOT / "pre_llm_fundamental_score_2021Q4_2026Q1_partial.csv"
DEFAULT_COMPLETE_PANEL_CSV = DEFAULT_PANEL_ROOT / "fundamental_complete_prellm_to_top15_2021Q4_2026Q2.csv"

QUARTER_RE = re.compile(r"(?P<year>20\d{2})Q(?P<quarter>[1-4])", re.IGNORECASE)
DATE_RE = re.compile(r"(?P<year>20\d{2})-(?P<month>\d{2})-(?P<day>\d{2})")


def default_quarters() -> list[str]:
    return ["2021Q4"] + [f"{year}Q{quarter}" for year in range(2022, 2026) for quarter in range(1, 5)] + ["2026Q1", "2026Q2"]


def _ticker(value: Any) -> str:
    return str(value or "").upper().replace(".", "-").strip()


def _quarter_from_date(text: str) -> str:
    match = DATE_RE.search(text)
    if not match:
        return ""
    try:
        dt = date(int(match.group("year")), int(match.group("month")), int(match.group("day")))
    except ValueError:
        return ""
    return f"{dt.year}Q{((dt.month - 1) // 3) + 1}"


def _quarter_from_text(text: str) -> str:
    match = QUARTER_RE.search(text)
    if match:
        return f"{match.group('year')}Q{match.group('quarter')}"
    return _quarter_from_date(text)


def _iter_csv_rows(path: Path) -> Iterable[dict[str, str]]:
    try:
        with path.open(newline="", encoding="utf-8", errors="ignore") as handle:
            yield from csv.DictReader(handle)
    except Exception:
        return


@dataclass
class EvidenceInventory:
    quarters: list[str]
    ticker_quarter_sources: dict[tuple[str, str], set[str]] = field(default_factory=lambda: defaultdict(set))
    ticker_sources: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    source_counts: Counter[str] = field(default_factory=Counter)
    source_files: dict[str, str] = field(default_factory=dict)

    def add_ticker(self, ticker: str, source: str) -> None:
        ticker = _ticker(ticker)
        if not ticker:
            return
        self.ticker_sources[ticker].add(source)
        self.source_counts[f"{source}_ticker"] += 1

    def add_ticker_quarter(self, ticker: str, quarter: str, source: str) -> None:
        ticker = _ticker(ticker)
        quarter = str(quarter or "").upper().strip()
        if not ticker or quarter not in self.quarters:
            return
        self.add_ticker(ticker, source)
        self.ticker_quarter_sources[(ticker, quarter)].add(source)
        self.source_counts[f"{source}_ticker_quarter"] += 1


def scan_sec_docs(root: Path, *, source: str, inventory: EvidenceInventory) -> None:
    if not root.exists():
        return
    for path in root.iterdir():
        if not path.is_file():
            continue
        ticker = _ticker(path.name.split("_", 1)[0])
        if ticker:
            inventory.add_ticker(ticker, source)


def scan_facts(root: Path, *, inventory: EvidenceInventory) -> None:
    if not root.exists():
        return
    for path in root.glob("facts_*.json"):
        ticker = _ticker(path.stem.replace("facts_", "", 1))
        if ticker:
            inventory.add_ticker(ticker, "companyfacts_file")


def scan_raw_8k(root: Path, *, inventory: EvidenceInventory) -> None:
    if not root.exists():
        return
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        parts = path.name.split("_")
        ticker = _ticker(parts[0] if parts else "")
        quarter = _quarter_from_text(path.name)
        if ticker:
            inventory.add_ticker(ticker, "older_raw_8k")
        if ticker and quarter:
            inventory.add_ticker_quarter(ticker, quarter, "older_raw_8k")


def scan_quarter_csv(path: Path, *, source: str, inventory: EvidenceInventory) -> None:
    if not path.exists():
        return
    for row in _iter_csv_rows(path):
        ticker = _ticker(row.get("ticker") or row.get("symbol"))
        quarter = str(row.get("quarter") or "").upper().strip() or _quarter_from_text(path.name)
        if ticker:
            inventory.add_ticker(ticker, source)
        if ticker and quarter:
            inventory.add_ticker_quarter(ticker, quarter, source)


def scan_csv_tree(root: Path, *, source: str, inventory: EvidenceInventory, name_prefixes: tuple[str, ...] = ()) -> None:
    if not root.exists():
        return
    for path in root.rglob("*.csv"):
        if name_prefixes and not path.name.startswith(name_prefixes):
            continue
        scan_quarter_csv(path, source=source, inventory=inventory)


def _parquet_tickers(path: Path) -> set[str]:
    try:
        import pyarrow.parquet as pq
    except Exception:
        return set()
    try:
        names = pq.ParquetFile(path).schema.names
    except Exception:
        return set()
    tickers: set[str] = set()
    lowered = {name.lower() for name in names}
    if "ticker" in lowered:
        try:
            import pandas as pd

            frame = pd.read_parquet(path, columns=[next(name for name in names if name.lower() == "ticker")])
            return {_ticker(value) for value in frame.iloc[:, 0].dropna().unique() if _ticker(value)}
        except Exception:
            return set()
    for name in names:
        try:
            first, _second = ast.literal_eval(name)
        except Exception:
            continue
        ticker = _ticker(first)
        if ticker:
            tickers.add(ticker)
    return tickers


def scan_price_cache(root: Path, *, inventory: EvidenceInventory) -> None:
    if not root.exists():
        return
    for path in root.glob("prices*.parquet"):
        for ticker in _parquet_tickers(path):
            inventory.add_ticker(ticker, "price_cache")


def build_inventory(
    *,
    output_root: Path,
    quarters: list[str] | None = None,
    sec_root: Path = DEFAULT_SEC_ROOT,
    parser_root: Path = DEFAULT_PARSER_ROOT,
    panel_csv: Path = DEFAULT_COMPLETE_PANEL_CSV,
    price_root: Path = DEFAULT_PRICE_ROOT,
) -> dict[str, Any]:
    quarter_list = quarters or default_quarters()
    inventory = EvidenceInventory(quarters=quarter_list)

    roots = {
        "sec_docs_html": sec_root / "sec_docs_html",
        "sec_docs_text": sec_root / "sec_docs_text",
        "companyfacts_glob": sec_root,
        "older_raw_8k": sec_root / "earnings_8k_raw",
        "llm_extractions": sec_root / "llm_extractions",
        "add_ticker_llm": parser_root / "add_ticker",
        "parser_root": parser_root,
        "combined_score_csv": DEFAULT_COMBINED_SCORE_CSV,
        "pre_llm_csv": DEFAULT_PRE_LLM_CSV,
        "complete_panel_csv": panel_csv,
        "price_cache": price_root,
    }
    inventory.source_files = {key: str(value) for key, value in roots.items()}

    scan_sec_docs(roots["sec_docs_html"], source="sec_docs_html", inventory=inventory)
    scan_sec_docs(roots["sec_docs_text"], source="sec_docs_text", inventory=inventory)
    scan_facts(roots["companyfacts_glob"], inventory=inventory)
    scan_raw_8k(roots["older_raw_8k"], inventory=inventory)
    scan_csv_tree(roots["llm_extractions"], source="shared_llm_csv", inventory=inventory)
    scan_csv_tree(roots["add_ticker_llm"], source="add_ticker_llm_csv", inventory=inventory)
    scan_csv_tree(
        roots["parser_root"],
        source="parser_quarter_csv",
        inventory=inventory,
        name_prefixes=("pre_llm_", "post_llm_", "llm_", "tier_", "combined_all_tiers", "xbrl_"),
    )
    scan_quarter_csv(roots["combined_score_csv"], source="combined_score_csv", inventory=inventory)
    scan_quarter_csv(roots["pre_llm_csv"], source="pre_llm_csv", inventory=inventory)
    scan_quarter_csv(roots["complete_panel_csv"], source="complete_panel_csv", inventory=inventory)
    scan_price_cache(roots["price_cache"], inventory=inventory)

    by_ticker_quarters: dict[str, set[str]] = defaultdict(set)
    for ticker, quarter in inventory.ticker_quarter_sources:
        by_ticker_quarters[ticker].add(quarter)

    source_unique_tickers: dict[str, set[str]] = defaultdict(set)
    for ticker, sources in inventory.ticker_sources.items():
        for source in sources:
            source_unique_tickers[source].add(ticker)
    source_unique_ticker_quarters: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for key, sources in inventory.ticker_quarter_sources.items():
        for source in sources:
            source_unique_ticker_quarters[source].add(key)

    rows = []
    for ticker, quarter in sorted(inventory.ticker_quarter_sources):
        rows.append(
            {
                "ticker": ticker,
                "quarter": quarter,
                "sources": ";".join(sorted(inventory.ticker_quarter_sources[(ticker, quarter)])),
            }
        )
    summary = {
        "quarter_start": quarter_list[0],
        "quarter_end": quarter_list[-1],
        "quarter_count": len(quarter_list),
        "unique_tickers_with_any_evidence": len(inventory.ticker_sources),
        "unique_tickers_with_quarter_evidence": len(by_ticker_quarters),
        "ticker_quarter_evidence_count": len(inventory.ticker_quarter_sources),
        "tickers_with_all_quarters": sum(1 for quarters_for_ticker in by_ticker_quarters.values() if set(quarter_list) <= quarters_for_ticker),
        "source_observation_counts": dict(sorted(inventory.source_counts.items())),
        "source_unique_ticker_counts": {source: len(tickers) for source, tickers in sorted(source_unique_tickers.items())},
        "source_unique_ticker_quarter_counts": {
            source: len(ticker_quarters) for source, ticker_quarters in sorted(source_unique_ticker_quarters.items())
        },
        "source_roots": inventory.source_files,
    }

    output_root.mkdir(parents=True, exist_ok=True)
    ticker_quarter_csv = output_root / "sec_evidence_ticker_quarter_inventory.csv"
    summary_json = output_root / "sec_evidence_inventory_summary.json"
    write_csv(ticker_quarter_csv, rows)
    write_json_atomic(summary_json, {**summary, "artifacts": {"ticker_quarter_csv": str(ticker_quarter_csv), "summary_json": str(summary_json)}})
    return {**summary, "artifacts": {"ticker_quarter_csv": str(ticker_quarter_csv), "summary_json": str(summary_json)}}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build a local SEC evidence inventory across all configured roots.")
    parser.add_argument("--output-root", default="eval_results/fundamental/sec_evidence_inventory_2021Q4_2026Q2")
    args = parser.parse_args(argv)
    print(json.dumps(build_inventory(output_root=Path(args.output_root)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
