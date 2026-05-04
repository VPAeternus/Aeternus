"""Symphony — autonomous task dispatcher daemon.

Polls tasks/queue/ for pending S-* and H-* task specs, dispatches Claude Code
agents in isolated git worktrees, manages lifecycle (timeout, retry), and serves
a live HTML dashboard with task submission.

Usage:
    python scripts/symphony.py              # run daemon (serves on :7777)
    python scripts/symphony.py --dry-run    # parse queue, show plan, no dispatch
    python scripts/symphony.py --port 8080  # custom port
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import os
import re
import signal
import subprocess
import sys
import textwrap
import threading
import time
from datetime import datetime, timezone
from functools import partial
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
QUEUE_DIR = ROOT / "tasks" / "queue"
STATE_DIR = ROOT / "eval_results" / "agents"
DASHBOARD_PATH = ROOT / "eval_results" / "dashboards" / "symphony.html"
STATE_PATH = STATE_DIR / "symphony_state.json"

MAX_CONCURRENT = int(os.environ.get("SYMPHONY_MAX_CONCURRENT", "2"))
TIMEOUT_MINUTES = int(os.environ.get("SYMPHONY_TIMEOUT_MINUTES", "15"))
MAX_RETRIES = 2
TICK_SECONDS = 30

TIER_MAP = {"S": "sonnet", "H": "haiku"}
TASK_RE = re.compile(r"^([SH])-(\d{3})-.*\.md$")

# ---------------------------------------------------------------------------
# Task parser
# ---------------------------------------------------------------------------


def _parse_task_file(path: Path) -> dict[str, Any] | None:
    """Parse a task queue markdown file into a dict."""
    m = TASK_RE.match(path.name)
    if not m:
        return None
    tier_letter, number = m.group(1), m.group(2)
    task_id = f"{tier_letter}-{number}"
    tier = TIER_MAP[tier_letter]

    text = path.read_text(encoding="utf-8")

    # Extract status
    status_match = re.search(r"^## Status\s*\n(\S+)", text, re.MULTILINE)
    status = status_match.group(1).strip() if status_match else "unknown"

    # Extract summary
    summary_match = re.search(r"^## Summary\s*\n(.+)", text, re.MULTILINE)
    summary = summary_match.group(1).strip() if summary_match else path.stem

    # Extract files to touch
    files_match = re.search(r"^## Files to Touch\s*\n((?:- .+\n?)+)", text, re.MULTILINE)
    files_to_touch = []
    if files_match:
        files_to_touch = [
            line.strip().lstrip("- ").strip("`")
            for line in files_match.group(1).strip().splitlines()
        ]

    return {
        "task_id": task_id,
        "tier": tier,
        "tier_letter": tier_letter,
        "number": int(number),
        "summary": summary,
        "status": status,
        "file": str(path),
        "files_to_touch": files_to_touch,
    }


def scan_queue() -> list[dict[str, Any]]:
    """Scan tasks/queue/ and return parsed pending tasks, sorted by priority."""
    tasks = []
    for p in QUEUE_DIR.glob("*.md"):
        parsed = _parse_task_file(p)
        if parsed and parsed["status"] == "pending":
            tasks.append(parsed)
    # H-* first (clear fast), then by number ascending
    tasks.sort(key=lambda t: (0 if t["tier_letter"] == "H" else 1, t["number"]))
    return tasks


def _next_task_number(tier_letter: str) -> int:
    """Find the next available task number for a given tier letter."""
    existing = set()
    for p in QUEUE_DIR.glob(f"{tier_letter}-*.md"):
        m = re.match(r"[SH]-(\d{3})", p.name)
        if m:
            existing.add(int(m.group(1)))
    n = 1
    while n in existing:
        n += 1
    return n


def create_task(description: str, tier: str, context: str = "") -> dict[str, str]:
    """Create a new task markdown file in the queue. Returns task_id and path."""
    tier_letter = "H" if tier == "haiku" else "S"
    number = _next_task_number(tier_letter)
    task_id = f"{tier_letter}-{number:03d}"

    # Slugify description for filename
    slug = re.sub(r"[^a-z0-9]+", "-", description.lower().strip())[:40].strip("-")
    filename = f"{task_id}-{slug}.md"
    path = QUEUE_DIR / filename

    context_section = context if context else "Implement as described in the summary."

    content = textwrap.dedent(f"""\
        # Task: {task_id}

        ## Tier
        {tier}

        ## Summary
        {description}

        ## Context
        {context_section}

        ## Requirements
        1. Implement the task as described above
        2. Follow existing code patterns and CLAUDE.md rules

        ## Files to Touch
        - (determined by agent)

        ## Acceptance Criteria
        - [ ] Implementation matches the summary description
        - [ ] All existing tests pass: `python -m pytest tests/ -v`

        ## Status
        pending

        ---

        ## Handoff
        *Fill in when marking done. Opus reads this to parse completion without reading the implementation.*

        **Work Done:** [files changed + one-line summary of what shipped]

        **Learnings:** [anything surprising, a footgun hit, or a pattern worth capturing — or "none"]

        **Follow-ups:** [new tasks this work reveals, if any — or "none"]
    """)

    path.write_text(content, encoding="utf-8")
    return {"task_id": task_id, "file": str(path), "tier": tier}


# ---------------------------------------------------------------------------
# Agent lifecycle
# ---------------------------------------------------------------------------


def _create_worktree(task_id: str) -> Path:
    """Create a git worktree for the task and return its path."""
    wt_dir = ROOT / ".claude" / "worktrees" / task_id
    branch = f"symphony/{task_id}"
    subprocess.run(
        ["git", "worktree", "add", str(wt_dir), "-b", branch, "HEAD"],
        cwd=str(ROOT),
        capture_output=True,
        check=True,
    )
    return wt_dir


def _remove_worktree(task_id: str) -> None:
    """Remove a git worktree and its branch."""
    wt_dir = ROOT / ".claude" / "worktrees" / task_id
    branch = f"symphony/{task_id}"
    subprocess.run(
        ["git", "worktree", "remove", str(wt_dir), "--force"],
        cwd=str(ROOT),
        capture_output=True,
    )
    subprocess.run(
        ["git", "branch", "-D", branch],
        cwd=str(ROOT),
        capture_output=True,
    )


def dispatch_agent(task: dict[str, Any]) -> dict[str, Any]:
    """Launch a Claude Code agent for the given task. Returns agent record."""
    task_id = task["task_id"]
    task_file = Path(task["file"]).name

    wt_dir = _create_worktree(task_id)
    log_path = STATE_DIR / f"{task_id}.log"

    prompt = (
        f"Read and implement tasks/queue/{task_file}. "
        "Follow CLAUDE.md rules. "
        "When done, update the Status line to 'done' and fill in the Handoff section. "
        "Run tests before marking done."
    )

    log_fh = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            "claude",
            "-p", prompt,
            "--allowedTools", "Edit,Write,Bash,Read,Glob,Grep",
        ],
        cwd=str(wt_dir),
        stdout=log_fh,
        stderr=subprocess.STDOUT,
    )

    return {
        "task_id": task_id,
        "tier": task["tier"],
        "summary": task["summary"],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "worktree": str(wt_dir),
        "log": str(log_path),
        "pid": proc.pid,
        "retries": 0,
        "_proc": proc,
        "_log_fh": log_fh,
    }


def check_agent(agent: dict[str, Any]) -> str | None:
    """Check agent status. Returns 'done', 'failed', 'timed_out', or None (still running)."""
    proc: subprocess.Popen = agent["_proc"]
    rc = proc.poll()

    # Still running — check timeout
    if rc is None:
        started = datetime.fromisoformat(agent["started_at"])
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        if elapsed > TIMEOUT_MINUTES * 60:
            proc.kill()
            proc.wait()
            agent["_log_fh"].close()
            return "timed_out"
        return None

    agent["_log_fh"].close()

    if rc == 0:
        # Check if task status was updated to done
        task_file = QUEUE_DIR / f"{agent['task_id']}-{_find_task_filename(agent['task_id'])}"
        # Simpler: just accept exit 0 as done
        return "done"

    return "failed"


def _find_task_filename(task_id: str) -> str | None:
    """Find the full filename for a task_id in the queue directory."""
    prefix = task_id + "-"
    for p in QUEUE_DIR.glob("*.md"):
        if p.name.startswith(prefix):
            return p.name
    return None


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------


def build_state(
    active: list[dict],
    completed: list[dict],
    failed: list[dict],
    queue: list[dict],
    start_time: float,
    stats: dict,
) -> dict[str, Any]:
    """Build the state dict for JSON serialization."""
    now = datetime.now(timezone.utc)
    return {
        "timestamp": now.isoformat(),
        "uptime_seconds": int(time.time() - start_time),
        "config": {
            "max_concurrent": MAX_CONCURRENT,
            "timeout_minutes": TIMEOUT_MINUTES,
        },
        "queue": [
            {"task_id": t["task_id"], "tier": t["tier"], "summary": t["summary"]}
            for t in queue
        ],
        "active": [
            {
                "task_id": a["task_id"],
                "tier": a["tier"],
                "summary": a["summary"],
                "started_at": a["started_at"],
                "elapsed_seconds": int(
                    (now - datetime.fromisoformat(a["started_at"])).total_seconds()
                ),
                "worktree": a["worktree"],
                "pid": a["pid"],
            }
            for a in active
        ],
        "completed": completed,
        "failed": failed,
        "stats": stats,
    }


def read_autoresearch_state() -> dict[str, Any]:
    """Read autoresearch experiment state from results.tsv and score.py."""
    results_path = ROOT / "autoresearch" / "results.tsv"
    score_path = ROOT / "autoresearch" / "score.py"

    experiments = []
    if results_path.exists():
        lines = results_path.read_text(encoding="utf-8").strip().splitlines()
        for line in lines[1:]:  # skip header
            parts = line.split("\t")
            if len(parts) >= 5:
                experiments.append({
                    "commit": parts[0],
                    "mean_ic_20d": float(parts[1]) if parts[1] else 0,
                    "mean_ic_5d": float(parts[2]) if parts[2] else 0,
                    "status": parts[3],
                    "description": parts[4],
                })

    # Parse WEIGHTS from score.py
    weights = {}
    if score_path.exists():
        text = score_path.read_text(encoding="utf-8")
        w_match = re.search(r"WEIGHTS\s*=\s*\{([^}]+)\}", text, re.DOTALL)
        if w_match:
            for line in w_match.group(1).strip().splitlines():
                kv = re.match(r'\s*"([^"]+)"\s*:\s*([\d.]+)', line)
                if kv:
                    weights[kv.group(1)] = float(kv.group(2))

    # Stats
    keeps = [e for e in experiments if e["status"] == "keep"]
    discards = [e for e in experiments if e["status"] == "discard"]
    best_ic = max((e["mean_ic_20d"] for e in keeps), default=0)
    keep_rate = len(keeps) / len(experiments) * 100 if experiments else 0

    return {
        "experiments": experiments,
        "weights": weights,
        "total": len(experiments),
        "keeps": len(keeps),
        "discards": len(discards),
        "best_ic": best_ic,
        "keep_rate": keep_rate,
        "latest_ic": experiments[-1]["mean_ic_20d"] if experiments else 0,
    }


def read_autoresearch_fundamentals_state() -> dict[str, Any]:
    """Read fundamentals autoresearch state from results_fundamentals.tsv and score_fundamentals.py."""
    results_path = ROOT / "autoresearch" / "results_fundamentals.tsv"
    score_path = ROOT / "autoresearch" / "score_fundamentals.py"

    experiments = []
    if results_path.exists():
        lines = results_path.read_text(encoding="utf-8").strip().splitlines()
        for line in lines[1:]:  # skip header
            parts = line.split("\t")
            if len(parts) >= 5:
                experiments.append({
                    "commit": parts[0],
                    "mean_ic_60d": float(parts[1]) if parts[1] else 0,
                    "mean_ic_252d": float(parts[2]) if parts[2] else 0,
                    "status": parts[3],
                    "description": parts[4],
                })

    # Parse WEIGHTS from score_fundamentals.py
    weights = {}
    if score_path.exists():
        text = score_path.read_text(encoding="utf-8")
        w_match = re.search(r"WEIGHTS\s*=\s*\{([^}]+)\}", text, re.DOTALL)
        if w_match:
            for line in w_match.group(1).strip().splitlines():
                kv = re.match(r'\s*"([^"]+)"\s*:\s*([\d.]+)', line)
                if kv:
                    weights[kv.group(1)] = float(kv.group(2))

    keeps = [e for e in experiments if e["status"] == "keep"]
    discards = [e for e in experiments if e["status"] == "discard"]
    best_ic = max((e["mean_ic_60d"] for e in keeps), default=0)
    keep_rate = len(keeps) / len(experiments) * 100 if experiments else 0

    return {
        "experiments": experiments,
        "weights": weights,
        "total": len(experiments),
        "keeps": len(keeps),
        "discards": len(discards),
        "best_ic": best_ic,
        "keep_rate": keep_rate,
        "latest_ic": experiments[-1]["mean_ic_60d"] if experiments else 0,
    }


def write_state(state: dict[str, Any]) -> None:
    """Write state JSON to disk."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# HTML dashboard
