import json
from pathlib import Path
from typing import Any


def save_signal_registry(
    rows: list[dict[str, Any]],
    *,
    results_root: str | Path = "eval_results/fundamental_autoresearch",
    run_date: str,
    registry_name: str = "fundamental_signals",
) -> Path:
    output_dir = Path(results_root) / run_date
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{registry_name}.json"
    path.write_text(json.dumps(rows, indent=2, sort_keys=True))
    return path


def load_signal_registry(
    *,
    results_root: str | Path = "eval_results/fundamental_autoresearch",
    run_date: str,
    registry_name: str = "fundamental_signals",
) -> list[dict[str, Any]]:
    path = Path(results_root) / run_date / f"{registry_name}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text())


def choose_canonical_winner(rows: list[dict[str, Any]]) -> dict[str, Any]:
    passed = [row for row in rows if row.get("gate_status") == "PASSED"]
    pool = passed if passed else list(rows)
    if not pool:
        return {}
    return max(pool, key=lambda row: float(row.get("primary_metric_value", float("-inf"))))


def load_latest_signal_registry(
    *,
    results_root: str | Path = "eval_results/fundamental_autoresearch",
    registry_name: str = "fundamental_signals",
) -> tuple[str | None, list[dict[str, Any]]]:
    root = Path(results_root)
    if not root.exists():
        return None, []

    run_dates = sorted(
        child.name
        for child in root.iterdir()
        if child.is_dir() and (child / f"{registry_name}.json").exists()
    )
    if not run_dates:
        return None, []

    latest = run_dates[-1]
    return latest, load_signal_registry(
        results_root=root,
        run_date=latest,
        registry_name=registry_name,
    )


def get_active_strategy(
    *,
    results_root: str | Path = "eval_results/fundamental_autoresearch",
    run_date: str | None = None,
    registry_name: str = "fundamental_signals",
    preferred_statuses: tuple[str, ...] = ("promoted", "shadow"),
) -> dict[str, Any] | None:
    if run_date is not None:
        rows = load_signal_registry(
            results_root=results_root,
            run_date=run_date,
            registry_name=registry_name,
        )
        resolved_run_date = run_date if rows else None
        if not rows:
            resolved_run_date, rows = load_latest_signal_registry(
                results_root=results_root,
                registry_name=registry_name,
            )
    else:
        resolved_run_date, rows = load_latest_signal_registry(
            results_root=results_root,
            registry_name=registry_name,
        )

    if not rows:
        return None

    for preferred in preferred_statuses:
        matching = [
            row for row in rows
            if row.get("status") == preferred or row.get("recommended_status") == preferred
        ]
        if matching:
            winner = max(
                matching,
                key=lambda row: float(row.get("primary_metric_value", float("-inf"))),
            )
            return {
                **winner,
                "resolved_status": preferred,
                "registry_run_date": resolved_run_date,
            }

    return None


def promote_strategy(
    rows: list[dict[str, Any]],
    *,
    strategy: str,
    status: str = "shadow",
    robustness: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if status not in {"shadow", "promoted"}:
        raise ValueError(f"Unsupported promotion status: {status}")

    promoted = False
    updated_rows: list[dict[str, Any]] = []
    for row in rows:
        current = dict(row)
        if current.get("strategy") == strategy:
            current["status"] = status
            current["recommended_status"] = status
            current["manual_override"] = True
            if robustness is not None:
                current["robustness_summary"] = robustness
            promoted = True
        else:
            if current.get("status") in {"shadow", "promoted"}:
                current["status"] = "candidate"
            if current.get("recommended_status") in {"shadow", "promoted"}:
                current["recommended_status"] = "candidate"
        updated_rows.append(current)

    if not promoted:
        raise ValueError(f"Strategy not found in registry rows: {strategy}")

    return updated_rows
