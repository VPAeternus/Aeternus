"""3-tier content generation pipeline for X (Twitter) distribution.

Generates hook post, analysis post, and full article from an existing
analysis_report.json.  Pure template assembly — zero LLM calls, zero API cost.
"""

import html as html_mod
import json
import os
import re
import textwrap
from pathlib import Path
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _first_sentence(text: str) -> str:
    """Return the first sentence of *text*."""
    if not text:
        return ""
    for end in (". ", ".\n"):
        idx = text.find(end)
        if idx != -1:
            return text[: idx + 1].strip()
    return text.strip()


def _trim_to_words(text: str, max_words: int) -> str:
    """Trim *text* to approximately *max_words* words at a sentence boundary."""
    if not text:
        return ""
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    truncated = " ".join(words[:max_words])
    # Try to end at a sentence boundary
    for end in (". ", ".\n"):
        idx = truncated.rfind(end)
        if idx != -1:
            return truncated[: idx + 1].strip()
    return truncated.strip() + "..."


def _safe_get(d: Any, *keys: str, default: Any = None) -> Any:
    """Nested dict access with fallback."""
    val = d
    for k in keys:
        if not isinstance(val, dict):
            return default
        val = val.get(k, default)
    return val


def _fmt_score(val: Any) -> str:
    if val is None:
        return "N/A"
    try:
        return str(int(round(float(val))))
    except (TypeError, ValueError):
        return "N/A"


def _fmt_float(val: Any, decimals: int = 2) -> str:
    if val is None:
        return "N/A"
    try:
        return f"{float(val):.{decimals}f}"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_pct(val: Any) -> str:
    if val is None:
        return "N/A"
    try:
        return f"{float(val):.0f}%"
    except (TypeError, ValueError):
        return "N/A"


def _load_report(ticker: str, date: str) -> dict:
    """Load analysis_report.json for *ticker*/*date*."""
    path = Path("results") / ticker / date / "analysis_report.json"
    if not path.exists():
        raise FileNotFoundError(f"Report not found: {path}")
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Post #1 — Hook (<280 chars)
# ---------------------------------------------------------------------------

def generate_hook_post(report: dict) -> str:
    """Generate a short hook post for X (<280 chars)."""
    ticker = report.get("company_of_interest", "???")
    score_dict = report.get("aeternus_score", {})
    score = _fmt_float(score_dict.get("aeternus_score"))
    rating = score_dict.get("rating", "N/A")
    confidence = _safe_get(report, "structured_trader_verdict", "conviction", default=score_dict.get("confidence", "?"))

    # Decision from structured verdict or final_trade_decision
    decision = _safe_get(report, "structured_trader_verdict", "decision", default="")
    if not decision:
        ftd = report.get("final_trade_decision", "")
        if ftd:
            decision = ftd.split()[0] if ftd.split() else rating
        else:
            decision = rating

    # Alpha
    alpha_raw = _safe_get(score_dict, "alpha_decomposition", "alpha_residual")
    alpha_interp = _safe_get(score_dict, "alpha_decomposition", "interpretation", default="")
    if alpha_raw is not None:
        sign = "+" if float(alpha_raw) >= 0 else ""
        alpha_str = f"Alpha: {sign}{_fmt_float(alpha_raw)} ({alpha_interp})"
    else:
        alpha_str = ""

    # One-line hook from judge_decision or final_trade_decision
    judge = _safe_get(report, "investment_debate_state", "judge_decision", default="")
    hook_line = _first_sentence(judge)
    if not hook_line:
        hook_line = _first_sentence(report.get("final_trade_decision", ""))

    # Strip leading verdict prefix if it duplicates ticker/decision (e.g. "VERDICT: GOOGL is a BUY...")
    for prefix in (
        "JUDGE VERDICT:",
        "VERDICT:",
        "VERDICT -",
        f"VERDICT: {ticker}",
        "The research manager's verdict:",
    ):
        if hook_line.upper().startswith(prefix.upper()):
            hook_line = hook_line[len(prefix):].strip()
            # Remove leading "is a BUY" etc since we already show decision
            for starter in ("is a BUY", "is a SELL", "is a HOLD", "is a STRONG BUY", "is a STRONG SELL"):
                if hook_line.lower().startswith(starter.lower()):
                    hook_line = hook_line[len(starter):].strip()
                    if hook_line.startswith("."):
                        hook_line = hook_line[1:].strip()
                    break
            break

    lines = [f"${ticker} — {decision} ({confidence}/5)"]
    lines.append(f"Score: {score}/100 | {alpha_str}" if alpha_str else f"Score: {score}/100")
    if hook_line:
        lines.append(hook_line)
    lines.append("Analysis to follow.")

    post = "\n\n".join(lines)

    # If over 280 chars, shorten the hook line
    if len(post) > 280 and hook_line:
        words = hook_line.split()
        while len(post) > 280 and len(words) > 5:
            words = words[:-1]
            shortened = " ".join(words) + "..."
            lines_copy = [lines[0], lines[1], shortened, "Analysis to follow."]
            post = "\n\n".join(lines_copy)

    return post