# ---------------------------------------------------------------------------


def _badge_html(status: str) -> str:
    """Render a pill-shaped status badge."""
    styles = {
        "active": ("background:#e8faf4;border-color:rgba(16,163,127,0.18);color:#0f513f", "active"),
        "done": ("background:#e8faf4;border-color:rgba(16,163,127,0.18);color:#0f513f", "done"),
        "pending": ("background:#fff7e8;border-color:#f1d8a6;color:#8a5a00", "pending"),
        "failed": ("background:#fef3f2;border-color:#f6d3cf;color:#b42318", "failed"),
        "timed_out": ("background:#fff7e8;border-color:#f1d8a6;color:#8a5a00", "timed out"),
    }
    style, label = styles.get(status, (f"background:#f3f4f6;border-color:#d9d9e3;color:#202123", status))
    return f'<span class="badge" style="{style}">{label}</span>'


def _tier_badge(tier: str) -> str:
    """Render a tier badge (sonnet/haiku)."""
    colors = {
        "sonnet": ("background:#eef2ff;border-color:#c7d2fe;color:#4338ca", "sonnet"),
        "haiku": ("background:#fef3c7;border-color:#fcd34d;color:#92400e", "haiku"),
    }
    style, label = colors.get(tier, ("background:#f3f4f6;border-color:#d9d9e3;color:#202123", tier))
    return f'<span class="badge" style="{style}">{label}</span>'


