"""S-085: DoD Contract Scout — USASpending.gov defense contract award spike detector.

Reads USASpending.gov public API (no key required) to detect spending spikes in
defense-related contract awards 4-8 weeks before operations become public.
Free daily scheduled writer that writes CausalEvents to AKG.
"""

from __future__ import annotations

import datetime as dt
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional

import requests

if TYPE_CHECKING:
    from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph

# ---------------------------------------------------------------------------
# API constants
# ---------------------------------------------------------------------------

_USASPENDING_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"

# Definitive Contract (A), Purchase Order (B), Delivery Order (C), BPA Call (D)
_CONTRACT_AWARD_TYPE_CODES = ["A", "B", "C", "D"]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ContractSector:
    name: str
    naics_codes: list
    keywords: list          # filter award descriptions (case-insensitive)
    baseline_weight: float  # expected fraction of total DoD spend


@dataclass
class ContractSpike:
    sector: str
    recent_total_usd: float
    baseline_total_usd: float
    z_score: float
    top_recipients: list
    award_count: int
    direction: str          # always "POSITIVE" -- defense build-up signal
    confidence: float


# ---------------------------------------------------------------------------
# Sector definitions
# ---------------------------------------------------------------------------

CONTRACT_SECTORS: Dict[str, ContractSector] = {
    "MUNITIONS": ContractSector(
        name="Munitions",
        naics_codes=["336414", "336415", "336419", "325920", "332993"],
        keywords=["missile", "munition", "ammunition", "explosive", "warhead", "bomb"],
        baseline_weight=0.12,
    ),
    "FUEL_SUPPLY": ContractSector(
        name="Fuel Supply",
        naics_codes=["324110"],
        keywords=["fuel", "petroleum", "jet fuel", "jp-8", "diesel", "aviation"],
        baseline_weight=0.08,
    ),
    "MEDICAL_FORWARD": ContractSector(
        name="Forward Medical",
        naics_codes=["621"],
        keywords=["field hospital", "combat medical", "trauma", "forward", "triage", "casualty"],
        baseline_weight=0.04,
    ),
    "ENGINEERING_BASE": ContractSector(
        name="Base Engineering",
        naics_codes=["237"],
        keywords=["base", "airfield", "runway", "fortif", "barrier", "rapid deployment"],
        baseline_weight=0.03,
    ),
}


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _build_request_body(
    naics_codes: list,
    start_date: str,
    end_date: str,
    limit: int = 50,
) -> dict:
    return {
        "filters": {
            "award_type_codes": _CONTRACT_AWARD_TYPE_CODES,
            "agencies": [
                {"type": "awarding", "tier": "toptier", "name": "Department of Defense"}
            ],
            "time_period": [{"start_date": start_date, "end_date": end_date}],
            "naics_codes": naics_codes,
        },
        "fields": [
            "Award ID",
            "Recipient Name",
            "Award Amount",
            "Award Date",
            "awarding_agency_name",
            "Description",
        ],
        "sort": "Award Amount",
        "order": "desc",
        "limit": limit,
    }


