from tradingagents.research.fundamental.src.daily_run.eligibility import assign_daily_tiers, build_llm_eligibility, build_tier_filtered_llm_packets


def _row(ticker, entry_open, score=3, revenue_bucket="$500M-$1B"):
    return {"ticker": ticker, "quarter": "2026Q2", "entry_open": str(entry_open), "revenue_bucket": revenue_bucket, "pre_llm_fundamental_score": str(score), "pre_llm_fundamental_bucket": "good"}


def test_assign_daily_tiers_assigns_tier_zero_to_low_price_broad_candidate():
    rows, summary = assign_daily_tiers([_row("AAA", 20)])
    assert rows[0]["tier_0_bucket"]
    assert not rows[0].get("tier_1_bucket")
    assert summary["tier_0_count"] == 1


def test_llm_eligibility_excludes_tier_zero_and_requires_cached_ready_with_earnings_8k():
    tiered, _ = assign_daily_tiers([_row("T0", 20), _row("T1", 12), _row("MISS", 8), _row("NO8K", 8)])
    coverage = [
        {"ticker": "T0", "quarter": "2026Q2", "coverage_status": "CACHED_READY", "earnings_8k_accession": "1", "earnings_8k_primary_document": "8k.htm"},
        {"ticker": "T1", "quarter": "2026Q2", "coverage_status": "CACHED_READY", "earnings_8k_accession": "1", "earnings_8k_primary_document": "8k.htm"},
        {"ticker": "MISS", "quarter": "2026Q2", "coverage_status": "BLOCKED_METADATA_OR_ISSUER_REALITY", "earnings_8k_accession": "1", "earnings_8k_primary_document": "8k.htm"},
        {"ticker": "NO8K", "quarter": "2026Q2", "coverage_status": "CACHED_READY", "periodic_accession": "1", "periodic_primary_document": "10q.htm"},
    ]
    eligible, quarantine, summary = build_llm_eligibility(tiered, coverage)
    assert [row["ticker"] for row in eligible] == ["T1"]
    assert {row["ticker"] for row in quarantine} == {"T0", "MISS", "NO8K"}
    assert next(row for row in quarantine if row["ticker"] == "NO8K")["llm_quarantine_reason"] == "missing_earnings_8k_or_press_release"
    assert summary["llm_eligible_count"] == 1


def test_build_tier_filtered_packets_never_builds_for_full_universe_or_tier_zero():
    candidates = [{"ticker": "T1", "quarter": "2026Q2", "tier_1_bucket": "Tier 1 - Balanced priority feed"}]
    docs = [
        {"ticker": "T1", "quarter": "2026Q2", "document_type": "periodic_10q_10k", "clean_text": "Quarterly filing fallback."},
        {"ticker": "T1", "quarter": "2026Q2", "document_type": "earnings_exhibit", "clean_text": "Management raised guidance."},
    ]
    packets, quarantine, summary = build_tier_filtered_llm_packets(candidates, docs, broad_universe_count=3)
    assert quarantine == []
    assert len(packets) == 1
    assert packets[0]["sample_id"] == "T1_2026Q2"
    assert packets[0]["evidence_snippets"] == ["Management raised guidance."]
    assert [ref["document_type"] for ref in packets[0]["document_refs"]] == ["earnings_exhibit"]
    assert summary["packet_count"] == 1
    assert summary["eligible_count"] == 1
    assert summary["broad_universe_count"] == 3


def test_build_tier_filtered_packets_quarantines_empty_evidence():
    candidates = [{"ticker": "T1", "quarter": "2026Q2", "tier_1_bucket": "Tier 1 - Balanced priority feed"}]
    packets, quarantine, summary = build_tier_filtered_llm_packets(candidates, [], broad_universe_count=3)
    assert packets == []
    assert [row["ticker"] for row in quarantine] == ["T1"]
    assert quarantine[0]["llm_quarantine_reason"] == "empty_evidence_docs"
    assert summary["packet_count"] == 0
    assert summary["empty_evidence_count"] == 1
