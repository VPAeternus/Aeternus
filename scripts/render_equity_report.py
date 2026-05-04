#!/usr/bin/env python3
"""Render Equity_Research_Report.md into a design-forward HTML report."""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
from pathlib import Path
from string import Template
from typing import Dict, List

try:
    import markdown as mdlib
except Exception:
    mdlib = None

DEFAULT_DISCLAIMER = (
    "For informational purposes only. This document is a design-forward rendering of the "
    "provided internal research notes (Markdown source-of-truth)."
)


def wrap_tables(html_text: str) -> str:
    def add_class(match):
        attrs = match.group(1) or ""
        if 'class="' in attrs:
            class_match = re.search(r"class=\"([^\"]+)\"", attrs)
            if class_match:
                classes = class_match.group(1).split()
                if "table" not in classes:
                    classes.append("table")
                new_class = "class=\"" + " ".join(classes) + "\""
                attrs = re.sub(r"class=\"[^\"]+\"", new_class, attrs)
        else:
            attrs += ' class="table"'
        return f"<table{attrs}>"

    html_text = re.sub(r"<table([^>]*)>", lambda m: '<div class="tableWrap">' + add_class(m), html_text)
    html_text = html_text.replace("</table>", "</table></div>")
    return html_text


def md_to_html(text: str) -> str:
    if mdlib:
        html_out = mdlib.markdown(
            text,
            extensions=["tables", "fenced_code", "toc"],
            output_format="html5",
        )
        return wrap_tables(html_out)
    return f"<pre>{html.escape(text)}</pre>"


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "section"


def pick_icon_id(title: str) -> str:
    title_l = title.lower()
    if "score" in title_l:
        return "i-score"
    if "analyst" in title_l or "market" in title_l:
        return "i-market"
    if "research" in title_l:
        return "i-decision"
    if "trading" in title_l or "plan" in title_l:
        return "i-plan"
    if "portfolio" in title_l or "decision" in title_l:
        return "i-decision"
    return "i-score"


def parse_header(md_text: str) -> Dict[str, str]:
    header: Dict[str, str] = {}
    title_match = re.search(r"^#\s+(.+)$", md_text, re.M)
    if title_match:
        header["title"] = title_match.group(1).strip()
        if ":" in header["title"]:
            header["ticker"] = header["title"].split(":", 1)[-1].strip()
    date_match = re.search(r"^Date:\s*(.+)$", md_text, re.M)
    if date_match:
        header["date"] = date_match.group(1).strip()
    built_match = re.search(r"^Built by:\s*(.+)$", md_text, re.M)
    if built_match:
        header["built_by"] = built_match.group(1).strip()
    return header


def parse_sections(md_text: str) -> List[Dict[str, str]]:
    lines = md_text.splitlines()
    sections: List[Dict[str, str]] = []
    current = None
    section_re = re.compile(r"^#\s+[IVX]+\.")
    for line in lines:
        if section_re.match(line):
            title = line[2:].strip()
            if current:
                current["body"] = "\n".join(current["body"]).strip()
                sections.append(current)
            current = {"title": title, "body": []}
        else:
            if current:
                current["body"].append(line)
    if current:
        current["body"] = "\n".join(current["body"]).strip()
        sections.append(current)
    return sections


def extract_company_profile(md_text: str) -> str | None:
    match = re.search(
        r"^##\s+Company Profile\s*\n(.+?)(\n\s*\n|\n##\s+|\n#\s+)",
        md_text,
        re.S | re.M,
    )
    if match:
        profile = match.group(1).strip()
        return profile.split("\n\n")[0].strip()
    return None


def extract_value(patterns: List[str], text: str) -> str | None:
    for pat in patterns:
        match = re.search(pat, text, re.I | re.M)
        if match:
            return match.group(1).strip()
    return None


