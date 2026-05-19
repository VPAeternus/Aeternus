from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from tradingagents.research.fundamental.src.config.cache_paths import sec_cache_root
from tradingagents.research.fundamental.src.features.common import clean
from tradingagents.research.fundamental.src.features.theme_acceleration import THEME_ACCELERATION_FIELDS, normalized_theme_acceleration_fields


CSV_FIELDS = [
    "sample_id",
    "quarter",
    "ticker",
    "event_date",
    "causal_change",
    "proof_alignment",
    "durability",
    "operating_leverage_quality",
    "negative_revision_risk",
    "story_vs_numbers_gap_penalty",
    "narrative_delta_score",
    "narrative_delta_bucket",
    "score_addition",
    "post_llm_candidate_flag",
    "post_llm_high_priority_flag",
    "post_llm_demote_flag",
    "post_llm_demote_severity",
    "post_llm_demote_reason_code",
    "post_llm_demote_overrideable",
    "post_llm_demote_evidence",
    "detected_driver_category",
    "detected_driver_name",
    "evidence_positive",
    "evidence_risk",
    "confidence",
    "blocking_issues",
    "primary_theme",
    "secondary_themes",
    "theme_tags",
    "theme_role",
    "theme_confidence",
    "theme_driver_type",
    "theme_momentum",
    "theme_evidence",
    *THEME_ACCELERATION_FIELDS,
    "theme_tailwind_score",
    "theme_driver_summary",
    "theme_evidence_summary",
    "llm_source_accessions",
    "llm_source_document_dates",
    "llm_source_available_date",
    "llm_prompt_input_hash",
    "llm_prompt_input_allowed_docs_only",
    "llm_generated_at",
    "llm_model",
    "llm_output_hash",
    "llm_cache_key",
    "source_packet_path",
    "reasoning_effort",
]

DEMOTE_SEVERITIES = {"none", "soft", "hard", "unknown"}
DEMOTE_REASON_CODES = {
    "",
    "weak_fundamentals",
    "cyclical_trough",
    "high_leverage",
    "inventory_digesting",
    "margin_pressure",
    "customer_concentration",
    "liquidity_risk",
    "dilution_risk",
    "going_concern",
    "accounting_quality",
    "fraud_or_integrity",
    "broken_thesis",
    "missing_filings",
}

BLOCKED_PACKET_FIELDS = {
    "return_10d_pct",
    "return_20d_pct",
    "return_30d_pct",
    "return_60d_pct",
    "return_90d_pct",
    "entry_open",
    "tradable_date",
}


def read_packets(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def scrub_packet(packet: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in packet.items() if key not in BLOCKED_PACKET_FIELDS}


def result_schema() -> dict[str, Any]:
    item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "sample_id": {"type": "string"},
            "quarter": {"type": "string"},
            "ticker": {"type": "string"},
            "event_date": {"type": "string"},
            "causal_change": {"type": "integer", "minimum": 0, "maximum": 3},
            "proof_alignment": {"type": "integer", "minimum": 0, "maximum": 3},
            "durability": {"type": "integer", "minimum": 0, "maximum": 2},
            "operating_leverage_quality": {"type": "integer", "minimum": 0, "maximum": 2},
            "negative_revision_risk": {"type": "integer", "minimum": 0, "maximum": 5},
            "story_vs_numbers_gap_penalty": {"type": "integer", "minimum": 0, "maximum": 3},
            "narrative_delta_score": {"type": "integer", "minimum": -5, "maximum": 10},
            "narrative_delta_bucket": {
                "type": "string",
                "enum": ["inflecting", "constructive", "neutral", "deteriorating", "unscorable"],
            },
            "score_addition": {"type": "integer", "minimum": -3, "maximum": 3},
            "post_llm_demote_severity": {"type": "string", "enum": sorted(DEMOTE_SEVERITIES)},
            "post_llm_demote_reason_code": {"type": "string", "enum": sorted(DEMOTE_REASON_CODES)},
            "post_llm_demote_overrideable": {"type": "integer", "minimum": 0, "maximum": 1},
            "post_llm_demote_evidence": {"type": "string"},
            "detected_driver_category": {"type": "string"},
            "detected_driver_name": {"type": "string"},
            "evidence_positive": {"type": "string"},
            "evidence_risk": {"type": "string"},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "blocking_issues": {"type": "string"},
            "primary_theme": {"type": "string"},
            "secondary_themes": {"type": "array", "items": {"type": "string"}},
            "theme_tags": {"type": "array", "items": {"type": "string"}},
            "theme_role": {
                "type": "string",
                "enum": [
                    "direct_beneficiary",
                    "supplier",
                    "customer_exposure",
                    "infrastructure_provider",
                    "commodity_exposure",
                    "platform_leader",
                    "turnaround_with_theme_tailwind",
                    "indirect_beneficiary",
                    "none",
                ],
            },
            "theme_confidence": {"type": "string", "enum": ["none", "low", "medium", "high"]},
            "theme_driver_type": {"type": "string", "enum": ["revenue", "margin", "demand", "capacity", "pricing", "valuation", "none"]},
            "theme_momentum": {"type": "string", "enum": ["accelerating", "stable", "fading", "unknown"]},
            "theme_evidence": {"type": "array", "items": {"type": "string"}},
            "filing_theme_growth_flag": {"type": "integer", "minimum": 0, "maximum": 1},
            "filing_theme_guidance_flag": {"type": "integer", "minimum": 0, "maximum": 1},
            "filing_theme_margin_flag": {"type": "integer", "minimum": 0, "maximum": 1},
            "filing_theme_customer_win_flag": {"type": "integer", "minimum": 0, "maximum": 1},
            "filing_theme_capacity_expansion_flag": {"type": "integer", "minimum": 0, "maximum": 1},
            "theme_acceleration_score": {"type": "integer", "minimum": 0, "maximum": 15},
            "theme_tailwind_score": {"type": "integer", "minimum": 0, "maximum": 20},
            "theme_driver_summary": {"type": "string"},
            "theme_evidence_summary": {"type": "string"},
        },
        # Structured-output schemas require `required` to match declared properties.
        # Post-LLM flags are deterministic derived fields added after validation,
        # so they are intentionally not requested from the model.
        "required": [],
    }
    item["required"] = list(item["properties"].keys())
    return {"type": "object", "additionalProperties": False, "properties": {"results": {"type": "array", "items": item}}, "required": ["results"]}


