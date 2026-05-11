"""CLI command: fundamental — run fundamental framework from scout handoff."""
from __future__ import annotations

from cli.common import *  # noqa: F401,F403

import datetime as _dt
import json
import os
import subprocess
import sys as _sys


def _print_top10_table(rows: list[dict]) -> None:
    table = Table(title="Fundamental High-Conviction Top 10")
    table.add_column("Rank", justify="right")
    table.add_column("Ticker", style="bold green")
    table.add_column("Composite", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Confidence", justify="right")
    table.add_column("Lane")
    table.add_column("Reasons")
    for idx, row in enumerate(rows, start=1):
        table.add_row(
            str(row.get("selection_rank") or row.get("selection_order") or idx),
            str(row.get("ticker", "")),
            str(row.get("composite_score", "")),
            str(row.get("score", row.get("entry_score_0_100", ""))),
            str(row.get("confidence_numeric", row.get("confidence", ""))),
            str(row.get("lane_normalized", row.get("lane", ""))),
            ",".join(str(x) for x in row.get("reason_codes", [])),
        )
    console.print(table)


def _print_top15_table(rows: list[dict], title: str = "Fundamental High-Conviction Top 15") -> None:
    table = Table(title=title)
    table.add_column("Sleeve")
    table.add_column("Rank", justify="right")
    table.add_column("Ticker", style="bold green")
    table.add_column("Treatment")
    table.add_column("Score", justify="right")
    table.add_column("Exception", justify="right")
    for idx, row in enumerate(rows, start=1):
        table.add_row(
            str(row.get("selected_sleeve", "")),
            str(row.get("selected_sleeve_rank") or row.get("selection_rank") or idx),
            str(row.get("ticker", "")),
            str(row.get("portfolio_treatment", "")),
            str(row.get("score", row.get("entry_score_0_100", ""))),
            str(row.get("right_tail_exception_score", "")),
        )
    console.print(table)


def _print_candidate_scores(lake_root: Path) -> None:
    try:
        import pandas as pd
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]Could not render score table: pandas unavailable ({exc})[/yellow]")
        return

    path = lake_root / "candidate_scores.parquet"
    if not path.exists():
        console.print(f"[yellow]No candidate_scores artifact found at {path}[/yellow]")
        return
    frame = pd.read_parquet(path)
    if frame.empty:
        console.print("[yellow]candidate_scores is empty[/yellow]")
        return

    table = Table(title="Fundamental Scores")
    table.add_column("Ticker", style="bold green")
    table.add_column("Pre Score", justify="right")
    table.add_column("Bucket")
    table.add_column("Entry", justify="right")
    table.add_column("Label")
    table.add_column("Decision")
    table.add_column("Docs")
    for _, row in frame.iterrows():
        table.add_row(
            str(row.get("ticker", "")),
            str(row.get("pre_llm_fundamental_score", "")),
            str(row.get("pre_llm_fundamental_bucket", "")),
            str(row.get("entry_score_0_100", "")),
            str(row.get("entry_score_label", "")),
            str(row.get("decision_type", "")),
            str(row.get("document_status", "")),
        )
    console.print(table)


@app.command("fundamental-top10")
def fundamental_top10(
    scores_csv: str = typer.Option(..., "--scores-csv", help="Required final fundamental scores CSV path"),
    coverage_manifest: str = typer.Option("", "--coverage-manifest", help="Optional SEC coverage manifest CSV path"),
    output_root: str = typer.Option("", "--output-root", help="Output root; defaults to scores CSV parent or eval_results/fundamental/<date>"),
    date: str = typer.Option("", "--date", help="Selection date YYYY-MM-DD"),
    top_n: int = typer.Option(10, "--top-n", min=1, help="Number of names to select"),
    min_score: float = typer.Option(70.0, "--min-score", help="Minimum score threshold"),
    min_confidence: float = typer.Option(3.0, "--min-confidence", help="Minimum confidence threshold"),
    format: str = typer.Option("table", "--format", help="Output format: table|json"),
):
    """Select post-score high-conviction fundamental Top-N names."""
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import select_from_csv

    fmt = format.strip().lower()
    if fmt not in {"table", "json"}:
        console.print("[red]--format must be table or json[/red]")
        raise typer.Exit(1)

    scores_path = Path(scores_csv)
    if not scores_path.exists():
        console.print(f"[red]scores CSV not found: {scores_path}[/red]")
        raise typer.Exit(1)
    coverage_path = Path(coverage_manifest) if coverage_manifest.strip() else None
    if coverage_path is not None and not coverage_path.exists():
        console.print(f"[red]coverage manifest not found: {coverage_path}[/red]")
        raise typer.Exit(1)

    selection_date = date.strip()
    out_root = Path(output_root.strip()) if output_root.strip() else (
        Path("eval_results") / "fundamental" / selection_date if selection_date else scores_path.parent
    )
    config = {
        "top_n": top_n,
        "min_score": min_score,
        "min_confidence": min_confidence,
        "selection_date": selection_date,
        "coverage_gating": coverage_path is not None,
    }
    result = select_from_csv(scores_path, out_root, config, coverage_path)

    if fmt == "json":
        console.print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_top10_table(result.get("selected_rows", []))
        paths = result["output_paths"]
        console.print(f"[green]Wrote[/green] {paths['csv']} | {paths['json']} | {paths['recommendation_md']}")


