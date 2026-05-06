"""Build universe from AKG — single source of truth for all pipeline symbols."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .contracts import UniverseRow


# AKG thematic sector ID -> GICS sector label.
_AKG_TO_GICS = {
    "semis_ai_infrastructure": "Technology",
    "biotech_pharma": "Healthcare",
    "defense_aerospace": "Industrials",
    "energy_power": "Energy",
    "materials_critical_minerals": "Materials",
    "fintech_banking": "Financials",
    "macro_rates": "Financials",
    "china_geopolitics": "Industrials",
}

_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,6}$")

_ANCHOR_CACHE_PATH = Path("eval_results/deal_flow/anchor_set_cache.json")

# Module-level tier map from last filtered universe build.
_last_universe_tier_map: Dict[str, str] = {}
_last_universe_ledger: Dict[str, Any] = {}


def get_last_universe_tier_map() -> Dict[str, str]:
    """Return tier map from the most recent build_filtered_universe call."""
    return dict(_last_universe_tier_map)


def get_last_universe_ledger() -> Dict[str, Any]:
    """Return the last universe filter snapshot for ledger instrumentation."""
    return {
        "kept_symbols": list(_last_universe_ledger.get("kept_symbols", [])),
        "candidate_drop_symbols": list(_last_universe_ledger.get("candidate_drop_symbols", [])),
        "haystack_drop_symbols": list(_last_universe_ledger.get("haystack_drop_symbols", [])),
        "rule_snapshot": dict(_last_universe_ledger.get("rule_snapshot", {})),
    }


# ---------------------------------------------------------------------------
# Anchor set: top holdings from SPY/QQQ + DOW_30 static list
# ---------------------------------------------------------------------------

def _load_anchor_cache(ttl_days: int = 7) -> Optional[List[str]]:
    """Read cached anchor set. Returns None if missing or stale."""
    try:
        if not _ANCHOR_CACHE_PATH.exists():
            return None
        data = json.loads(_ANCHOR_CACHE_PATH.read_text())
        cached_at = float(data.get("cached_at", 0))
        if time.time() - cached_at > ttl_days * 86400:
            return None
        symbols = data.get("symbols", [])
        if not symbols:
            return None
        return list(symbols)
    except Exception:
        return None


def _build_anchor_set(ttl_days: int = 7) -> List[str]:
    """Top 50 holdings of SPY + QQQ, unioned with DOW_30. Cached to disk."""
    from tradingagents.dealflow.sources.universe_seeder import DOW_30

    cached = _load_anchor_cache(ttl_days=ttl_days)
    if cached is not None:
        return cached

    anchors: set[str] = set(DOW_30)

    try:
        import yfinance as yf
        for etf in ("SPY", "QQQ"):
            try:
                ticker = yf.Ticker(etf)
                holdings = ticker.funds_data.top_holdings
                if holdings is not None and hasattr(holdings, "index"):
                    for sym in holdings.index:
                        s = str(sym).upper().strip()
                        if s and _SYMBOL_RE.match(s):
                            anchors.add(s)
            except Exception:
                continue
    except Exception:
        pass  # yfinance unavailable — DOW_30 fallback

    result = sorted(anchors)

    # Persist cache
    try:
        _ANCHOR_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _ANCHOR_CACHE_PATH.write_text(json.dumps({
            "cached_at": time.time(),
            "symbols": result,
        }))
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# 4-tier filtered universe
# ---------------------------------------------------------------------------

def build_filtered_universe(
    akg,
    extra_symbols: Optional[Sequence[str]] = None,
    earnings_options_symbols: Optional[Sequence[str]] = None,
    technical_ignition_symbols: Optional[Sequence[str]] = None,
    fvg_recall_symbols: Optional[Sequence[str]] = None,
    fma_recall_symbols: Optional[Sequence[str]] = None,
    config: Optional[dict] = None,
) -> Tuple[List[UniverseRow], Dict[str, str]]:
    """Build a filtered universe using 5-tier gating.

    Tiers:
        T1 ANCHOR   — top ETF holdings + DOW_30
        T2 NEIGHBOR — 1-hop supply chain neighbors of anchors
        T3 SCOUT    — scout-activated (ATMOSPHERE+) OR 2-hop neighbors with centrality
        T4 DARK     — high centrality, no aeternus_score
        T5 RESCAN   — SCORED nodes with fresh scout signals (re-analysis candidates)
        T6 PORTFOLIO — open positions (must never fall out of the universe)

    Returns (rows, tier_map) where tier_map maps symbol -> tier label.
    """
    global _last_universe_tier_map, _last_universe_ledger

    cfg = config or {}
    dark_centrality = float(cfg.get("dealflow_filter_dark_centrality", 0.3))
    two_hop_centrality = float(cfg.get("dealflow_filter_two_hop_centrality", 0.05))
    anchor_ttl = int(cfg.get("dealflow_anchor_cache_ttl_days", 7))
    candidate_min_liquidity_score = float(
        cfg.get("dealflow_universe_candidate_min_liquidity_score", 30.0)
    )

    # Refresh centrality scores on all nodes.
    akg.get_centrality_scores()

    # T1: Anchor set
    anchor_list = _build_anchor_set(ttl_days=anchor_ttl)
    anchor_set = set(anchor_list)

    # T2: 1-hop supply chain neighbors of anchors
    neighbor_set: set[str] = set()
    for sym in anchor_set:
        for nb in akg.get_supply_chain_neighbors(sym, direction="both"):
            nb_ticker = str(nb.get("ticker", "")).upper().strip()
            if nb_ticker:
                neighbor_set.add(nb_ticker)
    neighbor_set -= anchor_set  # remove overlaps

    # T3 source A: 2-hop neighbors from T2, gated by centrality
    two_hop_set: set[str] = set()
    for sym in neighbor_set:
        for nb in akg.get_supply_chain_neighbors(sym, direction="both"):
            nb_ticker = str(nb.get("ticker", "")).upper().strip()
            if not nb_ticker:
                continue
            node = akg._nodes.get(nb_ticker)
            if node and float(node.get("centrality", 0) or 0) >= two_hop_centrality:
                two_hop_set.add(nb_ticker)
    two_hop_set -= anchor_set
    two_hop_set -= neighbor_set

    # T3 source B: scout-activated emerging planets
    emerging_set: set[str] = set()
    for planet in akg.get_emerging_planets(min_tier="ATMOSPHERE", top_k=200):
        pid = str(planet.get("id", "")).upper().strip()
        if pid:
            emerging_set.add(pid)
    # Combine into T3
    scout_set = (two_hop_set | emerging_set) - anchor_set - neighbor_set

    # T4: Dark matter — high centrality, no score
    dark_set: set[str] = set()
    for node in akg.get_dark_nodes(min_centrality=dark_centrality):
        did = str(node.get("id", "")).upper().strip()
        if did:
            dark_set.add(did)
    dark_set -= anchor_set
    dark_set -= neighbor_set
    dark_set -= scout_set

    # T5: Rescan — previously-analyzed tickers with fresh scout signals
    rescan_set: set[str] = set()
    for node in akg.get_rescan_candidates(max_age_days=7):
        rid = str(node.get("id", "")).upper().strip()
        if rid:
            rescan_set.add(rid)
    rescan_set -= anchor_set | neighbor_set | scout_set

    # T6: Portfolio — open positions must never fall out of the universe
    portfolio_set: set[str] = set()
    for node in akg.get_open_positions():
        pid = str(node.get("id", "")).upper().strip()
        if pid:
            portfolio_set.add(pid)
    portfolio_set -= anchor_set | neighbor_set | scout_set | dark_set | rescan_set

    # Build tier_map — highest tier wins
    tier_map: Dict[str, str] = {}
    for sym in anchor_set:
        tier_map[sym] = "T1_ANCHOR"
    for sym in neighbor_set:
        tier_map[sym] = "T2_NEIGHBOR"
    for sym in scout_set:
        tier_map[sym] = "T3_SCOUT"
    for sym in dark_set:
        tier_map[sym] = "T4_DARK"
    for sym in rescan_set:
        tier_map[sym] = "T5_RESCAN"
    for sym in portfolio_set:
        tier_map[sym] = "T6_PORTFOLIO"

    fvg_recall_set: set[str] = set()
    if fvg_recall_symbols:
        for raw in fvg_recall_symbols:
            sym = _normalize_symbol(raw)
            if sym and _SYMBOL_RE.match(sym) and sym not in tier_map:
                tier_map[sym] = "T3B_FVG_RECALL"
                fvg_recall_set.add(sym)

    fma_recall_set: set[str] = set()
    if fma_recall_symbols:
        for raw in fma_recall_symbols:
            sym = _normalize_symbol(raw)
            if not sym or not _SYMBOL_RE.match(sym):
                continue
            fma_recall_set.add(sym)
            if sym not in tier_map:
                tier_map[sym] = "T3C_FMA_RECALL"

    technical_ignition_set: set[str] = set()
    if technical_ignition_symbols:
        for raw in technical_ignition_symbols:
            sym = _normalize_symbol(raw)
            if not sym or not _SYMBOL_RE.match(sym):
                continue
            technical_ignition_set.add(sym)
            if sym not in tier_map:
                tier_map[sym] = "T3D_TECHNICAL_IGNITION"

    earnings_options_set: set[str] = set()
    if earnings_options_symbols:
        for raw in earnings_options_symbols:
            sym = _normalize_symbol(raw)
            if not sym or not _SYMBOL_RE.match(sym):
                continue
            earnings_options_set.add(sym)
            if sym not in tier_map:
                tier_map[sym] = "T3E_EARNINGS_OPTIONS"

    # Extra symbols (manual watchlist) always included
    extra_norm: set[str] = set()
    if extra_symbols:
        for raw in extra_symbols:
            sym = _normalize_symbol(raw)
            if sym and _SYMBOL_RE.match(sym) and sym not in tier_map:
                tier_map[sym] = "MANUAL"
                extra_norm.add(sym)

    # Build rows from qualifying AKG nodes
    rows: List[UniverseRow] = []
    seen: set[str] = set()

    for node in akg._nodes.values():
        if node.get("node_type") != "company":
            continue
        symbol = str(node.get("id", "")).upper().strip()
        if not symbol or symbol in seen:
            continue
        if symbol not in tier_map:
            continue
        seen.add(symbol)

        asset_class = node.get("asset_class") or "Equity"
        sector_gics = (
            node.get("sector_gics")
            or _akg_sector_to_gics(node.get("sector"))
            or "Unclassified Equity"
        )
        liquidity = node.get("liquidity_score")
        if liquidity is None:
            liquidity = 50.0

        rows.append({
            "symbol": symbol,
            "asset_class": asset_class,
            "sector": sector_gics,
            "liquidity_score": float(liquidity),
            "aliases": list(node.get("aliases") or []),
        })

    # Append extra symbols not in AKG
    if extra_symbols:
        for raw in extra_symbols:
            symbol = _normalize_symbol(raw)
            if not symbol or symbol in seen:
                continue
            if not _SYMBOL_RE.match(symbol):
                continue
            seen.add(symbol)
            rows.append({
                "symbol": symbol,
                "asset_class": "Equity",
                "sector": "Unclassified Equity",
                "liquidity_score": 30.0,
                "aliases": [],
            })

    if technical_ignition_symbols:
        for raw in technical_ignition_symbols:
            symbol = _normalize_symbol(raw)
            if not symbol or symbol in seen:
                continue
            if not _SYMBOL_RE.match(symbol):
                continue
            seen.add(symbol)
            rows.append({
                "symbol": symbol,
                "asset_class": "Equity",
                "sector": "Unclassified Equity",
                "liquidity_score": 30.0,
                "aliases": [],
            })

    if earnings_options_symbols:
        for raw in earnings_options_symbols:
            symbol = _normalize_symbol(raw)
            if not symbol or symbol in seen:
                continue
            if not _SYMBOL_RE.match(symbol):
                continue
            seen.add(symbol)
            rows.append({
                "symbol": symbol,
                "asset_class": "Equity",
                "sector": "Unclassified Equity",
                "liquidity_score": 30.0,
                "aliases": [],
            })

    _last_universe_tier_map = dict(tier_map)
    kept_symbols = _normalize_symbols([row.get("symbol") for row in rows])
    all_company_symbols: List[str] = []
    candidate_drop_symbols: List[str] = []
    kept_set = set(kept_symbols)
    for node in akg._nodes.values():
        if node.get("node_type") != "company":
            continue
        symbol = _normalize_symbol(node.get("id", ""))
        if not symbol or not _SYMBOL_RE.match(symbol):
            continue
        all_company_symbols.append(symbol)
        if symbol in kept_set:
            continue
        asset_class = str(node.get("asset_class") or "Equity")
        liquidity = node.get("liquidity_score")
        liquidity_score = float(liquidity) if liquidity is not None else 50.0
        if asset_class == "Equity" and liquidity_score >= candidate_min_liquidity_score:
            candidate_drop_symbols.append(symbol)

    haystack_drop_symbols = [
        symbol for symbol in _normalize_symbols(all_company_symbols) if symbol not in kept_set
    ]
    tier_counts = dict(Counter(tier_map.values()))
    _last_universe_ledger = {
        "kept_symbols": kept_symbols,
        "candidate_drop_symbols": _normalize_symbols(candidate_drop_symbols),
        "haystack_drop_symbols": haystack_drop_symbols,
        "rule_snapshot": {
            "filter_enabled": True,
            "candidate_min_liquidity_score": candidate_min_liquidity_score,
            "tier_counts": tier_counts,
            "kept_count": len(kept_symbols),
            "candidate_drop_count": len(candidate_drop_symbols),
            "haystack_drop_count": len(haystack_drop_symbols),
            "manual_count": int(tier_counts.get("MANUAL", 0)),
            "fvg_recall_selected_count": int(len(fvg_recall_set)),
            "fma_recall_selected_count": int(len(fma_recall_set)),
            "technical_ignition_selected_count": int(len(technical_ignition_set)),
            "earnings_options_selected_count": int(len(earnings_options_set)),
            "fma_recall_overlap_with_fvg_count": int(len(fma_recall_set & fvg_recall_set)),
            "total_company_count": len(_normalize_symbols(all_company_symbols)),
        },
    }
    return rows, tier_map


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _akg_sector_to_gics(akg_sector: Optional[str]) -> str:
    """Convert an AKG internal sector id to a GICS sector label."""
    if not akg_sector:
        return ""
    return _AKG_TO_GICS.get(str(akg_sector).strip(), "")


def build_universe_from_akg(
    extra_symbols: Optional[Sequence[str]] = None,
    earnings_options_symbols: Optional[Sequence[str]] = None,
    technical_ignition_symbols: Optional[Sequence[str]] = None,
    fvg_recall_symbols: Optional[Sequence[str]] = None,
    fma_recall_symbols: Optional[Sequence[str]] = None,
    min_extra_adv_usd: float = 5_000_000.0,
    config: Optional[dict] = None,
) -> List[UniverseRow]:
    """Build List[UniverseRow] from AKG company nodes.

    If ``dealflow_universe_filter_enabled`` is True (default), uses the 4-tier
    centrality-gated filter to reduce universe from ~5,000 to ~300-450 symbols.
    If False, returns all company nodes (legacy behavior).

    ``extra_symbols`` not already in the AKG get a default row
    (asset_class="Equity", sector="Unclassified Equity", liquidity=30.0).
    """
    from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph

    cfg = config or {}
    filter_enabled = bool(cfg.get("dealflow_universe_filter_enabled", True))

    akg = AeternusKnowledgeGraph.load()

    global _last_universe_ledger

    if filter_enabled:
        rows, _tier_map = build_filtered_universe(
            akg=akg,
            extra_symbols=extra_symbols,
            earnings_options_symbols=earnings_options_symbols,
            technical_ignition_symbols=technical_ignition_symbols,
            fvg_recall_symbols=fvg_recall_symbols,
            fma_recall_symbols=fma_recall_symbols,
            config=cfg,
        )
        return rows

    # Legacy: all company nodes
    rows: List[UniverseRow] = []
    seen: set[str] = set()

    for node in akg._nodes.values():
        if node.get("node_type") != "company":
            continue
        symbol = str(node.get("id", "")).upper().strip()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)

        asset_class = node.get("asset_class") or "Equity"
        sector_gics = node.get("sector_gics") or _akg_sector_to_gics(node.get("sector")) or "Unclassified Equity"
        liquidity = node.get("liquidity_score")
        if liquidity is None:
            liquidity = 50.0
        aliases = node.get("aliases") or []

        rows.append(
            {
                "symbol": symbol,
                "asset_class": asset_class,
                "sector": sector_gics,
                "liquidity_score": float(liquidity),
                "aliases": list(aliases),
            }
        )

    # Extra symbols not yet in AKG (cashtag-discovered, manual watchlist).
    if extra_symbols:
        for raw in extra_symbols:
            symbol = _normalize_symbol(raw)
            if not symbol or symbol in seen:
                continue
            if not _SYMBOL_RE.match(symbol):
                continue
            seen.add(symbol)
            rows.append(
                {
                    "symbol": symbol,
                    "asset_class": "Equity",
                    "sector": "Unclassified Equity",
                    "liquidity_score": 30.0,
                    "aliases": [],
                }
            )

    if technical_ignition_symbols:
        for raw in technical_ignition_symbols:
            symbol = _normalize_symbol(raw)
            if not symbol or symbol in seen:
                continue
            if not _SYMBOL_RE.match(symbol):
                continue
            seen.add(symbol)
            rows.append(
                {
                    "symbol": symbol,
                    "asset_class": "Equity",
                    "sector": "Unclassified Equity",
                    "liquidity_score": 30.0,
                    "aliases": [],
                }
            )

    if earnings_options_symbols:
        for raw in earnings_options_symbols:
            symbol = _normalize_symbol(raw)
            if not symbol or symbol in seen:
                continue
            if not _SYMBOL_RE.match(symbol):
                continue
            seen.add(symbol)
            rows.append(
                {
                    "symbol": symbol,
                    "asset_class": "Equity",
                    "sector": "Unclassified Equity",
                    "liquidity_score": 30.0,
                    "aliases": [],
                }
            )

    kept_symbols = _normalize_symbols([row.get("symbol") for row in rows])
    _last_universe_ledger = {
        "kept_symbols": kept_symbols,
        "candidate_drop_symbols": [],
        "haystack_drop_symbols": [],
        "rule_snapshot": {
            "filter_enabled": False,
            "kept_count": len(kept_symbols),
            "candidate_drop_count": 0,
            "haystack_drop_count": 0,
            "total_company_count": len(kept_symbols),
        },
    }
    return rows


def _normalize_symbol(raw: object) -> str:
    symbol = str(raw or "").upper().strip()
    if symbol.startswith("$"):
        symbol = symbol[1:]
    symbol = symbol.replace("/", "-").replace("_", "-")
    if "." in symbol:
        symbol = symbol.replace(".", "-")
    return symbol


def _normalize_symbols(symbols: Sequence[object]) -> List[str]:
    normalized: List[str] = []
    seen: set[str] = set()
    for raw in symbols:
        symbol = _normalize_symbol(raw)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(symbol)
    return normalized
