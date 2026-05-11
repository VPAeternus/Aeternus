from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.features.equity_research_note import ResearchContext, build_research_outputs, write_research_outputs


DEFAULT_MASTER = Path("Growth/earnings_8k_sec_parser/rank_scored_tier0_tier1_tier2_tier3_tier4_hp1_hp4_2021Q4_2026Q1_partial_gpt55_mixed.csv")
FALLBACK_MASTER = Path("Growth/earnings_8k_sec_parser/combined_all_tiers_hp_extensions_llm_rank_scores_2021Q4_2026Q1_partial.csv")
DEFAULT_OUTPUT_DIR = Path("outputs/research")


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def _load_master(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path, low_memory=False)
    if FALLBACK_MASTER.exists():
        return pd.read_csv(FALLBACK_MASTER, low_memory=False)
    raise FileNotFoundError(f"No rank/combined master found: {path}")


def _latest_signal_row(df: pd.DataFrame, ticker: str) -> dict[str, Any]:
    rows = df[df["ticker"].astype(str).str.upper().eq(ticker.upper())].copy()
    if rows.empty:
        raise ValueError(f"{ticker} not found in master signal file")
    rows = rows.sort_values("quarter")
    scored = rows[pd.to_numeric(rows.get("entry_score_0_100"), errors="coerce").fillna(0).gt(0)]
    if not scored.empty:
        return scored.tail(1).iloc[0].to_dict()
    return rows.tail(1).iloc[0].to_dict()


def _historical_rows(df: pd.DataFrame, ticker: str) -> list[dict[str, Any]]:
    rows = df[df["ticker"].astype(str).str.upper().eq(ticker.upper())].copy()
    if rows.empty:
        return []
    return rows.sort_values("quarter").to_dict("records")


def _filing_dict(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "form": args.filing_form,
        "items": args.filing_items,
        "accepted_datetime": args.accepted_datetime,
        "accession": args.accession,
        "url": args.filing_url,
    }


def _summary_dict(args: argparse.Namespace, signal_row: dict[str, Any]) -> dict[str, Any]:
    return {
        "reported_revenue": args.reported_revenue,
        "revenue_growth": args.revenue_growth,
        "guidance": args.guidance,
        "business_driver": args.business_driver or _clean(signal_row.get("primary_theme")),
        "risk": args.risk,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate short + long equity research notes from framework signals")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--master", default=str(DEFAULT_MASTER))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    parser.add_argument("--current-price", type=float)
    parser.add_argument("--filing-form", default="")
    parser.add_argument("--filing-items", default="")
    parser.add_argument("--accepted-datetime", default="")
    parser.add_argument("--accession", default="")
    parser.add_argument("--filing-url", default="")
    parser.add_argument("--reported-revenue", default="")
    parser.add_argument("--revenue-growth", default="")
    parser.add_argument("--guidance", default="")
    parser.add_argument("--business-driver", default="")
    parser.add_argument("--risk", default="")
    args = parser.parse_args()

    ticker = args.ticker.upper()
    master = _load_master(Path(args.master))
    signal_row = _latest_signal_row(master, ticker)
    context = ResearchContext(
        ticker=ticker,
        as_of_date=args.as_of_date,
        latest_filing=_filing_dict(args),
        latest_filing_summary=_summary_dict(args, signal_row),
        signal_row=signal_row,
        historical_rows=_historical_rows(master, ticker),
        current_price=args.current_price,
    )
    outputs = build_research_outputs(context)
    paths = write_research_outputs(outputs, Path(args.output_dir))
    for kind, path in paths.items():
        print(f"{kind}={path}")


if __name__ == "__main__":
    main()
