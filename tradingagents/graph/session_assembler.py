"""Session-powered analysis assembler.

Pure Python module for session analysis mode — gathers computation engine
data and computes AeternusScorer-equivalent scores without LLM API calls.
The LLM reasoning (analyst reports, debate, trader verdict) comes from
Sonnet subagents in the Claude Code session, not from API calls.
"""

import json
import os
import ssl
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

# Minimum data_coverage (0.0–1.0) for computation engine metrics to anchor a
# pillar score.  Matches AeternusScorer.MIN_ANCHOR_COVERAGE.
MIN_ANCHOR_COVERAGE = 0.4

_ENV_LOADED = False


def _ensure_env():
    """Load .env and configure SSL certs (idempotent)."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    # Fix macOS Python SSL cert issue — point urllib at certifi CA bundle
    try:
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    except ImportError:
        pass
    _ENV_LOADED = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_call(fn, *args, **kwargs):
    """Call fn(*args, **kwargs), return {} on any exception."""
    try:
        result = fn(*args, **kwargs)
        return result if result is not None else {}
    except Exception:
        return {}


def _clamp_score(value: Any) -> int:
    """Clamp a numeric value to 0-100."""
    try:
        num = int(round(float(value)))
    except (TypeError, ValueError):
        return 50
    return max(0, min(100, num))


def _clamp_confidence(value: Any) -> int:
    """Clamp a numeric value to 1-5."""
    try:
        num = int(round(float(value)))
    except (TypeError, ValueError):
        return 3
    return max(1, min(5, num))


# ---------------------------------------------------------------------------
# Pure-Python sub-score functions (exact replicas from AeternusScorer)
# ---------------------------------------------------------------------------

def _score_quality(m: Dict[str, Any]) -> int:
    piotroski = m.get("piotroski", {})
    ratios = m.get("ratios", {})
    fscore = piotroski.get("fscore")
    if fscore is None:
        return 50
    score = max(0, min(100, int(round((fscore / 9) * 100))))
    roe = ratios.get("roe")
    if roe is not None:
        if roe > 15:
            score += 10
        elif roe < 0:
            score -= 15
    return score


def _score_growth(m: Dict[str, Any]) -> int:
    ratios = m.get("ratios", {})
    income = m.get("income", {})
    rev_growth = ratios.get("quarterly_revenue_growth_yoy")
    earn_growth = ratios.get("quarterly_earnings_growth_yoy")
    rev_growth_qoq = income.get("revenue_growth_qoq")
    growth = rev_growth
    if growth is None:
        growth = rev_growth_qoq
    if growth is None:
        growth = earn_growth
    if growth is None:
        return 50
    if -1 < growth < 1 and growth != 0:
        growth = growth * 100
    if growth > 20:
        score = 90
    elif growth > 10:
        score = 75
    elif growth > 0:
        score = 60
    elif growth > -10:
        score = 40
    else:
        score = 25
    margin_trend = income.get("margin_trend")
    if margin_trend == "improving":
        score += 5
    elif margin_trend == "declining":
        score -= 5
    return score


def _score_health(m: Dict[str, Any]) -> int:
    balance = m.get("balance", {})
    cashflow = m.get("cashflow", {})
    score = 50
    cr = balance.get("current_ratio")
    if cr is not None:
        if cr >= 2.0:
            score = 80
        elif cr >= 1.5:
            score = 70
        elif cr >= 1.0:
            score = 55
        else:
            score = 35
    de = balance.get("debt_to_equity")
    if de is not None:
        if de > 3.0:
            score -= 10
        elif de < 0.5:
            score += 5
    fcf_pos = cashflow.get("fcf_positive")
    if fcf_pos is False:
        score -= 15
    elif fcf_pos is True:
        score += 5
    ocf_trend = cashflow.get("ocf_trend")
    if ocf_trend == "improving":
        score += 5
    elif ocf_trend == "declining":
        score -= 5
    return score


def _score_valuation(m: Dict[str, Any]) -> int:
    ratios = m.get("ratios", {})
    score = 50
    fpe = ratios.get("forward_pe")
    pe = ratios.get("pe")
    target_pe = fpe if fpe is not None else pe
    if target_pe is not None:
        if target_pe < 0:
            score = 30
        elif target_pe <= 10:
            score = 85
        elif target_pe <= 20:
            score = 75
        elif target_pe <= 30:
            score = 60
        elif target_pe <= 40:
            score = 50
        else:
            score = 40
    peg = ratios.get("peg")
    if peg is not None:
        if 0 < peg < 1:
            score += 10
        elif peg > 3:
            score -= 5
    return score


def _score_polarity(m: Dict[str, Any]) -> int:
    composite = m.get("composite_score")
    if composite is not None:
        return _clamp_score(composite)
    av = m.get("av_sentiment", {})
    av_score = av.get("score")
    if av_score is not None:
        return _clamp_score(50.0 + 40.0 * av_score)
    text = m.get("text_sentiment", {})
    text_score = text.get("social_score")
    if text_score is not None:
        return _clamp_score(text_score)
    return 50


def _score_buzz(m: Dict[str, Any]) -> int:
    buzz = m.get("buzz", {})
    total = buzz.get("total_articles", 0)
    if total >= 30:
        score = 85
    elif total >= 15:
        score = 70
    elif total >= 5:
        score = 50
    else:
        score = 30
    quality = buzz.get("source_quality", "low")
    if quality == "high":
        score += 10
    elif quality == "medium":
        score += 5
    return score


def _score_catalyst(m: Dict[str, Any]) -> int:
    text = m.get("text_sentiment", {})
    catalyst_raw = text.get("catalyst_score")
    if catalyst_raw is None:
        return 50
    score = _clamp_score(catalyst_raw)
    direction = m.get("direction")
    text_direction = text.get("direction")
    if direction and text_direction and direction == text_direction and direction != "NEUTRAL":
        score = min(100, score + 10)
    return score


def _compute_fundamental_sub(metrics: Dict[str, Any]) -> Dict[str, int]:
    quality = _score_quality(metrics)
    growth = _score_growth(metrics)
    health = _score_health(metrics)
    valuation = _score_valuation(metrics)
    return {
        "quality": max(0, min(100, quality)),
        "growth": max(0, min(100, growth)),
        "health": max(0, min(100, health)),
        "valuation": max(0, min(100, valuation)),
    }


def _compute_fundamental_overlay(fundamental_sub: Optional[Dict[str, int]]) -> Dict[str, Any]:
    from tradingagents.graph.aeternus_scoring import AeternusScorer

    return AeternusScorer.compute_fundamental_overlay(fundamental_sub)


def _compute_fundamental_shadow_signal(fundamental_sub: Optional[Dict[str, int]]) -> Dict[str, Any]:
    return {"strategy": None, "gate_status": None, "recommended_status": None}


def _compute_sentiment_sub(metrics: Dict[str, Any]) -> Dict[str, int]:
    if metrics.get("source") == "dealflow":
        return {
            "polarity": max(0, min(100, int(metrics.get("social_momentum", 50)))),
            "buzz": max(0, min(100, int(metrics.get("social_momentum", 50)))),
            "catalyst": max(0, min(100, int(metrics.get("news_catalyst", 50)))),
        }
    polarity = _score_polarity(metrics)
    buzz = _score_buzz(metrics)
    catalyst = _score_catalyst(metrics)
    return {
        "polarity": max(0, min(100, polarity)),
        "buzz": max(0, min(100, buzz)),
        "catalyst": max(0, min(100, catalyst)),
    }


def _compute_macro_sub(metrics: Dict[str, Any]) -> Dict[str, int]:
    subscores = metrics.get("subscores", {})
    return {
        "regime_fit": max(0, min(100, int(subscores.get("regime_fit", 50)))),
        "monetary_stress": max(0, min(100, int(subscores.get("monetary_stress", 50)))),
        "rate_headwind": max(0, min(100, int(subscores.get("rate_headwind", 50)))),
        "commodity_cycle": max(0, min(100, int(subscores.get("commodity_cycle", 50)))),
    }


def _compute_momentum_sub(metrics: Dict[str, Any]) -> Dict[str, int]:
    subscores = metrics.get("subscores", {})
    return {
        "trend_strength": max(0, min(100, int(subscores.get("trend_strength", 50)))),
        "momentum_health": max(0, min(100, int(subscores.get("momentum_health", 50)))),
        "regime_quality": max(0, min(100, int(subscores.get("regime_quality", 50)))),
        "volume_confirmation": max(0, min(100, int(subscores.get("volume_confirmation", 50)))),
    }


# ---------------------------------------------------------------------------
# Deep-selection gate — enforces dealflow_deep_k / lane quotas
# ---------------------------------------------------------------------------

def get_deep_selected_tickers(queue_date: str) -> list:
    """Return ONLY tickers marked ``selected_for_deep=True`` in the research queue.

    This is the hard gate that prevents session-analysis from exceeding the
    configured ``dealflow_deep_k`` / lane-quota limits.  The pipeline already
    sets ``selected_for_deep`` on each queue item during
    ``DealFlowPipeline._build_research_queue``.  This function simply reads
    that flag and returns the filtered list.

    Returns a list of dicts, each with at minimum ``symbol``, ``sector``,
    ``lane``, and the full queue-item dict under ``queue_context``.
    """
    rq_path = Path("eval_results") / "deal_flow" / queue_date / "research_queue.json"
    if not rq_path.exists():
        raise FileNotFoundError(f"Research queue not found: {rq_path}")

    rq = json.loads(rq_path.read_text())
    items = rq.get("items", [])

    selected = []
    for item in items:
        if not item.get("selected_for_deep"):
            continue
        selected.append({
            "symbol": item["symbol"],
            "sector": item.get("sector", ""),
            "asset_class": item.get("asset_class", "Equity"),
            "lane": item.get("lane", "CORE"),
            "queue_context": item,
        })

    total = len(items)
    deep = len(selected)
    skipped = total - deep
    if skipped > 0:
        import sys
        print(
            f"[deep-selection gate] {deep}/{total} tickers pass "
            f"selected_for_deep (skipped {skipped})",
            file=sys.stderr,
        )

    return selected


# ---------------------------------------------------------------------------
# Function 1: gather_computation_data
# ---------------------------------------------------------------------------

def gather_computation_data(
    ticker: str,
    date: str,
    sector: str = "",
    asset_class: str = "Equity",
) -> dict:
    """Run all pure-Python computation engines. No LLM calls."""
    # Ensure .env is loaded (API keys) and SSL certs are configured
    _ensure_env()
    from tradingagents.dataflows.interface import route_to_vendor
    from tradingagents.agents.utils.sentiment_engine import build_sentiment_snapshot
    from tradingagents.agents.utils.momentum_engine import build_momentum_snapshot
    from tradingagents.agents.utils.options_engine import build_options_snapshot
    from tradingagents.agents.utils.flow_toxicity_engine import build_flow_toxicity_snapshot

    fundamental_metrics = {}

    # Sentiment
    def _gather_sentiment():
        start_date = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
        av_raw = _safe_call(route_to_vendor, "get_news", ticker, start_date, date)
        xai_raw = _safe_call(route_to_vendor, "get_news", f"${ticker} social media sentiment", start_date, date)
        return build_sentiment_snapshot(av_raw or "", xai_raw or "", ticker)

    sentiment_metrics = _safe_call(_gather_sentiment)

    macro_metrics = {}

    # Momentum
    momentum_metrics = _safe_call(build_momentum_snapshot, ticker, date)

    # Options (returns dict or None)
    options_raw = _safe_call(build_options_snapshot, ticker)
    options_metrics = options_raw if options_raw else {}

    # Flow toxicity (returns dict or None)
    ft_raw = _safe_call(build_flow_toxicity_snapshot, ticker)
    flow_toxicity_metrics = ft_raw if ft_raw else {}

    return {
        "ticker": ticker,
        "date": date,
        "fundamental_metrics": fundamental_metrics or {},
        "sentiment_metrics": sentiment_metrics or {},
        "momentum_metrics": momentum_metrics or {},
        "macro_metrics": macro_metrics or {},
        "options_metrics": options_metrics or {},
        "flow_toxicity_metrics": flow_toxicity_metrics or {},
    }


# ---------------------------------------------------------------------------
# Function 2: build_session_score
# ---------------------------------------------------------------------------

def build_session_score(computation_data: dict, sonnet_outputs: dict) -> dict:
    """Compute AeternusRating dict using only Python math + Sonnet text."""
    from tradingagents.graph.coherence_engine import build_coherence_snapshot
    from tradingagents.graph.regime_weights import get_weights
    from tradingagents.graph.fama_french import get_ff_factors

    fundamental_metrics = computation_data.get("fundamental_metrics") or {}
    sentiment_metrics = computation_data.get("sentiment_metrics") or {}
    macro_metrics = computation_data.get("macro_metrics") or {}
    momentum_metrics = computation_data.get("momentum_metrics") or {}
    options_metrics = computation_data.get("options_metrics") or {}
    flow_toxicity_metrics = computation_data.get("flow_toxicity_metrics") or {}

    # 1. Fundamental sub-scores
    fundamental_sub = None
    _fund_cov = fundamental_metrics.get("data_coverage", 0.0)
    _fund_gated = bool(fundamental_metrics) and _fund_cov < MIN_ANCHOR_COVERAGE
    if fundamental_metrics and not _fund_gated:
        fundamental_sub = _compute_fundamental_sub(fundamental_metrics)
        anchored_fundamental = round(
            fundamental_sub["quality"] * 0.35
            + fundamental_sub["growth"] * 0.30
            + fundamental_sub["health"] * 0.20
            + fundamental_sub["valuation"] * 0.15,
        )
        anchored_fundamental = max(0, min(100, anchored_fundamental))
    else:
        anchored_fundamental = 50
    fundamental_overlay = _compute_fundamental_overlay(fundamental_sub)
    fundamental_shadow = _compute_fundamental_shadow_signal(fundamental_sub)

    # 2. Sentiment sub-scores
    sentiment_sub = None
    _sent_cov = sentiment_metrics.get("data_coverage", 0.0)
    _sent_gated = bool(sentiment_metrics) and _sent_cov < MIN_ANCHOR_COVERAGE
    if sentiment_metrics and not _sent_gated:
        sentiment_sub = _compute_sentiment_sub(sentiment_metrics)
        anchored_sentiment = round(
            sentiment_sub["polarity"] * 0.40
            + sentiment_sub["buzz"] * 0.30
            + sentiment_sub["catalyst"] * 0.30,
        )
        anchored_sentiment = max(0, min(100, anchored_sentiment))
    else:
        anchored_sentiment = 50

    # Blend options sentiment (70/30 or 100% options when no text)
    options_sub = None
    if options_metrics and options_metrics.get("sentiment_score") is not None:
        options_sub = {
            "sentiment_score": options_metrics["sentiment_score"],
            "fear_greed": options_metrics.get("fear_greed", "NEUTRAL"),
            "put_call_volume_ratio": options_metrics.get("put_call_volume_ratio"),
            "iv_skew": options_metrics.get("iv_skew"),
        }
        options_sentiment = options_metrics["sentiment_score"]
        if sentiment_sub is not None:
            anchored_sentiment = round(anchored_sentiment * 0.70 + options_sentiment * 0.30)
            anchored_sentiment = max(0, min(100, anchored_sentiment))
        else:
            anchored_sentiment = options_sentiment

    # Blend flow toxicity (85/15)
    flow_toxicity_sub = None
    if flow_toxicity_metrics and flow_toxicity_metrics.get("composite_score") is not None:
        flow_toxicity_sub = {
            "composite_score": flow_toxicity_metrics["composite_score"],
            "toxicity_level": flow_toxicity_metrics.get("toxicity_level", "UNKNOWN"),
            "vpin_proxy": flow_toxicity_metrics.get("vpin_proxy"),
            "direction": flow_toxicity_metrics.get("direction", "NEUTRAL"),
        }
        ft_score = flow_toxicity_metrics["composite_score"]
        if anchored_sentiment != 50 or sentiment_sub is not None or options_sub is not None:
            anchored_sentiment = round(anchored_sentiment * 0.85 + ft_score * 0.15)
            anchored_sentiment = max(0, min(100, anchored_sentiment))
        else:
            anchored_sentiment = ft_score

    # 3. Macro sub-scores
    macro_sub = None
    _macro_cov = macro_metrics.get("data_coverage", 0.0)
    _macro_gated = bool(macro_metrics) and _macro_cov < MIN_ANCHOR_COVERAGE
    if macro_metrics and not _macro_gated:
        macro_sub = _compute_macro_sub(macro_metrics)
        anchored_macro = round(
            macro_sub["regime_fit"] * 0.25
            + macro_sub["monetary_stress"] * 0.25
            + macro_sub["rate_headwind"] * 0.25
            + macro_sub["commodity_cycle"] * 0.25,
        )
        anchored_macro = max(0, min(100, anchored_macro))
    else:
        anchored_macro = 50

    # 4. Momentum sub-scores
    momentum_sub = None
    _mom_cov = momentum_metrics.get("data_coverage", 0.0)
    _mom_gated = bool(momentum_metrics) and _mom_cov < MIN_ANCHOR_COVERAGE
    if momentum_metrics and not _mom_gated:
        momentum_sub = _compute_momentum_sub(momentum_metrics)
        anchored_momentum = round(
            momentum_sub["trend_strength"] * 0.40
            + momentum_sub["momentum_health"] * 0.30
            + momentum_sub["regime_quality"] * 0.20
            + momentum_sub["volume_confirmation"] * 0.10,
        )
        anchored_momentum = max(0, min(100, anchored_momentum))
    else:
        anchored_momentum = 50

    data_quality_gate = {
        "fundamental": _fund_gated,
        "sentiment": _sent_gated,
        "macro": _macro_gated,
        "momentum": _mom_gated,
    }

    # 5. Scores dict
    scores = {
        "fundamental": anchored_fundamental,
        "macro": anchored_macro,
        "sentiment": anchored_sentiment,
        "momentum": anchored_momentum,
    }

    # 6. Coherence
    coherence_snapshot = _safe_call(
        build_coherence_snapshot,
        pillar_composites=scores,
        fundamental_sub=fundamental_sub,
        macro_sub=macro_sub,
        sentiment_sub=sentiment_sub,
        momentum_sub=momentum_sub,
    )
    if not coherence_snapshot:
        coherence_snapshot = {"composite_score": 50, "subscores": {}, "detected_patterns": []}
    coherence_sub = coherence_snapshot.get("subscores", {})
    scores["coherence"] = coherence_snapshot.get("composite_score", 50)

    # 7. Regime weights + ensemble blend
    regime = macro_metrics.get("regime", "NEUTRAL")

    # Extract debate voice scores from Sonnet outputs (same logic as AeternusScorer)
    from tradingagents.graph.aeternus_scoring import AeternusScorer
    _scorer_inst = AeternusScorer.__new__(AeternusScorer)
    _state_for_debate = {
        "investment_debate_state": sonnet_outputs.get("investment_debate_state"),
        "investment_plan": sonnet_outputs.get("investment_plan", ""),
        "structured_trader_verdict": sonnet_outputs.get("structured_trader_verdict"),
        "structured_verdict": sonnet_outputs.get("structured_verdict"),
    }
    research_debate_score = _scorer_inst._extract_research_debate_score(_state_for_debate)
    trader_verdict_score = _scorer_inst._extract_trader_verdict_score(_state_for_debate)
    risk_verdict_score = _scorer_inst._extract_risk_verdict_score(_state_for_debate)

    model_scores = {
        "fundamental":     scores["fundamental"],
        "coherence":       scores["coherence"],
        "macro":           scores["macro"],
        "sentiment":       scores["sentiment"],
        "momentum":        scores["momentum"],
        "research_debate": research_debate_score,
        "trader_verdict":  trader_verdict_score,
        "risk_verdict":    risk_verdict_score,
    }
    active_models = {k for k, v in model_scores.items() if v is not None}
    quant_pillars = {"fundamental", "coherence", "macro", "sentiment", "momentum"}

    if not active_models - quant_pillars:
        # No debate voices — pure quant fallback
        weights = _safe_call(get_weights, regime)
        if not weights:
            weights = {
                "fundamental": 0.30, "coherence": 0.25,
                "macro": 0.20, "sentiment": 0.15, "momentum": 0.10,
            }
        aeternus_score = round(
            scores["fundamental"] * weights["fundamental"]
            + scores["coherence"] * weights["coherence"]
            + scores["macro"] * weights["macro"]
            + scores["sentiment"] * weights["sentiment"]
            + scores["momentum"] * weights["momentum"],
            2,
        )
        effective_weights = weights
    else:
        from tradingagents.graph.ensemble_weights import EnsembleWeightStore
        ensemble_store = EnsembleWeightStore.load()
        effective_weights = ensemble_store.get_effective_weights(regime, active_models)
        aeternus_score = round(
            sum(model_scores[k] * effective_weights[k] for k in active_models),
            2,
        )
        weights = effective_weights

    # Quant-only reference score (drift monitor)
    quant_weights_ref = _safe_call(get_weights, regime)
    if not quant_weights_ref:
        quant_weights_ref = {"fundamental": 0.30, "coherence": 0.25, "macro": 0.20, "sentiment": 0.15, "momentum": 0.10}
    quant_only_score = round(
        sum(scores[p] * quant_weights_ref[p] for p in quant_weights_ref), 2
    )

    # 8. Alpha decomposition (exact replica from AeternusScorer._compute_alpha_decomposition)
    valuation_score = (
        fundamental_sub["valuation"]
        if fundamental_sub and "valuation" in fundamental_sub
        else scores.get("fundamental", 50)
    )
    alpha_decomposition = None
    try:
        ff = get_ff_factors(lookback_days=60)
        if ff is not None:
            mkt_loading = scores.get("macro", 50) / 50.0 - 1.0
            val_loading = valuation_score / 50.0 - 1.0
            size_loading = 0.0
            factor_predicted = 50.0 + (
                mkt_loading * ff["mkt_rf"] * 10.0
                + val_loading * ff["hml"] * 8.0
                + size_loading * ff["smb"] * 5.0
            )
            factor_predicted = max(0.0, min(100.0, factor_predicted))
            factor_source = "fama_french"
        else:
            factor_predicted = (
                scores.get("macro", 50) * 0.35
                + valuation_score * 0.35
                + scores.get("momentum", 50) * 0.30
            )
            factor_source = "heuristic"
        alpha_residual = aeternus_score - factor_predicted
        if alpha_residual > 8:
            interpretation = "Significant alpha — agents see value beyond factors"
        elif alpha_residual > 3:
            interpretation = "Moderate alpha"
        elif alpha_residual >= -3:
            interpretation = "Factor-neutral"
        elif alpha_residual >= -8:
            interpretation = "Moderate discount — agents detect hidden risks"
        else:
            interpretation = "Significant discount"
        alpha_decomposition = {
            "factor_predicted": round(factor_predicted, 2),
            "alpha_residual": round(alpha_residual, 2),
            "interpretation": interpretation,
            "factor_source": factor_source,
        }
    except Exception:
        pass

    # 9. Epistemic
    epistemic = None
    try:
        from tradingagents.graph.epistemic import build_epistemic_report
        epistemic = build_epistemic_report(
            fundamental_metrics=fundamental_metrics,
            sentiment_metrics=sentiment_metrics,
            macro_metrics=macro_metrics,
            momentum_metrics=momentum_metrics,
            options_metrics=options_metrics,
            coherence_snapshot=coherence_snapshot,
            weights=weights,
            aeternus_score=aeternus_score,
            breakdown=scores,
        )
    except Exception:
        pass

    epistemic_summary = None
    if epistemic:
        epistemic_summary = {
            "overall_confidence": epistemic.get("overall_confidence", "LOW"),
            "weakest_pillar": epistemic.get("weakest_pillar", "unknown"),
        }

    # 10. Calibration
    calibration_context = None
    try:
        from tradingagents.graph.calibration import build_calibration_report
        calibration_context = build_calibration_report()
    except Exception:
        pass

    # 11. Rating
    if aeternus_score >= 80:
        rating = "Strong Buy"
    elif aeternus_score >= 60:
        rating = "Buy"
    elif aeternus_score >= 40:
        rating = "Hold"
    elif aeternus_score >= 20:
        rating = "Sell"
    else:
        rating = "Strong Sell"

    # 12. Confidence from data quality
    keys = [
        "fundamentals_report", "market_report", "sentiment_report",
        "news_report", "investment_plan", "final_trade_decision",
    ]
    present = sum(1 for k in keys if sonnet_outputs.get(k))
    data_quality = max(1, min(5, round(1 + (4 * present / len(keys)))))
    confidence = data_quality

    # 13. IC calibration delta
    ic_adjustments_applied = False
    try:
        from tradingagents.graph.ic_adjustments import load_ic_adjustments
        ic_conf = load_ic_adjustments("ic_confidence_calibration.json").get("adjustments", {})
        conf_delta = ic_conf.get(str(confidence), 0.0)
        if conf_delta:
            confidence = max(1, min(5, int(round(confidence + conf_delta))))
            ic_adjustments_applied = True
    except Exception:
        pass

    # 14. Return full AeternusRating-compatible dict
    return {
        "rating_id": str(uuid.uuid4()),
        "ticker": computation_data.get("ticker", ""),
        "date": computation_data.get("date", ""),
        "aeternus_score": aeternus_score,
        "rating": rating,
        "confidence": confidence,
        "breakdown": scores,
        "rationales": {},
        "price_at_rating": None,
        "price_target": None,
        "catalyst": None,
        "confidence_factors": {"data_quality": data_quality},
        "sector": None,
        "peer_comparison": None,
        "fundamental_sub": fundamental_sub,
        "fundamental_overlay_score": fundamental_overlay["score"],
        "fundamental_overlay_label": fundamental_overlay["label"],
        "fundamental_overlay_notes": fundamental_overlay["notes"],
        "fundamental_shadow_strategy": fundamental_shadow["strategy"],
        "fundamental_shadow_gate_status": fundamental_shadow["gate_status"],
        "fundamental_shadow_recommended_status": fundamental_shadow["recommended_status"],
        "sentiment_sub": sentiment_sub,
        "macro_sub": macro_sub,
        "momentum_sub": momentum_sub,
        "options_sub": options_sub,
        "flow_toxicity_sub": flow_toxicity_sub,
        "coherence_sub": coherence_sub,
        "detected_patterns": coherence_snapshot.get("detected_patterns", []),
        "regime_weights": weights,
        "weight_regime": regime,
        "alpha_decomposition": alpha_decomposition,
        "catalyst_timeline": None,
        "epistemic": epistemic,
        "calibration_context": calibration_context,
        "data_quality_gate": data_quality_gate,
        "epistemic_summary": epistemic_summary,
        "ic_adjustments_applied": ic_adjustments_applied,
        "ensemble_weights": effective_weights,
        "ensemble_model_scores": {k: v for k, v in model_scores.items()},
        "quant_only_score": quant_only_score,
        "timestamp": datetime.now().isoformat(),
    }


# ---------------------------------------------------------------------------
# Function 3: write_analysis_report
# ---------------------------------------------------------------------------

def write_analysis_report(
    ticker: str,
    date: str,
    computation_data: dict,
    sonnet_outputs: dict,
    score_dict: dict,
    queue_context: Optional[dict] = None,
) -> str:
    """Write results/{TICKER}/{DATE}/analysis_report.json in downstream format."""
    report = {
        "company_of_interest": ticker,
        "trade_date": date,
        "fundamentals_report": sonnet_outputs.get("fundamentals_report", ""),
        "market_report": sonnet_outputs.get("market_report", ""),
        "sentiment_report": sonnet_outputs.get("sentiment_report", ""),
        "news_report": sonnet_outputs.get("news_report", ""),
        "investment_debate_state": sonnet_outputs.get("investment_debate_state", {}),
        "risk_debate_state": sonnet_outputs.get("risk_debate_state", {}),
        "trader_investment_decision": sonnet_outputs.get("trader_investment_decision", ""),
        "investment_plan": sonnet_outputs.get("investment_plan", ""),
        "final_trade_decision": sonnet_outputs.get("final_trade_decision", ""),
        "structured_trader_verdict": sonnet_outputs.get("structured_trader_verdict", {}),
        "structured_verdict": sonnet_outputs.get("structured_verdict", {}),
        "fundamental_metrics": computation_data.get("fundamental_metrics", {}),
        "sentiment_metrics": computation_data.get("sentiment_metrics", {}),
        "macro_metrics": computation_data.get("macro_metrics", {}),
        "momentum_metrics": computation_data.get("momentum_metrics", {}),
        "aeternus_score": score_dict,
        "dealflow_context": queue_context or {},
        "messages": [],
    }
    path = Path("results") / ticker / date
    path.mkdir(parents=True, exist_ok=True)
    (path / "analysis_report.json").write_text(json.dumps(report, indent=2, default=str))

    # Generate content posts for distribution
    try:
        from tradingagents.graph.content_posts import generate_all_posts
        generate_all_posts(ticker, date, report=report)
    except Exception:
        pass  # Content generation is non-critical

    return str(path / "analysis_report.json")


# ---------------------------------------------------------------------------
# Function 4: write_batch_summary
# ---------------------------------------------------------------------------

def write_batch_summary(queue_date: str, items: list) -> str:
    """Write batch_analyze_summary and batch_analyze_latest in exact downstream format.

    Normalises items so ``build_portfolio_plan`` in paper_execution.py can
    consume them directly (needs ``symbol``, ``status``, ``recommendation``,
    ``analysis_report_path``).
    """
    base = Path("eval_results/deal_flow") / queue_date
    base.mkdir(parents=True, exist_ok=True)

    # Load research queue for per-ticker metadata (lane, playbook, queue_id)
    rq_items: Dict[str, dict] = {}
    rq_path = base / "research_queue.json"
    run_id = ""
    if rq_path.exists():
        try:
            rq = json.loads(rq_path.read_text())
            run_id = str(rq.get("run_id", ""))
            for rqi in rq.get("items", rq.get("queue", [])):
                sym = str(rqi.get("symbol", rqi.get("ticker", ""))).upper()
                if sym:
                    rq_items[sym] = rqi
        except Exception:
            pass

    normalised: list = []
    for item in items:
        ticker = str(item.get("symbol", item.get("ticker", ""))).upper()
        if not ticker:
            continue
        # Derive recommendation from final_trade_decision or rating
        ftd = str(item.get("final_trade_decision", "")).upper()
        if ftd.startswith("BUY"):
            recommendation = "BUY"
        elif ftd.startswith("SELL"):
            recommendation = "SELL"
        else:
            recommendation = "HOLD"
        rqi = rq_items.get(ticker, {})
        normalised.append({
            "queue_id": str(item.get("queue_id", rqi.get("queue_id", ""))),
            "symbol": ticker,
            "ticker": ticker,
            "status": str(item.get("status", "SUCCESS")),
            "recommendation": recommendation,
            "aeternus_score": item.get("aeternus_score", 0),
            "confidence": item.get("confidence", 0),
            "rating": item.get("rating", ""),
            "final_trade_decision": item.get("final_trade_decision", ""),
            "analysis_report_path": item.get(
                "analysis_report_path",
                f"results/{ticker}/{queue_date}/analysis_report.json",
            ),
            "lane": str(item.get("lane", rqi.get("lane", "CORE"))).upper(),
            "research_playbook": str(
                item.get("research_playbook", rqi.get("research_playbook", "N/A"))
            ),
            "dominant_signal_family": str(
                item.get("dominant_signal_family", "session_analysis")
            ),
        })

    summary = {
        "queue_date": queue_date,
        "date": queue_date,
        "run_id": run_id,
        "analyzed_count": len(normalised),
        "items": normalised,
    }

    (base / "batch_analyze_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    (base / "batch_analyze_latest.json").write_text(json.dumps(summary, indent=2, default=str))
    return str(base / "batch_analyze_latest.json")
