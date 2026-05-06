from __future__ import annotations

import os
from pathlib import Path


AETERNUS_HOLDINGS_ROOT = Path(
    os.environ.get(
        "AETERNUS_HOLDINGS_ROOT",
        str(Path.home() / "Documents" / "GitHub" / "AeternusHoldings"),
    )
)

SEC_CACHE_ROOT = Path(
    os.environ.get(
        "AETERNUS_SEC_CACHE_ROOT",
        str(AETERNUS_HOLDINGS_ROOT / "cache" / "sec"),
    )
)

LOCAL_MARKET_CACHE_ROOT = Path(
    os.environ.get(
        "AETERNUS_MARKET_CACHE_ROOT",
        str(Path.home() / ".cache" / "autoresearch_fundamentals"),
    )
)


def sec_cache_root(*parts: str) -> Path:
    return SEC_CACHE_ROOT.joinpath(*parts)


def market_cache_root(*parts: str) -> Path:
    return LOCAL_MARKET_CACHE_ROOT.joinpath(*parts)
