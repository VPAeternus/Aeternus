"""Fama-French 3-factor data fetcher with local caching.

Downloads daily Fama-French 3-factor returns from Kenneth French Data Library,
caches locally, and returns recent factor averages for alpha decomposition.
"""

import csv
import io
import logging
import os
import re
import time
import urllib.request
import zipfile
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_FF_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_daily_CSV.zip"

# Cache location: same directory as other data caches
_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "dataflows", "data_cache")
_CACHE_FILE = os.path.join(_CACHE_DIR, "ff_factors_daily.csv")
_CACHE_MAX_AGE_SECONDS = 7 * 24 * 3600  # 7 days


def _cache_is_fresh() -> bool:
    """Check if the cached CSV exists and is younger than _CACHE_MAX_AGE_SECONDS."""
    try:
        if not os.path.exists(_CACHE_FILE):
            return False
        age = time.time() - os.path.getmtime(_CACHE_FILE)
        return age < _CACHE_MAX_AGE_SECONDS
    except Exception:
        return False


def _download_and_cache() -> Optional[str]:
    """Download the FF daily factors ZIP, extract CSV, save to cache.

    Returns the CSV content as a string, or None on failure.
    """
    try:
        req = urllib.request.Request(_FF_URL, headers={"User-Agent": "AeternusAgents/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            zip_bytes = resp.read()

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            # The ZIP contains a single CSV file
            names = zf.namelist()
            csv_name = None
            for name in names:
                if name.lower().endswith(".csv"):
                    csv_name = name
                    break
            if csv_name is None:
                logger.warning("fama_french: no CSV found in ZIP archive")
                return None

            csv_bytes = zf.read(csv_name)
            csv_text = csv_bytes.decode("utf-8", errors="replace")

        # Save to cache
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            f.write(csv_text)

        return csv_text

    except Exception as exc:
        logger.warning("fama_french: download failed (%s)", exc)
        return None


def _read_cache() -> Optional[str]:
    """Read cached CSV content. Returns None if file doesn't exist."""
    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def _parse_ff_csv(csv_text: str, lookback_days: int) -> Optional[Dict[str, float]]:
    """Parse Fama-French CSV and return mean factor returns over lookback period.

    The FF CSV has description lines before the actual data.
    Data rows start with an 8-digit date (YYYYMMDD) followed by Mkt-RF, SMB, HML, RF.
    All values are in percentage units (e.g., -0.10 means -0.10%).

    Returns: {"mkt_rf": float, "smb": float, "hml": float, "rf": float} or None.
    """
    rows = []
    for line in csv_text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Data rows start with 8-digit date
        if re.match(r"^\d{8}", line):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5:
                try:
                    mkt_rf = float(parts[1])
                    smb = float(parts[2])
                    hml = float(parts[3])
                    rf = float(parts[4])
                    rows.append((mkt_rf, smb, hml, rf))
                except (ValueError, IndexError):
                    continue

    if not rows:
        return None

    # Take last lookback_days rows
    recent = rows[-lookback_days:]
    if not recent:
        return None

    n = len(recent)
    return {
        "mkt_rf": sum(r[0] for r in recent) / n,
        "smb": sum(r[1] for r in recent) / n,
        "hml": sum(r[2] for r in recent) / n,
        "rf": sum(r[3] for r in recent) / n,
    }


def get_ff_factors(lookback_days: int = 60) -> Optional[Dict[str, float]]:
    """Fetch recent Fama-French 3-factor average daily returns.

    Returns: {"mkt_rf": float, "smb": float, "hml": float, "rf": float}
    All values are mean daily returns over lookback period, in percentage units.
    Returns None if fetch/parse fails.
    """
    if _cache_is_fresh():
        csv_text = _read_cache()
    else:
        csv_text = _download_and_cache()
        if csv_text is None:
            # Fallback: try stale cache
            csv_text = _read_cache()

    if csv_text is None:
        return None

    return _parse_ff_csv(csv_text, lookback_days)
