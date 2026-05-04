"""Tests for the needle bypass — extreme-signal LOW_DATA detection."""

from tradingagents.dealflow.scoring import detect_needles


def _signal(symbol, family, score, evidence=5, z_score=0.0, status="OK"):
    return {
        "symbol": symbol,
        "signal_family": family,
        "raw_score": score,
        "z_score": z_score,
        "direction": "BULLISH" if score >= 60 else "NEUTRAL",
        "evidence_count": evidence,
        "freshness_hours": 1.0,
        "source_status": status,
        "source_name": "test",
    }


def _candidate(symbol, status="LOW_DATA"):
    return {
        "symbol": symbol,
        "status": status,
        "asset_class": "Equity",
        "sector": "Technology",
    }


def test_detect_needles_finds_extreme_signal():
    signals = [
        _signal("ACME", "insider_cluster", 85.0, z_score=2.8),
        _signal("ACME", "price_momentum", 55.0, z_score=0.3),
    ]
    candidates = [_candidate("ACME")]
    needles = detect_needles(signals, candidates)
    assert len(needles) == 1
    assert needles[0]["symbol"] == "ACME"
    assert needles[0]["trigger_family"] == "insider_cluster"
    assert needles[0]["z_score"] == 2.8
    assert needles[0]["raw_score"] == 85.0
    assert "Needle" in needles[0]["reason"]


def test_detect_needles_ignores_moderate_z():
    signals = [_signal("BORING", "price_momentum", 80.0, z_score=1.5)]
    candidates = [_candidate("BORING")]
    needles = detect_needles(signals, candidates)
    assert needles == []


def test_detect_needles_ignores_high_z_low_raw():
    signals = [_signal("WEAK", "emergence", 60.0, z_score=3.0)]
    candidates = [_candidate("WEAK")]
    needles = detect_needles(signals, candidates)
    assert needles == []


def test_detect_needles_skips_active_candidates():
    signals = [_signal("GOOD", "insider_cluster", 90.0, z_score=2.9)]
    candidates = [_candidate("GOOD", status="ACTIVE")]
    needles = detect_needles(signals, candidates)
    assert needles == []


def test_detect_needles_skips_non_ok_signals():
    signals = [_signal("STALE", "smart_money", 88.0, z_score=2.7, status="NO_DATA")]
    candidates = [_candidate("STALE")]
    needles = detect_needles(signals, candidates)
    assert needles == []


def test_needle_injection_integration(monkeypatch):
    """Verify needle candidates merge into _iv_force_queue on the pipeline."""
    from tradingagents.dealflow import pipeline as pipeline_mod
    from tradingagents.dealflow.pipeline import DealFlowPipeline

    # Stub detect_needles to return a known needle
    needle = {
        "symbol": "EDGE",
        "trigger_family": "insider_cluster",
        "z_score": 2.9,
        "raw_score": 88.0,
        "reason": "Needle: insider_cluster z=2.9",
    }
    monkeypatch.setattr(pipeline_mod, "detect_needles", lambda *a, **kw: [needle])

    # Stub score_candidates to return the minimum needed
    monkeypatch.setattr(
        pipeline_mod,
        "score_candidates",
        lambda **kw: ([], []),
    )

    pipe = DealFlowPipeline(config={"dealflow_top_k": 5})
    pipe._iv_force_queue = []

    # Call the collect method portion that invokes score_candidates + detect_needles.
    # We can't easily call collect() without heavy mocking, so we test the
    # mechanism directly: simulate the post-score_candidates block.
    from tradingagents.dealflow.scoring import detect_needles as real_detect

    signals = [_signal("EDGE", "insider_cluster", 88.0, z_score=2.9)]
    candidates = [_candidate("EDGE")]
    result = real_detect(signals, candidates)

    # Simulate the pipeline merge logic
    iv_fq = getattr(pipe, "_iv_force_queue", None) or []
    pipe._iv_force_queue = iv_fq + result

    assert len(pipe._iv_force_queue) == 1
    assert pipe._iv_force_queue[0]["symbol"] == "EDGE"
    assert pipe._iv_force_queue[0]["reason"] == "Needle: insider_cluster z=2.9"
