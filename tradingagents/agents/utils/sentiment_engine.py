"""Compatibility sentiment metrics for legacy graph tests."""

from __future__ import annotations

import json
import re
from typing import Any

_BULLISH_PHRASES = [
    ("record revenue", 2.0),
    ("record earnings", 2.0),
    ("raised guidance", 2.0),
    ("beat expectations", 2.0),
    ("exceeded estimates", 2.0),
    ("price target raised", 2.0),
    ("upgrade", 1.5),
    ("outperform", 1.5),
    ("bullish", 1.5),
    ("beat", 1.5),
    ("upside", 1.5),
    ("breakout", 1.5),
    ("surge", 1.5),
    ("momentum", 1.5),
    ("growth", 1.0),
    ("strong", 1.0),
    ("positive", 1.0),
    ("opportunity", 1.0),
    ("accelerate", 1.0),
    ("recover", 1.0),
    ("gain", 1.0),
]

_BEARISH_PHRASES = [
    ("missed expectations", 2.0),
    ("lowered guidance", 2.0),
    ("cut guidance", 2.0),
    ("price target cut", 2.0),
    ("downgrade", 1.5),
    ("underperform", 1.5),
    ("bearish", 1.5),
    ("miss", 1.5),
    ("downside", 1.5),
    ("breakdown", 1.5),
    ("selloff", 1.5),
    ("weak", 1.0),
    ("decline", 1.0),
    ("concern", 1.0),
    ("risk", 1.0),
    ("lawsuit", 1.0),
    ("investigation", 1.0),
    ("recall", 1.0),
    ("loss", 1.0),
]

_CATALYST_PHRASES = [
    ("earnings", 1.5),
    ("guidance", 1.5),
    ("acquisition", 2.0),
    ("merger", 2.0),
    ("fda approval", 2.0),
    ("fda", 1.5),
    ("approval", 1.5),
    ("deal", 1.5),
    ("contract", 1.5),
    ("launch", 1.5),
    ("ipo", 1.5),
    ("regulation", 1.0),
    ("restructuring", 1.5),
    ("buyback", 1.5),
    ("dividend", 1.0),
]

_NEGATORS = {"not", "no", "never", "neither", "nor", "without", "despite", "n't"}


def _direction_from_score(score: float) -> str:
    if score >= 60.0:
        return "BULLISH"
    if score <= 40.0:
        return "BEARISH"
    return "NEUTRAL"


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def extract_av_sentiment(raw_response: Any, symbol: str) -> dict[str, Any] | None:
    if not raw_response:
        return None
    try:
        payload = json.loads(raw_response) if isinstance(raw_response, str) else raw_response
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    feed = payload.get("feed")
    if not isinstance(feed, list) or not feed:
        return None

    ticker = symbol.upper()
    weighted_sentiment = 0.0
    total_weight = 0.0
    catalyst_hits = 0.0
    evidence_count = 0

    for article in feed:
        if not isinstance(article, dict):
            continue
        if "overall_sentiment_score" not in article and "ticker_sentiment" not in article:
            continue
        overall = _to_float(article.get("overall_sentiment_score"))
        ticker_score = overall
        relevance = 0.3
        for row in article.get("ticker_sentiment", []) or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("ticker", "")).upper() == ticker:
                ticker_score = _to_float(row.get("ticker_sentiment_score"), overall)
                relevance = _to_float(row.get("relevance_score"), 0.3)
                break
        weight = max(0.1, relevance)
        weighted_sentiment += ticker_score * weight
        total_weight += weight
        evidence_count += 1
        for topic_entry in article.get("topics", []) or []:
            if not isinstance(topic_entry, dict):
                continue
            topic = str(topic_entry.get("topic", "")).lower()
            if any(key in topic for key in ("earnings", "merger", "ipo", "fda", "regulation", "dividend", "contract")):
                catalyst_hits += _to_float(topic_entry.get("relevance_score"))

    if evidence_count == 0 or total_weight == 0:
        return None

    avg_sentiment = weighted_sentiment / total_weight
    social_score = max(0.0, min(100.0, 50.0 + 40.0 * avg_sentiment))
    catalyst_score = max(0.0, min(100.0, 20.0 + catalyst_hits * 15.0 + evidence_count * 1.5))
    return {
        "social_score": social_score,
        "catalyst_score": catalyst_score,
        "evidence_count": float(evidence_count),
        "avg_score": avg_sentiment,
        "label": _direction_from_score(social_score),
        "relevance_weighted_score": avg_sentiment,
        "article_count": evidence_count,
    }