def extract_fields(md_text: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    fields["recommendation"] = extract_value(
        [r"Recommendation:\s*\*\*(.+?)\*\*", r"Recommendation:\s*(.+)"],
        md_text,
    ) or "N/A"

    fields["score"] = extract_value(
        [r"\*\*Aeternus Score:\*\*\s*(.+)", r"Aeternus Score:\s*(.+)"],
        md_text,
    ) or "N/A"
    fields["rating"] = extract_value(
        [r"\*\*Rating:\*\*\s*(.+)", r"Rating:\s*(.+)"],
        md_text,
    ) or "N/A"
    fields["confidence"] = extract_value(
        [r"\*\*Confidence:\*\*\s*(.+)", r"Confidence:\s*(.+)"],
        md_text,
    ) or "N/A"

    fields["summary"] = extract_company_profile(md_text) or "N/A"

    fields["market_cap"] = extract_value(
        [r"market cap is\s*(\$[0-9\.]+[MBT])", r"Market Cap\s*\|\s*(\$[0-9\.]+[MBT])"],
        md_text,
    )
    fields["last_close"] = extract_value(
        [r"\*\*Close Price\*\*\s*\|\s*(\$[0-9\.]+)", r"Last Close\s*\|\s*(\$[0-9\.]+)"],
        md_text,
    )
    fields["cash_sti"] = extract_value(
        [r"cash/short-term investments\s*\((\$[0-9\.]+[MBT])\)", r"Cash\s*&\s*Equivalents\s*\|\s*(\$[0-9\.]+[MBT])"],
        md_text,
    )
    fields["sma_200"] = extract_value(
        [r"\*\*200 SMA\*\*\s*\|\s*(\$[0-9\.]+)", r"200D SMA\s*\|\s*(\$[0-9\.]+)"],
        md_text,
    )
    return fields


def build_kpi_html(kpis: Dict[str, str], rating: str) -> str:
    def kpi(label: str, value: str, note: str | None = None, is_pill: bool = False) -> str:
        value = value if value else "N/A"
        if is_pill:
            class_name = rating_class(value)
            return (
                f"<div class=\"kpi\"><div class=\"kpi__label\">{label}</div>"
                f"<span class=\"pill {class_name}\">{html.escape(value)}</span></div>"
            )
        note_html = f"<div class=\"kpi__note\">{html.escape(note)}</div>" if note else ""
        return (
            f"<div class=\"kpi\"><div class=\"kpi__label\">{label}</div>"
            f"<div class=\"kpi__value\">{html.escape(value)}</div>{note_html}</div>"
        )

    return "\n".join(
        [
            kpi("Rating", rating, is_pill=True),
            kpi("Aeternus Score", kpis.get("score", "N/A"), note=kpis.get("rating", "")),
            kpi("Last Close", kpis.get("last_close", "N/A")),
            kpi("Market Cap", kpis.get("market_cap", "N/A")),
            kpi("Cash + STI", kpis.get("cash_sti", "N/A")),
            kpi("200D SMA", kpis.get("sma_200", "N/A")),
        ]
    )


def rating_class(rating: str) -> str:
    r = (rating or "").lower()
    if "buy" in r:
        return "pill--buy"
    if "hold" in r:
        return "pill--hold"
    if "sell" in r:
        return "pill--sell"
    return ""


def build_radar_svg(labels, values) -> str:
    if not labels or not values or len(labels) != len(values):
        return ""
    n = len(labels)
    vals = [max(0, min(100, float(v))) for v in values]
    center = (180.0, 180.0)
    radius = 180.0

    rings = []
    for i in range(1, 6):
        r = radius * i / 5
        pts = []
        for j in range(n):
            angle = (2 * math.pi * j / n) - (math.pi / 2)
            x = center[0] + r * math.cos(angle)
            y = center[1] + r * math.sin(angle)
            pts.append(f"{x:.1f},{y:.1f}")
        rings.append(f"<polygon points=\"{' '.join(pts)}\" class=\"radar__ring\" />")

    spokes = []
    for j in range(n):
        angle = (2 * math.pi * j / n) - (math.pi / 2)
        x = center[0] + radius * math.cos(angle)
        y = center[1] + radius * math.sin(angle)
        spokes.append(f"<line x1=\"{center[0]:.0f}\" y1=\"{center[1]:.0f}\" x2=\"{x:.1f}\" y2=\"{y:.1f}\" class=\"radar__spoke\" />")

    shape_pts = []
    for j, val in enumerate(vals):
        angle = (2 * math.pi * j / n) - (math.pi / 2)
        r = radius * (val / 100.0)
        x = center[0] + r * math.cos(angle)
        y = center[1] + r * math.sin(angle)
        shape_pts.append(f"{x:.1f},{y:.1f}")

    label_nodes = []
    for j, label in enumerate(labels):
        angle = (2 * math.pi * j / n) - (math.pi / 2)
        x = center[0] + (radius + 18) * math.cos(angle)
        y = center[1] + (radius + 18) * math.sin(angle)
        anchor = "middle"
        if x > center[0] + 8:
            anchor = "start"
        elif x < center[0] - 8:
            anchor = "end"
        dy = "-2"
        if y > center[1] + 8:
            dy = "10"
        label_nodes.append(
            f"<text x=\"{x:.1f}\" y=\"{y:.1f}\" text-anchor=\"{anchor}\" class=\"radar__label\" dy=\"{dy}\">{html.escape(label)}</text>"
        )

    return (
        "<svg class=\"radar\" viewBox=\"-70 -70 500 500\" role=\"img\" aria-label=\"Aeternus dimension scores radar chart\">"
        "<g>"
        + "".join(rings)
        + "".join(spokes)
        + "</g>"
        + f"<polygon points=\"{' '.join(shape_pts)}\" class=\"radar__shape\" />"
        + "<g>"
        + "".join(label_nodes)
        + "</g>"
        + f"<circle cx=\"{center[0]:.0f}\" cy=\"{center[1]:.0f}\" r=\"2.25\" class=\"radar__center\" />"
        + "</svg>"
    )


def build_sentiment_bar(sent: Dict[str, int]) -> str:
    keys = ["bullish", "somewhat_bullish", "neutral", "somewhat_bearish", "bearish"]
    counts = [max(0, int(sent.get(k, 0))) for k in keys]
    total = sum(counts) or 1
    widths = [round(640 * c / total) for c in counts]

    labels = ["Bullish", "Somewhat-Bullish", "Neutral", "Somewhat-Bearish", "Bearish"]
    seg_classes = [
        "sentbar__seg--bullish",
        "sentbar__seg--somewhat-bullish",
        "sentbar__seg--neutral",
        "sentbar__seg--somewhat-bearish",
        "sentbar__seg--bearish",
    ]
    dot_classes = [
        "sentbar__dot--bullish",
        "sentbar__dot--somewhat-bullish",
        "sentbar__dot--neutral",
        "sentbar__dot--somewhat-bearish",
        "sentbar__dot--bearish",
    ]

    x = 0
    rects = []
    for width, cls in zip(widths, seg_classes):
        rects.append(
            f"<rect x=\"{x}\" y=\"0\" width=\"{width}\" height=\"26\" rx=\"7\" ry=\"7\" class=\"sentbar__seg {cls}\" />"
        )
        x += width

    legend_items = []
    for label, count, dot in zip(labels, counts, dot_classes):
        legend_items.append(
            f"<div class=\"sentbar__legendItem\"><span class=\"sentbar__dot {dot}\"></span>"
            f"<span class=\"sentbar__legendLabel\">{label}</span>"
            f"<span class=\"sentbar__legendCount\">{count}</span></div>"
        )

    return (
        "<div class=\"sentbar\">"
        "<div class=\"sentbar__bar\">"
        "<svg viewBox=\"0 0 640 26\" preserveAspectRatio=\"none\" role=\"img\" aria-label=\"Sentiment distribution (high relevance)\">"
        + "".join(rects)
        + "</svg></div>"
        + f"<div class=\"sentbar__legend\">{''.join(legend_items)}</div>"
        + "</div>"
    )


def build_key_levels_ladder(levels: List[Dict[str, object]]) -> str:
    if not levels:
        return ""
    items = []
    for lvl in levels:
        label = html.escape(str(lvl.get("label", "")))
        value = html.escape(str(lvl.get("value", "")))
        pos = float(lvl.get("position", 0))
        accent = " ladder__item--accent" if lvl.get("accent") else ""
        items.append(
            "<div class=\"ladder__item{accent}\">"
            "<div class=\"ladder__tag\">{label}</div>"
            "<div class=\"ladder__value\">{value}</div>"
            "<div class=\"ladder__rail\"><div class=\"ladder__dot\" style=\"left:{pos}%\"></div></div>"
            "</div>".format(accent=accent, label=label, value=value, pos=pos)
        )

    return (
        "<div class=\"ladder\" aria-label=\"Key technical levels ladder\">"
        "<div class=\"ladder__title\">Key Levels (From Report)</div>"
        + "".join(items)
        + "</div>"
    )


def build_summary_html(summary: str, sector: str, industry: str) -> str:
    summary = summary or "N/A"
    sector = sector or "N/A"
    industry = industry or "N/A"
    return (
        '<div class="summaryCard">'
        '<div class="summaryCard__title">Company Summary</div>'
        f'<div class="summaryCard__text">{md_to_html(summary)}</div>'
        '<div class="summaryMeta">'
        f'<span class="summaryMeta__pill">Sector: {html.escape(sector)}</span>'
        f'<span class="summaryMeta__pill">Industry: {html.escape(industry)}</span>'
        '</div></div>'
    )


def render_report(report_dir: Path, template_path: Path, output_path: Path) -> None:
    md_path = report_dir / "Equity_Research_Report.md"
    meta_path = report_dir / "report_meta.json"

    md_text = md_path.read_text()
    header = parse_header(md_text)
    sections = parse_sections(md_text)
    extracted = extract_fields(md_text)

    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    kpis_meta = meta.get("kpis", {}) if isinstance(meta.get("kpis", {}), dict) else {}
    charts_meta = meta.get("charts", {}) if isinstance(meta.get("charts", {}), dict) else {}

    ticker = meta.get("ticker") or header.get("ticker") or extracted.get("ticker") or "N/A"
    company_name = meta.get("company_name") or ticker
    headline = meta.get("headline") or f"{company_name} Investment Outlook"
    date = meta.get("date") or header.get("date") or "N/A"
    built_by = meta.get("built_by") or header.get("built_by") or "Aeternus Multi-Agent System"
    recommendation = (extracted.get("recommendation") or "N/A").replace("**", "").strip()

    kpi_values = {
        "score": kpis_meta.get("score") or extracted.get("score") or "N/A",
        "rating": kpis_meta.get("rating") or extracted.get("rating") or "N/A",
        "last_close": kpis_meta.get("last_close") or extracted.get("last_close") or "N/A",
        "market_cap": kpis_meta.get("market_cap") or extracted.get("market_cap") or "N/A",
        "cash_sti": kpis_meta.get("cash_sti") or extracted.get("cash_sti") or "N/A",
        "sma_200": kpis_meta.get("sma_200") or extracted.get("sma_200") or "N/A",
    }
    confidence = kpis_meta.get("confidence") or extracted.get("confidence") or "N/A"

    radar_html = build_radar_svg(
        charts_meta.get("radar", {}).get("labels", []),
        charts_meta.get("radar", {}).get("values", []),
    )
    sentiment_html = build_sentiment_bar(charts_meta.get("sentiment", {}))
    ladder_html = build_key_levels_ladder(charts_meta.get("key_levels", []))

    toc_links = []
    toc_cards = []
    for idx, section in enumerate(sections, start=1):
        section_id = slugify(section["title"])
        toc_links.append(
            f"<a class=\"toc__item\" href=\"#{section_id}\"><span class=\"toc__label\">{html.escape(section['title'])}</span></a>"
        )
        toc_cards.append(
            "<a class=\"tocCard\" href=\"#{}\">".format(section_id)
            + f"<div class=\"tocCard__num\">{idx:02d}</div>"
            + f"<div class=\"tocCard__title\">{html.escape(section['title'])}</div>"
            + "<div class=\"tocCard__cta\">Open section</div></a>"
        )

    sections_html = []
    for section in sections:
        section_id = slugify(section["title"])
        icon_id = pick_icon_id(section["title"])
        body_html = md_to_html(section["body"]) if section["body"] else ""
        if section["title"].strip().startswith("II.") and (radar_html or sentiment_html):
            viz = (
                "<div class=\"vizRow vizRow--two\">"
                "<div class=\"vizCard\"><div class=\"vizCard__header\">"
                "<div class=\"vizCard__title\">Aeternus Score Breakdown</div>"
                "<div class=\"vizCard__sub\">Dimensions from the report’s score table</div>"
                "</div>"
                + radar_html
                + "</div>"
                "<div class=\"vizCard\"><div class=\"vizCard__header\">"
                "<div class=\"vizCard__title\">Sentiment Split</div>"
                "<div class=\"vizCard__sub\">High-relevance distribution (from report table)</div>"
                "</div>"
                + sentiment_html
                + "</div></div>"
            )
            body_html = viz + body_html
        if section["title"].strip().startswith("III.") and ladder_html:
            body_html = f"<div class=\"vizRow\">{ladder_html}</div>" + body_html

        sections_html.append(
            f"<section class=\"page chapter\" id=\"{section_id}\">"
            "<header class=\"chapterHeader\">"
            f"<div class=\"chapterHeader__icon\" aria-hidden=\"true\"><svg class=\"icon\" viewBox=\"0 0 24 24\" aria-hidden=\"true\"><use href=\"#{icon_id}\"></use></svg></div>"
            "<div><div class=\"chapterHeader__kicker\">Section</div>"
            f"<h2 class=\"chapterHeader__title\">{html.escape(section['title'])}</h2></div></header>"
            f"<div class=\"chapterBody\">{body_html}</div>"
            "</section>"
        )

    base_dir = Path(__file__).resolve().parents[1]
    logo_path = Path(meta.get("logo_path") or f"assets/logos/{ticker}.png")
    logo_src = logo_path if logo_path.is_absolute() else (base_dir / logo_path).resolve()
    logo_rel = None
    if logo_src.exists():
        logo_rel = Path(os.path.relpath(logo_src, report_dir))

    if logo_rel:
        logo_html = f"<img src=\"{logo_rel.as_posix()}\" alt=\"{html.escape(company_name)} logo\" />"
    else:
        logo_html = (
            "<div class=\"logoBadge\">"
            f"<div class=\"logoBadge__ticker\">{html.escape(ticker)}</div>"
            "<div class=\"logoBadge__label\">Company Logo</div>"
            "</div>"
        )

    summary_html = build_summary_html(
        meta.get("summary") or extracted.get("summary") or "N/A",
        meta.get("sector") or "N/A",
        meta.get("industry") or "N/A",
    )

    template_text = template_path.read_text()
    template = Template(template_text)

    html_out = template.safe_substitute(
        page_title=f"{ticker} Equity Research",
        accent=(meta.get("theme", {}) or {}).get("accent", "#1C4EB2"),
        accent_secondary=(meta.get("theme", {}) or {}).get("accent_secondary", "#147B7B"),
        ticker=ticker,
        headline=headline,
        date=date,
        built_by=built_by,
        confidence=confidence,
        recommendation=recommendation.upper(),
        score=kpi_values.get("score", "N/A"),
        kpi_html=build_kpi_html(kpi_values, kpi_values.get("rating", "N/A")),
        summary_html=summary_html,
        logo_html=logo_html,
        disclaimer=meta.get("disclaimer") or DEFAULT_DISCLAIMER,
        toc_links="\n".join(toc_links),
        toc_cards="\n".join(toc_cards),
        sections_html="\n".join(sections_html),
        cover_svg="",
    )

    output_path.write_text(html_out)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render Equity Research Report HTML")
    parser.add_argument("--report-dir", required=True, help="Path to report directory (contains Equity_Research_Report.md)")
    parser.add_argument(
        "--template",
        default=str(Path(__file__).resolve().parents[1] / "templates" / "equity_report_template.html"),
        help="Path to HTML template",
    )
    parser.add_argument("--output", default=None, help="Output HTML path")
    args = parser.parse_args()

    report_dir = Path(args.report_dir).resolve()
    template_path = Path(args.template).resolve()
    output_path = Path(args.output).resolve() if args.output else report_dir / "index.single.html"

    render_report(report_dir, template_path, output_path)
    print(f"Rendered report to {output_path}")


if __name__ == "__main__":
    main()
