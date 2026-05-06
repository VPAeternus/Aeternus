from __future__ import annotations

import argparse
import csv
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from src.config.cache_paths import sec_cache_root

PACKET_DIR = sec_cache_root("filing_packets")
DEFAULT_SOURCE_OUTPUT = Path("Growth/be_lte_nvda_sndk_venture_score_source.csv")
DEFAULT_UNIVERSE = ["BE", "LITE", "NVDA", "SNDK"]
MIN_FILED = "2025-01-01"
INCUMBENT_LEADERS = {"NVDA"}

WAVE_TERMS = [
    "artificial intelligence",
    "ai/ml",
    "ai infrastructure",
    "ai workloads",
    "data center",
    "datacenter",
]
ENABLING_LAYER_TERMS = [
    "power",
    "storage",
    "nand",
    "ssd",
    "optical",
    "interconnect",
    "network",
    "infrastructure",
    "fuel cell",
]
DEMAND_LIFT_TERMS = [
    "increased demand",
    "strong demand",
    "demand for",
    "revenue increased",
    "shipments",
    "deploy",
    "deployment",
    "exabytes sold",
    "outpace supply",
]
DEPLOYMENT_CONTEXT_TERMS = [
    "enterprise ssd",
    "public clouds",
    "cloud service providers",
    "ai infrastructure builders",
    "semi-custom",
    "datacenters",
    "data center customers",
    "grid infrastructure",
    "interconnection",
]
GROWTH_SURFACE_TERMS = [
    "large",
    "broad",
    "expanding portfolio",
    "growing needs",
    "growth surface",
    "massive",
    "high-demand",
]
LEADERSHIP_TERMS = [
    "industry leader based on revenue and market share",
    "largest-ever",
    "leading developer, manufacturer and provider",
    "recognized as an industry leader",
]
DEVELOPING_WAVE_TERMS = [
    "persist through calendar year 2026 and beyond",
    "through 2028",
    "through 2033",
    "growing demand",
    "accelerating",
    "expand their data centers",
    "rapid growth of ai infrastructure",
]
LIQUIDITY_TERMS = [
    "cash and cash equivalents",
    "liquidity",
    "revolving credit facility",
    "cash flows",
    "sufficiency of our cash",
]
SCAFFOLD_TERMS = [
    "brookfield",
    "aep",
    "financing framework",
    "channel and financing partner",
    "safe harbor",
    "tax credit",
    "strategic partnership",
    "utility",
]
CAPACITY_TERMS = [
    "manufacturing capacity",
    "supplier",
    "capacity",
    "production",
    "commercial capacity",
    "enterprise ssd shipments",
]
IMPROVEMENT_TERMS = [
    "improved pricing",
    "gross margin increased",
    "improved revenues",
    "higher asp",
    "capital efficiency",
    "profitability",
]
RUNWAY_TERMS = [
    "through 2028",
    "through 2033",
    "beyond",
    "persist through calendar year 2026 and beyond",
    "durable demand",
    "multi-year",
]
TORQUE_TERMS = [
    "higher asp",
    "gross margin increased",
    "improved pricing",
    "underutilization charges",
    "pricing conditions",
    "outpace supply",
]
FINANCING_DEPENDENCE_TERMS = [
    "additional financing",
    "tax equity",
    "reduced availability of project finance",
    "obtain additional capital",
]
DELAY_TERMS = [
    "delay",
    "delays",
    "delayed",
    "bookings",
    "order uncertainty",
    "backlog",
]
PRESSURE_TERMS = [
    "margin pressure",
    "underutilization",
    "inventory",
    "commoditization",
    "higher costs per gigabyte",
]
REGULATORY_TERMS = [
    "export",
    "china",
    "tariff",
    "regulatory",
    "feoc",
]
CONCENTRATION_TERMS = [
    "customer concentration",
    "limited customers",
    "cancellation",
    "backlog uncertainty",
    "order cancellations",
]
NUMERIC_GROWTH_PATTERNS = [
    re.compile(r"\b\d{1,3}%"),
    re.compile(r"\b\$\d+(?:\.\d+)?\s*billion\b"),
    re.compile(r"\b\d+(?:\.\d+)?\s*gw\b"),
]


