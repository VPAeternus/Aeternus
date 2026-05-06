from __future__ import annotations

import argparse
import csv
import html
import json
import re
import time
from io import StringIO
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd
from sec_parser import Edgar10QParser

from src.config.cache_paths import sec_cache_root

try:
    import yfinance as yf
except Exception:  # pragma: no cover - lets extraction run without price package.
    yf = None

try:
    from edgar import Filing as EdgarFiling
    from edgar import set_identity as edgar_set_identity
except Exception:  # pragma: no cover - lets extraction run without edgartools.
    EdgarFiling = None
    edgar_set_identity = None


USER_AGENT = "AeternusAutoResearch research@aeternusholdings.com"
ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = sec_cache_root()
CACHE_HTML = CACHE_ROOT / "filings_html"
CACHE_TEXT = CACHE_ROOT / "filings_text"
OUTPUT_ROOT = ROOT / "Growth" / "earnings_8k_sec_parser"
INVENTORY_PATH = ROOT / "Growth" / "cached_10q_10k_ticker_inventory.csv"
RETURN_HORIZONS = [10, 20, 30, 60, 90]
MANIFEST_KEY = ["ticker", "filed", "form"]
LLM_SCHEMA_VERSION = "earnings_8k_llm_extraction_v1"


@dataclass(frozen=True)
class CompanyRef:
    ticker: str
    cik: str
    cik_int: str
    title: str


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def number(value: str) -> int | float | None:
    value = value.replace(",", "").replace("$", "").strip()
    if not value:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return int(parsed) if parsed.is_integer() else parsed


def money_to_millions(value: str, unit: str) -> int | float | None:
    parsed = number(value)
    if parsed is None:
        return None
    return int(round(float(parsed) * 1000)) if unit.lower().startswith("billion") else parsed


def directional_pct(text: str) -> int | float | None:
    match = re.search(r"(up|down|increased|decreased|grew|declined)\s+(\d+(?:\.\d+)?)\s*(?:percent|%)", text, flags=re.I)
    if not match:
        return None
    parsed = number(match.group(2))
    if parsed is None:
        return None
    sign = -1 if match.group(1).lower() in {"down", "decreased", "declined"} else 1
    return sign * parsed


def fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def fetch_json(url: str) -> dict:
    return json.loads(fetch(url))


def company_refs() -> dict[str, CompanyRef]:
    data = fetch_json("https://www.sec.gov/files/company_tickers.json")
    refs: dict[str, CompanyRef] = {}
    for item in data.values():
        ticker = str(item["ticker"]).upper()
        cik_int = str(item["cik_str"])
        refs[ticker] = CompanyRef(
            ticker=ticker,
            cik=cik_int.zfill(10),
            cik_int=cik_int,
            title=str(item["title"]),
        )
    return refs


def cached_10q_10k_tickers() -> list[str]:
    if INVENTORY_PATH.exists():
        return [row["ticker"] for row in csv.DictReader(INVENTORY_PATH.open())]
    packet_dir = CACHE_ROOT / "filing_packets"
    return sorted({p.name.split("_", 1)[0].upper() for p in packet_dir.glob("*.json")})


def filing_rows(ref: CompanyRef, start_date: str, end_date: str) -> tuple[list[dict], list[dict]]:
    recent = fetch_json(f"https://data.sec.gov/submissions/CIK{ref.cik}.json")["filings"]["recent"]
    earnings: list[dict] = []
    periodic: list[dict] = []
    for idx, form in enumerate(recent["form"]):
        filed = recent["filingDate"][idx]
        if filed < start_date or filed > end_date:
            continue
        if form in {"8-K", "8-K/A"} and "2.02" in (recent["items"][idx] or ""):
            earnings.append({key: recent[key][idx] for key in [
                "accessionNumber",
                "filingDate",
                "reportDate",
                "acceptanceDateTime",
                "form",
                "items",
                "primaryDocument",
            ]})
        if form in {"10-Q", "10-K"}:
            periodic.append({
                "form": form,
                "filed": filed,
                "accession": recent["accessionNumber"][idx],
                "primary_document": recent["primaryDocument"][idx],
            })
    return sorted(earnings, key=lambda row: row["filingDate"]), sorted(periodic, key=lambda row: row["filed"])


