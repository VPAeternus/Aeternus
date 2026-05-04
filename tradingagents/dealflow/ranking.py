"""Lane-aware ranking and diversification constraints for Deal Flow shortlist."""

from __future__ import annotations

from collections import Counter
from typing import List, Set

from .contracts import DealFlowCandidate


def rank_candidates(
    candidates: List[DealFlowCandidate],
    top_k: int,
    max_sector_count: int = 5,
    min_macro_hedge_candidates: int = 2,
    core_quota: int = 18,
    momentum_quota: int = 12,
) -> List[DealFlowCandidate]:
    eligible = [c for c in candidates if c.get("status") == "ACTIVE"]

    # Rank CORE pool by momentum_score (Rank IC = +0.49) not core_score (IC = -0.52).
    # Two hindsight cycles showed core_score is negatively correlated with 5-day returns.
    core_pool = sorted(
        [c for c in eligible if c.get("lane") == "CORE"],
        key=lambda c: (-float(c.get("momentum_score", 0.0)), float(c.get("freshness_hours", 9999.0))),
    )
    momentum_pool = sorted(
        [c for c in eligible if c.get("lane") == "MOMENTUM"],
        key=lambda c: (-float(c.get("asymmetry_score", 0.0)), float(c.get("freshness_hours", 9999.0))),
    )

    sector_counts: Counter = Counter()
    selected: List[DealFlowCandidate] = []
    selected_symbols: Set[str] = set()

    _select_from_pool(
        selected=selected,
        selected_symbols=selected_symbols,
        sector_counts=sector_counts,
        pool=core_pool,
        target_count=min(core_quota, top_k),
        max_sector_count=max_sector_count,
    )
    _select_from_pool(
        selected=selected,
        selected_symbols=selected_symbols,
        sector_counts=sector_counts,
        pool=momentum_pool,
        target_count=min(momentum_quota, max(0, top_k - len(selected))),
        max_sector_count=max_sector_count,
    )

    # Refill shortfall from same lane first, then the other lane.
    if len(selected) < top_k:
        _select_from_pool(
            selected=selected,
            selected_symbols=selected_symbols,
            sector_counts=sector_counts,
            pool=core_pool,
            target_count=top_k - len(selected),
            max_sector_count=max_sector_count,
        )
    if len(selected) < top_k:
        _select_from_pool(
            selected=selected,
            selected_symbols=selected_symbols,
            sector_counts=sector_counts,
            pool=momentum_pool,
            target_count=top_k - len(selected),
            max_sector_count=max_sector_count,
        )

    # Final fallback: any eligible symbol by lane-specific ranking score.
    if len(selected) < top_k:
        fallback = sorted(
            eligible,
            key=lambda c: (-_lane_rank_score(c), float(c.get("freshness_hours", 9999.0))),
        )
        _select_from_pool(
            selected=selected,
            selected_symbols=selected_symbols,
            sector_counts=sector_counts,
            pool=fallback,
            target_count=top_k - len(selected),
            max_sector_count=max_sector_count,
        )

    selected = _enforce_macro_hedge_minimum(
        selected=selected,
        eligible=eligible,
        minimum=min_macro_hedge_candidates,
        top_k=top_k,
    )
    selected = selected[:top_k]

    ranked: List[DealFlowCandidate] = []
    for idx, candidate in enumerate(selected, start=1):
        clone = dict(candidate)
        clone["rank"] = idx
        ranked.append(clone)
    return ranked


def _select_from_pool(
    selected: List[DealFlowCandidate],
    selected_symbols: Set[str],
    sector_counts: Counter,
    pool: List[DealFlowCandidate],
    target_count: int,
    max_sector_count: int,
) -> None:
    if target_count <= 0:
        return
    added = 0
    for candidate in pool:
        if added >= target_count:
            break
        symbol = str(candidate.get("symbol", ""))
        sector = candidate.get("sector", "Unknown")
        if not symbol or symbol in selected_symbols:
            continue
        if sector_counts[sector] >= max_sector_count:
            continue
        selected.append(candidate)
        selected_symbols.add(symbol)
        sector_counts[sector] += 1
        added += 1


def _lane_rank_score(candidate: DealFlowCandidate) -> float:
    """Lane-aware ranking score. CORE uses momentum_score (IC=+0.49), not core_score (IC=-0.52)."""
    lane = candidate.get("lane")
    if lane == "MOMENTUM":
        return float(candidate.get("asymmetry_score", 0.0))
    return float(candidate.get("momentum_score", 0.0))


def _enforce_macro_hedge_minimum(
    selected: List[DealFlowCandidate],
    eligible: List[DealFlowCandidate],
    minimum: int,
    top_k: int,
) -> List[DealFlowCandidate]:
    hedge_like = [c for c in selected if _is_macro_hedge_candidate(c)]
    if len(hedge_like) >= minimum:
        return selected

    additions = [c for c in eligible if _is_macro_hedge_candidate(c) and c not in selected]
    additions.sort(key=lambda c: -_lane_rank_score(c))

    while len(hedge_like) < minimum and additions:
        add = additions.pop(0)
        removal_index = _lowest_non_hedge_index(selected)
        if removal_index is not None and len(selected) >= top_k:
            selected.pop(removal_index)
        selected.append(add)
        selected.sort(key=lambda c: -_lane_rank_score(c))
        hedge_like = [c for c in selected if _is_macro_hedge_candidate(c)]

    return selected


def _is_macro_hedge_candidate(candidate: DealFlowCandidate) -> bool:
    asset_class = candidate.get("asset_class", "")
    sector = candidate.get("sector", "")
    return asset_class in {"ETF", "CommodityProxy"} or sector in {"Rates", "Metals", "Energy", "Commodities"}


def _lowest_non_hedge_index(candidates: List[DealFlowCandidate]):
    non_hedge_indices = [i for i, c in enumerate(candidates) if not _is_macro_hedge_candidate(c)]
    if not non_hedge_indices:
        return None
    return min(non_hedge_indices, key=lambda i: _lane_rank_score(candidates[i]))
