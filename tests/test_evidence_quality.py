from tradingagents.dealflow.evidence_quality import build_x_feed_evidence_quality


def test_evidence_quality_rewards_sources_and_penalizes_no_source(tmp_path):
    base = tmp_path / "x_feed"
    day = base / "2026-05-05"
    day.mkdir(parents=True)
    merged = {
        "AAA": {
            "ticker": "AAA",
            "sentiment": 0.6,
            "timestamp": "2026-05-05T12:00:00Z",
            "source_quality": "cited",
            "no_source_found": False,
            "theme_links": ["ai"],
            "evidence": [
                {"accounts_cited": ["@a", "@b"], "source_pass_type": "sector", "sentiment": 0.6, "timestamp": "2026-05-05T12:00:00Z", "catalyst": "fresh cited item"},
                {"accounts_cited": ["@c"], "source_pass_type": "macro", "sentiment": 0.5, "timestamp": "2026-05-05T13:00:00Z", "catalyst": "fresh cited item"},
            ],
        },
        "BBB": {"ticker": "BBB", "sentiment": 0.5, "no_source_found": True, "theme_links": ["ai"], "evidence": []},
    }
    graph = {
        "tickers": {
            "AAA": {"theme_emergence_score": 90, "evidence_count": 2, "theme_links": ["ai"]},
            "BBB": {"theme_emergence_score": 30, "evidence_count": 1, "theme_links": ["ai"]},
        },
        "themes": {"ai": {"tickers": ["AAA", "BBB"]}},
    }
    out = build_x_feed_evidence_quality(as_of_date="2026-05-05", merged=merged, graph=graph, base_dir=base)
    assert out["AAA"]["evidence_quality_score"] > out["BBB"]["evidence_quality_score"]
    assert out["BBB"]["quality_components"]["source_integrity"] == 0.0


def test_evidence_quality_handles_missing_fields():
    out = build_x_feed_evidence_quality(as_of_date="2026-05-05", merged={"AAA": {}} , graph={})
    assert 0.0 <= out["AAA"]["evidence_quality_score"] <= 100.0
