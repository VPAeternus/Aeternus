from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from tradingagents.research.fundamental.src.config.cache_paths import market_cache_root, sec_cache_root

from .artifacts import write_csv, write_json_atomic, write_text_atomic
from .coverage import coverage_gate_result, load_raw_documents_from_coverage, normalize_coverage_summary, run_sec_coverage_manifest, run_sec_fetch_once
from .eligibility import assign_daily_tiers, build_llm_eligibility, build_tier_filtered_llm_packets
from .finalize import add_qoq_context, build_final_scores, load_prior_context, publish_top15_and_shadow, validate_broad_final_scores, write_final_scores_csv
from .llm_validation import validate_post_llm_csv
from .models import DailyRunConfig, DailyRunState, GateResult, GateStatus, RunMode, StopGateError
from .review_list_filter import (
    _companyfacts_ready,
    _coverage_reason,
    fetch_review_price_rows,
    filter_review_list_rows,
    load_cached_review_price_rows,
    load_sec_ticker_map_rows,
    store_review_price_rows,
    write_sec_universe_inputs,
)
from .scoring_inputs import attach_entry_prices, build_pre_llm_from_companyfacts_cache, derive_tradable_date_from_coverage, split_score_ready_rows
from .universe import build_combined_universe, validate_universe_gate
from ..panel.exporter import build_complete_panel


def _null_price_provider(tickers, *, start, end):
    return []

try:
    from tradingagents.research.fundamental.src.ingest.prices import fetch_yahoo_ohlcv as _default_price_provider
except Exception:
    _default_price_provider = _null_price_provider


@dataclass
class DailyRunServices:
    price_provider: Callable[..., list[dict[str, Any]]] = _default_price_provider
    run_coverage: Callable[..., dict[str, Any]] | None = None
    run_fetch_once: Callable[..., dict[str, Any]] | None = None
    run_llm: Callable[..., Path | None] | None = None
    publish: Callable[..., GateResult] | None = None


@dataclass
class DailyRunResult:
    gates: list[GateResult]
    summary: dict[str, Any]
    artifacts: dict[str, str]


def _source_hash(path: Path | None) -> str:
    if path is None or not path.exists(): return ""
    import hashlib
    h = hashlib.sha256(); h.update(path.read_bytes()); return h.hexdigest()


def _record(state: DailyRunState, result: GateResult) -> None:
    state.record(result)
    write_json_atomic(state.config.output_root / "gates" / f"gate_{result.gate_number:02d}.json", {"gate_number": result.gate_number, "gate_name": result.gate_name, "status": result.status.value, "summary": result.summary, "artifacts": result.artifacts})
    result.raise_if_hard_stop()


def _copy_if_exists(source: str | Path | None, target: Path) -> str:
    if not source:
        return ""
    src = Path(source)
    if not src.exists() or src.is_dir():
        return ""
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
    return str(target)


def _write_operator_final_bundle(state: DailyRunState, publish_gate: GateResult) -> dict[str, str]:
    """Mirror only operator-facing publish files into output_root/final/.

    Root artifacts remain for compatibility; final/ is the clean review surface.
    """
    final_dir = state.config.output_root / "final"
    artifacts: dict[str, str] = {}
    copied = _copy_if_exists(state.artifacts.get("final_scores_csv"), final_dir / "fundamental_final_scores.csv")
    if copied:
        artifacts["operator_final_scores_csv"] = copied
    for key, filename in {
        "top15_csv": "high_conviction_top15.csv",
        "top15_json": "high_conviction_top15.json",
        "top15_recommendation_md": "high_conviction_top15_daily_recommendation.md",
    }.items():
        copied = _copy_if_exists(state.artifacts.get(key), final_dir / filename)
        if copied:
            artifacts[f"operator_{key}"] = copied
    guard_source = state.artifacts.get("publish_guard_summary") or state.artifacts.get("publish_guard_summary_json")
    copied = _copy_if_exists(guard_source, final_dir / "publish_guard_summary.json")
    if copied:
        artifacts["operator_publish_guard_summary_json"] = copied
    else:
        guard_path = final_dir / "publish_guard_summary.json"
        write_json_atomic(guard_path, {"gate": publish_gate.gate_number, "status": publish_gate.status.value, **publish_gate.summary})
        artifacts["operator_publish_guard_summary_json"] = str(guard_path)
    state.artifacts.update(artifacts)
    return artifacts