@app.command("fundamental-top15")
def fundamental_top15(
    scores_csv: str = typer.Option(..., "--scores-csv", help="Required final fundamental scores CSV path"),
    coverage_manifest: str = typer.Option("", "--coverage-manifest", help="Optional SEC coverage manifest CSV path"),
    output_root: str = typer.Option("", "--output-root", help="Output root; defaults to scores CSV parent or eval_results/fundamental/<date>"),
    date: str = typer.Option("", "--date", help="Selection date YYYY-MM-DD"),
    core_n: int = typer.Option(10, "--core-n", min=1, help="Core names to select"),
    exception_slots: int = typer.Option(5, "--exception-slots", min=0, help="Right-tail exception slots"),
    format: str = typer.Option("table", "--format", help="Output format: table|json"),
):
    """Select Top-15 queue: Top-10 core plus right-tail exception sleeve."""
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import select_top15_from_csv

    fmt = format.strip().lower()
    if fmt not in {"table", "json"}:
        console.print("[red]--format must be table or json[/red]")
        raise typer.Exit(1)
    scores_path = Path(scores_csv)
    if not scores_path.exists():
        console.print(f"[red]scores CSV not found: {scores_path}[/red]")
        raise typer.Exit(1)
    coverage_path = Path(coverage_manifest) if coverage_manifest.strip() else None
    if coverage_path is not None and not coverage_path.exists():
        console.print(f"[red]coverage manifest not found: {coverage_path}[/red]")
        raise typer.Exit(1)
    selection_date = date.strip()
    out_root = Path(output_root.strip()) if output_root.strip() else (
        Path("eval_results") / "fundamental" / selection_date if selection_date else scores_path.parent
    )
    config = {
        "selection_date": selection_date,
        "enabled": True,
        "core_n": core_n,
        "exception_slots": exception_slots,
        "coverage_gating": coverage_path is not None,
    }
    result = select_top15_from_csv(scores_path, out_root, config, coverage_path)
    if fmt == "json":
        console.print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_top15_table(result.get("selected_rows", []))
        paths = result["output_paths"]
        console.print(f"[green]Wrote[/green] {paths['csv']} | {paths['json']} | {paths['recommendation_md']}")


