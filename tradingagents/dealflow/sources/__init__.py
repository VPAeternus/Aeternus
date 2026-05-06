"""Deal Flow source adapters."""

from .breakout_scanner import scan_breakout_discovery
from .price_momentum import collect_price_momentum_signals
from .sector_rotation import collect_sector_rotation_signals
from .smart_money import collect_smart_money_signals
from .social_news import collect_social_news_signals
from .insider_cluster import collect_insider_cluster_signals, scan_insider_sweep
from .technical_ignition_scout import scan_technical_ignition_setups
from .thirteenf_watchlist_scout import scan_thirteenf_watchlist

__all__ = [
    "scan_breakout_discovery",
    "scan_technical_ignition_setups",
    "scan_thirteenf_watchlist",
    "collect_price_momentum_signals",
    "collect_sector_rotation_signals",
    "collect_smart_money_signals",
    "collect_social_news_signals",
    "collect_insider_cluster_signals",
    "scan_insider_sweep",
]
