"""Theme tags, clustering, and research playbook selectors for Deal Flow."""

from __future__ import annotations

from typing import Dict, List, Literal


AI_INFRA_SYMBOLS = {
    "NVDA",
    "AMD",
    "AVGO",
    "MU",
    "TSM",
    "ASML",
    "ANET",
    "SMCI",
    "ARM",
    "MSFT",
    "AMZN",
    "GOOGL",
    "META",
    "PLTR",
    "OKLO",
    "SMH",
}

DEFENSE_TECH_SYMBOLS = {
    "LMT",
    "NOC",
    "RTX",
    "BA",
    "HII",
    "LDOS",
    "KTOS",
    "AVAV",
    "PLTR",
    "ITA",
    "XAR",
}

ENERGY_TRANSITION_SYMBOLS = {
    "TSLA",
    "FSLR",
    "ENPH",
    "SEDG",
    "NEE",
    "ICLN",
    "TAN",
    "LIT",
    "URNM",
    "CCJ",
}

CRYPTO_BETA_SYMBOLS = {
    "COIN",
    "MSTR",
    "HOOD",
    "RIOT",
    "MARA",
    "BITO",
    "IBIT",
    "FBTC",
    "ARKB",
    "ETHA",
}


ResearchPlaybook = Literal[
    "MOMENTUM_BREAKOUT",
    "HYBRID_COMPOUNDER",
]


def infer_trend_tags(
    subscores: Dict[str, float],
    symbol: str = "",
    sector: str = "",
    asset_class: str = "",
) -> List[str]:
    tags: List[str] = []

    if float(subscores.get("price_momentum", 0.0)) >= 75.0:
        tags.append("price-breakout")
    if float(subscores.get("social_momentum", 0.0)) >= 70.0:
        tags.append("social-acceleration")
    if float(subscores.get("news_catalyst", 0.0)) >= 70.0:
        tags.append("catalyst-heavy")
    if float(subscores.get("smart_money", 0.0)) >= 65.0:
        tags.append("smart-money-confirmation")
    if float(subscores.get("macro_regime_fit", 0.0)) >= 65.0:
        tags.append("macro-tailwind")
    for theme_tag in infer_theme_clusters(
        symbol=symbol,
        sector=sector,
        asset_class=asset_class,
        subscores=subscores,
    ):
        if theme_tag not in tags:
            tags.append(theme_tag)

    if not tags:
        tags.append("balanced")

    return tags


def infer_theme_clusters(
    symbol: str,
    sector: str,
    asset_class: str,
    subscores: Dict[str, float],
) -> List[str]:
    tags: List[str] = []
    sym = str(symbol or "").upper().strip()
    sector_text = str(sector or "").lower()
    asset = str(asset_class or "").upper()
    price_momentum = float(subscores.get("price_momentum", 50.0))
    news_catalyst = float(subscores.get("news_catalyst", 50.0))
    social_momentum = float(subscores.get("social_momentum", 50.0))

    ai_sector_hit = any(
        token in sector_text
        for token in ("technology", "semiconductor", "software", "communications")
    )
    if (
        sym in AI_INFRA_SYMBOLS
        or (
            ai_sector_hit
            and (price_momentum >= 65.0 or social_momentum >= 65.0)
        )
    ):
        tags.append("theme-ai-infrastructure")

    defense_sector_hit = any(token in sector_text for token in ("aerospace", "defense", "industrial"))
    if sym in DEFENSE_TECH_SYMBOLS or (defense_sector_hit and news_catalyst >= 55.0):
        tags.append("theme-defense-tech")

    energy_sector_hit = any(token in sector_text for token in ("energy", "utilities", "materials"))
    if sym in ENERGY_TRANSITION_SYMBOLS or (energy_sector_hit and news_catalyst >= 55.0):
        tags.append("theme-energy-transition")

    crypto_sector_hit = any(token in sector_text for token in ("financial", "crypto", "digital asset"))
    if (
        sym in CRYPTO_BETA_SYMBOLS
        or (asset == "ETF" and sym in {"BITO", "IBIT", "FBTC", "ARKB", "ETHA"})
        or (crypto_sector_hit and social_momentum >= 70.0)
    ):
        tags.append("theme-crypto-beta")

    if any(tag in tags for tag in ("theme-ai-infrastructure", "theme-defense-tech", "theme-energy-transition", "theme-crypto-beta")):
        tags.append("theme-structural-growth")

    return tags


def is_structural_growth_theme(tags: List[str]) -> bool:
    tag_set = set(tags or [])
    return "theme-structural-growth" in tag_set


def select_research_playbook(
    lane: str,
    momentum_score: float,
) -> ResearchPlaybook:
    if lane == "MOMENTUM" and momentum_score >= 70.0:
        return "MOMENTUM_BREAKOUT"
    return "HYBRID_COMPOUNDER"


def why_now_text(
    lane: str,
    momentum_score: float,
    asymmetry_score: float,
    trend_tags: List[str],
) -> str:
    if lane == "MOMENTUM":
        return (
            f"Momentum lane triggered (score {momentum_score:.1f}) with asymmetric upside "
            f"(asymmetry {asymmetry_score:.1f}) and trend tags: {', '.join(trend_tags[:3])}."
        )

    return (
        f"Core lane selected with balanced profile; "
        f"momentum {momentum_score:.1f}, trend tags: {', '.join(trend_tags[:3])}."
    )
