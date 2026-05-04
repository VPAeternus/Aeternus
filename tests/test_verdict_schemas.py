"""Tests for expanded verdict schemas."""
import pytest
from tradingagents.graph.verdict_schemas import (
    InvalidationCondition,
    ConvictionMilestone,
    DissentRecord,
    ScenarioOutcome,
    TraderVerdict,
    InvestmentVerdict,
    RiskVerdict,
)


class TestInvalidationCondition:
    def test_basic_creation(self):
        ic = InvalidationCondition(
            metric="PE_ratio", operator=">", threshold=35.0,
            description="PE exceeds growth justification",
        )
        assert ic.metric == "PE_ratio"
        assert ic.operator == ">"
        assert ic.threshold == 35.0

    def test_all_operators(self):
        for op in ["<", ">", "==", "crosses_below", "crosses_above"]:
            ic = InvalidationCondition(
                metric="price", operator=op, threshold=100.0,
                description=f"test {op}",
            )
            assert ic.operator == op

    def test_invalid_operator_rejected(self):
        with pytest.raises(Exception):
            InvalidationCondition(
                metric="price", operator="!=", threshold=100.0,
                description="bad op",
            )


class TestConvictionMilestone:
    def test_basic_creation(self):
        cm = ConvictionMilestone(
            trigger_type="price_above", trigger_value=200.0,
            new_conviction=4, action="ADD",
        )
        assert cm.trigger_type == "price_above"
        assert cm.new_conviction == 4

    def test_conviction_bounds(self):
        with pytest.raises(Exception):
            ConvictionMilestone(
                trigger_type="price_above", trigger_value=200.0,
                new_conviction=0, action="HOLD",
            )
        with pytest.raises(Exception):
            ConvictionMilestone(
                trigger_type="price_above", trigger_value=200.0,
                new_conviction=6, action="HOLD",
            )

    def test_all_actions(self):
        for action in ["HOLD", "ADD", "TRIM", "EXIT"]:
            cm = ConvictionMilestone(
                trigger_type="days_held", trigger_value=10,
                new_conviction=3, action=action,
            )
            assert cm.action == action


class TestDissentRecord:
    def test_basic_creation(self):
        dr = DissentRecord(
            dissenter_role="Conservative",
            dissent_topic="position sizing",
            dissent_strength=4,
            resolution="Reduced from 8% to 5%",
        )
        assert dr.dissent_strength == 4

    def test_strength_bounds(self):
        with pytest.raises(Exception):
            DissentRecord(
                dissenter_role="X", dissent_topic="Y",
                dissent_strength=0, resolution="Z",
            )
        with pytest.raises(Exception):
            DissentRecord(
                dissenter_role="X", dissent_topic="Y",
                dissent_strength=6, resolution="Z",
            )


class TestScenarioOutcome:
    def test_basic_creation(self):
        so = ScenarioOutcome(
            label="BULL", probability=0.3,
            target_return_pct=15.0,
            description="Strong earnings growth",
        )
        assert so.label == "BULL"
        assert so.probability == 0.3

    def test_probability_bounds(self):
        with pytest.raises(Exception):
            ScenarioOutcome(
                label="BASE", probability=-0.1,
                description="bad prob",
            )
        with pytest.raises(Exception):
            ScenarioOutcome(
                label="BASE", probability=1.1,
                description="bad prob",
            )

    def test_optional_targets(self):
        so = ScenarioOutcome(label="BEAR", probability=0.2, description="Recession")
        assert so.target_price is None
        assert so.target_return_pct is None


class TestTraderVerdict:
    def test_minimal_creation(self):
        tv = TraderVerdict(
            decision="BUY", conviction=4, reasoning="Strong fundamentals",
        )
        assert tv.decision == "BUY"
        assert tv.invalidation_conditions == []
        assert tv.scenarios == []
        assert tv.milestones == []
        assert tv.position_size_pct == 0.05

    def test_full_creation(self):
        tv = TraderVerdict(
            decision="BUY",
            conviction=4,
            reasoning="Strong case",
            invalidation_conditions=[
                InvalidationCondition(
                    metric="price", operator="<", threshold=140.0,
                    description="Below support",
                ),
            ],
            scenarios=[
                ScenarioOutcome(label="BULL", probability=0.3, target_return_pct=20.0, description="Best case"),
                ScenarioOutcome(label="BASE", probability=0.5, target_return_pct=8.0, description="Likely"),
                ScenarioOutcome(label="BEAR", probability=0.2, target_return_pct=-10.0, description="Worst"),
            ],
            milestones=[
                ConvictionMilestone(trigger_type="price_above", trigger_value=200.0, new_conviction=5, action="ADD"),
            ],
            position_size_pct=0.08,
        )
        assert len(tv.invalidation_conditions) == 1
        assert len(tv.scenarios) == 3
        assert len(tv.milestones) == 1
        assert tv.position_size_pct == 0.08

    def test_model_dump_roundtrip(self):
        tv = TraderVerdict(decision="HOLD", conviction=3, reasoning="Neutral")
        data = tv.model_dump()
        tv2 = TraderVerdict(**data)
        assert tv2.decision == tv.decision

    def test_invalid_decision_rejected(self):
        with pytest.raises(Exception):
            TraderVerdict(decision="SHORT", conviction=3, reasoning="Bad")


class TestRiskVerdict:
    def test_backwards_compatible(self):
        """Existing fields still work without new fields."""
        rv = RiskVerdict(
            decision="BUY", conviction=4,
            hedge_directive="NO_CHANGE",
            reasoning="Risk acceptable",
        )
        assert rv.dissent_records == []
        assert rv.invalidation_conditions == []
        assert rv.drawdown_mode is False
        assert rv.re_entry_conditions == []

    def test_full_with_new_fields(self):
        rv = RiskVerdict(
            decision="HOLD", conviction=2,
            hedge_directive="INCREASE_HEDGE",
            hedge_instrument="SPY",
            max_position_pct=0.03,
            reasoning="Too risky in drawdown",
            dissent_records=[
                DissentRecord(
                    dissenter_role="Aggressive",
                    dissent_topic="Missing the dip",
                    dissent_strength=4,
                    resolution="Overruled — capital preservation",
                ),
            ],
            invalidation_conditions=[
                InvalidationCondition(
                    metric="price", operator=">", threshold=180.0,
                    description="Break above resistance",
                ),
            ],
            drawdown_mode=True,
            re_entry_conditions=["VIX below 20", "Score above 60"],
        )
        assert rv.drawdown_mode is True
        assert len(rv.dissent_records) == 1
        assert len(rv.re_entry_conditions) == 2

    def test_model_dump(self):
        rv = RiskVerdict(
            decision="SELL", conviction=5,
            hedge_directive="INCREASE_HEDGE",
            reasoning="Liquidate",
        )
        data = rv.model_dump()
        assert data["dissent_records"] == []
        assert data["drawdown_mode"] is False


class TestInvestmentVerdict:
    def test_unchanged(self):
        """InvestmentVerdict should be unchanged."""
        iv = InvestmentVerdict(
            decision="BUY", conviction=4,
            reasoning="Strong", bull_strength=5, bear_strength=2,
        )
        assert iv.bull_strength == 5
