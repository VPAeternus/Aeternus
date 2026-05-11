from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACKETS = ROOT / "Growth" / "earnings_8k_sec_parser" / "llm_spec_convex_all_2022Q4_2023Q2_packets.jsonl"
DEFAULT_OUTPUT_DIR = ROOT / "Growth" / "earnings_8k_sec_parser" / "llm_spec_convex_all_2022Q4_2023Q2_llm"
DEFAULT_CONSOLIDATED = ROOT / "Growth" / "earnings_8k_sec_parser" / "llm_spec_convex_all_2022Q4_2023Q2_extractions.csv"

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
    "theme_tailwind_score",
    "theme_driver_summary",
    "theme_evidence_summary",
]


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def read_packets(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def scrub_packet(packet: dict[str, Any]) -> dict[str, Any]:
    blocked = {"return_10d_pct", "return_20d_pct", "return_30d_pct", "return_60d_pct", "return_90d_pct", "entry_open", "tradable_date"}
    return {key: value for key, value in packet.items() if key not in blocked}


def build_prompt(packets: list[dict[str, Any]]) -> str:
    safe_packets = [scrub_packet(packet) for packet in packets]
    return f"""You are reviewing SEC 8-K Item 2.02 / EX-99.1 earnings-release evidence packets for an investment research pipeline.

Rules:
- Use only evidence inside each packet.
- Do not use stock price, future returns, analyst expectations, news, or outside knowledge.
- Do not infer missing facts. If evidence is absent, score conservatively.
- Return JSON only, matching schema: {{"results": [ ... ]}}.
- Include one result for every input packet, same order.

Scoring formula:
narrative_delta_score =
  causal_change
+ proof_alignment
+ durability
+ operating_leverage_quality
- negative_revision_risk
- story_vs_numbers_gap_penalty

Field ranges:
- causal_change: integer 0-3
- proof_alignment: integer 0-3
- durability: integer 0-2
- operating_leverage_quality: integer 0-2
- negative_revision_risk: integer 0-5
- story_vs_numbers_gap_penalty: integer 0-3
- narrative_delta_score: integer formula result, clipped only if below -5 or above 10
- narrative_delta_bucket: inflecting if score >= 7, constructive if 3-6, neutral if 0-2, deteriorating if <0, unscorable only if evidence cannot be read
- score_addition: inflecting +3, constructive +1, neutral 0, deteriorating -3, unscorable 0
- hard override: if negative_revision_risk >= 4, score_addition must be -3
- confidence: low, medium, or high

Interpretation:
- causal_change asks whether filing explains real business change, not just reports numbers.
- proof_alignment asks whether hard numbers support the story.
- durability asks whether change looks multi-quarter/structural.
- operating_leverage_quality asks whether driver converts into margin/profit/cash economics.
- negative_revision_risk asks whether future numbers may come down due to guidance cut, shortfall, demand break, liquidity issue, severe margin pressure, regulatory shock, or execution miss.
- story_vs_numbers_gap_penalty asks whether narrative is ahead of or contradicted by numbers.

Adaptive theme classification:
- Identify any macro, sector, product, commodity, infrastructure, technology, or cycle-driven theme that could be causing a re-rating.
- Do not force AI/data-center; AI is only one possible theme.
- Return primary_theme, secondary_themes, theme_tags, theme_role, theme_confidence, theme_driver_type, theme_momentum, theme_evidence, theme_driver_summary, and theme_evidence_summary.
- Set theme_tailwind_score to 0. Deterministic scoring computes final theme score later.

Output each result with these exact keys:
sample_id, quarter, ticker, event_date, causal_change, proof_alignment, durability, operating_leverage_quality, negative_revision_risk, story_vs_numbers_gap_penalty, narrative_delta_score, narrative_delta_bucket, score_addition, detected_driver_category, detected_driver_name, evidence_positive, evidence_risk, confidence, blocking_issues, primary_theme, secondary_themes, theme_tags, theme_role, theme_confidence, theme_driver_type, theme_momentum, theme_evidence, theme_tailwind_score, theme_driver_summary, theme_evidence_summary.

Packets:
{json.dumps(safe_packets, indent=2, ensure_ascii=True)}
"""


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


def int_field(row: dict[str, Any], key: str, lo: int, hi: int) -> int:
    value = row.get(key)
    if isinstance(value, bool):
        raise ValueError(f"{key} bool invalid")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{key} invalid: {value!r}") from None
    if parsed < lo or parsed > hi:
        raise ValueError(f"{key} out of range: {parsed}")
    return parsed


def optional_int_field(row: dict[str, Any], key: str, lo: int, hi: int, default: int = 0) -> int:
    if key not in row or clean(row.get(key)) == "":
        return default
    return int_field(row, key, lo, hi)


def bucket_for(score: int) -> str:
    if score >= 7:
        return "inflecting"
    if score >= 3:
        return "constructive"
    if score >= 0:
        return "neutral"
    return "deteriorating"


def score_addition_for(bucket: str, risk: int) -> int:
    if risk >= 4:
        return -3
    return {"inflecting": 3, "constructive": 1, "neutral": 0, "deteriorating": -3, "unscorable": 0}[bucket]


def validate_result(payload: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    if clean(payload.get("sample_id")) != clean(packet.get("sample_id")):
        raise ValueError(f"sample_id mismatch: {payload.get('sample_id')} != {packet.get('sample_id')}")

    causal = int_field(payload, "causal_change", 0, 3)
    proof = int_field(payload, "proof_alignment", 0, 3)
    durability = int_field(payload, "durability", 0, 2)
    op_leverage = int_field(payload, "operating_leverage_quality", 0, 2)
    risk = int_field(payload, "negative_revision_risk", 0, 5)
    gap = int_field(payload, "story_vs_numbers_gap_penalty", 0, 3)
    score = max(-5, min(10, causal + proof + durability + op_leverage - risk - gap))

    model_bucket = clean(payload.get("narrative_delta_bucket"))
    if model_bucket == "unscorable":
        blocking = clean(payload.get("blocking_issues"))
        if not blocking:
            raise ValueError("unscorable requires blocking_issues")
        bucket = "unscorable"
    else:
        bucket = bucket_for(score)

    score_addition = score_addition_for(bucket, risk)

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
            "score_addition": score_addition,
            "confidence": confidence,
            "primary_theme": clean(payload.get("primary_theme")),
            "secondary_themes": json.dumps([clean(item) for item in secondary if clean(item)], ensure_ascii=True),
            "theme_tags": json.dumps([clean(item) for item in tags if clean(item)], ensure_ascii=True),
            "theme_role": theme_role,
            "theme_confidence": theme_confidence,
            "theme_driver_type": theme_driver_type,
            "theme_momentum": theme_momentum,
            "theme_evidence": json.dumps([clean(item) for item in evidence if clean(item)], ensure_ascii=True),
            "theme_tailwind_score": optional_int_field(payload, "theme_tailwind_score", 0, 20),
            "theme_driver_summary": clean(payload.get("theme_driver_summary")),
            "theme_evidence_summary": clean(payload.get("theme_evidence_summary") or payload.get("theme_driver_summary")),
        }
    )
    return normalized


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
            "theme_tailwind_score": {"type": "integer", "minimum": 0, "maximum": 20},
            "theme_driver_summary": {"type": "string"},
            "theme_evidence_summary": {"type": "string"},
        },
        "required": CSV_FIELDS,
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"results": {"type": "array", "items": item}},
        "required": ["results"],
    }


