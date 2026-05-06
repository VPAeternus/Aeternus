from __future__ import annotations

import csv
import html
import json
import re
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd

from src.config.cache_paths import sec_cache_root

try:
    import yfinance as yf
except Exception:  # pragma: no cover - lets extraction run without price package.
    yf = None

USER_AGENT = "AeternusAutoResearch research@aeternusholdings.com"
ROOT = Path(__file__).resolve().parents[1]
INPUT_CSV = ROOT / "Growth" / "nvda_8k_item_202_earnings_2021_2026.csv"
OUT_DIR = ROOT / "Growth" / "nvda_8k_item_202_extractions"
CACHE_ROOT = sec_cache_root()
CACHE_HTML = CACHE_ROOT / "filings_html"
CACHE_TEXT = CACHE_ROOT / "filings_text"
RAW_EX99_DIR = CACHE_ROOT / "nvda_8k_item_202_ex99_text"
CIK = "0001045810"
CIK_INT = "1045810"
RETURN_HORIZONS = [10, 20, 30, 60, 90]


def _fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def _fetch_json(url: str) -> dict[str, object]:
    return json.loads(_fetch(url))


def _strip_html(value: str) -> str:
    value = re.sub(r"<script\b[^>]*>.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    return clean(value)


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def _number(value: str) -> int | float | None:
    value = value.replace(",", "").replace("$", "").strip()
    if not value:
        return None
    try:
        num = float(value)
    except ValueError:
        return None
    if num.is_integer():
        return int(num)
    return num


def _signed_pct(value: str) -> int | float | None:
    num = _number(value)
    return num


def _directional_pct(match: re.Match[str] | None) -> int | float | None:
    if not match:
        return None
    sign = -1 if match.group(1).lower() == "down" else 1
    num = _number(match.group(2))
    return sign * num if num is not None else None


def _first(pattern: str, text: str, group: int = 1) -> str:
    match = re.search(pattern, text, flags=re.I | re.S)
    return clean(match.group(group)) if match else ""


def _money_to_millions(value: str, unit: str) -> int | float | None:
    num = _number(value)
    if num is None:
        return None
    unit = unit.lower()
    if unit.startswith("billion"):
        return int(round(float(num) * 1000))
    return num


def _period(text: str) -> dict[str, str]:
    quarter = _first(r"Financial Results for ([^•]+)", text)
    ended = _first(r"quarter ended ([A-Za-z]+ \d{1,2}, \d{4})", text)
    return {
        "reported_period_text": quarter,
        "quarter_ended_text": ended,
    }


def _headline(text: str) -> str:
    return _first(r"(NVIDIA (?:Announces|Provides)[^•]{0,240})", text) or text[:220]


def _quarter_results(text: str) -> dict[str, int | float | None]:
    revenue_match = re.search(
        r"reported(?: record)? revenue for the .*?quarter ended .*?, of \$(\d+(?:\.\d+)?)\s*(billion|million), ([^.]+)\.",
        text,
        flags=re.I | re.S,
    )
    gaap_eps_match = re.search(
        r"GAAP earnings per diluted share for the quarter were(?: a record)? \$(\d+(?:\.\d+)?), ([^.]+)\.",
        text,
        flags=re.I | re.S,
    )
    non_gaap_eps_match = re.search(
        r"Non-GAAP earnings per diluted share were \$(\d+(?:\.\d+)?), ([^.]+)\.",
        text,
        flags=re.I | re.S,
    )
    revenue_delta = revenue_match.group(3) if revenue_match else ""
    gaap_delta = gaap_eps_match.group(2) if gaap_eps_match else ""
    non_gaap_delta = non_gaap_eps_match.group(2) if non_gaap_eps_match else ""
    yoy_pattern = r"(up|down)\s+(\d+(?:\.\d+)?)\s*(?:percent|%)\s+from a year"
    qoq_pattern = r"(up|down)\s+(\d+(?:\.\d+)?)\s*(?:percent|%)\s+from the previous quarter"
    preliminary = re.search(
        r"Second quarter revenue is expected to be approximately \$(\d+(?:\.\d+)?)\s*(billion|million), ([^.]+)\.",
        text,
        flags=re.I | re.S,
    )
    preliminary_delta = preliminary.group(3) if preliminary else ""
    result = {
        "revenue_millions": _money_to_millions(revenue_match.group(1), revenue_match.group(2)) if revenue_match else None,
        "revenue_yoy_pct": _directional_pct(re.search(yoy_pattern, revenue_delta, flags=re.I)),
        "revenue_qoq_pct": _directional_pct(re.search(qoq_pattern, revenue_delta, flags=re.I)),
        "gaap_eps_diluted": _number(gaap_eps_match.group(1)) if gaap_eps_match else None,
        "gaap_eps_yoy_pct": _directional_pct(re.search(yoy_pattern, gaap_delta, flags=re.I)),
        "gaap_eps_qoq_pct": _directional_pct(re.search(qoq_pattern, gaap_delta, flags=re.I)),
        "non_gaap_eps_diluted": _number(non_gaap_eps_match.group(1)) if non_gaap_eps_match else None,
        "non_gaap_eps_yoy_pct": _directional_pct(re.search(yoy_pattern, non_gaap_delta, flags=re.I)),
        "non_gaap_eps_qoq_pct": _directional_pct(re.search(qoq_pattern, non_gaap_delta, flags=re.I)),
        "is_preliminary_result": preliminary is not None,
    }
    if preliminary and result["revenue_millions"] is None:
        result["revenue_millions"] = _money_to_millions(preliminary.group(1), preliminary.group(2))
        result["revenue_yoy_pct"] = _directional_pct(re.search(yoy_pattern, preliminary_delta, flags=re.I))
        result["revenue_qoq_pct"] = _directional_pct(re.search(r"(up|down)\s+(\d+(?:\.\d+)?)\s*(?:percent|%)\s+sequentially", preliminary_delta, flags=re.I))
    return result


def _fiscal_year_results(text: str) -> dict[str, int | float | None]:
    revenue_match = re.search(
        r"For fiscal \d{4}, revenue was(?: a record)? \$(\d+(?:\.\d+)?)\s*(billion|million), up (\d+) percent",
        text,
        flags=re.I | re.S,
    )
    gaap_eps_match = re.search(
        r"GAAP earnings per diluted share were(?: a record)? \$(\d+(?:\.\d+)?), up (\d+) percent from",
        text,
        flags=re.I | re.S,
    )
    non_gaap_eps_match = re.search(
        r"Non-GAAP earnings per diluted share were \$(\d+(?:\.\d+)?), up (\d+) percent from",
        text,
        flags=re.I | re.S,
    )
    return {
        "revenue_millions": _money_to_millions(revenue_match.group(1), revenue_match.group(2)) if revenue_match else None,
        "revenue_yoy_pct": _signed_pct(revenue_match.group(3)) if revenue_match else None,
        "gaap_eps_diluted": _number(gaap_eps_match.group(1)) if gaap_eps_match else None,
        "gaap_eps_yoy_pct": _signed_pct(gaap_eps_match.group(2)) if gaap_eps_match else None,
        "non_gaap_eps_diluted": _number(non_gaap_eps_match.group(1)) if non_gaap_eps_match else None,
        "non_gaap_eps_yoy_pct": _signed_pct(non_gaap_eps_match.group(2)) if non_gaap_eps_match else None,
    }


def _guidance(text: str) -> dict[str, int | float | None]:
    revenue = re.search(r"Revenue is expected to be \$(\d+(?:\.\d+)?)\s*(billion|million), plus or minus (\d+(?:\.\d+)?)\s*(?:percent|%)", text, flags=re.I)
    gm = re.search(r"GAAP and non-GAAP gross margins are expected to be (\d+(?:\.\d+)?)\s*(?:percent|%) and (\d+(?:\.\d+)?)\s*(?:percent|%)", text, flags=re.I)
    opex = re.search(r"GAAP and non-GAAP operating expenses are expected to be approximately \$(\d+(?:\.\d+)?)\s*(billion|million) and \$(\d+(?:\.\d+)?)\s*(billion|million)", text, flags=re.I)
    tax = re.search(r"GAAP and non-GAAP tax rates are both expected to be (\d+(?:\.\d+)?)\s*(?:percent|%), plus or minus (\d+(?:\.\d+)?)\s*(?:percent|%)", text, flags=re.I)
    return {
        "revenue_millions": _money_to_millions(revenue.group(1), revenue.group(2)) if revenue else None,
        "revenue_range_pct": _number(revenue.group(3)) if revenue else None,
        "gaap_gross_margin_pct": _number(gm.group(1)) if gm else None,
        "non_gaap_gross_margin_pct": _number(gm.group(2)) if gm else None,
        "gaap_opex_millions": _money_to_millions(opex.group(1), opex.group(2)) if opex else None,
        "non_gaap_opex_millions": _money_to_millions(opex.group(3), opex.group(4)) if opex else None,
        "tax_rate_pct": _number(tax.group(1)) if tax else None,
        "tax_rate_range_pct": _number(tax.group(2)) if tax else None,
    }


def _segment(name: str, text: str) -> dict[str, int | float | None | str]:
    pattern = rf"{re.escape(name)} .*?Fourth-quarter revenue was(?: a record)? \$(\d+(?:\.\d+)?)\s*(billion|million),([^•]+)"
    match = re.search(pattern, text, flags=re.I | re.S)
    full_year = re.search(r"Full-year revenue was(?: a record)? \$(\d+(?:\.\d+)?)\s*(billion|million), (up|down) (\d+) percent", match.group(3), flags=re.I) if match else None
    yoy = re.search(r"(up|down) (\d+) percent from a year", match.group(3), flags=re.I) if match else None
    qoq = re.search(r"(up|down|slightly above) (?:the previous quarter|(\d+) percent from the previous quarter)", match.group(3), flags=re.I) if match else None
    return {
        "q4_revenue_millions": _money_to_millions(match.group(1), match.group(2)) if match else None,
        "q4_yoy_pct": ((-1 if yoy and yoy.group(1).lower() == "down" else 1) * _number(yoy.group(2))) if yoy else None,
        "full_year_revenue_millions": _money_to_millions(full_year.group(1), full_year.group(2)) if full_year else None,
        "full_year_yoy_pct": ((-1 if full_year and full_year.group(3).lower() == "down" else 1) * _number(full_year.group(4))) if full_year else None,
        "raw_excerpt": clean(match.group(0))[:500] if match else "",
        "qoq_text": clean(qoq.group(0)) if qoq else "",
    }


def _snippets_for_patterns(text: str, patterns: list[str], *, limit: int = 5) -> list[str]:
    snippets = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.I):
            snippet = clean(match.group(0))
            if snippet and snippet not in snippets:
                snippets.append(snippet[:400])
            if len(snippets) >= limit:
                return snippets
    return snippets


