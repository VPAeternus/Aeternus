from __future__ import annotations

import json
from typing import Any, Dict, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from tradingagents.dataflows.claude_cli import ChatClaudeCLI
from tradingagents.dataflows.codex_cli import ChatCodexCLI
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.session_assembler import (
    build_session_score,
    gather_computation_data,
    write_analysis_report,
)

SUPPORTED_SESSION_PROVIDERS = {"claude", "gpt"}

SESSION_RESEARCH_SYSTEM_PROMPT = """
You are the Aeternus session research engine.

You will receive a ticker, queue context, and a structured computation packet.
Your job is to synthesize that packet into a complete investment-research payload.

Rules:
- Use only the provided packet and your financial reasoning.
- Do not invent precise market levels, dates, or facts that are not supported by the packet.
- If evidence is weak or missing, say so directly.
- Keep each report decision-useful and concise.
- Return exactly one JSON object and no surrounding prose.

Required JSON keys:
- market_report
- sentiment_report
- news_report
- fundamentals_report
- investment_plan
- final_trade_decision
- trader_investment_decision

`final_trade_decision` must begin with:
Recommendation: **BUY**
or
Recommendation: **HOLD**
or
Recommendation: **SELL**
""".strip()


_REPORT_COMPLETENESS_KEYS = (
    "fundamentals_report",
    "market_report",
    "sentiment_report",
    "news_report",
    "investment_plan",
    "final_trade_decision",
)


def _strip_code_fence(text: str) -> str:
    value = str(text or "").strip()
    if not value.startswith("```"):
        return value
    lines = value.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_completion_payload(text: str) -> Dict[str, Any]:
    candidates = [str(text or "").strip()]
    stripped = _strip_code_fence(text)
    if stripped and stripped not in candidates:
        candidates.append(stripped)
    for candidate in candidates:
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise RuntimeError("session research completion did not return a JSON object")


def _fallback_recommendation(score_dict: Dict[str, Any]) -> str:
    rating = str(score_dict.get("rating", "")).upper()
    if "SELL" in rating:
        return "SELL"
    if "BUY" in rating:
        return "BUY"
    if "HOLD" in rating:
        return "HOLD"
    score = score_dict.get("aeternus_score")
    if isinstance(score, (int, float)):
        if float(score) >= 60.0:
            return "BUY"
        if float(score) < 40.0:
            return "SELL"
    return "HOLD"


def _build_research_prompt(
    ticker: str,
    analysis_date: str,
    computation_data: Dict[str, Any],
    queue_context: Optional[Dict[str, Any]],
) -> str:
    context = queue_context or {}
    packet = json.dumps(computation_data, indent=2, default=str)
    queue_json = json.dumps(context, indent=2, default=str)
    return (
        f"Ticker: {str(ticker).upper().strip()}\n"
        f"Analysis date: {str(analysis_date).strip()}\n\n"
        "Queue context:\n"
        f"{queue_json}\n\n"
        "Computation packet:\n"
        f"{packet}\n\n"
        "Return the required JSON object now."
    )


def _build_model(provider: str, config: Dict[str, Any]):
    provider_name = str(provider or "").strip().lower()
    if provider_name == "claude":
        return ChatClaudeCLI(
            model=str(config.get("claude_cli_deep_model", "claude-sonnet-4-6")),
            fallback_model=str(
                config.get("claude_cli_fallback_model", "claude-haiku-4-5-20251001")
            ),
            timeout=int(
                config.get(
                    "claude_cli_analyst_timeout",
                    config.get("claude_cli_timeout", 240),
                )
            ),
        )
    if provider_name == "gpt":
        return ChatCodexCLI(
            model=str(config.get("codex_cli_deep_model", "gpt-5.4")),
            reasoning_effort=str(
                config.get("codex_cli_deep_reasoning_effort", "high")
            ),
            timeout=int(config.get("codex_cli_timeout_seconds", 300)),
            binary=str(config.get("codex_cli_binary", "codex")),
        )
    raise ValueError(f"Unsupported session research provider: {provider}")


