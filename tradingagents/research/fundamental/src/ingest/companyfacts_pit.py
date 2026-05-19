from __future__ import annotations

import json
from datetime import date
from typing import Any, Iterable, Iterator

from tradingagents.research.fundamental.src.ingest.period_context import normalize_accession


FIELD_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue_value": ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"),
    "net_income_value": ("NetIncomeLoss",),
    "assets_value": ("Assets",),
    "operating_cash_flow_value": ("NetCashProvidedByUsedInOperatingActivities",),
    "investing_cash_flow_value": ("NetCashProvidedByUsedInInvestingActivities",),
    "financing_cash_flow_value": ("NetCashProvidedByUsedInFinancingActivities",),
}

DURATION_FIELDS = {
    "revenue_value",
    "net_income_value",
    "operating_cash_flow_value",
    "investing_cash_flow_value",
    "financing_cash_flow_value",
}
INSTANT_FIELDS = {"assets_value"}
PROVENANCE_SUFFIXES = (
    "fact_namespace",
    "fact_concept",
    "fact_unit",
    "fact_start",
    "fact_end",
    "fact_filed",
    "fact_form",
    "fact_accession",
    "fact_period_type",
    "fact_selection_reason",
    "fact_missing_reason",
    "fact_is_exact_accession",
    "fact_is_consolidated",
    "fact_dimensions",
    "fact_segment",
    "fact_frame",
    "derivation_formula",
    "derivation_source_facts_json",
)


def select_pit_financials(
    companyfacts: dict[str, Any],
    row_contract: dict[str, Any],
    *,
    fields: Iterable[str] | None = None,
    allow_relaxed_filed_date: bool = False,
) -> dict[str, Any]:
    if allow_relaxed_filed_date and _truthy(row_contract.get("score_producing_flag")):
        raise ValueError("allow_relaxed_filed_date is not allowed for score-producing rows")
    out: dict[str, Any] = {}
    for field in fields or FIELD_CONCEPTS:
        out.update(_select_field(companyfacts, row_contract, field))
    return out


def _select_field(companyfacts: dict[str, Any], row: dict[str, Any], field: str) -> dict[str, Any]:
    out = _empty_field(field, "")
    concepts = FIELD_CONCEPTS.get(field, ())
    cutoff = _parse_date(row.get("financial_cutoff_date") or row.get("source_available_date"))
    target_end = _parse_date(row.get("target_period_end"))
    periodic_accession = normalize_accession(row.get("periodic_accession"))
    score_producing = _truthy(row.get("score_producing_flag"))
    if score_producing and target_end is None:
        return _empty_field(field, "missing_target_period_end")
    exact_required = bool(periodic_accession and score_producing)

    all_items = [
        item for item in _iter_fact_items(companyfacts, concepts)
        if _is_number(item.get("val"))
        and _date_lte(item.get("filed"), cutoff)
        and _date_lte(item.get("end"), target_end)
    ]
    if exact_required:
        current_items = [item for item in all_items if normalize_accession(item.get("accn") or item.get("accession")) == periodic_accession]
        if not current_items:
            return _empty_field(field, "missing_exact_accession_fact")
    else:
        current_items = all_items

    consolidated = [item for item in current_items if _is_consolidated(item)]
    if not consolidated and current_items:
        return _empty_field(field, "segment_only_fact_not_allowed")
    if not consolidated:
        return _empty_field(field, "missing_pit_fact")

    if field in INSTANT_FIELDS:
        target_items = [item for item in consolidated if _is_target_period(item, target_end)] if target_end else []
        if target_end and not target_items:
            return _empty_field(field, "missing_target_period_fact")
        return _selected(field, _prefer_usd_best_by_end(target_items or consolidated), "instant", "selected_instant_fact")

    direct = [item for item in consolidated if _is_target_period(item, target_end) and _is_quarter_duration(item)]
    if direct:
        return _selected(field, _prefer_usd(direct), "quarterly", "selected_quarterly_fact")

    derived = _derive_qtd_from_ytd(field, consolidated, all_items, cutoff, target_end)
    if derived:
        return derived
    return _empty_field(field, "missing_prior_ytd_for_qtd_derivation")


def _derive_qtd_from_ytd(
    field: str,
    current_items: list[dict[str, Any]],
    all_items: list[dict[str, Any]],
    cutoff: date | None,
    target_end: date | None,
) -> dict[str, Any] | None:
    current_ytd = [
        item for item in current_items
        if item.get("start")
        and not _is_quarter_duration(item)
        and (target_end is None or _parse_date(item.get("end")) == target_end)
    ]
    if not current_ytd:
        return None
    current = _prefer_usd(current_ytd)
    current_start = _parse_date(current.get("start"))
    current_end = _parse_date(current.get("end"))
    if current_start is None or current_end is None:
        return None
    prior_items = [
        item for item in all_items
        if _is_consolidated(item)
        and item.get("concept") == current.get("concept")
        and item.get("unit") == current.get("unit")
        and str(item.get("fy") or "") == str(current.get("fy") or "")
        and _parse_date(item.get("end")) is not None
        and _parse_date(item.get("end")) < current_end
        and _parse_date(item.get("start")) == current_start
        and _date_lte(item.get("filed"), cutoff)
    ]
    if not prior_items:
        return None
    prior = _best_by_end_then_filed(prior_items)
    value = _num(current["val"]) - _num(prior["val"])
    out = _selected(field, current, "derived_qtd_from_ytd", "derived_current_ytd_minus_prior_ytd")
    out[field] = _clean_number(value)
    out[f"{field}_derivation_formula"] = "current_ytd_minus_prior_ytd"
    out[f"{field}_derivation_source_facts_json"] = json.dumps(
        [
            _provenance_dict(current),
            _provenance_dict(prior),
        ],
        sort_keys=True,
    )
    return out