def _evidence_buckets(text: str) -> dict[str, list[str]]:
    probes = {
        "numeric_evidence": [
            r"reported(?: record)? revenue[^.]+\.",
            r"GAAP earnings per diluted share[^.]+\.",
            r"Non-GAAP earnings per diluted share[^.]+\.",
            r"revenue was(?: a record)? \$[^.]+\.",
            r"gross margin[^.]+\.",
        ],
        "guidance_evidence": [
            r"Revenue is expected[^.]+\.",
            r"GAAP and non-GAAP gross margins are expected[^.]+\.",
            r"GAAP and non-GAAP operating expenses are expected[^.]+\.",
            r"outlook[^.]+\.",
        ],
        "wave_or_demand_evidence": [
            r"Demand for [^.]+\.",
            r"strong demand[^.]+\.",
            r"record demand[^.]+\.",
            r"customer[^.]{0,160}demand[^.]+\.",
            r"AI[^.]+\.",
            r"accelerated computing[^.]+\.",
            r"Data Center[^•.]+\.",
            r"cloud[^.]+\.",
            r"platform[^.]+\.",
        ],
        "warning_or_risk_evidence": [
            r"preliminary financial results[^.]+\.",
            r"shortfall[^.]+\.",
            r"weaker than forecasted[^.]+\.",
            r"inventory[^.]{0,160}(?:reserves|demand|obligations|diminished|challenging)[^.]+\.",
            r"(?:incurred|include)[^.]{0,80}\$[^.]{0,80}(?:billion|million)[^.]{0,80}charges[^.]+\.",
            r"challenging market conditions[^.]+\.",
            r"export control[^.]+\.",
            r"forward-looking statements[^.]+\.",
        ],
    }
    output: dict[str, list[str]] = {}
    for key, patterns in probes.items():
        output[key] = _snippets_for_patterns(text, patterns)
    return output


