from __future__ import annotations

import argparse
import csv
import json
import re
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd
from bs4 import BeautifulSoup

from src.config.cache_paths import market_cache_root
from earnings_8k_sec_parser_pipeline import (
    clean,
    evidence_buckets,
    earnings_score,
    extract_tables,
    parse_semantic_text,
)
from sec_document_quality_gate import doc_cache_paths


ROOT = Path(__file__).resolve().parents[1]
MARKET_CACHE_DIR = market_cache_root()
DEFAULT_AUDIT = ROOT / "Growth" / "earnings_8k_sec_parser" / "filing_coverage_audit_2024Q3.csv"
DEFAULT_XBRL = ROOT / "Growth" / "earnings_8k_sec_parser" / "xbrl_universal_features_through_ocf_2024Q3_100m_plus_index_mandatory.csv"
DEFAULT_OUTPUT_ROOT = ROOT / "Growth" / "earnings_8k_sec_parser" / "local_extractions_2024Q3"
DEFAULT_MANIFEST = ROOT / "Growth" / "earnings_8k_sec_parser" / "local_earnings_extraction_manifest_2024Q3.csv"
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
            if not {"Open", "Close"}.issubset(fields):
                continue
            panel = frame[ticker][["Open", "Close"]].copy()
            panel.index = pd.to_datetime(panel.index)
            if panel.index.tz is not None:
                panel.index = panel.index.tz_localize(None)
            panels[ticker] = panel
    return panels


def return_fields(panel: pd.DataFrame | None, filed: str) -> dict[str, str]:
    fields = {"tradable_date": "", "entry_open": ""}
    for horizon in RETURN_HORIZONS:
        fields[f"return_{horizon}d_pct"] = ""
    if panel is None or panel.empty or not filed:
        return fields
    frame = panel.dropna(subset=["Open", "Close"]).sort_index()
    target = pd.Timestamp(filed) + pd.Timedelta(days=1)
    entry_rows = frame[frame.index.normalize() >= target.normalize()]
    if entry_rows.empty:
        return fields
    entry_open = float(entry_rows.iloc[0]["Open"])
    fields["tradable_date"] = entry_rows.index[0].strftime("%Y-%m-%d")
    fields["entry_open"] = f"{entry_open:.6f}"
    for horizon in RETURN_HORIZONS:
        exit_target = entry_rows.index[0] + pd.Timedelta(days=horizon)
        exit_rows = frame[frame.index.normalize() >= exit_target.normalize()]
        if exit_rows.empty:
            continue
        exit_close = float(exit_rows.iloc[0]["Close"])
        fields[f"return_{horizon}d_pct"] = f"{((exit_close / entry_open) - 1) * 100:.4f}"
    return fields


def read_cached_text(ticker: str, accession: str, document: str) -> tuple[str, str]:
    _, text_path = doc_cache_paths(ticker, accession, document)
    if not text_path.exists():
        return "", str(text_path)
    return text_path.read_text(encoding="utf-8", errors="ignore"), str(text_path)


def read_cached_html(ticker: str, accession: str, document: str) -> str:
    html_path, _ = doc_cache_paths(ticker, accession, document)
    if not html_path.exists():
        return ""
    return html_path.read_text(encoding="utf-8", errors="ignore")


