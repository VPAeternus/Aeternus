"""Portfolio dashboard command — generates a self-contained HTML investor dashboard."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer

from cli.common import app

_LANE_COLORS = {
    "CORE": ("#c8a535", "#2a1f00"),        # gold on dark-gold
    "MOMENTUM": ("#4db8ff", "#001a2a"),    # sky-blue on deep-navy
    "HEDGE": ("#a0c878", "#0f1e08"),       # sage on dark-green
}


def _lane_badge(lane: str) -> str:
    bg_color, text_color = _LANE_COLORS.get(lane, ("#6b7280", "#fff"))
    return (
        f'<span class="lane-badge" style="background:{bg_color};color:{text_color}">'
        f"{lane}</span>"
    )


def _pnl_cell(val: float, is_pct: bool = True) -> str:
    cls = "pos" if val >= 0 else "neg"
    fmt = f"{val:+.2f}{'%' if is_pct else ''}"
    return f'<span class="{cls}">{fmt}</span>'


def _status_color(status: str) -> str:
    return {"OK": "#3cb878", "WARNING": "#f0a000", "ALERT": "#e03030"}.get(status, "#6b7280")


def _build_html(data: dict) -> str:
    summary = data.get("summary", {})
    positions = data.get("positions", [])
    perf = data.get("performance", {})
    risk = data.get("risk", {})
    signals = data.get("signals", {})

    gen_date = data.get("date", "N/A")
    gen_ts = data.get("generated_at", "")

    # Equity KPI
    equity = summary.get("equity", 0)
    hwm = summary.get("hwm", 0)
    dd_pct = summary.get("drawdown_pct", 0.0)
    dd_status = summary.get("drawdown_status", "OK")
    n_positions = summary.get("total_positions", 0)
    win_rate = summary.get("win_rate", 0.0)
    gross_exp = summary.get("gross_exposure", 0)
    net_exp = summary.get("net_exposure", 0)
    sharpe = summary.get("sharpe_proxy", 0)

    dd_color = _status_color(dd_status)

    # Status banner (WARNING/ALERT = hedge engine should be active)
    status_banner = ""
    if dd_status in ("WARNING", "ALERT"):
        banner_bg = "#2a0d00" if dd_status == "ALERT" else "#1e1600"
        banner_border = dd_color
        status_banner = f"""
        <div class="status-banner" style="border-left-color:{banner_border};background:{banner_bg}">
            <strong style="color:{banner_border}">{dd_status}:</strong>
            Portfolio is {dd_pct:.1f}% below high water mark.
            {"Immediate review required — check hedge engine and open positions." if dd_status == "ALERT" else "Review open positions and signals. Hedge engine should be active."}
        </div>"""

    # Exposure bar
    total_exp = gross_exp if gross_exp > 0 else 1
    long_pct = (sum(p["notional"] for p in positions if p["direction"] == "LONG") / total_exp * 100) if total_exp else 0
    short_pct = (sum(p["notional"] for p in positions if p["direction"] == "SHORT") / total_exp * 100) if total_exp else 0

    # Position rows
    pos_rows = ""
    for pos in positions:
        lane_html = _lane_badge(pos.get("lane", "CORE"))
        pnl_cell = _pnl_cell(pos["pnl_pct"], is_pct=True)
        direction_cls = "dir-long" if pos["direction"] == "LONG" else "dir-short"
        pos_rows += f"""
        <tr>
            <td class="sym-col"><strong>{pos['symbol']}</strong></td>
            <td>{lane_html}</td>
            <td class="{direction_cls}">{pos['direction']}</td>
            <td class="num">{pos['net_quantity']:,.2f}</td>
            <td class="num">${pos['avg_price']:,.2f}</td>
            <td class="num">${pos['mark_price']:,.2f}</td>
            <td class="num">{pnl_cell}</td>
            <td class="num">${pos['notional']:,.0f}</td>
            <td class="num">{pos['hold_days']}d</td>
        </tr>"""

    if not pos_rows:
        pos_rows = '<tr><td colspan="9" class="empty-row">No open positions.</td></tr>'

    # Equity chart data
    equity_history = perf.get("equity_history", [])
    chart_labels = json.dumps([pt["date"] for pt in equity_history])
    chart_values = json.dumps([pt["equity"] for pt in equity_history])
    has_chart_data = len(equity_history) >= 3
    chart_section = ""
    if has_chart_data:
        chart_section = """
        <div class="chart-container">
            <canvas id="equityChart" height="160"></canvas>
        </div>"""
    else:
        chart_section = """
        <div class="chart-placeholder">
            <span class="placeholder-label">Track record building — need 3+ closed trades for chart.</span>
        </div>"""

    # Lane table
    by_lane = perf.get("by_lane", {})
    lane_rows = ""
    for lane in ["CORE", "MOMENTUM", "HEDGE"]:
        ls = by_lane.get(lane)
        if ls:
            lane_rows += f"""
            <tr>
                <td>{_lane_badge(lane)}</td>
                <td class="num">{ls['trades']}</td>
                <td class="num">{ls['win_rate']:.0%}</td>
                <td class="num">{_pnl_cell(ls['avg_pnl_pct'], is_pct=True)}</td>
            </tr>"""
    if not lane_rows:
        lane_rows = '<tr><td colspan="4" class="empty-row">No closed trades yet.</td></tr>'

    # Recent trades
    recent_rows = ""
    for t in perf.get("closed_trades", []):
        pnl_cell = _pnl_cell(t["pnl_pct"], is_pct=True)
        recent_rows += f"""
        <tr>
            <td><strong>{t['symbol']}</strong></td>
            <td class="num">{t['exit_date']}</td>
            <td class="num">{t['hold_days']}d</td>
            <td class="num">{pnl_cell}</td>
            <td>${t['pnl_usd']:+,.0f}</td>
            <td>{t['exit_reason']}</td>
        </tr>"""
    if not recent_rows:
        recent_rows = '<tr><td colspan="6" class="empty-row">No closed trades.</td></tr>'

    # Risk cards
    dg = risk.get("drawdown_guard", {})
    conc_flags = risk.get("concentration_flags", [])
    pending_exits = risk.get("pending_exits", 0)

    conc_html = ""
    if conc_flags:
        conc_items = "".join(f"<li>{f}</li>" for f in conc_flags)
        conc_html = f'<ul class="conc-list">{conc_items}</ul>'
    else:
        conc_html = '<span class="ok-label">No concentration flags.</span>'

    # Signals table
    signal_rows = ""
    for sig in signals.get("top_queue", []):
        score_color = "#3cb878" if sig["score"] >= 65 else ("#f0a000" if sig["score"] >= 50 else "#e03030")
        signal_rows += f"""
        <tr>
            <td><strong>{sig['symbol']}</strong></td>
            <td class="num" style="color:{score_color};font-weight:700">{sig['score']:.1f}</td>
            <td>{sig['direction']}</td>
            <td>{sig['family']}</td>
        </tr>"""
    if not signal_rows:
        signal_rows = '<tr><td colspan="4" class="empty-row">No signals queued.</td></tr>'

    causal_count = signals.get("causal_candidates", 0)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Aeternus Portfolio Dashboard — {gen_date}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Source+Code+Pro:wght@400;600&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
    <style>
        :root {{
            --bg:        #0c1624;
            --surface:   #111e30;
            --surface2:  #172035;
            --border:    rgba(200, 165, 53, 0.12);
            --border-bright: rgba(200, 165, 53, 0.28);
            --text:      #ede5cc;
            --text-dim:  #8a8070;
            --accent:    #c8a535;
            --accent-dim: rgba(200, 165, 53, 0.10);
            --green:     #3cb878;
            --green-dim: rgba(60, 184, 120, 0.12);
            --red:       #e03030;
            --red-dim:   rgba(224, 48, 48, 0.12);
            --font-body: 'Instrument Serif', Georgia, serif;
            --font-mono: 'Source Code Pro', 'SF Mono', Consolas, monospace;
        }}

        *, *::before, *::after {{ box-sizing: border-box; }}

        html {{ scroll-behavior: smooth; }}

        body {{
            background: var(--bg);
            background-image: radial-gradient(ellipse at 50% 0%, rgba(200,165,53,0.05) 0%, transparent 55%);
            color: var(--text);
            font-family: var(--font-body);
            font-size: 16px;
            line-height: 1.6;
            margin: 0;
            padding: 0 40px 60px;
            overflow-wrap: break-word;
        }}

        /* ─── Layout ─── */
        .wrap {{
            max-width: 1400px;
            margin: 0 auto;
            display: grid;
            grid-template-columns: 170px 1fr;
            gap: 0 40px;
        }}
        .main {{ min-width: 0; }}

        /* ─── TOC Sidebar ─── */
        .toc {{
            position: sticky;
            top: 24px;
            align-self: start;
            padding: 14px 0;
            grid-row: 1 / -1;
            max-height: calc(100dvh - 48px);
            overflow-y: auto;
        }}
        .toc::-webkit-scrollbar {{ width: 3px; }}
        .toc::-webkit-scrollbar-thumb {{ background: var(--surface2); border-radius: 2px; }}

        .toc-title {{
            font-family: var(--font-mono);
            font-size: 9px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 2px;
            color: var(--text-dim);
            padding: 0 0 10px;
            margin-bottom: 8px;
            border-bottom: 1px solid var(--border);
        }}
        .toc a {{
            display: block;
            font-family: var(--font-mono);
            font-size: 11px;
            color: var(--text-dim);
            text-decoration: none;
            padding: 4px 8px;
            border-radius: 5px;
            border-left: 2px solid transparent;
            transition: all 0.15s;
            line-height: 1.4;
            margin-bottom: 1px;
        }}
        .toc a:hover {{ color: var(--text); background: var(--surface2); }}
        .toc a.active {{ color: var(--accent); border-left-color: var(--accent); }}

        /* ─── Page Header ─── */
        .page-header {{
            padding: 48px 0 32px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 40px;
        }}
        .page-header__eyebrow {{
            font-family: var(--font-mono);
            font-size: 10px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 2px;
            color: var(--accent);
            margin-bottom: 8px;
        }}
        .page-header__title {{
            font-size: clamp(28px, 4vw, 42px);
            font-weight: normal;
            font-style: italic;
            line-height: 1.15;
            margin: 0 0 8px;
            color: var(--text);
        }}
        .page-header__meta {{
            font-family: var(--font-mono);
            font-size: 11px;
            color: var(--text-dim);
        }}

        /* ─── Section Headings ─── */
        .sec-head {{
            font-family: var(--font-mono);
            font-size: 10px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 2px;
            color: var(--accent);
            padding: 28px 0 12px;
            margin-bottom: 16px;
            border-bottom: 1px solid var(--border);
            scroll-margin-top: 24px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .sec-head::before {{
            content: '';
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: var(--accent);
            flex-shrink: 0;
        }}

        /* ─── Status Banner ─── */
        .status-banner {{
            border-left: 4px solid;
            border-radius: 6px;
            padding: 14px 18px;
            margin-bottom: 24px;
            font-size: 14px;
            line-height: 1.5;
        }}

        /* ─── KPI Cards ─── */
        .kpi-row {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 14px;
            margin-bottom: 24px;
        }}
        .kpi-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 18px 20px;
            animation: fadeScale 0.35s ease-out both;
            animation-delay: calc(var(--i, 0) * 0.06s);
        }}
        .kpi-card__value {{
            font-size: 28px;
            font-weight: 400;
            font-style: italic;
            line-height: 1.1;
            font-variant-numeric: tabular-nums;
            color: var(--text);
            margin-bottom: 6px;
        }}
        .kpi-card__label {{
            font-family: var(--font-mono);
            font-size: 10px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1.5px;
            color: var(--text-dim);
        }}

        /* ─── Exposure Bar ─── */
        .exposure-wrap {{
            margin-bottom: 28px;
        }}
        .exposure-label {{
            font-family: var(--font-mono);
            font-size: 11px;
            color: var(--text-dim);
            margin-bottom: 8px;
            display: flex;
            justify-content: space-between;
        }}
        .exposure-bar {{
            height: 8px;
            background: var(--surface2);
            border-radius: 4px;
            overflow: hidden;
            display: flex;
        }}
        .exposure-long {{ background: var(--green); border-radius: 4px 0 0 4px; }}
        .exposure-short {{ background: var(--red); border-radius: 0 4px 4px 0; }}

        /* ─── Tables ─── */
        .table-wrap {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            overflow: hidden;
            margin-bottom: 24px;
        }}
        .table-scroll {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
        table.data-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            line-height: 1.4;
        }}
        table.data-table thead {{
            position: sticky;
            top: 0;
            z-index: 2;
        }}
        table.data-table th {{
            background: var(--surface2);
            font-family: var(--font-mono);
            font-size: 10px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-dim);
            text-align: left;
            padding: 11px 14px;
            border-bottom: 1px solid var(--border-bright);
            white-space: nowrap;
        }}
        table.data-table td {{
            padding: 11px 14px;
            border-bottom: 1px solid var(--border);
            vertical-align: middle;
            color: var(--text);
        }}
        table.data-table tbody tr:nth-child(even) {{ background: rgba(200,165,53,0.03); }}
        table.data-table tbody tr:hover {{ background: rgba(200,165,53,0.07); }}
        table.data-table tbody tr:last-child td {{ border-bottom: none; }}
        table.data-table td.num {{
            text-align: right;
            font-family: var(--font-mono);
            font-size: 12px;
            font-variant-numeric: tabular-nums;
        }}
        table.data-table th.num {{ text-align: right; }}
        .sym-col {{ font-family: var(--font-mono); font-size: 13px; }}'
        .empty-row {{
            text-align: center;
            color: var(--text-dim);
            font-family: var(--font-mono);
            font-size: 12px;
            padding: 24px;
        }}

        /* ─── Lane Badges ─── */
        .lane-badge {{
            font-family: var(--font-mono);
            font-size: 9px;
            font-weight: 600;
            padding: 2px 8px;
            border-radius: 4px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}

        /* ─── Direction colors ─── */
        .dir-long {{ color: var(--green); font-family: var(--font-mono); font-size: 12px; }}
        .dir-short {{ color: var(--red); font-family: var(--font-mono); font-size: 12px; }}

        /* ─── P&L colors ─── */
        .pos {{ color: var(--green); }}
        .neg {{ color: var(--red); }}
        .ok-label {{ color: var(--green); font-family: var(--font-mono); font-size: 12px; }}

        /* ─── Risk cards ─── */
        .risk-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 14px;
            margin-bottom: 24px;
        }}
        .risk-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 18px 20px;
        }}
        .risk-card__label {{
            font-family: var(--font-mono);
            font-size: 10px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1.5px;
            color: var(--text-dim);
            margin-bottom: 8px;
        }}
        .risk-card__value {{
            font-family: var(--font-mono);
            font-size: 18px;
            font-weight: 600;
        }}

        .conc-list {{
            list-style: none;
            padding: 0;
            margin: 0;
            font-family: var(--font-mono);
            font-size: 12px;
        }}
        .conc-list li {{
            padding: 4px 0 4px 14px;
            position: relative;
            color: var(--accent);
        }}
        .conc-list li::before {{
            content: '!';
            position: absolute;
            left: 0;
            color: var(--accent);
            font-weight: 700;
        }}

        /* ─── Chart ─── */
        .chart-container {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 24px;
        }}
        .chart-placeholder {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 40px 24px;
            margin-bottom: 24px;
            text-align: center;
        }}
        .placeholder-label {{
            font-family: var(--font-mono);
            font-size: 12px;
            color: var(--text-dim);
        }}

        /* ─── Footer ─── */
        .page-footer {{
            margin-top: 60px;
            padding-top: 24px;
            border-top: 1px solid var(--border);
            font-family: var(--font-mono);
            font-size: 11px;
            color: var(--text-dim);
            text-align: center;
        }}

        /* ─── Animations ─── */
        @keyframes fadeScale {{
            from {{ opacity: 0; transform: scale(0.96); }}
            to {{ opacity: 1; transform: scale(1); }}
        }}
        @keyframes fadeUp {{
            from {{ opacity: 0; transform: translateY(10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}

        /* ─── Mobile ─── */
        @media (max-width: 1000px) {{
            body {{ padding: 0 20px 40px; }}
            .wrap {{ grid-template-columns: 1fr; padding-top: 0; }}
            .toc {{
                position: sticky;
                top: 0;
                z-index: 200;
                max-height: none;
                display: flex;
                gap: 4px;
                align-items: center;
                overflow-x: auto;
                -webkit-overflow-scrolling: touch;
                background: var(--bg);
                border-bottom: 1px solid var(--border);
                padding: 10px 0;
                margin: 0 -20px;
                padding-left: 20px;
                padding-right: 20px;
                grid-row: auto;
            }}
            .toc::-webkit-scrollbar {{ display: none; }}
            .toc-title {{ display: none; }}
            .toc a {{
                white-space: nowrap;
                flex-shrink: 0;
                border-left: none;
                border-bottom: 2px solid transparent;
                border-radius: 4px 4px 0 0;
                padding: 6px 10px;
                font-size: 10px;
            }}
            .toc a.active {{
                border-left: none;
                border-bottom-color: var(--accent);
                background: var(--surface);
            }}
            .main {{ padding-top: 20px; }}
            .sec-head {{ scroll-margin-top: 52px; }}
        }}

        /* ─── Print ─── */
        @media print {{
            .toc {{ display: none; }}
            .wrap {{ grid-template-columns: 1fr; }}
        }}

        @media (prefers-reduced-motion: reduce) {{
            *, *::before, *::after {{
                animation-duration: 0.01ms !important;
                transition-duration: 0.01ms !important;
            }}
        }}
    </style>
</head>
<body>
<div class="wrap">

    <!-- TOC Sidebar -->
    <nav class="toc" id="toc">
        <div class="toc-title">Dashboard</div>
        <a href="#s1">1. Summary</a>
        <a href="#s2">2. Positions</a>
        <a href="#s3">3. Performance</a>
        <a href="#s4">4. Risk &amp; Signals</a>
    </nav>

    <!-- Main Content -->
    <div class="main">

        <!-- Page Header -->
        <div class="page-header">
            <div class="page-header__eyebrow">Aeternus Investment Intelligence</div>
            <h1 class="page-header__title">Portfolio Dashboard</h1>
            <div class="page-header__meta">
                {gen_date} &nbsp;&bull;&nbsp; Generated {gen_ts[:19].replace("T", " ")} UTC
            </div>
        </div>

        <!-- ── Section 1: Summary ── -->
        <div id="s1" class="sec-head">1 — Portfolio Summary</div>
        {status_banner}

        <div class="kpi-row">
            <div class="kpi-card" style="--i:0">
                <div class="kpi-card__value">${equity:,.0f}</div>
                <div class="kpi-card__label">Current Equity</div>
            </div>
            <div class="kpi-card" style="--i:1">
                <div class="kpi-card__value" style="color:{dd_color}">{dd_pct:.1f}%</div>
                <div class="kpi-card__label">Drawdown &nbsp;<span style="color:{dd_color};font-size:9px">{dd_status}</span></div>
            </div>
            <div class="kpi-card" style="--i:2">
                <div class="kpi-card__value">{n_positions}</div>
                <div class="kpi-card__label">Open Positions</div>
            </div>
            <div class="kpi-card" style="--i:3">
                <div class="kpi-card__value">{win_rate:.0%}</div>
                <div class="kpi-card__label">Win Rate</div>
            </div>
        </div>

        <div class="exposure-wrap">
            <div class="exposure-label">
                <span>Gross: ${gross_exp:,.0f}</span>
                <span>Net: ${net_exp:+,.0f}</span>
            </div>
            <div class="exposure-bar">
                <div class="exposure-long" style="width:{long_pct:.1f}%"></div>
                <div class="exposure-short" style="width:{short_pct:.1f}%"></div>
            </div>
            <div class="exposure-label" style="margin-top:6px">
                <span style="color:var(--green)">Long {long_pct:.0f}%</span>
                <span style="color:var(--red)">Short {short_pct:.0f}%</span>
            </div>
        </div>

        <!-- ── Section 2: Open Positions ── -->
        <div id="s2" class="sec-head">2 — Open Positions</div>

        <div class="table-wrap">
            <div class="table-scroll">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Symbol</th>
                            <th>Lane</th>
                            <th>Direction</th>
                            <th class="num">Qty</th>
                            <th class="num">Avg Price</th>
                            <th class="num">Mark Price</th>
                            <th class="num">P&amp;L %</th>
                            <th class="num">Notional</th>
                            <th class="num">Days</th>
                        </tr>
                    </thead>
                    <tbody>
                        {pos_rows}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- ── Section 3: Performance ── -->
        <div id="s3" class="sec-head">3 — Performance</div>

        {chart_section}

        <div class="table-wrap" style="margin-bottom:24px">
            <div class="table-scroll">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Lane</th>
                            <th class="num">Trades</th>
                            <th class="num">Win Rate</th>
                            <th class="num">Avg P&amp;L %</th>
                        </tr>
                    </thead>
                    <tbody>
                        {lane_rows}
                    </tbody>
                </table>
            </div>
        </div>

        <div class="table-wrap">
            <div class="table-scroll">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Symbol</th>
                            <th class="num">Exit Date</th>
                            <th class="num">Hold</th>
                            <th class="num">P&amp;L %</th>
                            <th class="num">P&amp;L $</th>
                            <th>Exit Reason</th>
                        </tr>
                    </thead>
                    <tbody>
                        {recent_rows}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- ── Section 4: Risk & Signals ── -->
        <div id="s4" class="sec-head">4 — Risk &amp; Signals</div>

        <div class="risk-grid">
            <div class="risk-card">
                <div class="risk-card__label">Drawdown Guard</div>
                <div class="risk-card__value" style="color:{dd_color}">{dd_status}</div>
                <div style="font-family:var(--font-mono);font-size:11px;color:var(--text-dim);margin-top:6px">
                    {dd_pct:.2f}% from HWM ${hwm:,.0f}
                </div>
            </div>
            <div class="risk-card">
                <div class="risk-card__label">Concentration</div>
                <div>{conc_html}</div>
            </div>
            <div class="risk-card">
                <div class="risk-card__label">Pending Exits</div>
                <div class="risk-card__value" style="color:{'var(--accent)' if pending_exits > 0 else 'var(--green)'}">{pending_exits}</div>
            </div>
            <div class="risk-card">
                <div class="risk-card__label">Sharpe (Realized)</div>
                <div class="risk-card__value">{sharpe:.2f}</div>
            </div>
        </div>

        <div class="table-wrap">
            <div class="table-scroll">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Symbol</th>
                            <th class="num">Score</th>
                            <th>Direction</th>
                            <th>Signal Family</th>
                        </tr>
                    </thead>
                    <tbody>
                        {signal_rows}
                    </tbody>
                </table>
            </div>
        </div>

        <div class="page-footer">
            Aeternus Investment Intelligence Platform &nbsp;&bull;&nbsp;
            {causal_count} causal candidate{'' if causal_count == 1 else 's'} in queue &nbsp;&bull;&nbsp;
            {gen_ts[:19].replace("T", " ")} UTC
        </div>

    </div><!-- /main -->
</div><!-- /wrap -->

<script>
// ── Scroll Spy ──
(function() {{
  var toc = document.getElementById('toc');
  var links = toc.querySelectorAll('a');
  var sections = [];

  links.forEach(function(link) {{
    var id = link.getAttribute('href').slice(1);
    var el = document.getElementById(id);
    if (el) sections.push({{ id: id, el: el, link: link }});
  }});

  var observer = new IntersectionObserver(function(entries) {{
    entries.forEach(function(entry) {{
      if (entry.isIntersecting) {{
        links.forEach(function(l) {{ l.classList.remove('active'); }});
        var match = sections.find(function(s) {{ return s.el === entry.target; }});
        if (match) {{
          match.link.classList.add('active');
          if (window.innerWidth <= 1000) {{
            match.link.scrollIntoView({{ behavior: 'smooth', block: 'nearest', inline: 'center' }});
          }}
        }}
      }}
    }});
  }}, {{ rootMargin: '-10% 0px -80% 0px' }});

  sections.forEach(function(s) {{ observer.observe(s.el); }});

  links.forEach(function(link) {{
    link.addEventListener('click', function(e) {{
      e.preventDefault();
      var id = link.getAttribute('href').slice(1);
      var el = document.getElementById(id);
      if (el) {{
        el.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
        history.replaceState(null, '', '#' + id);
      }}
    }});
  }});
}})();

// ── Equity Chart ──
try {{
  var labels = {chart_labels};
  var values = {chart_values};
  if (labels.length >= 3) {{
    var canvas = document.getElementById('equityChart');
    if (canvas) {{
      var ctx = canvas.getContext('2d');
      new Chart(ctx, {{
        type: 'line',
        data: {{
          labels: labels,
          datasets: [{{
            label: 'Portfolio Equity',
            data: values,
            borderColor: '#c8a535',
            backgroundColor: 'rgba(200,165,53,0.08)',
            fill: true,
            tension: 0.3,
            pointRadius: 2,
            pointHoverRadius: 5,
            borderWidth: 2,
          }}]
        }},
        options: {{
          responsive: true,
          plugins: {{
            legend: {{
              labels: {{ color: '#8a8070', font: {{ family: "'Source Code Pro', monospace", size: 11 }} }}
            }},
            tooltip: {{
              callbacks: {{
                label: function(ctx) {{
                  return ' $' + ctx.raw.toLocaleString('en-US', {{minimumFractionDigits: 0}});
                }}
              }}
            }}
          }},
          scales: {{
            x: {{
              ticks: {{ color: '#8a8070', font: {{ family: "'Source Code Pro', monospace", size: 10 }}, maxTicksLimit: 8 }},
              grid: {{ color: 'rgba(200,165,53,0.06)' }}
            }},
            y: {{
              ticks: {{
                color: '#8a8070',
                font: {{ family: "'Source Code Pro', monospace", size: 10 }},
                callback: function(v) {{ return '$' + (v/1000).toFixed(0) + 'k'; }}
              }},
              grid: {{ color: 'rgba(200,165,53,0.06)' }}
            }}
          }}
        }}
      }});
    }}
  }}
}} catch(e) {{
  // CDN unavailable or no data — chart placeholder already shown
  console.warn('Chart.js: ' + e.message);
}}
</script>
</body>
</html>"""
    return html


