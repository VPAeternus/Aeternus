from __future__ import annotations

import html
import re
from typing import Any


def quality_check_document(row: dict[str, Any], min_text_length: int = 500) -> dict[str, Any]:
    text = str(row.get("clean_text") or row.get("raw_text") or "")
    reasons: list[str] = []
    if len(text.strip()) < min_text_length:
        reasons.append("text_too_short")
    if row.get("document_status") in {"missing", "failed"}:
        reasons.append(f"document_status_{row.get('document_status')}")
    return {
        "extraction_ready_flag": int(not reasons),
        "quality_fail_reasons": ";".join(reasons),
        "extraction_quality_failure": int(bool(reasons)),
    }


def html_to_text(raw: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", raw or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def classify_doc_quality(document_type: str, text: str) -> dict[str, Any]:
    lower = text.lower()
    reasons: list[str] = []
    if document_type == "primary_8k" and len(text) < 100:
        reasons.append("primary_8k_too_short")
    elif document_type == "earnings_exhibit":
        if len(text) < 1500:
            reasons.append("earnings_exhibit_too_short")
        terms = ("earnings", "results", "revenue", "quarter", "fiscal", "guidance", "outlook")
        if sum(1 for term in terms if term in lower) < 3:
            reasons.append("exhibit_not_earnings_like")
    elif document_type == "periodic_10q_10k" and len(text) < 1000:
        reasons.append("periodic_doc_too_short")
    return {
        "document_type": document_type,
        "text_len": len(text),
        "extraction_ready_flag": int(not reasons),
        "quality_fail_reasons": ";".join(reasons),
        "extraction_quality_failure": int(bool(reasons)),
    }