def _text_flags(text: str) -> dict[str, bool]:
    lower = text.lower()
    return {
        "preliminary_results": "preliminary financial results" in lower,
        "revenue_shortfall": "shortfall" in lower or "weaker than forecasted" in lower,
        "inventory_charge": "inventory" in lower and "charge" in lower,
        "weak_demand": "weaker" in lower or "challenging market conditions" in lower or "demand diminished" in lower,
        "export_control_hit": "export control" in lower or "license is required for exports" in lower,
        "record_revenue": "record revenue" in lower or "record quarterly revenue" in lower,
        "ai_wave": "artificial intelligence" in lower or "generative ai" in lower or "accelerated computing" in lower or "ai infrastructure" in lower,
        "data_center_strength": "data center" in lower and ("record" in lower or "up" in lower or "strong" in lower),
    }


def _earnings_score(payload: dict[str, object], text: str) -> dict[str, object]:
    quarter = payload["quarter_results"]
    guidance = payload["next_quarter_guidance"]
    flags = _text_flags(text)
    current_revenue = quarter.get("revenue_millions")
    guidance_revenue = guidance.get("revenue_millions")
    guidance_vs_current_pct = None
    if current_revenue and guidance_revenue:
        guidance_vs_current_pct = (guidance_revenue / current_revenue - 1) * 100

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

    revenue_yoy = quarter.get("revenue_yoy_pct")
    revenue_qoq = quarter.get("revenue_qoq_pct")
    earnings_torque = 0
    if revenue_yoy is not None:
        if revenue_yoy >= 75:
            earnings_torque += 2
        elif revenue_yoy >= 30:
            earnings_torque += 1
        elif revenue_yoy < 0:
            earnings_torque -= 1
    if revenue_qoq is not None:
        if revenue_qoq >= 10:
            earnings_torque += 1
        elif revenue_qoq < 0:
            earnings_torque -= 1

    wave_torque = 0
    if flags["ai_wave"]:
        wave_torque += 1
    if flags["data_center_strength"]:
        wave_torque += 1
    if flags["record_revenue"]:
        wave_torque += 1
    wave_torque = min(wave_torque, 3)

    margin_quality = 0
    gaap_margin = guidance.get("gaap_gross_margin_pct")
    non_gaap_margin = guidance.get("non_gaap_gross_margin_pct")
    if non_gaap_margin is not None and non_gaap_margin >= 65:
        margin_quality += 1
    if gaap_margin is not None and gaap_margin >= 60:
        margin_quality += 1
    margin_quality = min(margin_quality, 2)

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
    if total >= 7:
        bucket = "high"
    elif total >= 4:
        bucket = "medium"
    elif total >= 1:
        bucket = "low"
    else:
        bucket = "avoid"

    return {
        "earnings_score": total,
        "earnings_score_bucket": bucket,
        "guidance_torque": guidance_torque,
        "earnings_torque": earnings_torque,
        "segment_wave_torque": wave_torque,
        "margin_quality": margin_quality,
        "warning_penalty": warning_penalty,
        "guidance_vs_current_pct": round(guidance_vs_current_pct, 4) if guidance_vs_current_pct is not None else None,
        "flags": flags,
    }


