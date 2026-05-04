"""Walk-forward evidence generation."""

from __future__ import annotations

from statistics import median
from typing import Any, Dict, List, Optional


def build_walkforward_report(
    daily_rows: List[Dict[str, Any]],
    train_days: int = 756,
    test_days: int = 252,
    step_days: int = 63,
    fallback_train_days: int = 252,
    fallback_test_days: int = 63,
) -> Dict[str, Any]:
    ordered = sorted(
        [row for row in daily_rows if str(row.get("date", "")).strip()],
        key=lambda row: str(row.get("date")),
    )

    total_days = len(ordered)
    if total_days >= train_days + test_days:
        active_train = int(train_days)
        active_test = int(test_days)
        depth_mode = "FULL"
    elif total_days >= fallback_train_days + fallback_test_days:
        active_train = int(fallback_train_days)
        active_test = int(fallback_test_days)
        depth_mode = "PARTIAL"
    else:
        return {
            "status": "INSUFFICIENT_DEPTH",
            "depth_mode": "INSUFFICIENT",
            "parameters": {
                "train_days": int(train_days),
                "test_days": int(test_days),
                "step_days": int(step_days),
                "fallback_train_days": int(fallback_train_days),
                "fallback_test_days": int(fallback_test_days),
            },
            "windows_count": 0,
            "windows": [],
            "aggregate": {
                "median_drift_5d_pct": None,
                "median_drift_20d_pct": None,
                "iqr_drift_5d_pct": None,
                "iqr_drift_20d_pct": None,
                "edge_decay_5d_pct": None,
                "edge_decay_20d_pct": None,
            },
        }

    windows: List[Dict[str, Any]] = []
    step = max(1, int(step_days))
    window_index = 0
    stop = total_days - (active_train + active_test)
    for start in range(0, stop + 1, step):
        train_slice = ordered[start : start + active_train]
        test_slice = ordered[start + active_train : start + active_train + active_test]
        if not train_slice or not test_slice:
            continue

        train_5 = _median_or_none([_to_float(row.get("edge_5d_pct")) for row in train_slice])
        train_20 = _median_or_none([_to_float(row.get("edge_20d_pct")) for row in train_slice])
        test_5 = _median_or_none([_to_float(row.get("edge_5d_pct")) for row in test_slice])
        test_20 = _median_or_none([_to_float(row.get("edge_20d_pct")) for row in test_slice])

        drift_5 = _delta_or_none(test_5, train_5)
        drift_20 = _delta_or_none(test_20, train_20)

        windows.append(
            {
                "window_id": f"wf-{window_index:03d}",
                "train_start": str(train_slice[0].get("date")),
                "train_end": str(train_slice[-1].get("date")),
                "test_start": str(test_slice[0].get("date")),
                "test_end": str(test_slice[-1].get("date")),
                "train_count": len(train_slice),
                "test_count": len(test_slice),
                "train_edge_5d_pct": train_5,
                "train_edge_20d_pct": train_20,
                "test_edge_5d_pct": test_5,
                "test_edge_20d_pct": test_20,
                "drift_5d_pct": drift_5,
                "drift_20d_pct": drift_20,
            }
        )
        window_index += 1

    drifts_5 = [
        _to_float(window.get("drift_5d_pct"))
        for window in windows
        if isinstance(window.get("drift_5d_pct"), (int, float))
    ]
    drifts_20 = [
        _to_float(window.get("drift_20d_pct"))
        for window in windows
        if isinstance(window.get("drift_20d_pct"), (int, float))
    ]

    median_drift_5 = _median_or_none(drifts_5)
    median_drift_20 = _median_or_none(drifts_20)
    edge_decay_5 = _edge_decay(median_drift_5)
    edge_decay_20 = _edge_decay(median_drift_20)

    return {
        "status": "COMPLETE" if depth_mode == "FULL" else "PARTIAL_DATA",
        "depth_mode": depth_mode,
        "parameters": {
            "train_days": int(active_train),
            "test_days": int(active_test),
            "step_days": int(step),
            "fallback_train_days": int(fallback_train_days),
            "fallback_test_days": int(fallback_test_days),
        },
        "windows_count": len(windows),
        "windows": windows,
        "aggregate": {
            "median_drift_5d_pct": median_drift_5,
            "median_drift_20d_pct": median_drift_20,
            "iqr_drift_5d_pct": _iqr_or_none(drifts_5),
            "iqr_drift_20d_pct": _iqr_or_none(drifts_20),
            "edge_decay_5d_pct": edge_decay_5,
            "edge_decay_20d_pct": edge_decay_20,
        },
    }


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _delta_or_none(lhs: Optional[float], rhs: Optional[float]) -> Optional[float]:
    if lhs is None or rhs is None:
        return None
    return round(lhs - rhs, 6)


def _median_or_none(values: List[Optional[float]]) -> Optional[float]:
    clean = [float(value) for value in values if isinstance(value, (int, float))]
    if not clean:
        return None
    return round(float(median(clean)), 6)


def _iqr_or_none(values: List[Optional[float]]) -> Optional[float]:
    clean = sorted(float(value) for value in values if isinstance(value, (int, float)))
    if len(clean) < 4:
        return None
    q1 = _percentile(clean, 25.0)
    q3 = _percentile(clean, 75.0)
    return round(q3 - q1, 6)


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]

    rank = (pct / 100.0) * (len(values) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(values) - 1)
    weight = rank - lower
    return values[lower] * (1.0 - weight) + values[upper] * weight


def _edge_decay(median_drift: Optional[float]) -> Optional[float]:
    if median_drift is None:
        return None
    # Decay is the magnitude of negative drift only.
    if median_drift < 0.0:
        return round(abs(median_drift), 6)
    return 0.0
