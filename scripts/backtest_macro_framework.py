#!/usr/bin/env python3
"""Research-only macro framework backtest.

This script downloads historical ETF data via yfinance, computes deterministic
macro snapshots, joins forward returns for default horizons, emits regime and
sector tables, and optionally runs a macro-on vs macro-neutral dealflow ablation
from a candidate JSON/CSV file.

Disclaimer: yfinance/current FRED histories are not true point-in-time data.
Use vintage/release-date aligned inputs for production-grade validation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from tradingagents.backtesting.macro import (
    DEFAULT_HORIZONS,
    attach_forward_returns,
    build_historical_macro_snapshots,
    build_performance_table,
    run_macro_ablation,
)
from tradingagents.backtesting.macro.regime_tables import build_sector_performance_table
from tradingagents.agents.utils.macro_engine import _TICKERS as MACRO_TICKERS

SECTOR_ETFS = {
    "XLK": "Technology",
    "XLV": "Healthcare",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLI": "Industrials",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLB": "Materials",
    "XLC": "Communication Services",
    "XLRE": "Real Estate",
    "XLU": "Utilities",
}

DISCLAIMER = "research_only_not_true_pit_unless_inputs_are_vintage_or_release_aligned"


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest Aeternus macro framework research signals")
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--end", default="")
    parser.add_argument("--frequency", default="W-FRI", help="Snapshot frequency, e.g. W-FRI or ME")
    parser.add_argument("--output-dir", default="eval_results/macro_backtest")
    parser.add_argument("--fred-csv", default="", help="Optional CSV indexed by date with dgs10/dgs2/cpi_yoy columns")
    parser.add_argument("--fred-release-lag-days", type=int, default=0)
    parser.add_argument("--candidate-file", default="", help="Optional dealflow candidate JSON/CSV for ablation")
    parser.add_argument("--candidate-return-col", default="fwd_20d")
    parser.add_argument("--top-k", type=int, default=20)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    tickers = sorted(set(MACRO_TICKERS) | set(SECTOR_ETFS) | {"SPY"})
    prices = fetch_yfinance_closes(tickers, start=args.start, end=args.end or None)
    fred = load_fred_csv(args.fred_csv) if args.fred_csv else None

    snapshots = build_historical_macro_snapshots(
        prices,
        fred_history=fred,
        snapshot_frequency=args.frequency,
        fred_release_lag_days=args.fred_release_lag_days,
    )
    return_symbols = ["SPY", *SECTOR_ETFS.keys()]
    labeled = attach_forward_returns(snapshots, prices, horizons=DEFAULT_HORIZONS, symbols=return_symbols)

    regime_table = build_performance_table(labeled, group_by=("regime",))
    sector_rows = explode_sector_returns(labeled, SECTOR_ETFS)
    sector_table = build_sector_performance_table(sector_rows, return_columns=[col for col in sector_rows.columns if col.startswith("fwd_")])

    write_frame(labeled, output_dir / "macro_snapshots_labeled.csv")
    write_frame(regime_table, output_dir / "regime_performance.csv")
    write_frame(sector_table, output_dir / "sector_performance.csv")

    manifest = {
        "disclaimer": DISCLAIMER,
        "start": args.start,
        "end": args.end or None,
        "frequency": args.frequency,
        "horizons": list(DEFAULT_HORIZONS),
        "tickers": tickers,
        "fred_release_lag_days": args.fred_release_lag_days,
        "outputs": [
            "macro_snapshots_labeled.csv",
            "regime_performance.csv",
            "sector_performance.csv",
        ],
    }

    if args.candidate_file:
        candidates = load_candidates(args.candidate_file)
        ablation = run_macro_ablation(
            candidates,
            forward_return_col=args.candidate_return_col,
            top_k=args.top_k,
        )
        write_frame(ablation["ranked"], output_dir / "dealflow_macro_ablation_ranked.csv")
        write_frame(ablation["selected"], output_dir / "dealflow_macro_ablation_selected.csv")
        write_frame(ablation["summary"], output_dir / "dealflow_macro_ablation_summary.csv")
        manifest["outputs"].extend(
            [
                "dealflow_macro_ablation_ranked.csv",
                "dealflow_macro_ablation_selected.csv",
                "dealflow_macro_ablation_summary.csv",
            ]
        )

    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    print(f"Wrote macro backtest artifacts to {output_dir}")
    print(f"DISCLAIMER: {DISCLAIMER}")


def fetch_yfinance_closes(tickers: Iterable[str], *, start: str, end: str | None) -> pd.DataFrame:
    import yfinance as yf

    raw = yf.download(
        list(tickers),
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned no data")
    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" in raw.columns.get_level_values(0):
            closes = raw.xs("Close", axis=1, level=0)
        elif "Close" in raw.columns.get_level_values(1):
            closes = raw.xs("Close", axis=1, level=1)
        else:
            raise RuntimeError("yfinance response did not include Close columns")
    else:
        closes = raw[["Close"]].rename(columns={"Close": list(tickers)[0]})
    closes.index = pd.to_datetime(closes.index)
    return closes.sort_index()


def load_fred_csv(path: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    date_col = "date" if "date" in frame.columns else frame.columns[0]
    frame[date_col] = pd.to_datetime(frame[date_col])
    return frame.set_index(date_col).sort_index()


def load_candidates(path: str) -> pd.DataFrame:
    p = Path(path)
    if p.suffix.lower() == ".csv":
        frame = pd.read_csv(p)
        if "subscores" in frame.columns:
            frame["subscores"] = frame["subscores"].apply(lambda x: json.loads(x) if isinstance(x, str) else x)
        return frame
    payload = json.loads(p.read_text())
    if isinstance(payload, dict):
        for key in ("candidates", "rows", "items"):
            if isinstance(payload.get(key), list):
                return pd.DataFrame(payload[key])
    if isinstance(payload, list):
        return pd.DataFrame(payload)
    raise ValueError(f"Unsupported candidate file shape: {path}")


def explode_sector_returns(labeled: pd.DataFrame, sector_etfs: dict[str, str]) -> pd.DataFrame:
    rows = []
    for _, row in labeled.iterrows():
        base = {"snapshot_date": row.get("snapshot_date"), "regime": row.get("regime")}
        for symbol, sector in sector_etfs.items():
            out = dict(base)
            out["symbol"] = symbol
            out["sector"] = sector
            for horizon in DEFAULT_HORIZONS:
                src = f"fwd_{symbol}_{horizon}d"
                if src in row:
                    out[f"fwd_sector_{horizon}d"] = row[src]
            rows.append(out)
    return pd.DataFrame(rows)


def write_frame(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False)


if __name__ == "__main__":
    main()
