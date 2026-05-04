import json
from typing import Any

import requests

from tradingagents.research.fundamental_autoresearch.autoresearch import (
    build_signal_registry_rows,
    run_constrained_autoresearch,
)
from tradingagents.research.fundamental_autoresearch.evaluate import evaluate_scored_rows
from tradingagents.research.fundamental_autoresearch.score import score_feature_row_with_weights


class QwenAutoresearchError(RuntimeError):
    pass


_COMPONENT_KEYS = (
    "health",
    "growth",
    "quality",
    "capital_discipline",
    "valuation",
)


def _format_weight(value: float) -> str:
    return f"{value:.2f}".replace(".", "p")


def _strategy_name(weights: dict[str, float]) -> str:
    parts = [f"qwen__health_{_format_weight(weights['health'])}"]
    if weights["growth"] < 0:
        parts.append(f"inv_growth_{_format_weight(abs(weights['growth']))}")
    if weights["quality"] < 0:
        parts.append(f"inv_quality_{_format_weight(abs(weights['quality']))}")
    if weights["capital_discipline"] > 0:
        parts.append(
            f"capital_discipline_{_format_weight(weights['capital_discipline'])}"
        )
    if weights["valuation"] > 0:
        parts.append(f"valuation_{_format_weight(weights['valuation'])}")
    return "__".join(parts)


def normalize_qwen_weight_proposal(proposal: dict[str, Any]) -> dict[str, float] | None:
    payload = proposal.get("weights", proposal)
    if not isinstance(payload, dict):
        return None

    try:
        raw_health = float(payload.get("health", 0.0))
        raw_growth = float(payload.get("growth", 0.0))
        raw_quality = float(payload.get("quality", 0.0))
        raw_capital_discipline = float(payload.get("capital_discipline", 0.0))
        raw_valuation = float(payload.get("valuation", 0.0))
    except (TypeError, ValueError):
        return None

    constrained = {
        "health": max(0.0, raw_health),
        "growth": -abs(raw_growth),
        "quality": -abs(raw_quality),
        "capital_discipline": max(0.0, raw_capital_discipline),
        "valuation": max(0.0, raw_valuation),
    }

    total_absolute = (
        constrained["health"]
        + abs(constrained["growth"])
        + abs(constrained["quality"])
        + constrained["capital_discipline"]
        + constrained["valuation"]
    )
    if total_absolute <= 0:
        return None

    normalized = {
        "health": round(constrained["health"] / total_absolute, 4),
        "growth": round(constrained["growth"] / total_absolute, 4),
        "quality": round(constrained["quality"] / total_absolute, 4),
        "capital_discipline": round(
            constrained["capital_discipline"] / total_absolute, 4
        ),
        "valuation": round(constrained["valuation"] / total_absolute, 4),
    }

    if normalized["health"] < 0.4:
        return None

    if normalized["health"] < max(
        abs(normalized["growth"]),
        abs(normalized["quality"]),
        normalized["capital_discipline"],
        normalized["valuation"],
    ):
        return None

    absolute_sum = (
        normalized["health"]
        + abs(normalized["growth"])
        + abs(normalized["quality"])
        + normalized["capital_discipline"]
        + normalized["valuation"]
    )
    if round(absolute_sum, 4) != 1.0:
        drift = round(1.0 - absolute_sum, 4)
        normalized["health"] = round(normalized["health"] + drift, 4)

    return normalized


