from tradingagents.research.fundamental.src.features.llm_packets import build_llm_packets


def test_llm_packets_exclude_quarterly_filing_from_main_extraction():
    candidates = [{"ticker": "AAA", "quarter": "2026Q2", "tier_1_bucket": "Tier 1"}]
    docs = [
        {"ticker": "AAA", "quarter": "2026Q2", "document_type": "periodic_10q_10k", "clean_text": "quarterly filing text"},
        {"ticker": "AAA", "quarter": "2026Q2", "document_type": "primary_8k", "clean_text": "primary 8-k text"},
        {"ticker": "AAA", "quarter": "2026Q2", "document_type": "earnings_exhibit", "clean_text": "press release text"},
    ]

    packets = build_llm_packets(candidates, docs)

    assert len(packets) == 1
    assert packets[0]["evidence_snippets"] == ["press release text", "primary 8-k text"]
    assert [ref["document_type"] for ref in packets[0]["document_refs"]] == ["earnings_exhibit", "primary_8k"]


def test_llm_packets_can_opt_into_quarterly_filing_for_separate_workflows():
    candidates = [{"ticker": "AAA", "quarter": "2026Q2", "tier_1_bucket": "Tier 1"}]
    docs = [{"ticker": "AAA", "quarter": "2026Q2", "document_type": "periodic_10q_10k", "clean_text": "quarterly filing text"}]

    packets = build_llm_packets(candidates, docs, allowed_document_types={"periodic_10q_10k"})

    assert packets[0]["evidence_snippets"] == ["quarterly filing text"]
    assert packets[0]["document_refs"][0]["document_type"] == "periodic_10q_10k"