# ---------------------------------------------------------------------------
# Post #2 — Analysis (~800-1200 chars)
# ---------------------------------------------------------------------------

def generate_analysis_post(report: dict) -> str:
    """Generate a medium standalone analysis post for X."""
    ticker = report.get("company_of_interest", "???")
    score_dict = report.get("aeternus_score", {})
    score = _fmt_float(score_dict.get("aeternus_score"))
    rating = score_dict.get("rating", "N/A")
    confidence = _safe_get(report, "structured_trader_verdict", "conviction", default=score_dict.get("confidence", "?"))

    # Decision line
    ftd = report.get("final_trade_decision", "")
    decision_line = _first_sentence(ftd) if ftd else f"{rating} — {ticker}"

    # Bull/bear summaries
    bull = _safe_get(report, "investment_debate_state", "bull_history", default="")
    bear = _safe_get(report, "investment_debate_state", "bear_history", default="")
    bull_summary = _trim_to_words(bull, 150)
    bear_summary = _trim_to_words(bear, 150)

    # Judge
    judge = _safe_get(report, "investment_debate_state", "judge_decision", default="")

    # Score breakdown
    breakdown = score_dict.get("breakdown", {})
    weights = score_dict.get("regime_weights", {})

    # Alpha
    alpha_raw = _safe_get(score_dict, "alpha_decomposition", "alpha_residual")
    alpha_interp = _safe_get(score_dict, "alpha_decomposition", "interpretation", default="")
    if alpha_raw is not None:
        sign = "+" if float(alpha_raw) >= 0 else ""
        alpha_line = f"Alpha Residual: {sign}{_fmt_float(alpha_raw)} ({alpha_interp})"
    else:
        alpha_line = ""

    # Risk
    risk_judge = _safe_get(report, "risk_debate_state", "judge_decision", default="")
    risk_line = _first_sentence(risk_judge) if risk_judge else ""

    parts = []
    parts.append(f"${ticker} — {rating} (Score: {score}/100, Confidence: {confidence}/5)")
    parts.append(f"Decision: {decision_line}")

    if bull_summary:
        parts.append(f"THE CASE FOR:\n{bull_summary}")
    if bear_summary:
        parts.append(f"THE CASE AGAINST:\n{bear_summary}")
    if judge:
        parts.append(f"WHAT TIPPED THE BALANCE:\n{judge}")

    # Pillar table
    pillar_lines = ["KEY NUMBERS:"]
    pillar_order = ["fundamental", "coherence", "macro", "sentiment", "momentum"]
    for p in pillar_order:
        s = _fmt_score(breakdown.get(p))
        w = weights.get(p)
        w_str = f" ({_fmt_pct(w * 100)})" if w is not None else ""
        pillar_lines.append(f"  {p.capitalize()}{w_str}: {s}")
    parts.append("\n".join(pillar_lines))

    if alpha_line:
        parts.append(alpha_line)
    if risk_line:
        parts.append(f"Risk: {risk_line}")

    parts.append("Here is the article and full analysis if anyone wants details.")

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Post #3 — Full Article (Markdown, 2000-4000 words)
# ---------------------------------------------------------------------------

