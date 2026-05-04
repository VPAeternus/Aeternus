"""Deterministic scoring and lane assignment for Deal Flow candidates."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean, pstdev
from typing import Dict, Iterable, List, Tuple

from .contracts import DealFlowCandidate, DealFlowSignal, UniverseRow
from .themes import infer_trend_tags, is_structural_growth_theme

CORE_SCORE_WEIGHTS: Dict[str, float] = {
    "social_momentum": 10.0,
    "price_momentum": 30.0,
    "macro_regime_fit": 14.0,
    "news_catalyst": 15.0,
    "smart_money": 11.0,
    "liquidity_tradability": 5.0,
    "sector_rotation": 8.0,
    "insider_cluster": 5.0,
    "emergence": 7.0,
}

GATING_FAMILIES = (
    "social_momentum",
    "macro_regime_fit",
    "news_catalyst",
    "smart_money",
    "price_momentum",
    "emergence",
)

CORE_SIGNAL_FAMILIES = (
    "social_momentum",
    "news_catalyst",
    "macro_regime_fit",
    "smart_money",
    "price_momentum",
    "sector_rotation",
    "insider_cluster",
    "emergence",
)


def score_candidates(
    universe: Iterable[UniverseRow],
    signals: Iterable[DealFlowSignal],
    min_signal_families: int,
    min_evidence_count: int,
    momentum_lane_threshold: float = 70.0,
    momentum_lane_price_override_threshold: float = 82.0,
    momentum_lane_social_confirmation_threshold: float = 60.0,
    momentum_lane_floor_ratio: float = 0.20,
    momentum_lane_promotion_min_score: float = 62.0,
    momentum_lane_promotion_min_price_score: float = 70.0,
    **_ignored,
) -> Tuple[List[DealFlowSignal], List[DealFlowCandidate]]:
    universe_map = {row["symbol"]: row for row in universe}
    signal_list = list(signals)

    _apply_family_z_scores(signal_list)
    grouped = _best_signal_per_symbol_family(signal_list)

    candidates: List[DealFlowCandidate] = []
    for symbol, row in universe_map.items():
        by_family = grouped.get(symbol, {})

        subscores: Dict[str, float] = {}
        active_families = 0
        evidence_count = 0
        freshness_values: List[float] = []

        for family in CORE_SIGNAL_FAMILIES:
            signal = by_family.get(family)
            if not signal:
                continue
            if signal.get("source_status") != "OK":
                continue
            score = float(signal.get("raw_score", 0.0))
            subscores[family] = score
            if family in GATING_FAMILIES:
                active_families += 1
                evidence_count += int(signal.get("evidence_count", 0))
            freshness_values.append(float(signal.get("freshness_hours", 9999.0)))

        liquidity = float(row.get("liquidity_score", 0.0))
        subscores["liquidity_tradability"] = liquidity

        core_score = _weighted_core_score(subscores)
        core_score = _apply_sector_override(core_score, str(row.get("sector", "Unknown")))
        momentum_score = _momentum_score(subscores)
        asymmetry_score = _asymmetry_score(subscores, momentum_score)

        trend_tags = infer_trend_tags(
            subscores,
            symbol=symbol,
            sector=str(row.get("sector", "Unknown")),
            asset_class=str(row.get("asset_class", "Unknown")),
        )

        lane = _assign_lane(
            subscores=subscores,
            trend_tags=trend_tags,
            momentum_score=momentum_score,
            momentum_lane_threshold=float(momentum_lane_threshold),
            momentum_lane_price_override_threshold=float(momentum_lane_price_override_threshold),
            momentum_lane_social_confirmation_threshold=float(momentum_lane_social_confirmation_threshold),
        )

        freshness_hours = min(freshness_values) if freshness_values else 9999.0
        status = "ACTIVE"
        if active_families < min_signal_families or evidence_count < min_evidence_count:
            status = "LOW_DATA"

        # Phase 1 lane metadata is proxy-only and does not drive current ranking.
        narrative_ignition_score = _narrative_ignition_score(subscores)
        fundamentals_acceleration_score = _fundamentals_acceleration_score(
            subscores,
            trend_tags,
        )
        relative_strength_score = _relative_strength_score(subscores)
        upside_3m_score = _upside_3m_score(
            core_score=core_score,
            momentum_score=momentum_score,
            asymmetry_score=asymmetry_score,
        )
        emergence_proxy_score = _emergence_proxy_score(
            narrative_ignition_score=narrative_ignition_score,
            fundamentals_acceleration_score=fundamentals_acceleration_score,
            relative_strength_score=relative_strength_score,
        )
        lane_candidates = _lane_candidates(
            upside_3m_score=upside_3m_score,
            emergence_proxy_score=emergence_proxy_score,
            trend_tags=trend_tags,
        )

        risk_tags = _risk_tags(
            subscores=subscores,
            lane=lane,
            status=status,
            momentum_score=momentum_score,
        )
        reason = _reason_text(subscores=subscores, lane=lane, status=status)

        candidate: DealFlowCandidate = {
            "symbol": symbol,
            "asset_class": row.get("asset_class", "Unknown"),
            "sector": row.get("sector", "Unknown"),
            "liquidity_score": liquidity,
            "subscores": subscores,
            "deal_flow_score": float(round(core_score, 4)),
            "core_score": float(round(core_score, 4)),
            "momentum_score": float(round(momentum_score, 4)),
            "asymmetry_score": float(round(asymmetry_score, 4)),
            "active_families": active_families,
            "evidence_count": evidence_count,
            "freshness_hours": float(round(freshness_hours, 4)),
            "status": status,
            "risk_tags": risk_tags,
            "trend_tags": trend_tags,
            "lane": lane,
            "upside_3m_score": upside_3m_score,
            "emergence_proxy_score": emergence_proxy_score,
            "narrative_ignition_score": narrative_ignition_score,
            "fundamentals_acceleration_score": fundamentals_acceleration_score,
            "relative_strength_score": relative_strength_score,
            "lane_candidates": lane_candidates,
            "source": "AUTO",
            "source_detail": "AUTO_MODEL",
            "manual_note": "",
            "manual_priority": 0,
            "reason": reason,
        }
        candidates.append(candidate)

    _rebalance_momentum_lane(
        candidates=candidates,
        momentum_lane_floor_ratio=float(momentum_lane_floor_ratio),
        momentum_lane_promotion_min_score=float(momentum_lane_promotion_min_score),
        momentum_lane_promotion_min_price_score=float(momentum_lane_promotion_min_price_score),
        momentum_lane_social_confirmation_threshold=float(momentum_lane_social_confirmation_threshold),
    )

    return signal_list, candidates


def _assign_lane(
    subscores: Dict[str, float],
    trend_tags: List[str],
    momentum_score: float,
    momentum_lane_threshold: float,
    momentum_lane_price_override_threshold: float,
    momentum_lane_social_confirmation_threshold: float,
) -> str:
    social_momentum = float(subscores.get("social_momentum", 50.0))
    price_momentum = float(subscores.get("price_momentum", 50.0))

    strict_momentum_gate = momentum_score >= momentum_lane_threshold

    price_override_gate = (
        momentum_score >= momentum_lane_threshold + 2.0
        and price_momentum >= momentum_lane_price_override_threshold
        and social_momentum >= momentum_lane_social_confirmation_threshold
    )

    structural_theme_gate = (
        is_structural_growth_theme(trend_tags)
        and momentum_score >= momentum_lane_threshold
        and price_momentum >= max(60.0, momentum_lane_threshold - 2.0)
    )

    if strict_momentum_gate or price_override_gate or structural_theme_gate:
        return "MOMENTUM"
    return "CORE"


def _best_signal_per_symbol_family(
    signals: List[DealFlowSignal],
) -> Dict[str, Dict[str, DealFlowSignal]]:
    grouped: Dict[str, Dict[str, DealFlowSignal]] = defaultdict(dict)
    for sig in signals:
        symbol = sig["symbol"]
        family = sig["signal_family"]
        existing = grouped[symbol].get(family)
        if existing is None:
            grouped[symbol][family] = sig
            continue

        existing_ok = existing.get("source_status") == "OK"
        current_ok = sig.get("source_status") == "OK"
        if current_ok and not existing_ok:
            grouped[symbol][family] = sig
            continue

        if current_ok == existing_ok and float(sig.get("raw_score", 0.0)) > float(existing.get("raw_score", 0.0)):
            grouped[symbol][family] = sig
    return grouped


def _rebalance_momentum_lane(
    candidates: List[DealFlowCandidate],
    momentum_lane_floor_ratio: float,
    momentum_lane_promotion_min_score: float,
    momentum_lane_promotion_min_price_score: float,
    momentum_lane_social_confirmation_threshold: float,
) -> None:
    if momentum_lane_floor_ratio <= 0.0:
        return

    active = [c for c in candidates if c.get("status") == "ACTIVE"]
    if not active:
        return

    target_count = int(round(float(len(active)) * momentum_lane_floor_ratio))
    target_count = max(1, min(len(active), target_count))
    current_count = sum(1 for c in active if c.get("lane") == "MOMENTUM")
    if current_count >= target_count:
        return

    needed = target_count - current_count
    promotable: List[DealFlowCandidate] = []
    for candidate in active:
        if candidate.get("lane") == "MOMENTUM":
            continue
        momentum_score = float(candidate.get("momentum_score", 0.0))
        if momentum_score < momentum_lane_promotion_min_score:
            continue

        subs = dict(candidate.get("subscores", {}))
        price_momentum = float(subs.get("price_momentum", 50.0))
        social_momentum = float(subs.get("social_momentum", 50.0))
        trend_tags = list(candidate.get("trend_tags", []))

        has_confirmation = (
            price_momentum >= momentum_lane_promotion_min_price_score
            or social_momentum >= momentum_lane_social_confirmation_threshold
            or is_structural_growth_theme(trend_tags)
        )
        if not has_confirmation:
            continue
        promotable.append(candidate)

    promotable.sort(
        key=lambda c: (
            -float(c.get("asymmetry_score", 0.0)),
            -float(c.get("momentum_score", 0.0)),
        )
    )

    for candidate in promotable[:needed]:
        candidate["lane"] = "MOMENTUM"
        risk_tags = list(candidate.get("risk_tags", []))
        if "Momentum lane (calibrated)" not in risk_tags:
            risk_tags.append("Momentum lane (calibrated)")
        candidate["risk_tags"] = risk_tags
        reason = str(candidate.get("reason", "")).strip()
        if "calibrated for momentum coverage" not in reason:
            if reason:
                candidate["reason"] = f"{reason} Lane calibrated for momentum coverage."
            else:
                candidate["reason"] = "Lane calibrated for momentum coverage."


def _weighted_core_score(subscores: Dict[str, float]) -> float:
    from tradingagents.scheduler.agents.investment_committee import load_ic_adjustments
    ic_weights = load_ic_adjustments("ic_signal_weights.json").get("adjustments", {})

    # Config-based weight overrides (operator tuning without code changes)
    config_overrides: Dict[str, float] = {}
    try:
        from tradingagents.default_config import DEFAULT_CONFIG
        raw = DEFAULT_CONFIG.get("dealflow_core_score_weight_overrides", {})
        if isinstance(raw, dict):
            config_overrides = raw
    except Exception:
        pass

    effective_weights = dict(CORE_SCORE_WEIGHTS)
    for family, weight in config_overrides.items():
        if family in effective_weights:
            effective_weights[family] = max(0.0, min(40.0, float(weight)))

    # IC adjustments apply on top of config overrides
    for family, delta in ic_weights.items():
        if family in effective_weights:
            effective_weights[family] = max(0.0, min(40.0, effective_weights[family] + delta))

    weighted_sum = 0.0
    total_weight = 0.0
    for family, weight in effective_weights.items():
        score = subscores.get(family)
        if score is None:
            continue
        weighted_sum += weight * float(score)
        total_weight += weight
    if total_weight <= 0.0:
        return 0.0
    return weighted_sum / total_weight


def _apply_sector_override(core_score: float, sector: str) -> float:
    """Apply IC sector override delta to core score."""
    from tradingagents.scheduler.agents.investment_committee import load_ic_adjustments
    overrides = load_ic_adjustments("ic_sector_overrides.json").get("adjustments", {})
    delta = overrides.get(sector, 0.0)
    delta = max(-0.20, min(0.20, delta))
    return core_score * (1.0 + delta)


def _momentum_score(subscores: Dict[str, float]) -> float:
    price_momentum = float(subscores.get("price_momentum", 50.0))
    social_momentum = float(subscores.get("social_momentum", 50.0))
    news_catalyst = float(subscores.get("news_catalyst", 50.0))
    return (
        0.60 * price_momentum
        + 0.30 * social_momentum
        + 0.10 * news_catalyst
    )


def _asymmetry_score(subscores: Dict[str, float], momentum_score: float) -> float:
    macro = float(subscores.get("macro_regime_fit", 50.0))
    smart_money = float(subscores.get("smart_money", 50.0))
    liquidity = float(subscores.get("liquidity_tradability", 50.0))
    return (
        0.70 * momentum_score
        + 0.10 * macro
        + 0.10 * smart_money
        + 0.10 * liquidity
    )


def _phase1_lane_score(raw_value: float) -> float:
    return float(round(max(0.0, min(100.0, raw_value)), 4))


def _narrative_ignition_score(subscores: Dict[str, float]) -> float:
    social_momentum = float(subscores.get("social_momentum", 50.0))
    news_catalyst = float(subscores.get("news_catalyst", 50.0))
    emergence = float(subscores.get("emergence", 50.0))
    return _phase1_lane_score(
        0.45 * social_momentum
        + 0.35 * news_catalyst
        + 0.20 * emergence
    )


def _fundamentals_acceleration_score(subscores: Dict[str, float], trend_tags: List[str]) -> float:
    smart_money = float(subscores.get("smart_money", 50.0))
    news_catalyst = float(subscores.get("news_catalyst", 50.0))
    emergence = float(subscores.get("emergence", 50.0))
    sector_rotation = float(subscores.get("sector_rotation", 50.0))
    structural_bonus = 5.0 if is_structural_growth_theme(trend_tags) else 0.0
    return _phase1_lane_score(
        0.35 * smart_money
        + 0.30 * news_catalyst
        + 0.20 * emergence
        + 0.15 * sector_rotation
        + structural_bonus
    )


def _relative_strength_score(subscores: Dict[str, float]) -> float:
    price_momentum = float(subscores.get("price_momentum", 50.0))
    sector_rotation = float(subscores.get("sector_rotation", 50.0))
    return _phase1_lane_score(0.75 * price_momentum + 0.25 * sector_rotation)


def _upside_3m_score(
    *,
    core_score: float,
    momentum_score: float,
    asymmetry_score: float,
) -> float:
    return _phase1_lane_score(
        0.45 * float(core_score)
        + 0.35 * float(momentum_score)
        + 0.20 * float(asymmetry_score)
    )


def _emergence_proxy_score(
    *,
    narrative_ignition_score: float,
    fundamentals_acceleration_score: float,
    relative_strength_score: float,
) -> float:
    return _phase1_lane_score(
        0.40 * float(narrative_ignition_score)
        + 0.35 * float(fundamentals_acceleration_score)
        + 0.25 * float(relative_strength_score)
    )


def _lane_candidates(
    *,
    upside_3m_score: float,
    emergence_proxy_score: float,
    trend_tags: List[str],
) -> List[str]:
    candidates: List[str] = []
    if float(upside_3m_score) >= 62.0:
        candidates.append("3M_UPSIDE")
    if float(emergence_proxy_score) >= 64.0 or is_structural_growth_theme(trend_tags):
        candidates.append("EMERGENCE")
    if candidates:
        return candidates
    if float(emergence_proxy_score) > float(upside_3m_score):
        return ["EMERGENCE"]
    return ["3M_UPSIDE"]


def _apply_family_z_scores(signals: List[DealFlowSignal]) -> None:
    family_values: Dict[str, List[float]] = defaultdict(list)
    for sig in signals:
        if sig.get("source_status") == "OK":
            family_values[sig["signal_family"]].append(float(sig.get("raw_score", 0.0)))

    family_stats: Dict[str, Tuple[float, float]] = {}
    for family, values in family_values.items():
        if not values:
            family_stats[family] = (0.0, 0.0)
            continue
        family_stats[family] = (mean(values), pstdev(values))

    for sig in signals:
        family = sig["signal_family"]
        mu, sigma = family_stats.get(family, (0.0, 0.0))
        if sig.get("source_status") != "OK" or sigma == 0.0:
            sig["z_score"] = 0.0
            continue
        z = (float(sig.get("raw_score", 0.0)) - mu) / sigma
        sig["z_score"] = float(max(-3.0, min(3.0, z)))


def _risk_tags(
    subscores: Dict[str, float],
    lane: str,
    status: str,
    momentum_score: float,
) -> List[str]:
    tags: List[str] = []
    if status == "LOW_DATA":
        tags.append("Data sparsity")

    if lane == "MOMENTUM":
        tags.append("Momentum lane")
    if momentum_score >= 85.0:
        tags.append("High momentum volatility")
    if float(subscores.get("macro_regime_fit", 50.0)) < 40.0:
        tags.append("Macro headwind")
    if float(subscores.get("news_catalyst", 50.0)) >= 80.0:
        tags.append("Event volatility")

    if not tags:
        tags.append("Standard")
    return tags


def _reason_text(subscores: Dict[str, float], lane: str, status: str) -> str:
    if status == "LOW_DATA":
        return "Insufficient multi-family evidence for production shortlist inclusion."
    ordered = sorted(subscores.items(), key=lambda kv: kv[1], reverse=True)
    top = [name for name, _ in ordered[:3]]
    if not top:
        return "No strong signal family present."
    return f"{lane} drivers: {', '.join(top)}"


def detect_needles(
    signals: List[DealFlowSignal],
    candidates: List[DealFlowCandidate],
    z_threshold: float = 2.5,
    min_raw_score: float = 78.0,
) -> List[Dict]:
    """Find LOW_DATA candidates with at least one extreme signal.

    Returns list of dicts with keys: symbol, trigger_family, z_score,
    raw_score, reason — compatible with the IV force-queue entry format.
    """
    grouped = _best_signal_per_symbol_family(signals)
    low_data_symbols = {
        str(c.get("symbol", "")) for c in candidates if c.get("status") == "LOW_DATA"
    }

    needles: List[Dict] = []
    for symbol in low_data_symbols:
        by_family = grouped.get(symbol, {})
        for family, sig in by_family.items():
            if sig.get("source_status") != "OK":
                continue
            z = float(sig.get("z_score", 0.0))
            raw = float(sig.get("raw_score", 0.0))
            if z >= z_threshold and raw >= min_raw_score:
                needles.append({
                    "symbol": symbol,
                    "trigger_family": family,
                    "z_score": z,
                    "raw_score": raw,
                    "reason": f"Needle: {family} z={z:.1f}",
                })
                break  # one qualifying signal is enough
    return needles
