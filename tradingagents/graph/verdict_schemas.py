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

