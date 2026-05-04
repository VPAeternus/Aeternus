"""Static HTML track record dashboard generator.

Renders a self-contained HTML page from track_record.json with:
- Summary stats (win rate, avg return, Sharpe, alpha vs SPY)
- Table of all rated tickers
- Chart.js cumulative return line vs SPY benchmark
"""

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def compute_track_record_stats(history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pure computation of track record stats from a flat list of rating dicts.

    Returns:
        dict with keys: total_analyses, closed_count, win_rate, avg_return,
        sharpe_ratio (float or None), date_start, date_end, cumulative_returns
    """
    total_analyses = len(history)
    closed_trades = []

    for entry in history:
        if entry.get("status") != "CLOSED":
            continue
        open_price = entry.get("price_at_rating")
        close_price = entry.get("close_price")
        if not open_price or not close_price:
            continue
        try:
            open_price = float(open_price)
            close_price = float(close_price)
        except (TypeError, ValueError):
            continue
        ret = (close_price - open_price) / open_price
        rating = entry.get("rating", "")
        if "Buy" in rating:
            win = ret > 0
        elif "Sell" in rating:
            win = ret < 0
        else:
            win = False
        closed_trades.append(
            {
                "entry": entry,
                "return_pct": ret,
                "win": win,
                "trade_date": entry.get("trade_date", ""),
            }
        )

    closed_count = len(closed_trades)

    if closed_count == 0:
        win_rate = 0.0
        avg_return = 0.0
        sharpe_ratio = None
    else:
        wins = sum(1 for t in closed_trades if t["win"])
        win_rate = wins / closed_count
        returns = [t["return_pct"] for t in closed_trades]
        avg_return = sum(returns) / len(returns)

        if closed_count >= 2:
            mean_r = avg_return
            variance = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
            std_r = math.sqrt(variance) if variance > 0 else 0.0
            sharpe_ratio = (mean_r / std_r * math.sqrt(252)) if std_r > 0 else None
        else:
            sharpe_ratio = None

    # Date range from all entries
    all_dates = [e.get("trade_date", "") for e in history if e.get("trade_date")]
    all_dates_sorted = sorted(d for d in all_dates if d)
    date_start = all_dates_sorted[0] if all_dates_sorted else None
    date_end = all_dates_sorted[-1] if all_dates_sorted else None

    # Cumulative returns for chart — closed trades sorted by trade_date
    sorted_closed = sorted(closed_trades, key=lambda t: t["trade_date"])
    cumulative = []
    cum = 1.0
    for t in sorted_closed:
        cum *= 1.0 + t["return_pct"]
        cumulative.append(
            {
                "date": t["trade_date"],
                "ticker": t["entry"].get("ticker", ""),
                "cumulative_return": round((cum - 1.0) * 100, 4),
            }
        )

    return {
        "total_analyses": total_analyses,
        "closed_count": closed_count,
        "win_rate": win_rate,
        "avg_return": avg_return,
        "sharpe_ratio": sharpe_ratio,
        "date_start": date_start,
        "date_end": date_end,
        "cumulative_returns": cumulative,
    }


def _get_spy_data(date_start: Optional[str], date_end: Optional[str]) -> Optional[Dict[str, Any]]:
    """Fetch SPY benchmark data. Returns None on any failure."""
    if not date_start:
        return None
    try:
        import yfinance as yf

        # Extend end date slightly to ensure we get data on the last day
        spy = yf.Ticker("SPY")
        hist = spy.history(start=date_start, end=date_end or datetime.now().strftime("%Y-%m-%d"))
        if hist.empty:
            return None

        spy_start_price = float(hist["Close"].iloc[0])
        spy_end_price = float(hist["Close"].iloc[-1])
        spy_return = (spy_end_price - spy_start_price) / spy_start_price

        # Build SPY cumulative series aligned to dates
        spy_series = []
        for d, row in hist.iterrows():
            date_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
            cum_r = (float(row["Close"]) - spy_start_price) / spy_start_price
            spy_series.append({"date": date_str, "cumulative_return": round(cum_r * 100, 4)})

        return {
            "spy_return": spy_return,
            "spy_series": spy_series,
        }
    except Exception:
        return None


def _score_value(entry: Dict[str, Any]) -> Optional[float]:
    """Extract numeric Aeternus score from an entry (handles nested dict)."""
    score_field = entry.get("aeternus_score")
    if isinstance(score_field, dict):
        val = score_field.get("aeternus_score")
    else:
        val = score_field
    try:
        return round(float(val), 1) if val is not None else None
    except (TypeError, ValueError):
        return None


def _return_color(ret: float) -> str:
    return "var(--green)" if ret >= 0 else "var(--red)"


def _build_table_rows(history: List[Dict[str, Any]]) -> str:
    rows = []
    for entry in sorted(history, key=lambda e: e.get("trade_date", ""), reverse=True):
        ticker = entry.get("ticker", "")
        trade_date = entry.get("trade_date", "")[:10] if entry.get("trade_date") else ""
        rating = entry.get("rating", "")
        score = _score_value(entry)
        score_str = f"{score:.1f}" if score is not None else "—"
        entry_price = entry.get("price_at_rating")
        entry_str = f"${float(entry_price):.2f}" if entry_price else "—"
        close_price = entry.get("close_price")
        close_date = (entry.get("close_date", "") or "")[:10]
        status = entry.get("status", "OPEN")

        if status == "CLOSED" and entry_price and close_price:
            try:
                ret = (float(close_price) - float(entry_price)) / float(entry_price)
                ret_str = f"{ret * 100:+.2f}%"
                ret_color = _return_color(ret)
                ret_cell = f'<td style="color:{ret_color};font-weight:600;">{ret_str}</td>'
            except (TypeError, ValueError):
                ret_cell = "<td>—</td>"
            close_str = f"${float(close_price):.2f}"
            days_held = ""
            if trade_date and close_date:
                try:
                    d0 = datetime.strptime(trade_date, "%Y-%m-%d")
                    d1 = datetime.strptime(close_date, "%Y-%m-%d")
                    days_held = str((d1 - d0).days)
                except ValueError:
                    pass
            status_cell = '<td style="color:var(--muted);">CLOSED</td>'
        else:
            ret_cell = "<td>—</td>"
            close_str = "—"
            close_date = "—"
            days_held = "—"
            status_cell = '<td style="color:var(--accent);">OPEN</td>'

        # Rating color
        if "Strong Buy" in rating or "Buy" in rating:
            rating_color = "var(--green)"
        elif "Sell" in rating:
            rating_color = "var(--red)"
        else:
            rating_color = "var(--yellow)"

        row = f"""<tr>
          <td><strong>{ticker}</strong></td>
          <td>{trade_date}</td>
          <td style="color:{rating_color};">{rating}</td>
          <td>{score_str}</td>
          <td>{entry_str}</td>
          <td>{close_str}</td>
          {ret_cell}
          <td>{days_held}</td>
          {status_cell}
        </tr>"""
        rows.append(row)
    return "\n".join(rows)


def _render_html(
    stats: Dict[str, Any],
    entries: List[Dict[str, Any]],
    spy_data: Optional[Dict[str, Any]],
) -> str:
    """Pure HTML generation from computed stats and entries."""

    total = stats["total_analyses"]
    closed = stats["closed_count"]
    win_rate = stats["win_rate"]
    avg_return = stats["avg_return"]
    sharpe = stats["sharpe_ratio"]
    date_start = stats.get("date_start", "")
    date_end = stats.get("date_end", "")
    cumulative = stats.get("cumulative_returns", [])

    # Date range label
    if date_start and date_end:
        date_range = f"{date_start} — {date_end}"
    elif date_start:
        date_range = f"Since {date_start}"
    else:
        date_range = "No trades recorded"

    # SPY stats
    spy_return = spy_data["spy_return"] if spy_data else None
    if spy_return is not None:
        total_portfolio_return = (
            cumulative[-1]["cumulative_return"] / 100 if cumulative else 0.0
        )
        alpha = total_portfolio_return - spy_return
        spy_block = f"""
        <div class="stat-card">
          <div class="stat-label">SPY Return</div>
          <div class="stat-value" style="color:var(--muted);">{spy_return * 100:+.2f}%</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Alpha vs SPY</div>
          <div class="stat-value" style="color:{'var(--green)' if alpha >= 0 else 'var(--red)'};">{alpha * 100:+.2f}%</div>
        </div>"""
    else:
        spy_block = ""

    # Sharpe display
    sharpe_str = f"{sharpe:.2f}" if sharpe is not None else "N/A"
    sharpe_color = "var(--green)" if (sharpe is not None and sharpe > 1) else "var(--muted)"

    # Cumulative return display
    if cumulative:
        cum_final = cumulative[-1]["cumulative_return"]
        cum_color = _return_color(cum_final)
        cum_str = f"{cum_final:+.2f}%"
    else:
        cum_final = 0.0
        cum_color = "var(--muted)"
        cum_str = "—"

    # Win rate color
    wr_pct = win_rate * 100
    wr_color = "var(--green)" if wr_pct >= 50 else "var(--red)"

    # Stats grid
    stats_section = f"""
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-label">Total Analyses</div>
        <div class="stat-value">{total}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Closed Trades</div>
        <div class="stat-value">{closed}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Win Rate</div>
        <div class="stat-value" style="color:{wr_color};">{wr_pct:.1f}%</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Avg Return</div>
        <div class="stat-value" style="color:{_return_color(avg_return)};">{avg_return * 100:+.2f}%</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Cumulative Return</div>
        <div class="stat-value" style="color:{cum_color};">{cum_str}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Sharpe Ratio</div>
        <div class="stat-value" style="color:{sharpe_color};">{sharpe_str}</div>
      </div>
      {spy_block}
    </div>"""

    # Empty state
    if not entries:
        body_content = """
    <div class="empty-state">
      No trades recorded yet. Run analyses and execute trades to build your track record.
    </div>"""
        chart_section = ""
        table_section = ""
    else:
        # Chart data
        chart_labels = json.dumps([c["date"] for c in cumulative])
        chart_portfolio = json.dumps([c["cumulative_return"] for c in cumulative])

        if spy_data and spy_data.get("spy_series"):
            spy_series = spy_data["spy_series"]
            spy_chart_labels = json.dumps([s["date"] for s in spy_series])
            spy_chart_data = json.dumps([s["cumulative_return"] for s in spy_series])
            spy_dataset = f"""{{
              label: 'SPY Benchmark',
              data: {spy_chart_data},
              borderColor: 'rgba(139,148,158,0.7)',
              backgroundColor: 'transparent',
              borderWidth: 1.5,
              borderDash: [4, 4],
              pointRadius: 0,
              tension: 0.3,
            }}"""
        else:
            spy_chart_labels = "[]"
            spy_dataset = ""

        datasets = f"""{{
              label: 'Aeternus Portfolio',
              data: {chart_portfolio},
              borderColor: '#58a6ff',
              backgroundColor: 'rgba(88,166,255,0.08)',
              borderWidth: 2,
              pointRadius: 3,
              tension: 0.3,
              fill: true,
            }}"""
        if spy_dataset:
            datasets = datasets + ",\n" + spy_dataset

        chart_section = f"""
    <h2>Cumulative Return</h2>
    <div style="background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:24px;margin-bottom:32px;">
      <canvas id="returnChart" height="80"></canvas>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script>
    (function() {{
      const labels = {chart_labels};
      const ctx = document.getElementById('returnChart').getContext('2d');
      new Chart(ctx, {{
        type: 'line',
        data: {{
          labels: labels,
          datasets: [
            {datasets}
          ]
        }},
        options: {{
          responsive: true,
          interaction: {{ mode: 'index', intersect: false }},
          plugins: {{
            legend: {{ labels: {{ color: '#e6edf3', font: {{ size: 12 }} }} }},
            tooltip: {{
              callbacks: {{
                label: ctx => ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(2) + '%'
              }}
            }}
          }},
          scales: {{
            x: {{
              ticks: {{ color: '#8b949e', maxTicksLimit: 8 }},
              grid: {{ color: '#30363d' }}
            }},
            y: {{
              ticks: {{ color: '#8b949e', callback: v => v.toFixed(1) + '%' }},
              grid: {{ color: '#30363d' }}
            }}
          }}
        }}
      }});
    }})();
    </script>"""

        table_rows = _build_table_rows(entries)
        table_section = f"""
    <h2>All Ratings</h2>
    <table>
      <thead>
        <tr>
          <th>Ticker</th><th>Date</th><th>Rating</th><th>Score</th>
          <th>Entry Price</th><th>Exit Price</th><th>Return %</th>
          <th>Days Held</th><th>Status</th>
        </tr>
      </thead>
      <tbody>
        {table_rows}
      </tbody>
    </table>"""

        body_content = chart_section + table_section

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Aeternus Track Record</title>
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
    line-height: 1.7; max-width: 1100px; margin: 0 auto; padding: 40px 24px 80px;
  }}
  h1 {{
    font-size: 1.9em; margin: 0 0 8px; border-bottom: 1px solid var(--border);
    padding-bottom: 12px; color: var(--fg);
  }}
  h2 {{
    font-size: 1.4em; margin: 48px 0 16px; color: var(--accent);
    border-bottom: 1px solid var(--border); padding-bottom: 8px;
  }}
  p {{ margin: 0 0 16px; }}
  .subtitle {{ color: var(--muted); font-style: italic; margin-bottom: 32px; }}
  .stats-grid {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 12px; margin: 24px 0 40px;
  }}
  .stat-card {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 16px 20px;
  }}
  .stat-label {{ font-size: 0.8em; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px; }}
  .stat-value {{ font-size: 1.6em; font-weight: 700; color: var(--fg); }}
  table {{
    width: 100%; border-collapse: collapse; margin: 16px 0 24px; font-size: 0.91em;
  }}
  th {{
    text-align: left; padding: 10px 14px; background: var(--surface2);
    border: 1px solid var(--border); font-weight: 600; color: var(--accent);
  }}
  td {{
    padding: 10px 14px; border: 1px solid var(--border);
    background: var(--surface); vertical-align: middle;
  }}
  tr:hover td {{ background: var(--surface2); }}
  .empty-state {{
    text-align: center; padding: 80px 24px; color: var(--muted);
    font-size: 1.1em; background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; margin: 40px 0;
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
  @media (max-width: 600px) {{
    table {{ font-size: 0.78em; }}
    th, td {{ padding: 7px 8px; }}
  }}
</style>
</head>
<body>
<h1>Aeternus Track Record</h1>
<p class="subtitle">{date_range} &nbsp;·&nbsp; Generated {generated_at}</p>

<h2>Performance Summary</h2>
{stats_section}

{body_content}

<div class="disclaimer">
  Past performance is not indicative of future results. This dashboard is for internal
  tracking purposes only and does not constitute investment advice. All returns are
  unaudited and based on logged entry/exit prices.
</div>
</body>
</html>"""


def generate_dashboard(
    track_record_path: str = "eval_results/track_record.json",
    output_path: str = "docs/track_record.html",
    spy_benchmark: bool = True,
) -> str:
    """Generate a self-contained HTML dashboard from the track record.

    Returns the output file path.
    """
    tr_path = Path(track_record_path)
    if tr_path.exists():
        try:
            history = json.loads(tr_path.read_text(encoding="utf-8"))
            if not isinstance(history, list):
                history = []
        except (json.JSONDecodeError, OSError):
            history = []
    else:
        history = []

    stats = compute_track_record_stats(history)

    spy_data: Optional[Dict[str, Any]] = None
    if spy_benchmark and stats["date_start"]:
        spy_data = _get_spy_data(stats["date_start"], stats["date_end"])

    html = _render_html(stats, history, spy_data)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    return str(out)