def match_periodic(filed: str, periodic: list[dict]) -> dict:
    candidates = [row for row in periodic if row["filed"] >= filed]
    return candidates[0] if candidates else {"form": "", "filed": "", "accession": "", "primary_document": ""}


def filing_url(ref: CompanyRef, accn: str, document: str) -> str:
    compact = accn.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{ref.cik_int}/{compact}/{document}"


def index_names(ref: CompanyRef, accn: str) -> list[str]:
    compact = accn.replace("-", "")
    payload = fetch_json(f"https://www.sec.gov/Archives/edgar/data/{ref.cik_int}/{compact}/index.json")
    return [item["name"] for item in payload.get("directory", {}).get("item", [])]


def is_sec_generated_html(name: str) -> bool:
    low = name.lower()
    return (
        "index" in low
        or "headers" in low
        or re.fullmatch(r"r\d+\.htm[l]?", low) is not None
        or low in {"show.js", "report.css"}
    )


def find_ex99(ref: CompanyRef, accn: str, primary_document: str) -> tuple[str, str]:
    names = index_names(ref, accn)
    html_names = [
        name for name in names
        if name.lower().endswith((".htm", ".html"))
        and name != primary_document
        and not is_sec_generated_html(name)
    ]
    candidates = [
        name for name in html_names
        if re.search(r"ex[-_]?99|ex99|ex991|exhibit[-_]?99", name, re.I)
    ]
    if not candidates:
        candidates = [
            name for name in html_names
            if re.search(r"earn|result|financial|release|press|pr\.htm", name, re.I)
        ]
    if not candidates:
        candidates = html_names
    name = candidates[0] if candidates else primary_document
    return name, filing_url(ref, accn, name)


def element_text(element: object) -> str:
    value = getattr(element, "text", "")
    if callable(value):
        try:
            value = value()
        except Exception:
            value = ""
    return str(value or "")


def parse_semantic_text(html_text: str) -> tuple[str, list[dict]]:
    elements = Edgar10QParser().parse(html_text)
    semantic_rows = []
    parts = []
    for element in elements:
        text = clean(element_text(element))
        if not text:
            continue
        row = {
            "type": type(element).__name__,
            "text": text,
        }
        semantic_rows.append(row)
        parts.append(text)
    return "\n".join(parts), semantic_rows


def extract_tables(html_text: str, limit: int = 12) -> list[dict[str, object]]:
    try:
        frames = pd.read_html(StringIO(html_text))
    except Exception:
        return []
    tables: list[dict[str, object]] = []
    for idx, frame in enumerate(frames[:limit]):
        normalized = frame.fillna("").astype(str)
        rows = [
            [clean(cell) for cell in row]
            for row in normalized.head(40).values.tolist()
        ]
        tables.append({
            "table_index": idx,
            "shape": [int(frame.shape[0]), int(frame.shape[1])],
            "columns": [clean(str(column)) for column in frame.columns.tolist()],
            "rows": rows,
        })
    return tables


def edgartools_context(ref: CompanyRef, row: dict) -> dict[str, object]:
    if EdgarFiling is None or edgar_set_identity is None:
        return {"available": False, "error": "edgartools_not_importable"}
    try:
        edgar_set_identity(USER_AGENT)
        filing = EdgarFiling(
            cik=int(ref.cik_int),
            company=ref.title,
            form=row["form"],
            filing_date=row["filingDate"],
            accession_no=row["accessionNumber"],
        )
        filing_text = filing.text()
        return {
            "available": True,
            "filing_url": filing.url,
            "text_char_count": len(filing_text),
            "attachments_preview": clean(str(filing.attachments))[:2000],
            "exhibits_preview": clean(str(filing.exhibits))[:2000],
        }
    except Exception as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}


