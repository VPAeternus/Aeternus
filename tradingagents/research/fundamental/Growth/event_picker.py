from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVENT_PATH = ROOT / "Growth" / "earnings_8k_sec_parser" / "event_shock_scores.csv"
MANIFEST_PATH = ROOT / "Growth" / "earnings_8k_sec_parser" / "manifest.csv"
OUT_DIR = ROOT / "Growth" / "earnings_8k_sec_parser"
DEFAULT_PICKS = OUT_DIR / "fundamental_picks.csv"
DEFAULT_SUMMARY = OUT_DIR / "fundamental_summary.csv"
DEFAULT_CANDIDATES = OUT_DIR / "fundamental_candidates.csv"
DEFAULT_VENTURE_SOURCES = [
    ROOT / "Growth" / "venture_scan_2021-06_2023-06_all_scored.csv",
    ROOT / "Growth" / "venture_scan_2026_inventory_all_scored.csv",
    ROOT / "Growth" / "be_lte_nvda_sndk_aaoi_venture_score_source.csv",
    ROOT / "Growth" / "be_lte_nvda_sndk_venture_score_source.csv",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return list(csv.DictReader(path.open(encoding="utf-8")))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def to_float(value: str | object, default: float = 0.0) -> float:
    try:
        if value in {None, ""}:
            return default
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def to_int(value: str | object, default: int = 0) -> int:
    try:
        if value in {None, ""}:
            return default
        return int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def key(row: dict[str, str]) -> tuple[str, str]:
    return (row["ticker"], row["filed"])


def load_events() -> list[dict[str, str]]:
    manifest = {key(row): row for row in read_csv(MANIFEST_PATH)}
    rows: list[dict[str, str]] = []
    for row in read_csv(EVENT_PATH):
        merged = dict(manifest.get(key(row), {}))
        merged.update(row)
        rows.append(merged)
    return rows


def load_venture_rows(paths: list[Path]) -> dict[str, list[dict[str, str]]]:
    dedupe: dict[tuple[str, str], dict[str, str]] = {}
    for path in paths:
        for row in read_csv(path):
            ticker = row.get("ticker", "").upper()
            filing_date = row.get("filing_date", "")
            if not ticker or not filing_date or not row.get("venture_score"):
                continue
            current = dedupe.get((ticker, filing_date))
            if current is None or len(row) > len(current):
                dedupe[(ticker, filing_date)] = row
    by_ticker: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in dedupe.values():
        by_ticker[row["ticker"].upper()].append(row)
    for rows in by_ticker.values():
        rows.sort(key=lambda row: row.get("filing_date", ""))
    return by_ticker


def active_venture(ticker: str, decision_date: date, venture_by_ticker: dict[str, list[dict[str, str]]]) -> dict[str, str]:
    candidates = [
        row for row in venture_by_ticker.get(ticker.upper(), [])
        if parse_date(row.get("filing_date", "")) and parse_date(row.get("filing_date", "")) <= decision_date
    ]
    return candidates[-1] if candidates else {}


def convexity_score(ticker: str, event_row: dict[str, str], venture_row: dict[str, str]) -> float:
    # Small/mid-cap proxy until market-cap history is added: use known universe + return convexity evidence.
    base = {
        "AAOI": 4.0,
        "BE": 3.5,
        "LITE": 2.5,
        "SNDK": 2.0,
        "MU": 1.5,
        "GOOGL": 0.5,
        "NVDA": 0.5,
    }.get(ticker.upper(), 1.0)
    if "expansion" in venture_row.get("archetype_path", "").lower():
        base += 0.75
    if to_int(venture_row.get("asymmetric_upside")) >= 3:
        base += 0.75
    return min(base, 5.0)


def capital_priority(event: dict[str, str], venture: dict[str, str]) -> tuple[float, str, str, bool, str]:
    ticker = event["ticker"]
    bucket = event.get("event_shock_bucket", "")
    demand = to_float(event.get("demand_shock_score"))
    risk = to_float(event.get("risk_shock_score"))
    cyclicality_penalty = to_float(event.get("cyclicality_penalty"))
    net = to_float(event.get("event_shock_score"))
    venture_score = to_int(venture.get("venture_score"))
    wave = to_int(venture.get("wave_exposure"))
    asym = to_int(venture.get("asymmetric_upside"))
    fundable = to_int(venture.get("fundable_scaling"))
    torque = to_int(venture.get("wave_torque_operating_leverage"))
    false_promise = to_int(venture.get("false_promise_penalty"))
    saturation = to_int(venture.get("incumbent_saturation_penalty"))
    convexity = convexity_score(ticker, event, venture)

    if bucket == "insufficient_history":
        return -999.0, "skip_insufficient_history", "not enough prior 8-K history", False, ""

    score = 0.0
    score += demand * 1.4
    score += max(net, 0) * 0.7
    score += min(venture_score, 20) * 0.55
    score += wave * 0.8
    score += asym * 0.7
    score += fundable * 0.45
    score += torque * 0.7
    score += convexity * 1.3
    score -= risk * 1.1
    score -= cyclicality_penalty * 1.4
    score -= false_promise * 1.2
    score -= saturation * 0.8

    if bucket == "mixed_high_shock":
        if demand >= 8 and risk <= 10:
            score += 1.5
            label = "mixed_demand_dominant"
        else:
            score -= 3.0
            label = "mixed_risk_dominant"
    elif bucket == "positive_shock":
        score += 2.0
        label = "clean_positive_shock"
    elif bucket == "negative_shock":
        score -= 4.0
        label = "avoid_negative_shock"
    else:
        label = "neutral_event"

    if not venture:
        score -= 8.0
        label = "missing_venture_context"

    cyclicality_gate = cyclicality_penalty >= 3 and not (venture_score >= 14 and demand >= 8)
    cyclicality_gate_reason = ""
    if cyclicality_gate:
        score -= 1.0
        cyclicality_gate_reason = (
            f"cyclicality_penalty={cyclicality_penalty:.2f} with venture={venture_score} "
            f"and demand={demand:.2f}; requires venture>=14 and demand>=8"
        )

    why = (
        f"{label}; demand={demand:.2f}; risk={risk:.2f}; venture={venture_score}; "
        f"wave={wave}; asym={asym}; convexity={convexity:.2f}; cyclicality={cyclicality_penalty:.2f}"
    )
    return round(score, 4), label, why, cyclicality_gate, cyclicality_gate_reason


def build_candidates(events: list[dict[str, str]], venture_by_ticker: dict[str, list[dict[str, str]]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for event in events:
        decision_date = parse_date(event.get("tradable_date", "")) or parse_date(event.get("filed", ""))
        if decision_date is None:
            continue
        venture = active_venture(event["ticker"], decision_date, venture_by_ticker)
        score, bucket, why, cyclicality_gate, cyclicality_gate_reason = capital_priority(event, venture)
        output.append({
            "decision_date": decision_date.isoformat(),
            "ticker": event["ticker"],
            "filed": event["filed"],
            "capital_priority_score": score,
            "capital_priority_bucket": bucket,
            "cyclicality_gate": str(cyclicality_gate),
            "cyclicality_gate_reason": cyclicality_gate_reason,
            "why_selected": why,
            "event_shock_score": event.get("event_shock_score", ""),
            "event_shock_bucket": event.get("event_shock_bucket", ""),
            "demand_shock_score": event.get("demand_shock_score", ""),
            "risk_shock_score": event.get("risk_shock_score", ""),
            "cyclicality_penalty": event.get("cyclicality_penalty", ""),
            "cyclicality_delta": event.get("cyclicality_delta", ""),
            "event_shock_confidence": event.get("event_shock_confidence", ""),
            "venture_score": venture.get("venture_score", ""),
            "venture_filing_date": venture.get("filing_date", ""),
            "venture_archetype_path": venture.get("archetype_path", ""),
            "venture_wave_exposure": venture.get("wave_exposure", ""),
            "venture_asymmetric_upside": venture.get("asymmetric_upside", ""),
            "venture_fundable_scaling": venture.get("fundable_scaling", ""),
            "venture_wave_torque_operating_leverage": venture.get("wave_torque_operating_leverage", ""),
            "venture_false_promise_penalty": venture.get("false_promise_penalty", ""),
            "return_10d_pct": event.get("return_10d_pct", ""),
            "return_20d_pct": event.get("return_20d_pct", ""),
            "return_30d_pct": event.get("return_30d_pct", ""),
            "return_60d_pct": event.get("return_60d_pct", ""),
            "return_90d_pct": event.get("return_90d_pct", ""),
            "positive_delta_drivers": event.get("positive_delta_drivers", ""),
            "evidence_snippets": event.get("evidence_snippets", ""),
        })
    return sorted(output, key=lambda row: (row["decision_date"], -float(row["capital_priority_score"])))


def period_key(decision_date: str, period: str) -> str:
    parsed = parse_date(decision_date)
    if parsed is None or period == "event":
        return decision_date
    if period == "month":
        return f"{parsed.year}-{parsed.month:02d}"
    if period == "quarter":
        quarter = ((parsed.month - 1) // 3) + 1
        return f"{parsed.year}Q{quarter}"
    raise ValueError(f"Unsupported rebalance period: {period}")


def pick_fundamental(candidates: list[dict[str, object]], top_n: int, min_score: float, rebalance_period: str) -> list[dict[str, object]]:
    by_date: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in candidates:
        if float(row["capital_priority_score"]) >= min_score:
            by_date[period_key(str(row["decision_date"]), rebalance_period)].append(row)
    picks: list[dict[str, object]] = []
    for period, rows in sorted(by_date.items()):
        ranked = sorted(rows, key=lambda row: float(row["capital_priority_score"]), reverse=True)
        for rank, row in enumerate(ranked[:top_n], start=1):
            pick = dict(row)
            pick["rank"] = rank
            pick["rebalance_period"] = period
            picks.append(pick)
    return picks


def summarize(picks: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for group_name, group_rows in [("all", picks)] + sorted(
        ((ticker, [row for row in picks if row["ticker"] == ticker]) for ticker in {row["ticker"] for row in picks}),
        key=lambda item: item[0],
    ):
        row: dict[str, object] = {"group": group_name, "n": len(group_rows)}
        for horizon in [10, 20, 30, 60, 90]:
            vals = [to_float(item.get(f"return_{horizon}d_pct"), None) for item in group_rows]  # type: ignore[arg-type]
            nums = [value for value in vals if value is not None]
            row[f"avg_return_{horizon}d_pct"] = round(sum(nums) / len(nums), 4) if nums else ""
            row[f"win_rate_{horizon}d_pct"] = round(sum(1 for value in nums if value > 0) / len(nums) * 100, 2) if nums else ""
        rows.append(row)
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fundamental event + venture capital priority picker")
    parser.add_argument("--event-path", type=Path, default=EVENT_PATH)
    parser.add_argument("--top-n", type=int, default=1)
    parser.add_argument("--min-score", type=float, default=0)
    parser.add_argument("--rebalance-period", choices=["event", "month", "quarter"], default="quarter")
    parser.add_argument("--picks-output", type=Path, default=DEFAULT_PICKS)
    parser.add_argument("--candidates-output", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--venture-source", type=Path, action="append", default=[])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    event_rows = load_events()
    venture_sources = args.venture_source or DEFAULT_VENTURE_SOURCES
    venture_by_ticker = load_venture_rows(venture_sources)
    candidates = build_candidates(event_rows, venture_by_ticker)
    picks = pick_fundamental(candidates, args.top_n, args.min_score, args.rebalance_period)
    write_csv(args.candidates_output, candidates)
    write_csv(args.picks_output, picks)
    write_csv(args.summary_output, summarize(picks))
    print(f"candidates={len(candidates)} picks={len(picks)}")
    print(f"wrote {args.candidates_output}")
    print(f"wrote {args.picks_output}")
    print(f"wrote {args.summary_output}")
    print(dict(Counter(row["ticker"] for row in picks)))


if __name__ == "__main__":
    main()