def _selected(field: str, item: dict[str, Any], period_type: str, reason: str) -> dict[str, Any]:
    value = _clean_number(_num(item.get("val")))
    unit = str(item.get("unit") or "")
    out = _empty_field(field, "")
    out[field] = value
    out["financial_values_currency"] = unit
    if field == "revenue_value" and unit != "USD":
        out["revenue_bucket"] = ""
    out.update(
        {
            f"{field}_fact_namespace": item.get("namespace", ""),
            f"{field}_fact_concept": item.get("concept", ""),
            f"{field}_fact_unit": unit,
            f"{field}_fact_start": item.get("start", ""),
            f"{field}_fact_end": item.get("end", ""),
            f"{field}_fact_filed": item.get("filed", ""),
            f"{field}_fact_form": item.get("form", ""),
            f"{field}_fact_accession": item.get("accn", item.get("accession", "")),
            f"{field}_fact_period_type": period_type,
            f"{field}_fact_selection_reason": reason,
            f"{field}_fact_missing_reason": "",
            f"{field}_fact_is_exact_accession": "1",
            f"{field}_fact_is_consolidated": "1" if _is_consolidated(item) else "0",
            f"{field}_fact_dimensions": _json_or_blank(item.get("dimensions")),
            f"{field}_fact_segment": item.get("segment", ""),
            f"{field}_fact_frame": item.get("frame", ""),
        }
    )
    return out


def _empty_field(field: str, reason: str) -> dict[str, Any]:
    out = {field: ""}
    for suffix in PROVENANCE_SUFFIXES:
        out[f"{field}_{suffix}"] = ""
    out[f"{field}_fact_missing_reason"] = reason
    return out


def _iter_fact_items(companyfacts: dict[str, Any], concepts: tuple[str, ...]) -> Iterator[dict[str, Any]]:
    facts = companyfacts.get("facts", {})
    for namespace, payload in facts.items():
        if not isinstance(payload, dict):
            continue
        for concept in concepts:
            units = payload.get(concept, {}).get("units", {})
            for unit, values in units.items():
                for item in values if isinstance(values, list) else []:
                    if isinstance(item, dict):
                        yield {**item, "namespace": namespace, "concept": concept, "unit": unit}


def _is_consolidated(item: dict[str, Any]) -> bool:
    return not any(item.get(key) for key in ("segment", "segments", "dimensions", "dimension", "member"))


def _is_quarter_duration(item: dict[str, Any]) -> bool:
    start = _parse_date(item.get("start"))
    end = _parse_date(item.get("end"))
    if start is None or end is None:
        return False
    return 0 <= (end - start).days <= 120


def _is_target_period(item: dict[str, Any], target_end: date | None) -> bool:
    end = _parse_date(item.get("end"))
    return end is not None and (target_end is None or end == target_end)


def _prefer_usd(items: list[dict[str, Any]]) -> dict[str, Any]:
    return _best_by_filed([item for item in items if item.get("unit") == "USD"] or items)


def _prefer_usd_best_by_end(items: list[dict[str, Any]]) -> dict[str, Any]:
    return _best_by_end_then_filed([item for item in items if item.get("unit") == "USD"] or items)


def _best_by_filed(items: list[dict[str, Any]]) -> dict[str, Any]:
    return sorted(items, key=lambda item: str(item.get("filed") or ""), reverse=True)[0]


def _best_by_end_then_filed(items: list[dict[str, Any]]) -> dict[str, Any]:
    return sorted(items, key=lambda item: (str(item.get("end") or ""), str(item.get("filed") or "")), reverse=True)[0]


def _provenance_dict(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "namespace": item.get("namespace", ""),
        "concept": item.get("concept", ""),
        "unit": item.get("unit", ""),
        "start": item.get("start", ""),
        "end": item.get("end", ""),
        "filed": item.get("filed", ""),
        "form": item.get("form", ""),
        "accession": item.get("accn", item.get("accession", "")),
        "val": item.get("val", ""),
    }


def _date_lte(value: Any, cutoff: date | None) -> bool:
    parsed = _parse_date(value)
    return parsed is not None and (cutoff is None or parsed <= cutoff)


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def _is_number(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _num(value: Any) -> float:
    return float(value)


def _clean_number(value: float) -> int | float:
    return int(value) if value.is_integer() else value


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _json_or_blank(value: Any) -> str:
    return "" if value in (None, "", [], {}) else json.dumps(value, sort_keys=True)