def _periodic_filings() -> list[dict[str, str]]:
    submissions = _fetch_json(f"https://data.sec.gov/submissions/CIK{CIK}.json")
    recent = submissions["filings"]["recent"]
    filings = []
    for idx, form in enumerate(recent["form"]):
        if form not in {"10-Q", "10-K"}:
            continue
        filed = recent["filingDate"][idx]
        if not ("2021-01-01" <= filed <= "2026-12-31"):
            continue
        accession = recent["accessionNumber"][idx]
        compact = accession.replace("-", "")
        primary = recent["primaryDocument"][idx]
        filings.append(
            {
                "form": form,
                "filed": filed,
                "report_date": recent["reportDate"][idx],
                "accession": accession,
                "url": f"https://www.sec.gov/Archives/edgar/data/{CIK_INT}/{compact}/{primary}",
            }
        )
    return sorted(filings, key=lambda item: item["filed"])


def _match_periodic_filing(filed: str, periodic: list[dict[str, str]]) -> dict[str, str]:
    candidates = [item for item in periodic if item["filed"] >= filed]
    if not candidates:
        return {"form": "", "filed": "", "report_date": "", "url": ""}
    match = candidates[0]
    return {
        "form": match["form"],
        "filed": match["filed"],
        "report_date": match["report_date"],
        "url": match["url"],
    }