def _extract_json_payload(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise QwenAutoresearchError("Qwen returned invalid JSON") from exc

    if not isinstance(payload, dict) or "proposals" not in payload:
        raise QwenAutoresearchError("Qwen response missing proposals")
    if not isinstance(payload["proposals"], list):
        raise QwenAutoresearchError("Qwen proposals must be a list")
    return payload


def _build_qwen_prompt(
    leaderboard: list[dict[str, Any]],
    *,
    proposal_count: int,
) -> str:
    compact = [
        {
            "strategy": row["strategy"],
            "weights": row["weights"],
            "metric": row["primary_metric_value"],
        }
        for row in leaderboard
    ]
    return (
        "/no_think\n"
        "You are proposing new off-grid fundamental factor weight configurations.\n"
        "Goal: improve 60d sector-neutral rank IC over the current constrained leaderboard.\n"
        "Rules:\n"
        "- health must stay positive and dominant\n"
        "- growth must be non-positive\n"
        "- quality must be non-positive\n"
        "- capital_discipline and valuation must be non-negative\n"
        "- propose bounded, realistic variants near the current leaders\n"
        "- return JSON only with shape {\"proposals\": [...]}.\n"
        f"- return exactly {proposal_count} proposals.\n\n"
        f"Current leaderboard:\n{json.dumps(compact, indent=2, sort_keys=True)}"
    )


def request_qwen_weight_proposals(
    *,
    base_url: str,
    model: str,
    leaderboard: list[dict[str, Any]],
    proposal_count: int,
    timeout_seconds: int = 120,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    prompt = _build_qwen_prompt(leaderboard, proposal_count=proposal_count)
    session = session or requests.Session()
    response = session.post(
        f"{base_url.rstrip('/')}/chat/completions",
        json={
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a quant research copilot. Return strict JSON only. /no_think"
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "temperature": 0.2,
            "max_tokens": 1200,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise QwenAutoresearchError("Qwen server response missing message content") from exc

    if not content:
        reasoning = ""
        try:
            reasoning = payload["choices"][0]["message"].get("reasoning", "")
        except (KeyError, IndexError, TypeError):
            reasoning = ""
        raise QwenAutoresearchError(
            "Qwen returned empty content"
            + (f" with reasoning preview: {reasoning[:240]!r}" if reasoning else "")
        )

    parsed = _extract_json_payload(content)
    return {
        "model": payload.get("model", model),
        "raw_content": content,
        "proposals": parsed["proposals"],
        "prompt": prompt,
    }


def run_qwen_autoresearch(
    rows: list[dict[str, Any]],
    *,
    dataset_name: str,
    base_url: str,
    model: str,
    proposal_count: int = 8,
    current_leaderboard_top_n: int = 5,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    current = run_constrained_autoresearch(
        rows,
        dataset_name=dataset_name,
        top_n=current_leaderboard_top_n,
        robustness_top_n=0,
    )
    proposal_bundle = request_qwen_weight_proposals(
        base_url=base_url,
        model=model,
        leaderboard=current["leaderboard"],
        proposal_count=proposal_count,
        timeout_seconds=timeout_seconds,
    )

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[tuple[float, float, float, float, float]] = set()

    for raw in proposal_bundle["proposals"]:
        normalized = normalize_qwen_weight_proposal(raw)
        if normalized is None:
            rejected.append({"raw": raw, "reason": "invalid_or_non_dominant"})
            continue
        key = tuple(normalized[k] for k in _COMPONENT_KEYS)
        if key in seen:
            rejected.append({"raw": raw, "reason": "duplicate"})
            continue
        seen.add(key)

        strategy = _strategy_name(normalized)
        scored_rows = []
        for row in rows:
            score = score_feature_row_with_weights(
                row,
                component_weights=normalized,
                strategy_name=strategy,
            )
            scored_rows.append(
                {
                    **row,
                    "fundamental_score": score.fundamental_score,
                }
            )
        summary = evaluate_scored_rows(
            scored_rows,
            dataset_name=dataset_name,
            score_version=strategy,
        )
        accepted.append(
            {
                "strategy": strategy,
                "weights": normalized,
                "primary_metric_name": summary.primary_metric_name,
                "primary_metric_value": summary.primary_metric_value,
                "coverage_ratio": summary.coverage_ratio,
                "observations": summary.observations,
            }
        )

    accepted = sorted(
        accepted,
        key=lambda row: row["primary_metric_value"],
        reverse=True,
    )
    if not accepted:
        raise QwenAutoresearchError("No valid Qwen proposals survived normalization")

    registry_rows = build_signal_registry_rows(accepted, top_robustness={})
    return {
        "model": proposal_bundle["model"],
        "prompt": proposal_bundle.get("prompt", ""),
        "raw_content": proposal_bundle["raw_content"],
        "proposal_count": len(proposal_bundle["proposals"]),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "current_leaderboard": current["leaderboard"],
        "normalized_proposals": [row["weights"] for row in accepted],
        "rejected_proposals": rejected,
        "leaderboard": registry_rows,
        "best_strategy": registry_rows[0],
        "registry_rows": registry_rows,
    }
