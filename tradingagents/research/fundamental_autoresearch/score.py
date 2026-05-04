from tradingagents.research.fundamental_autoresearch.contracts import FundamentalScoreResult


_STRATEGY_WEIGHTS: dict[str, dict[str, float]] = {
    "baseline_v1": {
        "growth": 0.25,
        "quality": 0.25,
        "health": 0.20,
        "capital_discipline": 0.10,
        "valuation": 0.20,
    },
    "growth_only": {
        "growth": 1.0,
        "quality": 0.0,
        "health": 0.0,
        "capital_discipline": 0.0,
        "valuation": 0.0,
    },
    "quality_only": {
        "growth": 0.0,
        "quality": 1.0,
        "health": 0.0,
        "capital_discipline": 0.0,
        "valuation": 0.0,
    },
    "health_only": {
        "growth": 0.0,
        "quality": 0.0,
        "health": 1.0,
        "capital_discipline": 0.0,
        "valuation": 0.0,
    },
    "capital_discipline_only": {
        "growth": 0.0,
        "quality": 0.0,
        "health": 0.0,
        "capital_discipline": 1.0,
        "valuation": 0.0,
    },
    "valuation_only": {
        "growth": 0.0,
        "quality": 0.0,
        "health": 0.0,
        "capital_discipline": 0.0,
        "valuation": 1.0,
    },
    "growth_quality": {
        "growth": 0.5,
        "quality": 0.5,
        "health": 0.0,
        "capital_discipline": 0.0,
        "valuation": 0.0,
    },
    "quality_valuation": {
        "growth": 0.0,
        "quality": 0.5,
        "health": 0.0,
        "capital_discipline": 0.0,
        "valuation": 0.5,
    },
    "growth_only_inverted": {
        "growth": -1.0,
        "quality": 0.0,
        "health": 0.0,
        "capital_discipline": 0.0,
        "valuation": 0.0,
    },
    "quality_only_inverted": {
        "growth": 0.0,
        "quality": -1.0,
        "health": 0.0,
        "capital_discipline": 0.0,
        "valuation": 0.0,
    },
    "growth_quality_inverted": {
        "growth": -0.5,
        "quality": -0.5,
        "health": 0.0,
        "capital_discipline": 0.0,
        "valuation": 0.0,
    },
    "health_minus_growth": {
        "growth": -0.3,
        "quality": 0.0,
        "health": 0.7,
        "capital_discipline": 0.0,
        "valuation": 0.0,
    },
    "health_minus_quality": {
        "growth": 0.0,
        "quality": -0.3,
        "health": 0.7,
        "capital_discipline": 0.0,
        "valuation": 0.0,
    },
}

_COMPONENT_ORDER = (
    "growth",
    "quality",
    "health",
    "capital_discipline",
    "valuation",
    "growth_acceleration",
    "margin_expansion",
    "quality_tension_inverse",
    "balance_sheet_resilience",
)


def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


def _score_growth(features: dict) -> float:
    revenue = features.get("revenue_growth_yoy_pct") or 0.0
    fcf = features.get("fcf_growth_yoy_pct") or 0.0
    equity = features.get("equity_change_pct") or 0.0
    revenue_accel = features.get("revenue_growth_acceleration_pct") or 0.0
    fcf_accel = features.get("fcf_growth_acceleration_pct") or 0.0
    return _clamp(
        50.0
        + (0.55 * revenue)
        + (0.55 * fcf)
        + (0.35 * equity)
        + (0.8 * revenue_accel)
        + (0.8 * fcf_accel)
    )


def _score_quality(features: dict) -> float:
    gross_margin = (features.get("gross_margin") or 0.0) * 100.0
    operating_margin = (features.get("operating_margin") or 0.0) * 100.0
    margin_change = features.get("margin_change_pct") or 0.0
    tension = features.get("quality_valuation_tension") or 0.0
    raw = (gross_margin * 0.4) + (operating_margin * 0.45) + (margin_change * 2.0)
    tension_penalty = tension * 6.0
    return _clamp(raw - tension_penalty)


def _score_health(features: dict) -> float:
    debt_to_equity = features.get("debt_to_equity")
    current_ratio = features.get("current_ratio")
    liquidity_stress = features.get("liquidity_stress_score")
    leverage_stress = features.get("leverage_stress_score")
    debt_component = 50.0 if debt_to_equity is None else _clamp(100.0 - (debt_to_equity * 30.0))
    liquidity_component = 50.0 if current_ratio is None else _clamp(current_ratio * 60.0)
    stress_penalty = 0.0
    if liquidity_stress is not None:
        stress_penalty += liquidity_stress * 10.0
    if leverage_stress is not None:
        stress_penalty += leverage_stress * 10.0
    return _clamp(((debt_component * 0.55) + (liquidity_component * 0.45)) - stress_penalty)