def snippets_for_patterns(text: str, patterns: list[str], limit: int = 6) -> list[str]:
    snippets: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.I):
            snippet = clean(match.group(0))
            if snippet and snippet not in snippets:
                snippets.append(snippet[:420])
            if len(snippets) >= limit:
                return snippets
    return snippets


def evidence_buckets(text: str) -> dict[str, list[str]]:
    return {
        "numeric_evidence": snippets_for_patterns(text, [
            r"(?:revenue|revenues|net sales|sales) (?:of|were|was|totaled|increased|decreased)[^.]{0,220}\.",
            r"(?:GAAP|Non-GAAP)? ?(?:gross margin|operating income|net income|earnings per share|EPS)[^.]{0,220}\.",
            r"(?:cash flow|free cash flow|backlog)[^.]{0,220}\.",
        ]),
        "guidance_evidence": snippets_for_patterns(text, [
            r"(?:guidance|outlook)[^.]{0,260}\.",
            r"(?:expects|expected|forecast|anticipates|projects)[^.]{0,260}\.",
        ]),
        "wave_or_demand_evidence": snippets_for_patterns(text, [
            r"(?:demand|customer|customers|backlog|orders|bookings)[^.]{0,260}\.",
            r"(?:AI|artificial intelligence|data center|datacenter|cloud|optical|network|storage|memory|power)[^.]{0,260}\.",
            r"(?:capacity|supply|shipments|product cycle|ramp)[^.]{0,260}\.",
        ]),
        "warning_or_risk_evidence": snippets_for_patterns(text, [
            r"(?:preliminary|shortfall|weaker|soft demand|inventory|charge|impairment|delay|delayed|export control|restriction)[^.]{0,260}\.",
            r"(?:decline|decrease|loss|headwind|challenging|uncertain)[^.]{0,260}\.",
        ]),
    }


def regex_financial_extracts(text: str) -> dict[str, object]:
    revenue_match = re.search(
        r"(?:revenue|revenues|net sales|sales)[^.]{0,80}?\$([0-9,.]+)\s*(billion|million)",
        text,
        flags=re.I,
    )
    guidance_match = re.search(
        r"(?:revenue|revenues|net sales|sales) (?:is|are)? ?(?:expected|forecast|projected)[^.]{0,80}?\$([0-9,.]+)\s*(billion|million)",
        text,
        flags=re.I,
    )
    guidance_margin_match = re.search(
        r"(?:non-GAAP )?gross margins? (?:is|are)? ?(?:expected|forecast|projected)[^.]{0,80}?(\d+(?:\.\d+)?)\s*(?:percent|%)",
        text,
        flags=re.I,
    )
    revenue_context = clean(revenue_match.group(0)) if revenue_match else ""
    current_revenue = money_to_millions(revenue_match.group(1), revenue_match.group(2)) if revenue_match else None
    guidance_revenue = money_to_millions(guidance_match.group(1), guidance_match.group(2)) if guidance_match else None
    return {
        "quarter_revenue_millions": current_revenue,
        "quarter_revenue_yoy_pct": directional_pct(revenue_context),
        "guidance_revenue_millions": guidance_revenue,
        "guidance_gross_margin_pct": number(guidance_margin_match.group(1)) if guidance_margin_match else None,
    }


def empty_llm_extraction() -> dict[str, object]:
    return {
        "schema_version": LLM_SCHEMA_VERSION,
        "source_method": "",
        "reported_period": {"period_text": "", "period_end_date": ""},
        "reported_results": {
            "revenue_millions": None,
            "revenue_yoy_pct": None,
            "revenue_qoq_pct": None,
            "gross_margin_pct": None,
            "non_gaap_gross_margin_pct": None,
            "eps": None,
            "non_gaap_eps": None,
        },
        "forward_guidance": {
            "revenue_millions_midpoint": None,
            "revenue_low_millions": None,
            "revenue_high_millions": None,
            "revenue_growth_yoy_pct": None,
            "gross_margin_pct": None,
            "non_gaap_gross_margin_pct": None,
            "guide_direction": "",
        },
        "qualitative": {
            "demand_signal": "",
            "wave_signal": "",
            "margin_signal": "",
            "risk_signal": "",
            "customer_signal": "",
        },
        "evidence": [],
        "missing_fields": [],
        "confidence": 0,
    }


