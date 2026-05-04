"""S-085: DoD Contract Scout — tests.

6 tests, all mocked (no real HTTP calls).
Monkeypatch pattern: patch requests.post with a mock returning status_code=200
and .json() returning the expected USASpending structure.
"""

from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.dealflow.sources.dod_contract_scout import (
    CONTRACT_SECTORS,
    ContractSpike,
    scan_dod_contract_spikes,
)


# ---------------------------------------------------------------------------
# Factory helpers (prefixed _ per convention)
# ---------------------------------------------------------------------------

def _mock_response(results: list, status_code: int = 200) -> MagicMock:
    """Return a mock requests.Response with .status_code and .json()."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {"results": results}
    return resp


def _award(
    amount: float,
    recipient: str = "ACME DEFENSE LLC",
    description: str = "missile system procurement",
) -> dict:
    return {
        "Award ID": "FAKE-001",
        "Recipient Name": recipient,
        "Award Amount": amount,
        "Award Date": "2026-02-01",
        "awarding_agency_name": "Department of Defense",
        "Description": description,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_munitions_spike_detected():
    """High recent vs low baseline for MUNITIONS triggers a spike with Z > 1.5."""
    # Recent: $500M in munitions awards; baseline: $50M (norm to 30d = $16.7M)
    # Z = (500M - 16.7M) / (16.7M * 0.3) = huge > 1.5
    recent_result = [_award(500_000_000, description="missile system delivery")]
    baseline_result = [_award(50_000_000, description="missile system delivery")]

    call_count = [0]

    def mock_post(url, json=None, timeout=None, headers=None):
        call_count[0] += 1
        # First call per sector = recent, second = baseline
        if call_count[0] % 2 == 1:
            return _mock_response(recent_result)
        return _mock_response(baseline_result)

    with patch("requests.post", side_effect=mock_post):
        spikes = scan_dod_contract_spikes(dry_run=True)

    munitions_spikes = [s for s in spikes if s.sector == "MUNITIONS"]
    assert len(munitions_spikes) == 1, f"Expected 1 MUNITIONS spike, got {munitions_spikes}"
    assert munitions_spikes[0].z_score > 1.5
    assert munitions_spikes[0].direction == "POSITIVE"


def test_no_spike_when_normal_spend():
    """Recent spend at the same daily rate as baseline produces no spikes.

    lookback_days=30, baseline_days=90 (defaults).
    recent=100M over 30d; baseline must be 300M over 90d so that
    baseline_normalized = 300M * (30/90) = 100M -> Z = (100M-100M)/(100M*0.3) = 0.
    """
    # recent window: 100M; baseline window: 300M (same per-day rate after normalization)
    call_count = [0]

    def mock_post(url, json=None, timeout=None, headers=None):
        call_count[0] += 1
        # Odd call = recent, even call = baseline
        if call_count[0] % 2 == 1:
            return _mock_response([_award(100_000_000, description="missile procurement")])
        return _mock_response([_award(300_000_000, description="missile procurement")])

    with patch("requests.post", side_effect=mock_post):
        spikes = scan_dod_contract_spikes(dry_run=True)

    assert spikes == [], f"Expected no spikes, got {spikes}"


def test_dry_run_does_not_write_akg():
    """dry_run=True means akg.set_causal_event is never called even when spikes fire."""
    recent_result = [_award(500_000_000, description="ammunition stockpile")]
    baseline_result = [_award(10_000_000, description="ammunition stockpile")]

    call_count = [0]

    def mock_post(url, json=None, timeout=None, headers=None):
        call_count[0] += 1
        if call_count[0] % 2 == 1:
            return _mock_response(recent_result)
        return _mock_response(baseline_result)

    mock_akg = MagicMock()

    with patch("requests.post", side_effect=mock_post):
        spikes = scan_dod_contract_spikes(akg=mock_akg, dry_run=True)

    mock_akg.set_causal_event.assert_not_called()
    # Spikes should still be returned even in dry_run
    assert len(spikes) >= 1


def test_api_failure_returns_empty():
    """ConnectionError on requests.post causes graceful return of empty list."""
    with patch("requests.post", side_effect=ConnectionError("network unreachable")):
        spikes = scan_dod_contract_spikes(dry_run=True)

    assert spikes == []


def test_confidence_capped_at_one():
    """An extreme Z-score (e.g. 100) produces confidence = 1.0."""
    # recent = $10B, baseline norm ~$3.3M -> Z >> 3 -> confidence capped at 1.0
    huge_recent = [_award(10_000_000_000, description="bomb warhead system")]
    tiny_baseline = [_award(10_000_000, description="bomb warhead system")]

    call_count = [0]

    def mock_post(url, json=None, timeout=None, headers=None):
        call_count[0] += 1
        if call_count[0] % 2 == 1:
            return _mock_response(huge_recent)
        return _mock_response(tiny_baseline)

    with patch("requests.post", side_effect=mock_post):
        spikes = scan_dod_contract_spikes(dry_run=True)

    assert len(spikes) > 0
    for spike in spikes:
        assert spike.confidence <= 1.0


def test_multiple_sectors_can_spike():
    """Two sectors (MUNITIONS and FUEL_SUPPLY) both spike when both show high recent spend."""
    # We need MUNITIONS and FUEL_SUPPLY to both get recent >> baseline
    # Map NAICS codes to sector to alternate correctly
    munitions_naics = set(CONTRACT_SECTORS["MUNITIONS"].naics_codes)
    fuel_naics = set(CONTRACT_SECTORS["FUEL_SUPPLY"].naics_codes)

    def mock_post(url, json=None, timeout=None, headers=None):
        body_naics = set(json.get("filters", {}).get("naics_codes", []))
        # Identify which sector is being queried
        time_period = json.get("filters", {}).get("time_period", [{}])
        start = time_period[0].get("start_date", "") if time_period else ""
        # Determine if this is recent or baseline by comparing date recency
        today = dt.date.today()
        cutoff = (today - dt.timedelta(days=30)).isoformat()
        is_recent = start >= cutoff

        if body_naics & munitions_naics:
            desc = "missile system procurement"
            amount = 800_000_000 if is_recent else 20_000_000
        elif body_naics & fuel_naics:
            desc = "aviation jet fuel jp-8"
            amount = 600_000_000 if is_recent else 15_000_000
        else:
            desc = "other"
            amount = 10_000_000

        return _mock_response([_award(amount, description=desc)])

    with patch("requests.post", side_effect=mock_post):
        spikes = scan_dod_contract_spikes(dry_run=True)

    spike_sectors = {s.sector for s in spikes}
    assert "MUNITIONS" in spike_sectors, f"MUNITIONS not in {spike_sectors}"
    assert "FUEL_SUPPLY" in spike_sectors, f"FUEL_SUPPLY not in {spike_sectors}"
    assert len(spikes) >= 2


# ---------------------------------------------------------------------------
# Test 7: AKG auto-load when not passed + dry_run=False
# ---------------------------------------------------------------------------

def test_akg_auto_loaded_when_not_passed():
    """When akg=None and dry_run=False, scout loads AKG internally and saves after spikes."""
    mock_akg = MagicMock()

    fake_spike = ContractSpike(
        sector="MUNITIONS",
        recent_total_usd=50_000_000.0,
        baseline_total_usd=10_000_000.0,
        z_score=4.0,
        top_recipients=["Raytheon", "Lockheed"],
        award_count=25,
        direction="POSITIVE",
        confidence=1.0,
    )

    with patch("tradingagents.dealflow.sources.dod_contract_scout._detect_sector_spike", return_value=fake_spike), \
         patch("tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph") as MockAKG:
        MockAKG.load.return_value = mock_akg

        spikes = scan_dod_contract_spikes()  # No akg passed, not dry_run

    # AKG should have been loaded
    MockAKG.load.assert_called_once()
    # set_causal_event called once per sector (4 sectors, all return fake_spike)
    assert mock_akg.set_causal_event.call_count == 4
    # save() should have been called
    mock_akg.save.assert_called_once()
