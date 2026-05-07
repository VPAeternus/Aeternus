# tradingagents/graph/aeternus_scoring.py

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, TypedDict
import uuid

from pydantic import BaseModel, Field

from .coherence_engine import build_coherence_snapshot
from .ensemble_weights import EnsembleWeightStore
from .regime_weights import get_weights
from .fama_french import get_ff_factors
from .epistemic import build_epistemic_report
from .calibration import build_calibration_report
from tradingagents.agents.utils.agent_utils import extract_text_content, make_cached_system_message
from tradingagents.scoring import confidence as confidence_helpers
from tradingagents.scoring import json_utils as scoring_json_utils
from tradingagents.scoring import rating as rating_helpers

# Minimum data_coverage (0.0–1.0) for computation engine metrics to anchor a pillar score.
# Below this threshold, the pillar falls back to LLM-scored estimate.
# Matches epistemic._coverage_to_tier() LOW boundary.
MIN_ANCHOR_COVERAGE = 0.4


class _ScorerLLMResponse(BaseModel):
    """Schema for the LLM scoring response."""
    fundamental_score: int = Field(default=50, ge=0, le=100)
    technical_score: int = Field(default=50, ge=0, le=100)
    macro_score: int = Field(default=50, ge=0, le=100)
    momentum_score: int = Field(default=50, ge=0, le=100)
    confidence: int = Field(default=3, ge=1, le=5)
    confidence_factors: Optional[Dict[str, int]] = None
    price_target: Optional[float] = None
    catalyst: Optional[str] = None
    score_rationales: Optional[Dict[str, str]] = None


class AeternusRating(TypedDict):
    """Structured output schema for Aeternus score and rating."""
    rating_id: str  # NEW: Unique Identifier for Audit Trail
    ticker: str
    date: str
    aeternus_score: float
    rating: str
    confidence: int
    breakdown: Dict[str, int]
    rationales: Dict[str, str]
    price_at_rating: Optional[float]
    price_target: Optional[float]
    catalyst: Optional[str]
    confidence_factors: Optional[Dict[str, int]]
    sector: Optional[str]
    peer_comparison: Optional[Dict[str, Any]]
    fundamental_sub: Optional[Dict[str, int]]
    fundamental_overlay_score: Optional[float]
    fundamental_overlay_label: Optional[str]
    fundamental_overlay_notes: Optional[str]
    fundamental_shadow_strategy: Optional[str]
    fundamental_shadow_gate_status: Optional[str]
    fundamental_shadow_recommended_status: Optional[str]
    macro_sub: Optional[Dict[str, int]]
    momentum_sub: Optional[Dict[str, int]]
    options_sub: Optional[Dict[str, Any]]
    flow_toxicity_sub: Optional[Dict[str, Any]]
    coherence_sub: Optional[Dict[str, int]]
    detected_patterns: Optional[List[Dict[str, Any]]]
    regime_weights: Optional[Dict[str, float]]
    weight_regime: Optional[str]
    alpha_decomposition: Optional[Dict[str, Any]]
    catalyst_timeline: Optional[Dict[str, Any]]
    epistemic: Optional[Dict[str, Any]]
    calibration_context: Optional[Dict[str, Any]]
    data_quality_gate: Optional[Dict[str, bool]]
    epistemic_summary: Optional[Dict[str, str]]
    ic_adjustments_applied: Optional[bool]
    ensemble_weights: Optional[Dict[str, float]]
    ensemble_model_scores: Optional[Dict[str, Any]]
    quant_only_score: Optional[float]
    timestamp: str