def llm_extraction_path(llm_dir: Path | None, base: str) -> Path | None:
    return None if llm_dir is None else llm_dir / f"{base}.json"


def load_llm_extraction(llm_dir: Path | None, base: str) -> dict[str, object] | None:
    path = llm_extraction_path(llm_dir, base)
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def merged_structured_extracts(text: str, llm_extraction: dict[str, object] | None) -> dict[str, object]:
    regex_extracts = regex_financial_extracts(text)
    structured = empty_llm_extraction()
    structured["source_method"] = "llm_json" if llm_extraction else "regex_fallback"
    if llm_extraction:
        structured.update(llm_extraction)
    reported = structured.get("reported_results", {}) if isinstance(structured.get("reported_results"), dict) else {}
    guidance = structured.get("forward_guidance", {}) if isinstance(structured.get("forward_guidance"), dict) else {}
    if llm_extraction:
        return {
            "source_method": structured.get("source_method", ""),
            "quarter_revenue_millions": reported.get("revenue_millions"),
            "quarter_revenue_yoy_pct": reported.get("revenue_yoy_pct"),
            "quarter_revenue_qoq_pct": reported.get("revenue_qoq_pct"),
            "guidance_revenue_millions": guidance.get("revenue_millions_midpoint"),
            "guidance_revenue_low_millions": guidance.get("revenue_low_millions"),
            "guidance_revenue_high_millions": guidance.get("revenue_high_millions"),
            "guidance_gross_margin_pct": guidance.get("non_gaap_gross_margin_pct") or guidance.get("gross_margin_pct"),
            "qualitative": structured.get("qualitative", {}),
            "evidence": structured.get("evidence", []),
            "missing_fields": structured.get("missing_fields", []),
            "confidence": structured.get("confidence", 0),
        }
    return {
        "source_method": structured.get("source_method", ""),
        "quarter_revenue_millions": reported.get("revenue_millions") or regex_extracts["quarter_revenue_millions"],
        "quarter_revenue_yoy_pct": reported.get("revenue_yoy_pct") if reported.get("revenue_yoy_pct") is not None else regex_extracts["quarter_revenue_yoy_pct"],
        "quarter_revenue_qoq_pct": reported.get("revenue_qoq_pct"),
        "guidance_revenue_millions": guidance.get("revenue_millions_midpoint") or regex_extracts["guidance_revenue_millions"],
        "guidance_revenue_low_millions": guidance.get("revenue_low_millions"),
        "guidance_revenue_high_millions": guidance.get("revenue_high_millions"),
        "guidance_gross_margin_pct": guidance.get("non_gaap_gross_margin_pct") or guidance.get("gross_margin_pct") or regex_extracts["guidance_gross_margin_pct"],
        "qualitative": structured.get("qualitative", {}),
        "evidence": structured.get("evidence", []),
        "missing_fields": structured.get("missing_fields", []),
        "confidence": structured.get("confidence", 0),
    }


def llm_input_payload(
    metadata: dict[str, object],
    semantic_text: str,
    semantic_rows: list[dict],
    tables: list[dict[str, object]],
    buckets: dict[str, list[str]],
) -> dict[str, object]:
    return {
        "task": "Extract earnings facts from this SEC 8-K EX-99.1. Return only JSON matching schema.",
        "schema_version": LLM_SCHEMA_VERSION,
        "metadata": metadata,
        "output_schema": empty_llm_extraction(),
        "instructions": [
            "Use only evidence present in the filing text or tables.",
            "Do not infer Wall Street expectations or external estimates.",
            "Normalize dollar values to millions.",
            "If a value is absent, set it to null and list the field in missing_fields.",
            "Every non-null numeric or qualitative field must be supported by a short evidence quote.",
        ],
        "evidence_buckets": buckets,
        "tables": tables,
        "semantic_elements": semantic_rows[:120],
        "semantic_text": semantic_text[:60000],
    }


