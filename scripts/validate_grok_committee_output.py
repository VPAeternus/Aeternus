#!/usr/bin/env python3
"""Validate Grok committee output against packet policy and schema."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


VALID_EXEC_GATE = {
    "PASS",
    "BLOCKED_STALE_CONTEXT",
    "BLOCKED_MISSING_LIVE_MARKS",
    "BLOCKED_OTHER",
}
VALID_ACTIONS = {"BUY", "ADD", "HOLD", "WATCHLIST", "TRIM", "AVOID"}
VALID_CHANGE_TYPES = {"OPEN", "INCREASE", "DECREASE", "CLOSE", "NONE"}
VALID_HEDGE_ACTIONS = {
    "NO_CHANGE",
    "INCREASE_HEDGE",
    "DECREASE_HEDGE",
    "DEFER_UNTIL_FRESH_CONTEXT",
}
VALID_OPERATORS = {"<", "<=", ">", ">=", "==", "!="}
REQUIRED_TOP_LEVEL = [
    "as_of_date",
    "input_tickers",
    "execution_gate",
    "portfolio_snapshot_used",
    "per_ticker_decisions",
    "portfolio_actions",
    "ranked_conviction",
    "gaps_and_followups",
]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parse_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return None


def validate(packet: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    for key in REQUIRED_TOP_LEVEL:
        if key not in output:
            errors.append(f"Missing top-level field: {key}")

    gate = output.get("execution_gate")
    if not isinstance(gate, dict):
        errors.append("execution_gate must be an object")
    else:
        status = gate.get("status")
        if status not in VALID_EXEC_GATE:
            errors.append(f"execution_gate.status invalid: {status}")
        reasons = gate.get("reasons")
        if not isinstance(reasons, list):
            errors.append("execution_gate.reasons must be a list")

    pss = output.get("portfolio_snapshot_used") or {}
    if not isinstance(pss, dict):
        errors.append("portfolio_snapshot_used must be an object")
    else:
        if "snapshot_stale" not in pss:
            errors.append("portfolio_snapshot_used.snapshot_stale is required")

    per_ticker = output.get("per_ticker_decisions")
    if not isinstance(per_ticker, list):
        errors.append("per_ticker_decisions must be a list")
        per_ticker = []

    ranked = output.get("ranked_conviction")
    if not isinstance(ranked, list):
        errors.append("ranked_conviction must be a list")

    portfolio_actions = output.get("portfolio_actions") or {}
    rec_changes = portfolio_actions.get("recommended_changes")
    if not isinstance(rec_changes, list):
        errors.append("portfolio_actions.recommended_changes must be a list")
        rec_changes = []
    hedge_view = portfolio_actions.get("hedge_view") or {}
    if isinstance(hedge_view, dict):
        hedge_action = hedge_view.get("action")
        if hedge_action is not None and hedge_action not in VALID_HEDGE_ACTIONS:
            errors.append(f"portfolio_actions.hedge_view.action invalid: {hedge_action}")

    packet_exec = (packet.get("execution_readiness") or {}).get("status")
    blocked_packet = packet_exec != "PASS"
    stale_packet = bool((packet.get("data_freshness") or {}).get("portfolio_snapshot_stale"))

    output_gate_status = (output.get("execution_gate") or {}).get("status")
    blocked_output = output_gate_status != "PASS"

    if blocked_packet and not blocked_output:
        errors.append(
            "execution_gate.status must be blocked because packet execution_readiness.status is blocked."
        )

    if stale_packet and not pss.get("snapshot_stale", False):
        errors.append(
            "portfolio_snapshot_used.snapshot_stale must be true when packet indicates stale context."
        )

    current_symbols = {
        str((row or {}).get("symbol")).upper()
        for row in ((packet.get("portfolio_context") or {}).get("current_positions") or [])
        if (row or {}).get("symbol")
    }

    for idx, row in enumerate(per_ticker):
        prefix = f"per_ticker_decisions[{idx}]"
        if not isinstance(row, dict):
            errors.append(f"{prefix} must be an object")
            continue
        ticker = str(row.get("ticker", "")).upper()
        action = row.get("action")
        target_weight_pct = row.get("target_weight_pct")
        if action not in VALID_ACTIONS:
            errors.append(f"{prefix}.action invalid: {action}")
        if not _is_number(target_weight_pct):
            errors.append(f"{prefix}.target_weight_pct must be numeric")

        if action in {"BUY", "ADD"}:
            if _is_number(target_weight_pct) and target_weight_pct <= 0:
                errors.append(f"{prefix} BUY/ADD requires positive target_weight_pct")
        if action in {"WATCHLIST", "HOLD", "AVOID"}:
            if _is_number(target_weight_pct) and target_weight_pct != 0:
                errors.append(f"{prefix} {action} requires target_weight_pct=0")

        # HOLD only valid for symbols currently held in portfolio context.
        if action == "HOLD" and ticker and ticker not in current_symbols:
            errors.append(
                f"{prefix} uses HOLD for non-held ticker {ticker}; use WATCHLIST/AVOID instead."
            )

        # Numeric trigger requirements.
        for trigger_key in (
            "entry_trigger_numeric",
            "invalidation_trigger_numeric",
            "review_trigger_numeric",
        ):
            rules = row.get(trigger_key)
            if not isinstance(rules, list) or not rules:
                errors.append(f"{prefix}.{trigger_key} must be a non-empty list")
                continue
            for ridx, rule in enumerate(rules):
                rule_prefix = f"{prefix}.{trigger_key}[{ridx}]"
                if not isinstance(rule, dict):
                    errors.append(f"{rule_prefix} must be an object")
                    continue
                metric = rule.get("metric")
                op = rule.get("operator")
                value = rule.get("value")
                if not isinstance(metric, str) or not metric.strip():
                    errors.append(f"{rule_prefix}.metric must be a non-empty string")
                if op not in VALID_OPERATORS:
                    errors.append(f"{rule_prefix}.operator invalid: {op}")
                if not _is_number(value):
                    errors.append(f"{rule_prefix}.value must be numeric")

    # Blocked-gate execution safety
    if blocked_output:
        for idx, row in enumerate(per_ticker):
            action = (row or {}).get("action")
            tw = (row or {}).get("target_weight_pct")
            if action in {"BUY", "ADD"} and _is_number(tw) and tw > 0:
                errors.append(
                    f"Blocked execution_gate cannot contain BUY/ADD with positive weight: per_ticker_decisions[{idx}]"
                )
        for idx, change in enumerate(rec_changes):
            if not isinstance(change, dict):
                errors.append(f"portfolio_actions.recommended_changes[{idx}] must be an object")
                continue
            ct = change.get("change_type")
            w = change.get("weight_change_pct")
            if ct in {"OPEN", "INCREASE"} and _is_number(w) and w > 0:
                errors.append(
                    f"Blocked execution_gate cannot recommend {ct} with positive weight change at recommended_changes[{idx}]"
                )

    # Search policy validation.
    search_policy = packet.get("search_policy") or {}
    if bool(search_policy.get("allow_external_search")):
        ext = output.get("external_enrichment")
        if not isinstance(ext, dict):
            errors.append("external_enrichment is required when search_policy.allow_external_search=true")
        else:
            used = bool(ext.get("used"))
            queries = ext.get("queries")
            citations = ext.get("citations")
            conflicts = ext.get("conflicts_with_packet")
            if not isinstance(queries, list):
                errors.append("external_enrichment.queries must be a list")
            if not isinstance(citations, list):
                errors.append("external_enrichment.citations must be a list")
                citations = []
            if not isinstance(conflicts, list):
                errors.append("external_enrichment.conflicts_with_packet must be a list")
            if used and len(citations) == 0:
                errors.append("external_enrichment.used=true requires at least one citation")
            recency_days = int(search_policy.get("citation_recency_days") or 7)
            for idx, c in enumerate(citations):
                cp = f"external_enrichment.citations[{idx}]"
                if not isinstance(c, dict):
                    errors.append(f"{cp} must be an object")
                    continue
                for field in ("id", "url", "source", "published_at", "claim", "supports"):
                    if field not in c:
                        errors.append(f"{cp}.{field} is required")
                dt = _parse_date(c.get("published_at"))
                if dt is None:
                    errors.append(f"{cp}.published_at must be ISO date/datetime")
                else:
                    now = datetime.utcnow()
                    age = (now - dt.replace(tzinfo=None)).days
                    if age > recency_days:
                        warnings.append(
                            f"{cp}.published_at appears older than recency window ({age}d > {recency_days}d)"
                        )
                if not isinstance(c.get("supports"), list):
                    errors.append(f"{cp}.supports must be a list")

    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Grok committee output JSON.")
    parser.add_argument("--packet", required=True, help="Path to packet JSON used for prompt.")
    parser.add_argument(
        "--output",
        required=True,
        help="Path to model output JSON to validate, or '-' to read JSON from stdin.",
    )
    args = parser.parse_args()

    packet_path = Path(args.packet)
    packet = _read_json(packet_path)
    if args.output == "-":
        raw = sys.stdin.read()
        output = json.loads(raw)
    else:
        output_path = Path(args.output)
        output = _read_json(output_path)
    result = validate(packet=packet, output=output)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
