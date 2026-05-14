from pydantic import BaseModel, Field
from typing import Literal, Optional, List


class InvalidationCondition(BaseModel):
    """A specific, falsifiable condition that would invalidate the trade thesis."""
    metric: str = Field(description="What to monitor (e.g., 'revenue_growth', 'PE_ratio', 'RSI')")
    operator: Literal["<", ">", "==", "crosses_below", "crosses_above"]
    threshold: float
    description: str = Field(description="Human-readable explanation")


class ConvictionMilestone(BaseModel):
    """A price/time milestone that changes conviction level."""
    trigger_type: Literal["price_above", "price_below", "days_held", "score_change"]
    trigger_value: float
    new_conviction: int = Field(ge=1, le=5)
    action: Literal["HOLD", "ADD", "TRIM", "EXIT"]


class DissentRecord(BaseModel):
    """Captures significant disagreement between review participants."""
    dissenter_role: str
    dissent_topic: str
    dissent_strength: int = Field(ge=1, le=5)
    resolution: str


class ScenarioOutcome(BaseModel):
    """Bull/base/bear scenario with probability and target."""
    label: Literal["BULL", "BASE", "BEAR"]
    probability: float = Field(ge=0.0, le=1.0)
    target_price: Optional[float] = None
    target_return_pct: Optional[float] = None
    description: str


class TraderVerdict(BaseModel):
    """Structured output from the Trader node."""
    decision: Literal["BUY", "SELL", "HOLD"]
    conviction: int = Field(ge=1, le=5)
    reasoning: str
    invalidation_conditions: List[InvalidationCondition] = Field(default_factory=list)
    scenarios: List[ScenarioOutcome] = Field(default_factory=list)
    milestones: List[ConvictionMilestone] = Field(default_factory=list)
    position_size_pct: float = Field(ge=0.0, le=1.0, default=0.05)


class InvestmentVerdict(BaseModel):
    """Structured output from the Research Manager."""
    decision: Literal["BUY", "SELL", "HOLD"]
    conviction: int = Field(ge=1, le=5)
    reasoning: str = Field(description="Full investment plan text")
    bull_strength: int = Field(ge=1, le=5, description="How strong was the bull case")
    bear_strength: int = Field(ge=1, le=5, description="How strong was the bear case")


class RiskVerdict(BaseModel):
    """Structured output from the Risk Judge."""
    decision: Literal["BUY", "SELL", "HOLD"]
    conviction: int = Field(ge=1, le=5)
    hedge_directive: Literal["INCREASE_HEDGE", "DECREASE_HEDGE", "NO_CHANGE"]
    hedge_instrument: Optional[str] = None
    max_position_pct: float = Field(ge=0.0, le=1.0, default=0.05)
    reasoning: str = Field(description="Full risk assessment text")
    dissent_records: List[DissentRecord] = Field(default_factory=list)
    invalidation_conditions: List[InvalidationCondition] = Field(default_factory=list)
    drawdown_mode: bool = Field(default=False)
    re_entry_conditions: List[str] = Field(default_factory=list)
