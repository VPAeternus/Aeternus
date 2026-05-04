"""
fiscal_calendar.py — Pure Python fiscal year / quarter resolver.
No network calls, no LLM dependencies.

Usage:
    from tradingagents.agents.utils.fiscal_calendar import (
        get_fiscal_year_end_month,
        resolve_fiscal_quarter,
    )
"""

from __future__ import annotations

from datetime import date
from typing import Dict

# ---------------------------------------------------------------------------
# Fiscal Year End Month lookup.
# Only non-December (non-calendar-year) tickers are stored here.
# All omitted tickers default to 12 (calendar year) via get_fiscal_year_end_month().
# Values are the month number (1–12) on which the fiscal year closes.
# ---------------------------------------------------------------------------

FISCAL_YEAR_END_MONTH: Dict[str, int] = {
    # January (month 1)
    "WMT": 1,    # Walmart
    "HD": 1,     # Home Depot
    "LOW": 1,    # Lowe's
    "TGT": 1,    # Target
    "NVDA": 1,   # NVIDIA
    "CRM": 1,    # Salesforce
    "WDAY": 1,   # Workday
    "SNOW": 1,   # Snowflake
    "MDB": 1,    # MongoDB
    "CRWD": 1,   # CrowdStrike
    "OKTA": 1,   # Okta
    "DG": 1,     # Dollar General
    "DLTR": 1,   # Dollar Tree
    "JWN": 1,    # Nordstrom
    "MRVL": 1,   # Marvell Technology
    "BBWI": 1,   # Bath & Body Works
    "ANF": 1,    # Abercrombie & Fitch
    "GPS": 1,    # Gap
    "PVH": 1,    # PVH Corp
    "KR": 1,     # Kroger
    "RH": 1,     # RH
    "COUP": 1,   # Coupa Software

    # February (month 2)
    "STZ": 2,    # Constellation Brands
    "RAD": 2,    # Rite Aid

    # March (month 3)
    "RL": 3,     # Ralph Lauren

    # April (month 4)
    "SJM": 4,    # J.M. Smucker
    "BFB": 4,    # Brown-Forman (BF.B)

    # May (month 5)
    "ORCL": 5,   # Oracle
    "NKE": 5,    # Nike
    "FDX": 5,    # FedEx
    "GIS": 5,    # General Mills
    "CAG": 5,    # Conagra Brands

    # June (month 6)
    "MSFT": 6,   # Microsoft
    "LRCX": 6,   # Lam Research
    "KLAC": 6,   # KLA Corp
    "TEAM": 6,   # Atlassian
    "SYY": 6,    # Sysco
    "PFGC": 6,   # Performance Food Group

    # July (month 7)
    "INTU": 7,   # Intuit
    "PANW": 7,   # Palo Alto Networks
    "ZS": 7,     # Zscaler
    "CPB": 7,    # Campbell Soup

    # August (month 8)
    "MU": 8,     # Micron Technology
    "COST": 8,   # Costco Wholesale
    "AZO": 8,    # AutoZone
    "WBA": 8,    # Walgreens Boots Alliance

    # September (month 9)
    "AAPL": 9,   # Apple
    "QCOM": 9,   # Qualcomm

    # October (month 10)
    "AVGO": 10,  # Broadcom
    "HPQ": 10,   # HP Inc.
    "HPE": 10,   # Hewlett Packard Enterprise
    "AMAT": 10,  # Applied Materials
    "DE": 10,    # Deere & Company
    "SNPS": 10,  # Synopsys
    "TOL": 10,   # Toll Brothers
    "HRL": 10,   # Hormel Foods

    # November (month 11)
    "ADBE": 11,  # Adobe
    "CCL": 11,   # Carnival
    "LEN": 11,   # Lennar
    "MKC": 11,   # McCormick

    # ACN fiscal year ends August 31
    "ACN": 8,    # Accenture
}


def get_fiscal_year_end_month(ticker: str) -> int:
    """Return fiscal year end month (1–12) for ticker. Default 12 (calendar year)."""
    return FISCAL_YEAR_END_MONTH.get(ticker.upper(), 12)


def resolve_fiscal_quarter(ticker: str, fiscal_date_ending: str) -> Dict[str, str]:
    """Resolve fiscal quarter from ticker and fiscal_date_ending string (YYYY-MM-DD).

    Returns a dict with keys:
        start          — "YYYY-MM-DD" (first day of the quarter)
        end            — "YYYY-MM-DD" (last day of the quarter = fiscal_date_ending)
        label          — "Q1 FY2026"
        fiscal_year    — "2026"
        fiscal_quarter — "1"

    On any parse failure or unrecognized quarter boundary, all keys are set to "unknown".
    """
    _unknown: Dict[str, str] = {
        "start": "unknown",
        "end": "unknown",
        "label": "unknown",
        "fiscal_year": "unknown",
        "fiscal_quarter": "unknown",
    }

    # 1. Parse fiscal_date_ending
    try:
        end_date = date.fromisoformat(fiscal_date_ending[:10])
    except (ValueError, TypeError):
        return _unknown

    fye_month = get_fiscal_year_end_month(ticker)
    end_month = end_date.month

    # 2. Determine fiscal quarter number.
    #    Quarter boundaries (months from FYE month): 0=Q4, -3=Q3, -6=Q2, -9=Q1.
    #    Compute how many months before FYE this quarter ends (mod 12).
    months_before_fye = (fye_month - end_month) % 12
    offset_to_quarter: Dict[int, int] = {0: 4, 3: 3, 6: 2, 9: 1}
    fiscal_quarter = offset_to_quarter.get(months_before_fye)
    if fiscal_quarter is None:
        return _unknown

    # 3. Determine fiscal year.
    #    For non-calendar FYE: if end_month > fye_month, the period falls in the
    #    *next* named fiscal year (e.g., Apple FYE=Sep; Dec 2025 quarter → FY2026).
    #    For calendar FYE (month=12): fiscal_year = calendar year always.
    cal_year = end_date.year
    if fye_month != 12 and end_month > fye_month:
        fiscal_year = cal_year + 1
    else:
        fiscal_year = cal_year

    # 4. Compute quarter start date.
    #    Quarter spans 3 months. Start month = end_month - 2 (same quarter, 3 months long).
    #    e.g., quarter ending January → starts November.
    start_month = end_month - 2
    start_year = end_date.year
    if start_month <= 0:
        start_month += 12
        start_year -= 1

    start_date = date(start_year, start_month, 1)

    return {
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "label": f"Q{fiscal_quarter} FY{fiscal_year}",
        "fiscal_year": str(fiscal_year),
        "fiscal_quarter": str(fiscal_quarter),
    }
