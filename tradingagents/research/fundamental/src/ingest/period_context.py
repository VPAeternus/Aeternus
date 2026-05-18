from __future__ import annotations

from collections import Counter
from typing import Any, Iterator


def normalize_accession(value: Any) -> str:
    """Normalize SEC accession strings for dashed/undashed comparisons."""
    text = str(value or "").strip().upper()
    return "".join(ch for ch in text if ch.isalnum())


def derive_period_context(
    companyfacts: dict[str, Any],
    *,
    periodic_accession: Any,
    periodic_form: Any = "",
    periodic_filing_date: Any = "",
) -> dict[str, str]:
    accession = normalize_accession(periodic_accession)
    form = str(periodic_form or "").strip().upper()
    matches = [
        item for item in _iter_fact_items(companyfacts)
        if normalize_accession(item.get("accn") or item.get("accession")) == accession
    ]
    if form:
        form_matches = [item for item in matches if str(item.get("form") or "").strip().upper() == form]
        if form_matches:
            matches = form_matches
    valid = [item for item in matches if item.get("end")]
    if not accession:
        return _missing("missing_periodic_accession")
    if not valid:
        return _missing("no_companyfacts_for_periodic_accession")

    end_counts = Counter(str(item.get("end")) for item in valid)
    selected_end, selected_count = end_counts.most_common(1)[0]
    if len(end_counts) > 1 and list(end_counts.values()).count(selected_count) > 1:
        return _missing("ambiguous_period_context")

    selected = [item for item in valid if str(item.get("end")) == selected_end]
    with_start = [item for item in selected if item.get("start")]
    best = sorted(
        with_start or selected,
        key=lambda item: (
            str(item.get("filed") or periodic_filing_date or ""),
            str(item.get("concept") or ""),
        ),
        reverse=True,
    )[0]

    return {
        "fiscal_period_start": str(best.get("start") or ""),
        "fiscal_period_end": selected_end,
        "target_period_end": selected_end,
        "fiscal_year": str(best.get("fy") or ""),
        "fiscal_period": str(best.get("fp") or ""),
        "period_context_source": "companyfacts_accession",
        "period_context_confidence": "high",
        "period_context_missing_reason": "",
    }


def _missing(reason: str) -> dict[str, str]:
    return {
        "fiscal_period_start": "",
        "fiscal_period_end": "",
        "target_period_end": "",
        "fiscal_year": "",
        "fiscal_period": "",
        "period_context_source": "",
        "period_context_confidence": "none",
        "period_context_missing_reason": reason,
    }


def _iter_fact_items(companyfacts: dict[str, Any]) -> Iterator[dict[str, Any]]:
    facts = companyfacts.get("facts", {})
    for namespace, concepts in facts.items():
        if not isinstance(concepts, dict):
            continue
        for concept, payload in concepts.items():
            units = payload.get("units", {}) if isinstance(payload, dict) else {}
            for unit, values in units.items():
                for item in values if isinstance(values, list) else []:
                    if isinstance(item, dict):
                        yield {**item, "namespace": namespace, "concept": concept, "unit": unit}