def _write_final_report(state: DailyRunState, summary: dict[str, Any]) -> Path:
    by_gate = {gate.gate_number: gate for gate in state.gates}
    universe = by_gate.get(2).summary if by_gate.get(2) else {}
    coverage = by_gate.get(3).summary if by_gate.get(3) else {}
    pre = by_gate.get(5).summary if by_gate.get(5) else {}
    price = by_gate.get(6).summary if by_gate.get(6) else {}
    tier = by_gate.get(7).summary if by_gate.get(7) else {}
    llm = by_gate.get(8).summary if by_gate.get(8) else {}
    final_gate = by_gate.get(9).summary if by_gate.get(9) else {}
    publish = by_gate.get(10).summary if by_gate.get(10) else {}
    lines = [
        "# Daily Fundamental Run Report",
        "",
        f"1. run mode: `{summary.get('mode', '')}`",
        f"2. as-of date and quarter: `{summary.get('as_of', '')}` / `{summary.get('quarter', '')}`",
        f"3. master universe count: `{universe.get('row_count', universe.get('combined_count', ''))}`",
        f"4. scout append count: `{universe.get('scout_count', '')}`",
        f"5. invalid/rerouted tickers: `{coverage.get('blocked_tickers', [])}`",
        f"6. pre-LLM scorable count: `{pre.get('pre_llm_scored', '')}`",
        f"7. price/trade-date coverage: entry ready `{price.get('entry_open_ready', '')}`, missing `{price.get('missing_entry_open', '')}`, score-ready `{price.get('score_input_ready', '')}`, score-data quarantine `{price.get('score_input_quarantine_count', '')}`",
        f"8. Tier 0/1/2/3/4 counts: `{ {k: v for k, v in tier.items() if k.startswith('tier_')} }`",
        f"9. LLM-eligible count: `{tier.get('llm_eligible_count', '')}`",
        f"10. LLM packet count: `{llm.get('packet_count', '')}`",
        f"11. post-LLM completed count: `{llm.get('completed_count', '')}`",
        f"12. final score row count: `{final_gate.get('final_score_rows', '')}`",
        f"13. HP bucket counts: see `{state.artifacts.get('final_scores_csv', '')}`",
        f"14. RM bucket counts: see `{state.artifacts.get('final_scores_csv', '')}`",
        f"15. Top10 + Plus5 tickers: selected count `{publish.get('top15_selected_count', '')}`",
        f"16. shadow refill result: selected count `{publish.get('shadow_selected_count', '')}`",
        f"17. stop gates encountered: `{[g.gate_number for g in state.gates if g.status == GateStatus.HARD_STOP]}`",
        f"18. quarantined rows by reason: price `{price.get('missing_entry_open', '')}`, score data `{price.get('score_input_quarantine_count', '')}`, LLM `{tier.get('llm_quarantine_count', '')}`, empty evidence `{llm.get('empty_evidence_count', '')}`",
        f"19. files produced: `{state.artifacts}`",
        f"20. output status: `{'final' if summary.get('final') else 'diagnostic_or_stopped'}`",
        "",
    ]
    report_path = state.config.output_root / "daily_fundamental_run_report.md"
    write_text_atomic(report_path, "\n".join(lines))
    return report_path


