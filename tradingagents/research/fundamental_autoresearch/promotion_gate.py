from typing import Any


DEFAULT_PROMOTION_THRESHOLDS = {
    "min_primary_metric_value": 0.05,
    "min_coverage_ratio": 0.75,
    "min_observations": 250,
    "min_positive_horizon_count": 3,
    "min_era_count": 2,
    "min_sector_count": 3,
}


def evaluate_promotion_gate(
    row: dict[str, Any],
    *,
    robustness: dict[str, Any] | None = None,
    thresholds: dict[str, float | int] | None = None,
) -> dict[str, Any]:
    limits = dict(DEFAULT_PROMOTION_THRESHOLDS)
    if thresholds:
        limits.update(thresholds)

    robustness = robustness or {}
    failed_checks: list[str] = []

    primary_metric_value = float(row.get("primary_metric_value") or 0.0)
    coverage_ratio = float(row.get("coverage_ratio") or 0.0)
    observations = int(row.get("observations") or 0)

    if primary_metric_value < float(limits["min_primary_metric_value"]):
        failed_checks.append("primary_metric_value")
    if coverage_ratio < float(limits["min_coverage_ratio"]):
        failed_checks.append("coverage_ratio")
    if observations < int(limits["min_observations"]):
        failed_checks.append("observations")

    by_horizon = robustness.get("by_horizon", {}) or {}
    positive_horizons = sum(
        1
        for payload in by_horizon.values()
        if float((payload or {}).get("primary_metric_value") or 0.0) > 0.0
    )
    if positive_horizons < int(limits["min_positive_horizon_count"]):
        failed_checks.append("positive_horizons")

    by_era = robustness.get("by_era", {}) or {}
    if len(by_era) < int(limits["min_era_count"]):
        failed_checks.append("era_breadth")

    by_sector = robustness.get("by_sector", {}) or {}
    if len(by_sector) < int(limits["min_sector_count"]):
        failed_checks.append("sector_breadth")

    gate_status = "PASSED" if not failed_checks else "FAILED"
    recommended_status = "shadow" if gate_status == "PASSED" else "candidate"

    return {
        **row,
        "gate_status": gate_status,
        "recommended_status": recommended_status,
        "failed_checks": failed_checks,
    }
