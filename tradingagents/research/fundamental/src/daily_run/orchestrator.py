from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from tradingagents.research.fundamental.src.config.cache_paths import market_cache_root, sec_cache_root
from tradingagents.research.fundamental.src.features.common import clean, prior_quarter
from tradingagents.research.fundamental.src.features.llm_extraction import save_llm_rows_to_cache
from tradingagents.research.fundamental.src.features.post_llm_scores import REQUIRED_LLM_FIELDS

from .artifacts import write_csv, write_json_atomic, write_text_atomic
from .coverage import coverage_gate_result, load_raw_documents_from_coverage, materialize_alias_documents_from_queue, normalize_coverage_summary, run_sec_coverage_manifest, run_sec_fetch_once
from .eligibility import assign_daily_tiers, build_llm_eligibility, build_tier_filtered_llm_packets
from .finalize import QOQ_REQUIRED_FIELDS, add_qoq_context, build_final_scores, load_prior_context, publish_top15_and_shadow, validate_broad_final_scores, write_final_scores_csv
from .llm_validation import validate_post_llm_csv
from .identity import IdentityResolution, load_sec_ticker_rows, resolve_ticker_identity
from .master_source import ADDITIONS_LEDGER, append_master_additions, materialize_master_universe
from .models import DailyRunConfig, DailyRunState, GateResult, GateStatus, RunMode, StopGateError
from .price_cache import load_or_fetch_price_rows
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
from .scoring_inputs import attach_entry_prices, build_pre_llm_from_companyfacts_cache, derive_tradable_date_from_coverage, materialize_companyfacts_fallbacks, split_score_ready_rows
from .status import write_daily_status
from .universe import build_combined_universe, validate_universe_gate
from ..panel.exporter import build_complete_panel
from ..pipeline.dealflow_adapter import current_quarter

DEFAULT_TRUSTED_PANEL_PATH = Path("outputs/fundamental_backtest/full_complete_panel_2021Q4_2026Q2/fundamental_complete_prellm_to_top15_2021Q4_2026Q2.csv")


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
    resolve_identity: Callable[[str], IdentityResolution] | None = None
    sec_direct_lookup: Callable[[str], Mapping[str, Any] | None] | None = None


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


def _csv_row_count(path_value: str | Path | None) -> int:
    if not path_value:
        return 0
    path = Path(path_value)
    if not path.is_file() or path.stat().st_size == 0:
        return 0
    with path.open(newline="", encoding="utf-8") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def _read_tickers_from_csv(path_value: str | Path | None) -> list[str]:
    if not path_value:
        return []
    path = Path(path_value)
    if not path.is_file() or path.stat().st_size == 0:
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [_ticker(row.get("ticker")) for row in csv.DictReader(handle) if _ticker(row.get("ticker"))]


def _shadow_replacement_count(state: DailyRunState) -> int:
    shadow_json = state.artifacts.get("shadow_json")
    if shadow_json and Path(shadow_json).is_file():
        try:
            payload = json.loads(Path(shadow_json).read_text(encoding="utf-8"))
            summary = payload.get("core_deterioration_refill_summary") if isinstance(payload, dict) else {}
            if isinstance(summary, dict):
                return int(summary.get("replacement_count") or 0)
        except Exception:
            pass
    return _csv_row_count(state.artifacts.get("shadow_core_deterioration_refill_shadow_replacements"))


def _qoq_match_count(rows: list[dict[str, Any]]) -> int:
    return sum(1 for row in rows if all(clean(row.get(field)) for field in QOQ_REQUIRED_FIELDS))


def _qoq_match_rows_for_readiness(final_summary: dict[str, Any], tier_summary: dict[str, Any]) -> int:
    if "llm_eligible_qoq_context_match_rows" in final_summary:
        return int(final_summary.get("llm_eligible_qoq_context_match_rows") or 0)
    if "llm_eligible_qoq_context_match_rows" in tier_summary:
        return int(tier_summary.get("llm_eligible_qoq_context_match_rows") or 0)
    return int(final_summary.get("qoq_context_match_rows") or 0)


def _write_publish_readiness_summary(state: DailyRunState, *, final: bool, stopped: str) -> dict[str, str]:
    by_gate = {gate.gate_number: gate for gate in state.gates}
    hard_stop_gates = [gate.gate_number for gate in state.gates if gate.status == GateStatus.HARD_STOP]
    gates_passed = bool(state.gates) and not hard_stop_gates
    tier_gate = by_gate.get(7)
    llm_gate = by_gate.get(8)
    final_gate = by_gate.get(9)
    publish_gate = by_gate.get(10)
    tier_summary = tier_gate.summary if tier_gate else {}
    llm_summary = llm_gate.summary if llm_gate else {}
    final_summary = final_gate.summary if final_gate else {}
    publish_summary = publish_gate.summary if publish_gate else {}
    llm_eligible_count = int(tier_summary.get("llm_eligible_count") or 0)
    qoq_missing_count = int(final_summary.get("llm_complete_qoq_missing_rows") or 0)
    prior_missing_count = int(final_summary.get("prior_llm_extract_missing_for_final_count") or 0)
    qoq_context_match_rows = _qoq_match_rows_for_readiness(final_summary, tier_summary)
    prior_context_loaded = bool(final_summary.get("prior_context_loaded"))
    prior_duplicate_count = int(final_summary.get("prior_duplicate_key_count") or 0)
    expected_prior_context_rows = int(final_summary.get("expected_prior_context_rows") or 0)
    prior_context_complete = bool(
        final_gate
        and prior_context_loaded
        and prior_duplicate_count == 0
        and expected_prior_context_rows > 0
        and qoq_context_match_rows >= llm_eligible_count
        and qoq_missing_count == 0
        and prior_missing_count == 0
    )
    expected_llm = int(llm_summary.get("expected_count") or llm_summary.get("packet_count") or 0)
    completed_llm = int(llm_summary.get("completed_count") or 0)
    llm_complete = bool(llm_gate and llm_gate.status == GateStatus.PASS and (expected_llm == 0 or completed_llm == expected_llm))
    top15_emitted = bool(state.artifacts.get("top15_csv") and Path(state.artifacts["top15_csv"]).is_file())
    core_tickers = _read_tickers_from_csv(state.artifacts.get("top15_core_deterioration_review_queue"))
    readiness = {
        "status": "pass" if final and gates_passed and llm_complete and prior_context_complete and top15_emitted else ("blocked" if hard_stop_gates else "not_final"),
        "final": final,
        "stopped": stopped,
        "gates_passed": gates_passed,
        "hard_stop_gates": hard_stop_gates,
        "llm_complete": llm_complete,
        "llm_expected_count": expected_llm,
        "llm_completed_count": completed_llm,
        "llm_eligible_count": llm_eligible_count,
        "prior_context_complete": prior_context_complete,
        "prior_context_loaded": prior_context_loaded,
        "prior_context_reason": str(final_summary.get("reason") or ""),
        "expected_prior_context_rows": expected_prior_context_rows,
        "prior_duplicate_key_count": prior_duplicate_count,
        "qoq_context_match_rows": qoq_context_match_rows,
        "qoq_missing_count": qoq_missing_count,
        "prior_llm_missing_for_final_count": prior_missing_count,
        "top15_emitted": top15_emitted,
        "top15_selected_count": int(publish_summary.get("top15_selected_count") or 0),
        "shadow_selected_count": int(publish_summary.get("shadow_selected_count") or 0),
        "shadow_replacement_count": _shadow_replacement_count(state),
        "core_deterioration_count": len(core_tickers),
        "core_deterioration_tickers": core_tickers,
    }
    json_path = state.config.output_root / "publish_readiness_summary.json"
    md_path = state.config.output_root / "publish_readiness_summary.md"
    write_json_atomic(json_path, readiness)
    lines = [
        "# Publish Readiness",
        "",
        f"Status: {readiness['status']}",
        f"Final run: {readiness['final']}",
        f"Gates passed: {readiness['gates_passed']}",
        f"LLM complete: {readiness['llm_complete']} ({completed_llm}/{expected_llm})",
        f"Prior context complete: {readiness['prior_context_complete']}",
        f"QoQ prior matches: {qoq_context_match_rows}/{llm_eligible_count}",
        f"QoQ missing count: {qoq_missing_count}",
        f"Top15 emitted: {readiness['top15_emitted']}",
        f"Shadow replacements: {readiness['shadow_replacement_count']}",
        f"Core deterioration names: {', '.join(core_tickers) if core_tickers else 'none'}",
    ]
    if hard_stop_gates:
        lines.append(f"Hard-stop gates: {', '.join(str(gate) for gate in hard_stop_gates)}")
    write_text_atomic(md_path, "\n".join(lines) + "\n")
    return {"publish_readiness_summary_json": str(json_path), "publish_readiness_summary_md": str(md_path)}


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
    state.artifacts.update(_write_publish_readiness_summary(state, final=final, stopped=stopped))
    report_path = _write_final_report(state, summary)
    state.artifacts["daily_fundamental_run_report"] = str(report_path)
    summary["artifacts"] = state.artifacts
    write_json_atomic(state.config.output_root / "run_manifest.json", summary)
    return DailyRunResult(state.gates, summary, state.artifacts)


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path or not path.exists() or path.stat().st_size == 0: return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _ticker(value: Any) -> str:
    return str(value or "").upper().replace(".", "-").replace("/", "-").strip()