@app.command("dashboard")
def portfolio_dashboard(
    output: Optional[Path] = typer.Option(
        None, "--output", help="Output HTML path. Default: ~/.agent/diagrams/dashboard-DATE.html"
    ),
    no_open: bool = typer.Option(False, "--no-open", help="Don't auto-open in browser"),
):
    """Generate a self-contained HTML portfolio dashboard and open it in the browser."""
    from rich.console import Console
    from tradingagents.graph.dashboard_builder import build_dashboard_data

    console = Console()

    console.print("[cyan]Building dashboard data...[/cyan]")
    data = build_dashboard_data()

    console.print("[cyan]Rendering HTML...[/cyan]")
    html = _build_html(data)

    # Determine output path
    if output is None:
        agent_dir = Path.home() / ".agent" / "diagrams"
        agent_dir.mkdir(parents=True, exist_ok=True)
        output = agent_dir / f"dashboard-{data['date']}.html"
    else:
        output.parent.mkdir(parents=True, exist_ok=True)

    output.write_text(html, encoding="utf-8")
    console.print(f"[green]Dashboard written to:[/green] [cyan]{output}[/cyan]")

    if not no_open:
        try:
            subprocess.run(["open", str(output)], check=True)
            console.print("[green]Opened in browser.[/green]")
        except Exception as exc:
            console.print(f"[yellow]Note:[/yellow] Could not open browser: {exc}")
