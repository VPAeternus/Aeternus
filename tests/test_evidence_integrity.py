import pytest


def _candidate(
    symbol: str,
    *,
    status: str = "ACTIVE",
    active_families: int = 3,
    evidence_count: int = 6,
    freshness_hours: float = 8.0,
    asymmetry_score: float = 72.0,
    momentum_score: float = 68.0,
    subscores: dict | None = None,
) -> dict:
    return {
        "symbol": symbol,
        "status": status,
        "active_families": active_families,
        "evidence_count": evidence_count,
        "freshness_hours": freshness_hours,
        "asymmetry_score": asymmetry_score,
        "momentum_score": momentum_score,
        "subscores": subscores or {},
    }


def _signal(
    symbol: str,
    family: str,
    *,
    raw_score: float,
    source_status: str = "OK",
    evidence_count: int = 1,
    freshness_hours: float = 6.0,
) -> dict:
    return {
        "symbol": symbol,
        "signal_family": family,
        "raw_score": raw_score,
        "source_status": source_status,
        "evidence_count": evidence_count,
        "freshness_hours": freshness_hours,
        "source_name": family,
    }


def _health(connector: str, families: list[str], status: str) -> dict:
    return {
        "connector": connector,
        "status": status,
        "signal_families": families,
        "status_counts": {"OK": 0, "NO_DATA": 0, "ERROR": 0, "NOT_CONFIGURED": 0},
    }


def test_build_evidence_integrity_report_classifies_confirmed():
    from tradingagents.dealflow.evidence_integrity import build_evidence_integrity_report

    report = build_evidence_integrity_report(
        candidates=[
            _candidate("AAPL", status="ACTIVE", active_families=4, evidence_count=7, freshness_hours=4.0),
        ],
        signals=[
            _signal("AAPL", "price_momentum", raw_score=78.0),
            _signal("AAPL", "news_catalyst", raw_score=70.0),
            _signal("AAPL", "macro_regime_fit", raw_score=62.0),
            _signal("AAPL", "smart_money", raw_score=64.0),
        ],
        connector_health=[],
        rule_snapshot={"min_signal_families": 3, "min_evidence_count": 5},
    )

    record = report["candidate_records"][0]
    assert record["integrity_class"] == "CONFIRMED"
    assert report["class_counts"]["CONFIRMED"] == 1


def test_build_evidence_integrity_report_classifies_sparse_but_interesting():
    from tradingagents.dealflow.evidence_integrity import build_evidence_integrity_report

    report = build_evidence_integrity_report(
        candidates=[
            _candidate("PLTR", status="LOW_DATA", active_families=1, evidence_count=2, freshness_hours=6.0, asymmetry_score=84.0),
        ],
        signals=[
            _signal("PLTR", "price_momentum", raw_score=91.0),
        ],
        connector_health=[],
        rule_snapshot={"min_signal_families": 3, "min_evidence_count": 5},
    )

    record = report["candidate_records"][0]
    assert record["integrity_class"] == "SPARSE_BUT_INTERESTING"
    assert "price_momentum" in record["strong_families"]


def test_build_evidence_integrity_report_classifies_data_degraded():
    from tradingagents.dealflow.evidence_integrity import build_evidence_integrity_report

    report = build_evidence_integrity_report(
        candidates=[
            _candidate("AMD", status="LOW_DATA", active_families=1, evidence_count=1, freshness_hours=200.0, asymmetry_score=42.0),
        ],
        signals=[
            _signal("AMD", "price_momentum", raw_score=66.0),
            _signal("AMD", "news_catalyst", raw_score=0.0, source_status="ERROR"),
            _signal("AMD", "smart_money", raw_score=0.0, source_status="NOT_CONFIGURED"),
        ],
        connector_health=[
            _health("social_news", ["news_catalyst"], "ERROR"),
            _health("smart_money", ["smart_money"], "NOT_CONFIGURED"),
        ],
        rule_snapshot={"min_signal_families": 3, "min_evidence_count": 5},
    )

    record = report["candidate_records"][0]
    assert record["integrity_class"] == "DATA_DEGRADED"
    assert sorted(record["degraded_families"]) == ["news_catalyst", "smart_money"]


def test_build_evidence_integrity_report_classifies_low_signal():
    from tradingagents.dealflow.evidence_integrity import build_evidence_integrity_report

    report = build_evidence_integrity_report(
        candidates=[
            _candidate("VZ", status="LOW_DATA", active_families=1, evidence_count=1, freshness_hours=72.0, asymmetry_score=28.0),
        ],
        signals=[
            _signal("VZ", "price_momentum", raw_score=48.0),
        ],
        connector_health=[],
        rule_snapshot={"min_signal_families": 3, "min_evidence_count": 5},
    )

    record = report["candidate_records"][0]
    assert record["integrity_class"] == "LOW_SIGNAL"
    assert report["class_counts"]["LOW_SIGNAL"] == 1


def test_build_evidence_integrity_scorecards_compare_peers_and_step2_baseline():
    from tradingagents.dealflow.evidence_integrity import build_evidence_integrity_scorecards

    result = build_evidence_integrity_scorecards(
        evidence_integrity={
            "candidate_records": [
                {"symbol": "AAPL", "integrity_class": "CONFIRMED"},
                {"symbol": "PLTR", "integrity_class": "SPARSE_BUT_INTERESTING"},
                {"symbol": "AMD", "integrity_class": "DATA_DEGRADED"},
                {"symbol": "VZ", "integrity_class": "LOW_SIGNAL"},
            ]
        },
        step2_symbols=["AAPL", "PLTR", "AMD", "VZ"],
        shortlist_symbols=["AAPL", "PLTR"],
        deep_selection_symbols=["PLTR"],
        forward_returns_by_horizon={
            "5d": {"AAPL": 0.02, "PLTR": 0.06, "AMD": 0.01, "VZ": -0.01},
            "20d": {"AAPL": 0.05, "PLTR": 0.12, "AMD": 0.03, "VZ": 0.0},
            "3m": {"AAPL": 0.08, "PLTR": 0.20, "AMD": 0.04, "VZ": 0.01},
        },
        benchmark_returns_by_horizon={"5d": 0.01, "20d": 0.04, "3m": 0.05},
    )

    sparse = result["cohorts"]["SPARSE_BUT_INTERESTING"]
    assert sparse["count"] == 1
    assert sparse["mean_return_5d"] == 0.06
    assert sparse["edge_vs_benchmark_20d"] == 0.08
    assert sparse["shortlist_conversion"] == 1.0
    assert sparse["deep_selection_conversion"] == 1.0

    baseline = result["step2_baseline"]
    assert baseline["count"] == 4
    assert baseline["mean_return_5d"] == 0.02
    assert baseline["deep_selection_conversion"] == 0.25

    vs_baseline = result["comparisons"]["vs_step2_baseline"]["SPARSE_BUT_INTERESTING"]
    assert vs_baseline["mean_return_5d_delta"] == 0.04
    assert vs_baseline["shortlist_conversion_delta"] == 0.5

    vs_peers = result["comparisons"]["vs_other_cohorts"]["SPARSE_BUT_INTERESTING"]
    assert vs_peers["mean_return_20d_delta"] == 0.0933
    assert vs_peers["deep_selection_conversion_delta"] == 1.0