def build_prompt(packets: list[dict[str, Any]]) -> str:
    safe_packets = [scrub_packet(packet) for packet in packets]
    return (
        "Review SEC 8-K Item 2.02 / EX-99.1 evidence packets. "
        "Use only packet evidence. Do not use stock price, future returns, news, analyst expectations, or outside knowledge. "
        "Return JSON only with key `results`. Formula: narrative_delta_score = causal_change + proof_alignment + durability "
        "+ operating_leverage_quality - negative_revision_risk - story_vs_numbers_gap_penalty. "
        "Bucket: >=7 inflecting, 3-6 constructive, 0-2 neutral, <0 deteriorating. "
        "score_addition: inflecting 3, constructive 1, neutral 0, deteriorating -3; if negative_revision_risk >= 4 then -3.\n\n"
        "Adaptive theme classification: identify any macro, sector, product, commodity, infrastructure, technology, "
        "or cycle-driven theme that could be causing a re-rating. Do not force AI/data-center; AI is only one possible theme. "
        "Return primary_theme, secondary_themes, theme_tags, theme_role, theme_confidence, theme_driver_type, "
        "theme_momentum, theme_evidence, theme_driver_summary, and theme_evidence_summary. "
        "Theme acceleration: identify whether filing evidence shows the theme directly driving revenue/segment growth, "
        "guidance, margin improvement, customer wins, or capacity expansion. Return filing_theme_growth_flag, "
        "filing_theme_guidance_flag, filing_theme_margin_flag, filing_theme_customer_win_flag, "
        "filing_theme_capacity_expansion_flag, and theme_acceleration_score. Use 1/0 flags only. "
        "Require evidence snippets in theme_evidence; no evidence means all acceleration flags must be 0. "
        "Set theme_tailwind_score and theme_acceleration_score to 0; deterministic scoring computes final theme scores later.\n\n"
        "Demote severity: if post_llm_demote_flag would be true, classify severity as soft, hard, or unknown. "
        "Hard means integrity, missing filing, going-concern, broken-thesis, or ununderwritable risk. "
        "Soft means ugly but potentially re-ratable. Unknown means demote signal exists but severity is unclear. "
        "Overrideable=1 only when evidence says a soft demote may still deserve starter underwriting. "
        "Return post_llm_demote_severity, post_llm_demote_reason_code, post_llm_demote_overrideable, and post_llm_demote_evidence.\n\n"
        f"Packets:\n{json.dumps(safe_packets, indent=2, ensure_ascii=True)}"
    )


