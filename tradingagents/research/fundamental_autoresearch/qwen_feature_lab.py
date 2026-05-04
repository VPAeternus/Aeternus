import json
from typing import Any

import requests

from tradingagents.research.fundamental_autoresearch.autoresearch import (
    build_signal_registry_rows,
    run_constrained_autoresearch,
)
from tradingagents.research.fundamental_autoresearch.evaluate import evaluate_scored_rows
from tradingagents.research.fundamental_autoresearch.score import (
    get_component_catalog,
    score_feature_row_with_weights,
)


class QwenFeatureLabError(RuntimeError):
    pass


_BASE_STRATEGY = {
    "strategy": "health_0p5__inv_growth_0p1__inv_quality_0p4",
    "weights": {
        "health": 0.5,
        "growth": -0.1,
        "quality": -0.4,
        "capital_discipline": 0.0,
        "valuation": 0.0,
    },
}

_EXPERIMENTAL_COMPONENTS = (
    "growth_acceleration",
    "margin_expansion",
    "quality_tension_inverse",
    "balance_sheet_resilience",
)

_EXPERIMENTAL_COMPONENT_DESCRIPTIONS = {
    "growth_acceleration": "Rewards improving revenue/FCF acceleration instead of raw visible growth.",
    "margin_expansion": "Rewards positive operating/gross margin change versus the prior comparable period.",
    "quality_tension_inverse": "Rewards high-quality businesses that are not obviously over-loved on valuation.",
    "balance_sheet_resilience": "Rewards resilience from liquidity and leverage strength while penalizing stress.",
}


def _format_weight(value: float) -> str:
    return f"{value:.2f}".replace(".", "p")


def _strategy_name(weights: dict[str, float]) -> str:
    base_weight = round(
        1.0 - sum(weights.get(name, 0.0) for name in _EXPERIMENTAL_COMPONENTS),
        4,
    )
    parts = [f"qwen_feature__base_{_format_weight(base_weight)}"]
    for name in _EXPERIMENTAL_COMPONENTS:
        weight = weights.get(name, 0.0)
        if weight > 0:
            parts.append(f"{name}_{_format_weight(weight)}")
    return "__".join(parts)


def normalize_qwen_feature_lab_proposal(
    proposal: dict[str, Any],
) -> tuple[str, ...] | None:
    raw_components = proposal.get("components")
    if raw_components is None:
        payload = proposal.get("weights", proposal)
        if not isinstance(payload, dict):
            return None
        ranked = []
        for name in _EXPERIMENTAL_COMPONENTS:
            try:
                value = float(payload.get(name, 0.0))
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                ranked.append((name, value))
        ranked.sort(key=lambda row: row[1], reverse=True)
        raw_components = [name for name, _ in ranked[:2]]

    if not isinstance(raw_components, list):
        return None

    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_components:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if name in _EXPERIMENTAL_COMPONENTS and name not in seen:
            normalized.append(name)
            seen.add(name)

    if len(normalized) == 0 or len(normalized) > 2:
        return None

    return tuple(normalized)