def _next_trading_day(history: pd.DataFrame, filed: str) -> str:
    target = pd.Timestamp(filed) + pd.Timedelta(days=1)
    dates = pd.Series(history.index.strftime("%Y-%m-%d"), index=history.index)
    eligible = history[dates >= target.strftime("%Y-%m-%d")]
    if eligible.empty:
        return ""
    return eligible.index[0].strftime("%Y-%m-%d")


def _download_prices(rows: list[dict[str, str]]) -> pd.DataFrame:
    if yf is None:
        return pd.DataFrame()
    min_date = min(row["sec_filing_date"] for row in rows)
    start = (pd.Timestamp(min_date) - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    end = (pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    return yf.Ticker("NVDA").history(start=start, end=end, interval="1d", auto_adjust=False)


def _return_fields(history: pd.DataFrame, filed: str) -> dict[str, str]:
    fields = {"tradable_date": "", "entry_open": ""}
    for horizon in RETURN_HORIZONS:
        fields[f"return_{horizon}d_pct"] = ""
    if history.empty:
        return fields
    tradable_date = _next_trading_day(history, filed)
    if not tradable_date:
        return fields
    dates = history.index.strftime("%Y-%m-%d")
    entry_rows = history[dates == tradable_date]
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


def _extract(row: dict[str, str], text: str) -> dict[str, object]:
    payload = {
        "metadata": {
            "ticker": row["ticker"],
            "company": row["company"],
            "form": row["form"],
            "items": row["items"],
            "accession": row["accession"],
            "sec_filing_date": row["sec_filing_date"],
            "sec_acceptance_datetime_utc": row["sec_acceptance_datetime_utc"],
            "sec_report_date_event_date": row["sec_report_date_event_date"],
            "earnings_release_date_from_ex99": row["earnings_release_date_from_ex99"],
            "primary_document": row["primary_document"],
            "ex99_1_press_release_document": row["ex99_1_press_release_document"],
            "sec_filing_url": row["sec_filing_url"],
            "ex99_1_press_release_url": row["ex99_1_press_release_url"],
            "is_regular_quarterly_earnings_release": row["is_regular_quarterly_earnings_release"],
        },
        "headline": _headline(text),
        "reported_period": _period(text),
        "quarter_results": _quarter_results(text),
        "fiscal_year_results": _fiscal_year_results(text),
        "next_quarter_guidance": _guidance(text),
        "segment_highlights": {
            "data_center": _segment("Data Center", text),
            "gaming": _segment("Gaming", text),
            "professional_visualization": _segment("Professional Visualization", text),
            "automotive": _segment("Automotive", text),
        },
        "evidence_buckets": _evidence_buckets(text),
    }
    payload["earnings_score"] = _earnings_score(payload, text)
    return payload


def _write_md(path: Path, payload: dict[str, object]) -> None:
    lines = [f"# {payload['metadata']['ticker']} 8-K Item 2.02 Extraction", ""]
    lines.append(f"Source: {payload['metadata']['ex99_1_press_release_url']}")
    for section in ["metadata", "reported_period", "quarter_results", "fiscal_year_results", "next_quarter_guidance"]:
        lines += ["", f"## {section}"]
        for key, value in payload[section].items():
            lines.append(f"- `{key}`: {value}")
    lines += ["", "## earnings_score"]
    for key, value in payload["earnings_score"].items():
        lines.append(f"- `{key}`: {json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value}")
    lines += ["", "## segment_highlights"]
    for key, value in payload["segment_highlights"].items():
        lines.append(f"- `{key}`: {json.dumps(value, ensure_ascii=False)}")
    lines += ["", "## evidence_buckets"]
    for key, values in payload["evidence_buckets"].items():
        lines.append(f"- `{key}`: {' | '.join(values)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "json").mkdir(exist_ok=True)
    (OUT_DIR / "md").mkdir(exist_ok=True)
    CACHE_HTML.mkdir(parents=True, exist_ok=True)
    CACHE_TEXT.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(INPUT_CSV.open()))
    periodic = _periodic_filings()
    price_history = _download_prices(rows)
    manifest = []
    for row in rows:
        accn = row["accession"]
        compact = accn.replace("-", "")
        base = f"NVDA_{row['sec_filing_date']}_8-K_{accn}"

        primary_html = _fetch(row["sec_filing_url"])
        primary_text = _strip_html(primary_html)
        ex99_text = (RAW_EX99_DIR / f"{base.replace('_8-K_', '_')}_{row['ex99_1_press_release_document']}.txt")
        if ex99_text.exists():
            text = ex99_text.read_text(encoding="utf-8")
        else:
            text = _strip_html(_fetch(row["ex99_1_press_release_url"]))

        (CACHE_HTML / f"{base}_primary.html").write_text(primary_html, encoding="utf-8")
        (CACHE_TEXT / f"{base}_primary.txt").write_text(primary_text, encoding="utf-8")
        (CACHE_TEXT / f"{base}_ex99_1.txt").write_text(text, encoding="utf-8")

        payload = _extract(row, text)
        json_path = OUT_DIR / "json" / f"{base}.json"
        md_path = OUT_DIR / "md" / f"{base}.md"
        json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        _write_md(md_path, payload)
        periodic_match = _match_periodic_filing(row["sec_filing_date"], periodic)
        returns = _return_fields(price_history, row["sec_filing_date"])
        manifest.append(
            {
                "ticker": "NVDA",
                "filed": row["sec_filing_date"],
                "tradable_date": returns["tradable_date"],
                "is_regular_quarterly_earnings_release": row["is_regular_quarterly_earnings_release"],
                "periodic_filing_form": periodic_match["form"],
                "periodic_filing_date": periodic_match["filed"],
                "quarter_revenue_millions": payload["quarter_results"]["revenue_millions"],
                "guidance_revenue_millions": payload["next_quarter_guidance"]["revenue_millions"],
                "earnings_score": payload["earnings_score"]["earnings_score"],
                "earnings_score_bucket": payload["earnings_score"]["earnings_score_bucket"],
                "guidance_torque": payload["earnings_score"]["guidance_torque"],
                "earnings_torque": payload["earnings_score"]["earnings_torque"],
                "segment_wave_torque": payload["earnings_score"]["segment_wave_torque"],
                "margin_quality": payload["earnings_score"]["margin_quality"],
                "warning_penalty": payload["earnings_score"]["warning_penalty"],
                "guidance_vs_current_pct": payload["earnings_score"]["guidance_vs_current_pct"],
                "entry_open": returns["entry_open"],
                "return_10d_pct": returns["return_10d_pct"],
                "return_20d_pct": returns["return_20d_pct"],
                "return_30d_pct": returns["return_30d_pct"],
                "return_60d_pct": returns["return_60d_pct"],
                "return_90d_pct": returns["return_90d_pct"],
            }
        )
    with (OUT_DIR / "manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(manifest[0].keys()))
        writer.writeheader()
        writer.writerows(manifest)
    print(f"wrote {len(manifest)} extractions to {OUT_DIR}")
    print(f"cached 8-K html/text in {CACHE_HTML} and {CACHE_TEXT}")


if __name__ == "__main__":
    main()