def generate_article(report: dict) -> str:
    """Generate a full X article in Markdown from existing report sections."""
    ticker = report.get("company_of_interest", "???")
    date = report.get("trade_date", "")
    score_dict = report.get("aeternus_score", {})
    score = _fmt_float(score_dict.get("aeternus_score"))
    rating = score_dict.get("rating", "N/A")

    # Narrative sections
    fundamentals = report.get("fundamentals_report", "")
    market = report.get("market_report", "")
    sentiment = report.get("sentiment_report", "")
    news = report.get("news_report", "")

    # Debate
    debate = report.get("investment_debate_state", {})
    bull = debate.get("bull_history", "")
    bear = debate.get("bear_history", "")
    debate_synthesis = debate.get("history", "")
    judge = debate.get("judge_decision", "")

    # Trader
    ftd = report.get("final_trade_decision", "")

    # Risk
    risk = report.get("risk_debate_state", {})
    risky = risk.get("risky_history", "")
    safe = risk.get("safe_history", "")
    neutral = risk.get("neutral_history", "")
    risk_judge = risk.get("judge_decision", "")

    # Score details
    breakdown = score_dict.get("breakdown", {})
    weights = score_dict.get("regime_weights", {})
    weight_regime = score_dict.get("weight_regime", "")
    alpha_decomp = score_dict.get("alpha_decomposition", {})
    epistemic = score_dict.get("epistemic", {})
    epistemic_summary = score_dict.get("epistemic_summary", {})

    # Sub-scores
    fund_sub = score_dict.get("fundamental_sub", {})
    coh_sub = score_dict.get("coherence_sub", {})
    macro_sub = score_dict.get("macro_sub", {})
    sent_sub = score_dict.get("sentiment_sub", {})
    mom_sub = score_dict.get("momentum_sub", {})

    # Verdict
    verdict = report.get("structured_trader_verdict", {})
    scenarios = verdict.get("scenarios", [])
    invalidation = verdict.get("invalidation_conditions", [])

    # Alpha
    alpha_residual = alpha_decomp.get("alpha_residual")
    alpha_interp = alpha_decomp.get("interpretation", "")

    # Build article
    sections = []

    # Title
    sections.append(f"# ${ticker} — {rating}: AI-Powered Investment Analysis")
    sections.append(f"*{date} | Aeternus Multi-Agent System | Score: {score}/100*")

    # Executive Summary
    if judge:
        sections.append("## Executive Summary")
        sections.append(judge)

    # The Verdict
    if ftd:
        sections.append("## The Verdict")
        sections.append(ftd)

    sections.append("---")

    # Fundamental Analysis
    if fundamentals:
        sections.append("## Fundamental Analysis")
        sections.append(fundamentals)

    # Technical & Momentum
    if market:
        sections.append("## Technical & Momentum Analysis")
        sections.append(market)

    # Sentiment
    if sentiment:
        sections.append("## Sentiment & Social Analysis")
        sections.append(sentiment)

    # News
    if news:
        sections.append("## News & Catalyst Analysis")
        sections.append(news)

    sections.append("---")

    # Bull/Bear/Synthesis
    if bull:
        sections.append("## The Bull Case")
        sections.append(bull)

    if bear:
        sections.append("## The Bear Case")
        sections.append(bear)

    if debate_synthesis:
        sections.append("## Debate Synthesis")
        sections.append(debate_synthesis)

    sections.append("---")

    # Risk Assessment
    sections.append("## Risk Assessment")
    if risky:
        sections.append("### Aggressive View")
        sections.append(risky)
    if safe:
        sections.append("### Conservative View")
        sections.append(safe)
    if neutral:
        sections.append("### Balanced View")
        sections.append(neutral)
    if risk_judge:
        sections.append("### Risk Verdict")
        sections.append(risk_judge)

    sections.append("---")

    # Score Breakdown table
    sections.append("## Score Breakdown")
    sections.append("")
    sections.append("| Pillar | Weight | Score | Sub-scores |")
    sections.append("|--------|--------|-------|------------|")

    def _sub_str(sub: dict) -> str:
        if not sub:
            return ""
        return ", ".join(f"{k.replace('_', ' ').title()}: {_fmt_score(v)}" for k, v in sub.items())

    pillar_data = [
        ("Fundamental", weights.get("fundamental"), breakdown.get("fundamental"), fund_sub),
        ("Coherence", weights.get("coherence"), breakdown.get("coherence"), coh_sub),
        ("Macro", weights.get("macro"), breakdown.get("macro"), macro_sub),
        ("Sentiment", weights.get("sentiment"), breakdown.get("sentiment"), sent_sub),
        ("Momentum", weights.get("momentum"), breakdown.get("momentum"), mom_sub),
    ]
    for name, w, s, sub in pillar_data:
        w_str = _fmt_pct(w * 100) if w is not None else "N/A"
        sections.append(f"| {name} | {w_str} | {_fmt_score(s)} | {_sub_str(sub)} |")

    sections.append("")

    # Composite line
    composite_parts = [f"**Composite:** {score}/100"]
    if alpha_residual is not None:
        sign = "+" if float(alpha_residual) >= 0 else ""
        composite_parts.append(f"**Alpha Residual:** {sign}{_fmt_float(alpha_residual)} ({alpha_interp})")
    if weight_regime:
        composite_parts.append(f"**Regime:** {weight_regime}")
    ep_conf = epistemic_summary.get("overall_confidence") if epistemic_summary else None
    if ep_conf:
        composite_parts.append(f"**Epistemic Confidence:** {ep_conf}")
    sections.append(" | ".join(composite_parts))

    # Scenarios
    if scenarios:
        sections.append("")
        sections.append("## Scenarios")
        sections.append("")
        sections.append("| Scenario | Probability | Outcome |")
        sections.append("|----------|-------------|---------|")
        for s in scenarios:
            name = s.get("name", "").capitalize()
            prob = s.get("probability")
            prob_str = f"{int(prob * 100)}%" if prob is not None else "N/A"
            outcome = s.get("outcome", "").replace("\n", " ")
            sections.append(f"| {name} | {prob_str} | {outcome} |")

    # Invalidation
    if invalidation:
        sections.append("")
        sections.append("## What Would Change This View")
        sections.append("")
        for cond in invalidation:
            c = cond if isinstance(cond, str) else cond.get("condition", "")
            if c:
                sections.append(f"- {c}")

    sections.append("")
    sections.append("---")
    sections.append("")
    sections.append(
        "*This analysis was generated by the Aeternus Multi-Agent Investment System — "
        "an autonomous AI research platform where specialized agents (analysts, researchers, "
        "traders, risk managers) collaborate through structured debate to produce investment "
        "decisions. Every decision is logged to a public track record.*"
    )
    sections.append("")
    sections.append("*This is not financial advice. Past performance does not guarantee future results.*")

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Markdown → HTML converter (zero dependencies)
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{
    --bg: #0d1117; --fg: #e6edf3; --muted: #8b949e; --accent: #58a6ff;
    --green: #3fb950; --red: #f85149; --yellow: #d29922; --border: #30363d;
    --surface: #161b22; --surface2: #1c2128;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    background: var(--bg); color: var(--fg);
    line-height: 1.7; max-width: 860px; margin: 0 auto; padding: 40px 24px 80px;
  }}
  h1 {{
    font-size: 1.9em; margin: 0 0 8px; border-bottom: 1px solid var(--border);
    padding-bottom: 12px; color: var(--fg);
  }}
  h2 {{
    font-size: 1.4em; margin: 48px 0 16px; color: var(--accent);
    border-bottom: 1px solid var(--border); padding-bottom: 8px;
  }}
  h3 {{ font-size: 1.15em; margin: 32px 0 12px; color: var(--fg); }}
  p {{ margin: 0 0 16px; }}
  .subtitle {{ color: var(--muted); font-style: italic; margin-bottom: 32px; }}
  hr {{ border: none; border-top: 1px solid var(--border); margin: 40px 0; }}
  strong {{ color: var(--fg); font-weight: 600; }}
  em {{ color: var(--muted); }}
  ul {{ margin: 0 0 16px 24px; }}
  li {{ margin: 4px 0; }}
  table {{
    width: 100%; border-collapse: collapse; margin: 16px 0 24px;
    font-size: 0.92em;
  }}
  th {{
    text-align: left; padding: 10px 14px; background: var(--surface2);
    border: 1px solid var(--border); font-weight: 600; color: var(--accent);
  }}
  td {{
    padding: 10px 14px; border: 1px solid var(--border);
    background: var(--surface); vertical-align: top;
  }}
  tr:hover td {{ background: var(--surface2); }}
  .score-badge {{
    display: inline-block; padding: 2px 10px; border-radius: 4px;
    font-weight: 600; font-size: 0.9em;
  }}
  .disclaimer {{
    margin-top: 48px; padding: 16px; border: 1px solid var(--border);
    border-radius: 6px; background: var(--surface); font-size: 0.85em;
    color: var(--muted); font-style: italic;
  }}
  @media (prefers-color-scheme: light) {{
    :root {{
      --bg: #ffffff; --fg: #1f2328; --muted: #656d76; --accent: #0969da;
      --green: #1a7f37; --red: #cf222e; --yellow: #9a6700; --border: #d0d7de;
      --surface: #f6f8fa; --surface2: #eaeef2;
    }}
  }}