def _emit_complete_panel(state: DailyRunState) -> None:
    output_root = state.config.complete_panel_output_root or state.config.output_root / "complete_panel"
    try:
        result = build_complete_panel(
            run_root=state.config.output_root,
            output_root=output_root,
            quarter=state.config.quarter,
            as_of=state.config.as_of,
            allow_missing_financials=True,
        )
    except Exception as exc:  # noqa: BLE001
        _record(
            state,
            GateResult(
                11,
                "Complete panel emission",
                GateStatus.HARD_STOP,
                {"reason": "complete_panel_build_failed", "errors": [{"message": str(exc)}]},
                {},
            ),
        )
        return
    validation = result.get("validation") or {}
    artifacts = {
        "complete_panel_csv": str(result.get("csv_path", "")),
        "complete_panel_manifest": str(result.get("manifest_path", "")),
        "complete_panel_columns": str(result.get("columns_path", "")),
        "complete_panel_validation": str(result.get("validation_path", "")),
    }
    if validation.get("passed") is not True:
        _record(
            state,
            GateResult(
                11,
                "Complete panel emission",
                GateStatus.HARD_STOP,
                {
                    "reason": "complete_panel_validation_failed",
                    "errors": validation.get("errors") or [],
                    "validation": validation,
                },
                artifacts,
            ),
        )
        return
    _record(
        state,
        GateResult(
            11,
            "Complete panel emission",
            GateStatus.PASS,
            {"validation": validation},
            artifacts,
        ),
    )