def expand_qwen_feature_lab_components(
    components: tuple[str, ...],
) -> list[dict[str, float]]:
    if len(components) == 0 or len(components) > 2:
        return []

    residuals = [0.10, 0.15] if len(components) == 1 else [0.10, 0.15, 0.20]
    configs: list[dict[str, float]] = []
    seen: set[tuple[float, ...]] = set()

    for residual in residuals:
        if len(components) == 1:
            splits = [{components[0]: residual}]
        else:
            equal = round(residual / 2.0, 4)
            splits = [{components[0]: equal, components[1]: equal}]
            if residual >= 0.15:
                heavy = round(residual * (2.0 / 3.0), 4)
                light = round(residual - heavy, 4)
                splits.append({components[0]: heavy, components[1]: light})
                splits.append({components[0]: light, components[1]: heavy})

        base_weight = round(1.0 - residual, 4)
        for split in splits:
            final_weights = {
                name: round(value * base_weight, 4)
                for name, value in _BASE_STRATEGY["weights"].items()
            }
            for name, value in split.items():
                final_weights[name] = round(value, 4)

            absolute_sum = round(sum(abs(value) for value in final_weights.values()), 4)
            if absolute_sum != 1.0:
                drift = round(1.0 - absolute_sum, 4)
                final_weights["health"] = round(final_weights["health"] + drift, 4)

            key = tuple(round(final_weights.get(name, 0.0), 4) for name in get_component_catalog())
            if key in seen:
                continue
            seen.add(key)
            configs.append(final_weights)

    return configs


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
        raise QwenFeatureLabError("Qwen returned invalid JSON") from exc

    if not isinstance(payload, dict) or "proposals" not in payload:
        raise QwenFeatureLabError("Qwen response missing proposals")
    if not isinstance(payload["proposals"], list):
        raise QwenFeatureLabError("Qwen proposals must be a list")
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
        "You are proposing bounded experimental overlays for a proven fundamental strategy.\n"
        "Goal: improve 60d sector-neutral rank IC.\n"
        "Base strategy is fixed and must remain dominant.\n"
        "Rules:\n"
        "- Return strict JSON only with shape {\"proposals\": [...]}.\n"
        f"- Return exactly {proposal_count} proposals.\n"
        "- Each proposal must include a `components` list with one or two experimental component names.\n"
        "- Do not propose numeric weights. The evaluator will test weight grids automatically.\n"
        "- Prefer meaningful combinations, not tiny perturbations.\n\n"
        f"Base strategy:\n{json.dumps(_BASE_STRATEGY, indent=2, sort_keys=True)}\n\n"
        f"Experimental components:\n{json.dumps(_EXPERIMENTAL_COMPONENT_DESCRIPTIONS, indent=2, sort_keys=True)}\n\n"
        f"Current leaderboard:\n{json.dumps(compact, indent=2, sort_keys=True)}"
    )


def request_qwen_feature_lab_proposals(
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
            "max_tokens": 1600,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise QwenFeatureLabError("Qwen server response missing message content") from exc

    if not content:
        raise QwenFeatureLabError("Qwen returned empty content")

    parsed = _extract_json_payload(content)
    return {
        "model": payload.get("model", model),
        "raw_content": content,
        "proposals": parsed["proposals"],
        "prompt": prompt,
    }


def run_qwen_feature_lab(
    rows: list[dict[str, Any]],
    *,
    dataset_name: str,
    base_url: str,
    model: str,
    proposal_count: int = 4,
    current_leaderboard_top_n: int = 5,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    current = run_constrained_autoresearch(
        rows,
        dataset_name=dataset_name,
        top_n=current_leaderboard_top_n,
        robustness_top_n=0,
    )
    proposal_bundle = request_qwen_feature_lab_proposals(
        base_url=base_url,
        model=model,
        leaderboard=current["leaderboard"],
        proposal_count=proposal_count,
        timeout_seconds=timeout_seconds,
    )

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[tuple[float, ...]] = set()

    for raw in proposal_bundle["proposals"]:
        components = normalize_qwen_feature_lab_proposal(raw)
        if components is None:
            rejected.append({"raw": raw, "reason": "invalid_components"})
            continue

        candidate_weights = expand_qwen_feature_lab_components(components)
        if not candidate_weights:
            rejected.append({"raw": raw, "reason": "no_expandable_candidates"})
            continue

        accepted_for_raw: list[dict[str, Any]] = []
        for normalized in candidate_weights:
            key = tuple(round(normalized.get(name, 0.0), 4) for name in get_component_catalog())
            if key in seen:
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
            accepted_for_raw.append(
                {
                    "strategy": strategy,
                    "weights": normalized,
                    "components": list(components),
                    "primary_metric_name": summary.primary_metric_name,
                    "primary_metric_value": summary.primary_metric_value,
                    "coverage_ratio": summary.coverage_ratio,
                    "observations": summary.observations,
                }
            )

        if not accepted_for_raw:
            rejected.append({"raw": raw, "reason": "duplicate_or_exhausted"})
            continue

        accepted_for_raw.sort(key=lambda row: row["primary_metric_value"], reverse=True)
        accepted.append(accepted_for_raw[0])

    accepted = sorted(
        accepted,
        key=lambda row: row["primary_metric_value"],
        reverse=True,
    )
    if not accepted:
        raise QwenFeatureLabError("No valid Qwen feature-lab proposals survived normalization")

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
        "base_strategy": _BASE_STRATEGY,
        "experimental_components": dict(_EXPERIMENTAL_COMPONENT_DESCRIPTIONS),
    }
