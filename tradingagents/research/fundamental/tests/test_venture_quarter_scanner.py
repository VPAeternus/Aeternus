from __future__ import annotations

from pathlib import Path

import pytest

from Growth import venture_quarter_scanner as scanner
from Growth.venture_mechanical_scorer import FilingPacket


def test_parse_quarter_bounds() -> None:
    start, end = scanner.parse_quarter_bounds("2026Q1")

    assert start.isoformat() == "2026-01-01"
    assert end.isoformat() == "2026-03-31"


def test_parse_quarter_bounds_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        scanner.parse_quarter_bounds("2026-Q1")


def test_scan_quarter_filters_to_matching_rows_and_threshold(monkeypatch) -> None:
    packets = {
        "SNDK": [
            FilingPacket(
                ticker="SNDK",
                filed="2025-12-15",
                form="10-Q",
                accn="older",
                sections={
                    "item_1a_risk_factors": "Customer concentration can create delays.",
                    "item_2_mda": "storage demand softened",
                },
            ),
            FilingPacket(
                ticker="SNDK",
                filed="2026-01-30",
                form="10-Q",
                accn="hit",
                sections={
                    "item_1a_risk_factors": "Customer concentration can create delays.",
                    "item_2_mda": (
                        "Artificial intelligence workloads drove enterprise SSD shipments higher. "
                        "Demand for NAND continued to outpace supply. Datacenter revenue increased 76% "
                        "and gross margin increased due to higher ASP."
                    )
                },
            ),
            FilingPacket(
                ticker="SNDK",
                filed="2026-04-30",
                form="10-Q",
                accn="later",
                sections={
                    "item_1a_risk_factors": "Customer concentration can create delays.",
                    "item_2_mda": "Artificial intelligence workloads remained solid.",
                },
            ),
        ],
        "NVDA": [
            FilingPacket(
                ticker="NVDA",
                filed="2026-02-25",
                form="10-K",
                accn="miss",
                sections={
                    "item_1_business": (
                        "AI infrastructure data center leader with industry leader based on revenue and market share."
                    ),
                    "item_1a_risk_factors": "Export restrictions remain risks.",
                },
            )
        ],
    }

    monkeypatch.setattr(
        scanner,
        "_load_packets",
        lambda tickers, extraction_mode="packet", min_filed=None: packets,
    )

    rows = scanner.scan_quarter("2026Q1", min_score=10, tickers=["SNDK", "NVDA"])

    assert len(rows) == 1
    assert rows[0]["ticker"] == "SNDK"
    assert rows[0]["filing_date"] == "2026-01-30"
    assert rows[0]["scan_quarter"] == "2026Q1"
    assert rows[0]["tradable_date"] == "2026-02-02"
    assert int(rows[0]["venture_score"]) >= 10


def test_scan_quarter_discovers_cached_tickers_when_not_provided(
    monkeypatch, tmp_path: Path
) -> None:
    packet_dir = tmp_path / "central_sec_cache" / "filing_packets"
    packet_dir.mkdir(parents=True)
    (packet_dir / "AAOI_1.json").write_text("{}")
    (packet_dir / "SNDK_1.json").write_text("{}")

    monkeypatch.setattr(scanner, "sec_cache_root", lambda *parts: tmp_path / "central_sec_cache" / Path(*parts))
    monkeypatch.setattr(
        scanner,
        "_load_packets",
        lambda tickers, extraction_mode="packet", min_filed=None: {
            ticker: [
                FilingPacket(
                    ticker=ticker,
                    filed="2026-01-15",
                    form="10-Q",
                    accn=f"{ticker.lower()}-1",
                    sections={
                        "item_1a_risk_factors": "Customer concentration can create delays.",
                        "item_2_mda": (
                            "Artificial intelligence demand increased. "
                            "Datacenter revenue increased 20% and gross margin increased."
                        )
                    },
                )
            ]
            for ticker in tickers
        },
    )

    rows = scanner.scan_quarter("2026Q1", min_score=1)

    assert [row["ticker"] for row in rows] == ["AAOI", "SNDK"]


def test_scan_quarter_sorts_by_highest_score_first(monkeypatch) -> None:
    packets = {
        "AAOI": [
            FilingPacket(
                ticker="AAOI",
                filed="2026-03-01",
                form="10-Q",
                accn="a",
                sections={
                    "item_1a_risk_factors": "Customer concentration can create delays.",
                    "item_2_mda": (
                        "Artificial intelligence demand increased for datacenter optical products. "
                        "Revenue increased 25% and gross margin increased."
                    )
                },
            )
        ],
        "SNDK": [
            FilingPacket(
                ticker="SNDK",
                filed="2026-01-30",
                form="10-Q",
                accn="b",
                sections={
                    "item_1a_risk_factors": "Customer concentration can create delays.",
                    "item_2_mda": (
                        "Artificial intelligence workloads drove enterprise SSD shipments higher. "
                        "Demand for NAND continued to outpace supply. Datacenter revenue increased 76% "
                        "and gross margin increased due to higher ASP."
                    )
                },
            )
        ],
    }

    monkeypatch.setattr(
        scanner,
        "_load_packets",
        lambda tickers, extraction_mode="packet", min_filed=None: packets,
    )

    rows = scanner.scan_quarter("2026Q1", min_score=1, tickers=["AAOI", "SNDK"])

    assert len(rows) == 2
    assert int(rows[0]["venture_score"]) >= int(rows[1]["venture_score"])


def test_scan_quarter_skips_incomplete_filings(monkeypatch) -> None:
    packets = {
        "SNDK": [
            FilingPacket(
                ticker="SNDK",
                filed="2026-01-30",
                form="10-Q",
                accn="b",
                sections={
                    "item_2_mda": (
                        "Artificial intelligence workloads drove enterprise SSD shipments higher."
                    )
                },
            )
        ]
    }

    monkeypatch.setattr(
        scanner,
        "_load_packets",
        lambda tickers, extraction_mode="packet", min_filed=None: packets,
    )

    rows = scanner.scan_quarter("2026Q1", min_score=1, tickers=["SNDK"])

    assert rows == []