def _finish(state: DailyRunState, *, final: bool, stopped: str = "") -> DailyRunResult:
    summary = {"run_id": state.run_id, "as_of": state.config.as_of, "quarter": state.config.quarter, "mode": state.config.run_mode.value, "final": final, "stopped": stopped, "gate_statuses": [{"gate": g.gate_number, "name": g.gate_name, "status": g.status.value} for g in state.gates], "artifacts": state.artifacts}
    report_path = _write_final_report(state, summary)
    state.artifacts["daily_fundamental_run_report"] = str(report_path)
    summary["artifacts"] = state.artifacts
    write_json_atomic(state.config.output_root / "run_manifest.json", summary)
    return DailyRunResult(state.gates, summary, state.artifacts)


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path or not path.exists() or path.stat().st_size == 0: return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _build_review_list_from_sec_map(
    *,
    config: DailyRunConfig,
    coverage_runner: Callable[..., dict[str, Any]],
    fetch_runner: Callable[..., dict[str, Any]],
    price_provider: Callable[..., list[dict[str, Any]]],
    live_root: Path,
) -> tuple[Path, dict[str, Any], dict[str, str]]:
    sec_map_path = config.sec_ticker_map_path or sec_cache_root("sec_company_tickers.json")
    candidate_rows = load_sec_ticker_map_rows(sec_map_path, quarter=config.quarter)
    input_artifacts = write_sec_universe_inputs(candidate_rows, output_root=config.output_root, quarter=config.quarter)
    sec_universe_csv = Path(input_artifacts["sec_universe_csv"])
    sec_universe_json = Path(input_artifacts["sec_universe_json"])
    coverage_raw = coverage_runner(
        out_root=config.output_root,
        universe_csv=sec_universe_csv,
        eligible_json=sec_universe_json,
        quarter=config.quarter,
        live_sec_root=live_root,
    )
    sec_fetch_passes: list[dict[str, Any]] = []
    if not config.skip_fetch and int(coverage_raw.get("fetch_queue_count") or 0):
        pass_number = 0
        while int(coverage_raw.get("fetch_queue_count") or 0) and pass_number < max(1, int(config.max_sec_fetch_passes)):
            pass_number += 1
            before_count = int(coverage_raw.get("fetch_queue_count") or 0)
            fetch_manifest = fetch_runner(out_root=config.output_root, live_sec_root=live_root)
            coverage_raw = coverage_runner(
                out_root=config.output_root,
                universe_csv=sec_universe_csv,
                eligible_json=sec_universe_json,
                quarter=config.quarter,
                live_sec_root=live_root,
            )
            sec_fetch_passes.append(
                {
                    "pass": pass_number,
                    "initial_fetch_queue_count": before_count,
                    "post_fetch_queue_count": int(coverage_raw.get("fetch_queue_count") or 0),
                    "fetch_manifest": fetch_manifest,
                }
            )
    coverage_csv = Path(coverage_raw.get("outputs", {}).get("manifest_csv", config.output_root / f"sec_coverage_manifest_{config.quarter}.csv"))
    coverage_rows = _read_csv(coverage_csv)
    as_of_date = date.fromisoformat(config.as_of)
    start = (as_of_date - timedelta(days=max(60, int(config.review_price_lookback_days)))).isoformat()
    end = (as_of_date + timedelta(days=1)).isoformat()
    coverage_by_ticker = {str(row.get("ticker", "")).upper(): row for row in coverage_rows}
    price_needed_tickers = [
        str(row["ticker"]).upper()
        for row in candidate_rows
        if not _coverage_reason(coverage_by_ticker.get(str(row.get("ticker", "")).upper()))
        and _companyfacts_ready(row, companyfacts_root=live_root / "companyfacts", quarter=config.quarter)
    ]
    cache_path = config.review_price_cache_path or market_cache_root()
    price_rows = load_cached_review_price_rows([cache_path], tickers=price_needed_tickers, start=start, end=end)
    cached_tickers = {str(row.get("ticker", "")).upper() for row in price_rows}
    missing_tickers = [ticker for ticker in price_needed_tickers if ticker not in cached_tickers]
    live_price_rows: list[dict[str, Any]] = []
    price_cache_artifacts: dict[str, str] = {}
    if missing_tickers and config.review_allow_live_price_fetch:
        live_price_rows = fetch_review_price_rows(
            missing_tickers,
            start=start,
            end=end,
            price_provider=price_provider,
            batch_size=config.review_price_batch_size,
        )
        if live_price_rows:
            price_rows.extend(live_price_rows)
            run_cache_path = store_review_price_rows(live_price_rows, output_root=config.output_root, quarter=config.quarter, as_of=config.as_of)
            shared_cache_path = store_review_price_rows(live_price_rows, output_root=market_cache_root(), quarter=config.quarter, as_of=config.as_of)
            price_cache_artifacts = {
                "review_live_price_run_cache": str(run_cache_path),
                "review_live_price_shared_cache": str(shared_cache_path),
            }
    result = filter_review_list_rows(
        candidate_rows=candidate_rows,
        coverage_rows=coverage_rows,
        price_rows=price_rows,
        companyfacts_root=live_root / "companyfacts",
        quarter=config.quarter,
        as_of=config.as_of,
        output_root=config.output_root,
        min_close=float(config.review_min_close),
        min_adv60=float(config.review_min_adv60),
        sec_fetch_attempted=not config.skip_fetch,
        price_fetch_attempted=bool(config.review_allow_live_price_fetch),
    )
    artifacts = {**input_artifacts, **result.artifacts, **price_cache_artifacts, "review_list_sec_coverage_manifest": str(coverage_csv)}
    summary = {
        **result.summary,
        "sec_ticker_map_path": str(sec_map_path),
        "price_start": start,
        "price_end_exclusive": end,
        "review_price_cache_path": str(cache_path),
        "price_needed_ticker_count": len(price_needed_tickers),
        "cached_price_ticker_count": len(cached_tickers),
        "missing_cached_price_ticker_count": len(missing_tickers),
        "live_price_fetch_count": len(live_price_rows),
        "live_price_fetch_allowed": bool(config.review_allow_live_price_fetch),
        "sec_fetch_pass_count": len(sec_fetch_passes),
        "final_sec_fetch_queue_count": int(coverage_raw.get("fetch_queue_count") or 0),
        "sec_fetch_passes": sec_fetch_passes,
    }
    return Path(result.artifacts["review_stock_list_json"]), summary, artifacts


