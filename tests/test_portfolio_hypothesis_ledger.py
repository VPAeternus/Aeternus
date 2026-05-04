import json
from pathlib import Path
from unittest.mock import patch

from tradingagents.dealflow.hypothesis_ledger import ledger_rows_path


def _batch_item(symbol: str, score: float, confidence: int, status: str = "SUCCESS") -> dict:
    return {
        "symbol": symbol,
        "status": status,
        "recommendation": "BUY",
        "aeternus_score": score,
        "confidence": confidence,
        "queue_id": f"2026-03-06-run:{symbol}",
        "lane": "CORE",
        "research_playbook": "compounder",
        "dominant_signal_family": "price_momentum",
    }


def test_build_portfolio_plan_writes_portfolio_inclusion_ledger_row(tmp_path: Path):
    from tradingagents.graph.paper_execution import build_portfolio_plan

    batch_summary = {
        "date": "2026-03-06",
        "run_id": "2026-03-06-run",
        "items": [
            _batch_item("AAPL", 82.0, 5),
            _batch_item("NVDA", 78.0, 4),
            _batch_item("MU", 68.0, 4),
            _batch_item("TSLA", 54.0, 5),
        ],
    }

    alloc_meta = {
        "tiers": {"AAPL": "HIGH", "NVDA": "HIGH"},
        "pre_adj_weights": {"AAPL": 0.12, "NVDA": 0.10},
        "vol_data": {},
        "max_correlations": {},
        "avg_pairwise_correlation": 0.0,
        "effective_positions": 2.0,
    }

    with (
        patch("tradingagents.graph.paper_execution._fetch_reference_price_from_market", return_value=100.0),
        patch("tradingagents.graph.paper_execution._conviction_weights", return_value=([0.12, 0.10], alloc_meta)),
    ):
        plan = build_portfolio_plan(
            batch_summary=batch_summary,
            capital_usd=100000.0,
            max_positions=2,
            min_score=60.0,
            min_confidence=3,
            ledger_base_dir=tmp_path,
        )

    rows = json.loads(ledger_rows_path(base_dir=tmp_path, lane="shared").read_text())
    row = next(entry for entry in rows if entry["stage_id"] == "portfolio_inclusion_cut")

    assert row["kept_count"] == 2
    assert row["dropped_count"] == 2
    assert row["rule_snapshot"]["max_positions"] == 2
    assert row["rule_snapshot"]["min_score"] == 60.0
    assert {order["symbol"] for order in plan["orders"] if order.get("queue_id")} == {"AAPL", "NVDA"}
    assert set(json.loads(Path(row["kept_symbols_path"]).read_text())) == {"AAPL", "NVDA"}
    assert set(json.loads(Path(row["dropped_symbols_path"]).read_text())) == {"MU", "TSLA"}