def _has_negator(tokens: list[str], phrase_start: int) -> bool:
    words_before = tokens[max(0, phrase_start - 5):phrase_start]
    return any(word in _NEGATORS for word in words_before)


def _phrase_start(tokens: list[str], phrase: str) -> int:
    phrase_tokens = phrase.split()
    for idx in range(0, max(0, len(tokens) - len(phrase_tokens) + 1)):
        if tokens[idx:idx + len(phrase_tokens)] == phrase_tokens:
            return idx
    return -1


def score_text_sentiment(text: str, symbol: str) -> dict[str, Any]:
    if not text:
        return {
            "social_score": 50.0,
            "catalyst_score": 50.0,
            "evidence_count": 0.0,
            "direction": "NEUTRAL",
        }

    lower_text = text.lower()
    tokens = re.findall(r"\w+|n't", lower_text)
    bullish_score = 0.0
    bearish_score = 0.0
    catalyst_score = 0.0
    match_count = 0

    for phrase, weight in _BULLISH_PHRASES:
        if phrase in lower_text:
            start = _phrase_start(tokens, phrase)
            if start >= 0 and _has_negator(tokens, start):
                bearish_score += weight * 0.5
            else:
                bullish_score += weight
            match_count += 1

    for phrase, weight in _BEARISH_PHRASES:
        if phrase in lower_text:
            start = _phrase_start(tokens, phrase)
            if start >= 0 and _has_negator(tokens, start):
                bullish_score += weight * 0.5
            else:
                bearish_score += weight
            match_count += 1

    for phrase, weight in _CATALYST_PHRASES:
        if phrase in lower_text:
            catalyst_score += weight

    total = bullish_score + bearish_score
    net = 0.0 if total == 0 else (bullish_score - bearish_score) / (total + 1.0)
    social_score = max(0.0, min(100.0, 50.0 + 40.0 * net))
    catalyst = max(0.0, min(100.0, 20.0 + catalyst_score * 10.0))
    return {
        "social_score": social_score,
        "catalyst_score": catalyst,
        "evidence_count": float(match_count),
        "direction": _direction_from_score(social_score),
    }


def build_sentiment_snapshot(
    av_news_raw: Any,
    xai_social_raw: Any,
    ticker: str,
) -> dict[str, Any]:
    av_data = extract_av_sentiment(av_news_raw, ticker)
    if isinstance(xai_social_raw, str) and xai_social_raw.strip():
        text_data = score_text_sentiment(xai_social_raw, ticker)
    elif isinstance(xai_social_raw, dict):
        text_data = extract_av_sentiment(xai_social_raw, ticker)
        if text_data is None:
            text_data = score_text_sentiment(json.dumps(xai_social_raw), ticker)
    else:
        text_data = None

    av_present = av_data is not None
    text_present = text_data is not None
    data_coverage = (int(av_present) + int(text_present)) / 2.0

    if av_present and text_present:
        composite = av_data["social_score"] * 0.6 + text_data["social_score"] * 0.4
    elif av_present:
        composite = av_data["social_score"]
    elif text_present:
        composite = text_data["social_score"]
    else:
        composite = 50.0

    source_quality = "high" if av_present else "medium" if text_present else "low"
    direction = _direction_from_score(composite)
    return {
        "av_sentiment": {
            "score": av_data["avg_score"],
            "label": av_data["label"],
            "evidence_count": int(av_data["article_count"]),
            "relevance": av_data["relevance_weighted_score"],
        }
        if av_present
        else {},
        "text_sentiment": {
            "social_score": text_data["social_score"],
            "catalyst_score": text_data["catalyst_score"],
            "direction": text_data.get("direction", direction),
        }
        if text_present
        else {},
        "buzz": {
            "total_articles": int(av_data["article_count"]) if av_present else int(text_data.get("evidence_count", 0)) if text_present else 0,
            "av_articles": int(av_data["article_count"]) if av_present else 0,
            "source_quality": source_quality,
        },
        "composite_score": round(composite, 2),
        "direction": direction,
        "data_coverage": data_coverage,
    }
