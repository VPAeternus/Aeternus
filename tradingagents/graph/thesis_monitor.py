"""Thesis Invalidation Early Warning System.

Derives monitoring claims from entry pillar scores. Checks current deal flow signals
against stored claims. Surfaces WATCH/STRESS/CRITICAL alerts for open positions.

Pure Python — no LLM calls.
"""

# Pillar claim configuration: which pillar scores drive which monitoring claims.
# stress_signal: which current pillar score to check (matches AKG last_{pillar}_score field).
# stress_threshold: if current score < this, the claim is considered stressed.
PILLAR_CLAIM_MAP = {
    "fundamental": {
        "claim": "Strong fundamentals persist (margins, growth, F-Score)",
        "stress_signal": "fundamental",
        "stress_threshold": 45,
    },
    "sentiment": {
        "claim": "Positive market sentiment continues",
        "stress_signal": "sentiment",
        "stress_threshold": 45,
    },
    "macro": {
        "claim": "Favorable macro regime (rates, credit spreads, yield curve)",
        "stress_signal": "macro",
        "stress_threshold": 40,
    },
    "momentum": {
        "claim": "Price momentum intact (RSI, trend, acceleration)",
        "stress_signal": "momentum",
        "stress_threshold": 45,
    },
    "coherence": {
        "claim": "Cross-pillar signals aligned (no internal contradictions)",
        "stress_signal": "coherence",
        "stress_threshold": 40,
    },
}

# Minimum pillar score at entry to generate a monitoring claim (bullish signal threshold).
_CLAIM_ENTRY_THRESHOLD = 60


def derive_thesis_claims(rating: dict) -> list:
    """Derive monitoring claims from entry pillar scores in an AeternusRating dict.

    A pillar generates a claim if its entry score >= 60 (bullish signal at entry).

    Args:
        rating: AeternusRating dict (or any dict) with a "breakdown" key mapping
                pillar name -> score (0-100 scale).

    Returns:
        List of claim dicts, one per qualifying pillar:
        [{"pillar", "claim", "stress_signal", "stress_threshold", "entry_score"}, ...]
    """
    breakdown = rating.get("breakdown", {})
    claims = []
    for pillar, config in PILLAR_CLAIM_MAP.items():
        score = breakdown.get(pillar)
        if score is not None and score >= _CLAIM_ENTRY_THRESHOLD:
            claims.append({
                "pillar": pillar,
                "claim": config["claim"],
                "stress_signal": config["stress_signal"],
                "stress_threshold": config["stress_threshold"],
                "entry_score": score,
            })
    return claims


def record_thesis_entry(ticker: str, rating: dict, akg) -> list:
    """Derive thesis claims from the entry rating and persist them to AKG.

    Args:
        ticker: Stock ticker symbol.
        rating: AeternusRating dict with at minimum a "breakdown" field.
        akg: AeternusKnowledgeGraph instance.

    Returns:
        List of derived claim dicts (same as derive_thesis_claims output).
    """
    claims = derive_thesis_claims(rating)
    entry_date = rating.get("date")
    akg.set_thesis_claims(ticker, claims, entry_date=entry_date)
    return claims


def run_thesis_monitor(open_positions: dict, akg, dry_run: bool = False) -> dict:
    """Check all open positions against their stored thesis claims.

    For each ticker in open_positions:
    1. Retrieves stored thesis claims from AKG.
    2. Skips tickers with no claims (position predates thesis monitor or not yet recorded).
    3. Runs get_thesis_stress_report() to check current pillar scores vs. entry claims.
    4. Collects and classifies alerts by stress level.

    Args:
        open_positions: Dict of {ticker: position_data}. Values are not used directly;
                        only the keys (tickers) are iterated.
        akg: AeternusKnowledgeGraph instance.
        dry_run: If True, performs all checks but does not write back to AKG.
                 Currently a no-op flag reserved for future use.

    Returns:
        {
            "positions_checked": int,
            "positions_with_claims": int,
            "alerts": {
                "CRITICAL": [report, ...],
                "STRESS": [...],
                "WATCH": [...],
                "NONE": [...],
            }
        }
    """
    alerts = {"CRITICAL": [], "STRESS": [], "WATCH": [], "NONE": []}
    positions_checked = 0
    positions_with_claims = 0

    for ticker in open_positions:
        positions_checked += 1
        claims = akg.get_thesis_claims(ticker)
        if not claims:
            continue
        positions_with_claims += 1
        report = akg.get_thesis_stress_report(ticker)
        level = report.get("stress_level", "NONE")
        alerts[level].append(report)

    return {
        "positions_checked": positions_checked,
        "positions_with_claims": positions_with_claims,
        "alerts": alerts,
    }


def format_thesis_monitor_brief(monitor_result: dict) -> str:
    """Format thesis monitor results as a human-readable alert brief.

    Returns an empty string if there are no STRESS or CRITICAL alerts.
    WATCH alerts are included in the output when STRESS or CRITICAL also exist;
    standalone WATCH alerts are also returned to give early visibility.

    Args:
        monitor_result: Dict returned by run_thesis_monitor().

    Returns:
        Formatted multi-line string, or "" if nothing actionable.
    """
    alerts = monitor_result.get("alerts", {})
    critical = alerts.get("CRITICAL", [])
    stress = alerts.get("STRESS", [])
    watch = alerts.get("WATCH", [])

    # Return empty string if nothing above NONE level
    if not critical and not stress and not watch:
        return ""

    lines = ["=== THESIS MONITOR ==="]

    for level, reports in [("CRITICAL", critical), ("STRESS", stress), ("WATCH", watch)]:
        for report in reports:
            ticker = report.get("ticker", "?")
            claims_total = report.get("claims_total", 0)
            claims_stressed = report.get("claims_stressed", 0)
            lines.append(f"{level}: {ticker} — {claims_stressed}/{claims_total} thesis claims stressed")
            for sc in report.get("stressed_claims", []):
                claim_text = sc.get("claim", sc.get("pillar", "?"))
                entry = sc.get("entry_score", "?")
                current = sc.get("current_score", "?")
                threshold = sc.get("stress_threshold", "?")
                lines.append(
                    f"  - {claim_text} -> Entry: {entry}, Current: {current} (below {threshold} threshold)"
                )

    lines.append("=== END THESIS MONITOR ===")
    return "\n".join(lines)