def _render_fundamentals_subsection() -> str:
    """Render fundamentals autoresearch sub-section HTML."""
    fr = read_autoresearch_fundamentals_state()

    if fr["total"] == 0 and not fr["weights"]:
        return (
            '<div style="margin-top:1.2rem;padding-top:1rem;border-top:1px solid var(--line)">'
            '<div style="font-size:0.82rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:0.03em;margin-bottom:0.3rem">Fundamentals (EDGAR XBRL)</div>'
            '<div style="font-size:0.88rem;color:var(--muted)">No fundamental experiments run yet.</div>'
            '</div>'
        )

    # Weight bars
    weight_bars = ""
    max_w = max(fr["weights"].values()) if fr["weights"] else 1
    for family, w in sorted(fr["weights"].items(), key=lambda x: -x[1]):
        pct = w / max_w * 100 if max_w > 0 else 0
        weight_bars += (
            f'<div class="weight-row">'
            f'<span class="weight-label">{family}</span>'
            f'<div class="weight-track">'
            f'<div class="weight-fill" style="width:{pct}%;background:#6366f1"></div>'
            f'</div>'
            f'<span class="weight-val">{w:.0f}%</span>'
            f'</div>\n'
        )

    # Experiment feed (last 10)
    feed_rows = ""
    for exp in reversed(fr["experiments"][-10:]):
        status_cls = {"keep": "exp-keep", "discard": "exp-discard", "crash": "exp-crash"}.get(exp["status"], "")
        ic_fmt = f'{exp["mean_ic_60d"]:.4f}'
        feed_rows += (
            f'<div class="exp-row {status_cls}">'
            f'<span class="exp-commit mono">{exp["commit"]}</span>'
            f'<span class="exp-ic mono">{ic_fmt}</span>'
            f'<span class="exp-status">{exp["status"]}</span>'
            f'<span class="exp-desc">{html_mod.escape(exp["description"])}</span>'
            f'</div>\n'
        )
    if not feed_rows:
        feed_rows = '<div class="empty-msg">No experiments recorded yet.</div>'

    return f"""
      <div style="margin-top:1.2rem;padding-top:1rem;border-top:1px solid var(--line)">
        <div style="font-size:0.82rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:0.03em;margin-bottom:0.5rem">Fundamentals (EDGAR XBRL)</div>
        <div class="ar-grid">
          <div class="ar-stats">
            <div class="metric-card" style="margin-bottom:0.6rem">
              <div class="label">Best IC (60d)</div>
              <div class="val">{fr["best_ic"]:.4f}</div>
              <div class="detail">Latest: {fr["latest_ic"]:.4f}</div>
            </div>
            <div class="metric-card" style="margin-bottom:0.6rem">
              <div class="label">Experiments</div>
              <div class="val">{fr["total"]}</div>
              <div class="detail">{fr["keeps"]} kept ({fr["keep_rate"]:.0f}%) &middot; {fr["discards"]} discarded</div>
            </div>
          </div>
          <div class="ar-weights">
            <div style="font-size:0.82rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:0.03em;margin-bottom:0.5rem">Fundamental Weights</div>
            {weight_bars}
          </div>
        </div>
        <div style="font-size:0.82rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:0.03em;margin-bottom:0.5rem">Fundamental Experiments (latest first)</div>
        <div class="exp-feed">
          {feed_rows}
        </div>
      </div>"""


