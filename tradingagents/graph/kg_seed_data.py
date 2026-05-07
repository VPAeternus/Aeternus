"""Seed constants for Aeternus Knowledge Graph."""

from __future__ import annotations

from typing import Dict, List, Optional

SUPPLY_CHAIN_MAP: Dict[str, List[str]] = {
    # NVDA ecosystem
    "NVDA": ["TSM", "AMKR", "AVGO", "MRVL", "COHR", "LITE", "GLW", "ENTG", "LRCX", "AMAT"],
    # TSM customers / upstream suppliers
    "TSM": ["AXTI", "ENTG", "AMAT", "ASML", "LRCX", "KLAC", "ONTO", "CAMT"],
    # Hyperscalers → AI infra
    "MSFT": ["NVDA", "CRWV", "NBIS", "AMZN"],
    "GOOGL": ["NVDA", "TSM", "AMKR"],
    "AMZN": ["NVDA", "TSM"],
    "META": ["NVDA", "TSM"],
    # Advanced packaging
    "AMKR": ["TSM", "APH"],
    "SMTOY": ["TSM", "ASML", "LRCX"],
    # InP substrate / photonics chain
    "AXTI": ["LITE", "COHR"],
    "LITE": ["COHR", "NVDA"],
    "COHR": ["NVDA", "MSFT"],
    "GLW": ["LITE", "COHR"],
    # Semis supply
    "AVGO": ["TSM", "AMKR"],
    "MRVL": ["TSM", "AMKR"],
    "ALAB": ["TSM"],
    "CRDO": ["TSM"],
    # Memory
    "MU": ["AMAT", "LRCX", "KLAC", "ENTG", "SNDK"],
    "SNDK": ["TSM", "KIOXIA"],
    # AI power / neoclouds
    "CRWV": ["NVDA"],
    "NBIS": ["NVDA"],
    "IREN": ["NVDA"],
    "CIFR": ["NVDA"],
    "WULF": ["NVDA"],
    "TSSI": ["NVDA"],
    # EDA / process tools
    "KLAC": ["ENTG", "AMAT"],
    "ONTO": ["ENTG"],
    "CAMT": ["ENTG"],
    "LRCX": ["ENTG", "APH"],
    "AMAT": ["ENTG", "APH"],
    "ASML": ["ENTG", "APH", "AXTI"],
    "ENTG": ["APH"],
    # Connectors / hardware
    "APH": [],
    # Substrate / compound semis
    "INTC": ["TSM", "ASML", "LRCX", "AMAT", "ENTG"],
    "ON": ["TSM"],
    "TER": ["TSM", "AMAT"],
}

SEED_SECTORS = [
    "semis_ai_infrastructure",
    "biotech_pharma",
    "macro_rates",
    "defense_aerospace",
    "energy_power",
    "materials_critical_minerals",
    "china_geopolitics",
    "fintech_banking",
]

SEED_THEMES = [
    "HBM",
    "InP_substrates",
    "silicon_photonics",
    "advanced_packaging",
    "AI_CapEx",
    "neocloud",
    "rare_earth",
    "glass_substrate",
    "nuclear_SMR",
    "grid_interconnection",
    "PDUFA_catalyst",
    "Fed_pivot",
    "yield_curve_inversion",
    "chip_export_ban",
    "supply_chain_decoupling",
    "insider_cluster",
    "LNG_export",
    "critical_minerals",
    "stablecoin_legislation",
    "DoD_contract",
]

