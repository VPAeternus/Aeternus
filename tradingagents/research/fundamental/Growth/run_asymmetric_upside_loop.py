from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

from autoresearch.filing_queue import load_filing_queue
from autoresearch.tsla_autoresearch_master import extract_json_payload


PROMPT_PATH = Path(__file__).resolve().parent / "asymmetric_upside_extraction_prompt.md"
DEFAULT_QUEUE = (
    Path(__file__).resolve().parent.parent
    / "autoresearch"
    / "filing_queue_mid2021_mid2024_bigtech7.jsonl"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run asymmetric upside extraction over a filing queue")
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--model", type=str, default="Qwen3.6-35B-A3B-oQ2")
    parser.add_argument("--api-base", type=str, default="http://127.0.0.1:8040/v1")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=1400)
    parser.add_argument("--max-section-chars", type=int, default=24000)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


def load_prompt_template() -> str:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    marker = "## Prompt"
    _, _, body = text.partition(marker)
    return body.strip()


def filing_text_from_packet(packet: dict, max_section_chars: int) -> str:
    parts: list[str] = []
    for key, value in packet.get("sections", {}).items():
        section_text = str(value or "").strip()
        if not section_text:
            continue
        heading = key.replace("_", " ").upper()
        parts.append(f"=== {heading} ===\n{section_text[:max_section_chars]}")
    return "\n\n".join(parts)


def build_prompt(template: str, packet: dict, max_section_chars: int) -> str:
    filing_text = filing_text_from_packet(packet, max_section_chars=max_section_chars)
    return (
        template.replace("{ticker}", str(packet.get("ticker", "")).strip())
        .replace("{form}", str(packet.get("form", "")).strip())
        .replace("{filed}", str(packet.get("filed", "")).strip())
        .replace("{filing_text}", filing_text)
    )


def write_state(state_path: Path, **updates: object) -> None:
    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = {}
    state.update(updates)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def generate_json(
    *,
    prompt: str,
    model: str,
    api_base: str,
    temperature: float,
    max_tokens: int,
) -> str:
    system_text = (
        "You are analyzing an SEC filing for a deterministic investment research pipeline. "
        "Use only the filing text provided. Do not use outside knowledge, market prices, analyst views, news, or future events. "
        "Do not infer beyond the text. If evidence is weak or absent, say so. "
        "Return valid JSON only. No Markdown. No commentary. "
        "Match the requested asymmetric_upside schema exactly."
    )
    base = api_base.rstrip("/")
    chat_payload = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stop": ["<|endoftext|>", "<|eot_id|>", "```"],
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": prompt},
        ],
    }
    response = requests.post(f"{base}/chat/completions", json=chat_payload, timeout=180)
    if response.ok:
        return response.json()["choices"][0]["message"]["content"]

    response_text = response.text
    if response.status_code == 400 and "chat_template" in response_text:
        completion_prompt = (
            "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n"
            f"{system_text} Begin immediately with {{ and end with }}."
            "<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
            f"{prompt}"
            "<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
        )
        completion_payload = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "prompt": completion_prompt,
            "stop": ["<|eot_id|>", "```"],
        }
        completion_response = requests.post(f"{base}/completions", json=completion_payload, timeout=180)
        completion_response.raise_for_status()
        return completion_response.json()["choices"][0]["text"]

    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def invoke_with_retries(
    *,
    prompt: str,
    model: str,
    api_base: str,
    temperature: float,
    max_tokens: int,
    artifact_dir: Path,
    max_attempts: int = 3,
) -> tuple[dict, int]:
    current_prompt = prompt
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            raw = generate_json(
                prompt=current_prompt,
                model=model,
                api_base=api_base,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            (artifact_dir / f"attempt_{attempt}_raw.txt").write_text(str(raw), encoding="utf-8")
            payload = extract_json_payload(raw)
            asymmetric = payload.get("asymmetric_upside", {})
            total_score = int(asymmetric.get("total_score", -1))
            if total_score < 0 or total_score > 5:
                raise ValueError(f"Invalid total_score: {total_score}")
            return payload, attempt
        except Exception as exc:
            last_error = exc
            (artifact_dir / f"attempt_{attempt}_error.txt").write_text(str(exc), encoding="utf-8")
            current_prompt = (
                prompt
                + "\n\nYour last response was invalid. Return only one JSON object exactly matching the schema. "
                + "Do not include markdown, preamble, chain-of-thought, or commentary."
            )
    raise ValueError(f"Asymmetric upside response invalid after {max_attempts} attempts: {last_error}")


def main() -> None:
    args = parse_args()
    queue_records = load_filing_queue(args.queue, start_index=args.start_index, limit=args.limit)
    template = load_prompt_template()

    args.base_dir.mkdir(parents=True, exist_ok=True)
    filings_dir = args.base_dir / "filings"
    filings_dir.mkdir(parents=True, exist_ok=True)
    state_path = args.base_dir / "loop_state.json"
    summary_path = args.base_dir / "summary.json"

    write_state(
        state_path,
        status="running",
        prompt_path=str(PROMPT_PATH),
        queue_path=str(args.queue),
        model=args.model,
        completed_packets=0,
        total_packets=len(queue_records),
        current_queue_id=None,
        current_packet_path=None,
    )

    outputs: list[dict] = []
    for idx, record in enumerate(queue_records):
        packet_path = Path(str(record["packet_path"]))
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        prompt = build_prompt(template, packet, max_section_chars=args.max_section_chars)
        write_state(
            state_path,
            status="running",
            prompt_path=str(PROMPT_PATH),
            queue_path=str(args.queue),
            model=args.model,
            completed_packets=idx,
            total_packets=len(queue_records),
            current_queue_id=record["queue_id"],
            current_packet_path=str(packet_path),
        )
        payload, attempts = invoke_with_retries(
            prompt=prompt,
            model=args.model,
            api_base=args.api_base,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            artifact_dir=filings_dir,
        )
        payload["attempts"] = attempts
        outputs.append(payload)
        out_name = f"{idx:03d}_{packet['ticker']}_{packet['filed']}_{packet['accn'].replace('-', '')}.json"
        (filings_dir / out_name).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        write_state(
            state_path,
            status="running",
            prompt_path=str(PROMPT_PATH),
            queue_path=str(args.queue),
            model=args.model,
            completed_packets=idx + 1,
            total_packets=len(queue_records),
            current_queue_id=None,
            current_packet_path=None,
        )

    summary = {
        "status": "complete",
        "prompt_path": str(PROMPT_PATH),
        "queue_path": str(args.queue),
        "model": args.model,
        "completed_packets": len(outputs),
        "total_packets": len(queue_records),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    state_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