def _score_capital_discipline(features: dict) -> float:
    share_count_change = features.get("share_count_change_pct")
    if share_count_change is None:
        return 50.0
    return _clamp(60.0 + (-share_count_change * 10.0))


def _score_valuation(features: dict) -> float:
    ev_to_sales = features.get("ev_to_sales")
    earnings_yield = features.get("earnings_yield")
    ev_component = 50.0 if ev_to_sales is None else _clamp(100.0 - (ev_to_sales * 8.0))
    earnings_component = 50.0 if earnings_yield is None else _clamp(earnings_yield * 1200.0)
    return _clamp((ev_component * 0.4) + (earnings_component * 0.6))


def _score_growth_acceleration(features: dict) -> float:
    revenue_accel = features.get("revenue_growth_acceleration_pct") or 0.0
    fcf_accel = features.get("fcf_growth_acceleration_pct") or 0.0
    return _clamp(50.0 + (1.25 * revenue_accel) + (1.25 * fcf_accel))


def _score_margin_expansion(features: dict) -> float:
    margin_change = features.get("margin_change_pct") or 0.0
    return _clamp(50.0 + (3.5 * margin_change))


def _score_quality_tension_inverse(features: dict) -> float:
    tension = features.get("quality_valuation_tension") or 0.0
    return _clamp(100.0 - (tension * 10.0))


def _score_balance_sheet_resilience(features: dict) -> float:
    debt_to_equity = features.get("debt_to_equity")
    current_ratio = features.get("current_ratio")
    liquidity_stress = features.get("liquidity_stress_score") or 0.0
    leverage_stress = features.get("leverage_stress_score") or 0.0
    debt_component = 50.0 if debt_to_equity is None else _clamp(100.0 - (debt_to_equity * 28.0))
    liquidity_component = 50.0 if current_ratio is None else _clamp(current_ratio * 62.0)
    resilience = (debt_component * 0.45) + (liquidity_component * 0.55)
    stress_penalty = (liquidity_stress * 12.0) + (leverage_stress * 12.0)
    return _clamp(resilience - stress_penalty)


_COMPONENT_SCORERS = {
    "growth": _score_growth,
    "quality": _score_quality,
    "health": _score_health,
    "capital_discipline": _score_capital_discipline,
    "valuation": _score_valuation,
    "growth_acceleration": _score_growth_acceleration,
    "margin_expansion": _score_margin_expansion,
    "quality_tension_inverse": _score_quality_tension_inverse,
    "balance_sheet_resilience": _score_balance_sheet_resilience,
}


def compute_component_scores(features: dict) -> dict[str, float]:
    return {
        component: scorer(features)
        for component, scorer in _COMPONENT_SCORERS.items()
    }


def score_component(features: dict, component: str) -> float:
    if component not in _COMPONENT_SCORERS:
        raise ValueError(f"Unknown fundamental component: {component}")
    return _COMPONENT_SCORERS[component](features)


def get_component_catalog() -> tuple[str, ...]:
    return _COMPONENT_ORDER


def _blend_component(component_score: float, weight: float) -> float:
    if weight >= 0:
        return weight * component_score
    return abs(weight) * (100.0 - component_score)


def score_feature_row_with_weights(
    features: dict,
    *,
    component_weights: dict[str, float],
    strategy_name: str,
) -> FundamentalScoreResult:
    weights = component_weights
    component_scores = compute_component_scores(features)
    growth_score = component_scores["growth"]
    quality_score = component_scores["quality"]
    health_score = component_scores["health"]
    capital_discipline_score = component_scores["capital_discipline"]
    valuation_score = component_scores["valuation"]
    coverage_multiplier = 0.5 + (0.5 * float(features.get("data_coverage_score") or 0.0))

    total = (
        sum(
            _blend_component(component_scores[name], weight)
            for name, weight in weights.items()
            if name in component_scores and weight != 0
        )
    ) * coverage_multiplier

    return FundamentalScoreResult(
        ticker=features["ticker"],
        effective_market_date=features["effective_market_date"],
        fundamental_score=round(_clamp(total), 4),
        growth_score=round(growth_score, 4),
        quality_score=round(quality_score, 4),
        health_score=round(health_score, 4),
        capital_discipline_score=round(capital_discipline_score, 4),
        valuation_score=round(valuation_score, 4),
        score_version=strategy_name,
    )


def score_feature_row(features: dict, *, strategy: str = "baseline_v1") -> FundamentalScoreResult:
    if strategy not in _STRATEGY_WEIGHTS:
        raise ValueError(f"Unknown fundamental scoring strategy: {strategy}")
    return score_feature_row_with_weights(
        features,
        component_weights=_STRATEGY_WEIGHTS[strategy],
        strategy_name=strategy,
    )