def _fetch_awards(
    naics_codes: list,
    start_date: str,
    end_date: str,
    timeout_seconds: float = 30.0,
) -> Optional[dict]:
    """POST to USASpending API. Returns parsed JSON or None on any failure."""
    body = _build_request_body(naics_codes, start_date, end_date)
    try:
        resp = requests.post(
            _USASPENDING_URL,
            json=body,
            timeout=timeout_seconds,
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code != 200:
            print(
                f"[dod_contract_scout] API returned {resp.status_code} for {naics_codes}",
                file=sys.stderr,
            )
            return None
        return resp.json()
    except Exception as e:
        print(f"[dod_contract_scout] HTTP error for {naics_codes}: {e}", file=sys.stderr)
        return None


def _parse_awards(response: Optional[dict], keywords: list) -> tuple:
    """
    Parse USASpending response.
    Returns (total_usd, award_count, top_recipients).
    Filters awards to those whose Description contains at least one keyword
    (case-insensitive). Awards with no description are still counted.
    """
    if response is None:
        return 0.0, 0, []

    results = response.get("results", [])
    if not results:
        return 0.0, 0, []

    total_usd = 0.0
    award_count = 0
    recipient_totals: Dict[str, float] = {}

    for award in results:
        amount = award.get("Award Amount") or 0
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            amount = 0.0

        if amount <= 0:
            continue

        # Soft keyword filter on description -- skip only when description exists
        # and no keyword matches (NAICS code already ensures broad relevance)
        description = (award.get("Description") or "").lower()
        if description and keywords:
            if not any(kw in description for kw in keywords):
                continue

        total_usd += amount
        award_count += 1

        recipient = (award.get("Recipient Name") or "UNKNOWN").strip()
        recipient_totals[recipient] = recipient_totals.get(recipient, 0.0) + amount

    top_recipients = [
        r for r, _ in sorted(recipient_totals.items(), key=lambda x: x[1], reverse=True)
    ][:3]

    return total_usd, award_count, top_recipients


# ---------------------------------------------------------------------------
# Per-sector spike detection
# ---------------------------------------------------------------------------

def _detect_sector_spike(
    sector_key: str,
    sector: ContractSector,
    lookback_days: int,
    baseline_days: int,
    today: dt.date,
    timeout_seconds: float,
) -> Optional[ContractSpike]:
    """Fetch recent + baseline windows, compute Z-score, return ContractSpike or None."""
    recent_end = today
    recent_start = today - dt.timedelta(days=lookback_days)
    baseline_end = recent_start - dt.timedelta(days=1)
    baseline_start = baseline_end - dt.timedelta(days=baseline_days)

    recent_resp = _fetch_awards(
        naics_codes=sector.naics_codes,
        start_date=recent_start.isoformat(),
        end_date=recent_end.isoformat(),
        timeout_seconds=timeout_seconds,
    )
    baseline_resp = _fetch_awards(
        naics_codes=sector.naics_codes,
        start_date=baseline_start.isoformat(),
        end_date=baseline_end.isoformat(),
        timeout_seconds=timeout_seconds,
    )

    recent_total, award_count, top_recipients = _parse_awards(recent_resp, sector.keywords)
    baseline_total, _, _ = _parse_awards(baseline_resp, sector.keywords)

    # Normalize baseline to the same period length as the recent window
    baseline_normalized = (
        baseline_total * (lookback_days / baseline_days) if baseline_days > 0 else 0.0
    )

    # Z-score: use 30% of baseline_normalized as std estimate (two-point comparison)
    denominator = baseline_normalized * 0.3 if baseline_normalized > 0 else 1.0
    z_score = (recent_total - baseline_normalized) / denominator

    if z_score <= 1.5:
        return None

    confidence = round(min(1.0, z_score / 3.0), 6)

    return ContractSpike(
        sector=sector_key,
        recent_total_usd=round(recent_total, 2),
        baseline_total_usd=round(baseline_normalized, 2),
        z_score=round(z_score, 4),
        top_recipients=top_recipients,
        award_count=award_count,
        direction="POSITIVE",
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Main scan function
# ---------------------------------------------------------------------------

def scan_dod_contract_spikes(
    akg=None,
    lookback_days: int = 30,
    baseline_days: int = 90,
    dry_run: bool = False,
    timeout_seconds: float = 30.0,
) -> List[ContractSpike]:
    """
    Scan all CONTRACT_SECTORS for unusual DoD award spending.

    1. For each sector: fetch recent (last lookback_days) and baseline windows
    2. Normalize baseline to the same period length
    3. Z-score: (recent - baseline_norm) / (baseline_norm * 0.3)
    4. Spike fires if Z > 1.5; confidence = min(1.0, z / 3.0)
    5. Write CausalEvent to AKG for each spike (unless dry_run=True)
    6. Return list of ContractSpike objects
    """
    today = dt.date.today()
    today_str = today.isoformat()
    spikes: List[ContractSpike] = []

    # Load AKG if not provided (so CLI and scheduler callers don't need to pass it)
    if akg is None and not dry_run:
        try:
            from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
            akg = AeternusKnowledgeGraph.load()
        except Exception as e:
            print(f"[dod_contract_scout] AKG load error: {e}", file=sys.stderr)

    for sector_key, sector in CONTRACT_SECTORS.items():
        try:
            spike = _detect_sector_spike(
                sector_key=sector_key,
                sector=sector,
                lookback_days=lookback_days,
                baseline_days=baseline_days,
                today=today,
                timeout_seconds=timeout_seconds,
            )
        except Exception as e:
            print(
                f"[dod_contract_scout] sector eval error {sector_key}: {e}",
                file=sys.stderr,
            )
            spike = None

        if spike is None:
            continue

        spikes.append(spike)

        # Write CausalEvent to AKG
        if akg is not None and not dry_run:
            try:
                event_data = {
                    "ticker": f"DOD_{sector_key}",
                    "event_type": "COMMODITY_SHOCK",
                    "event_date": today_str,
                    "magnitude": spike.confidence,
                    "direction": "POSITIVE",
                    "source": "dod_contract_scout",
                    "processed_at": dt.datetime.utcnow().isoformat(),
                    "contract_sector": sector_key,
                    "recent_total_usd": spike.recent_total_usd,
                    "z_score": spike.z_score,
                    "top_recipients": spike.top_recipients,
                }
                akg.set_causal_event(
                    event_id=f"DOD_{sector_key}_{today_str}",
                    data=event_data,
                )
            except Exception as e:
                print(
                    f"[dod_contract_scout] AKG write error {sector_key}: {e}",
                    file=sys.stderr,
                )

    if akg is not None and spikes and not dry_run:
        try:
            akg.save()
        except Exception as e:
            print(f"[dod_contract_scout] AKG save error: {e}", file=sys.stderr)

    return spikes