class AeternusScorer:
    """Derives the Aeternus score and rating from analyst reports."""

    _calibration_cache = None  # class-level, loaded once per session

    def __init__(self, quick_thinking_llm, sector_context=None, track_record=None):
        self.quick_thinking_llm = quick_thinking_llm
        self.sector_context = sector_context
        self.track_record = track_record

    def _get_calibration(self):
        """Load calibration report once per session, cache at class level."""
        if AeternusScorer._calibration_cache is None:
            AeternusScorer._calibration_cache = build_calibration_report()
        return AeternusScorer._calibration_cache

    def score(
        self,
        state: Dict[str, Any],
        ticker: str = "",
        date: str = "",
        price_at_rating: Optional[float] = None,
        price_target: Optional[float] = None,
        catalyst: Optional[str] = None,
        fundamental_metrics: Optional[Dict[str, Any]] = None,
        macro_metrics: Optional[Dict[str, Any]] = None,
        momentum_metrics: Optional[Dict[str, Any]] = None,
        options_metrics: Optional[Dict[str, Any]] = None,
        flow_toxicity_metrics: Optional[Dict[str, Any]] = None,
    ) -> AeternusRating:
        """Compute the Aeternus score, rating, and breakdown from the graph state."""
        resolved_ticker = self._resolve_ticker(state, ticker)
        resolved_date = self._resolve_date(state, date)

        # Get sector context if available
        sector_data = {}
        if self.sector_context and resolved_ticker:
            try:
                sector_data = self.sector_context.get_context(resolved_ticker)
            except Exception:
                pass

        payload = {
            "ticker": resolved_ticker,
            "market_report": state.get("market_report", ""),
            "news_report": state.get("news_report", ""),
            "fundamentals_report": state.get("fundamentals_report", ""),
            "investment_plan": state.get("investment_plan", ""),
            "final_trade_decision": state.get("final_trade_decision", ""),
            "sector_context": sector_data,
        }

        system_message = (
            "You are an investment scoring assistant. Score each dimension 0-100 using SEMI-FORMAL REASONING.\n\n"
            "FOR EACH PILLAR SCORE, your rationale MUST follow this structure:\n"
            "1. PREMISES: State the 2-3 strongest data points from the reports (cite specific numbers)\n"
            "2. COUNTERFACTUAL: Name the single strongest piece of evidence that argues AGAINST your score "
            "direction, and explain why your premises outweigh it\n"
            "3. SCORE: The numeric score, anchored to calibration (50=neutral, 70+=bullish, 30-=bearish)\n\n"
            "If evidence is insufficient or conflicting with no clear weight, score 50 and state why.\n"
            "A score above 65 or below 35 WITHOUT a named counterfactual is INVALID.\n\n"
            "Return JSON only with numeric scores and short rationales following the above structure."
        )

        messages = [
            make_cached_system_message(system_message, self.quick_thinking_llm),
            (
                "human",
                "Reports (JSON):\n" + json.dumps(payload, ensure_ascii=True),
            ),
        ]

        # Try structured output first; fall back to free-form JSON parsing
        try:
            structured_llm = self.quick_thinking_llm.with_structured_output(_ScorerLLMResponse)
            result = structured_llm.invoke(messages)
            data = result.model_dump() if result else {}
        except Exception:
            response = self.quick_thinking_llm.invoke(messages)
            raw = extract_text_content(response)
            data = self._safe_parse_json(raw)

        # Compute anchored fundamental sub-scores if metrics provided
        fundamental_sub = None
        _fund_cov = (fundamental_metrics or {}).get("data_coverage", 0.0)
        _fund_gated = fundamental_metrics is not None and _fund_cov < MIN_ANCHOR_COVERAGE
        if fundamental_metrics and not _fund_gated:
            fundamental_sub = self._compute_fundamental_sub(fundamental_metrics)
            anchored_fundamental = round(
                fundamental_sub["quality"] * 0.35
                + fundamental_sub["growth"] * 0.30
                + fundamental_sub["health"] * 0.20
                + fundamental_sub["valuation"] * 0.15,
            )
            anchored_fundamental = max(0, min(100, anchored_fundamental))
        else:
            anchored_fundamental = None
        fundamental_overlay = self.compute_fundamental_overlay(fundamental_sub)
        fundamental_shadow = {
            "strategy": None,
            "gate_status": None,
            "recommended_status": None,
        }

        options_sub = None
        if options_metrics:
            options_sub = {
                "fear_greed": options_metrics.get("fear_greed", "NEUTRAL"),
                "put_call_volume_ratio": options_metrics.get("put_call_volume_ratio"),
                "iv_skew": options_metrics.get("iv_skew"),
            }

        flow_toxicity_sub = None
        if flow_toxicity_metrics and flow_toxicity_metrics.get("composite_score") is not None:
            flow_toxicity_sub = {
                "composite_score": flow_toxicity_metrics["composite_score"],
                "toxicity_level": flow_toxicity_metrics.get("toxicity_level", "UNKNOWN"),
                "vpin_proxy": flow_toxicity_metrics.get("vpin_proxy"),
                "direction": flow_toxicity_metrics.get("direction", "NEUTRAL"),
            }

        # Compute anchored macro sub-scores if metrics provided
        macro_sub = None
        _macro_cov = (macro_metrics or {}).get("data_coverage", 0.0)
        _macro_gated = macro_metrics is not None and _macro_cov < MIN_ANCHOR_COVERAGE
        if macro_metrics and not _macro_gated:
            macro_sub = self._compute_macro_sub(macro_metrics)
            anchored_macro = round(
                macro_sub["regime_fit"] * 0.25
                + macro_sub["monetary_stress"] * 0.25
                + macro_sub["rate_headwind"] * 0.25
                + macro_sub["commodity_cycle"] * 0.25,
            )
            anchored_macro = max(0, min(100, anchored_macro))
        else:
            anchored_macro = None

        momentum_sub = None
        _mom_cov = (momentum_metrics or {}).get("data_coverage", 0.0)
        _mom_gated = momentum_metrics is not None and _mom_cov < MIN_ANCHOR_COVERAGE
        if momentum_metrics and not _mom_gated:
            momentum_sub = self._compute_momentum_sub(momentum_metrics)
            anchored_momentum = round(
                momentum_sub["trend_strength"]      * 0.40
                + momentum_sub["momentum_health"]   * 0.30
                + momentum_sub["regime_quality"]    * 0.20
                + momentum_sub["volume_confirmation"] * 0.10
            )
            anchored_momentum = max(0, min(100, anchored_momentum))
        else:
            anchored_momentum = None

        data_quality_gate = {
            "fundamental": _fund_gated,
            "macro": _macro_gated,
            "momentum": _mom_gated,
        }

        scores = {
            "fundamental": anchored_fundamental if anchored_fundamental is not None else self._clamp_score(data.get("fundamental_score", 50)),
            "macro": anchored_macro if anchored_macro is not None else self._clamp_score(data.get("macro_score", 50)),
            "momentum": anchored_momentum if anchored_momentum is not None else self._clamp_score(data.get("momentum_score", 50)),
        }

        # Coherence: cross-pillar meta-analysis (replaces technical dimension)
        coherence_snapshot = build_coherence_snapshot(
            pillar_composites=scores,
            fundamental_sub=fundamental_sub,
            macro_sub=macro_sub,
            sentiment_sub=None,
            momentum_sub=momentum_sub,
            sentiment_low_coverage=False,
        )
        coherence_sub = coherence_snapshot["subscores"]
        scores["coherence"] = coherence_snapshot["composite_score"]

        # Regime-adaptive weights
        regime = (macro_metrics or {}).get("regime", "NEUTRAL")

        # Extract debate voice scores
        research_debate_score = self._extract_research_debate_score(state)
        trader_verdict_score = self._extract_trader_verdict_score(state)
        risk_verdict_score = self._extract_risk_verdict_score(state)

        # Build 8-model signal dict
        model_scores = {
            "fundamental":     scores["fundamental"],
            "coherence":       scores["coherence"],
            "macro":           scores["macro"],
            "momentum":        scores["momentum"],
            "research_debate": research_debate_score,
            "trader_verdict":  trader_verdict_score,
            "risk_verdict":    risk_verdict_score,
        }

        # Determine active models (non-None scores)
        active_models = {k for k, v in model_scores.items() if v is not None}
        quant_pillars = {"fundamental", "coherence", "macro", "momentum"}

        if not active_models - quant_pillars:
            # No debate voices — pure quant fallback (identical to previous behavior)
            quant_weights = get_weights(regime)
            aeternus_score = round(
                scores["fundamental"] * quant_weights["fundamental"]
                + scores["coherence"]  * quant_weights["coherence"]
                + scores["macro"]      * quant_weights["macro"]
                + scores["momentum"]   * quant_weights["momentum"],
                2,
            )
            effective_weights = quant_weights
        else:
            # Ensemble blend with debate voices
            ensemble_store = EnsembleWeightStore.load()
            effective_weights = ensemble_store.get_effective_weights(regime, active_models)
            aeternus_score = round(
                sum(model_scores[k] * effective_weights[k] for k in active_models),
                2,
            )

        # Quant-only reference score (for drift monitoring)
        quant_weights_ref = get_weights(regime)
        quant_only_score = round(
            sum(scores[p] * quant_weights_ref[p] for p in quant_weights_ref), 2
        )

        # Alpha decomposition (factor-neutral analysis)
        alpha_decomposition = self._compute_alpha_decomposition(
            aeternus_score, scores, fundamental_sub
        )

        # Catalyst timeline metadata
        catalyst_timeline = self._compute_catalyst_timeline(resolved_ticker)

        # Epistemic transparency report
        epistemic = None
        try:
            epistemic = build_epistemic_report(
                fundamental_metrics=fundamental_metrics,
                macro_metrics=macro_metrics,
                momentum_metrics=momentum_metrics,
                options_metrics=options_metrics,
                coherence_snapshot=coherence_snapshot,
                weights=effective_weights,
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

        # Calibration context
        calibration_context = None
        try:
            calibration_context = self._get_calibration()
        except Exception:
            pass

        rating = self._rating_from_score(aeternus_score)

        # Extract price_target and catalyst from LLM response or use provided values
        llm_price_target = data.get("price_target")
        llm_catalyst = data.get("catalyst")
        resolved_price_target = price_target or llm_price_target
        resolved_catalyst = catalyst or llm_catalyst

        confidence_factors = self._compute_confidence_factors(
            state=state,
            llm_data=data,
            sector=sector_data.get("sector"),
            price_target=resolved_price_target,
            catalyst=resolved_catalyst,
        )
        confidence = self._compute_weighted_confidence(confidence_factors)

        # Apply IC confidence calibration delta
        ic_adjustments_applied = False
        try:
            from tradingagents.scheduler.agents.investment_committee import load_ic_adjustments
            ic_conf = load_ic_adjustments("ic_confidence_calibration.json").get("adjustments", {})
            conf_delta = ic_conf.get(str(confidence), 0.0)
            if conf_delta:
                confidence = max(1, min(5, int(round(confidence + conf_delta))))
                ic_adjustments_applied = True
        except Exception:
            pass

        return AeternusRating(
            rating_id=str(uuid.uuid4()),  # Generate unique ID
            ticker=resolved_ticker,
            date=resolved_date,
            aeternus_score=aeternus_score,
            rating=rating,
            confidence=confidence,
            confidence_factors=confidence_factors,
            sector=sector_data.get("sector"),
            peer_comparison=sector_data.get("peer_comparison"),
            breakdown=scores,
            rationales=data.get("score_rationales", {}),
            price_at_rating=price_at_rating,
            price_target=resolved_price_target,
            catalyst=resolved_catalyst,
            fundamental_sub=fundamental_sub,
            fundamental_overlay_score=fundamental_overlay["score"],
            fundamental_overlay_label=fundamental_overlay["label"],
            fundamental_overlay_notes=fundamental_overlay["notes"],
            fundamental_shadow_strategy=fundamental_shadow["strategy"],
            fundamental_shadow_gate_status=fundamental_shadow["gate_status"],
            fundamental_shadow_recommended_status=fundamental_shadow["recommended_status"],
            macro_sub=macro_sub,
            momentum_sub=momentum_sub,
            options_sub=options_sub,
            flow_toxicity_sub=flow_toxicity_sub,
            coherence_sub=coherence_sub,
            detected_patterns=coherence_snapshot.get("detected_patterns", []),
            regime_weights=effective_weights,
            weight_regime=regime,
            alpha_decomposition=alpha_decomposition,
            catalyst_timeline=catalyst_timeline,
            epistemic=epistemic,
            calibration_context=calibration_context,
            data_quality_gate=data_quality_gate,
            epistemic_summary=epistemic_summary,
            ic_adjustments_applied=ic_adjustments_applied,
            ensemble_weights=effective_weights,
            ensemble_model_scores={k: v for k, v in model_scores.items()},
            quant_only_score=quant_only_score,
            timestamp=datetime.now().isoformat()
        )

    # --- Anchored fundamental sub-score computation ---

    def _compute_fundamental_sub(self, metrics: Dict[str, Any]) -> Dict[str, int]:
        """Compute 4 fundamental sub-scores from Python-computed metrics.

        Sub-scores: quality, growth, health, valuation (each 0-100).
        """
        quality = self._score_quality(metrics)
        growth = self._score_growth(metrics)
        health = self._score_health(metrics)
        valuation = self._score_valuation(metrics)
        return {
            "quality": max(0, min(100, quality)),
            "growth": max(0, min(100, growth)),
            "health": max(0, min(100, health)),
            "valuation": max(0, min(100, valuation)),
        }

    @staticmethod
    def compute_fundamental_overlay(
        fundamental_sub: Optional[Dict[str, int]],
    ) -> Dict[str, Any]:
        if not fundamental_sub:
            return {
                "score": None,
                "label": None,
                "notes": None,
            }

        score = round(
            (fundamental_sub["health"] * 0.5)
            + ((100 - fundamental_sub["quality"]) * 0.4)
            + ((100 - fundamental_sub["growth"]) * 0.1),
            2,
        )
        if score >= 70:
            label = "UNDERAPPRECIATED_RESILIENCE"
            notes = "Health leads while visible growth/quality expectations look less crowded."
        elif score <= 40:
            label = "CROWDING_RISK"
            notes = "Visible quality/growth appears crowded relative to balance-sheet resilience."
        else:
            label = "BALANCED"
            notes = "Resilience and expectation risk are mixed; treat as advisory only."
        return {
            "score": score,
            "label": label,
            "notes": notes,
        }

    def _score_quality(self, m: Dict[str, Any]) -> int:
        """Quality sub-score anchored to F-Score and ROE thresholds."""
        piotroski = m.get("piotroski", {})
        ratios = m.get("ratios", {})

        fscore = piotroski.get("fscore")
        if fscore is None:
            return 50

        # F-Score mapping: 9=100, 7=75, 5=50, 3=25, linear interpolation
        score = max(0, min(100, int(round((fscore / 9) * 100))))

        # ROE bonus/penalty
        roe = ratios.get("roe")
        if roe is not None:
            if roe > 15:
                score += 10
            elif roe < 0:
                score -= 15

        return score

    def _score_growth(self, m: Dict[str, Any]) -> int:
        """Growth sub-score anchored to revenue/earnings growth thresholds."""
        ratios = m.get("ratios", {})
        income = m.get("income", {})

        rev_growth = ratios.get("quarterly_revenue_growth_yoy")
        earn_growth = ratios.get("quarterly_earnings_growth_yoy")
        rev_growth_qoq = income.get("revenue_growth_qoq")

        # Use best available growth signal
        growth = rev_growth
        if growth is None:
            growth = rev_growth_qoq
        if growth is None:
            growth = earn_growth

        if growth is None:
            return 50

        # Convert to percentage if in decimal form (e.g., 0.25 -> 25)
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

        # Margin trend bonus
        margin_trend = income.get("margin_trend")
        if margin_trend == "improving":
            score += 5
        elif margin_trend == "declining":
            score -= 5

        return score

    def _score_health(self, m: Dict[str, Any]) -> int:
        """Health sub-score anchored to balance sheet and cash flow thresholds."""
        balance = m.get("balance", {})
        cashflow = m.get("cashflow", {})

        score = 50  # neutral start

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

        # D/E penalty
        de = balance.get("debt_to_equity")
        if de is not None:
            if de > 3.0:
                score -= 10
            elif de < 0.5:
                score += 5

        # FCF adjustment
        fcf_pos = cashflow.get("fcf_positive")
        if fcf_pos is False:
            score -= 15
        elif fcf_pos is True:
            score += 5

        # OCF trend bonus
        ocf_trend = cashflow.get("ocf_trend")
        if ocf_trend == "improving":
            score += 5
        elif ocf_trend == "declining":
            score -= 5

        return score

    def _score_valuation(self, m: Dict[str, Any]) -> int:
        """Valuation sub-score anchored to PE/EV and analyst target thresholds."""
        ratios = m.get("ratios", {})

        score = 50  # neutral start

        fpe = ratios.get("forward_pe")
        pe = ratios.get("pe")
        target_pe = fpe if fpe is not None else pe

        if target_pe is not None:
            if target_pe < 0:
                score = 30  # negative earnings
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

        # PEG ratio adjustment
        peg = ratios.get("peg")
        if peg is not None:
            if 0 < peg < 1:
                score += 10
            elif peg > 3:
                score -= 5

        return score

    # --- End anchored sub-scores ---

    # --- Anchored macro sub-score computation ---

    def _compute_macro_sub(self, metrics: Dict[str, Any]) -> Dict[str, int]:
        """Compute 4 macro sub-scores from Python-computed metrics.

        Sub-scores: regime_fit, monetary_stress, rate_headwind, commodity_cycle (each 0-100).
        Reads from the 'subscores' key of the macro_metrics dict produced by macro_engine.py.
        """
        subscores = metrics.get("subscores", {})
        return {
            "regime_fit": max(0, min(100, int(subscores.get("regime_fit", 50)))),
            "monetary_stress": max(0, min(100, int(subscores.get("monetary_stress", 50)))),
            "rate_headwind": max(0, min(100, int(subscores.get("rate_headwind", 50)))),
            "commodity_cycle": max(0, min(100, int(subscores.get("commodity_cycle", 50)))),
        }

    # --- End anchored macro sub-scores ---

    # --- Anchored momentum sub-score computation ---

    def _compute_momentum_sub(self, metrics: Dict[str, Any]) -> Dict[str, int]:
        subscores = metrics.get("subscores", {})
        return {
            "trend_strength":      max(0, min(100, int(subscores.get("trend_strength",      50)))),
            "momentum_health":     max(0, min(100, int(subscores.get("momentum_health",      50)))),
            "regime_quality":      max(0, min(100, int(subscores.get("regime_quality",       50)))),
            "volume_confirmation": max(0, min(100, int(subscores.get("volume_confirmation",  50)))),
        }

    # --- End anchored momentum sub-scores ---

    # --- Alpha decomposition ---

    def _compute_alpha_decomposition(
        self,
        aeternus_score: float,
        scores: Dict[str, int],
        fundamental_sub: Optional[Dict[str, int]],
    ) -> Dict[str, Any]:
        """Factor-neutral alpha decomposition.

        Uses Fama-French 3-factor data when available, falls back to
        heuristic 3-factor model (macro/valuation/momentum blend).
        """
        valuation_score = (
            fundamental_sub["valuation"]
            if fundamental_sub and "valuation" in fundamental_sub
            else scores.get("fundamental", 50)
        )

        ff = get_ff_factors(lookback_days=60)
        if ff is not None:
            # Map our pillar scores to factor loadings (-1 to +1)
            mkt_loading = scores.get("macro", 50) / 50.0 - 1.0
            val_loading = valuation_score / 50.0 - 1.0
            size_loading = 0.0  # neutral — we don't score size

            # Factor-predicted component (scale FF returns to our 0-100 score space)
            factor_predicted = 50.0 + (
                mkt_loading * ff["mkt_rf"] * 10.0
                + val_loading * ff["hml"] * 8.0
                + size_loading * ff["smb"] * 5.0
            )
            factor_predicted = max(0.0, min(100.0, factor_predicted))
            factor_source = "fama_french"
        else:
            # Fallback to heuristic model
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

        return {
            "factor_predicted": round(factor_predicted, 2),
            "alpha_residual": round(alpha_residual, 2),
            "interpretation": interpretation,
            "factor_source": factor_source,
        }

    # --- Catalyst timeline ---

    def _compute_catalyst_timeline(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Fetch upcoming catalyst events from yfinance calendar. Metadata only."""
        if not ticker:
            return None
        try:
            import yfinance as yf
            from datetime import datetime

            info = yf.Ticker(ticker)
            cal = info.calendar
            if cal is None or (isinstance(cal, dict) and not cal):
                return {"days_to_earnings": None, "days_to_dividend": None,
                        "earnings_proximity": "unknown", "event_density_30d": 0}

            today = datetime.now().date()
            events = []

            # Handle earnings date
            earnings_date = None
            if isinstance(cal, dict):
                ed = cal.get("Earnings Date")
                if ed is not None:
                    if isinstance(ed, list) and len(ed) > 0:
                        earnings_date = ed[0]
                    elif hasattr(ed, "date"):
                        earnings_date = ed
            elif hasattr(cal, "get"):
                ed = cal.get("Earnings Date")
                if ed is not None and isinstance(ed, list) and len(ed) > 0:
                    earnings_date = ed[0]

            days_to_earnings = None
            if earnings_date is not None:
                try:
                    if hasattr(earnings_date, "date"):
                        ed_date = earnings_date.date()
                    else:
                        ed_date = earnings_date
                    days_to_earnings = (ed_date - today).days
                    if days_to_earnings >= 0:
                        events.append(days_to_earnings)
                except Exception:
                    pass

            # Handle dividend date
            dividend_date = None
            if isinstance(cal, dict):
                dd = cal.get("Dividend Date") or cal.get("Ex-Dividend Date")
                if dd is not None:
                    if isinstance(dd, list) and len(dd) > 0:
                        dividend_date = dd[0]
                    elif hasattr(dd, "date"):
                        dividend_date = dd

            days_to_dividend = None
            if dividend_date is not None:
                try:
                    if hasattr(dividend_date, "date"):
                        dd_date = dividend_date.date()
                    else:
                        dd_date = dividend_date
                    days_to_dividend = (dd_date - today).days
                    if days_to_dividend >= 0:
                        events.append(days_to_dividend)
                except Exception:
                    pass

            # Earnings proximity
            if days_to_earnings is not None and days_to_earnings >= 0:
                if days_to_earnings <= 7:
                    earnings_proximity = "imminent"
                elif days_to_earnings <= 30:
                    earnings_proximity = "near"
                else:
                    earnings_proximity = "distant"
            else:
                earnings_proximity = "unknown"

            event_density_30d = sum(1 for e in events if 0 <= e <= 30)

            return {
                "days_to_earnings": days_to_earnings,
                "days_to_dividend": days_to_dividend,
                "earnings_proximity": earnings_proximity,
                "event_density_30d": event_density_30d,
            }
        except Exception:
            return None

    def _resolve_ticker(self, state: Dict[str, Any], ticker: str) -> str:
        return (
            ticker
            or state.get("ticker", "")
            or state.get("company_of_interest", "")
        )

    def _resolve_date(self, state: Dict[str, Any], date: str) -> str:
        return (
            date
            or state.get("date", "")
            or state.get("trade_date", "")
        )

    def _is_nonempty(self, value: Any) -> bool:
        return confidence_helpers.is_nonempty(value)

    def _normalize_factor(self, value: Any, default: int = 3) -> int:
        return confidence_helpers.normalize_factor(value, default=default)

    def _map_accuracy_to_factor(self, value: Any) -> int:
        return confidence_helpers.map_accuracy_to_factor(value)

    def _compute_data_quality_factor(self, state: Dict[str, Any]) -> int:
        return confidence_helpers.compute_data_quality_factor(state)

    def _compute_historical_accuracy_factor(
        self,
        sector: Optional[str],
        confidence_level: int,
    ) -> int:
        return confidence_helpers.compute_historical_accuracy_factor(
            track_record=self.track_record,
            sector=sector,
            confidence_level=confidence_level,
        )

    def _compute_confidence_factors(
        self,
        state: Dict[str, Any],
        llm_data: Dict[str, Any],
        sector: Optional[str],
        price_target: Optional[float],
        catalyst: Optional[str],
    ) -> Dict[str, int]:
        return confidence_helpers.compute_confidence_factors(
            state=state,
            llm_data=llm_data,
            sector=sector,
            price_target=price_target,
            catalyst=catalyst,
            track_record=self.track_record,
        )

    def _compute_weighted_confidence(self, factors: Dict[str, int]) -> int:
        return confidence_helpers.compute_weighted_confidence(factors)

    def _safe_parse_json(self, text: str) -> Dict[str, Any]:
        return scoring_json_utils.safe_parse_json(text)

    def _clamp_score(self, value: Any) -> int:
        return rating_helpers.clamp_score(value)

    def _clamp_confidence(self, value: Any) -> int:
        return confidence_helpers.clamp_confidence(value)

    # --- Debate voice signal extraction (ensemble inputs) ---

    _DIRECTION_BASE = {"BUY": 65, "SELL": 35, "HOLD": 50}

    def _extract_research_debate_score(self, state: Dict[str, Any]) -> Optional[int]:
        """Extract 0-100 score from research debate (bull/bear synthesis).

        Source: state["investment_debate_state"]["judge_decision"] string.
        Fallback: keyword scan on investment_plan with default conviction=3.
        """
        judge_text = None
        debate_state = state.get("investment_debate_state")
        if isinstance(debate_state, dict):
            judge_text = debate_state.get("judge_decision")

        decision, conviction, bull_str, bear_str = None, 3, 3, 3

        if judge_text and isinstance(judge_text, str):
            # Try structured format: "Decision: BUY | Conviction: 4/5 | Bull Strength: 4/5 | Bear Strength: 2/5"
            m = re.search(r"Decision:\s*(BUY|SELL|HOLD)", judge_text, re.IGNORECASE)
            if m:
                decision = m.group(1).upper()
            m = re.search(r"Conviction:\s*(\d)", judge_text)
            if m:
                conviction = max(1, min(5, int(m.group(1))))
            m = re.search(r"Bull\s*Strength:\s*(\d)", judge_text)
            if m:
                bull_str = max(1, min(5, int(m.group(1))))
            m = re.search(r"Bear\s*Strength:\s*(\d)", judge_text)
            if m:
                bear_str = max(1, min(5, int(m.group(1))))

        # Fallback: keyword scan on investment_plan
        if decision is None:
            plan_text = str(state.get("investment_plan", ""))[:500].upper()
            if not plan_text:
                return None
            for kw in ("SELL", "SHORT", "BEARISH"):
                if kw in plan_text:
                    decision = "SELL"
                    break
            if decision is None:
                for kw in ("BUY", "LONG", "BULLISH"):
                    if kw in plan_text:
                        decision = "BUY"
                        break
            if decision is None:
                for kw in ("HOLD", "NEUTRAL"):
                    if kw in plan_text:
                        decision = "HOLD"
                        break
            if decision is None:
                return None

        direction_base = self._DIRECTION_BASE[decision]
        conviction_mod = (conviction - 3) * 5
        context_mod = max(-12, min(12, (bull_str - bear_str) * 3))
        return max(0, min(100, direction_base + conviction_mod + context_mod))

    def _extract_trader_verdict_score(self, state: Dict[str, Any]) -> Optional[int]:
        """Extract 0-100 score from structured trader verdict.

        Source: state["structured_trader_verdict"] (TraderVerdict dict).
        """
        verdict = state.get("structured_trader_verdict")
        if not verdict or not isinstance(verdict, dict) or "decision" not in verdict:
            return None

        decision = verdict["decision"].upper()
        if decision not in self._DIRECTION_BASE:
            return None

        conviction = max(1, min(5, int(verdict.get("conviction", 3))))
        position_size_pct = float(verdict.get("position_size_pct", 0.05))

        direction_base = self._DIRECTION_BASE[decision]
        conviction_mod = (conviction - 3) * 5
        size_mod = max(-4, min(5, round((position_size_pct - 0.05) * 100)))

        # Scenario probability-weighted EV
        scenario_ev = 0.0
        for s in verdict.get("scenarios", []):
            prob = float(s.get("probability", 0))
            ret = float(s.get("target_return_pct", 0) or 0)
            scenario_ev += prob * ret
        scenario_mod = max(-8, min(8, round(scenario_ev * 2)))

        return max(0, min(100, direction_base + conviction_mod + size_mod + scenario_mod))

    def _extract_risk_verdict_score(self, state: Dict[str, Any]) -> Optional[int]:
        """Extract 0-100 score from structured risk verdict.

        Source: state["structured_verdict"] (RiskVerdict dict).
        """
        verdict = state.get("structured_verdict")
        if not verdict or not isinstance(verdict, dict) or "decision" not in verdict:
            return None

        decision = verdict["decision"].upper()
        if decision not in self._DIRECTION_BASE:
            return None

        conviction = max(1, min(5, int(verdict.get("conviction", 3))))

        direction_base = self._DIRECTION_BASE[decision]
        conviction_mod = (conviction - 3) * 5

        # Hedge directive modifier
        hedge = verdict.get("hedge_directive", "NO_CHANGE")
        hedge_mod = {"INCREASE_HEDGE": -5, "NO_CHANGE": 0, "DECREASE_HEDGE": 3}.get(hedge, 0)

        # Dissent modifier
        dissent_mod = 0
        for d in verdict.get("dissent_records", []):
            dissent_mod -= min(int(d.get("dissent_strength", 0)), 3)

        # Drawdown modifier
        drawdown_mod = -8 if verdict.get("drawdown_mode") else 0

        # Position size modifier
        max_pos = float(verdict.get("max_position_pct", 0.05))
        position_mod = max(-3, min(3, round((max_pos - 0.05) * 60)))

        return max(0, min(100, direction_base + conviction_mod + hedge_mod + dissent_mod + drawdown_mod + position_mod))

    # --- End debate voice extraction ---

    def _rating_from_score(self, score: float) -> str:
        return rating_helpers.rating_from_score(score)
