from __future__ import annotations

import hashlib
import json
from typing import Any


DEFAULT_LLM_DOCUMENT_TYPES = {"earnings_exhibit", "primary_8k"}
DOCUMENT_TYPE_PRIORITY = {"earnings_exhibit": 0, "primary_8k": 1}


BLOCKED_FIELDS = {
    "entry_open",
    "tradable_date",
    "return_10d_pct",
    "return_20d_pct",
    "return_30d_pct",
    "return_60d_pct",
    "return_90d_pct",
    "current_return_pct",
}

PRIOR_LLM_PREFIX = "prior_llm_"


def _key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("ticker", "")).upper(), str(row.get("quarter", ""))


def build_llm_packets(
    candidates: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    *,
    max_chars_per_doc: int = 5000,
    allowed_document_types: set[str] | None = None,
) -> list[dict[str, Any]]:
    allowed = DEFAULT_LLM_DOCUMENT_TYPES if allowed_document_types is None else allowed_document_types
    docs_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for doc in documents:
        if str(doc.get("document_type", "")).strip() not in allowed:
            continue
        docs_by_key.setdefault(_key(doc), []).append(doc)
    for key, docs in docs_by_key.items():
        docs_by_key[key] = sorted(docs, key=lambda row: DOCUMENT_TYPE_PRIORITY.get(str(row.get("document_type", "")), 99))
    packets: list[dict[str, Any]] = []
    for candidate in candidates:
        ticker, quarter = _key(candidate)
        evidence = []
        doc_refs = []
        for doc in docs_by_key.get((ticker, quarter), []):
            text = str(doc.get("clean_text") or doc.get("raw_text") or "").strip()
            if not text:
                continue
            doc_date = _doc_available_date(doc)
            evidence.append(text[:max_chars_per_doc])
            doc_refs.append(
                {
                    "document_type": doc.get("document_type", ""),
                    "accession": doc.get("accession", ""),
                    "document_name": doc.get("document_name", ""),
                    "document_url": doc.get("document_url", ""),
                    "document_date": doc_date,
                }
            )
        prior_llm_extract = {
            key[len(PRIOR_LLM_PREFIX):]: value
            for key, value in candidate.items()
            if key.startswith(PRIOR_LLM_PREFIX) and str(value).strip()
        }
        safe_candidate = {
            key: value
            for key, value in candidate.items()
            if key not in BLOCKED_FIELDS and not key.startswith(PRIOR_LLM_PREFIX)
        }
        if prior_llm_extract:
            safe_candidate["prior_llm_extract"] = prior_llm_extract
        source_dates = [str(ref.get("document_date") or "").strip() for ref in doc_refs if str(ref.get("document_date") or "").strip()]
        source_accessions = [str(ref.get("accession") or "").strip() for ref in doc_refs if str(ref.get("accession") or "").strip()]
        packet = {
            **safe_candidate,
            "sample_id": f"{ticker}_{quarter}",
            "ticker": ticker,
            "quarter": quarter,
            "evidence_snippets": evidence,
            "document_refs": doc_refs,
            "llm_source_accessions": ";".join(source_accessions),
            "llm_source_document_dates": ";".join(source_dates),
            "llm_source_available_date": max(source_dates) if source_dates else "",
            "llm_prompt_input_allowed_docs_only": "1",
        }
        packet["llm_prompt_input_hash"] = hashlib.sha256(
            json.dumps(
                {
                    "sample_id": packet["sample_id"],
                    "evidence_snippets": packet["evidence_snippets"],
                    "document_refs": packet["document_refs"],
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        packets.append(packet)
    return packets


def _doc_available_date(doc: dict[str, Any]) -> str:
    for key in ("filing_date", "document_date", "filed", "accepted_date", "event_date"):
        value = str(doc.get(key) or "").strip()
        if value:
            return value[:10]
    return ""
