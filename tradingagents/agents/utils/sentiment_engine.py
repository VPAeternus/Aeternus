"""Pure Python sentiment analysis computation engine.

No LLM calls, no network calls. Functions accept parsed data
and return typed dicts — same discipline as fundamental_engine.py.
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple


_BULLISH_PHRASES = [
    ("record revenue", 2.0), ("record earnings", 2.0), ("raised guidance", 2.0),
    ("beat expectations", 2.0), ("exceeded estimates", 2.0), ("strong buy", 2.0),
    ("price target raised", 2.0),
    ("upgrade", 1.5), ("outperform", 1.5), ("bullish", 1.5), ("beat", 1.5),
    ("upside", 1.5), ("breakout", 1.5), ("surge", 1.5), ("momentum", 1.5),
    ("growth", 1.0), ("strong", 1.0), ("positive", 1.0), ("opportunity", 1.0),
    ("expansion", 1.0), ("accelerate", 1.0), ("recover", 1.0), ("gain", 1.0),
]

_BEARISH_PHRASES = [
    ("missed expectations", 2.0), ("lowered guidance", 2.0), ("cut guidance", 2.0),
    ("guidance cut", 2.0), ("strong sell", 2.0), ("price target cut", 2.0),
    ("downgrade", 1.5), ("underperform", 1.5), ("bearish", 1.5), ("miss", 1.5),
    ("downside", 1.5), ("breakdown", 1.5), ("selloff", 1.5), ("sell off", 1.5),
    ("weak", 1.0), ("decline", 1.0), ("concern", 1.0), ("risk", 1.0),
    ("lawsuit", 1.0), ("investigation", 1.0), ("recall", 1.0), ("loss", 1.0),
]

_CATALYST_PHRASES = [
    ("earnings", 1.5), ("guidance", 1.5), ("acquisition", 2.0), ("merger", 2.0),
    ("fda approval", 2.0), ("fda", 1.5), ("approval", 1.5), ("deal", 1.5),
    ("contract", 1.5), ("launch", 1.5), ("ipo", 1.5), ("regulation", 1.0),
    ("restructuring", 1.5), ("buyback", 1.5), ("dividend", 1.0),
]

_NEGATORS = {"not", "no", "never", "neither", "nor", "without", "despite", "n't"}
_NEGATION_WINDOW = 5


def _direction_from_score(score: float) -> str:
    if score >= 60.0:
        return "BULLISH"
    if score <= 40.0:
        return "BEARISH"
    return "NEUTRAL"


def extract_av_sentiment(raw_response: Any, symbol: str) -> Optional[Dict[str, Any]]:
    """Extract and score sentiment from Alpha Vantage news/sentiment API response.

    Returns a dict with social_score, catalyst_score, evidence_count, avg_score,
    label, relevance_weighted_score, and article_count. Returns None if data is
    missing or malformed.
    """
    if not raw_response:
        return None
    try:
        payload = json.loads(raw_response) if isinstance(raw_response, str) else raw_response
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    feed = payload.get("feed")
    if not isinstance(feed, list) or not feed:
        return None
    if "overall_sentiment_score" not in feed[0] and "ticker_sentiment" not in feed[0]:
        return None

    ticker_upper = symbol.upper()
    weighted_sentiment = 0.0
    total_weight = 0.0
    catalyst_hits = 0.0
    evidence_count = 0

    for article in feed:
        if not isinstance(article, dict):
            continue
        overall = float(article.get("overall_sentiment_score") or 0.0)
        ticker_score = overall
        relevance = 0.3
        for ts in article.get("ticker_sentiment", []) or []:
            if not isinstance(ts, dict):
                continue
            if str(ts.get("ticker", "")).upper() == ticker_upper:
                ticker_score = float(ts.get("ticker_sentiment_score") or overall)
                relevance = float(ts.get("relevance_score") or 0.3)
                break
        weight = max(0.1, relevance)
        weighted_sentiment += ticker_score * weight
        total_weight += weight
        evidence_count += 1
        for topic_entry in article.get("topics", []) or []:
            if not isinstance(topic_entry, dict):
                continue
            topic = str(topic_entry.get("topic", "")).lower()
            if any(kw in topic for kw in ("earnings", "mergers", "ipo", "fda", "regulation", "dividend", "contract")):
                rel = float(topic_entry.get("relevance_score") or 0.0)
                catalyst_hits += rel

    if evidence_count == 0:
        return None

    avg_sentiment = weighted_sentiment / total_weight
    social_score = 50.0 + 40.0 * avg_sentiment
    catalyst_score = min(100.0, 20.0 + catalyst_hits * 15.0 + evidence_count * 1.5)

    return {
        "social_score": max(0.0, min(100.0, social_score)),
        "catalyst_score": max(0.0, min(100.0, catalyst_score)),
        "evidence_count": float(evidence_count),
        "avg_score": avg_sentiment,
        "label": _direction_from_score(social_score),
        "relevance_weighted_score": avg_sentiment,
        "article_count": evidence_count,
    }


def score_text_sentiment(text: str, symbol: str) -> Dict[str, Any]:
    """Score raw text for sentiment using phrase matching with negation detection.

    Returns a dict with social_score, catalyst_score, evidence_count, and direction.
    """
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

    # Check multi-word phrases against text directly with negation detection
    for phrase, weight in _BULLISH_PHRASES:
        for match in re.finditer(re.escape(phrase), lower_text):
            start_char = match.start()
            # Find token index closest to this character position
            char_pos = 0
            token_idx = 0
            for i, tok in enumerate(tokens):
                if char_pos >= start_char:
                    token_idx = i
                    break
                char_pos += len(tok) + 1
            # Check negation window before this token
            window_start = max(0, token_idx - _NEGATION_WINDOW)
            preceding = tokens[window_start:token_idx]
            if any(neg in preceding for neg in _NEGATORS):
                bearish_score += weight * 0.5
            else:
                bullish_score += weight
            match_count += 1

    for phrase, weight in _BEARISH_PHRASES:
        for match in re.finditer(re.escape(phrase), lower_text):
            start_char = match.start()
            char_pos = 0
            token_idx = 0
            for i, tok in enumerate(tokens):
                if char_pos >= start_char:
                    token_idx = i
                    break
                char_pos += len(tok) + 1
            window_start = max(0, token_idx - _NEGATION_WINDOW)
            preceding = tokens[window_start:token_idx]
            if any(neg in preceding for neg in _NEGATORS):
                bullish_score += weight * 0.5
            else:
                bearish_score += weight
            match_count += 1

    for phrase, weight in _CATALYST_PHRASES:
        if phrase in lower_text:
            catalyst_score += weight

    total = bullish_score + bearish_score
    if total == 0:
        net = 0.0
    else:
        net = (bullish_score - bearish_score) / (total + 1.0)

    social_score = 50.0 + 40.0 * net
    social_score = max(0.0, min(100.0, social_score))

    # Scale catalyst score to 0-100 range
    cat_score = min(100.0, 20.0 + catalyst_score * 10.0)
    cat_score = max(0.0, cat_score)

    return {
        "social_score": social_score,
        "catalyst_score": cat_score,
        "evidence_count": float(match_count),
        "direction": _direction_from_score(social_score),
    }


def build_sentiment_snapshot(
    av_news_raw: Any,
    xai_social_raw: Any,
    ticker: str,
) -> Dict[str, Any]:
    """Orchestrate AV and text sentiment into a unified snapshot.

    Calls extract_av_sentiment on av_news_raw and score_text_sentiment on
    xai_social_raw. Returns a composite dict with av_sentiment, text_sentiment,
    buzz metrics, composite_score, direction, and data_coverage.
    """
    av_data = extract_av_sentiment(av_news_raw, ticker)

    # xai_social_raw may be a string (news text) or structured payload
    if isinstance(xai_social_raw, str) and xai_social_raw.strip():
        text_data = score_text_sentiment(xai_social_raw, ticker)
    elif isinstance(xai_social_raw, dict):
        # Try AV format first; fall back to text scoring on concatenated values
        text_data = extract_av_sentiment(xai_social_raw, ticker)
        if text_data is None:
            text_str = json.dumps(xai_social_raw)
            text_data = score_text_sentiment(text_str, ticker)
    else:
        text_data = None

    av_present = av_data is not None
    text_present = text_data is not None
    data_coverage = (int(av_present) + int(text_present)) / 2.0

    if av_present:
        source_quality = "high"
    elif text_present:
        source_quality = "medium"
    else:
        source_quality = "low"

    # Composite score
    if av_present and text_present:
        composite_score = (
            av_data["social_score"] * 0.60
            + text_data["social_score"] * 0.40
        )
    elif av_present:
        composite_score = av_data["social_score"]
    elif text_present:
        composite_score = text_data["social_score"]
    else:
        composite_score = 50.0

    direction = _direction_from_score(composite_score)

    av_articles = int(av_data["article_count"]) if av_present else 0
    text_articles = int(text_data.get("evidence_count", 0)) if text_present else 0
    total_articles = av_articles + (text_articles if not av_present else 0)

    av_sentiment_out: Dict[str, Any] = {}
    if av_present:
        av_sentiment_out = {
            "score": av_data["avg_score"],
            "label": av_data["label"],
            "evidence_count": int(av_data["article_count"]),
            "relevance": av_data["relevance_weighted_score"],
        }

    text_sentiment_out: Dict[str, Any] = {}
    if text_present:
        text_sentiment_out = {
            "social_score": text_data["social_score"],
            "catalyst_score": text_data["catalyst_score"],
            "direction": text_data.get("direction", direction),
        }

    return {
        "av_sentiment": av_sentiment_out,
        "text_sentiment": text_sentiment_out,
        "buzz": {
            "total_articles": total_articles,
            "av_articles": av_articles,
            "source_quality": source_quality,
        },
        "composite_score": round(composite_score, 2),
        "direction": direction,
        "data_coverage": data_coverage,
    }