def text_flags(text: str) -> dict[str, bool]:
    lower = text.lower()
    return {
        "preliminary_results": "preliminary financial results" in lower or "preliminary results" in lower,
        "revenue_shortfall": "shortfall" in lower or "weaker than forecasted" in lower,
        "inventory_charge": "inventory" in lower and "charge" in lower,
        "weak_demand": "weaker" in lower or "challenging market conditions" in lower or "soft demand" in lower,
        "export_control_hit": "export control" in lower or "license is required for exports" in lower,
        "record_revenue": "record revenue" in lower or "record quarterly revenue" in lower,
        "ai_wave": "artificial intelligence" in lower or "generative ai" in lower or "accelerated computing" in lower or "ai infrastructure" in lower,
        "data_center_strength": "data center" in lower and ("record" in lower or "up" in lower or "strong" in lower or "growth" in lower),
    }


def earnings_score(text: str, extracts: dict[str, object], require_complete: bool = True) -> dict[str, object]:
    current_revenue = extracts["quarter_revenue_millions"]
    guidance_revenue = extracts["guidance_revenue_millions"]
    required = {
        "quarter_revenue_millions": current_revenue,
        "quarter_revenue_yoy_pct": extracts["quarter_revenue_yoy_pct"],
        "guidance_revenue_millions": guidance_revenue,
    }
    missing_required = [key for key, value in required.items() if value in {None, ""}]
    if require_complete and missing_required:
        return {
            "earnings_score": "",
            "earnings_score_bucket": "not_scored",
            "guidance_torque": "",
            "earnings_torque": "",
            "segment_wave_torque": "",
            "margin_quality": "",
            "warning_penalty": "",
            "guidance_vs_current_pct": "",
            "score_status": "missing_required_data",
            "score_missing_fields": missing_required,
        }

    guidance_vs_current_pct = None
    if current_revenue and guidance_revenue:
        guidance_vs_current_pct = (float(guidance_revenue) / float(current_revenue) - 1) * 100

    guidance_torque = 0
    if guidance_vs_current_pct is not None:
        if guidance_vs_current_pct >= 20:
            guidance_torque = 3
        elif guidance_vs_current_pct >= 10:
            guidance_torque = 2
        elif guidance_vs_current_pct >= 0:
            guidance_torque = 1
        else:
            guidance_torque = -2

    earnings_torque = 0
    revenue_yoy = extracts["quarter_revenue_yoy_pct"]
    if revenue_yoy is not None:
        if float(revenue_yoy) >= 75:
            earnings_torque += 2
        elif float(revenue_yoy) >= 30:
            earnings_torque += 1
        elif float(revenue_yoy) < 0:
            earnings_torque -= 1

    flags = text_flags(text)
    wave_torque = min(sum(1 for key in ["ai_wave", "data_center_strength", "record_revenue"] if flags[key]), 3)
    margin_quality = 1 if (extracts["guidance_gross_margin_pct"] is not None and float(extracts["guidance_gross_margin_pct"]) >= 60) else 0
    warning_penalty = 0
    if flags["preliminary_results"]:
        warning_penalty += 2
    if flags["revenue_shortfall"]:
        warning_penalty += 2
    if flags["inventory_charge"]:
        warning_penalty += 1
    if flags["weak_demand"]:
        warning_penalty += 1
    if flags["export_control_hit"]:
        warning_penalty += 1
    warning_penalty = min(warning_penalty, 5)
    total = guidance_torque + earnings_torque + wave_torque + margin_quality - warning_penalty
    bucket = "high" if total >= 7 else "medium" if total >= 4 else "low" if total >= 1 else "avoid"
    return {
        "earnings_score": total,
        "earnings_score_bucket": bucket,
        "guidance_torque": guidance_torque,
        "earnings_torque": earnings_torque,
        "segment_wave_torque": wave_torque,
        "margin_quality": margin_quality,
        "warning_penalty": warning_penalty,
        "guidance_vs_current_pct": round(guidance_vs_current_pct, 4) if guidance_vs_current_pct is not None else "",
        "score_status": "scored",
        "score_missing_fields": [],
    }