@app.command("fundamental-top15-refill-shadow")
def fundamental_top15_refill_shadow(
    scores_csv: str = typer.Option(..., "--scores-csv", help="Required final fundamental scores CSV path"),
    coverage_manifest: str = typer.Option("", "--coverage-manifest", help="Optional SEC coverage manifest CSV path"),
    output_root: str = typer.Option("", "--output-root", help="Output root; defaults to scores CSV parent or eval_results/fundamental/<date>"),
    date: str = typer.Option("", "--date", help="Selection date YYYY-MM-DD"),
    mode: str = typer.Option("strict", "--mode", help="Core deterioration refill mode"),
    core_n: int = typer.Option(10, "--core-n", min=1, help="Core names to select"),
    exception_slots: int = typer.Option(5, "--exception-slots", min=0, help="Right-tail exception slots"),
    format: str = typer.Option("table", "--format", help="Output format: table|json"),
):
    """Emit shadow Top-15 refill variant; does not replace normal Top-15."""
    from tradingagents.research.fundamental.src.selection.high_conviction_top10 import select_top15_core_deterioration_refill_shadow_from_csv

    fmt = format.strip().lower()
    if fmt not in {"table", "json"}:
        console.print("[red]--format must be table or json[/red]")
        raise typer.Exit(1)
    mode_value = mode.strip().lower()
    if mode_value not in {"strict", "downgrade", "all_review"}:
        console.print("[red]--mode must be strict, downgrade, or all_review[/red]")
        raise typer.Exit(1)
    scores_path = Path(scores_csv)
    if not scores_path.is_file():
        console.print(f"[red]scores CSV not found: {scores_path}[/red]")
        raise typer.Exit(1)
    coverage_path = Path(coverage_manifest) if coverage_manifest.strip() else None
    if coverage_path is not None and not coverage_path.is_file():
        console.print(f"[red]coverage manifest not found: {coverage_path}[/red]")
        raise typer.Exit(1)
    selection_date = date.strip()
    if selection_date:
        try:
            if _dt.date.fromisoformat(selection_date).isoformat() != selection_date:
                raise ValueError
        except ValueError:
            console.print("[red]--date must be YYYY-MM-DD[/red]")
            raise typer.Exit(1)
    out_root = Path(output_root.strip()) if output_root.strip() else (
        Path("eval_results") / "fundamental" / selection_date if selection_date else scores_path.parent
    )
    config = {
        "selection_date": selection_date,
        "enabled": True,
        "core_n": core_n,
        "exception_slots": exception_slots,
        "coverage_gating": coverage_path is not None,
        "core_deterioration_refill": {"enabled": True, "mode": mode_value},
    }
    result = select_top15_core_deterioration_refill_shadow_from_csv(scores_path, out_root, config, coverage_path)
    if fmt == "json":
        console.print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_top15_table(
            result.get("selected_rows", []),
            title="Fundamental Top-15 Refill Shadow (not official)",
        )
        paths = result["output_paths"]
        console.print(f"[green]Wrote shadow[/green] {paths['csv']} | {paths['json']} | {paths['core_deterioration_refill_shadow_replacements']}")


@app.command("fundamental-right-tail-queues")
def fundamental_right_tail_queues(
    scores_csv: str = typer.Option(..., "--scores-csv", help="Required final fundamental scores CSV path"),
    top15_selected_csv: str = typer.Option("", "--top15-selected-csv", help="Optional high_conviction_top15.csv path for already-selected suppression"),
    target_events_csv: str = typer.Option("", "--target-events-csv", help="Optional historical/debug target events CSV"),
    output_root: str = typer.Option("", "--output-root", help="Output root; defaults to scores CSV parent"),
    date: str = typer.Option("", "--date", help="Selection date YYYY-MM-DD"),
    format: str = typer.Option("table", "--format", help="Output format: table|json"),
):
    """Emit right-tail visibility queues from final fundamental scores."""
    from tradingagents.research.fundamental.src.selection.right_tail_queues import select_right_tail_queues_from_csv

    fmt = format.strip().lower()
    if fmt not in {"table", "json"}:
        console.print("[red]--format must be table or json[/red]")
        raise typer.Exit(1)
    scores_path = Path(scores_csv)
    if not scores_path.exists():
        console.print(f"[red]scores CSV not found: {scores_path}[/red]")
        raise typer.Exit(1)
    top15_path = Path(top15_selected_csv) if top15_selected_csv.strip() else None
    if top15_path is not None and not top15_path.exists():
        console.print(f"[yellow]Top15 selected CSV not provided or not found: {top15_path}; scout queues may include already-selected Top15 names.[/yellow]")
        top15_path = None
    elif top15_path is None:
        console.print("[yellow]Top15 selected CSV not provided; scout queues may include already-selected Top15 names.[/yellow]")
    target_path = Path(target_events_csv) if target_events_csv.strip() else None
    if target_path is not None and not target_path.exists():
        console.print(f"[red]target events CSV not found: {target_path}[/red]")
        raise typer.Exit(1)
    out_root = Path(output_root.strip()) if output_root.strip() else scores_path.parent
    result = select_right_tail_queues_from_csv(
        scores_path,
        out_root,
        top15_selected_csv=top15_path,
        target_events_csv=target_path,
        selection_date=date.strip(),
    )
    if fmt == "json":
        console.print(json.dumps(result, indent=2, sort_keys=True))
    else:
        paths = result["output_paths"]
        console.print(f"[green]Wrote[/green] {paths['top15_exception_candidate_queue']} | {paths['right_tail_scout_queue']} | {paths['demote_review_priority_1']} | {paths['demote_review_queue']} | {paths['thin_signal_watchlist_queue']} | {paths['thin_signal_watchlist_top100']} | {paths['right_tail_evidence_score_diagnostics']}")
        if "target_miss_rescue_audit" in paths:
            console.print(f"[green]Target audit[/green] {paths['target_miss_rescue_audit']}")


