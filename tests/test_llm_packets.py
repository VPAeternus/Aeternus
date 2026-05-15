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


def test_llm_packets_attach_prior_llm_extract_when_available():
    candidates = [
        {
            "ticker": "AAA",
            "quarter": "2026Q2",
            "tier_1_bucket": "Tier 1",
            "prior_llm_causal_change": "3",
            "prior_llm_narrative_delta_bucket": "constructive",
            "prior_llm_post_llm_candidate_flag": "1",
        }
    ]
    docs = [{"ticker": "AAA", "quarter": "2026Q2", "document_type": "earnings_exhibit", "clean_text": "press release text"}]

    packets = build_llm_packets(candidates, docs)

    assert packets[0]["prior_llm_extract"] == {
        "causal_change": "3",
        "narrative_delta_bucket": "constructive",
        "post_llm_candidate_flag": "1",
    }