def _cached_review_price_provider(config: DailyRunConfig) -> Callable[..., list[dict[str, Any]]]:
    cache_path = config.review_price_cache_path or market_cache_root()

    def provider(tickers, *, start, end):
        return load_cached_review_price_rows([cache_path], tickers=[str(ticker).upper() for ticker in tickers], start=start, end=end)

    return provider


def run_daily_fundamental(config: DailyRunConfig, services: DailyRunServices | None = None) -> DailyRunResult:
    services = services or DailyRunServices()
    run_price_provider = services.price_provider
    if config.build_review_list_from_sec and not config.review_allow_live_price_fetch:
        run_price_provider = _cached_review_price_provider(config)
    existing_manifest = config.output_root / "run_manifest.json"
    if existing_manifest.exists():
        try:
            prior = json.loads(existing_manifest.read_text(encoding="utf-8"))
        except Exception:
            prior = {}
        if prior.get("final") is True:
            blocked = {"reason": "output_root_contains_prior_final_run", "existing_manifest": str(existing_manifest)}
            blocked_path = config.output_root / f"rerun_blocked_{uuid4().hex[:8]}.json"
            write_json_atomic(blocked_path, blocked)
            gate = GateResult(1, "Run identity and immutable snapshot", GateStatus.HARD_STOP, blocked, {"rerun_blocked_manifest": str(blocked_path)})
            return DailyRunResult([gate], {"final": False, "stopped": str(blocked), "artifacts": gate.artifacts}, gate.artifacts)

    config.output_root.mkdir(parents=True, exist_ok=True)
    state = DailyRunState(config=config, run_id=f"daily_{uuid4().hex[:12]}")
    try:
        snapshots: dict[str, str] = {}
        snapshot_dir = config.output_root / "snapshots"
        for name, path in {"master_universe": config.master_universe_path, "handoff": config.handoff_path}.items():
            if path and path.exists():
                target = snapshot_dir / f"{name}{path.suffix or '.snapshot'}"
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                snapshots[name] = str(target)
        identity = {"run_id": state.run_id, "as_of": config.as_of, "quarter": config.quarter, "mode": config.run_mode.value, "source_hashes": {"master_universe": _source_hash(config.master_universe_path), "handoff": _source_hash(config.handoff_path), "sec_ticker_map": _source_hash(config.sec_ticker_map_path or sec_cache_root("sec_company_tickers.json")) if config.build_review_list_from_sec else ""}, "snapshots": snapshots}
        identity_path = config.output_root / "run_identity.json"; write_json_atomic(identity_path, identity)
        _record(state, GateResult(1, "Run identity and immutable snapshot", GateStatus.PASS, identity, {"run_identity": str(identity_path), **{f"snapshot_{k}": v for k, v in snapshots.items()}}))

        live_root = config.sec_live_root or sec_cache_root("live_sec")
        coverage_runner = services.run_coverage or run_sec_coverage_manifest
        active_master_universe_path = config.master_universe_path
        active_handoff_path = config.handoff_path
        review_filter_summary: dict[str, Any] = {}
        review_filter_artifacts: dict[str, str] = {}
        if config.build_review_list_from_sec:
            active_master_universe_path, review_filter_summary, review_filter_artifacts = _build_review_list_from_sec_map(
                config=config,
                coverage_runner=coverage_runner,
                fetch_runner=services.run_fetch_once or run_sec_fetch_once,
                price_provider=run_price_provider,
                live_root=live_root,
            )
            active_handoff_path = None
            state.artifacts.update(review_filter_artifacts)
            if int(review_filter_summary.get("kept_count", 0)) <= 0:
                _record(state, GateResult(2, "Universe construction and drift control", GateStatus.HARD_STOP, {"reason": "review_list_filter_kept_zero", **review_filter_summary}, review_filter_artifacts))

        if active_master_universe_path is None or not active_master_universe_path.exists():
            _record(state, GateResult(2, "Universe construction and drift control", GateStatus.HARD_STOP, {"reason": "missing_master_universe_path"}, {}))
        universe_csv = config.output_root / f"master_fundamental_universe_{config.quarter}.csv"
        try:
            universe = build_combined_universe(master_universe_path=active_master_universe_path, handoff_path=active_handoff_path, quarter=config.quarter, output_csv=universe_csv)
        except ValueError as exc:
            _record(state, GateResult(2, "Universe construction and drift control", GateStatus.HARD_STOP, {"reason": "invalid_master_universe_format", "error": str(exc)}, {}))
        universe.artifacts.update(review_filter_artifacts)
        universe_gate = validate_universe_gate(universe.rows, run_mode=config.run_mode, scout_count=int(universe.summary.get("scout_count", 0)), min_broad_universe_count=config.min_broad_universe_count, artifacts=universe.artifacts)
        if review_filter_summary:
            universe_gate.summary["review_list_filter"] = review_filter_summary
        _record(state, universe_gate)

        coverage_raw = coverage_runner(out_root=config.output_root, universe_csv=universe_csv, eligible_json=active_master_universe_path, quarter=config.quarter, live_sec_root=live_root)
        companyfacts_ready = len(universe.rows) - int((coverage_raw.get("missing_input_counts", {}) or {}).get("companyfacts", 0))
        coverage_summary = normalize_coverage_summary(coverage_raw, universe_count=len(universe.rows), companyfacts_ready_count=companyfacts_ready)
        _record(state, coverage_gate_result(coverage_summary, artifact_paths=coverage_summary.get("outputs", {})))

        if not config.skip_fetch and coverage_summary["fetch_queue_count"]:
            fetcher = services.run_fetch_once or run_sec_fetch_once
            fetch_passes: list[dict[str, Any]] = []
            initial_fetch_queue = coverage_summary["fetch_queue_count"]
            pass_number = 0
            while coverage_summary["fetch_queue_count"] and pass_number < max(1, int(config.max_sec_fetch_passes)):
                pass_number += 1
                before_fetch_queue = coverage_summary["fetch_queue_count"]
                fetch_manifest = fetcher(out_root=config.output_root, live_sec_root=live_root)
                coverage_raw = coverage_runner(out_root=config.output_root, universe_csv=universe_csv, eligible_json=active_master_universe_path, quarter=config.quarter, live_sec_root=live_root)
                companyfacts_ready = len(universe.rows) - int((coverage_raw.get("missing_input_counts", {}) or {}).get("companyfacts", 0))
                coverage_summary = normalize_coverage_summary(coverage_raw, universe_count=len(universe.rows), companyfacts_ready_count=companyfacts_ready)
                fetch_passes.append({"pass": pass_number, "initial_fetch_queue_count": before_fetch_queue, "post_fetch_queue_count": coverage_summary["fetch_queue_count"], "fetch_manifest": fetch_manifest})
            gate_status = GateStatus.HARD_STOP if coverage_summary["fetch_queue_count"] else GateStatus.PASS
            reason = "fetch_queue_remaining_after_max_passes" if coverage_summary["fetch_queue_count"] else "fetch_queue_drained"
            _record(state, GateResult(4, "Fetch and materialization", gate_status, {"initial_fetch_queue_count": initial_fetch_queue, "final_fetch_queue_count": coverage_summary["fetch_queue_count"], "fetch_pass_count": len(fetch_passes), "max_sec_fetch_passes": config.max_sec_fetch_passes, "reason": reason, "fetch_passes": fetch_passes}, coverage_summary.get("outputs", {})))
        else:
            _record(state, GateResult(4, "Fetch and materialization", GateStatus.PASS, {"fetch_queue_count": coverage_summary["fetch_queue_count"], "reason": "no_fetchable_queue_or_skip_fetch"}, {}))

        pre_rows, pre_summary = build_pre_llm_from_companyfacts_cache(universe_rows=universe.rows, companyfacts_root=live_root / "companyfacts", quarter=config.quarter)
        pre_path = config.output_root / "pre_llm_scores.csv"; write_csv(pre_path, pre_rows)
        _record(state, GateResult(5, "Pre-LLM scoring readiness", GateStatus.PASS, pre_summary, {"pre_llm_scores": str(pre_path)}))

        coverage_csv = Path(coverage_raw.get("outputs", {}).get("manifest_csv", config.output_root / f"sec_coverage_manifest_{config.quarter}.csv"))
        coverage_rows = _read_csv(coverage_csv)
        coverage_by_key = {(r.get("ticker", "").upper(), r.get("quarter", "")): r for r in coverage_rows}
        pre_with_dates = []
        for row in pre_rows:
            cov = coverage_by_key.get((row.get("ticker", "").upper(), row.get("quarter", "")), {})
            pre_with_dates.append({**row, **cov, "tradable_date": row.get("tradable_date") or derive_tradable_date_from_coverage(cov)})
        priced_rows, price_quarantine, price_summary = attach_entry_prices(pre_with_dates, as_of=config.as_of, price_provider=run_price_provider)
        price_ready_rows = [r for r in priced_rows if r.get("entry_open")]
        score_ready_rows, score_input_quarantine, score_input_summary = split_score_ready_rows(price_ready_rows)
        price_q_path = config.output_root / "entry_price_quarantine.csv"; write_csv(price_q_path, price_quarantine)
        score_q_path = config.output_root / "score_input_quarantine.csv"; write_csv(score_q_path, score_input_quarantine)
        price_status = GateStatus.HARD_STOP if config.run_mode == RunMode.BROAD_MASTER_FINAL and price_quarantine else GateStatus.PASS
        _record(state, GateResult(6, "Trade date, price, and entry-open", price_status, {**price_summary, **score_input_summary, "tier_input_rows": len(score_ready_rows), "reason": "missing_entry_open" if price_quarantine else ""}, {"entry_price_quarantine": str(price_q_path), "score_input_quarantine": str(score_q_path)}))

        prior_rows, prior_summary = load_prior_context(config.prior_context_path, current_quarter=config.quarter)
        tier_input_rows = score_ready_rows
        pre_tier_qoq_summary: dict[str, Any] = {
            "pre_tier_qoq_context_loaded": bool(prior_summary.get("prior_context_loaded")),
            "pre_tier_qoq_context_match_rows": 0,
        }
        if prior_summary.get("prior_context_loaded") and not prior_summary.get("prior_duplicate_key_count") and prior_summary.get("expected_prior_context_rows"):
            tier_input_rows, qoq_summary = add_qoq_context(score_ready_rows, prior_rows)
            pre_tier_qoq_summary.update({
                "pre_tier_qoq_context_match_rows": qoq_summary.get("qoq_context_match_rows", 0),
                "pre_tier_qoq_context_input_rows": qoq_summary.get("qoq_context_input_rows", len(score_ready_rows)),
            })

        tiered_rows, tier_summary = assign_daily_tiers(tier_input_rows)
        eligible_rows, llm_quarantine, eligibility_summary = build_llm_eligibility(tiered_rows, coverage_rows)
        write_csv(config.output_root / "tier_classification.csv", tiered_rows); write_csv(config.output_root / "llm_eligibility.csv", eligible_rows); write_csv(config.output_root / "llm_quarantine.csv", llm_quarantine)
        _record(state, GateResult(7, "Tier 0-4 and LLM eligibility", GateStatus.PASS, {**tier_summary, **eligibility_summary, **pre_tier_qoq_summary}, {"tier_classification": str(config.output_root / "tier_classification.csv"), "llm_eligibility": str(config.output_root / "llm_eligibility.csv")}))

        raw_docs = load_raw_documents_from_coverage(coverage_csv, live_root)
        packets, empty_q, packet_summary = build_tier_filtered_llm_packets(eligible_rows, raw_docs, broad_universe_count=len(universe.rows))
        packet_path = config.output_root / "lake" / "artifacts" / f"{config.quarter}_llm_packets.jsonl"
        write_text_atomic(packet_path, "\n".join(json.dumps(p, sort_keys=True) for p in packets))
        empty_q_path = config.output_root / "llm_empty_evidence_quarantine.csv"; write_csv(empty_q_path, empty_q)
        post_llm_path: Path | None = None
        if packet_summary["empty_evidence_count"]:
            _record(state, GateResult(8, "LLM packet, extraction, and validation", GateStatus.HARD_STOP, {**packet_summary, "reason": "eligible_rows_missing_non_empty_evidence"}, {"llm_packets": str(packet_path), "llm_empty_evidence_quarantine": str(empty_q_path)}))
        if packet_summary["packet_count"] != packet_summary["eligible_count"]:
            _record(state, GateResult(8, "LLM packet, extraction, and validation", GateStatus.HARD_STOP, {**packet_summary, "reason": "packet_count_mismatch"}, {"llm_packets": str(packet_path)}))
        if config.skip_llm or config.run_mode == RunMode.DIAGNOSTIC_ONLY:
            _record(state, GateResult(8, "LLM packet, extraction, and validation", GateStatus.SKIPPED, {**packet_summary, "reason": "skip_llm_or_diagnostic"}, {"llm_packets": str(packet_path), "llm_empty_evidence_quarantine": str(empty_q_path)}))
        else:
            if config.llm_mode == "post-file" and config.post_llm_path is not None:
                post_llm_path = config.post_llm_path
            else:
                post_llm_path = services.run_llm(packets_path=packet_path, output_root=config.output_root, config=config) if services.run_llm else None
            if post_llm_path is None:
                reason = "llm_subagent_job_written_rerun_post_file" if config.llm_mode == "subagent" else "llm_runner_not_configured"
                artifacts = {"llm_packets": str(packet_path)}
                job_path = config.output_root / "llm_subagent_job.json"
                if job_path.exists():
                    artifacts["llm_subagent_job"] = str(job_path)
                _record(state, GateResult(8, "LLM packet, extraction, and validation", GateStatus.HARD_STOP, {"reason": reason}, artifacts))
            _record(state, validate_post_llm_csv(post_llm_path, expected_sample_ids={p["sample_id"] for p in packets}))

        post_rows = _read_csv(post_llm_path) if post_llm_path else []
        final_rows, final_summary = build_final_scores(tiered_rows, as_of=config.as_of, post_llm_rows=post_rows, prior_context_rows=prior_rows)
        final_summary = {**final_summary, **prior_summary}
        final_path = config.output_root / f"fundamental_final_scores_{config.as_of}.csv"
        final_artifacts = write_final_scores_csv(final_path, final_rows, final_summary)
        explicit_invalid_quarantine_count = len(price_quarantine) + len(score_input_quarantine)
        _record(state, validate_broad_final_scores(final_rows=final_rows, broad_universe_count=len(universe.rows), explicit_invalid_quarantine_count=explicit_invalid_quarantine_count, run_mode=config.run_mode, artifacts=final_artifacts, prior_context_summary=prior_summary))

        if config.run_mode == RunMode.BROAD_MASTER_FINAL and not config.skip_llm:
            publish_gate = (services.publish or publish_top15_and_shadow)(scores_csv=final_path, output_root=config.output_root, as_of=config.as_of, broad_universe_count=len(universe.rows), explicit_invalid_quarantine_count=explicit_invalid_quarantine_count, coverage_manifest=coverage_csv if coverage_csv.exists() else None)
            _record(state, publish_gate)
            _write_operator_final_bundle(state, publish_gate)
            if config.emit_complete_panel:
                _emit_complete_panel(state)
            return _finish(state, final=True)
        _record(state, GateResult(10, "Top10 + Plus5 + shadow refill publish", GateStatus.SKIPPED, {"reason": "not_broad_final_or_skip_llm"}, {}))
        return _finish(state, final=False, stopped="publish_skipped")
    except StopGateError as exc:
        return _finish(state, final=False, stopped=str(exc))
