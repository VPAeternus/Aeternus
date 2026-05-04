"""Append-only hypothesis ledger helpers for funnel stage experiments."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Tuple

from .control_io import read_json_locked, update_json_locked, write_json_locked

_STAGE_ORDER = [
    "universe_gate_edge",
    "universe_gate_haystack",
    "evidence_gate",
    "shortlist_cut",
    "deep_selection_cut",
    "portfolio_inclusion_cut",
]


def build_stage_snapshot_paths(
    *,
    base_dir: Path,
    lane: str,
    stage_id: str,
) -> Tuple[Path, Path]:
    root = Path(base_dir) / "hypothesis_ledger" / str(lane).strip()
    return (
        root / f"{str(stage_id).strip()}.kept.json",
        root / f"{str(stage_id).strip()}.dropped.json",
    )


def build_stage_drop_metadata_path(
    *,
    base_dir: Path,
    lane: str,
    stage_id: str,
) -> Path:
    root = Path(base_dir) / "hypothesis_ledger" / str(lane).strip()
    return root / f"{str(stage_id).strip()}.dropped.meta.json"


def ledger_rows_path(*, base_dir: Path, lane: str) -> Path:
    return Path(base_dir) / "hypothesis_ledger" / str(lane).strip() / "rows.json"


def write_symbol_snapshot(path: Path, symbols: Iterable[str]) -> Path:
    normalized = []
    seen = set()
    for raw in symbols:
        symbol = str(raw or "").upper().strip()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(symbol)
    write_json_locked(Path(path), normalized)
    return Path(path)


def append_ledger_row(*, base_dir: Path, lane: str, row: dict[str, Any]) -> Path:
    path = ledger_rows_path(base_dir=base_dir, lane=lane)

    def _append(current: Any) -> list[dict[str, Any]]:
        rows = list(current) if isinstance(current, list) else []
        rows.append(dict(row))
        return rows

    update_json_locked(path, _append, default_factory=list)
    return path


def enrich_ledger_rows(
    *,
    base_dir: Path,
    lane: str,
    forward_returns_by_horizon: dict[str, dict[str, float]],
    winner_horizon: str | None = None,
    winner_threshold: float | None = None,
) -> list[dict[str, Any]]:
    path = ledger_rows_path(base_dir=base_dir, lane=lane)
    if not Path(path).exists():
        return []

    normalized_maps = {
        str(label): {
            str(symbol).upper().strip(): float(value)
            for symbol, value in dict(values).items()
            if str(symbol).strip()
        }
        for label, values in dict(forward_returns_by_horizon).items()
        if isinstance(values, dict)
    }
    resolved_winner_horizon = _resolve_winner_horizon(normalized_maps, winner_horizon)
    resolved_threshold = (
        float(winner_threshold)
        if winner_threshold is not None
        else _default_winner_threshold(resolved_winner_horizon)
    )

    def _update(current: Any) -> list[dict[str, Any]]:
        rows = list(current) if isinstance(current, list) else []
        updated: list[dict[str, Any]] = []
        for raw_row in rows:
            row = dict(raw_row)
            kept_symbols = _normalize_symbols(
                read_json_locked(Path(row.get("kept_symbols_path", "")), default_factory=list)
            )
            dropped_symbols = _normalize_symbols(
                read_json_locked(Path(row.get("dropped_symbols_path", "")), default_factory=list)
            )

            metrics_by_horizon = {
                label: compute_stage_metrics(
                    kept_symbols=kept_symbols,
                    dropped_symbols=dropped_symbols,
                    forward_returns_by_symbol=returns_map,
                    winner_threshold=resolved_threshold if label == resolved_winner_horizon else _default_winner_threshold(label),
                )
                for label, returns_map in normalized_maps.items()
            }
            metrics_5d = metrics_by_horizon.get("5d", {})
            metrics_20d = metrics_by_horizon.get("20d", {})
            metrics_3m = metrics_by_horizon.get("3m", {})
            winner_metrics = metrics_by_horizon.get(resolved_winner_horizon, {})

            row["kept_mean_return_5d"] = metrics_5d.get("kept_mean_return")
            row["dropped_mean_return_5d"] = metrics_5d.get("dropped_mean_return")
            row["edge_5d"] = metrics_5d.get("edge")
            row["edge_20d"] = metrics_20d.get("edge")
            row["edge_3m"] = metrics_3m.get("edge")
            row["future_winner_recall"] = winner_metrics.get("future_winner_recall")
            row["false_negative_cost"] = winner_metrics.get("false_negative_cost")
            sample_sizes = [
                metric.get("sample_size")
                for metric in metrics_by_horizon.values()
                if metric.get("sample_size") is not None
            ]
            row["sample_size"] = max(sample_sizes) if sample_sizes else None
            updated.append(row)
        return updated

    return update_json_locked(path, _update, default_factory=list)


def summarize_ledger_rows(
    *,
    base_dir: Path,
    lane: str,
) -> dict[str, Any]:
    rows = read_json_locked(ledger_rows_path(base_dir=base_dir, lane=lane), default_factory=list)
    normalized_rows = [dict(row) for row in rows if isinstance(row, dict)]

    order_map = {stage_id: idx for idx, stage_id in enumerate(_STAGE_ORDER)}
    normalized_rows.sort(
        key=lambda row: (
            order_map.get(str(row.get("stage_id", "")).strip(), len(order_map)),
            str(row.get("stage_id", "")).strip(),
        )
    )

    stages: list[dict[str, Any]] = []
    for row in normalized_rows:
        stages.append(
            {
                "stage_id": str(row.get("stage_id", "")).strip(),
                "kept_count": int(row.get("kept_count", 0) or 0),
                "dropped_count": int(row.get("dropped_count", 0) or 0),
                "edge_5d": row.get("edge_5d"),
                "edge_20d": row.get("edge_20d"),
                "edge_3m": row.get("edge_3m"),
                "future_winner_recall": row.get("future_winner_recall"),
                "false_negative_cost": row.get("false_negative_cost"),
                "sample_size": row.get("sample_size"),
            }
        )

    return {
        "lane": str(lane),
        "stages": stages,
    }


def compute_stage_metrics(
    *,
    kept_symbols: Iterable[str],
    dropped_symbols: Iterable[str],
    forward_returns_by_symbol: dict[str, float],
    winner_threshold: float = 0.20,
) -> dict[str, Any]:
    kept = _normalize_symbols(kept_symbols)
    dropped = _normalize_symbols(dropped_symbols)
    returns_map = {
        str(symbol).upper().strip(): float(value)
        for symbol, value in dict(forward_returns_by_symbol).items()
        if str(symbol).strip()
    }

    kept_returns = _returns_for_symbols(kept, returns_map)
    dropped_returns = _returns_for_symbols(dropped, returns_map)
    kept_mean = _mean_or_none(kept_returns)
    dropped_mean = _mean_or_none(dropped_returns)

    all_symbols = kept + [symbol for symbol in dropped if symbol not in kept]
    total_winners = [
        symbol for symbol in all_symbols
        if returns_map.get(symbol) is not None and float(returns_map[symbol]) >= float(winner_threshold)
    ]
    kept_winners = [
        symbol for symbol in kept
        if returns_map.get(symbol) is not None and float(returns_map[symbol]) >= float(winner_threshold)
    ]
    dropped_winner_returns = [
        float(returns_map[symbol])
        for symbol in dropped
        if returns_map.get(symbol) is not None and float(returns_map[symbol]) >= float(winner_threshold)
    ]

    edge = None
    if kept_mean is not None and dropped_mean is not None:
        edge = round(kept_mean - dropped_mean, 4)

    return {
        "kept_mean_return": kept_mean,
        "dropped_mean_return": dropped_mean,
        "edge": edge,
        "future_winner_recall": (
            round(len(kept_winners) / float(len(total_winners)), 4)
            if total_winners
            else None
        ),
        "false_negative_cost": round(sum(dropped_winner_returns), 4),
        "sample_size": len(kept_returns) + len(dropped_returns),
    }


def make_ledger_row(
    *,
    run_id: str,
    source_date: str,
    lane: str,
    stage_id: str,
    rule_snapshot: dict[str, Any],
    kept_symbols: Iterable[str],
    dropped_symbols: Iterable[str],
    base_dir: Path,
    drop_metadata_by_symbol: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    kept_list = list(kept_symbols)
    dropped_list = list(dropped_symbols)
    kept_path, dropped_path = build_stage_snapshot_paths(
        base_dir=Path(base_dir),
        lane=lane,
        stage_id=stage_id,
    )
    write_symbol_snapshot(kept_path, kept_list)
    write_symbol_snapshot(dropped_path, dropped_list)
    normalized_drop_metadata = _normalize_drop_metadata(drop_metadata_by_symbol)
    drop_metadata_path: Path | None = None
    if normalized_drop_metadata:
        drop_metadata_path = build_stage_drop_metadata_path(
            base_dir=Path(base_dir),
            lane=lane,
            stage_id=stage_id,
        )
        write_json_locked(drop_metadata_path, normalized_drop_metadata)

    return {
        "run_id": str(run_id),
        "source_date": str(source_date),
        "lane": str(lane),
        "stage_id": str(stage_id),
        "rule_snapshot": dict(rule_snapshot),
        "input_count": len(kept_list) + len(dropped_list),
        "kept_count": len(kept_list),
        "dropped_count": len(dropped_list),
        "kept_symbols_path": str(kept_path),
        "dropped_symbols_path": str(dropped_path),
        "kept_mean_return_5d": None,
        "dropped_mean_return_5d": None,
        "edge_5d": None,
        "edge_20d": None,
        "edge_3m": None,
        "future_winner_recall": None,
        "false_negative_cost": None,
        "sample_size": None,
        "recommended_adjustment": None,
        "applied_adjustment": None,
        "applied_by": None,
        "dropped_symbols_metadata_path": str(drop_metadata_path) if drop_metadata_path is not None else None,
    }


def _normalize_symbols(symbols: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen = set()
    for raw in symbols:
        symbol = str(raw or "").upper().strip()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(symbol)
    return normalized


def _returns_for_symbols(symbols: Iterable[str], returns_map: dict[str, float]) -> list[float]:
    values: list[float] = []
    for symbol in symbols:
        if symbol not in returns_map:
            continue
        values.append(float(returns_map[symbol]))
    return values


def _mean_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / float(len(values)), 4)


def _resolve_winner_horizon(
    forward_returns_by_horizon: dict[str, dict[str, float]],
    winner_horizon: str | None,
) -> str:
    preferred = str(winner_horizon or "").strip()
    if preferred and forward_returns_by_horizon.get(preferred):
        return preferred
    for label in ("3m", "20d", "5d"):
        if forward_returns_by_horizon.get(label):
            return label
    return "5d"


def _default_winner_threshold(horizon: str) -> float:
    label = str(horizon or "").strip().lower()
    if label == "3m":
        return 0.20
    if label == "20d":
        return 0.05
    return 0.02


def _normalize_drop_metadata(
    drop_metadata_by_symbol: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    if not isinstance(drop_metadata_by_symbol, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for raw_symbol, raw_payload in drop_metadata_by_symbol.items():
        symbol = str(raw_symbol or "").upper().strip()
        if not symbol:
            continue
        payload = dict(raw_payload or {}) if isinstance(raw_payload, dict) else {}
        normalized[symbol] = {
            "reason_code": str(payload.get("reason_code") or "").strip(),
            "reason_text": str(payload.get("reason_text") or "").strip(),
            "threshold": payload.get("threshold"),
            "observed_value": payload.get("observed_value"),
            "delta_to_pass": payload.get("delta_to_pass"),
        }
    return normalized
