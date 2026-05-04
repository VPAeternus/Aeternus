from dataclasses import dataclass


@dataclass(frozen=True)
class FilingSnapshotRow:
    ticker: str
    cik: str
    filing_type: str
    period_end: str
    filed_at: str
    accepted_at: str
    effective_market_date: str
    fiscal_period: str
    fiscal_year: int
    sector: str
    data_coverage_score: float
    missing_fields: list[str]
    source_flags: list[str]
    restatement_suspect: bool


@dataclass(frozen=True)
class FundamentalScoreResult:
    ticker: str
    effective_market_date: str
    fundamental_score: float
    growth_score: float
    quality_score: float
    health_score: float
    capital_discipline_score: float
    valuation_score: float
    score_version: str


@dataclass(frozen=True)
class FundamentalEvaluationSummary:
    dataset_name: str
    score_version: str
    primary_metric_name: str
    primary_metric_value: float
    coverage_ratio: float
    observations: int
