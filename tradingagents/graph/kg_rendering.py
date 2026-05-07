"""Obsidian/Markdown rendering helpers for AeternusKnowledgeGraph."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from tradingagents.graph.kg_templates import sanitize_filename

def to_obsidian(graph, vault_path) -> int:
    """
    Export full graph as an Obsidian-compatible Markdown vault.
    Returns count of files written.
    """
    vault = Path(vault_path)
    (vault / "companies").mkdir(parents=True, exist_ok=True)
    (vault / "themes").mkdir(parents=True, exist_ok=True)
    (vault / "sectors").mkdir(parents=True, exist_ok=True)
    (vault / "forces").mkdir(parents=True, exist_ok=True)

    # Ensure centrality is up-to-date
    graph.get_centrality_scores()

    files_written = 0

    # Group nodes by type
    company_nodes = [n for n in graph._nodes.values() if n["node_type"] == "company"]
    theme_nodes = [n for n in graph._nodes.values() if n["node_type"] == "theme"]
    sector_nodes = [n for n in graph._nodes.values() if n["node_type"] == "sector"]

    # --- Company files ---
    for node in company_nodes:
        content = render_company_md(graph, node)
        filename = sanitize_filename(node["id"]) + ".md"
        (vault / "companies" / filename).write_text(content, encoding="utf-8")
        files_written += 1

    # --- Theme files ---
    for node in theme_nodes:
        content = render_theme_md(graph, node)
        filename = sanitize_filename(node["id"]) + ".md"
        (vault / "themes" / filename).write_text(content, encoding="utf-8")
        files_written += 1

    # --- Sector files ---
    for node in sector_nodes:
        content = render_sector_md(graph, node, company_nodes)
        filename = sanitize_filename(node["id"]) + ".md"
        (vault / "sectors" / filename).write_text(content, encoding="utf-8")
        files_written += 1

    # --- Structural forces ---
    files_written += render_forces_to_vault(graph, vault)

    # --- Graph summary ---
    summary = render_summary(graph, company_nodes, theme_nodes, sector_nodes)
    (vault / "_graph_summary.md").write_text(summary, encoding="utf-8")
    files_written += 1

    return files_written

def render_forces_to_vault(graph, vault: Path) -> int:
    """Export structural forces as Obsidian-linked Markdown files."""
    try:
        from tradingagents.graph.structural_forces import STRUCTURAL_FORCES
    except ImportError:
        return 0

    files = 0
    for force in STRUCTURAL_FORCES:
        lines = [
            "---",
            f"force_id: {force.force_id}",
            f"conviction: {force.effective_conviction}",
            f"acceleration: {force.effective_acceleration}",
            f"horizon_months: {force.horizon_months}",
            "---",
            "",
            f"# {force.display_name}",
            "",
            force.description,
            "",
            "## Why Durable",
            force.why_durable,
            "",
            "## Causal Chain",
        ]
        for step in force.causal_chain:
            ticker_links = ", ".join(f"[[{t}]]" for t in step.derived_tickers)
            lines += [
                f"### Step {step.step}: {step.description}",
                f"- **Necessity:** {step.necessity_score:.0%}",
                f"- **Sector:** [[{step.sector_id}]]",
                f"- **Tickers:** {ticker_links}",
                f"- {step.reasoning}",
                "",
            ]
        lines += ["## Must Be True"]
        for cond in force.must_be_true:
            lines.append(f"- [ ] {cond}")
        lines += ["", "## Anti-Fragile To"]
        for item in force.anti_fragile_to:
            lines.append(f"- {item}")
        content = "\n".join(lines) + "\n"
        fname = sanitize_filename(force.force_id) + ".md"
        (vault / "forces" / fname).write_text(content, encoding="utf-8")
        files += 1

    # Forces index
    index_lines = ["# Structural Forces", ""]
    for f in STRUCTURAL_FORCES:
        index_lines.append(
            f"- [[{f.force_id}]] — {f.display_name} "
            f"(conviction {f.effective_conviction:.0%}, {f.effective_acceleration})"
        )
    (vault / "forces" / "_index.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    files += 1
    return files

def render_company_md(graph, node: dict) -> str:
    nid = node["id"]
    score_val = node["aeternus_score"]
    score_str = str(score_val) if score_val is not None else "null"

    tier = node.get("emergence_tier") or "DARK"
    e_score = node.get("emergence_score") or 0.0
    lines = [
        "---",
        f"ticker: {nid}",
        f"sector: {node['sector'] or 'null'}",
        f"signal_strength: {node['signal_strength']}",
        f"centrality: {node['centrality']}",
        f"aeternus_score: {score_str}",
        f"emergence_tier: {tier}",
        f"emergence_score: {e_score}",
        f"times_surfaced: {node['times_surfaced']}",
        f"last_surfaced: {node['last_surfaced'] or 'null'}",
        f"thesis_confirmed: {node['thesis_track_record']['confirmed']}",
        f"thesis_invalidated: {node['thesis_track_record']['invalidated']}",
        "---",
        "",
        f"# {node['display_name']} (${nid})",
        "",
        f"**Sector:** [[{node['sector']}]]" if node.get("sector") else "",
        f"**Emergence:** {tier} (score: {e_score:.4f})" if tier != "DARK" or e_score > 0 else f"**Emergence:** {tier}",
        "",
    ]

    # Outgoing edges grouped by relationship
    outgoing = graph._outgoing_edges(nid)
    rel_map: Dict[str, List[str]] = defaultdict(list)
    for e in outgoing:
        rel_map[e["relationship"]].append(e["target"])

    lines.append("## Connected Companies")
    if "supply_chain" in rel_map:
        lines.append("### Supplies to")
        for t in rel_map["supply_chain"]:
            lines.append(f"- [[{t}]]")
        lines.append("")

    if "sector_peer" in rel_map:
        lines.append("### Sector Peers")
        for t in rel_map["sector_peer"]:
            lines.append(f"- [[{t}]]")
        lines.append("")

    if "catalyst_beneficiary" in rel_map:
        lines.append("### Catalyst Beneficiaries")
        for t in rel_map["catalyst_beneficiary"]:
            lines.append(f"- [[{t}]]")
        lines.append("")

    # Incoming mentioned_by edges
    incoming = graph._incoming_edges(nid)
    mentioners = [e["source"] for e in incoming if e["relationship"] == "mentioned_by"]
    if mentioners:
        lines.append("## Mentioned By")
        for src in mentioners:
            lines.append(f"- [[{src}]]")
        lines.append("")

    # Themes (outgoing catalyst_beneficiary to theme nodes)
    themes = [
        e["target"] for e in outgoing
        if e["relationship"] == "catalyst_beneficiary"
        and graph._nodes.get(e["target"], {}).get("node_type") == "theme"
    ]
    if themes:
        lines.append("## Themes")
        for t in themes:
            lines.append(f"- [[{t}]]")
        lines.append("")

    lines += [
        "## Signal History",
        f"- times_surfaced: {node['times_surfaced']}",
        f"- last_surfaced: {node['last_surfaced'] or 'null'}",
        f"- signal_strength: {node['signal_strength']}",
        "",
        "## Track Record",
        f"- Confirmed theses: {node['thesis_track_record']['confirmed']}",
        f"- Invalidated: {node['thesis_track_record']['invalidated']}",
    ]

    return "\n".join(lines) + "\n"

def render_theme_md(graph, node: dict) -> str:
    nid = node["id"]
    display = node["display_name"] or nid

    lines = [
        "---",
        f"theme: {nid}",
        "node_type: theme",
        "---",
        "",
        f"# {display}",
        "",
        "## Companies in This Theme",
    ]

    # Incoming catalyst_beneficiary edges from company nodes
    incoming = graph._incoming_edges(nid)
    companies = [
        e["source"] for e in incoming
        if e["relationship"] == "catalyst_beneficiary"
        and graph._nodes.get(e["source"], {}).get("node_type") == "company"
    ]
    for c in companies:
        lines.append(f"- [[{c}]]")

    return "\n".join(lines) + "\n"

def render_sector_md(graph, node: dict, all_company_nodes: List[dict]) -> str:
    nid = node["id"]
    display = node["display_name"] or nid

    sector_companies = [
        c for c in all_company_nodes if c.get("sector") == nid
    ]
    sector_companies.sort(key=lambda n: n["centrality"], reverse=True)

    lines = [
        "---",
        f"sector: {nid}",
        "---",
        "",
        f"# {display}",
        "",
        "## Companies",
    ]

    for c in sector_companies:
        score_str = str(c["aeternus_score"]) if c["aeternus_score"] is not None else "null"
        lines.append(
            f"- [[{c['id']}]] — centrality: {c['centrality']}, "
            f"signal: {c['signal_strength']}, score: {score_str}"
        )

    return "\n".join(lines) + "\n"

def render_summary(graph, company_nodes: List[dict], theme_nodes: List[dict],
                    sector_nodes: List[dict]) -> str:
    total_nodes = len(graph._nodes)
    total_edges = len(graph._edges)
    now = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")

    all_nodes_sorted = sorted(graph._nodes.values(), key=lambda n: n["centrality"], reverse=True)
    top_15 = all_nodes_sorted[:15]
    dark = graph.get_dark_nodes(min_centrality=0.0)[:10]

    # Hot sectors by average signal_strength
    sector_signals: Dict[str, List[float]] = defaultdict(list)
    for c in company_nodes:
        if c.get("sector"):
            sector_signals[c["sector"]].append(c["signal_strength"])
    sector_avgs = [
        (sec, sum(sigs) / len(sigs))
        for sec, sigs in sector_signals.items() if sigs
    ]
    sector_avgs.sort(key=lambda x: x[1], reverse=True)

    lines = [
        "# Aeternus Knowledge Graph — Summary",
        "",
        f"Generated: {now}",
        "",
        "## Stats",
        f"- Total nodes: {total_nodes}",
        f"- Total edges: {total_edges}",
        f"- Company nodes: {len(company_nodes)}",
        f"- Theme nodes: {len(theme_nodes)}",
        f"- Sector nodes: {len(sector_nodes)}",
        "",
        "## Top Centrality Nodes",
        "| Ticker | Centrality | Signal | Score | Times Surfaced |",
        "|--------|------------|--------|-------|----------------|",
    ]

    for n in top_15:
        score_str = str(n["aeternus_score"]) if n["aeternus_score"] is not None else "null"
        lines.append(
            f"| {n['id']} | {n['centrality']} | {n['signal_strength']} "
            f"| {score_str} | {n['times_surfaced']} |"
        )

    lines += [
        "",
        "## Dark Nodes (High Centrality, Not Yet Scored)",
        "| Ticker | Centrality | Times Surfaced | Sector |",
        "|--------|------------|----------------|--------|",
    ]
    for n in dark:
        lines.append(
            f"| {n['id']} | {n['centrality']} | {n['times_surfaced']} | {n.get('sector') or 'null'} |"
        )

    lines += ["", "## Hot Sectors (by average signal_strength)"]
    for i, (sec, avg) in enumerate(sector_avgs, 1):
        lines.append(f"{i}. [[{sec}]] — avg signal: {round(avg, 4)}")

    # Emergence tier distribution
    tier_counts: Dict[str, int] = {}
    for c in company_nodes:
        tier = c.get("emergence_tier") or "DARK"
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    tier_order = ["DARK", "ROCKY", "ATMOSPHERE", "HABITABLE", "SCORED"]
    lines += ["", "## Emergence Pipeline"]
    lines.append("| Tier | Count | Description |")
    lines.append("|------|-------|-------------|")
    tier_descs = {
        "DARK": "No cashtag/sentiment data",
        "ROCKY": "1 signal source present",
        "ATMOSPHERE": "Both velocity + sentiment",
        "HABITABLE": "High conviction (v_z >= 2.0 AND sentiment >= 0.5)",
        "SCORED": "Pipeline-analyzed with AeternusScore",
    }
    for tier in tier_order:
        count = tier_counts.get(tier, 0)
        if count > 0:
            lines.append(f"| {tier} | {count} | {tier_descs.get(tier, '')} |")

    # Structural forces reference
    try:
        from tradingagents.graph.structural_forces import STRUCTURAL_FORCES
        lines += ["", "## Structural Forces"]
        for f in STRUCTURAL_FORCES:
            lines.append(
                f"- [[{f.force_id}]] — {f.display_name} "
                f"(conviction {f.effective_conviction:.0%}, {f.effective_acceleration})"
            )
    except ImportError:
        pass

    return "\n".join(lines) + "\n"
