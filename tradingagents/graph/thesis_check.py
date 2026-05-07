import json
from datetime import datetime
from typing import Any, Dict, List

from tradingagents.agents.utils.agent_utils import extract_text_content, make_cached_system_message


class ThesisChecker:
    """LLM-powered daily thesis comparator for analyze runs."""

    def __init__(self, quick_thinking_llm):
        self.quick_thinking_llm = quick_thinking_llm

    def check(self, state: Dict[str, Any], ticker: str = "", date: str = "") -> Dict[str, Any]:
        resolved_ticker = (
            ticker
            or state.get("ticker", "")
            or state.get("company_of_interest", "")
        )
        resolved_date = (
            date
            or state.get("date", "")
            or state.get("trade_date", "")
        )

        payload = {
            "ticker": resolved_ticker,
            "date": resolved_date,
            "market_report": state.get("market_report", ""),
            "news_report": state.get("news_report", ""),
            "investment_plan": state.get("investment_plan", ""),
            "final_trade_decision": state.get("final_trade_decision", ""),
        }

        system_message = (
            "You are an investment thesis comparator. Use the provided daily market "
            "signals, indicators, and news to determine whether the current "
            "investment thesis should change today. Return strict JSON only."
        )
        schema_hint = {
            "thesis_change": "NO",
            "reason": "Daily data supports the current thesis.",
            "daily_signals": [
                "Signal 1",
                "Signal 2",
            ],
            "confidence": 3,
        }

        messages = [
            make_cached_system_message(system_message, self.quick_thinking_llm),
            (
                "human",
                "Analyze this payload and return only JSON matching this schema.\n\n"
                + json.dumps({"payload": payload, "schema": schema_hint}, ensure_ascii=True),
            ),
        ]

        try:
            response = self.quick_thinking_llm.invoke(messages)
            raw = extract_text_content(response)
            data = self._safe_parse_json(raw)
        except Exception:
            data = {}

        thesis_change = str(data.get("thesis_change", "NO")).strip().upper()
        if thesis_change not in {"YES", "NO"}:
            thesis_change = "NO"

        reason = str(data.get("reason", "")).strip() or (
            "Insufficient daily data to justify a thesis change."
        )
        daily_signals = self._normalize_signals(data.get("daily_signals"))
        confidence = self._clamp_confidence(data.get("confidence", 3))

        return {
            "ticker": resolved_ticker,
            "date": resolved_date,
            "thesis_change": thesis_change,
            "reason": reason,
            "daily_signals": daily_signals,
            "confidence": confidence,
            "timestamp": datetime.now().isoformat(),
        }

    def _safe_parse_json(self, text: str) -> Dict[str, Any]:
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}

        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}

    def _normalize_signals(self, value: Any) -> List[str]:
        if isinstance(value, list):
            signals = [str(v).strip() for v in value if str(v).strip()]
            return signals[:5]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    def _clamp_confidence(self, value: Any) -> int:
        try:
            num = int(round(float(value)))
        except (TypeError, ValueError):
            return 3
        return max(1, min(5, num))
