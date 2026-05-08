import sys
from pathlib import Path

FUNDAMENTAL_ROOT = Path(__file__).resolve().parents[1] / "tradingagents" / "research" / "fundamental"
if str(FUNDAMENTAL_ROOT) not in sys.path:
    sys.path.insert(0, str(FUNDAMENTAL_ROOT))

from src.pipeline.run_on_new_filing import build_signal_tables


def _row(ticker="RMX", quarter="2026Q1", **extra):
    row = {
        "ticker": ticker,
        "quarter": quarter,
        "tradable_date": "2026-05-01",
        "entry_open": "20",
        "revenue_bucket": "$1B-$10B",
        "pre_llm_fundamental_score": "-1",
        "pre_llm_fundamental_bucket": "weak",
        "entry_qoq_pct": "25",
        "theme_tailwind_score": "5",
    }
    row.update(extra)
    return row


def test_rm_priority_candidate_receives_market_repricing_score_in_live_signal_tables():
    signal_rows, _, _ = build_signal_tables([_row()], as_of="2026-05-08")

    row = signal_rows[0]
    assert bool(row["rm2_weak_acceleration"])
    assert bool(row["repricing_momentum_priority"])
    assert row["market_repricing_score"] == 16
    assert row["entry_raw_score"] >= 16


def test_rm4_persistent_repricing_uses_prior_entry_qoq_pct_when_present():
    signal_rows, _, _ = build_signal_tables([_row(prior_entry_qoq_pct="22")], as_of="2026-05-08")

    row = signal_rows[0]
    assert bool(row["rm4_persistent_repricing_wave"])
    assert bool(row["repricing_momentum_priority"])
    assert row["market_repricing_score"] == 20
    assert row["repricing_confirmed"] == 1