def html_to_text(html_text: str) -> str:
    soup = BeautifulSoup(html_text or "", "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return clean(soup.get_text(" "))


def safe_parse_semantic_text(html_text: str) -> tuple[str, list[dict[str, str]], str]:
    try:
        semantic_text, semantic_rows = parse_semantic_text(html_text)
        return semantic_text, semantic_rows, "sec_parser"
    except Exception as exc:
        return html_to_text(html_text), [], f"beautifulsoup_fallback:{type(exc).__name__}"


def money_to_millions(value: str, unit: str | None = None) -> float | None:
    value = str(value or "").replace("$", "").replace(",", "").strip()
    if not value or value in {"-", "—", "–"}:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    if unit and unit.lower().startswith("b"):
        return parsed * 1000
    return parsed


def first_number(text: str) -> float | None:
    match = re.search(r"\(?\$?\s*(-?[0-9][0-9,]*(?:\.[0-9]+)?)\)?", text)
    if not match:
        return None
    value = money_to_millions(match.group(1))
    if value is not None and "(" in match.group(0):
        value = -abs(value)
    return value


def directional_pct(text: str) -> float | None:
    lowered = text.lower()
    patterns = [
        r"(?:up|increased|grew|growth of)\s+([0-9]+(?:\.[0-9]+)?)\s*(?:%|percent)",
        r"([0-9]+(?:\.[0-9]+)?)\s*(?:%|percent)\s+(?:increase|growth)",
        r"(?:down|decreased|declined|decrease of|decline of)\s+([0-9]+(?:\.[0-9]+)?)\s*(?:%|percent)",
        r"([0-9]+(?:\.[0-9]+)?)\s*(?:%|percent)\s+(?:decrease|decline)",
    ]
    for idx, pattern in enumerate(patterns):
        match = re.search(pattern, lowered)
        if match:
            value = float(match.group(1))
            return -value if idx >= 2 else value
    return None


def row_has_revenue_label(cells: list[str]) -> bool:
    label = " ".join(cells[:3]).lower()
    if any(bad in label for bad in ["deferred revenue", "unearned revenue", "cost of revenue", "revenue recognition"]):
        return False
    return bool(re.search(r"\b(revenue|revenues|net sales|sales|total revenue|total revenues)\b", label))


def table_extracts(tables: list[dict[str, Any]]) -> dict[str, Any]:
    for table in tables:
        rows = table.get("rows", [])
        table_text = " ".join(
            [" ".join(map(str, table.get("columns", [])))]
            + [" ".join(map(str, row)) for row in rows[:8]]
        ).lower()
        scale = 1.0
        if "in thousands" in table_text or "thousands" in table_text:
            scale = 0.001
        elif "in billions" in table_text or "billions" in table_text:
            scale = 1000.0
        # SEC earnings tables most often state either millions or thousands.
        for idx, raw_row in enumerate(rows):
            cells = [clean(str(cell)) for cell in raw_row]
            if not row_has_revenue_label(cells):
                continue
            nums = [
                value * scale
                for cell in cells[1:]
                for value in [first_number(cell)]
                if value is not None
            ]
            if not nums:
                continue
            current = nums[0]
            prior = nums[1] if len(nums) > 1 else None
            yoy = ((current / prior) - 1) * 100 if prior not in {None, 0} else None
            # Avoid accidentally selecting per-share or percent rows.
            if abs(current) < 1:
                continue
            return {
                "quarter_revenue_millions": round(current, 4),
                "quarter_revenue_yoy_pct": round(yoy, 4) if yoy is not None else None,
                "revenue_evidence": " | ".join(cells[:6]),
                "revenue_table_index": table.get("table_index", ""),
            }
    return {}


def text_extracts(text: str) -> dict[str, Any]:
    revenue_patterns = [
        r"(?:revenue|revenues|net sales|sales)[^.]{0,120}?\$([0-9,.]+)\s*(billion|million)",
        r"\$([0-9,.]+)\s*(billion|million)[^.]{0,80}?(?:revenue|revenues|net sales|sales)",
    ]
    out: dict[str, Any] = {}
    for pattern in revenue_patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            out["quarter_revenue_millions"] = money_to_millions(match.group(1), match.group(2))
            snippet = clean(match.group(0))
            out["quarter_revenue_yoy_pct"] = directional_pct(snippet)
            out["revenue_evidence"] = snippet[:500]
            break
    guidance_match = re.search(
        r"(?:revenue|revenues|net sales|sales)[^.]{0,100}?(?:expect|expects|expected|forecast|project|projects|outlook|guidance)[^.]{0,120}?\$([0-9,.]+)\s*(billion|million)",
        text,
        flags=re.I,
    ) or re.search(
        r"(?:expect|expects|expected|forecast|project|projects|outlook|guidance)[^.]{0,140}?(?:revenue|revenues|net sales|sales)[^.]{0,120}?\$([0-9,.]+)\s*(billion|million)",
        text,
        flags=re.I,
    )
    if guidance_match:
        out["guidance_revenue_millions"] = money_to_millions(guidance_match.group(1), guidance_match.group(2))
        out["guidance_evidence"] = clean(guidance_match.group(0))[:500]
    return out


def numeric_extracts(semantic_text: str, tables: list[dict[str, Any]], xbrl: dict[str, str]) -> dict[str, Any]:
    table_values = table_extracts(tables)
    text_values = text_extracts(semantic_text)
    revenue = text_values.get("quarter_revenue_millions") or table_values.get("quarter_revenue_millions")
    yoy = text_values.get("quarter_revenue_yoy_pct")
    if yoy is None:
        yoy = table_values.get("quarter_revenue_yoy_pct")
    if revenue is None and xbrl.get("revenue_value"):
        revenue = round(float(xbrl["revenue_value"]) / 1_000_000, 4)
    # The active universe excludes >=$10B revenue companies; a single-quarter
    # extracted revenue above $10B is almost always an HTML table value in
    # thousands where the unit note lives outside the parsed table.
    if revenue is not None and revenue > 10_000:
        revenue = round(revenue / 1000, 4)
    return {
        "source_method": "sec_parser_table_xbrl",
        "quarter_revenue_millions": revenue,
        "quarter_revenue_yoy_pct": yoy,
        "quarter_revenue_qoq_pct": None,
        "guidance_revenue_millions": text_values.get("guidance_revenue_millions"),
        "guidance_revenue_low_millions": None,
        "guidance_revenue_high_millions": None,
        "guidance_gross_margin_pct": None,
        "qualitative": {},
        "evidence": [
            item for item in [
                {"field": "reported_results.revenue_millions", "quote": text_values.get("revenue_evidence") or table_values.get("revenue_evidence", "")},
                {"field": "reported_results.revenue_yoy_pct", "quote": table_values.get("revenue_evidence", "")},
                {"field": "forward_guidance.revenue_millions_midpoint", "quote": text_values.get("guidance_evidence", "")},
            ] if item["quote"]
        ],
        "missing_fields": [],
        "confidence": 0,
    }


def earnings_score_no_guidance_required(text: str, extracts: dict[str, Any]) -> dict[str, Any]:
    score = earnings_score(text, extracts, require_complete=False)
    required = {
        "quarter_revenue_millions": extracts.get("quarter_revenue_millions"),
        "quarter_revenue_yoy_pct": extracts.get("quarter_revenue_yoy_pct"),
    }
    missing = [key for key, value in required.items() if value in {None, ""}]
    if missing:
        score.update({
            "earnings_score": "",
            "earnings_score_bucket": "not_scored",
            "score_status": "missing_required_data",
            "score_missing_fields": missing,
        })
    else:
        score["score_status"] = "scored"
        score["score_missing_fields"] = []
    return score


def extract_row(row: dict[str, str], xbrl: dict[str, str], panel: pd.DataFrame | None, output_root: Path) -> dict[str, Any]:
    ticker = row["ticker"]
    accession = row["event_accession"]
    event_date = (row.get("event_dates", "").split(";") or [""])[0]
    primary_text, primary_text_path = read_cached_text(ticker, accession, row.get("primary_8k_doc", ""))
    exhibit_parts: list[str] = []
    exhibit_html_parts: list[str] = []
    exhibit_paths: list[str] = []
    for document in [item for item in row.get("exhibit_docs", "").split(";") if item]:
        text, path = read_cached_text(ticker, accession, document)
        if text:
            exhibit_parts.append(text)
        exhibit_paths.append(path)
        html_text = read_cached_html(ticker, accession, document)
        if html_text:
            exhibit_html_parts.append(html_text)
    exhibit_text = "\n\n".join(exhibit_parts)
    exhibit_html = "\n\n".join(exhibit_html_parts)
    combined_text = "\n\n".join(part for part in [primary_text, exhibit_text] if part)
    semantic_status = "text_cache_only"
    if exhibit_html:
        semantic_text, semantic_rows, semantic_status = safe_parse_semantic_text(exhibit_html)
    else:
        semantic_text, semantic_rows = exhibit_text or combined_text, []
    tables = extract_tables(exhibit_html) if exhibit_html else []
    extraction_text = semantic_text or exhibit_text or combined_text
    buckets = evidence_buckets(extraction_text)
    extracts = numeric_extracts(extraction_text, tables, xbrl)
    score = earnings_score_no_guidance_required(extraction_text, extracts)
    returns = return_fields(panel, event_date)

    payload = {
        "metadata": {
            "quarter": row.get("quarter", ""),
            "ticker": ticker,
            "cik": row.get("cik", ""),
            "event_date": event_date,
            "event_accession": accession,
            "primary_8k_doc": row.get("primary_8k_doc", ""),
            "exhibit_docs": [item for item in row.get("exhibit_docs", "").split(";") if item],
            "primary_text_path": primary_text_path,
            "exhibit_text_paths": exhibit_paths,
            "revenue_bucket": row.get("revenue_bucket", ""),
        },
        "xbrl": xbrl,
        "evidence_buckets": buckets,
        "semantic_rows": semantic_rows[:200],
        "tables": tables,
        "financial_extracts": extracts,
        "earnings_score": score,
        "returns": returns,
        "text_stats": {
            "primary_text_len": len(primary_text),
            "exhibit_text_len": len(exhibit_text),
            "combined_text_len": len(combined_text),
            "semantic_text_len": len(semantic_text),
            "table_count": len(tables),
            "semantic_parse_status": semantic_status,
        },
    }
    ticker_dir = output_root / ticker
    ticker_dir.mkdir(parents=True, exist_ok=True)
    out_json = (ticker_dir / f"{ticker}_{event_date}_{accession.replace('-', '')}.json").resolve()
    out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "quarter": row.get("quarter", ""),
        "ticker": ticker,
        "event_date": event_date,
        "event_accession": accession,
        "revenue_bucket": row.get("revenue_bucket", ""),
        "revenue_value": xbrl.get("revenue_value", ""),
        "net_income_value": xbrl.get("net_income_value", ""),
        "assets_value": xbrl.get("assets_value", ""),
        "financing_cash_flow_value": xbrl.get("financing_cash_flow_value", ""),
        "investing_cash_flow_value": xbrl.get("investing_cash_flow_value", ""),
        "operating_cash_flow_value": xbrl.get("operating_cash_flow_value", ""),
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
        "quarter_revenue_qoq_pct": extracts["quarter_revenue_qoq_pct"],
        "guidance_revenue_millions": extracts["guidance_revenue_millions"],
        "guidance_gross_margin_pct": extracts["guidance_gross_margin_pct"],
        "numeric_evidence_count": len(buckets["numeric_evidence"]),
        "guidance_evidence_count": len(buckets["guidance_evidence"]),
        "wave_or_demand_evidence_count": len(buckets["wave_or_demand_evidence"]),
        "warning_or_risk_evidence_count": len(buckets["warning_or_risk_evidence"]),
        "primary_text_len": len(primary_text),
        "exhibit_text_len": len(exhibit_text),
        "semantic_text_len": len(semantic_text),
        "semantic_parse_status": semantic_status,
        "table_count": len(tables),
        "json_path": str(out_json.relative_to(ROOT)),
        **returns,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local Python earnings extraction from cached 8-K/exhibit text")
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--xbrl", type=Path, default=DEFAULT_XBRL)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_root = args.output_root.resolve()
    args.manifest = args.manifest.resolve()
    audit_rows = [
        row for row in read_csv(args.audit)
        if row.get("earnings_event_ready_for_local_extraction") == "True"
    ]
    if args.limit is not None:
        audit_rows = audit_rows[: args.limit]
    xbrl_rows = {row["ticker"]: row for row in read_csv(args.xbrl)}
    prices = load_price_panels()
    manifest: list[dict[str, Any]] = []
    for idx, row in enumerate(audit_rows, start=1):
        manifest.append(extract_row(row, xbrl_rows.get(row["ticker"], {}), prices.get(row["ticker"]), args.output_root))
        if idx % 100 == 0:
            print(f"{idx}/{len(audit_rows)}", flush=True)
    write_csv(args.manifest, manifest)
    scored = sum(row["score_status"] == "scored" for row in manifest)
    print(f"rows={len(manifest)} scored={scored} not_scored={len(manifest)-scored}")
    missing_counts: dict[str, int] = {}
    for row in manifest:
        if row["score_status"] == "scored":
            continue
        for field in str(row["score_missing_fields"]).split(";"):
            if field:
                missing_counts[field] = missing_counts.get(field, 0) + 1
    for field, count in sorted(missing_counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"{field}: {count}")
    print(f"wrote {args.manifest}")
    print(f"wrote JSON under {args.output_root}")


if __name__ == "__main__":
    main()
