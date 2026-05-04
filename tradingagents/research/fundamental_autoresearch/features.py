from tradingagents.research.fundamental_autoresearch.contracts import FilingSnapshotRow


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return ((current - previous) / abs(previous)) * 100.0


def _collect_missing_fields(metrics: dict[str, float | None]) -> list[str]:
    return [key for key, value in metrics.items() if value is None]


def _bounded_ratio(value: float | None, *, floor: float = 0.0, ceiling: float = 2.0) -> float | None:
    if value is None:
        return None
    return max(floor, min(ceiling, value))


def build_feature_row(
    row: FilingSnapshotRow,
    *,
    current_metrics: dict[str, float | None],
    previous_metrics: dict[str, float | None] | None = None,
) -> dict:
    previous_metrics = previous_metrics or {}
    missing_fields = _collect_missing_fields(current_metrics)
    present_fields = len(current_metrics) - len(missing_fields)
    coverage = present_fields / len(current_metrics) if current_metrics else 0.0

    gross_margin = _safe_div(current_metrics.get("gross_profit"), current_metrics.get("revenue"))
    operating_margin = _safe_div(current_metrics.get("operating_income"), current_metrics.get("revenue"))
    debt_to_equity = _safe_div(current_metrics.get("total_debt"), current_metrics.get("shareholder_equity"))
    current_ratio = _safe_div(current_metrics.get("current_assets"), current_metrics.get("current_liabilities"))
    ev_to_sales = _safe_div(current_metrics.get("enterprise_value"), current_metrics.get("revenue"))
    earnings_yield = _safe_div(current_metrics.get("net_income"), current_metrics.get("market_cap"))
    previous_revenue_growth = _pct_change(
        previous_metrics.get("revenue"),
        previous_metrics.get("previous_revenue"),
    )
    previous_fcf_growth = _pct_change(
        previous_metrics.get("free_cash_flow"),
        previous_metrics.get("previous_free_cash_flow"),
    )
    current_revenue_growth = _pct_change(
        current_metrics.get("revenue"),
        previous_metrics.get("revenue"),
    )
    current_fcf_growth = _pct_change(
        current_metrics.get("free_cash_flow"),
        previous_metrics.get("free_cash_flow"),
    )
    revenue_growth_acceleration = (
        None
        if current_revenue_growth is None or previous_revenue_growth is None
        else current_revenue_growth - previous_revenue_growth
    )
    fcf_growth_acceleration = (
        None
        if current_fcf_growth is None or previous_fcf_growth is None
        else current_fcf_growth - previous_fcf_growth
    )
    margin_change_pct = None
    if operating_margin is not None and previous_metrics.get("previous_operating_margin") is not None:
        margin_change_pct = (operating_margin - previous_metrics["previous_operating_margin"]) * 100.0
    elif gross_margin is not None and previous_metrics.get("previous_gross_margin") is not None:
        margin_change_pct = (gross_margin - previous_metrics["previous_gross_margin"]) * 100.0

    quality_valuation_tension = (
        None
        if operating_margin is None or ev_to_sales is None
        else operating_margin * ev_to_sales
    )
    liquidity_ratio_delta = (
        None
        if current_ratio is None or previous_metrics.get("previous_current_ratio") is None
        else current_ratio - previous_metrics["previous_current_ratio"]
    )
    leverage_ratio_delta = (
        None
        if debt_to_equity is None or previous_metrics.get("previous_debt_to_equity") is None
        else debt_to_equity - previous_metrics["previous_debt_to_equity"]
    )
    liquidity_stress_score = None
    if current_ratio is not None:
        liquidity_stress_score = _bounded_ratio(
            max(0.0, 1.5 - current_ratio) + max(0.0, -(liquidity_ratio_delta or 0.0)),
            ceiling=3.0,
        )
    leverage_stress_score = None
    if debt_to_equity is not None:
        leverage_stress_score = _bounded_ratio(
            (max(0.0, debt_to_equity) * 0.5) + max(0.0, leverage_ratio_delta or 0.0),
            ceiling=3.0,
        )

    return {
        "ticker": row.ticker,
        "effective_market_date": row.effective_market_date,
        "sector": row.sector,
        "revenue_growth_yoy_pct": current_revenue_growth,
        "fcf_growth_yoy_pct": current_fcf_growth,
        "revenue_growth_acceleration_pct": revenue_growth_acceleration,
        "fcf_growth_acceleration_pct": fcf_growth_acceleration,
        "share_count_change_pct": _pct_change(
            current_metrics.get("shares_outstanding"),
            previous_metrics.get("shares_outstanding"),
        ),
        "equity_change_pct": _pct_change(
            current_metrics.get("shareholder_equity"),
            previous_metrics.get("shareholder_equity"),
        ),
        "gross_margin": gross_margin,
        "operating_margin": operating_margin,
        "debt_to_equity": debt_to_equity,
        "current_ratio": current_ratio,
        "ev_to_sales": ev_to_sales,
        "earnings_yield": earnings_yield,
        "margin_change_pct": margin_change_pct,
        "quality_valuation_tension": quality_valuation_tension,
        "liquidity_stress_score": liquidity_stress_score,
        "leverage_stress_score": leverage_stress_score,
        "data_coverage_score": coverage,
        "missing_fields": missing_fields,
        "source_flags": list(row.source_flags),
        "restatement_suspect": row.restatement_suspect,
    }
