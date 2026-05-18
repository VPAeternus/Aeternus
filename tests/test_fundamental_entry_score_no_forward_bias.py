from tradingagents.research.fundamental.src.features.scoring import compute_entry_score
from tradingagents.research.fundamental.src.ingest.prices import compute_return_checkpoints


def _base_row():
    return {
        "ticker": "AAA",
        "pre_llm_fundamental_bucket": "strong",
        "revenue_bucket": "$1B-$2B",
        "entry_open": "30",
        "tier_1_bucket": "Tier 1 - Balanced priority feed",
        "pre_llm_fundamental_score": "7",
        "post_llm_candidate_flag": "1",
        "post_llm_high_priority_flag": "1",
        "causal_change": "3",
        "negative_revision_risk": "1",
        "narrative_delta_bucket": "constructive",
        "operating_leverage_quality": "2",
        "durability": "2",
        "market_repricing_score": "8",
        "theme_tailwind_score": "5",
    }


def test_entry_score_ignores_future_return_monitoring_and_rank_labels():
    baseline = compute_entry_score(_base_row())
    injected = compute_entry_score(
        {
            **_base_row(),
            "return_10d_pct": "999",
            "return_20d_pct": "999",
            "return_30d_pct": "999",
            "return_60d_pct": "999",
            "return_90d_pct": "999",
            "current_return_pct": "999",
            "return_since_signal_pct": "999",
            "return_since_purchase_pct": "999",
            "monitoring_score_0_100": "100",
            "active_monitoring_score_0_100": "100",
            "final_rank_score_0_100": "100",
            "rank_score_label": "winner",
            "monitoring_status": "hit",
            "winner_90d_30pct": "1",
            "loser_90d_minus30pct": "0",
        }
    )

    assert injected["entry_raw_score"] == baseline["entry_raw_score"]
    assert injected["entry_score_0_100"] == baseline["entry_score_0_100"]
    assert "return_90d_pct" not in injected["entry_score_inputs"]
    assert "final_rank_score_0_100" not in injected["entry_score_inputs"]
    assert "rank_score_label" not in injected["entry_score_inputs"]
    assert "monitoring_status" not in injected["entry_score_inputs"]
    assert "winner_90d_30pct" not in injected["entry_score_inputs"]


def test_entry_score_populates_legacy_aliases():
    scored = compute_entry_score(_base_row())

    assert scored["base_entry_raw_score"] == scored["entry_raw_score"]
    assert scored["base_entry_score_0_100"] == scored["entry_score_0_100"]
    assert scored["compatibility_alias_source"] == "current_entry_score"


def test_theme_score_ignored_when_theme_source_is_after_decision_date():
    scored = compute_entry_score(
        {
            **_base_row(),
            "theme_tailwind_score": "20",
            "theme_source_available_date": "2026-05-20",
            "decision_date": "2026-05-10",
        }
    )

    assert scored["theme_tailwind_score"] == 0


def test_static_theme_taxonomy_ignored_unless_allowed_for_historical_scoring():
    scored = compute_entry_score(
        {
            **_base_row(),
            "theme_tailwind_score": "20",
            "theme_source_type": "static_taxonomy",
            "theme_score_allowed_for_historical_scoring": "false",
        }
    )

    assert scored["theme_tailwind_score"] == 0


def test_return_labels_use_calendar_day_legacy_default():
    rows = [
        {"ticker": "AAA", "date": "2026-01-02", "open": 100, "close": 100},
        {"ticker": "AAA", "date": "2026-01-13", "open": 109, "close": 110},
        {"ticker": "AAA", "date": "2026-01-22", "open": 119, "close": 120},
        {"ticker": "AAA", "date": "2026-02-02", "open": 129, "close": 130},
        {"ticker": "AAA", "date": "2026-03-03", "open": 159, "close": 160},
        {"ticker": "AAA", "date": "2026-04-02", "open": 189, "close": 190},
    ]

    labels = compute_return_checkpoints(rows, tradable_date="2026-01-02")

    assert labels["return_horizon_type"] == "calendar_days_legacy"
    assert labels["return_exit_date_rule"] == "first_trading_session_on_or_after_entry_date_plus_N_calendar_days"
    assert labels["return_exit_date_10d"] == "2026-01-13"
    assert labels["return_exit_price_10d"] == 110.0
    assert labels["return_10d_pct"] == 10.0
    assert labels["return_exit_date_90d"] == "2026-04-02"
    assert labels["return_90d_pct"] == 90.0
