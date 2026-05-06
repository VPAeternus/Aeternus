from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

from autoresearch.tsla_autoresearch_master import extract_json_payload


BASE_DIR = Path(__file__).resolve().parent
PROMPT_PATH = BASE_DIR / "venture_llm_scoring_extraction_prompt.md"
EXTRACT_ROOT = BASE_DIR / "be_extracts"
MANIFEST_PATH = EXTRACT_ROOT / "manifest.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BE venture extraction loop over markdown filing extracts")
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--model", type=str, default="Qwen3.6-35B-A3B-oQ2")
    parser.add_argument("--api-base", type=str, default="http://127.0.0.1:8040/v1")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=1800)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


def load_prompt_template() -> str:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    marker = "## Prompt"
    _, _, body = text.partition(marker)
    return body.strip()


def load_manifest_rows() -> list[dict[str, str]]:
    rows = list(csv.DictReader(MANIFEST_PATH.open(encoding="utf-8")))
    rows.sort(key=lambda row: (row["filed"], row["accn"]))
    return rows


def frontmatter_and_body(md_path: Path) -> tuple[dict[str, str], str]:
    raw = md_path.read_text(encoding="utf-8")
    parts = raw.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"Invalid frontmatter format: {md_path}")
    meta_block = parts[1].strip()
    body = parts[2].strip()
    meta: dict[str, str] = {}
    for line in meta_block.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()
    return meta, body


def build_prompt(template: str, meta: dict[str, str], body: str) -> str:
    return (
        template.replace("{ticker}", meta.get("ticker", ""))
        .replace("{company}", "Bloom Energy")
        .replace("{form}", meta.get("form", ""))
        .replace("{filed}", meta.get("filed", ""))
        .replace("{accn}", meta.get("accn", ""))
        .replace("{filing_text}", body)
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
        "Do not infer beyond the text. If required evidence is missing, mark it missing. Do not fill gaps. "
        "Return valid JSON only. No Markdown. No commentary. "
        "Match the requested venture scoring extraction schema exactly."
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


def validate_payload(payload: dict) -> None:
    required_root = [
        "ticker",
        "company",
        "form",
        "filed",
        "accn",
        "required_sections_present",
        "missing_required_sections",
        "wave_exposure",
        "asymmetric_upside",
        "fundable_scaling",
        "wave_torque_operating_leverage",
        "incumbent_saturation_penalty",
        "false_promise_penalty",
        "data_completeness",
        "decision_summary",
    ]
    for key in required_root:
        if key not in payload:
            raise ValueError(f"Missing key: {key}")
    for key in [
        "wave_exposure",
        "asymmetric_upside",
        "fundable_scaling",
        "wave_torque_operating_leverage",
        "incumbent_saturation_penalty",
        "false_promise_penalty",
    ]:
        component = payload[key]
        if not isinstance(component, dict):
            raise ValueError(f"Invalid component: {key}")
        if "score" not in component or "evidence" not in component or "rationale" not in component:
            raise ValueError(f"Incomplete component: {key}")


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
            validate_payload(payload)
            return payload, attempt
        except Exception as exc:
            last_error = exc
            (artifact_dir / f"attempt_{attempt}_error.txt").write_text(str(exc), encoding="utf-8")
            current_prompt = (
                prompt
                + "\n\nYour last response was invalid. Return only one JSON object exactly matching the schema. "
                + "Do not include markdown, preamble, chain-of-thought, or commentary."
            )
    raise ValueError(f"BE extraction invalid after {max_attempts} attempts: {last_error}")


def main() -> None:
    args = parse_args()
    rows = load_manifest_rows()
    rows = rows[args.start_index :]
    if args.limit is not None:
        rows = rows[: args.limit]
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
        extract_root=str(EXTRACT_ROOT / "sec_parser"),
        model=args.model,
        completed_packets=0,
        total_packets=len(rows),
        current_extract_path=None,
    )

    outputs: list[dict] = []
    for idx, row in enumerate(rows):
        md_rel = row["sec_parser_file"]
        md_path = EXTRACT_ROOT / md_rel
        meta, body = frontmatter_and_body(md_path)
        prompt = build_prompt(template, meta, body)
        write_state(
            state_path,
            status="running",
            prompt_path=str(PROMPT_PATH),
            extract_root=str(EXTRACT_ROOT / "sec_parser"),
            model=args.model,
            completed_packets=idx,
            total_packets=len(rows),
            current_extract_path=str(md_path),
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
        out_name = md_path.stem + ".json"
        (filings_dir / out_name).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        write_state(
            state_path,
            status="running",
            prompt_path=str(PROMPT_PATH),
            extract_root=str(EXTRACT_ROOT / "sec_parser"),
            model=args.model,
            completed_packets=idx + 1,
            total_packets=len(rows),
            current_extract_path=None,
        )

    summary = {
        "status": "complete",
        "prompt_path": str(PROMPT_PATH),
        "extract_root": str(EXTRACT_ROOT / "sec_parser"),
        "model": args.model,
        "completed_packets": len(outputs),
        "total_packets": len(rows),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    state_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
