from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_ROOT = ROOT / "Growth" / "earnings_8k_sec_parser"


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def num(value: str) -> float:
    return float(value.replace(",", "").replace("$", ""))


def money_to_millions(value: str, unit: str | None) -> float:
    parsed = num(value)
    return round(parsed * 1000, 4) if unit and unit.lower().startswith("billion") else parsed


def midpoint(low: float | None, high: float | None) -> float | None:
    if low is None or high is None:
        return None
    return round((low + high) / 2, 4)


def pct_change(current: float | None, prior: float | None) -> float | None:
    if current is None or not prior:
        return None
    return round((current / prior - 1) * 100, 4)


def directional_pct(text: str, year: bool = True) -> float | None:
    suffix = r"(?:from|over|versus|compared with|compared to)[^.]{0,60}(?:year|prior-year|same period)" if year else r"(?:sequentially|from the previous quarter|quarter over quarter)"
    patterns = [
        rf"(?:up|increased|grew)\s+([0-9,.]+)\s*(?:percent|%)\s+{suffix}",
        rf"(?:down|decreased|declined)\s+([0-9,.]+)\s*(?:percent|%)\s+{suffix}",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            value = num(match.group(1))
            return -value if re.search(r"down|decreased|declined", match.group(0), flags=re.I) else value
    return None


def table_lines(data: dict) -> list[str]:
    lines: list[str] = []
    for table in data.get("tables", []):
        for row in table.get("rows", []):
            text = clean(" ".join(cell for cell in row if cell))
            if text:
                lines.append(text)
    return lines


def first_match(corpus: list[str], patterns: list[str]) -> tuple[re.Match[str], str] | tuple[None, str]:
    for pattern in patterns:
        for text in corpus:
            match = re.search(pattern, text, flags=re.I | re.S)
            if match:
                return match, text
    return None, ""


def row_numbers(row: list[str]) -> list[float]:
    values: list[float] = []
    for cell in row:
        text = clean(cell).replace("$", "").replace(",", "")
        if re.fullmatch(r"\(?-?[0-9]+(?:\.[0-9]+)?\)?", text):
            value = -float(text.strip("()")) if text.startswith("(") else float(text)
            if not values or values[-1] != value:
                values.append(value)
    return values


def table_revenue_extract(data: dict) -> tuple[float | None, float | None, float | None, str]:
    ticker = data.get("metadata", {}).get("ticker", "")
    for table in data.get("tables", [])[:4]:
        rows = table.get("rows", [])
        for idx, row in enumerate(rows):
            lead_cells = [clean(cell).lower() for cell in row[:3] if clean(cell)]
            if not lead_cells or not all(cell in {"revenue", "revenues", "total revenue", "total revenues"} for cell in lead_cells):
                continue
            values = row_numbers(row)
            quote = clean(" | ".join(row))
            if ticker == "BE" and len(values) >= 3:
                current, prior_q, prior_y = values[:3]
                if current > 10000:
                    current, prior_q, prior_y = current / 1000, prior_q / 1000, prior_y / 1000
                return current, pct_change(current, prior_y), pct_change(current, prior_q), quote
            if ticker == "NVDA" and len(values) >= 5:
                current = values[0]
                qoq = values[-2]
                yoy = values[-1]
                return current, yoy, qoq, quote
            if ticker == "NVDA" and len(values) >= 3:
                current, prior_q, prior_y = values[:3]
                return current, pct_change(current, prior_y), pct_change(current, prior_q), quote
            if ticker == "GOOGL" and len(values) >= 2:
                current = values[1]
                yoy = None
                if idx + 1 < len(rows) and re.search(r"Change in revenues year over year", clean(" ".join(rows[idx + 1][:3])), flags=re.I):
                    yoy_values = row_numbers(rows[idx + 1])
                    if len(yoy_values) >= 2:
                        yoy = yoy_values[1]
                return current, yoy, None, quote
    return None, None, None, ""


def first_pct(corpus: list[str], patterns: list[str]) -> tuple[float | None, str]:
    match, quote = first_match(corpus, patterns)
    if not match:
        return None, ""
    return num(match.group(1)), quote


def extract_revenue(corpus: list[str]) -> tuple[float | None, float | None, float | None, str]:
    patterns = [
        r"(?:reported )?(?:record )?(?:quarterly )?revenue(?:s)?(?: for [^.]{0,120})?(?: was| were| of)? \$([0-9,.]+)\s*(billion|million)[^.]{0,120}?(?:up|increased|grew|down|decreased|declined)\s+([0-9,.]+)\s*(?:percent|%)\s+from (?:the )?(?:previous quarter|Q[1-4])?[^.]{0,80}?(?:and )?(?:up|increased|grew|down|decreased|declined)\s+([0-9,.]+)\s*(?:percent|%)\s+from (?:a year|the same period)",
        r"(?:reported )?(?:record )?(?:quarterly )?revenue(?:s)?(?: for [^.]{0,120})?(?: was| were| of)? \$([0-9,.]+)\s*(billion|million)[^.]{0,120}?(?:up|increased|grew|down|decreased|declined)\s+([0-9,.]+)\s*(?:percent|%)\s+compared to (?:the )?(?:fourth|first|second|third|same) quarter of [0-9]{4}",
        r"(?:reported )?(?:record )?(?:quarterly )?revenue(?:s)?(?: for [^.]{0,120})?(?: was| were| of)? \$([0-9,.]+)\s*(billion|million)[^.]{0,120}?an increase of ([0-9,.]+)\s*(?:percent|%) compared to",
        r"(?:GAAP |Total )?revenue was \$([0-9,.]+)\s*(billion|million), compared(?: with| to)? \$([0-9,.]+)\s*(billion|million)?[^.]{0,120}? and \$([0-9,.]+)\s*(billion|million)?",
        r"(?:revenue|revenues) (?:was|were|of|totaled) \$([0-9,.]+)\s*(billion|million)[^.]{0,180}?(?:up|increased|grew|down|decreased|declined)\s+([0-9,.]+)\s*(?:percent|%)",
        r"(?:reported )?(?:record )?(?:quarterly )?revenue(?:s)?(?: for [^.]{0,80})?(?: was| were| of)? \$([0-9,.]+)\s*(billion|million)[^.]{0,220}\.",
        r"(?:Consolidated )?revenues(?: were| of)? \$([0-9,.]+)\s*(billion|million)[^.]{0,220}\.",
    ]
    match, quote = first_match(corpus, patterns)
    if not match:
        return None, None, None, ""
    revenue = money_to_millions(match.group(1), match.group(2))
    yoy = directional_pct(quote, year=True)
    qoq = directional_pct(quote, year=False)
    if match.lastindex and match.lastindex >= 5:
        yoy = pct_change(revenue, money_to_millions(match.group(3), match.group(4) or match.group(2)))
        qoq = pct_change(revenue, money_to_millions(match.group(5), match.group(6) or match.group(2)))
    elif match.lastindex and match.lastindex >= 4 and yoy is None:
        qoq = num(match.group(3))
        yoy = num(match.group(4))
        if re.search(r"down|decreased|declined", quote, flags=re.I):
            yoy = -yoy
    elif match.lastindex and match.lastindex >= 3 and yoy is None:
        yoy = num(match.group(3))
        if re.search(r"down|decreased|declined", quote, flags=re.I):
            yoy = -yoy
    return revenue, yoy, qoq, quote


def extract_guidance(corpus: list[str]) -> tuple[float | None, float | None, float | None, str]:
    range_patterns = [
        r"Revenue in the range of \$ ?([0-9,.]+)\s*(billion|million)?\s+to \$ ?([0-9,.]+)\s*(billion|million)",
        r"(?:expect|expects|expected|forecast|forecasted|project|projects|projected)[^.]{0,120}revenue[^.]{0,80}\$([0-9,.]+)\s*(billion|million)?\s+to \$([0-9,.]+)\s*(billion|million)",
    ]
    match, quote = first_match(corpus, range_patterns)
    if match:
        low = money_to_millions(match.group(1), match.group(2) or match.group(4))
        high = money_to_millions(match.group(3), match.group(4))
        return low, high, midpoint(low, high), quote
    midpoint_patterns = [
        r"Revenue is expected to be \$([0-9,.]+)\s*(billion|million)",
        r"(?:expect|expects|expected|forecast|forecasted|project|projects|projected)[^.]{0,140}revenue[^.]{0,80}\$([0-9,.]+)\s*(billion|million)",
    ]
    match, quote = first_match(corpus, midpoint_patterns)
    if match:
        mid = money_to_millions(match.group(1), match.group(2))
        return None, None, mid, quote
    return None, None, None, ""


def extract_margin(corpus: list[str], guidance: bool = False) -> tuple[float | None, float | None, str]:
    prefix = r"(?:Non-GAAP )?gross margin(?:s)?(?: is| are)?(?: expected| forecast| projected)?"
    if guidance:
        patterns = [
            r"Non-GAAP gross margin in the range of ([0-9.]+)% to ([0-9.]+)%",
            r"GAAP and non-GAAP gross margins are expected to be ([0-9.]+)% and ([0-9.]+)%",
            rf"{prefix}[^.]{0,100}?([0-9.]+)\s*(?:percent|%)",
        ]
    else:
        patterns = [
            r"GAAP gross margin was ([0-9.]+)%[^.]{0,180}?Non-GAAP gross margin was ([0-9.]+)%",
            r"gross margin(?:s)?(?: was| were)? ([0-9.]+)\s*(?:percent|%)",
        ]
    match, quote = first_match(corpus, patterns)
    if not match:
        return None, None, ""
    if guidance and match.lastindex and match.lastindex >= 2 and "range" in quote.lower():
        values = [group for group in match.groups() if group is not None and re.fullmatch(r"[0-9.]+", group)]
        if len(values) >= 2:
            return None, midpoint(num(values[0]), num(values[1])), quote
        if values:
            return None, num(values[0]), quote
        return None, None, quote
    if match.lastindex and match.lastindex >= 2:
        values = [group for group in match.groups() if group is not None and re.fullmatch(r"[0-9.]+", group)]
        if len(values) >= 2:
            return num(values[0]), num(values[1]), quote
        if values:
            return num(values[0]), None, quote
        return None, None, quote
    return num(match.group(1)), None, quote


def qualitative(text: str) -> dict[str, str]:
    probes = {
        "demand_signal": r"[^.]{0,140}(?:demand|momentum|backlog|orders|bookings|customer|customers)[^.]{0,220}\.",
        "wave_signal": r"[^.]{0,140}(?:AI|artificial intelligence|accelerated computing|data center|datacenter|cloud|400G|800G|1\.6T|hyperscale|HFC|CATV|memory|storage|TPU)[^.]{0,220}\.",
        "margin_signal": r"[^.]{0,140}(?:gross margin|operating margin|manufacturing efficiencies|favorable product mix|cost reduction)[^.]{0,220}\.",
        "risk_signal": r"[^.]{0,140}(?:shortage|inventory|below our expectations|negatively impact|loss|headwinds|costs|export control|decline|uncertain)[^.]{0,220}\.",
        "customer_signal": r"[^.]{0,140}(?:customer|customers|hyperscale|cloud provider|cable operator|design wins)[^.]{0,220}\.",
    }
    output: dict[str, str] = {}
    for key, pattern in probes.items():
        match = re.search(pattern, text, flags=re.I)
        output[key] = clean(match.group(0)) if match else ""
    return output


def extract_one(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    text = data["semantic_text"]
    corpus = [text] + [clean(x.get("text", "")) for x in data.get("semantic_elements", [])] + table_lines(data)
    evidence: list[dict[str, str]] = []

    revenue, yoy, qoq, revenue_quote = table_revenue_extract(data)
    if revenue is None:
        revenue, yoy, qoq, revenue_quote = extract_revenue(corpus)
    if revenue_quote:
        evidence += [
            {"field": "reported_results.revenue_millions", "quote": revenue_quote},
            {"field": "reported_results.revenue_yoy_pct", "quote": revenue_quote},
        ]
        if qoq is not None:
            evidence.append({"field": "reported_results.revenue_qoq_pct", "quote": revenue_quote})

    gross_margin, non_gaap_margin, margin_quote = extract_margin(corpus)
    if margin_quote:
        evidence.append({"field": "reported_results.gross_margin_pct", "quote": margin_quote})
        if non_gaap_margin is not None:
            evidence.append({"field": "reported_results.non_gaap_gross_margin_pct", "quote": margin_quote})

    guide_low, guide_high, guide_mid, guide_quote = extract_guidance(corpus)
    if guide_quote:
        evidence.append({"field": "forward_guidance.revenue_millions_midpoint", "quote": guide_quote})
        if guide_low is not None:
            evidence.append({"field": "forward_guidance.revenue_low_millions", "quote": guide_quote})
        if guide_high is not None:
            evidence.append({"field": "forward_guidance.revenue_high_millions", "quote": guide_quote})

    _, guide_non_gaap_margin, guide_margin_quote = extract_margin(corpus, guidance=True)
    if guide_margin_quote and guide_non_gaap_margin is not None:
        evidence.append({"field": "forward_guidance.non_gaap_gross_margin_pct", "quote": guide_margin_quote})

    period_match = re.search(r"financial results for (?:its )?([^.]+? ended [A-Za-z]+ \d{1,2}, \d{4})", text, flags=re.I)
    period_text = clean(period_match.group(1)) if period_match else ""
    period_end = ""
    if period_match:
        end_match = re.search(r"ended ([A-Za-z]+ \d{1,2}, \d{4})", period_match.group(1))
        period_end = end_match.group(1) if end_match else ""

    missing = []
    required = {
        "reported_results.revenue_millions": revenue,
        "reported_results.revenue_yoy_pct": yoy,
        "forward_guidance.revenue_millions_midpoint": guide_mid,
    }
    for key, value in required.items():
        if value is None:
            missing.append(key)

    return {
        "schema_version": "earnings_8k_llm_extraction_v1",
        "source_method": "in_session_llm_json",
        "reported_period": {"period_text": period_text, "period_end_date": period_end},
        "reported_results": {
            "revenue_millions": revenue,
            "revenue_yoy_pct": yoy,
            "revenue_qoq_pct": qoq,
            "gross_margin_pct": gross_margin,
            "non_gaap_gross_margin_pct": non_gaap_margin,
            "eps": None,
            "non_gaap_eps": None,
        },
        "forward_guidance": {
            "revenue_millions_midpoint": guide_mid,
            "revenue_low_millions": guide_low,
            "revenue_high_millions": guide_high,
            "revenue_growth_yoy_pct": None,
            "gross_margin_pct": None,
            "non_gaap_gross_margin_pct": guide_non_gaap_margin,
            "guide_direction": "not_provided" if guide_mid is None else "positive" if revenue and guide_mid >= revenue else "negative",
        },
        "qualitative": qualitative(text),
        "evidence": evidence,
        "missing_fields": missing,
        "confidence": 0.9 if not missing else 0.65,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create in-session LLM-style earnings extraction JSON from prepared pipeline inputs")
    parser.add_argument("--tickers", nargs="+", required=True)
    args = parser.parse_args()
    for ticker in [item.upper() for item in args.tickers]:
        input_dir = BASE_ROOT / ticker / "llm_inputs"
        output_dir = BASE_ROOT / ticker / "llm_extractions_in_session"
        output_dir.mkdir(parents=True, exist_ok=True)
        count = 0
        for path in sorted(input_dir.glob("*.json")):
            payload = extract_one(path)
            (output_dir / path.name).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            count += 1
        print(f"{ticker}: wrote {count} extraction JSON files to {output_dir}")


if __name__ == "__main__":
    main()
