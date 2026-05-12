from __future__ import annotations

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
            evidence.append(text[:max_chars_per_doc])
            doc_refs.append(
                {
                    "document_type": doc.get("document_type", ""),
                    "accession": doc.get("accession", ""),
                    "document_name": doc.get("document_name", ""),
                    "document_url": doc.get("document_url", ""),
                }
            )
        safe_candidate = {key: value for key, value in candidate.items() if key not in BLOCKED_FIELDS}
        packets.append(
            {
                **safe_candidate,
                "sample_id": f"{ticker}_{quarter}",
                "ticker": ticker,
                "quarter": quarter,
                "evidence_snippets": evidence,
                "document_refs": doc_refs,
            }
        )
    return packets
