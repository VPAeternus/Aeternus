from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

import pandas as pd

from src.config.cache_paths import market_cache_root
from earnings_8k_sec_parser_pipeline import (
    evidence_buckets,
    earnings_score,
    merged_structured_extracts,
)
from sec_document_quality_gate import doc_cache_paths


ROOT = Path(__file__).resolve().parents[1]
MARKET_CACHE_DIR = market_cache_root()
DEFAULT_INPUT = ROOT / "Growth" / "earnings_8k_sec_parser" / "sec_document_quality_passed_2024Q3_revenue_buckets.csv"
DEFAULT_OUTPUT = ROOT / "Growth" / "earnings_8k_sec_parser" / "bucket_score_lt_100m_2024Q3.csv"
RETURN_HORIZONS = [10, 20, 30, 60, 90]


def read_csv(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_price_panels() -> dict[str, pd.DataFrame]:
    panels: dict[str, pd.DataFrame] = {}
    for path in sorted(MARKET_CACHE_DIR.glob("prices*.parquet")):
        try:
            frame = pd.read_parquet(path)
        except Exception:
            continue
        if not isinstance(frame.columns, pd.MultiIndex):
            continue
        for ticker in sorted(set(frame.columns.get_level_values(0))):
            if ticker in panels:
                continue
            fields = [field for sym, field in frame.columns if sym == ticker]
            needed = [field for field in ["Open", "High", "Low", "Close", "Volume"] if field in fields]
            if {"Open", "Close"} - set(needed):
                continue
            panel = frame[ticker][needed].copy()
            panel.index = pd.to_datetime(panel.index)
            panels[ticker] = panel
    return panels


def return_fields(panel: pd.DataFrame | None, filed: str) -> dict[str, str]:
    fields = {"tradable_date": "", "entry_open": ""}
    for horizon in RETURN_HORIZONS:
        fields[f"return_{horizon}d_pct"] = ""
    if panel is None or panel.empty or not filed:
        return fields
    target = pd.Timestamp(filed) + pd.Timedelta(days=1)
    eligible = panel[panel.index.normalize() >= target.normalize()].dropna(subset=["Open", "Close"])
    if eligible.empty:
        return fields
    entry = eligible.iloc[0]
    entry_open = float(entry["Open"])
    fields["tradable_date"] = eligible.index[0].strftime("%Y-%m-%d")
    fields["entry_open"] = f"{entry_open:.6f}"
    for horizon in RETURN_HORIZONS:
        exit_target = eligible.index[0] + pd.Timedelta(days=horizon)
        exits = panel[panel.index.normalize() >= exit_target.normalize()].dropna(subset=["Close"])
        if exits.empty:
            continue
        exit_close = float(exits.iloc[0]["Close"])
        fields[f"return_{horizon}d_pct"] = f"{((exit_close / entry_open) - 1) * 100:.4f}"
    return fields


def cached_exhibit_text(row: dict[str, str]) -> tuple[str, int]:
    parts: list[str] = []
    for document in [x for x in row.get("exhibit_docs", "").split(";") if x]:
        _, text_path = doc_cache_paths(row["ticker"], row["event_accession"], document)
        if text_path.exists():
            parts.append(text_path.read_text(encoding="utf-8", errors="ignore"))
    return "\n\n".join(parts), len(parts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score one revenue bucket from cached SEC docs")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--bucket", default="<$100M")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    prices = load_price_panels()
    rows = [row for row in read_csv(args.input) if row.get("revenue_bucket") == args.bucket]
    output: list[dict[str, Any]] = []
    for row in rows:
        text, exhibit_doc_count = cached_exhibit_text(row)
        buckets = evidence_buckets(text)
        extracts = merged_structured_extracts(text, None)
        score = earnings_score(text, extracts)
        returns = return_fields(prices.get(row["ticker"]), row.get("event_dates", "").split(";")[0])
        output.append({
            "quarter": row.get("quarter", ""),
            "ticker": row["ticker"],
            "event_date": row.get("event_dates", "").split(";")[0],
            "revenue_bucket": row.get("revenue_bucket", ""),
            "revenue_value_millions": row.get("revenue_value_millions", ""),
            "avg_dollar_volume_60d": row.get("avg_dollar_volume_60d", ""),
            "earnings_score": score["earnings_score"],
            "earnings_score_bucket": score["earnings_score_bucket"],
            "guidance_torque": score["guidance_torque"],
            "earnings_torque": score["earnings_torque"],
            "segment_wave_torque": score["segment_wave_torque"],
            "margin_quality": score["margin_quality"],
            "warning_penalty": score["warning_penalty"],
            "guidance_vs_current_pct": score["guidance_vs_current_pct"],
            "score_status": score["score_status"],
            "score_missing_fields": ";".join(score["score_missing_fields"]),
            "extraction_source": extracts["source_method"],
            "quarter_revenue_millions": extracts["quarter_revenue_millions"],
            "quarter_revenue_yoy_pct": extracts["quarter_revenue_yoy_pct"],
            "guidance_revenue_millions": extracts["guidance_revenue_millions"],
            "numeric_evidence_count": len(buckets["numeric_evidence"]),
            "guidance_evidence_count": len(buckets["guidance_evidence"]),
            "wave_or_demand_evidence_count": len(buckets["wave_or_demand_evidence"]),
            "warning_or_risk_evidence_count": len(buckets["warning_or_risk_evidence"]),
            "exhibit_doc_count": exhibit_doc_count,
            "exhibit_text_len": len(text),
            **returns,
        })
    write_csv(args.output, output)
    print(f"bucket={args.bucket} rows={len(output)} wrote={args.output}")


if __name__ == "__main__":
    main()