SEED_COMPANIES = [
    # Semis/AI infra
    ("NVDA", "semis_ai_infrastructure", "NVIDIA Corp"),
    ("TSM", "semis_ai_infrastructure", "Taiwan Semiconductor Mfg"),
    ("AXTI", "semis_ai_infrastructure", "AXT Inc"),
    ("LITE", "semis_ai_infrastructure", "Lumentum Holdings"),
    ("COHR", "semis_ai_infrastructure", "Coherent Corp"),
    ("MRVL", "semis_ai_infrastructure", "Marvell Technology"),
    ("AMKR", "semis_ai_infrastructure", "Amkor Technology"),
    ("SMCI", "semis_ai_infrastructure", "Super Micro Computer"),
    ("AVGO", "semis_ai_infrastructure", "Broadcom Inc"),
    ("AMAT", "semis_ai_infrastructure", "Applied Materials"),
    ("ASML", "semis_ai_infrastructure", "ASML Holding"),
    ("LRCX", "semis_ai_infrastructure", "Lam Research"),
    ("KLAC", "semis_ai_infrastructure", "KLA Corp"),
    ("ENTG", "semis_ai_infrastructure", "Entegris Inc"),
    # Hyperscalers
    ("MSFT", "semis_ai_infrastructure", "Microsoft Corp"),
    ("GOOGL", "semis_ai_infrastructure", "Alphabet Inc"),
    ("AMZN", "semis_ai_infrastructure", "Amazon.com Inc"),
    ("META", "semis_ai_infrastructure", "Meta Platforms"),
    # Neoclouds
    ("CRWV", "semis_ai_infrastructure", "CoreWeave Inc"),
    ("NBIS", "semis_ai_infrastructure", "Nebius Group"),
    # Energy/power infra
    ("VRT", "energy_power", "Vertiv Holdings"),
    ("EQIX", "energy_power", "Equinix Inc"),
    ("DLR", "energy_power", "Digital Realty Trust"),
    # Biotech
    ("MRNA", "biotech_pharma", "Moderna Inc"),
    ("BNTX", "biotech_pharma", "BioNTech SE"),
    # Defense
    ("LMT", "defense_aerospace", "Lockheed Martin"),
    ("RTX", "defense_aerospace", "RTX Corp"),
    ("NOC", "defense_aerospace", "Northrop Grumman"),
    ("KTOS", "defense_aerospace", "Kratos Defense"),
    ("AVAV", "defense_aerospace", "AeroVironment Inc"),
    # Critical minerals
    ("MP", "materials_critical_minerals", "MP Materials"),
    ("ALB", "materials_critical_minerals", "Albemarle Corp"),
    ("LTHM", "materials_critical_minerals", "Livent Corp"),
    # EV
    ("TSLA", "semis_ai_infrastructure", "Tesla Inc"),
    # Nuclear
    ("BWXT", "energy_power", "BWX Technologies"),
    ("OKLO", "energy_power", "Oklo Inc"),
    # Fintech
    ("SQ", "fintech_banking", "Block Inc"),
    ("PYPL", "fintech_banking", "PayPal Holdings"),
    # Semis — legacy / tools
    ("INTC", "semis_ai_infrastructure", "Intel Corp"),
    ("QCOM", "semis_ai_infrastructure", "Qualcomm Inc"),
    ("MU", "semis_ai_infrastructure", "Micron Technology"),
    ("AAPL", "semis_ai_infrastructure", "Apple Inc"),
    ("GLW", "semis_ai_infrastructure", "Corning Inc"),
    # Additional supply chain nodes
    ("ALAB", "semis_ai_infrastructure", "Astera Labs Inc"),
    ("CRDO", "semis_ai_infrastructure", "Credo Technology"),
    ("SMTOY", "semis_ai_infrastructure", "Sumitomo Electric (ADR)"),
    ("APH", "semis_ai_infrastructure", "Amphenol Corp"),
    ("SNDK", "semis_ai_infrastructure", "SanDisk Corp"),
    ("ON", "semis_ai_infrastructure", "ON Semiconductor"),
    ("TER", "semis_ai_infrastructure", "Teradyne Inc"),
    ("ONTO", "semis_ai_infrastructure", "Onto Innovation"),
    ("CAMT", "semis_ai_infrastructure", "Camtek Ltd"),
    ("IREN", "energy_power", "Iris Energy"),
    ("CIFR", "energy_power", "Cipher Mining"),
    ("WULF", "energy_power", "TeraWulf Inc"),
    ("TSSI", "semis_ai_infrastructure", "TSS Inc"),
]

_DEFAULT_KG_PATH = "eval_results/control/knowledge_graph.json"

_YFINANCE_SECTOR_MAP = {
    "Technology": "semis_ai_infrastructure",
    "Healthcare": "biotech_pharma",
    "Industrials": "defense_aerospace",
    "Energy": "energy_power",
    "Basic Materials": "materials_critical_minerals",
    "Financial Services": "fintech_banking",
    "Consumer Cyclical": None,
    "Consumer Defensive": None,
    "Real Estate": None,
    "Communication Services": "semis_ai_infrastructure",  # GOOGL, META
    "Utilities": "energy_power",
}

EMERGENCE_SIGNALS = [
    # --- Original 4 signals ---
    ("cashtag_velocity_z",           0.0,   5.0,   8, False),
    ("cashtag_sentiment",           -1.0,   1.0,   5, False),
    ("breakout_score",              50.0, 100.0,  10, False),
    ("iv_divergence",                0.0,   1.0,   7, True),
    # --- S-078 signals (all 0-100 scale) ---
    ("signal_momentum_score",        0.0, 100.0,  15, False),
    ("signal_smart_money_score",     0.0, 100.0,  10, False),
    ("signal_insider_score",         0.0, 100.0,   8, False),
    ("signal_insider_sell_score",    0.0, 100.0,   4, False),
    ("signal_sec_catalyst_score",    0.0, 100.0,   7, False),
    ("signal_news_catalyst_score",   0.0, 100.0,   7, False),
    ("signal_social_score",          0.0, 100.0,   6, False),
    ("signal_sector_rotation_score", 0.0, 100.0,   5, False),
    ("signal_macro_score",           0.0, 100.0,   5, False),
    ("signal_value_score",           0.0, 100.0,   2, False),
    ("signal_theme_acceleration_score", 0.0, 15.0, 8, False),
]