</style>
</head>
<body>
{body}
</body>
</html>"""


def _md_to_html(md: str) -> str:
    """Convert the subset of Markdown used by generate_article() to HTML."""
    lines = md.split("\n")
    html_parts: list[str] = []
    in_table = False
    in_ul = False
    table_rows: list[str] = []
    ul_items: list[str] = []

    def _flush_table():
        nonlocal in_table, table_rows
        if not table_rows:
            return
        out = ["<table>"]
        for i, row_text in enumerate(table_rows):
            cells = [c.strip() for c in row_text.strip("|").split("|")]
            tag = "th" if i == 0 else "td"
            out.append("<tr>" + "".join(f"<{tag}>{_inline(c)}</{tag}>" for c in cells) + "</tr>")
        out.append("</table>")
        html_parts.append("\n".join(out))
        in_table = False
        table_rows = []

    def _flush_ul():
        nonlocal in_ul, ul_items
        if not ul_items:
            return
        html_parts.append("<ul>\n" + "\n".join(f"<li>{_inline(i)}</li>" for i in ul_items) + "\n</ul>")
        in_ul = False
        ul_items = []

    def _inline(text: str) -> str:
        """Convert inline markdown (bold, italic) to HTML."""
        t = html_mod.escape(text)
        t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"\*(.+?)\*", r"<em>\1</em>", t)
        return t

    for line in lines:
        stripped = line.strip()

        # Empty line — flush lists
        if not stripped:
            if in_ul:
                _flush_ul()
            continue

        # Horizontal rule
        if stripped == "---":
            if in_table:
                _flush_table()
            if in_ul:
                _flush_ul()
            html_parts.append("<hr>")
            continue

        # Table row
        if stripped.startswith("|") and stripped.endswith("|"):
            # Skip separator row (|---|---|)
            if re.match(r"^\|[\s\-:|]+\|$", stripped):
                continue
            if not in_table:
                if in_ul:
                    _flush_ul()
                in_table = True
            table_rows.append(stripped)
            continue
        elif in_table:
            _flush_table()

        # List item
        if stripped.startswith("- "):
            if not in_ul:
                in_ul = True
            ul_items.append(stripped[2:])
            continue
        elif in_ul:
            _flush_ul()

        # Headers
        if stripped.startswith("### "):
            html_parts.append(f"<h3>{_inline(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            html_parts.append(f"<h2>{_inline(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            html_parts.append(f"<h1>{_inline(stripped[2:])}</h1>")
        # Italic line (subtitle)
        elif stripped.startswith("*") and stripped.endswith("*") and not stripped.startswith("**"):
            html_parts.append(f'<p class="subtitle">{_inline(stripped[1:-1])}</p>')
        else:
            html_parts.append(f"<p>{_inline(stripped)}</p>")

    # Flush any remaining
    if in_table:
        _flush_table()
    if in_ul:
        _flush_ul()

    return "\n".join(html_parts)


def generate_article_html(report: dict) -> str:
    """Generate a styled HTML article from a report dict."""
    md = generate_article(report)
    ticker = report.get("company_of_interest", "???")
    rating = report.get("aeternus_score", {}).get("rating", "N/A")
    title = f"{ticker} — {rating} | Aeternus Analysis"
    body = _md_to_html(md)
    return _HTML_TEMPLATE.format(title=html_mod.escape(title), body=body)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def generate_all_posts(
    ticker: str,
    date: str,
    report: Optional[dict] = None,
) -> dict:
    """Generate all 3 posts and save to disk.

    Returns {"hook": str, "analysis": str, "article": str, "paths": {...}}.
    """
    if report is None:
        report = _load_report(ticker, date)

    hook = generate_hook_post(report)
    analysis = generate_analysis_post(report)
    article = generate_article(report)
    article_html = generate_article_html(report)

    # Save to disk
    posts_dir = Path("results") / ticker / date / "posts"
    posts_dir.mkdir(parents=True, exist_ok=True)

    hook_path = posts_dir / "post_1_hook.txt"
    analysis_path = posts_dir / "post_2_analysis.txt"
    article_path = posts_dir / "post_3_article.md"
    html_path = posts_dir / "post_3_article.html"

    hook_path.write_text(hook)
    analysis_path.write_text(analysis)
    article_path.write_text(article)
    html_path.write_text(article_html)

    return {
        "hook": hook,
        "analysis": analysis,
        "article": article,
        "article_html": article_html,
        "paths": {
            "hook": str(hook_path),
            "analysis": str(analysis_path),
            "article": str(article_path),
            "article_html": str(html_path),
        },
    }
