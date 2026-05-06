import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Growth"))

import build_pre_llm_fundamental_score as scorer  # noqa: E402


class PreLlmFundamentalScoreTests(unittest.TestCase):
    def test_tier_bucket_marks_broad_right_tail_scouting_universe(self):
        row = {
            "revenue_bucket": "$2B-$10B",
            "pre_llm_fundamental_bucket": "weak",
        }
        returns = {"entry_open": "24.990000"}

        self.assertEqual(
            scorer.tier_bucket(row, returns),
            "Tier 0 - Broad right-tail scouting universe",
        )

    def test_tier_bucket_rejects_large_price_or_not_scored(self):
        row = {
            "revenue_bucket": "$100M-$500M",
            "pre_llm_fundamental_bucket": "not_scored",
        }
        returns = {"entry_open": "10.000000"}

        self.assertEqual(scorer.tier_bucket(row, returns), "")

        row["pre_llm_fundamental_bucket"] = "strong"
        returns["entry_open"] = "25.000000"
        self.assertEqual(scorer.tier_bucket(row, returns), "")

    def test_tier_1_bucket_marks_balanced_priority_feed(self):
        row = {
            "revenue_bucket": "$2B-$10B",
            "pre_llm_fundamental_bucket": "mixed",
        }
        returns = {"entry_open": "14.990000"}

        self.assertEqual(
            scorer.tier_1_bucket(row, returns),
            "Tier 1 - Balanced priority feed",
        )

    def test_tier_1_bucket_rejects_fifteen_dollar_entry(self):
        row = {
            "revenue_bucket": "$2B-$10B",
            "pre_llm_fundamental_bucket": "mixed",
        }
        returns = {"entry_open": "15.000000"}

        self.assertEqual(scorer.tier_1_bucket(row, returns), "")

    def test_tier_2_bucket_marks_high_priority_compact_feed(self):
        row = {
            "revenue_bucket": "$2B-$10B",
            "pre_llm_fundamental_bucket": "good",
        }
        returns = {"entry_open": "9.990000"}

        self.assertEqual(
            scorer.tier_2_bucket(row, returns),
            "Tier 2 - High-priority compact feed",
        )

    def test_tier_2_bucket_rejects_ten_dollar_entry(self):
        row = {
            "revenue_bucket": "$2B-$10B",
            "pre_llm_fundamental_bucket": "good",
        }
        returns = {"entry_open": "10.000000"}

        self.assertEqual(scorer.tier_2_bucket(row, returns), "")

    def test_tier_3_bucket_marks_revised_dislocation_feed(self):
        row = {
            "revenue_bucket": "$2B-$10B",
            "pre_llm_fundamental_bucket": "mixed",
            "pre_llm_fundamental_score": "0",
        }
        returns = {"entry_open": "14.990000"}

        self.assertEqual(
            scorer.tier_3_bucket(row, returns),
            "Tier 3 - Revised dislocation feed",
        )

    def test_tier_3_bucket_rejects_positive_score(self):
        row = {
            "revenue_bucket": "$2B-$10B",
            "pre_llm_fundamental_bucket": "good",
            "pre_llm_fundamental_score": "1",
        }
        returns = {"entry_open": "14.990000"}

        self.assertEqual(scorer.tier_3_bucket(row, returns), "")

    def test_tier_4_bucket_marks_ultra_distressed_tag(self):
        row = {
            "revenue_bucket": "$100M-$500M",
            "pre_llm_fundamental_bucket": "weak",
            "pre_llm_fundamental_score": "-2",
        }
        returns = {"entry_open": "4.990000"}

        self.assertEqual(
            scorer.tier_4_bucket(row, returns),
            "Tier 4 - Ultra-distressed tag, not a production tier",
        )

    def test_tier_4_bucket_allows_positive_scored_names(self):
        row = {
            "revenue_bucket": "$100M-$500M",
            "pre_llm_fundamental_bucket": "strong",
            "pre_llm_fundamental_score": "8",
        }
        returns = {"entry_open": "4.990000"}

        self.assertEqual(
            scorer.tier_4_bucket(row, returns),
            "Tier 4 - Ultra-distressed tag, not a production tier",
        )

    def test_tier_4_bucket_rejects_not_scored_or_over_10b(self):
        row = {
            "revenue_bucket": ">$10B",
            "pre_llm_fundamental_bucket": "strong",
            "pre_llm_fundamental_score": "8",
        }
        returns = {"entry_open": "4.990000"}

        self.assertEqual(scorer.tier_4_bucket(row, returns), "")

        row["revenue_bucket"] = "$100M-$500M"
        row["pre_llm_fundamental_bucket"] = "not_scored"
        self.assertEqual(scorer.tier_4_bucket(row, returns), "")


if __name__ == "__main__":
    unittest.main()
