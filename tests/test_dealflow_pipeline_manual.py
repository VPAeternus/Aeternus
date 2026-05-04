from tradingagents.dealflow.pipeline import DealFlowPipeline


def test_synthesize_manual_candidate_uses_sector_baseline_for_known_symbol():
    pipeline = DealFlowPipeline(config={})
    candidate = pipeline._synthesize_manual_candidate("TSLA", "MOMENTUM")  # pylint: disable=protected-access

    assert candidate["symbol"] == "TSLA"
    assert candidate["asset_class"] == "Equity"
    assert candidate["sector"] == "Consumer Discretionary"
    assert candidate["lane"] == "MOMENTUM"


def test_synthesize_manual_candidate_uses_unclassified_for_unknown_symbol():
    pipeline = DealFlowPipeline(config={})
    candidate = pipeline._synthesize_manual_candidate("ZZZZ", "CORE")  # pylint: disable=protected-access

    assert candidate["symbol"] == "ZZZZ"
    assert candidate["asset_class"] == "Equity"
    assert candidate["sector"] == "Unclassified Equity"
    assert candidate["lane"] == "CORE"
