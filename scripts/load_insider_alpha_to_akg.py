"""
Bulk-load insider Alpha Scores into AKG.

Run this once after backtest_insider_alpha.py completes.

Usage: python3 scripts/load_insider_alpha_to_akg.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from pathlib import Path

from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph

SCORES_PATH = Path("eval_results/insider_alpha_scores.json")


def main():
    if not SCORES_PATH.exists():
        print(f"ERROR: {SCORES_PATH} not found. Run backtest_insider_alpha.py first.")
        sys.exit(1)

    payload = json.loads(SCORES_PATH.read_text())
    scores = payload.get("scores", {})
    computed_date = payload.get("computed_date", "unknown")

    print(f"Loading {len(scores)} ticker Alpha Scores (computed {computed_date}) into AKG...")

    akg = AeternusKnowledgeGraph()
    loaded = 0
    skipped = 0

    for ticker, data in scores.items():
        try:
            akg.set_insider_alpha(ticker, data)
            loaded += 1
        except Exception as e:
            print(f"  WARN: {ticker} failed — {e}")
            skipped += 1

    print(f"Done. {loaded} loaded, {skipped} skipped.")

    # Spot-check a few known names
    for check in ["BRK-B", "OXY", "COIN", "BAC"]:
        result = akg.get_insider_alpha(check)
        if result:
            print(f"  {check}: alpha={result['alpha_score']:.1f}, "
                  f"win_rate={result['win_rate_30d']:.0%}, "
                  f"buys={result['buy_count']}")


if __name__ == "__main__":
    main()