def _observed_fixed_holiday(year: int, month: int, day: int) -> date:
    holiday = date(year, month, day)
    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    current = date(year, month, 1)
    while current.weekday() != weekday:
        current += timedelta(days=1)
    return current + timedelta(weeks=n - 1)


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    if month == 12:
        current = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        current = date(year, month + 1, 1) - timedelta(days=1)
    while current.weekday() != weekday:
        current -= timedelta(days=1)
    return current


def _easter_sunday(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _market_holidays(year: int) -> set[date]:
    return {
        _observed_fixed_holiday(year, 1, 1),
        _nth_weekday_of_month(year, 1, 0, 3),
        _nth_weekday_of_month(year, 2, 0, 3),
        _easter_sunday(year) - timedelta(days=2),
        _last_weekday_of_month(year, 5, 0),
        _observed_fixed_holiday(year, 6, 19),
        _observed_fixed_holiday(year, 7, 4),
        _nth_weekday_of_month(year, 9, 0, 1),
        _nth_weekday_of_month(year, 11, 3, 4),
        _observed_fixed_holiday(year, 12, 25),
    }


@dataclass
class FilingPacket:
    ticker: str
    filed: str
    form: str
    accn: str
    sections: dict[str, str]
    source_mode: str = "packet"

    @property
    def text(self) -> str:
        return "\n".join(self.sections.values()).lower()


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def _section_label(section_key: str) -> str:
    lowered = section_key.lower()
    if "business" in lowered:
        return "business"
    if "risk" in lowered:
        return "risk"
    if "mda" in lowered:
        return "mda"
    return lowered


def _section_items(
    packet: FilingPacket, include_risk: bool = True
) -> list[tuple[str, str, str]]:
    items = []
    for key, value in packet.sections.items():
        label = _section_label(key)
        if not include_risk and label == "risk":
            continue
        items.append((key, label, value.lower()))
    return items


def _find_section_hit(
    packet: FilingPacket,
    *,
    terms: Iterable[str] = (),
    patterns: Iterable[re.Pattern[str]] = (),
    labels: Iterable[str] | None = None,
    include_risk: bool = True,
    exclude_terms: Iterable[str] = (),
) -> tuple[str, str] | None:
    allowed_labels = set(labels or [])
    for _key, label, text in _section_items(packet, include_risk=include_risk):
        if allowed_labels and label not in allowed_labels:
            continue
        if exclude_terms and _contains_any(text, exclude_terms):
            continue
        if terms and _contains_any(text, terms):
            return label, text
        if any(pattern.search(text) for pattern in patterns):
            return label, text
    return None


def _count_section_hits(packet: FilingPacket, terms: Iterable[str]) -> int:
    hits = 0
    for _key, _label, text in _section_items(packet):
        if _contains_any(text, terms):
            hits += 1
    return hits


def _audit_text(values: list[str]) -> str:
    if not values:
        return ""
    return "|".join(dict.fromkeys(values))


def _required_section_labels(form: str) -> set[str]:
    if form == "10-K":
        return {"business", "risk", "mda"}
    if form == "10-Q":
        return {"risk", "mda"}
    return set()


def _missing_required_section_labels(packet: FilingPacket) -> list[str]:
    required = _required_section_labels(packet.form)
    present = {label for _key, label, _text in _section_items(packet)}
    return sorted(required - present)


def _assert_scoreable(
    packet: FilingPacket, prior_packet: FilingPacket | None
) -> None:
    missing_current = _missing_required_section_labels(packet)
    if missing_current:
        joined = ",".join(missing_current)
        raise ValueError(f"incomplete_current_filing:{joined}")

    if prior_packet is None:
        return

    missing_prior = _missing_required_section_labels(prior_packet)
    if missing_prior:
        joined = ",".join(missing_prior)
        raise ValueError(f"incomplete_prior_filing:{joined}")


def _extract_sections_via_edgartools(
    ticker: str,
    accn: str,
    form: str,
    fallback_sections: dict[str, str],
) -> dict[str, str]:
    try:
        from autoresearch.fetch_filing_text import (
            _build_filing_lookup,
            extract_sections,
        )
    except Exception:
        return fallback_sections

    try:
        lookup = _build_filing_lookup(ticker)
        filing = lookup.get(accn.replace("-", ""))
        if filing is None:
            return fallback_sections

        sections = {
            key: value
            for key, value in (extract_sections(filing, form) or {}).items()
            if value and not key.startswith("_")
        }
        if sections:
            return sections

        obj = None
        try:
            obj = filing.obj()
        except Exception:
            obj = None

        item_map = {
            "10-K": [
                ("Item 1", "item_1_business"),
                ("Item 1A", "item_1a_risk_factors"),
                ("Item 7", "item_7_mda"),
            ],
            "10-Q": [
                ("Item 1A", "item_1a_risk_factors"),
                ("Item 2", "item_2_mda"),
            ],
        }
        if obj is not None:
            for item_key, section_key in item_map.get(form, []):
                try:
                    value = obj[item_key]
                except Exception:
                    value = None
                if value:
                    sections[section_key] = str(value)[:200000]
        if sections:
            return sections

        text_value = ""
        try:
            text_value = str(filing.text() or "")
        except Exception:
            text_value = ""
        if not text_value:
            return fallback_sections

        lowered = text_value.lower()
        if form == "10-K":
            if "item 1" in lowered and "business" in lowered:
                sections["item_1_business"] = text_value[:200000]
            if "item 1a" in lowered and "risk factors" in lowered:
                sections["item_1a_risk_factors"] = text_value[:200000]
            if "item 7" in lowered and "management" in lowered:
                sections["item_7_mda"] = text_value[:200000]
        elif form == "10-Q":
            if "item 1a" in lowered and "risk factors" in lowered:
                sections["item_1a_risk_factors"] = text_value[:200000]
            if "item 2" in lowered and "management" in lowered:
                sections["item_2_mda"] = text_value[:200000]
        return sections or fallback_sections
    except Exception:
        return fallback_sections


def _load_packets(
    tickers: list[str], extraction_mode: str = "packet", min_filed: str | None = None
) -> dict[str, list[FilingPacket]]:
    min_filed = MIN_FILED if min_filed is None else min_filed
    by_ticker: dict[str, list[FilingPacket]] = {ticker: [] for ticker in tickers}
    for ticker in tickers:
        for path in sorted(PACKET_DIR.glob(f"{ticker}_*.json")):
            raw = json.loads(path.read_text())
            filed = str(raw.get("filed", ""))
            form = str(raw.get("form", ""))
            if not filed or filed < min_filed:
                continue
            if form not in {"10-Q", "10-K"}:
                continue
            sections = raw.get("sections", {}) or {}
            source_mode = "packet"
            if extraction_mode == "edgartools":
                sections = _extract_sections_via_edgartools(
                    ticker=ticker,
                    accn=str(raw["accn"]),
                    form=form,
                    fallback_sections=sections,
                )
                source_mode = "edgartools"
            by_ticker[ticker].append(
                FilingPacket(
                    ticker=ticker,
                    filed=filed,
                    form=form,
                    accn=str(raw["accn"]),
                    sections=sections,
                    source_mode=source_mode,
                )
            )
        by_ticker[ticker].sort(key=lambda item: item.filed)
    return by_ticker


def _wave_exposure(packet: FilingPacket) -> tuple[int, list[str]]:
    score = 0
    audit: list[str] = []
    non_risk_labels = {
        label for _key, label, _text in _section_items(packet, include_risk=False)
    }

    ai_hit = _find_section_hit(
        packet, terms=WAVE_TERMS, labels=non_risk_labels, include_risk=False
    )
    if ai_hit:
        score += 1
        audit.append(f"wave_ai_context_{ai_hit[0]}")

    enabling_hit = _find_section_hit(
        packet,
        terms=ENABLING_LAYER_TERMS,
        labels=non_risk_labels,
        include_risk=False,
    )
    if enabling_hit:
        score += 1
        audit.append(f"wave_enabling_layer_{enabling_hit[0]}")

    demand_hit = _find_section_hit(
        packet,
        terms=DEMAND_LIFT_TERMS,
        labels=non_risk_labels,
        include_risk=False,
    )
    if ai_hit and demand_hit:
        score += 1
        audit.append(f"wave_demand_confirmation_{demand_hit[0]}")

    deployment_hit = _find_section_hit(
        packet,
        terms=DEPLOYMENT_CONTEXT_TERMS,
        labels=non_risk_labels,
        include_risk=False,
    )
    if deployment_hit:
        score += 1
        audit.append(f"wave_deployment_context_{deployment_hit[0]}")

    multi_section_count = 0
    for label in sorted(non_risk_labels):
        section_hit = _find_section_hit(
            packet,
            terms=WAVE_TERMS + DEPLOYMENT_CONTEXT_TERMS,
            labels=[label],
            include_risk=False,
        )
        if section_hit:
            multi_section_count += 1
    if multi_section_count > 1:
        score += 1
        audit.append("wave_multi_section_support")

    return min(score, 5), audit


def _asymmetric_upside(packet: FilingPacket) -> tuple[int, list[str]]:
    score = 0
    audit: list[str] = []
    if packet.ticker not in INCUMBENT_LEADERS:
        score += 2
        audit.append("upside_non_incumbent")

    growth_hit = _find_section_hit(
        packet,
        terms=GROWTH_SURFACE_TERMS + DEPLOYMENT_CONTEXT_TERMS,
        labels=["business", "mda"],
        include_risk=False,
    )
    if growth_hit:
        score += 1
        audit.append(f"upside_growth_surface_{growth_hit[0]}")

    leadership_hit = _find_section_hit(
        packet,
        terms=LEADERSHIP_TERMS,
        labels=["business", "mda"],
        include_risk=False,
    )
    if not leadership_hit:
        score += 1
        audit.append("upside_no_incumbent_leadership_claim")

    wave_hit = _find_section_hit(
        packet,
        terms=DEVELOPING_WAVE_TERMS + WAVE_TERMS,
        labels=["business", "mda"],
        include_risk=False,
    )
    if wave_hit:
        score += 1
        audit.append(f"upside_wave_duration_{wave_hit[0]}")
    return min(score, 5), audit


def _fundable_scaling(packet: FilingPacket) -> tuple[int, list[str]]:
    score = 0
    audit: list[str] = []
    for name, terms in [
        ("scaling_liquidity", LIQUIDITY_TERMS),
        ("scaling_scaffold", SCAFFOLD_TERMS),
        ("scaling_capacity", CAPACITY_TERMS),
        ("scaling_improvement", IMPROVEMENT_TERMS),
        ("scaling_runway", RUNWAY_TERMS),
    ]:
        hit = _find_section_hit(packet, terms=terms, labels=["business", "mda", "risk"])
        if hit:
            score += 1
            audit.append(f"{name}_{hit[0]}")
    return min(score, 5), audit


def _trigger_snapshot(packet: FilingPacket) -> dict[str, bool]:
    wave_score, wave_audit = _wave_exposure(packet)
    scaling_score, scaling_audit = _fundable_scaling(packet)
    torque_score, torque_audit = _wave_torque(packet)
    return {
        "wave_framing": wave_score >= 2
        or any(item.startswith("wave_ai_context") for item in wave_audit),
        "demand_evidence": any("demand_confirmation" in item for item in wave_audit),
        "scaling_support": scaling_score >= 2
        or any(item.startswith("scaling_capacity") for item in scaling_audit),
        "operating_leverage": any(
            "torque_pricing_margin" in item for item in torque_audit
        ),
        "breakaway": any("torque_numeric_growth" in item for item in torque_audit),
    }


def _filing_delta(packet: FilingPacket, prior_packet: FilingPacket | None) -> int:
    current = _trigger_snapshot(packet)
    if prior_packet is None:
        return sum(1 for value in current.values() if value)
    prior = _trigger_snapshot(prior_packet)
    return sum(
        1 for key, value in current.items() if value and not prior.get(key, False)
    )


def _wave_torque(packet: FilingPacket) -> tuple[int, list[str]]:
    score = 0
    audit: list[str] = []

    enabling_hit = _find_section_hit(
        packet,
        terms=ENABLING_LAYER_TERMS,
        labels=["business", "mda"],
        include_risk=False,
    )
    if enabling_hit:
        score += 1
        audit.append(f"torque_enabling_layer_{enabling_hit[0]}")

    numeric_hit = _find_section_hit(
        packet,
        patterns=NUMERIC_GROWTH_PATTERNS,
        labels=["business", "mda"],
        include_risk=False,
    )
    if numeric_hit and _find_section_hit(
        packet,
        terms=[
            "revenue increased",
            "shipments",
            "stronger demand",
            "datacenter revenue",
            "enterprise ssd shipments",
        ],
        labels=[numeric_hit[0]],
        include_risk=False,
    ):
        score += 1
        audit.append(f"torque_numeric_growth_{numeric_hit[0]}")

    pricing_hit = _find_section_hit(
        packet,
        terms=TORQUE_TERMS,
        labels=["business", "mda"],
        include_risk=False,
    )
    if pricing_hit:
        score += 1
        audit.append(f"torque_pricing_margin_{pricing_hit[0]}")
    return min(score, 3), audit


def _saturation_penalty(
    packet: FilingPacket, filing_delta: int
) -> tuple[int, list[str]]:
    penalty = 0
    audit: list[str] = []
    if packet.ticker in INCUMBENT_LEADERS:
        penalty -= 3
        audit.append("saturation_incumbent_leader")
    if filing_delta <= 1:
        penalty -= 1
        audit.append("saturation_low_delta")
    leadership_hit = _find_section_hit(
        packet,
        terms=LEADERSHIP_TERMS,
        labels=["business", "mda"],
        include_risk=False,
    )
    if leadership_hit:
        penalty -= 1
        audit.append(f"saturation_leadership_claim_{leadership_hit[0]}")
    return penalty, audit


def _false_promise_penalty(packet: FilingPacket) -> tuple[int, list[str]]:
    penalty = 0
    audit: list[str] = []
    for name, terms in [
        ("financing", FINANCING_DEPENDENCE_TERMS),
        ("delay", DELAY_TERMS),
        ("pressure", PRESSURE_TERMS),
        ("regulatory", REGULATORY_TERMS),
        ("concentration", CONCENTRATION_TERMS),
    ]:
        hit = _find_section_hit(packet, terms=terms, labels=["risk", "mda", "business"])
        if hit:
            penalty -= 1
            audit.append(f"penalty_{name}_{hit[0]}")
    return penalty, audit


def _archetype(packet: FilingPacket, wave_torque: int) -> str:
    if wave_torque >= 2:
        return "Torque Bottleneck"
    return "Expansion Bridge"


def _score_packet(
    packet: FilingPacket, prior_packet: FilingPacket | None
) -> dict[str, int | str]:
    _assert_scoreable(packet, prior_packet)
    wave_exposure, wave_exposure_audit = _wave_exposure(packet)
    asymmetric_upside, asymmetric_upside_audit = _asymmetric_upside(packet)
    fundable_scaling, fundable_scaling_audit = _fundable_scaling(packet)
    filing_delta = _filing_delta(packet, prior_packet)
    wave_torque, wave_torque_audit = _wave_torque(packet)
    saturation_penalty, saturation_penalty_audit = _saturation_penalty(
        packet, filing_delta
    )
    false_promise_penalty, false_promise_penalty_audit = _false_promise_penalty(packet)
    venture_score = (
        wave_exposure
        + asymmetric_upside
        + fundable_scaling
        + filing_delta
        + wave_torque
        + saturation_penalty
        + false_promise_penalty
    )
    return {
        "venture_score": venture_score,
        "archetype_path": _archetype(packet, wave_torque),
        "wave_exposure": wave_exposure,
        "wave_exposure_audit": _audit_text(wave_exposure_audit),
        "asymmetric_upside": asymmetric_upside,
        "asymmetric_upside_audit": _audit_text(asymmetric_upside_audit),
        "fundable_scaling": fundable_scaling,
        "fundable_scaling_audit": _audit_text(fundable_scaling_audit),
        "filing_delta": filing_delta,
        "wave_torque_operating_leverage": wave_torque,
        "wave_torque_operating_leverage_audit": _audit_text(wave_torque_audit),
        "incumbent_saturation_penalty": saturation_penalty,
        "incumbent_saturation_penalty_audit": _audit_text(saturation_penalty_audit),
        "false_promise_penalty": false_promise_penalty,
        "false_promise_penalty_audit": _audit_text(false_promise_penalty_audit),
    }


def _output_ticker(ticker: str) -> str:
    return "LTE" if ticker.upper() == "LITE" else ticker.upper()


def _next_trading_day(date_str: str) -> str:
    current = date.fromisoformat(date_str) + timedelta(days=1)
    while current.weekday() >= 5 or current in _market_holidays(current.year):
        current += timedelta(days=1)
    return current.isoformat()


def _winner(rows: list[dict[str, str]]) -> str:
    active_rows = [
        row
        for row in rows
        if row["active"] == "1" and str(row["venture_score"]).strip()
    ]
    if not active_rows:
        return ""

    def key(row: dict[str, str]):
        return (
            int(row["venture_score"]),
            int(row["wave_exposure"]),
            int(row["wave_torque_operating_leverage"]),
            int(row["asymmetric_upside"]),
            int(row["filing_delta"]),
            int(row["incumbent_saturation_penalty"]),
        )

    return max(active_rows, key=key)["ticker"]


def build_rows(
    tickers: list[str] | None = None,
    *,
    extraction_mode: str = "packet",
) -> list[dict[str, str]]:
    active_tickers = [ticker.upper() for ticker in (tickers or DEFAULT_UNIVERSE)]
    packets_by_ticker = _load_packets(active_tickers, extraction_mode=extraction_mode)
    events = sorted(
        {packet.filed for packets in packets_by_ticker.values() for packet in packets}
    )
    latest: dict[str, FilingPacket] = {}
    prior_by_current: dict[tuple[str, str], FilingPacket | None] = {}
    for ticker, packets in packets_by_ticker.items():
        prior: FilingPacket | None = None
        for packet in packets:
            prior_by_current[(ticker, packet.filed)] = prior
            prior = packet

    rows: list[dict[str, str]] = []
    for event in events:
        for ticker in active_tickers:
            for packet in packets_by_ticker[ticker]:
                if packet.filed <= event:
                    latest[ticker] = packet
            packet = latest.get(ticker)
            if packet is None:
                rows.append(
                    {
                        "quarter": event,
                        "ticker": _output_ticker(ticker),
                        "active": "0",
                        "buy": "0",
                        "earnings_date": "",
                        "filing_date": "",
                        "tradable_date": "",
                        "source_mode": extraction_mode,
                        "venture_score": "",
                        "archetype_path": "",
                        "wave_exposure": "",
                        "wave_exposure_audit": "",
                        "asymmetric_upside": "",
                        "asymmetric_upside_audit": "",
                        "fundable_scaling": "",
                        "fundable_scaling_audit": "",
                        "filing_delta": "",
                        "wave_torque_operating_leverage": "",
                        "wave_torque_operating_leverage_audit": "",
                        "incumbent_saturation_penalty": "",
                        "incumbent_saturation_penalty_audit": "",
                        "false_promise_penalty": "",
                        "false_promise_penalty_audit": "",
                        "notes": f"inactive before first {ticker} filing",
                    }
                )
                continue
            try:
                score = _score_packet(packet, prior_by_current[(ticker, packet.filed)])
            except ValueError as exc:
                rows.append(
                    {
                        "quarter": event,
                        "ticker": _output_ticker(ticker),
                        "active": "1",
                        "buy": "0",
                        "earnings_date": "",
                        "filing_date": packet.filed,
                        "tradable_date": _next_trading_day(packet.filed),
                        "source_mode": packet.source_mode,
                        "venture_score": "",
                        "archetype_path": "",
                        "wave_exposure": "",
                        "wave_exposure_audit": "",
                        "asymmetric_upside": "",
                        "asymmetric_upside_audit": "",
                        "fundable_scaling": "",
                        "fundable_scaling_audit": "",
                        "filing_delta": "",
                        "wave_torque_operating_leverage": "",
                        "wave_torque_operating_leverage_audit": "",
                        "incumbent_saturation_penalty": "",
                        "incumbent_saturation_penalty_audit": "",
                        "false_promise_penalty": "",
                        "false_promise_penalty_audit": "",
                        "notes": f"unscored incomplete filing {exc}",
                    }
                )
                continue
            rows.append(
                {
                    "quarter": event,
                    "ticker": _output_ticker(ticker),
                    "active": "1",
                    "buy": "0",
                    "earnings_date": "",
                    "filing_date": packet.filed,
                    "tradable_date": _next_trading_day(packet.filed),
                    "source_mode": packet.source_mode,
                    "venture_score": str(score["venture_score"]),
                    "archetype_path": str(score["archetype_path"]),
                    "wave_exposure": str(score["wave_exposure"]),
                    "wave_exposure_audit": str(score["wave_exposure_audit"]),
                    "asymmetric_upside": str(score["asymmetric_upside"]),
                    "asymmetric_upside_audit": str(score["asymmetric_upside_audit"]),
                    "fundable_scaling": str(score["fundable_scaling"]),
                    "fundable_scaling_audit": str(score["fundable_scaling_audit"]),
                    "filing_delta": str(score["filing_delta"]),
                    "wave_torque_operating_leverage": str(
                        score["wave_torque_operating_leverage"]
                    ),
                    "wave_torque_operating_leverage_audit": str(
                        score["wave_torque_operating_leverage_audit"]
                    ),
                    "incumbent_saturation_penalty": str(
                        score["incumbent_saturation_penalty"]
                    ),
                    "incumbent_saturation_penalty_audit": str(
                        score["incumbent_saturation_penalty_audit"]
                    ),
                    "false_promise_penalty": str(score["false_promise_penalty"]),
                    "false_promise_penalty_audit": str(
                        score["false_promise_penalty_audit"]
                    ),
                    "notes": f"active filing {packet.filed} {packet.form}",
                }
            )

    by_quarter: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_quarter.setdefault(row["quarter"], []).append(row)
    for _quarter, quarter_rows in by_quarter.items():
        winner = _winner(quarter_rows)
        if not winner:
            continue
        for row in quarter_rows:
            row["buy"] = "1" if row["ticker"] == winner else "0"
    return rows


def write_source_csv(
    rows: list[dict[str, str]], output: Path = DEFAULT_SOURCE_OUTPUT
) -> None:
    fieldnames = [
        "quarter",
        "ticker",
        "active",
        "buy",
        "earnings_date",
        "filing_date",
        "tradable_date",
        "source_mode",
        "venture_score",
        "archetype_path",
        "wave_exposure",
        "wave_exposure_audit",
        "asymmetric_upside",
        "asymmetric_upside_audit",
        "fundable_scaling",
        "fundable_scaling_audit",
        "filing_delta",
        "wave_torque_operating_leverage",
        "wave_torque_operating_leverage_audit",
        "incumbent_saturation_penalty",
        "incumbent_saturation_penalty_audit",
        "false_promise_penalty",
        "false_promise_penalty_audit",
        "notes",
    ]
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tickers",
        default=",".join(DEFAULT_UNIVERSE),
        help="Comma-separated ticker universe, e.g. BE,LITE,NVDA,SNDK,AAOI",
    )
    parser.add_argument(
        "--source-output",
        default=str(DEFAULT_SOURCE_OUTPUT),
        help="Path to write the quarter-level venture score source CSV",
    )
    parser.add_argument(
        "--extraction-mode",
        choices=["packet", "edgartools"],
        default="packet",
        help="Use cached packet sections or refresh extraction via edgartools helpers.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    tickers = [
        item.strip().upper() for item in str(args.tickers).split(",") if item.strip()
    ]
    output = Path(str(args.source_output))
    rows = build_rows(tickers, extraction_mode=str(args.extraction_mode))
    write_source_csv(rows, output)
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