def invoke_codex(
    prompt: str,
    *,
    model: str,
    reasoning_effort: str,
    workdir: Path,
    output_dir: Path,
    batch_name: str,
) -> str:
    codex_path = shutil.which("codex") or "/Applications/Codex.app/Contents/Resources/codex"
    output_path = output_dir / f"{batch_name}_raw.txt"
    schema_path = output_dir / f"{batch_name}_schema.json"
    schema_path.write_text(json.dumps(result_schema(), indent=2), encoding="utf-8")
    cmd = [
        codex_path,
        "exec",
        "-m",
        model,
        "-c",
        f'model_reasoning_effort="{reasoning_effort}"',
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "-C",
        str(workdir),
        "--output-schema",
        str(schema_path),
        "-o",
        str(output_path),
        prompt,
    ]
    proc = subprocess.run(cmd, cwd=workdir, text=True, capture_output=True)
    (output_dir / f"{batch_name}_stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (output_dir / f"{batch_name}_stderr.txt").write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"codex exit {proc.returncode}: {proc.stderr[-1200:]}")
    return output_path.read_text(encoding="utf-8")


def batched(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[idx : idx + size] for idx in range(0, len(items), size)]


def batch_done_path(output_dir: Path, batch_index: int) -> Path:
    return output_dir / f"batch_{batch_index:04d}.json"


def run_batches(
    packets: list[dict[str, Any]],
    *,
    output_dir: Path,
    model: str,
    reasoning_effort: str,
    batch_size: int,
    max_attempts: int,
    start_index: int,
    limit: int | None,
    resume: bool,
) -> list[dict[str, Any]]:
    selected = packets[start_index : start_index + limit if limit is not None else None]
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[dict[str, Any]] = []
    for batch_offset, batch in enumerate(batched(selected, batch_size), start=1):
        batch_index = start_index // batch_size + batch_offset
        out_path = batch_done_path(output_dir, batch_index)
        if resume and out_path.exists():
            written.extend(json.loads(out_path.read_text(encoding="utf-8")))
            continue
        prompt = build_prompt(batch)
        batch_name = f"batch_{batch_index:04d}"
        (output_dir / f"{batch_name}_prompt.txt").write_text(prompt, encoding="utf-8")
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                raw = invoke_codex(
                    prompt,
                    model=model,
                    reasoning_effort=reasoning_effort,
                    workdir=ROOT,
                    output_dir=output_dir,
                    batch_name=f"{batch_name}_attempt_{attempt}",
                )
                parsed = extract_json_payload(raw)
                results = parsed["results"] if isinstance(parsed, dict) and "results" in parsed else parsed
                if not isinstance(results, list):
                    raise ValueError("model output must be a JSON array or object with results array")
                if len(results) != len(batch):
                    raise ValueError(f"result count mismatch: {len(results)} != {len(batch)}")
                normalized = [validate_result(result, packet) for result, packet in zip(results, batch)]
                out_path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")
                written.extend(normalized)
                print(f"wrote {out_path} rows={len(normalized)}")
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                (output_dir / f"{batch_name}_attempt_{attempt}_error.txt").write_text(str(exc), encoding="utf-8")
                prompt = prompt + "\n\nPrevious response failed validation. Return valid JSON only. Fix formula, bucket, and score_addition exactly."
        else:
            raise RuntimeError(f"{batch_name} failed after {max_attempts} attempts: {last_error}")
    return written


def write_consolidated_csv(output_dir: Path, output_csv: Path) -> Path:
    rows: list[dict[str, Any]] = []
    for path in sorted(output_dir.glob("batch_*.json")):
        if not re.fullmatch(r"batch_\d{4}\.json", path.name):
            continue
        rows.extend(json.loads(path.read_text(encoding="utf-8")))
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return output_csv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LLM narrative extraction over spec_convex packets")
    parser.add_argument("--packets", type=Path, default=DEFAULT_PACKETS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_CONSOLIDATED)
    parser.add_argument("--model", default="gpt-5.4-mini")
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    packets = read_packets(args.packets)
    run_batches(
        packets,
        output_dir=args.output_dir,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        batch_size=args.batch_size,
        max_attempts=args.max_attempts,
        start_index=args.start_index,
        limit=args.limit,
        resume=not args.no_resume,
    )
    csv_path = write_consolidated_csv(args.output_dir, args.output_csv)
    print(f"wrote consolidated CSV {csv_path}")


if __name__ == "__main__":
    main()