def _int_field(row: dict[str, Any], key: str, lo: int, hi: int) -> int:
    try:
        value = int(row.get(key))
    except (TypeError, ValueError):
        raise ValueError(f"{key} invalid: {row.get(key)!r}") from None
    if value < lo or value > hi:
        raise ValueError(f"{key} out of range: {value}")
    return value


def _optional_int_field(row: dict[str, Any], key: str, lo: int, hi: int, default: int = 0) -> int:
    if key not in row or clean(row.get(key)) == "":
        return default
    return _int_field(row, key, lo, hi)


def _bucket_for(score: int) -> str:
    if score >= 7:
        return "inflecting"
    if score >= 3:
        return "constructive"
    if score >= 0:
        return "neutral"
    return "deteriorating"


def _score_addition_for(bucket: str, risk: int) -> int:
    if risk >= 4:
        return -3
    return {"inflecting": 3, "constructive": 1, "neutral": 0, "deteriorating": -3, "unscorable": 0}[bucket]


def validate_llm_result(payload: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    if clean(payload.get("sample_id")) != clean(packet.get("sample_id")):
        raise ValueError(f"sample_id mismatch: {payload.get('sample_id')} != {packet.get('sample_id')}")
    _validate_packet_source_availability(packet)
    causal = _int_field(payload, "causal_change", 0, 3)
    proof = _int_field(payload, "proof_alignment", 0, 3)
    durability = _int_field(payload, "durability", 0, 2)
    op_leverage = _int_field(payload, "operating_leverage_quality", 0, 2)
    risk = _int_field(payload, "negative_revision_risk", 0, 5)
    gap = _int_field(payload, "story_vs_numbers_gap_penalty", 0, 3)
    score = max(-5, min(10, causal + proof + durability + op_leverage - risk - gap))
    bucket = "unscorable" if clean(payload.get("narrative_delta_bucket")) == "unscorable" else _bucket_for(score)
    if bucket == "unscorable" and not clean(payload.get("blocking_issues")):
        raise ValueError("unscorable requires blocking_issues")
    confidence = clean(payload.get("confidence")).lower()
    if confidence not in {"low", "medium", "high"}:
        raise ValueError(f"invalid confidence: {confidence}")
    theme_confidence = clean(payload.get("theme_confidence") or "none").lower()
    if theme_confidence not in {"none", "low", "medium", "high"}:
        raise ValueError(f"invalid theme_confidence: {theme_confidence}")
    theme_role = clean(payload.get("theme_role") or "none")
    if theme_role not in {
        "direct_beneficiary",
        "supplier",
        "customer_exposure",
        "infrastructure_provider",
        "commodity_exposure",
        "platform_leader",
        "turnaround_with_theme_tailwind",
        "indirect_beneficiary",
        "none",
    }:
        raise ValueError(f"invalid theme_role: {theme_role}")
    theme_driver_type = clean(payload.get("theme_driver_type") or "none")
    if theme_driver_type not in {"revenue", "margin", "demand", "capacity", "pricing", "valuation", "none"}:
        raise ValueError(f"invalid theme_driver_type: {theme_driver_type}")
    theme_momentum = clean(payload.get("theme_momentum") or "unknown")
    if theme_momentum not in {"accelerating", "stable", "fading", "unknown"}:
        raise ValueError(f"invalid theme_momentum: {theme_momentum}")
    theme_tailwind = _optional_int_field(payload, "theme_tailwind_score", 0, 20)
    demote_severity = clean(payload.get("post_llm_demote_severity") or "none").lower()
    if demote_severity not in DEMOTE_SEVERITIES:
        raise ValueError(f"invalid post_llm_demote_severity: {demote_severity}")
    demote_reason = clean(payload.get("post_llm_demote_reason_code"))
    if demote_reason not in DEMOTE_REASON_CODES:
        raise ValueError(f"invalid post_llm_demote_reason_code: {demote_reason}")
    demote_overrideable = _optional_int_field(payload, "post_llm_demote_overrideable", 0, 1)
    demote_evidence = clean(payload.get("post_llm_demote_evidence"))
    derived_demote = int(risk >= 4 or gap >= 2 or bucket == "deteriorating")
    severity_demote = int(demote_severity in {"soft", "hard", "unknown"})
    if demote_severity == "none" and derived_demote:
        demote_severity = "unknown"
    if demote_severity == "none" and not derived_demote:
        demote_reason = ""
        demote_evidence = ""
        demote_overrideable = 0
    acceleration = normalized_theme_acceleration_fields(payload)
    secondary = payload.get("secondary_themes") or []
    tags = payload.get("theme_tags") or []
    evidence = payload.get("theme_evidence") or []
    if not isinstance(secondary, list) or not isinstance(tags, list) or not isinstance(evidence, list):
        raise ValueError("theme list fields must be arrays")
    normalized = {field: payload.get(field, "") for field in CSV_FIELDS}
    normalized.update(
        {
            "sample_id": clean(packet.get("sample_id")),
            "quarter": clean(payload.get("quarter") or packet.get("quarter")),
            "ticker": clean(payload.get("ticker") or packet.get("ticker")),
            "event_date": clean(payload.get("event_date") or packet.get("event_date")),
            "causal_change": causal,
            "proof_alignment": proof,
            "durability": durability,
            "operating_leverage_quality": op_leverage,
            "negative_revision_risk": risk,
            "story_vs_numbers_gap_penalty": gap,
            "narrative_delta_score": score,
            "narrative_delta_bucket": bucket,
            "score_addition": _score_addition_for(bucket, risk),
            "post_llm_candidate_flag": int(bucket in {"inflecting", "constructive"} and risk <= 3),
            "post_llm_high_priority_flag": int(score >= 7 and proof >= 3 and op_leverage >= 2 and risk <= 2),
            "post_llm_demote_flag": int(derived_demote or severity_demote),
            "post_llm_demote_severity": demote_severity,
            "post_llm_demote_reason_code": demote_reason,
            "post_llm_demote_overrideable": demote_overrideable,
            "post_llm_demote_evidence": demote_evidence,
            "confidence": confidence,
            "primary_theme": clean(payload.get("primary_theme")),
            "secondary_themes": json.dumps([clean(item) for item in secondary if clean(item)], ensure_ascii=True),
            "theme_tags": json.dumps([clean(item) for item in tags if clean(item)], ensure_ascii=True),
            "theme_role": theme_role,
            "theme_confidence": theme_confidence,
            "theme_driver_type": theme_driver_type,
            "theme_momentum": theme_momentum,
            "theme_evidence": json.dumps([clean(item) for item in evidence if clean(item)], ensure_ascii=True),
            **acceleration,
            "theme_tailwind_score": theme_tailwind,
            "theme_driver_summary": clean(payload.get("theme_driver_summary")),
            "theme_evidence_summary": clean(payload.get("theme_evidence_summary") or payload.get("theme_driver_summary")),
            "llm_source_accessions": clean(packet.get("llm_source_accessions")),
            "llm_source_document_dates": clean(packet.get("llm_source_document_dates")),
            "llm_source_available_date": _latest_source_date(packet.get("llm_source_document_dates")),
            "llm_prompt_input_hash": clean(packet.get("llm_prompt_input_hash")),
            "llm_prompt_input_allowed_docs_only": clean(packet.get("llm_prompt_input_allowed_docs_only") or "1"),
            "llm_generated_at": clean(payload.get("llm_generated_at")),
            "llm_model": clean(payload.get("llm_model") or packet.get("llm_model") or packet.get("model")),
            "llm_output_hash": clean(payload.get("llm_output_hash")) or _payload_hash(payload),
            "llm_cache_key": clean(packet.get("llm_cache_key")),
            "source_packet_path": clean(packet.get("source_packet_path")),
            "reasoning_effort": clean(packet.get("reasoning_effort")),
        }
    )
    return normalized


def _split_dates(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = value
    else:
        raw = re.split(r"[;,]", str(value or ""))
    return [str(item).strip()[:10] for item in raw if str(item).strip()]


def _latest_source_date(value: Any) -> str:
    dates = _split_dates(value)
    return max(dates) if dates else ""


def _validate_packet_source_availability(packet: dict[str, Any]) -> None:
    if clean(packet.get("llm_prompt_input_allowed_docs_only")) not in {"", "1", "true", "True"}:
        raise ValueError("LLM packet includes disallowed source documents")
    decision_date = clean(packet.get("decision_date") or packet.get("source_available_date"))
    if not decision_date:
        return
    for doc_date in _split_dates(packet.get("llm_source_document_dates")):
        if doc_date > decision_date[:10]:
            raise ValueError(f"future LLM source document: {doc_date} > {decision_date[:10]}")


def _payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def extract_json_payload(raw: str) -> Any:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start_candidates = [idx for idx in [text.find("{"), text.find("[")] if idx != -1]
        if not start_candidates:
            raise
        start = min(start_candidates)
        end = max(text.rfind("}"), text.rfind("]"))
        if end <= start:
            raise
        return json.loads(text[start : end + 1])


def codex_invoker(prompt: str, schema: dict[str, Any], model: str, reasoning_effort: str) -> str:
    codex_path = shutil.which("codex") or "/Applications/Codex.app/Contents/Resources/codex"
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as handle:
        json.dump(schema, handle)
        schema_path = handle.name
    proc = subprocess.run(
        [
            codex_path,
            "exec",
            "-m",
            model,
            "-c",
            f'model_reasoning_effort="{reasoning_effort}"',
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--output-schema",
            schema_path,
            prompt,
        ],
        text=True,
        capture_output=True,
    )
    stdout, stderr = proc.stdout, proc.stderr
    if proc.returncode != 0:
        raise RuntimeError(f"codex exit {proc.returncode}: {stderr[-1200:]}")
    return stdout


def _batched(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[idx : idx + size] for idx in range(0, len(items), size)]


def _validate_batch_results(results: Any, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(results, list) or len(results) != len(batch):
        raise ValueError("LLM result count mismatch")
    packet_by_id = {clean(packet.get("sample_id")): packet for packet in batch}
    result_by_id: dict[str, dict[str, Any]] = {}
    duplicate_ids: set[str] = set()
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("LLM result must be an object")
        sample_id = clean(result.get("sample_id"))
        if sample_id in result_by_id:
            duplicate_ids.add(sample_id)
        result_by_id[sample_id] = result
    if duplicate_ids:
        raise ValueError(f"duplicate LLM sample_ids: {sorted(duplicate_ids)}")
    expected_ids = set(packet_by_id)
    result_ids = set(result_by_id)
    missing = sorted(expected_ids - result_ids)
    unexpected = sorted(result_ids - expected_ids)
    if missing or unexpected:
        raise ValueError(f"LLM sample_id set mismatch: missing={missing} unexpected={unexpected}")
    return [validate_llm_result(result_by_id[clean(packet.get("sample_id"))], packet) for packet in batch]


def default_llm_cache_csv() -> Path:
    return sec_cache_root("llm_extractions", "daily_post_llm_cache.csv")


def _decode_csv_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for field in ("secondary_themes", "theme_tags", "theme_evidence"):
        value = out.get(field)
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                try:
                    out[field] = json.loads(text)
                except Exception:
                    out[field] = []
            elif text:
                out[field] = [text]
            else:
                out[field] = []
    return out


def read_cached_llm_rows_for_packets(
    packets: list[dict[str, Any]],
    *,
    cache_csv: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    cache_path = cache_csv or default_llm_cache_csv()
    packet_by_id = {clean(packet.get("sample_id")): packet for packet in packets if clean(packet.get("sample_id"))}
    found: dict[str, dict[str, Any]] = {}
    invalid = 0
    if cache_path.exists() and cache_path.stat().st_size:
        with cache_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames and "sample_id" in reader.fieldnames:
                for raw in reader:
                    sample_id = clean(raw.get("sample_id"))
                    packet = packet_by_id.get(sample_id)
                    if packet is None or sample_id in found:
                        continue
                    try:
                        found[sample_id] = validate_llm_result(_decode_csv_row(raw), packet)
                    except Exception:
                        invalid += 1
    missing = [packet for packet in packets if clean(packet.get("sample_id")) not in found]
    return [found[sample_id] for sample_id in sorted(found)], missing, {
        "llm_cache_path": str(cache_path),
        "llm_cache_expected_count": len(packet_by_id),
        "llm_cache_hit_count": len(found),
        "llm_cache_missing_count": len(missing),
        "llm_cache_invalid_count": invalid,
    }


def write_post_llm_csv(rows: list[dict[str, Any]], output_csv: Path) -> Path:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows([{field: row.get(field, "") for field in CSV_FIELDS} for row in rows])
    return output_csv


def save_llm_rows_to_cache(rows: list[dict[str, Any]], *, cache_csv: Path | None = None) -> dict[str, Any]:
    cache_path = cache_csv or default_llm_cache_csv()
    existing: dict[str, dict[str, Any]] = {}
    if cache_path.exists() and cache_path.stat().st_size:
        with cache_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames and "sample_id" in reader.fieldnames:
                for row in reader:
                    sample_id = clean(row.get("sample_id"))
                    if sample_id:
                        existing[sample_id] = {field: row.get(field, "") for field in CSV_FIELDS}
    upserted = 0
    for row in rows:
        sample_id = clean(row.get("sample_id"))
        if not sample_id:
            continue
        existing[sample_id] = {field: row.get(field, "") for field in CSV_FIELDS}
        upserted += 1
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8", dir=cache_path.parent, delete=False) as tmp:
        writer = csv.DictWriter(tmp, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for sample_id in sorted(existing):
            writer.writerow(existing[sample_id])
        tmp_path = Path(tmp.name)
    tmp_path.replace(cache_path)
    return {"llm_cache_path": str(cache_path), "llm_cache_upserted_count": upserted, "llm_cache_total_rows": len(existing)}


def run_llm_batches(
    packets: list[dict[str, Any]],
    *,
    output_dir: Path,
    invoker: Callable[[str, dict[str, Any], str, str], str] = codex_invoker,
    model: str,
    reasoning_effort: str,
    batch_size: int = 8,
    resume: bool = True,
    max_attempts: int = 2,
    shared_cache_csv: Path | None = None,
) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[dict[str, Any]] = []
    schema = result_schema()
    for batch_index, batch in enumerate(_batched(packets, batch_size), start=1):
        out_path = output_dir / f"batch_{batch_index:04d}.json"
        if resume and out_path.exists():
            try:
                saved_rows = json.loads(out_path.read_text(encoding="utf-8"))
                saved_ids = {clean(row.get("sample_id")) for row in saved_rows if isinstance(row, dict)}
                expected_ids = {clean(packet.get("sample_id")) for packet in batch}
                if saved_ids == expected_ids:
                    written.extend(_validate_batch_results(saved_rows, batch))
                    continue
            except Exception:
                pass
        prompt = build_prompt(batch)
        (output_dir / f"batch_{batch_index:04d}_prompt.txt").write_text(prompt, encoding="utf-8")
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                raw = invoker(prompt, schema, model, reasoning_effort)
                (output_dir / f"batch_{batch_index:04d}_attempt_{attempt}_raw.txt").write_text(raw, encoding="utf-8")
                parsed = extract_json_payload(raw)
                results = parsed["results"] if isinstance(parsed, dict) and "results" in parsed else parsed
                normalized = _validate_batch_results(results, batch)
                out_path.write_text(json.dumps(normalized, indent=2), encoding="utf-8")
                if shared_cache_csv is not None:
                    save_llm_rows_to_cache(normalized, cache_csv=shared_cache_csv)
                written.extend(normalized)
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                (output_dir / f"batch_{batch_index:04d}_attempt_{attempt}_error.txt").write_text(str(exc), encoding="utf-8")
        else:
            raise RuntimeError(f"batch_{batch_index:04d} failed: {last_error}")
    return written


def _ensure_post_llm_flags(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    risk = _optional_int_field(out, "negative_revision_risk", 0, 5)
    gap = _optional_int_field(out, "story_vs_numbers_gap_penalty", 0, 3)
    score = _optional_int_field(out, "narrative_delta_score", -5, 10)
    proof = _optional_int_field(out, "proof_alignment", 0, 3)
    op_leverage = _optional_int_field(out, "operating_leverage_quality", 0, 2)
    bucket = clean(out.get("narrative_delta_bucket"))
    out.setdefault("post_llm_candidate_flag", int(bucket in {"inflecting", "constructive"} and risk <= 3))
    out.setdefault("post_llm_high_priority_flag", int(score >= 7 and proof >= 3 and op_leverage >= 2 and risk <= 2))
    derived_demote = int(risk >= 4 or gap >= 2 or bucket == "deteriorating")
    severity = clean(out.get("post_llm_demote_severity") or "none").lower()
    if severity not in DEMOTE_SEVERITIES:
        severity = "unknown" if derived_demote else "none"
    severity_demote = int(severity in {"soft", "hard", "unknown"})
    if severity == "none" and derived_demote:
        severity = "unknown"
    out.setdefault("post_llm_demote_flag", int(derived_demote or severity_demote))
    out.setdefault("post_llm_demote_severity", severity)
    out.setdefault("post_llm_demote_reason_code", "")
    out.setdefault("post_llm_demote_overrideable", 0)
    out.setdefault("post_llm_demote_evidence", "")
    return out


def write_consolidated_csv(output_dir: Path, output_csv: Path) -> Path:
    rows: list[dict[str, Any]] = []
    for path in sorted(output_dir.glob("batch_*.json")):
        if re.fullmatch(r"batch_\d{4}\.json", path.name):
            rows.extend(_ensure_post_llm_flags(row) for row in json.loads(path.read_text(encoding="utf-8")))
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return output_csv