def _run_research_completion(
    *,
    provider: str,
    ticker: str,
    analysis_date: str,
    computation_data: Dict[str, Any],
    queue_context: Optional[Dict[str, Any]],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    model = _build_model(provider, config)
    prompt = _build_research_prompt(
        ticker=ticker,
        analysis_date=analysis_date,
        computation_data=computation_data,
        queue_context=queue_context,
    )
    result = model.invoke(
        [
            SystemMessage(content=SESSION_RESEARCH_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]
    )
    content = result.content if isinstance(result.content, str) else str(result.content)
    return _parse_completion_payload(content)


def _normalize_outputs(
    payload: Dict[str, Any],
    score_dict: Dict[str, Any],
) -> Dict[str, Any]:
    outputs = dict(payload or {})
    for key in (
        "market_report",
        "sentiment_report",
        "news_report",
        "fundamentals_report",
        "investment_plan",
        "final_trade_decision",
        "trader_investment_decision",
    ):
        outputs[key] = str(outputs.get(key, "") or "").strip()

    if not outputs["final_trade_decision"]:
        recommendation = _fallback_recommendation(score_dict)
        outputs["final_trade_decision"] = (
            f"Recommendation: **{recommendation}**\n\n"
            "Rationale: Session research engine fallback recommendation."
        )
    if not outputs["trader_investment_decision"]:
        outputs["trader_investment_decision"] = outputs["final_trade_decision"]
    return outputs


def _score_or_none(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _delta_or_none(before: Any, after: Any) -> Optional[float]:
    left = _score_or_none(before)
    right = _score_or_none(after)
    if left is None or right is None:
        return None
    return round(right - left, 4)


def _merge_llm_influence(
    *,
    base_score: Dict[str, Any],
    final_score: Dict[str, Any],
    outputs: Dict[str, Any],
) -> Dict[str, Any]:
    merged = dict(final_score or {})
    base_value = _score_or_none(base_score.get("aeternus_score"))
    final_value = _score_or_none(final_score.get("aeternus_score"))
    base_conf = base_score.get("confidence")
    final_conf = final_score.get("confidence")
    base_models = dict(base_score.get("ensemble_model_scores") or {})
    final_models = dict(final_score.get("ensemble_model_scores") or {})
    debate_components = {}
    for key in ("research_debate", "trader_verdict", "risk_verdict"):
        before = base_models.get(key)
        after = final_models.get(key)
        debate_components[key] = {
            "before": before,
            "after": after,
            "delta": _delta_or_none(before, after),
        }
    active_debate_components = sorted(
        key for key, payload in debate_components.items() if payload.get("after") is not None
    )
    present = sum(1 for key in _REPORT_COMPLETENESS_KEYS if str(outputs.get(key, "")).strip())
    influence = {
        "base_score_pre_llm": base_value,
        "final_score_post_llm": final_value,
        "score_delta": _delta_or_none(base_value, final_value),
        "base_confidence_pre_llm": base_conf,
        "final_confidence_post_llm": final_conf,
        "confidence_delta": _delta_or_none(base_conf, final_conf),
        "debate_components": debate_components,
        "active_debate_components": active_debate_components,
        "report_completeness": {
            "present_keys": present,
            "total_keys": len(_REPORT_COMPLETENESS_KEYS),
        },
    }
    merged["pre_llm_score"] = base_value
    merged["pre_llm_confidence"] = base_conf
    merged["llm_influence"] = influence
    return merged


def run_session_research(
    *,
    ticker: str,
    analysis_date: str,
    provider: str = "claude",
    queue_context: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> str:
    provider_name = str(provider or "").strip().lower()
    if provider_name not in SUPPORTED_SESSION_PROVIDERS:
        raise ValueError(f"Unsupported session research provider: {provider}")

    runtime_config = dict(DEFAULT_CONFIG)
    if isinstance(config, dict):
        runtime_config.update(config)

    context = dict(queue_context or {})
    computation_data = gather_computation_data(
        ticker=str(ticker).upper().strip(),
        date=str(analysis_date).strip(),
        sector=str(context.get("sector", "") or ""),
        asset_class=str(context.get("asset_class", "Equity") or "Equity"),
    )
    # Deterministic base score (no LLM outputs) for pre/post influence tracing.
    base_score = build_session_score(computation_data, {})
    outputs = _run_research_completion(
        provider=provider_name,
        ticker=str(ticker).upper().strip(),
        analysis_date=str(analysis_date).strip(),
        computation_data=computation_data,
        queue_context=context,
        config=runtime_config,
    )
    normalized_outputs = _normalize_outputs(outputs, base_score)
    score_dict = build_session_score(computation_data, normalized_outputs)
    score_dict = _merge_llm_influence(
        base_score=base_score,
        final_score=score_dict,
        outputs=normalized_outputs,
    )
    return write_analysis_report(
        ticker=str(ticker).upper().strip(),
        date=str(analysis_date).strip(),
        computation_data=computation_data,
        sonnet_outputs=normalized_outputs,
        score_dict=score_dict,
        queue_context=context,
    )