def _load_json(path: Path | None) -> Any:
    if path is None or not path.exists() or path.stat().st_size == 0:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _master_tickers(path: Path | None) -> set[str]:
    if path is not None and path.suffix.lower() == ".csv":
        return {_ticker(row.get("ticker") or row.get("symbol")) for row in _read_csv(path)}
    payload = _load_json(path)
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        items = payload["items"]
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    return {_ticker(item.get("ticker") or item.get("symbol")) for item in items if isinstance(item, dict)}


def _handoff_tickers(path: Path | None) -> list[str]:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return []
    seen: set[str] = set()
    tickers: list[str] = []
    for raw in payload.get("tickers", []) or []:
        ticker = _ticker(raw)
        if ticker and ticker not in seen:
            tickers.append(ticker)
            seen.add(ticker)
    return tickers


def _dealflow_root_from_handoff(path: Path) -> Path | None:
    try:
        run_date = date.fromisoformat(path.parent.name)
    except Exception:
        return None
    if path.parent.parent.name != "deal_flow":
        return None
    return path.parent.parent if run_date else None


def _load_handoff_payload(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    return payload if isinstance(payload, dict) else {}


def _materialize_handoff_backlog(config: DailyRunConfig, handoff_path: Path | None) -> tuple[Path | None, dict[str, Any], dict[str, str]]:
    if handoff_path is None or not handoff_path.exists():
        return handoff_path, {"dealflow_backlog_enabled": False}, {}
    root = _dealflow_root_from_handoff(handoff_path)
    days = max(1, int(config.dealflow_backlog_days))
    as_of_date = date.fromisoformat(config.as_of)
    start_date = as_of_date - timedelta(days=days - 1)
    source_paths: list[Path] = []
    if root is not None:
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            try:
                day = date.fromisoformat(child.name)
            except Exception:
                continue
            candidate = child / handoff_path.name
            if start_date <= day <= as_of_date and candidate.exists():
                source_paths.append(candidate)
    if handoff_path not in source_paths:
        source_paths.append(handoff_path)
    seen: set[str] = set()
    tickers: list[str] = []
    metadata: dict[str, Any] = {}
    source_counts: dict[str, int] = {}
    for path in source_paths:
        payload = _load_handoff_payload(path)
        source_date = path.parent.name
        count = 0
        for raw in payload.get("tickers", []) or []:
            ticker = _ticker(raw)
            if not ticker:
                continue
            count += 1
            meta = dict((payload.get("metadata_by_ticker") or {}).get(ticker) or {})
            prior_sources = list(meta.get("dealflow_source_dates", []) or [])
            if source_date not in prior_sources:
                prior_sources.append(source_date)
            meta["dealflow_source_dates"] = prior_sources
            metadata.setdefault(ticker, meta)
            if ticker not in seen:
                tickers.append(ticker)
                seen.add(ticker)
        source_counts[source_date] = count
    if len(source_paths) <= 1:
        return handoff_path, {"dealflow_backlog_enabled": False, "dealflow_backlog_days": days}, {}
    merged_path = config.output_root / "dealflow_handoff_backlog_merged.json"
    payload = {
        "tickers": tickers,
        "metadata_by_ticker": metadata,
        "source_stage": "dealflow_backlog",
        "source_paths": [str(path) for path in source_paths],
        "source_counts": source_counts,
        "date_start": start_date.isoformat(),
        "date_end": as_of_date.isoformat(),
        "count": len(tickers),
    }
    write_json_atomic(merged_path, payload)
    summary = {
        "dealflow_backlog_enabled": True,
        "dealflow_backlog_days": days,
        "dealflow_backlog_source_count": len(source_paths),
        "dealflow_backlog_ticker_count": len(tickers),
        "dealflow_backlog_source_counts": source_counts,
        "dealflow_backlog_start": start_date.isoformat(),
        "dealflow_backlog_end": as_of_date.isoformat(),
    }
    return merged_path, summary, {"dealflow_handoff_backlog_merged": str(merged_path)}


def _ticker_quarter_key(row: dict[str, Any]) -> tuple[str, str]:
    return _ticker(row.get("ticker")), str(row.get("quarter") or "")


def _sample_id(row: Mapping[str, Any]) -> str:
    return f"{_ticker(row.get('ticker'))}_{row.get('quarter', '')}"


def _sec_reality_quarantine_reason(row: Mapping[str, Any]) -> str:
    status = str(row.get("coverage_status", "")).upper()
    if not status or status == "NEEDS_FETCH":
        return ""
    missing = {item for item in str(row.get("missing_inputs", "")).split(";") if item}
    notes = str(row.get("notes", ""))
    has_periodic = bool(row.get("periodic_accession") and row.get("periodic_form") and row.get("periodic_primary_document"))
    if "10q_10k_metadata" in missing or "foreign_issuer_or_no_domestic_10q_10k" in notes:
        return "missing_periodic_10q_10k"
    if status == "CACHED_READY" and not has_periodic:
        return "missing_periodic_10q_10k"
    return ""


def _llm_recoverable_reason(row: dict[str, Any]) -> bool:
    return str(row.get("llm_quarantine_reason") or "") in {
        "llm_evidence_missing",
        "missing_earnings_8k_or_press_release",
        "empty_evidence_docs",
    }


def _promote_llm_rows_with_cached_docs(
    eligible_rows: list[dict[str, Any]],
    llm_quarantine: list[dict[str, Any]],
    raw_docs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    doc_types_by_key: dict[tuple[str, str], set[str]] = {}
    for doc in raw_docs:
        doc_types_by_key.setdefault(_ticker_quarter_key(doc), set()).add(str(doc.get("document_type") or ""))

    recovered: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []
    status_rows: list[dict[str, Any]] = []
    for row in llm_quarantine:
        key = _ticker_quarter_key(row)
        doc_types = doc_types_by_key.get(key, set())
        can_recover = _llm_recoverable_reason(row) and {"primary_8k", "earnings_exhibit"} <= doc_types
        if can_recover:
            recovered.append({**row, "llm_eligible": 1, "llm_recovery_status": "recovered_from_sec_cache"})
            status_rows.append({**row, "llm_recovery_status": "recovered_from_sec_cache", "available_document_types": ";".join(sorted(doc_types))})
        else:
            remaining.append(row)
            if _llm_recoverable_reason(row):
                status_rows.append({**row, "llm_recovery_status": "still_missing", "available_document_types": ";".join(sorted(doc_types))})

    summary = {
        "llm_evidence_cache_recovered_count": len(recovered),
        "llm_evidence_still_missing_count": sum(1 for row in remaining if _llm_recoverable_reason(row)),
    }
    return [*eligible_rows, *recovered], remaining, summary, status_rows


def _blocking_llm_quarantine_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if str(row.get("llm_quarantine_reason") or "").strip() != "not_llm_required"
    ]


def _non_fetchable_no_earnings_evidence(row: Mapping[str, Any]) -> bool:
    if str(row.get("llm_quarantine_reason") or "") != "missing_earnings_8k_or_press_release":
        return False
    if str(row.get("missing_inputs") or "").strip():
        return False
    return "no_item_2_02_8k_using_periodic_only" in str(row.get("notes") or "")


def _coverage_proves_no_earnings_evidence(row: Mapping[str, Any]) -> bool:
    if str(row.get("earnings_8k_accession") or "").strip():
        return False
    if str(row.get("earnings_8k_primary_document") or "").strip():
        return False
    if str(row.get("earnings_exhibit_document") or "").strip():
        return False
    notes = str(row.get("notes") or "")
    if "no_item_2_02_8k_using_periodic_only" not in notes:
        return False
    missing = str(row.get("missing_inputs") or "").strip()
    if not missing:
        return True
    return str(row.get("coverage_status") or "").strip() == "BLOCKED_METADATA_OR_ISSUER_REALITY"


PRIOR_LLM_FIELDS = (
    "causal_change",
    "negative_revision_risk",
    "narrative_delta_bucket",
    "operating_leverage_quality",
    "durability",
    "proof_alignment",
    "post_llm_candidate_flag",
    "post_llm_high_priority_flag",
    "post_llm_demote_flag",
    "post_llm_demote_severity",
    "post_llm_demote_reason_code",
    "post_llm_demote_overrideable",
)


def _attach_prior_llm_extract(rows: list[dict[str, Any]], prior_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    prior_by_ticker = {_ticker(row.get("ticker")): row for row in prior_rows}
    output: list[dict[str, Any]] = []
    attached = 0
    missing = 0
    for raw in rows:
        row = dict(raw)
        prior = prior_by_ticker.get(_ticker(row.get("ticker"))) or {}
        if _has_llm_extract(prior):
            attached += 1
            available = {field: prior.get(field) for field in PRIOR_LLM_FIELDS if clean(prior.get(field)) != ""}
            for field, value in available.items():
                row[f"prior_llm_{field}"] = value
        else:
            missing += 1
        output.append(row)
    return output, {"prior_llm_extract_attached_count": attached, "prior_llm_extract_missing_count": missing}


def _has_llm_extract(row: Mapping[str, Any]) -> bool:
    return all(clean(row.get(field)) != "" for field in REQUIRED_LLM_FIELDS)


def _merge_prior_llm_from_post_rows(
    prior_rows: list[dict[str, Any]],
    post_rows: list[dict[str, Any]],
    *,
    expected_prior_quarter: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    post_by_ticker = {
        _ticker(row.get("ticker")): row
        for row in post_rows
        if str(row.get("quarter") or "") == expected_prior_quarter and _has_llm_extract(row)
    }
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    attached = 0
    for row in prior_rows:
        seen.add(_ticker(row.get("ticker")))
        post = post_by_ticker.get(_ticker(row.get("ticker")))
        if post:
            attached += 1
            merged.append({**row, **{field: post.get(field, row.get(field, "")) for field in PRIOR_LLM_FIELDS}})
        else:
            merged.append(row)
    for ticker, post in post_by_ticker.items():
        if ticker not in seen:
            attached += 1
            merged.append(post)
    return merged, {"prior_llm_extract_completed_from_post_file_count": attached}


def _prior_llm_missing_rows(
    rows: list[dict[str, Any]],
    prior_rows: list[dict[str, Any]],
    *,
    expected_prior_quarter: str,
    impossible_keys: set[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    impossible_keys = impossible_keys or set()
    prior_by_ticker = {
        _ticker(row.get("ticker")): row
        for row in prior_rows
        if str(row.get("quarter") or "") == expected_prior_quarter
    }
    missing: list[dict[str, Any]] = []
    for row in rows:
        key = (_ticker(row.get("ticker")), expected_prior_quarter)
        if key in impossible_keys:
            continue
        if not _has_llm_extract(prior_by_ticker.get(key[0], {})):
            missing.append(row)
    return missing


def _prior_recovery_candidate_rows(
    current_rows: list[dict[str, Any]],
    prior_rows: list[dict[str, Any]],
    *,
    expected_prior_quarter: str,
) -> list[dict[str, Any]]:
    prior_by_ticker = {_ticker(row.get("ticker")): row for row in prior_rows if str(row.get("quarter") or "") == expected_prior_quarter}
    identity_fields = ("ticker", "symbol", "cik", "cik_str", "company_title", "title", "company_name")
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for current in current_rows:
        ticker = _ticker(current.get("ticker"))
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        prior = prior_by_ticker.get(ticker)
        if prior:
            base = dict(prior)
            for key in identity_fields:
                current_value = current.get(key, "")
                if current_value and not str(base.get(key, "") or "").strip():
                    base[key] = current_value
        else:
            base = {
                key: current.get(key, "")
                for key in identity_fields
            }
        base["ticker"] = ticker
        base["quarter"] = expected_prior_quarter
        base["llm_eligible"] = 1
        base["llm_recovery_role"] = "prior_quarter_required_for_final_scoring"
        candidates.append(base)
    return candidates


def _build_prior_recovery_context_rows(
    *,
    candidates: list[dict[str, Any]],
    coverage_rows: list[dict[str, Any]],
    expected_prior_quarter: str,
    config: DailyRunConfig,
    live_root: Path,
    price_provider: Callable[..., list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    coverage_by_ticker = {_ticker(row.get("ticker")): row for row in coverage_rows}
    seed_rows: list[dict[str, Any]] = []
    for candidate in candidates:
        ticker = _ticker(candidate.get("ticker"))
        coverage = coverage_by_ticker.get(ticker, {})
        row = {**candidate, **coverage}
        row["ticker"] = ticker
        row["quarter"] = expected_prior_quarter
        row["tradable_date"] = row.get("tradable_date") or derive_tradable_date_from_coverage(row)
        seed_rows.append(row)
    pre_rows, pre_summary = build_pre_llm_from_companyfacts_cache(
        universe_rows=seed_rows,
        companyfacts_root=live_root / "companyfacts",
        quarter=expected_prior_quarter,
        fallback_root=sec_cache_root(),
    )
    priced_rows, price_quarantine, price_summary = attach_entry_prices(pre_rows, as_of=config.as_of, price_provider=price_provider)
    ready = [
        row
        for row in priced_rows
        if clean(row.get("entry_open"))
        and clean(row.get("pre_llm_fundamental_bucket")) != "not_scored"
        and clean(row.get("pre_llm_fundamental_score"))
    ]
    summary = {
        "prior_recovery_context_rows": len(priced_rows),
        "prior_recovery_context_ready_count": len(ready),
        "prior_recovery_context_missing_price_count": len(price_quarantine),
        "prior_recovery_context_missing_score_count": len(priced_rows) - len(ready) - len(price_quarantine),
        **{f"prior_recovery_context_{key}": value for key, value in pre_summary.items()},
        **{f"prior_recovery_context_{key}": value for key, value in price_summary.items()},
    }
    return priced_rows, price_quarantine, summary


def _merge_prior_recovery_context(
    prior_rows: list[dict[str, Any]],
    recovery_rows: list[dict[str, Any]],
    *,
    expected_prior_quarter: str,
) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {
        (_ticker(row.get("ticker")), str(row.get("quarter") or "")): dict(row)
        for row in prior_rows
    }
    for recovery in recovery_rows:
        key = (_ticker(recovery.get("ticker")), expected_prior_quarter)
        base = by_key.get(key, {})
        merged = dict(base)
        for field, value in recovery.items():
            if clean(value) and not clean(merged.get(field)):
                merged[field] = value
        merged["ticker"] = key[0]
        merged["quarter"] = key[1]
        by_key[key] = merged
    return list(by_key.values())


def _build_prior_llm_recovery_packets(
    *,
    missing_current_rows: list[dict[str, Any]],
    prior_rows: list[dict[str, Any]],
    expected_prior_quarter: str,
    config: DailyRunConfig,
    coverage_runner: Callable[..., dict[str, Any]],
    fetcher: Callable[..., dict[str, Any]],
    live_root: Path,
    price_provider: Callable[..., list[dict[str, Any]]],
    broad_universe_count: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, str]]:
    if not missing_current_rows:
        return [], [], [], [], {"prior_llm_recovery_needed_count": 0, "prior_llm_recovery_packet_count": 0}, {}

    candidates = _prior_recovery_candidate_rows(missing_current_rows, prior_rows, expected_prior_quarter=expected_prior_quarter)
    recovery_dir = config.output_root / "prior_llm_recovery"
    recovery_dir.mkdir(parents=True, exist_ok=True)
    universe_csv = recovery_dir / f"prior_llm_recovery_universe_{expected_prior_quarter}.csv"
    eligible_json = recovery_dir / f"prior_llm_recovery_tickers_{expected_prior_quarter}.json"
    write_csv(universe_csv, candidates)
    write_json_atomic(eligible_json, {"items": candidates, "count": len(candidates), "quarter": expected_prior_quarter, "type": "prior_llm_recovery"})

    coverage_raw = coverage_runner(
        out_root=recovery_dir,
        universe_csv=universe_csv,
        eligible_json=eligible_json,
        quarter=expected_prior_quarter,
        live_sec_root=live_root,
    )
    fetch_passes: list[dict[str, Any]] = []
    if not config.skip_fetch and int(coverage_raw.get("fetch_queue_count") or 0):
        pass_number = 0
        while int(coverage_raw.get("fetch_queue_count") or 0) and pass_number < max(1, int(config.max_sec_fetch_passes)):
            pass_number += 1
            before_count = int(coverage_raw.get("fetch_queue_count") or 0)
            fetch_manifest = fetcher(out_root=recovery_dir, live_sec_root=live_root)
            coverage_raw = coverage_runner(
                out_root=recovery_dir,
                universe_csv=universe_csv,
                eligible_json=eligible_json,
                quarter=expected_prior_quarter,
                live_sec_root=live_root,
            )
            fetch_passes.append({"pass": pass_number, "initial_fetch_queue_count": before_count, "post_fetch_queue_count": int(coverage_raw.get("fetch_queue_count") or 0), "fetch_manifest": fetch_manifest})

    coverage_csv = Path(coverage_raw.get("outputs", {}).get("manifest_csv", recovery_dir / f"sec_coverage_manifest_{expected_prior_quarter}.csv"))
    coverage_rows = _read_csv(coverage_csv)
    coverage_by_ticker = {_ticker(row.get("ticker")): row for row in coverage_rows}
    context_rows, context_price_quarantine, context_summary = _build_prior_recovery_context_rows(
        candidates=candidates,
        coverage_rows=coverage_rows,
        expected_prior_quarter=expected_prior_quarter,
        config=config,
        live_root=live_root,
        price_provider=price_provider,
    )
    impossible = [
        {**candidate, **coverage_by_ticker.get(_ticker(candidate.get("ticker")), {}), "prior_llm_recovery_status": "impossible_no_earnings_8k_or_press_release_found"}
        for candidate in candidates
        if _coverage_proves_no_earnings_evidence(coverage_by_ticker.get(_ticker(candidate.get("ticker")), {}))
    ]
    impossible_keys = {(_ticker(row.get("ticker")), expected_prior_quarter) for row in impossible}
    runnable_candidates = [candidate for candidate in candidates if (_ticker(candidate.get("ticker")), expected_prior_quarter) not in impossible_keys]
    docs = load_raw_documents_from_coverage(coverage_csv, live_root)
    recovery_guard_count = max(broad_universe_count, len(runnable_candidates) + 1)
    packets, empty_q, packet_summary = build_tier_filtered_llm_packets(runnable_candidates, docs, broad_universe_count=recovery_guard_count)
    packet_ids = {str(packet.get("sample_id") or "") for packet in packets}
    missing = [
        {**candidate, **coverage_by_ticker.get(_ticker(candidate.get("ticker")), {}), "prior_llm_recovery_status": "needs_evidence_or_llm_before_final_scoring"}
        for candidate in runnable_candidates
        if _sample_id(candidate) not in packet_ids
    ]
    impossible_path = recovery_dir / "prior_llm_impossible_no_filings.csv"
    missing_path = recovery_dir / "prior_llm_recovery_missing.csv"
    write_csv(impossible_path, impossible)
    write_csv(missing_path, missing)
    summary = {
        "prior_llm_recovery_needed_count": len(candidates),
        "prior_llm_recovery_packet_count": len(packets),
        "prior_llm_recovery_impossible_no_filings_count": len(impossible),
        "prior_llm_recovery_missing_evidence_count": len(missing),
        "prior_llm_recovery_fetch_pass_count": len(fetch_passes),
        "prior_llm_recovery_final_fetch_queue_count": int(coverage_raw.get("fetch_queue_count") or 0),
        "prior_llm_recovery_fetch_passes": fetch_passes,
        **context_summary,
        **{f"prior_llm_recovery_{key}": value for key, value in packet_summary.items()},
    }
    artifacts = {
        "prior_llm_recovery_universe": str(universe_csv),
        "prior_llm_recovery_manifest": str(coverage_csv),
        "prior_llm_impossible_no_filings": str(impossible_path),
        "prior_llm_recovery_missing": str(missing_path),
    }
    if context_price_quarantine:
        context_price_path = recovery_dir / "prior_llm_recovery_price_quarantine.csv"
        write_csv(context_price_path, context_price_quarantine)
        artifacts["prior_llm_recovery_price_quarantine"] = str(context_price_path)
    return packets, impossible, missing, context_rows, summary, artifacts


def _build_llm_packets_with_empty_evidence_recovery(
    *,
    eligible_rows: list[dict[str, Any]],
    raw_docs: list[dict[str, Any]],
    coverage_csv: Path,
    live_root: Path,
    broad_universe_count: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    packets, empty_q, summary = build_tier_filtered_llm_packets(eligible_rows, raw_docs, broad_universe_count=broad_universe_count)
    summary["empty_evidence_recovery_attempted"] = False
    summary["empty_evidence_count_before_recovery"] = len(empty_q)
    if not empty_q:
        summary["empty_evidence_count_after_recovery"] = 0
        return packets, empty_q, summary, raw_docs

    recovered_docs = load_raw_documents_from_coverage(coverage_csv, live_root)
    recovered_packets, recovered_empty_q, recovered_summary = build_tier_filtered_llm_packets(
        eligible_rows,
        recovered_docs,
        broad_universe_count=broad_universe_count,
    )
    recovered_summary.update(
        {
            "empty_evidence_recovery_attempted": True,
            "empty_evidence_count_before_recovery": len(empty_q),
            "empty_evidence_count_after_recovery": len(recovered_empty_q),
        }
    )
    return recovered_packets, recovered_empty_q, recovered_summary, recovered_docs


def _load_identity_json_rows(path: Path | None) -> list[dict[str, Any]]:
    try:
        return load_sec_ticker_rows(_load_json(path))
    except Exception:
        return []


def _load_trusted_panel_rows(path: Path | None) -> list[dict[str, Any]]:
    panel_path = path or DEFAULT_TRUSTED_PANEL_PATH
    if not panel_path.exists() or panel_path.stat().st_size == 0:
        return []
    if panel_path.suffix.lower() == ".csv":
        return _read_csv(panel_path)
    return _load_identity_json_rows(panel_path)


def _sec_direct_lookup_from_official_map() -> Callable[[str], Mapping[str, Any] | None]:
    ticker_map: dict[str, dict[str, Any]] | None = None

    def lookup(ticker: str) -> Mapping[str, Any] | None:
        nonlocal ticker_map
        canonical = _ticker(ticker)
        if not canonical:
            return None
        if ticker_map is None:
            from tradingagents.research.fundamental.src.ingest.cik import load_company_ticker_map

            ticker_map = load_company_ticker_map(refresh=True)
        row = ticker_map.get(canonical)
        if row:
            return row
        return {
            "ticker": canonical,
            "identity_status": "ticker_or_name_unresolved",
            "rejection_reason": "SEC direct ticker lookup returned no official ticker match",
        }

    return lookup


def _default_identity_resolver(
    config: DailyRunConfig,
    *,
    sec_direct_lookup: Callable[[str], Mapping[str, Any] | None] | None = None,
) -> Callable[[str], IdentityResolution]:
    sec_map_path = config.sec_ticker_map_path or sec_cache_root("sec_company_tickers.json")
    sec_rows = _load_identity_json_rows(sec_map_path)
    refreshed_rows = _load_identity_json_rows(config.identity_refreshed_sec_ticker_map_path)
    complete_panel_rows = _load_trusted_panel_rows(config.identity_complete_panel_path)
    direct_lookup = sec_direct_lookup if sec_direct_lookup is not None else (None if config.skip_fetch else _sec_direct_lookup_from_official_map())

    def resolver(ticker: str) -> IdentityResolution:
        canonical = _ticker(ticker)
        facts_path = sec_cache_root(f"facts_{canonical}.json")
        facts: dict[str, dict[str, Any]] = {}
        if facts_path.exists():
            try:
                facts[canonical] = json.loads(facts_path.read_text(encoding="utf-8"))
            except Exception:
                facts = {}
        return resolve_ticker_identity(
            canonical,
            local_sec_ticker_rows=sec_rows,
            refreshed_sec_ticker_rows=refreshed_rows,
            complete_panel_rows=complete_panel_rows,
            local_sec_facts=facts,
            sec_direct_lookup=direct_lookup,
        )

    return resolver


def _resolve_new_dealflow_identities(
    *,
    config: DailyRunConfig,
    active_master_universe_path: Path,
    active_handoff_path: Path | None,
    resolver: Callable[[str], IdentityResolution],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, str]]:
    master_tickers = _master_tickers(active_master_universe_path)
    scout_tickers = _handoff_tickers(active_handoff_path)
    new_tickers = [ticker for ticker in scout_tickers if ticker not in master_tickers]
    resolved: dict[str, dict[str, Any]] = {}
    rejected: dict[str, dict[str, Any]] = {}
    resolution_rows: list[dict[str, Any]] = []
    additions: list[dict[str, Any]] = []
    for ticker in new_tickers:
        result = resolver(ticker)
        row = result.as_row()
        row["quarter"] = config.quarter
        row["source_status"] = "today_dealflow_add"
        resolution_rows.append(row)
        if result.cik and result.company_title and result.identity_status.startswith("resolved_"):
            resolved[result.ticker] = {
                **row,
                "ticker": result.ticker,
                "symbol": result.ticker,
                "cik_status": "resolved",
                "master_universe_source": "daily_scout_append",
            }
            additions.append(resolved[result.ticker])
        else:
            rejected[result.ticker or ticker] = row
    artifacts: dict[str, str] = {}
    resolution_path = config.output_root / "dealflow_identity_resolution.csv"
    rejection_path = config.output_root / "dealflow_identity_rejections.csv"
    pending_path = config.output_root / f"master_fundamental_universe_additions_pending_{config.quarter}.json"
    write_csv(resolution_path, resolution_rows)
    write_csv(rejection_path, list(rejected.values()))
    write_json_atomic(pending_path, {"items": additions, "count": len(additions), "quarter": config.quarter})
    artifacts.update({
        "dealflow_identity_resolution": str(resolution_path),
        "dealflow_identity_rejections": str(rejection_path),
        "master_additions_pending": str(pending_path),
    })
    return resolved, rejected, artifacts


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

    def provider(tickers, *, start, end, required_start_by_ticker=None):
        rows = load_cached_review_price_rows([cache_path], tickers=[str(ticker).upper() for ticker in tickers], start=start, end=end)
        if not required_start_by_ticker:
            return rows
        required = {_ticker(ticker): str(value)[:10] for ticker, value in required_start_by_ticker.items() if _ticker(ticker)}
        return [row for row in rows if str(row.get("date") or "")[:10] >= required.get(_ticker(row.get("ticker")), start)]

    return provider


def _cache_first_price_provider(
    config: DailyRunConfig,
    price_provider: Callable[..., list[dict[str, Any]]],
    summary: dict[str, Any],
    artifacts: dict[str, str],
) -> Callable[..., list[dict[str, Any]]]:
    cache_path = config.review_price_cache_path or market_cache_root()

    def provider(tickers, *, start, end, required_start_by_ticker=None):
        result = load_or_fetch_price_rows(
            [str(ticker).upper() for ticker in tickers],
            start=start,
            end=end,
            cache_paths=[cache_path, config.output_root],
            price_provider=price_provider,
            output_root=config.output_root,
            quarter=config.quarter,
            as_of=config.as_of,
            batch_size=config.review_price_batch_size,
            allow_live_fetch=bool(config.review_allow_live_price_fetch),
            shared_cache_root=market_cache_root(),
            required_start_by_ticker=required_start_by_ticker,
        )
        summary.clear()
        summary.update(result.summary)
        artifacts.clear()
        artifacts.update(result.artifacts)
        return result.rows

    return provider


def run_daily_fundamental(config: DailyRunConfig, services: DailyRunServices | None = None) -> DailyRunResult:
    services = services or DailyRunServices()
    run_price_provider = services.price_provider
    if config.build_review_list_from_sec and not config.review_allow_live_price_fetch:
        run_price_provider = _cached_review_price_provider(config)
    daily_price_summary: dict[str, Any] = {}
    daily_price_artifacts: dict[str, str] = {}
    scoring_price_provider = _cache_first_price_provider(config, run_price_provider, daily_price_summary, daily_price_artifacts)
    existing_manifest = config.output_root / "run_manifest.json"
    if existing_manifest.exists():
        try:
            prior = json.loads(existing_manifest.read_text(encoding="utf-8"))
        except Exception:
            prior = {}
        if prior.get("final") is True:
            blocked = {"reason": "output_root_contains_prior_final_run", "existing_manifest": str(existing_manifest)}
            gate = GateResult(1, "Run identity and immutable snapshot", GateStatus.HARD_STOP, blocked, {})
            return DailyRunResult([gate], {"final": False, "stopped": str(blocked), "artifacts": gate.artifacts}, gate.artifacts)

    config.output_root.mkdir(parents=True, exist_ok=True)
    state = DailyRunState(config=config, run_id=f"daily_{uuid4().hex[:12]}")
    try:
        expected_quarter = current_quarter(date.fromisoformat(config.as_of))
        date_quarter_mismatch = expected_quarter != config.quarter
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
        if date_quarter_mismatch and config.run_mode == RunMode.BROAD_MASTER_FINAL and not config.allow_date_quarter_mismatch:
            _record(state, GateResult(1, "Run identity and immutable snapshot", GateStatus.HARD_STOP, {"reason": "date_quarter_mismatch", "expected_quarter": expected_quarter, "provided_quarter": config.quarter, "as_of": config.as_of}, {"run_identity": str(identity_path), **{f"snapshot_{k}": v for k, v in snapshots.items()}}))
        else:
            _record(state, GateResult(1, "Run identity and immutable snapshot", GateStatus.PASS, identity, {"run_identity": str(identity_path), **{f"snapshot_{k}": v for k, v in snapshots.items()}}))

        live_root = config.sec_live_root or sec_cache_root("live_sec")
        if services.run_coverage is None:
            def coverage_runner(*, out_root, universe_csv, eligible_json, quarter, live_sec_root):
                return run_sec_coverage_manifest(out_root=out_root, universe_csv=universe_csv, eligible_json=eligible_json, quarter=quarter, live_sec_root=live_sec_root, as_of=config.as_of)
        else:
            coverage_runner = services.run_coverage
        active_master_universe_path = config.master_universe_path
        active_handoff_path = config.handoff_path
        dealflow_backlog_summary: dict[str, Any] = {}
        dealflow_backlog_artifacts: dict[str, str] = {}
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

        if active_master_universe_path is None:
            active_master_universe_path = materialize_master_universe(output_root=config.output_root)
        if not active_master_universe_path.exists():
            _record(state, GateResult(2, "Universe construction and drift control", GateStatus.HARD_STOP, {"reason": "missing_master_universe_path"}, {}))
        handoff_missing = active_handoff_path is None or not Path(active_handoff_path).exists()
        if config.run_mode == RunMode.BROAD_MASTER_FINAL and handoff_missing and not config.allow_missing_handoff:
            _record(state, GateResult(2, "Universe construction and drift control", GateStatus.HARD_STOP, {"reason": "missing_daily_handoff", "handoff_missing": True, "handoff_policy": "required_for_broad_final"}, {}))
        if config.run_mode == RunMode.SCOUT_SMOKE and handoff_missing and not config.allow_missing_handoff:
            _record(state, GateResult(2, "Universe construction and drift control", GateStatus.HARD_STOP, {"reason": "missing_daily_handoff", "handoff_missing": True, "handoff_policy": "required_for_scout_smoke_unless_allowed"}, {}))
        if not handoff_missing and not config.build_review_list_from_sec:
            active_handoff_path, dealflow_backlog_summary, dealflow_backlog_artifacts = _materialize_handoff_backlog(config, active_handoff_path)
            state.artifacts.update(dealflow_backlog_artifacts)
        identity_resolved: dict[str, dict[str, Any]] = {}
        identity_rejected: dict[str, dict[str, Any]] = {}
        identity_artifacts: dict[str, str] = {}
        if not handoff_missing and active_master_universe_path is not None and not config.build_review_list_from_sec:
            identity_resolved, identity_rejected, identity_artifacts = _resolve_new_dealflow_identities(
                config=config,
                active_master_universe_path=active_master_universe_path,
                active_handoff_path=active_handoff_path,
                resolver=services.resolve_identity or _default_identity_resolver(config, sec_direct_lookup=services.sec_direct_lookup),
            )
            state.artifacts.update(identity_artifacts)
        universe_csv = config.output_root / f"master_fundamental_universe_{config.quarter}.csv"
        try:
            universe = build_combined_universe(
                master_universe_path=active_master_universe_path,
                handoff_path=active_handoff_path if not handoff_missing else None,
                quarter=config.quarter,
                output_csv=universe_csv,
                unresolved_new_scouts=identity_resolved,
                rejected_new_scouts=identity_rejected,
            )
        except ValueError as exc:
            _record(state, GateResult(2, "Universe construction and drift control", GateStatus.HARD_STOP, {"reason": "invalid_master_universe_format", "error": str(exc)}, {}))
        universe.artifacts.update(identity_artifacts)
        universe.artifacts.update(review_filter_artifacts)
        universe.artifacts.update(dealflow_backlog_artifacts)
        master_snapshot_path = config.output_root / f"master_fundamental_universe_{config.quarter}.json"
        write_json_atomic(
            master_snapshot_path,
            {
                "items": universe.rows,
                "count": len(universe.rows),
                "quarter": config.quarter,
                "type": "combined_master_for_daily_run",
            },
        )
        universe.artifacts["master_universe_current_quarter_snapshot"] = str(master_snapshot_path)
        active_master_universe_path = master_snapshot_path
        universe_gate = validate_universe_gate(universe.rows, run_mode=config.run_mode, scout_count=int(universe.summary.get("scout_count", 0)), min_broad_universe_count=config.min_broad_universe_count, artifacts=universe.artifacts)
        universe_gate.summary["identity_resolved_new_count"] = len(identity_resolved)
        universe_gate.summary["identity_rejected_new_count"] = len(identity_rejected)
        if handoff_missing:
            universe_gate.summary["handoff_missing"] = True
            universe_gate.summary["handoff_policy"] = "allowed_missing" if config.allow_missing_handoff or config.run_mode == RunMode.DIAGNOSTIC_ONLY else "present"
        if review_filter_summary:
            universe_gate.summary["review_list_filter"] = review_filter_summary
        if dealflow_backlog_summary:
            universe_gate.summary.update(dealflow_backlog_summary)
        _record(state, universe_gate)
        daily_status_path = config.output_root / "daily_ticker_status.csv"
        write_daily_status(
            daily_status_path,
            quarter=config.quarter,
            universe_rows=universe.rows,
            identity_rejections=identity_rejected.values(),
        )
        state.artifacts["daily_ticker_status"] = str(daily_status_path)

        companyfacts_fallback_summary = materialize_companyfacts_fallbacks(
            universe_rows=universe.rows,
            companyfacts_root=live_root / "companyfacts",
            fallback_root=sec_cache_root(),
        )
        companyfacts_fallback_path = config.output_root / "companyfacts_fallback_summary.json"
        write_json_atomic(companyfacts_fallback_path, companyfacts_fallback_summary)
        state.artifacts["companyfacts_fallback_summary"] = str(companyfacts_fallback_path)
        coverage_raw = coverage_runner(out_root=config.output_root, universe_csv=universe_csv, eligible_json=active_master_universe_path, quarter=config.quarter, live_sec_root=live_root)
        companyfacts_ready = len(universe.rows) - int((coverage_raw.get("missing_input_counts", {}) or {}).get("companyfacts", 0))
        coverage_summary = normalize_coverage_summary(coverage_raw, universe_count=len(universe.rows), companyfacts_ready_count=companyfacts_ready)
        coverage_summary.update(companyfacts_fallback_summary)
        _record(state, coverage_gate_result(coverage_summary, artifact_paths=coverage_summary.get("outputs", {})))

        if not config.skip_fetch and coverage_summary["fetch_queue_count"]:
            fetcher = services.run_fetch_once or run_sec_fetch_once
            fetch_passes: list[dict[str, Any]] = []
            initial_fetch_queue = coverage_summary["fetch_queue_count"]
            pass_number = 0
            pre_fetch_alias_summary = materialize_alias_documents_from_queue(out_root=config.output_root, live_sec_root=live_root)
            if int(pre_fetch_alias_summary.get("alias_document_materialized_count") or 0):
                coverage_raw = coverage_runner(out_root=config.output_root, universe_csv=universe_csv, eligible_json=active_master_universe_path, quarter=config.quarter, live_sec_root=live_root)
                companyfacts_ready = len(universe.rows) - int((coverage_raw.get("missing_input_counts", {}) or {}).get("companyfacts", 0))
                coverage_summary = normalize_coverage_summary(coverage_raw, universe_count=len(universe.rows), companyfacts_ready_count=companyfacts_ready)
                coverage_summary.update(companyfacts_fallback_summary)
            while coverage_summary["fetch_queue_count"] and pass_number < max(1, int(config.max_sec_fetch_passes)):
                pass_number += 1
                before_fetch_queue = coverage_summary["fetch_queue_count"]
                fetch_manifest = fetcher(out_root=config.output_root, live_sec_root=live_root)
                alias_summary = materialize_alias_documents_from_queue(out_root=config.output_root, live_sec_root=live_root)
                coverage_raw = coverage_runner(out_root=config.output_root, universe_csv=universe_csv, eligible_json=active_master_universe_path, quarter=config.quarter, live_sec_root=live_root)
                companyfacts_ready = len(universe.rows) - int((coverage_raw.get("missing_input_counts", {}) or {}).get("companyfacts", 0))
                coverage_summary = normalize_coverage_summary(coverage_raw, universe_count=len(universe.rows), companyfacts_ready_count=companyfacts_ready)
                coverage_summary.update(companyfacts_fallback_summary)
                fetch_passes.append({"pass": pass_number, "initial_fetch_queue_count": before_fetch_queue, "post_fetch_queue_count": coverage_summary["fetch_queue_count"], "fetch_manifest": fetch_manifest, "alias_materialization": alias_summary})
            gate_status = GateStatus.HARD_STOP if coverage_summary["fetch_queue_count"] else GateStatus.PASS
            reason = "fetch_queue_remaining_after_max_passes" if coverage_summary["fetch_queue_count"] else "fetch_queue_drained"
            _record(state, GateResult(4, "Fetch and materialization", gate_status, {"initial_fetch_queue_count": initial_fetch_queue, "final_fetch_queue_count": coverage_summary["fetch_queue_count"], "fetch_pass_count": len(fetch_passes), "max_sec_fetch_passes": config.max_sec_fetch_passes, "reason": reason, "pre_fetch_alias_materialization": pre_fetch_alias_summary, "fetch_passes": fetch_passes}, coverage_summary.get("outputs", {})))
        else:
            _record(state, GateResult(4, "Fetch and materialization", GateStatus.PASS, {"fetch_queue_count": coverage_summary["fetch_queue_count"], "reason": "no_fetchable_queue_or_skip_fetch"}, {}))

        coverage_csv = Path(coverage_raw.get("outputs", {}).get("manifest_csv", config.output_root / f"sec_coverage_manifest_{config.quarter}.csv"))
        coverage_rows = _read_csv(coverage_csv)
        coverage_by_key = {(r.get("ticker", "").upper(), r.get("quarter", "")): r for r in coverage_rows}
        scoring_seed_rows = [
            {**row, **coverage_by_key.get((row.get("ticker", "").upper(), row.get("quarter", config.quarter)), {})}
            for row in universe.rows
        ]
        pre_rows, pre_summary = build_pre_llm_from_companyfacts_cache(universe_rows=scoring_seed_rows, companyfacts_root=live_root / "companyfacts", quarter=config.quarter, fallback_root=sec_cache_root())
        pre_path = config.output_root / "pre_llm_scores.csv"; write_csv(pre_path, pre_rows)
        _record(state, GateResult(5, "Pre-LLM scoring readiness", GateStatus.PASS, pre_summary, {"pre_llm_scores": str(pre_path)}))

        pre_with_dates = []
        sec_reality_quarantine = []
        for row in pre_rows:
            cov = coverage_by_key.get((row.get("ticker", "").upper(), row.get("quarter", "")), {})
            merged = {**row, **cov, "tradable_date": row.get("tradable_date") or derive_tradable_date_from_coverage(cov)}
            reason = _sec_reality_quarantine_reason(cov)
            if reason:
                sec_reality_quarantine.append({**merged, "score_input_quarantine_reason": reason})
            else:
                pre_with_dates.append(merged)
        priced_rows, price_quarantine, price_summary = attach_entry_prices(pre_with_dates, as_of=config.as_of, price_provider=scoring_price_provider)
        price_ready_rows = [r for r in priced_rows if r.get("entry_open")]
        score_ready_rows, score_input_quarantine, score_input_summary = split_score_ready_rows(price_ready_rows)
        score_input_quarantine = sec_reality_quarantine + score_input_quarantine
        score_input_summary["score_input_quarantine_count"] = len(score_input_quarantine)
        score_input_summary["sec_reality_quarantine_count"] = len(sec_reality_quarantine)
        score_input_summary["sec_reality_quarantine_tickers"] = [_ticker(row.get("ticker")) for row in sec_reality_quarantine[:50]]
        price_q_path = config.output_root / "entry_price_quarantine.csv"; write_csv(price_q_path, price_quarantine)
        score_q_path = config.output_root / "score_input_quarantine.csv"; write_csv(score_q_path, score_input_quarantine)
        price_status = GateStatus.PASS
        write_daily_status(
            daily_status_path,
            quarter=config.quarter,
            universe_rows=universe.rows,
            identity_rejections=identity_rejected.values(),
            coverage_rows=coverage_rows,
            pre_rows=pre_rows,
            price_quarantine=price_quarantine,
            score_input_quarantine=score_input_quarantine,
        )
        state.artifacts.update(daily_price_artifacts)
        _record(state, GateResult(6, "Trade date, price, and entry-open", price_status, {**price_summary, **daily_price_summary, **score_input_summary, "tier_input_rows": len(score_ready_rows), "reason": "price_quarantine_recorded" if price_quarantine else ""}, {"entry_price_quarantine": str(price_q_path), "score_input_quarantine": str(score_q_path), **daily_price_artifacts}))

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
        llm_recovery_summary: dict[str, Any] = {"llm_evidence_fetch_recovery_attempted": False}
        llm_recovery_artifacts: dict[str, str] = {}
        recoverable_before_fetch = [row for row in llm_quarantine if _llm_recoverable_reason(row)]
        fetch_queue_path = config.output_root / "sec_fetch_queue_resumable.json"
        can_run_fetch_recovery = bool(services.run_fetch_once) or fetch_queue_path.exists()
        if recoverable_before_fetch and not config.skip_fetch and can_run_fetch_recovery:
            fetcher = services.run_fetch_once or run_sec_fetch_once
            fetch_manifest = fetcher(out_root=config.output_root, live_sec_root=live_root)
            coverage_raw = coverage_runner(out_root=config.output_root, universe_csv=universe_csv, eligible_json=active_master_universe_path, quarter=config.quarter, live_sec_root=live_root)
            coverage_csv = Path(coverage_raw.get("outputs", {}).get("manifest_csv", config.output_root / f"sec_coverage_manifest_{config.quarter}.csv"))
            coverage_rows = _read_csv(coverage_csv)
            eligible_rows, llm_quarantine, eligibility_summary = build_llm_eligibility(tiered_rows, coverage_rows)
            recoverable_after_fetch = [row for row in llm_quarantine if _llm_recoverable_reason(row)]
            llm_recovery_summary.update(
                {
                    "llm_evidence_fetch_recovery_attempted": True,
                    "llm_evidence_fetch_manifest": fetch_manifest,
                    "llm_evidence_missing_before_fetch": len(recoverable_before_fetch),
                    "llm_evidence_missing_after_fetch": len(recoverable_after_fetch),
                }
            )
        elif recoverable_before_fetch:
            llm_recovery_summary.update(
                {
                    "llm_evidence_missing_before_fetch": len(recoverable_before_fetch),
                    "llm_evidence_fetch_skip_reason": "skip_fetch_enabled" if config.skip_fetch else "no_sec_fetch_queue",
                }
            )
        raw_docs = load_raw_documents_from_coverage(coverage_csv, live_root)
        eligible_rows, llm_quarantine, cache_recovery_summary, recovery_status_rows = _promote_llm_rows_with_cached_docs(eligible_rows, llm_quarantine, raw_docs)
        non_fetchable_llm_rejections = [row for row in llm_quarantine if _non_fetchable_no_earnings_evidence(row)]
        if non_fetchable_llm_rejections:
            rejected_keys = {_ticker_quarter_key(row) for row in non_fetchable_llm_rejections}
            llm_quarantine = [row for row in llm_quarantine if _ticker_quarter_key(row) not in rejected_keys]
            tiered_rows = [row for row in tiered_rows if _ticker_quarter_key(row) not in rejected_keys]
            score_input_quarantine.extend(
                {**row, "score_input_quarantine_reason": "no_earnings_8k_or_press_release_found"}
                for row in non_fetchable_llm_rejections
            )
            score_input_summary["score_input_quarantine_count"] = len(score_input_quarantine)
            write_csv(score_q_path, score_input_quarantine)
        eligibility_summary.update({"llm_eligible_count": len(eligible_rows), "llm_quarantine_count": len(llm_quarantine)})
        llm_recovery_summary.update(cache_recovery_summary)
        tier_path = config.output_root / "tier_classification.csv"
        llm_eligibility_path = config.output_root / "llm_eligibility.csv"
        llm_quarantine_path = config.output_root / "llm_quarantine.csv"
        llm_recovery_status_path = config.output_root / "llm_evidence_recovery_status.csv"
        llm_recovery_summary_path = config.output_root / "llm_evidence_recovery_summary.json"
        write_csv(tier_path, tiered_rows)
        write_csv(llm_quarantine_path, llm_quarantine)
        write_csv(llm_recovery_status_path, recovery_status_rows)
        write_json_atomic(llm_recovery_summary_path, llm_recovery_summary)
        llm_recovery_artifacts.update({"llm_evidence_recovery_status": str(llm_recovery_status_path), "llm_evidence_recovery_summary": str(llm_recovery_summary_path)})
        write_daily_status(
            daily_status_path,
            quarter=config.quarter,
            universe_rows=universe.rows,
            identity_rejections=identity_rejected.values(),
            coverage_rows=coverage_rows,
            pre_rows=pre_rows,
            price_quarantine=price_quarantine,
            score_input_quarantine=score_input_quarantine,
            llm_eligible_rows=eligible_rows,
            llm_quarantine=llm_quarantine,
        )
        blocking_llm_quarantine = _blocking_llm_quarantine_rows(llm_quarantine)
        expected_prior_quarter = str(prior_summary.get("expected_prior_quarter") or prior_quarter(config.quarter))
        eligible_rows, prior_llm_summary = _attach_prior_llm_extract(eligible_rows, prior_rows)
        prior_context_valid = bool(prior_summary.get("prior_context_loaded")) and not prior_summary.get("prior_duplicate_key_count") and bool(prior_summary.get("expected_prior_context_rows"))
        prior_missing_for_recovery = _prior_llm_missing_rows(eligible_rows, prior_rows, expected_prior_quarter=expected_prior_quarter) if prior_context_valid else []
        prior_recovery_packets: list[dict[str, Any]] = []
        prior_recovery_impossible: list[dict[str, Any]] = []
        prior_recovery_missing: list[dict[str, Any]] = []
        prior_recovery_context_rows: list[dict[str, Any]] = []
        prior_recovery_summary: dict[str, Any] = {"prior_llm_recovery_needed_count": len(prior_missing_for_recovery), "prior_llm_recovery_packet_count": 0}
        prior_recovery_artifacts: dict[str, str] = {}
        if prior_missing_for_recovery and not blocking_llm_quarantine:
            prior_recovery_packets, prior_recovery_impossible, prior_recovery_missing, prior_recovery_context_rows, prior_recovery_summary, prior_recovery_artifacts = _build_prior_llm_recovery_packets(
                missing_current_rows=prior_missing_for_recovery,
                prior_rows=prior_rows,
                expected_prior_quarter=expected_prior_quarter,
                config=config,
                coverage_runner=coverage_runner,
                fetcher=services.run_fetch_once or run_sec_fetch_once,
                live_root=live_root,
                price_provider=scoring_price_provider,
                broad_universe_count=len(universe.rows),
            )
            llm_recovery_artifacts.update(prior_recovery_artifacts)
        prior_llm_impossible_keys = {(_ticker(row.get("ticker")), expected_prior_quarter) for row in prior_recovery_impossible}
        write_csv(llm_eligibility_path, eligible_rows)
        gate7_summary = {**tier_summary, **eligibility_summary, **pre_tier_qoq_summary, **llm_recovery_summary, **prior_llm_summary}
        gate7_summary.update(prior_recovery_summary)
        gate7_summary.update(
            {
                "llm_eligible_qoq_context_match_rows": _qoq_match_count(eligible_rows),
                "llm_required_quarantine_count": len(blocking_llm_quarantine),
                "llm_required_quarantine_tickers": sorted({_ticker(row.get("ticker")) for row in blocking_llm_quarantine})[:50],
                "non_fetchable_llm_evidence_rejection_count": len(non_fetchable_llm_rejections),
                "non_fetchable_llm_evidence_rejection_tickers": sorted({_ticker(row.get("ticker")) for row in non_fetchable_llm_rejections})[:50],
            }
        )
        gate7_status = GateStatus.PASS
        if config.run_mode == RunMode.BROAD_MASTER_FINAL and blocking_llm_quarantine:
            gate7_status = GateStatus.HARD_STOP
            gate7_summary["reason"] = "llm_required_rows_still_missing_evidence"
        _record(state, GateResult(7, "Tier 0-4 and LLM eligibility", gate7_status, gate7_summary, {"tier_classification": str(tier_path), "llm_eligibility": str(llm_eligibility_path), "llm_quarantine": str(llm_quarantine_path), **llm_recovery_artifacts}))

        packets, empty_q, packet_summary, raw_docs = _build_llm_packets_with_empty_evidence_recovery(
            eligible_rows=eligible_rows,
            raw_docs=raw_docs,
            coverage_csv=coverage_csv,
            live_root=live_root,
            broad_universe_count=len(universe.rows),
        )
        current_packet_count = int(packet_summary.get("packet_count") or 0)
        current_eligible_count = int(packet_summary.get("eligible_count") or 0)
        packets = [*packets, *prior_recovery_packets]
        packet_summary.update(
            {
                "current_packet_count": current_packet_count,
                "current_eligible_count": current_eligible_count,
                "prior_llm_recovery_packet_count": len(prior_recovery_packets),
                "prior_llm_recovery_missing_evidence_count": len(prior_recovery_missing),
                "prior_llm_recovery_impossible_no_filings_count": len(prior_recovery_impossible),
                "packet_count": len(packets),
                "eligible_count": current_eligible_count + len(prior_recovery_packets),
            }
        )
        packet_path = config.output_root / "lake" / "artifacts" / f"{config.quarter}_llm_packets.jsonl"
        write_text_atomic(packet_path, "\n".join(json.dumps(p, sort_keys=True) for p in packets))
        empty_q_path = config.output_root / "llm_empty_evidence_quarantine.csv"; write_csv(empty_q_path, empty_q)
        write_daily_status(
            daily_status_path,
            quarter=config.quarter,
            universe_rows=universe.rows,
            identity_rejections=identity_rejected.values(),
            coverage_rows=coverage_rows,
            pre_rows=pre_rows,
            price_quarantine=price_quarantine,
            score_input_quarantine=score_input_quarantine,
            llm_eligible_rows=eligible_rows,
            llm_quarantine=llm_quarantine,
            packet_rows=packets,
            packet_quarantine=empty_q,
        )
        post_llm_path: Path | None = None
        if packet_summary["empty_evidence_count"]:
            _record(state, GateResult(8, "LLM packet, extraction, and validation", GateStatus.HARD_STOP, {**packet_summary, "reason": "eligible_rows_missing_non_empty_evidence"}, {"llm_packets": str(packet_path), "llm_empty_evidence_quarantine": str(empty_q_path)}))
        if current_packet_count != current_eligible_count:
            _record(state, GateResult(8, "LLM packet, extraction, and validation", GateStatus.HARD_STOP, {**packet_summary, "reason": "packet_count_mismatch"}, {"llm_packets": str(packet_path)}))
        if prior_recovery_missing and config.run_mode == RunMode.BROAD_MASTER_FINAL and not config.skip_llm:
            _record(state, GateResult(8, "LLM packet, extraction, and validation", GateStatus.HARD_STOP, {**packet_summary, "reason": "prior_llm_recovery_missing_evidence", "prior_llm_recovery_missing_tickers": sorted({_ticker(row.get("ticker")) for row in prior_recovery_missing})[:50]}, {"llm_packets": str(packet_path), "llm_empty_evidence_quarantine": str(empty_q_path), **prior_recovery_artifacts}))
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
                _record(state, GateResult(8, "LLM packet, extraction, and validation", GateStatus.HARD_STOP, {**packet_summary, "completed_count": 0, "reason": reason}, artifacts))
            validation_gate = validate_post_llm_csv(post_llm_path, expected_sample_ids={p["sample_id"] for p in packets})
            validation_gate.summary = {**packet_summary, **validation_gate.summary}
            validation_gate.artifacts.update({"llm_packets": str(packet_path), "llm_empty_evidence_quarantine": str(empty_q_path)})
            _record(state, validation_gate)

        post_rows = _read_csv(post_llm_path) if post_llm_path else []
        if post_rows:
            cache_summary = save_llm_rows_to_cache(post_rows)
            state.artifacts["llm_shared_cache"] = str(cache_summary.get("llm_cache_path", ""))
        prior_rows_with_recovery_context = _merge_prior_recovery_context(
            prior_rows,
            prior_recovery_context_rows,
            expected_prior_quarter=expected_prior_quarter,
        )
        prior_rows_for_final, prior_post_summary = _merge_prior_llm_from_post_rows(prior_rows_with_recovery_context, post_rows, expected_prior_quarter=expected_prior_quarter)
        final_prior_missing = _prior_llm_missing_rows(
            eligible_rows,
            prior_rows_for_final,
            expected_prior_quarter=expected_prior_quarter,
            impossible_keys=prior_llm_impossible_keys,
        ) if prior_context_valid else []
        if final_prior_missing and config.run_mode == RunMode.BROAD_MASTER_FINAL and not config.skip_llm:
            prior_block_path = config.output_root / "prior_llm_final_blockers.csv"
            write_csv(prior_block_path, final_prior_missing)
            _record(
                state,
                GateResult(
                    9,
                    "Final scoring, HP buckets, RM buckets, and QoQ context",
                    GateStatus.HARD_STOP,
                    {
                        **prior_summary,
                        **prior_post_summary,
                        "reason": "prior_llm_extract_required_for_final_scoring",
                        "prior_llm_extract_missing_for_final_count": len(final_prior_missing),
                        "prior_llm_extract_missing_for_final_tickers": sorted({_ticker(row.get("ticker")) for row in final_prior_missing})[:50],
                        "prior_llm_extract_impossible_no_filings_count": len(prior_recovery_impossible),
                    },
                    {"prior_llm_final_blockers": str(prior_block_path), **prior_recovery_artifacts},
                ),
            )
        prior_impossible_tickers = sorted({_ticker(row.get("ticker")) for row in prior_recovery_impossible})
        final_rows, final_summary = build_final_scores(
            tiered_rows,
            as_of=config.as_of,
            post_llm_rows=post_rows,
            prior_context_rows=prior_rows_for_final,
            allowed_missing_qoq_tickers=set(prior_impossible_tickers),
        )
        final_summary["llm_eligible_qoq_context_match_rows"] = _qoq_match_count(
            [row for row in final_rows if clean(row.get("llm_status")) == "complete"]
        )
        final_summary = {
            **final_summary,
            **prior_summary,
            **prior_post_summary,
            "prior_llm_extract_impossible_no_filings_count": len(prior_recovery_impossible),
            "prior_llm_extract_impossible_no_filings_tickers": prior_impossible_tickers[:50],
        }
        final_path = config.output_root / f"fundamental_final_scores_{config.as_of}.csv"
        final_artifacts = write_final_scores_csv(final_path, final_rows, final_summary)
        write_daily_status(
            daily_status_path,
            quarter=config.quarter,
            universe_rows=universe.rows,
            identity_rejections=identity_rejected.values(),
            coverage_rows=coverage_rows,
            pre_rows=pre_rows,
            price_quarantine=price_quarantine,
            score_input_quarantine=score_input_quarantine,
            llm_eligible_rows=eligible_rows,
            llm_quarantine=llm_quarantine,
            packet_rows=packets,
            packet_quarantine=empty_q,
            post_llm_rows=post_rows,
            final_rows=final_rows,
        )
        final_artifacts["daily_ticker_status"] = str(daily_status_path)
        explicit_invalid_quarantine_count = len(price_quarantine) + len(score_input_quarantine)
        _record(
            state,
            validate_broad_final_scores(
                final_rows=final_rows,
                broad_universe_count=len(universe.rows),
                explicit_invalid_quarantine_count=explicit_invalid_quarantine_count,
                run_mode=config.run_mode,
                artifacts=final_artifacts,
                prior_context_summary={
                    **prior_summary,
                    "qoq_context_match_rows": final_summary.get("qoq_context_match_rows", 0),
                    "qoq_context_input_rows": final_summary.get("qoq_context_input_rows", 0),
                    "llm_eligible_qoq_context_match_rows": final_summary.get("llm_eligible_qoq_context_match_rows", 0),
                    "prior_llm_extract_impossible_no_filings_tickers": final_summary.get("prior_llm_extract_impossible_no_filings_tickers", []),
                },
            ),
        )

        if config.run_mode == RunMode.BROAD_MASTER_FINAL and not config.skip_llm:
            publish_gate = (services.publish or publish_top15_and_shadow)(scores_csv=final_path, output_root=config.output_root, as_of=config.as_of, broad_universe_count=len(universe.rows), explicit_invalid_quarantine_count=explicit_invalid_quarantine_count, coverage_manifest=coverage_csv if coverage_csv.exists() else None)
            _record(state, publish_gate)
            _write_operator_final_bundle(state, publish_gate)
            if identity_resolved:
                final_tickers = {_ticker(row.get("ticker")) for row in final_rows}
                scored_additions = [
                    row
                    for ticker, row in identity_resolved.items()
                    if _ticker(ticker) in final_tickers
                ]
            else:
                scored_additions = []
            if scored_additions:
                ledger_path = config.master_additions_ledger_path or ADDITIONS_LEDGER
                append_master_additions(scored_additions, additions_path=ledger_path)
                state.artifacts["master_additions_ledger"] = str(ledger_path)
            if config.emit_complete_panel:
                _emit_complete_panel(state)
            return _finish(state, final=True)
        _record(state, GateResult(10, "Top10 + Plus5 + shadow refill publish", GateStatus.SKIPPED, {"reason": "not_broad_final_or_skip_llm"}, {}))
        return _finish(state, final=False, stopped="publish_skipped")
    except StopGateError as exc:
        return _finish(state, final=False, stopped=str(exc))