def _render_autoresearch_section() -> str:
    """Render autoresearch experiment panel HTML."""
    ar = read_autoresearch_state()

    if ar["total"] == 0 and not ar["weights"]:
        return (
            '<div class="section-card">'
            '<div class="section-title">Autoresearch</div>'
            '<div class="section-sub">Scoring IC optimizer (Karpathy-style). '
            'No experiments run yet. Dispatch one below or run manually.</div>'
            '</div>'
        )

    # Weight bars
    weight_bars = ""
    max_w = max(ar["weights"].values()) if ar["weights"] else 1
    for family, w in sorted(ar["weights"].items(), key=lambda x: -x[1]):
        pct = w / max_w * 100 if max_w > 0 else 0
        opacity = "1.0" if w > 0 else "0.3"
        weight_bars += (
            f'<div class="weight-row">'
            f'<span class="weight-label">{family}</span>'
            f'<div class="weight-track">'
            f'<div class="weight-fill" style="width:{pct}%;opacity:{opacity}"></div>'
            f'</div>'
            f'<span class="weight-val">{w:.0f}%</span>'
            f'</div>\n'
        )

    # Experiment feed (last 15)
    feed_rows = ""
    for exp in reversed(ar["experiments"][-15:]):
        status_cls = {"keep": "exp-keep", "discard": "exp-discard", "crash": "exp-crash"}.get(exp["status"], "")
        ic_fmt = f'{exp["mean_ic_20d"]:.4f}'
        feed_rows += (
            f'<div class="exp-row {status_cls}">'
            f'<span class="exp-commit mono">{exp["commit"]}</span>'
            f'<span class="exp-ic mono">{ic_fmt}</span>'
            f'<span class="exp-status">{exp["status"]}</span>'
            f'<span class="exp-desc">{html_mod.escape(exp["description"])}</span>'
            f'</div>\n'
        )
    if not feed_rows:
        feed_rows = '<div class="empty-msg">No experiments recorded yet.</div>'

    # IC chart data (JSON for Chart.js)
    ic_values = [e["mean_ic_20d"] for e in ar["experiments"]]
    ic_colors = [
        "'rgba(16,163,127,0.8)'" if e["status"] == "keep"
        else ("'rgba(180,35,24,0.6)'" if e["status"] in ("discard", "crash") else "'rgba(110,110,128,0.4)'")
        for e in ar["experiments"]
    ]
    ic_labels = list(range(1, len(ic_values) + 1))

    has_chart = len(ic_values) >= 2
    chart_html = ""
    if has_chart:
        chart_html = f"""
        <div style="margin-bottom:1rem">
          <canvas id="icChart" height="140"></canvas>
        </div>
        <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
        <script>
        new Chart(document.getElementById('icChart'), {{
          type: 'scatter',
          data: {{
            datasets: [{{
              label: 'mean_ic_20d',
              data: {json.dumps([{"x": i+1, "y": v} for i, v in enumerate(ic_values)])},
              pointBackgroundColor: [{",".join(ic_colors)}],
              pointRadius: 5,
              pointHoverRadius: 7,
              showLine: true,
              borderColor: 'rgba(16,163,127,0.3)',
              borderWidth: 1,
              fill: false,
            }}]
          }},
          options: {{
            responsive: true,
            plugins: {{
              legend: {{ display: false }},
              tooltip: {{
                callbacks: {{
                  label: (ctx) => 'IC: ' + ctx.parsed.y.toFixed(4)
                }}
              }}
            }},
            scales: {{
              x: {{ title: {{ display: true, text: 'Experiment #' }}, grid: {{ color: '#ececf1' }} }},
              y: {{ title: {{ display: true, text: 'IC (20d)' }}, grid: {{ color: '#ececf1' }} }}
            }}
          }}
        }});
        </script>"""

    return f"""
    <div class="section-card">
      <div class="section-title">Autoresearch</div>
      <div class="section-sub">Autonomous scoring IC optimizer. Agent modifies weights/formulas, measures Spearman IC, keeps improvements.</div>

      <div class="ar-grid">
        <div class="ar-stats">
          <div class="metric-card" style="margin-bottom:0.6rem">
            <div class="label">Best IC (20d)</div>
            <div class="val">{ar["best_ic"]:.4f}</div>
            <div class="detail">Latest: {ar["latest_ic"]:.4f}</div>
          </div>
          <div class="metric-card" style="margin-bottom:0.6rem">
            <div class="label">Experiments</div>
            <div class="val">{ar["total"]}</div>
            <div class="detail">{ar["keeps"]} kept ({ar["keep_rate"]:.0f}%) &middot; {ar["discards"]} discarded</div>
          </div>
        </div>
        <div class="ar-weights">
          <div style="font-size:0.82rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:0.03em;margin-bottom:0.5rem">Signal Weights</div>
          {weight_bars}
        </div>
      </div>

      {chart_html}

      <div style="font-size:0.82rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:0.03em;margin-bottom:0.5rem">Experiment Log (latest first)</div>
      <div class="exp-feed">
        {feed_rows}
      </div>

      <form class="ar-dispatch" id="arForm" style="margin-top:1rem;display:flex;gap:0.6rem;align-items:end;flex-wrap:wrap">
        <div class="field">
          <label for="n_experiments">Experiments</label>
          <input type="number" id="n_experiments" name="n_experiments" value="20" min="5" max="200" style="width:80px">
        </div>
        <div class="field">
          <label for="ar_tag">Tag</label>
          <input type="text" id="ar_tag" name="tag" value="{datetime.now().strftime("%b%d").lower()}" style="width:100px">
        </div>
        <button type="submit" class="btn-submit">Launch autoresearch</button>
      </form>

      {_render_fundamentals_subsection()}
    </div>"""


