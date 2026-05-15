from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from .artifacts import write_csv


STATUS_COLUMNS = [
    "ticker",
    "quarter",
    "source_status",
    "identity_status",
    "sec_status",
    "price_status",
    "pre_llm_status",
    "llm_required_status",
    "llm_packet_status",
    "llm_completion_status",
    "final_score_status",
    "rejection_reason",
]


def _ticker(value: Any) -> str:
    return str(value or "").upper().replace(".", "-").replace("/", "-").strip()


def _key(row: Mapping[str, Any], quarter: str) -> tuple[str, str]:
    return _ticker(row.get("ticker") or row.get("symbol")), str(row.get("quarter") or quarter)


def _base_row(ticker: str, quarter: str) -> dict[str, Any]:
    return {column: "" for column in STATUS_COLUMNS} | {"ticker": ticker, "quarter": quarter}


def _plain_source_status(row: Mapping[str, Any], *, default: str) -> str:
    raw = str(
        row.get("daily_source_label")
        or row.get("source_status")
        or row.get("master_universe_source")
        or row.get("stock_source_type")
        or default
    ).strip()
    if raw in {"master_start", "existing_master_addition", "today_dealflow_add", "rejected"}:
        return raw
    if raw == "daily_scout_append":
        return "existing_master_addition"
    if "master_start" in raw or "start_2021Q4" in raw:
        return "master_start"
    if raw in {"", "main_stock_list"}:
        return default
    return raw


def _ensure(rows: dict[tuple[str, str], dict[str, Any]], key: tuple[str, str]) -> dict[str, Any]:
    if key not in rows:
        rows[key] = _base_row(key[0], key[1])
    return rows[key]


def build_daily_status_rows(
    *,
    quarter: str,
    universe_rows: Iterable[Mapping[str, Any]] = (),
    identity_rejections: Iterable[Mapping[str, Any]] = (),
    coverage_rows: Iterable[Mapping[str, Any]] = (),
    pre_rows: Iterable[Mapping[str, Any]] = (),
    price_quarantine: Iterable[Mapping[str, Any]] = (),
    score_input_quarantine: Iterable[Mapping[str, Any]] = (),
    llm_eligible_rows: Iterable[Mapping[str, Any]] = (),
    llm_quarantine: Iterable[Mapping[str, Any]] = (),
    packet_rows: Iterable[Mapping[str, Any]] = (),
    packet_quarantine: Iterable[Mapping[str, Any]] = (),
    post_llm_rows: Iterable[Mapping[str, Any]] = (),
    final_rows: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in universe_rows:
        key = _key(raw, quarter)
        row = _ensure(rows, key)
        row["source_status"] = _plain_source_status(raw, default="master_start")
        row["identity_status"] = "resolved" if raw.get("cik") and raw.get("company_title") else "missing_identity"

    for raw in identity_rejections:
        key = _key(raw, quarter)
        row = _ensure(rows, key)
        row["source_status"] = "rejected"
        row["identity_status"] = str(raw.get("identity_status") or "unresolved")
        row["final_score_status"] = "rejected"
        row["rejection_reason"] = str(raw.get("rejection_reason") or raw.get("identity_status") or "")

    for raw in coverage_rows:
        row = _ensure(rows, _key(raw, quarter))
        row["sec_status"] = str(raw.get("coverage_status") or "")
        if raw.get("missing_inputs") and not row["rejection_reason"]:
            row["rejection_reason"] = str(raw.get("missing_inputs"))

    for raw in pre_rows:
        row = _ensure(rows, _key(raw, quarter))
        row["pre_llm_status"] = "ready" if str(raw.get("pre_llm_fundamental_bucket") or "") != "not_scored" else "missing_score_inputs"

    for raw in price_quarantine:
        row = _ensure(rows, _key(raw, quarter))
        row["price_status"] = str(raw.get("quarantine_reason") or "missing_entry_open")
        if not row["rejection_reason"]:
            row["rejection_reason"] = row["price_status"]

    for raw in score_input_quarantine:
        row = _ensure(rows, _key(raw, quarter))
        row["pre_llm_status"] = "blocked"
        row["final_score_status"] = "quarantined"
        row["rejection_reason"] = str(raw.get("score_input_quarantine_reason") or row["rejection_reason"])

    for raw in llm_eligible_rows:
        row = _ensure(rows, _key(raw, quarter))
        row["llm_required_status"] = "required"
        row["llm_packet_status"] = "ready_for_packet"

    for raw in llm_quarantine:
        row = _ensure(rows, _key(raw, quarter))
        reason = str(raw.get("llm_quarantine_reason") or "")
        row["llm_required_status"] = "not_required" if reason == "not_llm_required" else "blocked"
        row["llm_packet_status"] = reason
        if reason and reason != "not_llm_required" and not row["rejection_reason"]:
            row["rejection_reason"] = reason

    for raw in packet_rows:
        ticker = _ticker(raw.get("ticker"))
        qtr = str(raw.get("quarter") or quarter)
        row = _ensure(rows, (ticker, qtr))
        row["llm_packet_status"] = "packet_built"

    for raw in packet_quarantine:
        row = _ensure(rows, _key(raw, quarter))
        row["llm_packet_status"] = str(raw.get("llm_quarantine_reason") or "packet_missing_evidence")

    for raw in post_llm_rows:
        row = _ensure(rows, _key(raw, quarter))
        row["llm_completion_status"] = "complete"

    for raw in final_rows:
        row = _ensure(rows, _key(raw, quarter))
        if not row["price_status"]:
            row["price_status"] = "ready"
        row["final_score_status"] = "scored"

    return [rows[key] for key in sorted(rows)]


def write_daily_status(path: Path, **kwargs: Any) -> Path:
    return write_csv(path, build_daily_status_rows(**kwargs))
