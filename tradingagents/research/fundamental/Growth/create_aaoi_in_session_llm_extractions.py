from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = ROOT / "Growth" / "earnings_8k_sec_parser" / "AAOI" / "llm_inputs"
OUTPUT_DIR = ROOT / "Growth" / "earnings_8k_sec_parser" / "AAOI" / "llm_extractions_in_session"


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def num(value: str) -> float:
    return float(value.replace(",", ""))


def midpoint(low: float | None, high: float | None) -> float | None:
    if low is None or high is None:
        return None
    return round((low + high) / 2, 4)


def pct_change(current: float | None, prior: float | None) -> float | None:
    if current is None or not prior:
        return None
    return round((current / prior - 1) * 100, 4)


def all_table_lines(data: dict) -> list[str]:
    lines: list[str] = []
    for table in data["tables"]:
        for row in table["rows"]:
            text = clean(" ".join(cell for cell in row if cell))
            if text:
                lines.append(text)
    return lines


def first_match(lines: list[str], pattern: str) -> tuple[re.Match[str], str] | tuple[None, str]:
    for line in lines:
        match = re.search(pattern, line, flags=re.I)
        if match:
            return match, line
    return None, ""


def qualitative(text: str) -> dict[str, str]:
    probes = {
        "demand_signal": r"[^.]{0,140}(?:demand|momentum|backlog|orders|design wins|customer)[^.]{0,220}\.",
        "wave_signal": r"[^.]{0,140}(?:400G|800G|1\.6T|datacenter|hyperscale|HFC|CATV|QuantumLink|amplifier)[^.]{0,220}\.",
        "margin_signal": r"[^.]{0,140}(?:gross margin|manufacturing efficiencies|favorable product mix|cost reduction)[^.]{0,220}\.",
        "risk_signal": r"[^.]{0,140}(?:shortage|inventory|below our expectations|negatively impact|loss|headwinds|costs)[^.]{0,220}\.",
        "customer_signal": r"[^.]{0,140}(?:customer|customers|hyperscale|cable operator|design wins)[^.]{0,220}\.",
    }
    output: dict[str, str] = {}
    for key, pattern in probes.items():
        match = re.search(pattern, text, flags=re.I)
        output[key] = clean(match.group(0)) if match else ""
    return output


def extract_one(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    text = data["semantic_text"]
    lines = all_table_lines(data)
    evidence: list[dict[str, str]] = []

    revenue_match, revenue_quote = first_match(
        lines,
        r"(?:GAAP |Total )?revenue was \$([0-9,.]+) million, compared(?: with| to|) \$([0-9,.]+) million .*? and \$([0-9,.]+) million",
    )
    revenue = yoy = qoq = None
    if revenue_match:
        revenue = num(revenue_match.group(1))
        yoy = pct_change(revenue, num(revenue_match.group(2)))
        qoq = pct_change(revenue, num(revenue_match.group(3)))
        evidence.append({"field": "reported_results.revenue_millions", "quote": revenue_quote})
        evidence.append({"field": "reported_results.revenue_yoy_pct", "quote": revenue_quote})
        evidence.append({"field": "reported_results.revenue_qoq_pct", "quote": revenue_quote})

    margin_match, margin_quote = first_match(
        lines,
        r"GAAP gross margin was ([0-9.]+)%,.*?Non-GAAP gross margin was ([0-9.]+)%",
    )
    gaap_margin = non_gaap_margin = None
    if margin_match:
        gaap_margin = num(margin_match.group(1))
        non_gaap_margin = num(margin_match.group(2))
        evidence.append({"field": "reported_results.gross_margin_pct", "quote": margin_quote})
        evidence.append({"field": "reported_results.non_gaap_gross_margin_pct", "quote": margin_quote})

    guidance_match, guidance_quote = first_match(lines, r"Revenue in the range of \$ ?([0-9,.]+) million to \$ ?([0-9,.]+) million")
    guide_low = guide_high = guide_mid = None
    if guidance_match:
        guide_low = num(guidance_match.group(1))
        guide_high = num(guidance_match.group(2))
        guide_mid = midpoint(guide_low, guide_high)
        evidence.append({"field": "forward_guidance.revenue_low_millions", "quote": guidance_quote})
        evidence.append({"field": "forward_guidance.revenue_high_millions", "quote": guidance_quote})
        evidence.append({"field": "forward_guidance.revenue_millions_midpoint", "quote": guidance_quote})

    guidance_margin_match, guidance_margin_quote = first_match(lines, r"Non-GAAP gross margin in the range of ([0-9.]+)% to ([0-9.]+)%")
    guide_non_gaap_margin = None
    if guidance_margin_match:
        guide_non_gaap_margin = midpoint(num(guidance_margin_match.group(1)), num(guidance_margin_match.group(2)))
        evidence.append({"field": "forward_guidance.non_gaap_gross_margin_pct", "quote": guidance_margin_quote})

    period_match = re.search(r"financial results for (?:its )?([^\\.]+? ended [A-Za-z]+ \\d{1,2}, \\d{4})", text, flags=re.I)
    period_text = clean(period_match.group(1)) if period_match else ""
    period_end = ""
    if period_match:
        end_match = re.search(r"ended ([A-Za-z]+ \\d{1,2}, \\d{4})", period_match.group(1))
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
        "reported_period": {
            "period_text": period_text,
            "period_end_date": period_end,
        },
        "reported_results": {
            "revenue_millions": revenue,
            "revenue_yoy_pct": yoy,
            "revenue_qoq_pct": qoq,
            "gross_margin_pct": gaap_margin,
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
        "confidence": 0.88 if not missing else 0.62,
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in sorted(INPUT_DIR.glob("*.json")):
        payload = extract_one(path)
        (OUTPUT_DIR / path.name).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        count += 1
    print(f"wrote {count} extraction JSON files to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