def _export_final_scores(lake_root: Path, out_root: Path, run_date: str) -> Path | None:
    try:
        import pandas as pd
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]Could not export final scores CSV: pandas unavailable ({exc})[/yellow]")
        return None

    scores_parquet = lake_root / "candidate_scores.parquet"
    if not scores_parquet.exists():
        console.print(f"[yellow]No candidate_scores parquet to export: {scores_parquet}[/yellow]")
        return None
    out_path = out_root / f"fundamental_final_scores_{run_date}.csv"
    frame = pd.read_parquet(scores_parquet).fillna("")
    frame.to_csv(out_path, index=False)
    summary_path = out_root / f"fundamental_final_scores_summary_{run_date}.json"
    summary = {
        "rows": int(len(frame)),
        "score_path": str(out_path),
        "decision_counts": frame["decision_type"].value_counts(dropna=False).to_dict() if "decision_type" in frame else {},
        "document_status_counts": frame["document_status"].value_counts(dropna=False).to_dict() if "document_status" in frame else {},
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    console.print(f"[green]Final scores CSV[/green] {out_path}")
    return out_path


def _run_in_session_llm(
    *,
    packets_path: Path,
    output_dir: Path,
    output_csv: Path,
    lake_root: Path,
    as_of: str,
    model: str,
    reasoning_effort: str,
    batch_size: int,
) -> Path:
    from tradingagents.research.fundamental.src.features.llm_extraction import read_packets, run_llm_batches, write_consolidated_csv
    from tradingagents.research.fundamental.src.storage import add_run_lineage, make_pipeline_run_id, source_file_hash, write_table

    packets = read_packets(packets_path)
    rows = run_llm_batches(
        packets,
        output_dir=output_dir,
        model=model,
        reasoning_effort=reasoning_effort,
        batch_size=batch_size,
        resume=True,
    )
    write_consolidated_csv(output_dir, output_csv)
    lineage = add_run_lineage(rows, pipeline_run_id=make_pipeline_run_id("llm"), as_of_date=as_of, source_hash=source_file_hash(packets_path))
    write_table(lake_root, "post_llm_scores", lineage)
    return output_csv


def _run_external_llm(
    *,
    packets_path: Path,
    output_dir: Path,
    output_csv: Path,
    lake_root: Path,
    as_of: str,
    model: str,
    reasoning_effort: str,
    batch_size: int,
    fundamental_root: Path,
) -> Path:
    script = fundamental_root / "src" / "pipeline" / "run_llm_extraction.py"
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(fundamental_root.resolve()) + (os.pathsep + existing if existing else "")
    cmd = [
        _sys.executable,
        str(script),
        "--packets",
        str(packets_path),
        "--as-of",
        as_of,
        "--output-dir",
        str(output_dir),
        "--output-csv",
        str(output_csv),
        "--lake-root",
        str(lake_root),
        "--model",
        model,
        "--reasoning-effort",
        reasoning_effort,
        "--batch-size",
        str(batch_size),
    ]
    subprocess.run(cmd, check=True, env=env)
    return output_csv


def _write_subagent_llm_job(*, out_root: Path, packets_path: Path, output_dir: Path, output_csv: Path, lake_root: Path, as_of: str, model: str, reasoning_effort: str, batch_size: int) -> Path:
    job_path = out_root / "llm_subagent_job.json"
    payload = {
        "status": "needs_subagent_execution",
        "packets": str(packets_path),
        "output_dir": str(output_dir),
        "output_csv": str(output_csv),
        "lake_root": str(lake_root),
        "as_of": as_of,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "batch_size": batch_size,
        "required_result": "Run LLM extraction and write output_csv, then rerun fundamental with --llm-mode post-file --post-llm output_csv.",
    }
    job_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return job_path


@app.command("fundamental")
def fundamental(
    date: str = typer.Option("", "--date", help="Dealflow handoff date YYYY-MM-DD; defaults to today"),
    quarter: str = typer.Option("", "--quarter", help="Fundamental quarter, e.g. 2026Q2; defaults from --date"),
    handoff: str = typer.Option("", "--handoff", help="Optional final_dealflow_tickers.json path"),
    output_root: str = typer.Option("", "--output-root", help="Output root; defaults to eval_results/fundamental/<date>"),
    refresh_cik_map: bool = typer.Option(False, "--refresh-cik-map", help="Refresh SEC company_tickers.json cache"),
    skip_sec_fetch: bool = typer.Option(False, "--skip-sec-fetch", help="Skip SEC filing/document fetch"),
    skip_llm: bool = typer.Option(True, "--skip-llm/--run-llm", help="Legacy switch. --run-llm maps to --llm-mode in-session unless --llm-mode is set."),
    skip_price_fetch: bool = typer.Option(True, "--skip-price-fetch/--fetch-prices", help="Skip Yahoo price fetch by default"),
    llm_mode: str = typer.Option("skip", "--llm-mode", help="LLM mode: skip|post-file|in-session|external|subagent"),
    post_llm: str = typer.Option("", "--post-llm", help="Existing post_llm_scores.csv for --llm-mode post-file"),
    llm_model: str = typer.Option("gpt-5.5", "--llm-model", help="Model for in-session/external LLM extraction"),
    llm_reasoning_effort: str = typer.Option("high", "--llm-reasoning-effort", help="Reasoning effort for Codex-backed extraction"),
    llm_batch_size: int = typer.Option(8, "--llm-batch-size", min=1, help="Packets per LLM batch"),
    llm_output_dir: str = typer.Option("", "--llm-output-dir", help="LLM batch output dir; defaults under output root"),
    llm_output_csv: str = typer.Option("", "--llm-output-csv", help="LLM consolidated CSV; defaults under output root"),
):
    """Run the fundamental framework from dealflow scout ticker handoff."""
    import sys as _sys

    fundamental_root = Path("tradingagents") / "research" / "fundamental"
    if str(fundamental_root) not in _sys.path:
        _sys.path.insert(0, str(fundamental_root))

    framework_root = Path("tradingagents") / "research" / "fundamental"
    if str(framework_root.resolve()) not in _sys.path:
        _sys.path.insert(0, str(framework_root.resolve()))

    from tradingagents.research.fundamental.src.pipeline.dealflow_adapter import build_dealflow_universe_csv
    from tradingagents.research.fundamental.src.pipeline.run_quarter import run_quarter_pipeline

    run_date = date.strip() or _dt.date.today().strftime("%Y-%m-%d")
    out_root = Path(output_root.strip()) if output_root.strip() else Path("eval_results") / "fundamental" / run_date
    out_root.mkdir(parents=True, exist_ok=True)
    handoff_path = Path(handoff.strip()) if handoff.strip() else Path("eval_results") / "deal_flow" / run_date / "final_dealflow_tickers.json"
    if not handoff_path.exists():
        console.print(f"[red]dealflow ticker handoff not found: {handoff_path}[/red]")
        raise typer.Exit(1)

    universe_path = out_root / "dealflow_universe.csv"
    adapter_result = build_dealflow_universe_csv(
        as_of_date=run_date,
        handoff_path=handoff_path,
        output_path=universe_path,
        quarter=quarter.strip() or None,
        refresh_cik_map=bool(refresh_cik_map),
    )
    console.print(
        f"[green]Universe ready[/green] rows={adapter_result['row_count']} | "
        f"cik_resolved={adapter_result['resolved_cik_count']} | path={universe_path}"
    )
    if int(adapter_result.get("unresolved_cik_count", 0) or 0):
        console.print(f"[yellow]Unresolved CIKs: {adapter_result['unresolved_cik_count']}[/yellow]")

    lake_root = out_root / "lake"
    mode = llm_mode.strip().lower().replace("_", "-")
    if mode == "skip" and not skip_llm:
        mode = "in-session"
    valid_modes = {"skip", "post-file", "in-session", "external", "subagent"}
    if mode not in valid_modes:
        console.print(f"[red]--llm-mode must be one of: {', '.join(sorted(valid_modes))}[/red]")
        raise typer.Exit(1)

    post_llm_path = Path(post_llm.strip()) if post_llm.strip() else None
    llm_dir = Path(llm_output_dir.strip()) if llm_output_dir.strip() else out_root / "llm_batches"
    llm_csv = Path(llm_output_csv.strip()) if llm_output_csv.strip() else out_root / "post_llm_scores.csv"

    if mode == "post-file":
        if post_llm_path is None or not post_llm_path.exists() or post_llm_path.stat().st_size == 0:
            console.print("[red]--llm-mode post-file requires a non-empty --post-llm CSV[/red]")
            raise typer.Exit(1)
        result = run_quarter_pipeline(
            quarter=str(adapter_result["quarter"]),
            universe_path=universe_path,
            as_of=run_date,
            lake_root=lake_root,
            post_llm_path=post_llm_path,
            skip_sec_fetch=bool(skip_sec_fetch),
            skip_llm=False,
            skip_price_fetch=bool(skip_price_fetch),
        )
    elif mode == "skip":
        result = run_quarter_pipeline(
            quarter=str(adapter_result["quarter"]),
            universe_path=universe_path,
            as_of=run_date,
            lake_root=lake_root,
            post_llm_path=None,
            skip_sec_fetch=bool(skip_sec_fetch),
            skip_llm=True,
            skip_price_fetch=bool(skip_price_fetch),
        )
    else:
        first = run_quarter_pipeline(
            quarter=str(adapter_result["quarter"]),
            universe_path=universe_path,
            as_of=run_date,
            lake_root=lake_root,
            post_llm_path=None,
            skip_sec_fetch=bool(skip_sec_fetch),
            skip_llm=True,
            skip_price_fetch=bool(skip_price_fetch),
        )
        packets_path = Path(str(first["packet_path"]))
        raw_docs_path = lake_root / "raw_documents.parquet"
        if not raw_docs_path.exists() or raw_docs_path.stat().st_size == 0:
            console.print("[red]LLM mode requires SEC raw documents. Run without --skip-sec-fetch first, or reuse a lake with raw_documents.parquet.[/red]")
            raise typer.Exit(1)
        if not packets_path.exists() or packets_path.stat().st_size == 0:
            console.print(f"[red]LLM packet file missing/empty: {packets_path}[/red]")
            raise typer.Exit(1)
        if mode == "subagent":
            job_path = _write_subagent_llm_job(
                out_root=out_root,
                packets_path=packets_path,
                output_dir=llm_dir,
                output_csv=llm_csv,
                lake_root=lake_root,
                as_of=run_date,
                model=llm_model,
                reasoning_effort=llm_reasoning_effort,
                batch_size=llm_batch_size,
            )
            console.print(f"[yellow]Subagent job written[/yellow] {job_path}")
            console.print("[yellow]Run the subagent job, then rerun with --llm-mode post-file --post-llm " + str(llm_csv) + "[/yellow]")
            raise typer.Exit(2)
        if mode == "in-session":
            post_llm_path = _run_in_session_llm(
                packets_path=packets_path,
                output_dir=llm_dir,
                output_csv=llm_csv,
                lake_root=lake_root,
                as_of=run_date,
                model=llm_model,
                reasoning_effort=llm_reasoning_effort,
                batch_size=llm_batch_size,
            )
        else:
            post_llm_path = _run_external_llm(
                packets_path=packets_path,
                output_dir=llm_dir,
                output_csv=llm_csv,
                lake_root=lake_root,
                as_of=run_date,
                model=llm_model,
                reasoning_effort=llm_reasoning_effort,
                batch_size=llm_batch_size,
                fundamental_root=fundamental_root,
            )
        if post_llm_path is None or not post_llm_path.exists() or post_llm_path.stat().st_size == 0:
            console.print(f"[red]LLM output CSV missing/empty: {post_llm_path}[/red]")
            raise typer.Exit(1)
        result = run_quarter_pipeline(
            quarter=str(adapter_result["quarter"]),
            universe_path=universe_path,
            as_of=run_date,
            lake_root=lake_root,
            post_llm_path=post_llm_path,
            skip_sec_fetch=True,
            skip_llm=False,
            skip_price_fetch=bool(skip_price_fetch),
        )

    console.print(
        f"[green]Fundamental run complete[/green] run_id={result['pipeline_run_id']} | "
        f"candidates={result['candidate_rows']} | lake={lake_root} | llm_mode={mode}"
    )
    final_scores_path = _export_final_scores(lake_root, out_root, run_date)
    if final_scores_path is None:
        raise typer.Exit(1)
    _print_candidate_scores(lake_root)