def download_prices(ticker: str, rows: list[dict]) -> pd.DataFrame:
    if yf is None or not rows:
        return pd.DataFrame()
    min_date = min(row["filingDate"] for row in rows)
    start = (pd.Timestamp(min_date) - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    end = (pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    return yf.Ticker(ticker).history(start=start, end=end, interval="1d", auto_adjust=False)


def next_trading_day(history: pd.DataFrame, filed: str) -> str:
    target = pd.Timestamp(filed) + pd.Timedelta(days=1)
    eligible = history[history.index.strftime("%Y-%m-%d") >= target.strftime("%Y-%m-%d")]
    return "" if eligible.empty else eligible.index[0].strftime("%Y-%m-%d")


def return_fields(history: pd.DataFrame, filed: str) -> dict[str, str]:
    fields = {"tradable_date": "", "entry_open": ""}
    for horizon in RETURN_HORIZONS:
        fields[f"return_{horizon}d_pct"] = ""
    if history.empty:
        return fields
    tradable_date = next_trading_day(history, filed)
    if not tradable_date:
        return fields
    entry_rows = history[history.index.strftime("%Y-%m-%d") == tradable_date]
    if entry_rows.empty:
        return fields
    entry_open = float(entry_rows.iloc[0]["Open"])
    fields["tradable_date"] = tradable_date
    fields["entry_open"] = f"{entry_open:.6f}"
    for horizon in RETURN_HORIZONS:
        target = (pd.Timestamp(tradable_date) + pd.Timedelta(days=horizon)).strftime("%Y-%m-%d")
        exits = history[history.index.strftime("%Y-%m-%d") >= target]
        if exits.empty:
            continue
        exit_close = float(exits.iloc[0]["Close"])
        fields[f"return_{horizon}d_pct"] = f"{((exit_close / entry_open) - 1) * 100:.4f}"
    return fields


def quality_flags(primary_html: str, ex99_html: str, semantic_text: str, buckets: dict[str, list[str]], ex99_document: str) -> list[str]:
    flags: list[str] = []
    if not primary_html.strip():
        flags.append("missing_primary_html")
    if not ex99_html.strip():
        flags.append("missing_ex99_html")
    if len(semantic_text) < 1000:
        flags.append("short_semantic_text")
    if not ex99_document:
        flags.append("missing_ex99_document")
    for key in ["numeric_evidence", "guidance_evidence", "wave_or_demand_evidence"]:
        if not buckets.get(key):
            flags.append(f"missing_{key}")
    return flags


def process_ticker(ref: CompanyRef, start_date: str, end_date: str, sleep_seconds: float, llm_extractions_dir: Path | None, use_edgartools: bool) -> list[dict]:
    ticker_dir = OUTPUT_ROOT / ref.ticker
    raw_dir = sec_cache_root("earnings_8k_raw", ref.ticker)
    json_dir = ticker_dir / "json"
    semantic_dir = ticker_dir / "semantic_text"
    table_dir = ticker_dir / "tables"
    llm_input_dir = ticker_dir / "llm_inputs"
    for directory in [raw_dir, json_dir, semantic_dir, table_dir, llm_input_dir, CACHE_HTML, CACHE_TEXT]:
        directory.mkdir(parents=True, exist_ok=True)

    earnings, periodic = filing_rows(ref, start_date, end_date)
    price_history = download_prices(ref.ticker, earnings)
    manifest_rows: list[dict] = []
    for row in earnings:
        accn = row["accessionNumber"]
        filed = row["filingDate"]
        base = f"{ref.ticker}_{filed}_8-K_{accn}"
        primary_url = filing_url(ref, accn, row["primaryDocument"])
        ex99_document, ex99_url = find_ex99(ref, accn, row["primaryDocument"])

        primary_html = fetch(primary_url)
        ex99_html = fetch(ex99_url) if ex99_url else primary_html
        semantic_text, semantic_rows = parse_semantic_text(ex99_html)
        tables = extract_tables(ex99_html)
        edgar_context = edgartools_context(ref, row) if use_edgartools else {"available": False, "error": "disabled"}
        buckets = evidence_buckets(semantic_text)
        metadata = {
            "ticker": ref.ticker,
            "company": ref.title,
            "form": row["form"],
            "items": row["items"],
            "accession": accn,
            "sec_filing_date": filed,
            "sec_acceptance_datetime_utc": row["acceptanceDateTime"],
            "sec_report_date_event_date": row["reportDate"],
            "primary_document": row["primaryDocument"],
            "ex99_1_document": ex99_document,
            "sec_filing_url": primary_url,
            "ex99_1_url": ex99_url,
        }
        llm_extraction = load_llm_extraction(llm_extractions_dir, base)
        extracts = merged_structured_extracts(semantic_text, llm_extraction)
        score = earnings_score(semantic_text, extracts)
        returns = return_fields(price_history, filed)
        flags = quality_flags(primary_html, ex99_html, semantic_text, buckets, ex99_document)
        periodic_match = match_periodic(filed, periodic)
        metadata["periodic_filing_form"] = periodic_match["form"]
        metadata["periodic_filing_date"] = periodic_match["filed"]

        (raw_dir / f"{base}_primary.html").write_text(primary_html, encoding="utf-8")
        (raw_dir / f"{base}_ex99.html").write_text(ex99_html, encoding="utf-8")
        (semantic_dir / f"{base}_semantic.txt").write_text(semantic_text, encoding="utf-8")
        (table_dir / f"{base}_tables.json").write_text(json.dumps(tables, indent=2, ensure_ascii=False), encoding="utf-8")
        llm_buckets = buckets | {"edgartools_context": [json.dumps(edgar_context, ensure_ascii=False)[:4000]]}
        (llm_input_dir / f"{base}.json").write_text(
            json.dumps(llm_input_payload(metadata, semantic_text, semantic_rows, tables, llm_buckets), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (CACHE_HTML / f"{base}_primary.html").write_text(primary_html, encoding="utf-8")
        (CACHE_HTML / f"{base}_ex99_1.html").write_text(ex99_html, encoding="utf-8")
        (CACHE_TEXT / f"{base}_ex99_1.txt").write_text(semantic_text, encoding="utf-8")

        payload = {
            "metadata": metadata,
            "evidence_buckets": buckets,
            "tables": tables,
            "edgartools_context": edgar_context,
            "llm_input_path": str((llm_input_dir / f"{base}.json").relative_to(ROOT)),
            "llm_extraction": llm_extraction or {},
            "financial_extracts": extracts,
            "earnings_score": score,
            "returns": returns,
            "semantic_stats": {
                "semantic_char_count": len(semantic_text),
                "semantic_element_count": len(semantic_rows),
                "semantic_element_type_counts": {
                    key: sum(1 for item in semantic_rows if item["type"] == key)
                    for key in sorted({item["type"] for item in semantic_rows})
                },
            },
            "quality": {
                "quality_flags": flags,
                "quality_ok": not flags,
            },
        }
        (json_dir / f"{base}.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        manifest_rows.append({
            "ticker": ref.ticker,
            "filed": filed,
            "tradable_date": returns["tradable_date"],
            "form": row["form"],
            "items": row["items"],
            "acceptance_datetime_utc": row["acceptanceDateTime"],
            "primary_document": row["primaryDocument"],
            "ex99_1_document": ex99_document,
            "periodic_filing_form": periodic_match["form"],
            "periodic_filing_date": periodic_match["filed"],
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
            "llm_confidence": extracts["confidence"],
            "semantic_char_count": len(semantic_text),
            "semantic_element_count": len(semantic_rows),
            "table_count": len(tables),
            "edgartools_available": str(edgar_context.get("available", False)),
            "numeric_evidence_count": len(buckets["numeric_evidence"]),
            "guidance_evidence_count": len(buckets["guidance_evidence"]),
            "wave_or_demand_evidence_count": len(buckets["wave_or_demand_evidence"]),
            "warning_or_risk_evidence_count": len(buckets["warning_or_risk_evidence"]),
            "quality_flags": ";".join(flags),
            "quality_ok": str(not flags),
            "json_path": str((json_dir / f"{base}.json").relative_to(ROOT)),
            "entry_open": returns["entry_open"],
            "return_10d_pct": returns["return_10d_pct"],
            "return_20d_pct": returns["return_20d_pct"],
            "return_30d_pct": returns["return_30d_pct"],
            "return_60d_pct": returns["return_60d_pct"],
            "return_90d_pct": returns["return_90d_pct"],
        })
        if sleep_seconds:
            time.sleep(sleep_seconds)
    return manifest_rows


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(dict.fromkeys(key for row in rows for key in row.keys()))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return list(csv.DictReader(path.open()))


def row_key(row: dict) -> tuple[str, str, str]:
    return tuple(row.get(key, "") for key in MANIFEST_KEY)


def upsert_rows(existing: list[dict], incoming: list[dict]) -> list[dict]:
    merged = {row_key(row): row for row in existing}
    for row in incoming:
        merged[row_key(row)] = row
    return sorted(merged.values(), key=lambda row: (row.get("ticker", ""), row.get("filed", ""), row.get("form", "")))


def aggregate_global_manifest(incoming: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for manifest_path in OUTPUT_ROOT.glob("*/manifest.csv"):
        rows.extend(read_csv(manifest_path))
    rows.extend(incoming)
    return upsert_rows([], rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch 8-K Item 2.02 filings and parse EX-99.1 with sec-parser")
    parser.add_argument("--tickers", nargs="*", default=None)
    parser.add_argument("--all-cached-10q10k", action="store_true")
    parser.add_argument("--start-date", default="2021-01-01")
    parser.add_argument("--end-date", default="2026-12-31")
    parser.add_argument("--sleep-seconds", type=float, default=0.1)
    parser.add_argument("--llm-extractions-dir", type=Path, default=None, help="Optional directory of completed LLM extraction JSON files keyed by pipeline base filename")
    parser.add_argument("--use-edgartools", action="store_true", help="Add edgartools filing context to JSON/LLM inputs where available")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    refs = company_refs()
    tickers = args.tickers or []
    if args.all_cached_10q10k:
        tickers = cached_10q_10k_tickers()
    tickers = [ticker.upper() for ticker in tickers]
    missing = [ticker for ticker in tickers if ticker not in refs]
    if missing:
        raise ValueError(f"Missing SEC CIK refs for: {missing}")

    all_rows: list[dict] = []
    for ticker in tickers:
        rows = process_ticker(refs[ticker], args.start_date, args.end_date, args.sleep_seconds, args.llm_extractions_dir, args.use_edgartools)
        ticker_manifest = OUTPUT_ROOT / refs[ticker].ticker / "manifest.csv"
        write_csv(ticker_manifest, upsert_rows(read_csv(ticker_manifest), rows))
        all_rows.extend(rows)
        print(f"{ticker}: {len(rows)} 8-K Item 2.02 filings")
    global_rows = aggregate_global_manifest(all_rows)
    write_csv(OUTPUT_ROOT / "manifest.csv", global_rows)
    print(f"upserted {len(all_rows)} rows; global manifest now has {len(global_rows)} rows at {OUTPUT_ROOT / 'manifest.csv'}")


if __name__ == "__main__":
    main()
