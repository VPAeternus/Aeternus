from __future__ import annotations

from datetime import date
from typing import Any

from tradingagents.research.fundamental.src.features.common import clean


BOOTSTRAP_PRIOR_MISSING = "bootstrap_initial_quarter_missing_prior_context"


def build_row_contract(row: dict[str, Any], *, decision_date_rule: str) -> dict[str, Any]:
    out = dict(row)
    out["decision_date_rule"] = decision_date_rule or out.get("decision_date_rule", "")
    out.setdefault("source_available_date", out.get("decision_date", ""))
    out.setdefault("financial_cutoff_date", out.get("source_available_date", ""))
    out.setdefault("score_producing_flag", "1")
    out.setdefault("accepted_row_flag", "0")
    out.setdefault("diagnostic_only_flag", "0")
    out.setdefault("score_input_quarantine_reason", "")
    return out


def validate_row_contract(row: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    decision_rule = str(row.get("decision_date_rule") or "").strip()
    decision_date = _parse_date(row.get("decision_date"))

    if decision_rule == "full_evidence" and not clean(row.get("periodic_accession")):
        issues.append("missing_periodic_accession")
    if not clean(row.get("fiscal_period_end")) or not clean(row.get("target_period_end")):
        issues.append("missing_fiscal_period_metadata")

    financial_cutoff = _parse_date(row.get("financial_cutoff_date"))
    if financial_cutoff and decision_date and financial_cutoff > decision_date:
        issues.append("financial_cutoff_after_decision_date")

    _validate_universe_membership(row, decision_date, issues)
    _validate_prior_context(row, issues)
    _validate_execution_timing(row, issues)
    _validate_ticker_mapping(row, decision_date, issues)
    return issues


def _validate_universe_membership(row: dict[str, Any], decision_date: date | None, issues: list[str]) -> None:
    effective = _parse_date(row.get("universe_membership_effective_date"))
    if not effective or not decision_date or effective <= decision_date:
        return
    if _truthy(row.get("retrospective_universe_backfill_flag")):
        if not (_truthy(row.get("diagnostic_only_flag")) and _truthy(row.get("not_eligible_for_historical_selection_validation"))):
            issues.append("retrospective_universe_backfill_not_diagnostic")
    else:
        issues.append("universe_membership_after_decision_date")


def _validate_prior_context(row: dict[str, Any], issues: list[str]) -> None:
    if _truthy(row.get("prior_context_pit_valid_flag")):
        return
    if str(row.get("prior_context_missing_reason") or "") == BOOTSTRAP_PRIOR_MISSING:
        return
    issues.append("missing_prior_context")


def _validate_execution_timing(row: dict[str, Any], issues: list[str]) -> None:
    if not _truthy(row.get("price_reference_used_for_scoring_flag")):
        return
    if _truthy(row.get("execution_after_score_timestamp_flag")):
        return
    if _truthy(row.get("diagnostic_only_flag")) or _truthy(row.get("non_executable_research_score_flag")):
        return
    issues.append("execution_not_after_score_timestamp")


def _validate_ticker_mapping(row: dict[str, Any], decision_date: date | None, issues: list[str]) -> None:
    effective = _parse_date(row.get("ticker_mapping_effective_date"))
    if effective and decision_date and effective > decision_date:
        issues.append("ticker_mapping_after_decision_date")
    if clean(row.get("ticker_as_of_decision_date")) and clean(row.get("price_ticker_used")):
        if str(row.get("ticker_as_of_decision_date")).upper() != str(row.get("price_ticker_used")).upper():
            issues.append("price_ticker_facts_cik_mismatch")
    if not clean(row.get("facts_cik_used")) or not clean(row.get("price_ticker_used")):
        issues.append("ticker_cik_mapping_missing")


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}