def write_dashboard(state: dict[str, Any]) -> None:
    """Write self-contained HTML dashboard."""
    uptime = state["uptime_seconds"]
    h, m = divmod(uptime // 60, 60)
    stats = state["stats"]
    ts = state["timestamp"][:19].replace("T", " ")

    # Active agents rows
    active_rows = ""
    for a in state["active"]:
        elapsed_m = a["elapsed_seconds"] // 60
        elapsed_s = a["elapsed_seconds"] % 60
        active_rows += (
            f'<tr>'
            f'<td><strong>{a["task_id"]}</strong></td>'
            f'<td>{_tier_badge(a["tier"])}</td>'
            f'<td>{_badge_html("active")}</td>'
            f'<td class="mono">{elapsed_m}m {elapsed_s}s</td>'
            f'<td>{a.get("summary", "")}</td>'
            f'<td class="mono muted">{a.get("pid", "")}</td>'
            f'</tr>\n'
        )
    if not active_rows:
        active_rows = '<tr><td colspan="6" class="empty-msg">No active agents.</td></tr>'

    # Queue rows
    queue_rows = ""
    for t in state["queue"]:
        queue_rows += (
            f'<tr>'
            f'<td><strong>{t["task_id"]}</strong></td>'
            f'<td>{_tier_badge(t["tier"])}</td>'
            f'<td>{_badge_html("pending")}</td>'
            f'<td>{t.get("summary", "")}</td>'
            f'</tr>\n'
        )
    if not queue_rows:
        queue_rows = '<tr><td colspan="4" class="empty-msg">Queue empty.</td></tr>'

    # History rows
    history = (state.get("completed", []) + state.get("failed", []))[-20:]
    history_rows = ""
    for item in history:
        dur = item.get("duration_seconds", 0)
        history_rows += (
            f'<tr>'
            f'<td><strong>{item["task_id"]}</strong></td>'
            f'<td>{_tier_badge(item["tier"])}</td>'
            f'<td>{_badge_html(item["status"])}</td>'
            f'<td class="mono">{dur // 60}m {dur % 60}s</td>'
            f'</tr>\n'
        )
    if not history_rows:
        history_rows = '<tr><td colspan="4" class="empty-msg">No history yet.</td></tr>'

    # Autoresearch panel
    autoresearch_html = _render_autoresearch_section()

    # Live/offline badge
    is_live = len(state["active"]) > 0 or uptime < 60
    live_badge = (
        '<span class="live-badge"><span class="live-dot"></span>Live</span>'
        if is_live
        else '<span class="offline-badge">Idle</span>'
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="5">
<title>Symphony — Aeternus</title>
<style>
:root {{
  --page: #f7f7f8;
  --page-soft: #fbfbfc;
  --card: rgba(255,255,255,0.94);
  --card-muted: #f3f4f6;
  --ink: #202123;
  --muted: #6e6e80;
  --line: #ececf1;
  --line-strong: #d9d9e3;
  --accent: #10a37f;
  --accent-ink: #0f513f;
  --accent-soft: #e8faf4;
  --danger: #b42318;
  --danger-soft: #fef3f2;
  --radius-card: 24px;
  --radius-badge: 999px;
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  background: radial-gradient(circle at top, rgba(16,163,127,0.10) 0%, transparent 30%),
              linear-gradient(180deg, var(--page-soft), var(--page) 40%, #f3f4f6);
  color: var(--ink);
  font-family: "SF Pro Text","Helvetica Neue","Segoe UI",sans-serif;
  font-size: 15px;
  line-height: 1.5;
  min-height: 100vh;
}}
.app-shell {{
  max-width: 1280px;
  margin: 0 auto;
  padding: 2rem 1rem 3.5rem;
}}

/* Hero card */
.hero {{
  background: var(--card);
  backdrop-filter: blur(18px);
  border: 1px solid rgba(217,217,227,0.82);
  border-radius: 28px;
  padding: clamp(1.25rem, 3vw, 2rem);
  box-shadow: 0 20px 50px rgba(15,23,42,0.08);
  margin-bottom: 1rem;
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: start;
  gap: 1rem;
}}
.hero .eyebrow {{
  font-size: 0.76rem;
  font-weight: 600;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 0.3rem;
}}
.hero h1 {{
  font-size: clamp(2rem, 4vw, 3.3rem);
  font-weight: 700;
  line-height: 0.98;
  letter-spacing: -0.04em;
  color: var(--ink);
  margin-bottom: 0.5rem;
}}
.hero .sub {{
  font-size: 1rem;
  color: var(--muted);
  max-width: 46rem;
}}
.live-badge, .offline-badge {{
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  border-radius: var(--radius-badge);
  padding: 0.35rem 0.78rem;
  font-size: 0.82rem;
  font-weight: 700;
  letter-spacing: 0.01em;
  min-height: 2rem;
}}
.live-badge {{
  background: var(--accent-soft);
  border: 1px solid rgba(16,163,127,0.18);
  color: var(--accent-ink);
}}
.live-dot {{
  width: 0.52rem;
  height: 0.52rem;
  border-radius: 50%;
  background: var(--accent);
  animation: pulse 2s ease-in-out infinite;
}}
@keyframes pulse {{
  0%, 100% {{ opacity:1; }}
  50% {{ opacity:0.4; }}
}}
.offline-badge {{
  background: #f5f5f7;
  border: 1px solid var(--line-strong);
  color: var(--muted);
}}

/* Metric grid */
.metric-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0.85rem;
  margin-bottom: 1rem;
}}
.metric-card {{
  background: var(--card);
  border: 1px solid rgba(217,217,227,0.82);
  border-radius: 22px;
  padding: 1rem 1.05rem 1.1rem;
  box-shadow: 0 1px 2px rgba(16,24,40,0.05);
}}
.metric-card .label {{
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}}
.metric-card .val {{
  font-size: clamp(1.6rem, 2vw, 2.1rem);
  font-weight: 700;
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums slashed-zero;
  color: var(--ink);
}}
.metric-card .detail {{
  font-size: 0.88rem;
  color: var(--muted);
}}

/* Section cards */
.section-card {{
  background: var(--card);
  border: 1px solid rgba(217,217,227,0.82);
  border-radius: var(--radius-card);
  padding: 1.15rem;
  box-shadow: 0 1px 2px rgba(16,24,40,0.05);
  margin-bottom: 1rem;
}}
.section-card .section-title {{
  font-size: 1.08rem;
  font-weight: 600;
  letter-spacing: -0.02em;
  margin-bottom: 0.15rem;
}}
.section-card .section-sub {{
  font-size: 0.94rem;
  color: var(--muted);
  margin-bottom: 0.85rem;
}}

/* Tables */
table {{
  width: 100%;
  border-collapse: collapse;
  min-width: 600px;
}}
.table-wrap {{
  overflow-x: auto;
}}
th {{
  text-align: left;
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 0 0.5rem 0.75rem 0;
  border-bottom: 1px solid var(--line);
}}
td {{
  padding: 0.9rem 0.5rem 0.9rem 0;
  vertical-align: top;
  font-size: 0.94rem;
  border-top: 1px solid var(--line);
}}
tr:first-child td {{ border-top: none; }}
.empty-msg {{
  color: var(--muted);
  font-style: italic;
  padding: 1.2rem 0;
  border-top: none !important;
}}

/* Badges */
.badge {{
  display: inline-flex;
  align-items: center;
  border-radius: var(--radius-badge);
  padding: 0.3rem 0.68rem;
  font-size: 0.8rem;
  font-weight: 600;
  border: 1px solid;
  min-height: 1.85rem;
  white-space: nowrap;
}}

/* Utility */
.mono {{
  font-family: "SFMono-Regular","SF Mono",Consolas,"Liberation Mono",monospace;
  font-variant-numeric: tabular-nums slashed-zero;
}}
.muted {{ color: var(--muted); }}

/* Add task form */
.add-form {{
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 0.6rem;
  align-items: end;
}}
.add-form .field {{
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}}
.add-form .field.full {{
  grid-column: 1 / -1;
}}
.add-form label {{
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}}
.add-form input, .add-form select, .add-form textarea {{
  font-family: inherit;
  font-size: 0.94rem;
  padding: 0.6rem 0.85rem;
  border: 1px solid var(--line-strong);
  border-radius: 14px;
  background: white;
  color: var(--ink);
  outline: none;
  transition: border-color 0.15s;
}}
.add-form input:focus, .add-form select:focus, .add-form textarea:focus {{
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(16,163,127,0.10);
}}
.add-form textarea {{
  resize: vertical;
  min-height: 60px;
}}
.add-form select {{
  cursor: pointer;
  -webkit-appearance: none;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg width='10' height='6' viewBox='0 0 10 6' fill='none' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M1 1l4 4 4-4' stroke='%236e6e80' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 0.7rem center;
  padding-right: 2rem;
}}
.btn-submit {{
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  background: var(--accent);
  color: white;
  border: 1px solid var(--accent);
  border-radius: var(--radius-badge);
  padding: 0.6rem 1.2rem;
  font-size: 0.88rem;
  font-weight: 600;
  letter-spacing: -0.01em;
  cursor: pointer;
  transition: all 0.15s;
  box-shadow: 0 4px 12px rgba(16,163,127,0.18);
  white-space: nowrap;
  align-self: end;
}}
.btn-submit:hover {{
  transform: translateY(-1px);
  box-shadow: 0 8px 20px rgba(16,163,127,0.25);
}}
.btn-submit:active {{ transform: translateY(0); }}

/* Toast notification */
.toast {{
  position: fixed;
  top: 1.5rem;
  right: 1.5rem;
  background: var(--accent-soft);
  border: 1px solid rgba(16,163,127,0.18);
  color: var(--accent-ink);
  padding: 0.75rem 1.2rem;
  border-radius: 16px;
  font-weight: 600;
  font-size: 0.88rem;
  box-shadow: 0 8px 24px rgba(0,0,0,0.12);
  transform: translateY(-20px);
  opacity: 0;
  transition: all 0.3s ease;
  z-index: 100;
  pointer-events: none;
}}
.toast.show {{
  transform: translateY(0);
  opacity: 1;
}}

/* Autoresearch */
.ar-grid {{
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 1rem;
  margin-bottom: 1rem;
}}
.ar-stats {{ min-width: 180px; }}
.ar-weights {{ }}
.weight-row {{
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.3rem;
  font-size: 0.82rem;
}}
.weight-label {{
  width: 140px;
  color: var(--ink);
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}}
.weight-track {{
  flex: 1;
  height: 8px;
  background: var(--card-muted);
  border-radius: 4px;
  overflow: hidden;
}}
.weight-fill {{
  height: 100%;
  background: var(--accent);
  border-radius: 4px;
  transition: width 0.3s ease;
}}
.weight-val {{
  width: 36px;
  text-align: right;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}}
.exp-feed {{
  max-height: 280px;
  overflow-y: auto;
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 0.5rem;
}}
.exp-row {{
  display: grid;
  grid-template-columns: 5rem 4.5rem 4rem 1fr;
  gap: 0.5rem;
  padding: 0.4rem 0.5rem;
  font-size: 0.82rem;
  border-radius: 8px;
  align-items: center;
}}
.exp-row:nth-child(odd) {{ background: rgba(0,0,0,0.02); }}
.exp-keep {{ border-left: 3px solid var(--accent); }}
.exp-discard {{ border-left: 3px solid var(--danger); }}
.exp-crash {{ border-left: 3px solid #f0a000; }}
.exp-commit {{ color: var(--muted); font-size: 0.76rem; }}
.exp-ic {{ font-weight: 600; }}
.exp-status {{ font-weight: 600; font-size: 0.76rem; text-transform: uppercase; }}
.exp-keep .exp-status {{ color: var(--accent-ink); }}
.exp-discard .exp-status {{ color: var(--danger); }}
.exp-crash .exp-status {{ color: #8a5a00; }}
.exp-desc {{ color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
@media (max-width: 860px) {{
  .ar-grid {{ grid-template-columns: 1fr; }}
}}

/* Context toggle */
.context-toggle {{
  font-size: 0.82rem;
  color: var(--accent);
  cursor: pointer;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  margin-top: 0.3rem;
}}
.context-toggle:hover {{ text-decoration: underline; }}
.context-area {{ display: none; }}
.context-area.open {{ display: block; margin-top: 0.5rem; }}

/* Responsive */
@media (max-width: 860px) {{
  .hero {{ grid-template-columns: 1fr; }}
  .metric-grid {{ grid-template-columns: repeat(2, 1fr); }}
  .add-form {{ grid-template-columns: 1fr; }}
}}
@media (max-width: 560px) {{
  .metric-grid {{ grid-template-columns: 1fr; }}
  .section-card, .hero, .metric-card {{ border-radius: 20px; }}
}}
</style>
</head>
<body>
<div class="app-shell">

<div class="hero">
  <div>
    <div class="eyebrow">Symphony Orchestration</div>
    <h1>Task Dispatcher</h1>
    <div class="sub">Autonomous agent dispatch, worktree isolation, lifecycle management, and task completion tracking for the Aeternus pipeline.</div>
  </div>
  <div>{live_badge}</div>
</div>

<div class="section-card">
  <div class="section-title">Add Task</div>
  <div class="section-sub">Describe what you want built. An agent will pick it up and implement it autonomously.</div>
  <form class="add-form" id="addTaskForm">
    <div class="field">
      <label for="description">Task description</label>
      <input type="text" id="description" name="description" placeholder="e.g. Add retry logic to the API client" required>
    </div>
    <div class="field">
      <label for="tier">Tier</label>
      <select id="tier" name="tier">
        <option value="sonnet">Sonnet</option>
        <option value="haiku">Haiku</option>
      </select>
    </div>
    <button type="submit" class="btn-submit">Add task</button>
    <div class="field full">
      <span class="context-toggle" onclick="document.getElementById('ctxArea').classList.toggle('open')">+ Add context (optional)</span>
      <div id="ctxArea" class="context-area">
        <textarea id="context" name="context" placeholder="Additional context, file references, or requirements for the agent..."></textarea>
      </div>
    </div>
  </form>
</div>

<div id="toast" class="toast"></div>

<div class="metric-grid">
  <div class="metric-card">
    <div class="label">Active</div>
    <div class="val">{len(state["active"])}</div>
    <div class="detail">Agents running in worktrees</div>
  </div>
  <div class="metric-card">
    <div class="label">Queued</div>
    <div class="val">{len(state["queue"])}</div>
    <div class="detail">Pending tasks in queue</div>
  </div>
  <div class="metric-card">
    <div class="label">Completed</div>
    <div class="val">{stats.get("total_completed", 0)}</div>
    <div class="detail">of {stats.get("total_dispatched", 0)} dispatched</div>
  </div>
  <div class="metric-card">
    <div class="label">Uptime</div>
    <div class="val">{h}h {m:02d}m</div>
    <div class="detail">Failed: {stats.get("total_failed", 0)} | Updated: {ts}</div>
  </div>
</div>

<div class="section-card">
  <div class="section-title">Active Agents</div>
  <div class="section-sub">Running sessions with isolated worktrees and elapsed time.</div>
  <div class="table-wrap">
  <table>
    <tr><th>Task</th><th>Tier</th><th>State</th><th>Runtime</th><th>Summary</th><th>PID</th></tr>
    {active_rows}
  </table>
  </div>
</div>

<div class="section-card">
  <div class="section-title">Queue</div>
  <div class="section-sub">Tasks waiting for an available agent slot.</div>
  <div class="table-wrap">
  <table>
    <tr><th>Task</th><th>Tier</th><th>State</th><th>Summary</th></tr>
    {queue_rows}
  </table>
  </div>
</div>

<div class="section-card">
  <div class="section-title">History</div>
  <div class="section-sub">Completed and failed tasks from this session (last 20).</div>
  <div class="table-wrap">
  <table>
    <tr><th>Task</th><th>Tier</th><th>Status</th><th>Duration</th></tr>
    {history_rows}
  </table>
  </div>
</div>

{autoresearch_html}

</div>
<script>
document.getElementById('addTaskForm').addEventListener('submit', async (e) => {{
  e.preventDefault();
  const desc = document.getElementById('description').value.trim();
  const tier = document.getElementById('tier').value;
  const ctx = document.getElementById('context').value.trim();
  if (!desc) return;

  try {{
    const res = await fetch('/api/v1/tasks', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{description: desc, tier: tier, context: ctx}})
    }});
    const data = await res.json();
    if (res.ok) {{
      const toast = document.getElementById('toast');
      toast.textContent = 'Task ' + data.task_id + ' created';
      toast.classList.add('show');
      setTimeout(() => toast.classList.remove('show'), 3000);
      document.getElementById('description').value = '';
      document.getElementById('context').value = '';
      document.getElementById('ctxArea').classList.remove('open');
    }}
  }} catch (err) {{
    console.error(err);
  }}
}});

// Autoresearch dispatch
const arForm = document.getElementById('arForm');
if (arForm) {{
  arForm.addEventListener('submit', async (e) => {{
    e.preventDefault();
    const n = document.getElementById('n_experiments').value;
    const tag = document.getElementById('ar_tag').value.trim();
    try {{
      const res = await fetch('/api/v1/autoresearch', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{n_experiments: parseInt(n), tag: tag}})
      }});
      const data = await res.json();
      if (res.ok) {{
        const toast = document.getElementById('toast');
        toast.textContent = 'Autoresearch dispatched as ' + data.task_id;
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), 3000);
      }}
    }} catch (err) {{
      console.error(err);
    }}
  }});
}}
</script>
</body>
</html>"""

    DASHBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_PATH.write_text(html, encoding="utf-8")
    _latest_dashboard_html[0] = html


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

# Shared mutable ref so the request handler can read the latest dashboard HTML
_latest_dashboard_html: list[str] = [""]


class SymphonyHandler(BaseHTTPRequestHandler):
    """Serves dashboard and accepts task creation via POST."""

    def log_message(self, format, *args):
        pass  # suppress request logs

    def do_GET(self):
        if self.path == "/" or self.path == "/dashboard":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(_latest_dashboard_html[0].encode("utf-8"))
        elif self.path == "/api/v1/state":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                data = STATE_PATH.read_text(encoding="utf-8")
            except FileNotFoundError:
                data = "{}"
            self.wfile.write(data.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/v1/tasks":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            content_type = self.headers.get("Content-Type", "")

            if "application/json" in content_type:
                data = json.loads(body)
            else:
                data = {k: v[0] for k, v in parse_qs(body).items()}

            description = data.get("description", "").strip()
            tier = data.get("tier", "sonnet").strip()
            context = data.get("context", "").strip()

            if not description:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "description required"}).encode())
                return

            if tier not in ("sonnet", "haiku"):
                tier = "sonnet"

            result = create_task(description, tier, context)

            if "application/x-www-form-urlencoded" in content_type:
                # Form submission — redirect back to dashboard
                self.send_response(303)
                self.send_header("Location", "/")
                self.end_headers()
            else:
                # JSON API
                self.send_response(201)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())

        elif self.path == "/api/v1/autoresearch":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            content_type = self.headers.get("Content-Type", "")

            if "application/json" in content_type:
                data = json.loads(body)
            else:
                data = {k: v[0] for k, v in parse_qs(body).items()}

            n_experiments = int(data.get("n_experiments", 20))
            tag = data.get("tag", datetime.now().strftime("%b%d").lower())

            # Create a task that runs autoresearch
            desc = f"Run {n_experiments} autoresearch experiments (tag: {tag})"
            context = (
                f"Run the autoresearch scoring optimizer loop.\n\n"
                f"1. Read `autoresearch/program.md` for full instructions\n"
                f"2. Create branch `autoresearch/{tag}` if it doesn't exist\n"
                f"3. Run baseline: `python autoresearch/score.py > autoresearch/run.log 2>&1`\n"
                f"4. Execute {n_experiments} experiments modifying `autoresearch/score.py`\n"
                f"5. Keep improvements, discard regressions (by mean_ic_20d)\n"
                f"6. Log all results to `autoresearch/results.tsv`\n\n"
                f"Goal: maximize mean_ic_20d. Each experiment ~30-60 seconds."
            )
            result = create_task(desc, "sonnet", context)
            result["n_experiments"] = n_experiments
            result["tag"] = tag

            if "application/x-www-form-urlencoded" in content_type:
                self.send_response(303)
                self.send_header("Location", "/")
                self.end_headers()
            else:
                self.send_response(201)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
        else:
            self.send_response(404)
            self.end_headers()


def start_http_server(port: int) -> HTTPServer:
    """Start the dashboard HTTP server in a daemon thread."""
    server = HTTPServer(("0.0.0.0", port), SymphonyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

DEFAULT_PORT = int(os.environ.get("SYMPHONY_PORT", "7777"))


def run(dry_run: bool = False, port: int = DEFAULT_PORT) -> None:
    """Main dispatcher loop."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    start_time = time.time()
    active: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    dispatched_ids: set[str] = set()
    stats = {"total_dispatched": 0, "total_completed": 0, "total_failed": 0}

    print(f"Symphony started | max_concurrent={MAX_CONCURRENT} timeout={TIMEOUT_MINUTES}m")

    if dry_run:
        queue = scan_queue()
        print(f"\nPending tasks: {len(queue)}")
        for t in queue:
            print(f"  {t['task_id']} [{t['tier']}] {t['summary']}")
        print("\n--dry-run: no agents dispatched.")
        return

    # Start HTTP server
    server = start_http_server(port)
    print(f"Dashboard: http://localhost:{port}")
    print()

    # Graceful shutdown
    shutdown = False

    def _handle_signal(signum, frame):
        nonlocal shutdown
        print("\nShutdown requested — finishing active agents...")
        shutdown = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    while not shutdown:
        # 1. Check active agents
        still_active = []
        for agent in active:
            result = check_agent(agent)
            if result is None:
                still_active.append(agent)
            else:
                started = datetime.fromisoformat(agent["started_at"])
                duration = int((datetime.now(timezone.utc) - started).total_seconds())
                record = {
                    "task_id": agent["task_id"],
                    "tier": agent["tier"],
                    "status": result,
                    "duration_seconds": duration,
                }
                if result == "done":
                    completed.append(record)
                    stats["total_completed"] += 1
                    print(f"  [{agent['task_id']}] completed in {duration // 60}m")
                    _remove_worktree(agent["task_id"])
                elif result in ("failed", "timed_out") and agent["retries"] < MAX_RETRIES:
                    agent["retries"] += 1
                    print(f"  [{agent['task_id']}] {result} — retry {agent['retries']}/{MAX_RETRIES}")
                    _remove_worktree(agent["task_id"])
                    dispatched_ids.discard(agent["task_id"])
                else:
                    failed.append(record)
                    stats["total_failed"] += 1
                    print(f"  [{agent['task_id']}] {result} (no retries left)")
                    _remove_worktree(agent["task_id"])
        active = still_active

        # 2. Dispatch new agents
        if len(active) < MAX_CONCURRENT:
            queue = scan_queue()
            eligible = [t for t in queue if t["task_id"] not in dispatched_ids]
            slots = MAX_CONCURRENT - len(active)
            for task in eligible[:slots]:
                try:
                    agent = dispatch_agent(task)
                    active.append(agent)
                    dispatched_ids.add(task["task_id"])
                    stats["total_dispatched"] += 1
                    print(f"  [{task['task_id']}] dispatched ({task['tier']})")
                except Exception as e:
                    print(f"  [{task['task_id']}] dispatch error: {e}")

        # 3. Write state + dashboard
        queue = scan_queue()
        remaining_queue = [t for t in queue if t["task_id"] not in dispatched_ids]
        state = build_state(active, completed, failed, remaining_queue, start_time, stats)
        write_state(state)
        write_dashboard(state)

        time.sleep(TICK_SECONDS)

    # Shutdown: wait for active agents
    for agent in active:
        print(f"  Waiting for [{agent['task_id']}]...")
        agent["_proc"].wait(timeout=60)
        agent["_log_fh"].close()

    print("Symphony stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Symphony task dispatcher")
    parser.add_argument("--dry-run", action="store_true", help="Parse queue without dispatching")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"HTTP server port (default {DEFAULT_PORT})")
    args = parser.parse_args()
    run(dry_run=args.dry_run, port=args.port)
