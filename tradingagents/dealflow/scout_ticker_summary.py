"""Scout ticker count and handoff artifacts for dealflow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence


SCOUT_TICKER_CONTRACT = "DEALFLOW_SCOUT_TICKER_TOTAL_V1"
FINAL_TICKER_CONTRACT = "AUTHORITATIVE_DEALFLOW_TICKER_HANDOFF_V2"

SCOUT_ORDER = [
    "x_manual_feed",
    "breakout_scan",
    "thirteenf_watchlist",
    "insider_cluster",
    "technical_ignition",
    "iv_force_queue",
    "fvg_recall",
    "fma_recall",
    "commodity_shock",
    "dod_contract",
]


def build_scout_ticker_summary(
    as_of_date: str,
    *,
    x_feed_merged: Mapping[str, Any] | None,
    scout_audit: Mapping[str, Any] | None,
    fvg_recall: Mapping[str, Any] | None,
    fma_recall: Mapping[str, Any] | None,
    commodity_symbols: Sequence[Any] | None = None,
    dod_symbols: Sequence[Any] | None = None,
) -> Dict[str, Any]:
    """Build per-scout ticker counts and deduped union."""
    audit = dict(scout_audit or {})
    breakout = (audit.get("breakout") or {}).get("alerts") or []
    iv = (audit.get("iv") or {}).get("force_queue") or []
    insider = audit.get("insider") or {}
    technical = audit.get("technical_ignition") or {}
    thirteenf = audit.get("thirteenf_watchlist") or {}

    scouts = {
        "x_manual_feed": _normalize_symbols((x_feed_merged or {}).keys()),
        "breakout_scan": _normalize_symbols(row.get("ticker") for row in breakout if isinstance(row, Mapping)),
        "thirteenf_watchlist": _normalize_symbols(thirteenf.get("symbols") or []),
        "insider_cluster": _normalize_symbols(
            [
                *[row.get("ticker") for row in insider.get("buy_clusters", []) if isinstance(row, Mapping)],
                *[row.get("ticker") for row in insider.get("sell_clusters", []) if isinstance(row, Mapping)],
            ]
        ),
        "technical_ignition": _normalize_symbols(technical.get("promoted_symbols") or []),
        "iv_force_queue": _normalize_symbols(_iv_symbols(iv)),
        "fvg_recall": _normalize_symbols((fvg_recall or {}).get("selected_symbols") or []),
        "fma_recall": _normalize_symbols((fma_recall or {}).get("selected_symbols") or []),
        "commodity_shock": _normalize_symbols(commodity_symbols or []),
        "dod_contract": _normalize_symbols(dod_symbols or []),
    }

    tickers: List[str] = []
    ticker_scouts: Dict[str, List[str]] = {}
    for scout_name in SCOUT_ORDER:
        for symbol in scouts.get(scout_name, []):
            ticker_scouts.setdefault(symbol, []).append(scout_name)
            if symbol not in tickers:
                tickers.append(symbol)

    overlap = {
        symbol: sources
        for symbol, sources in ticker_scouts.items()
        if len(sources) > 1
    }

    return {
        "date": as_of_date,
        "contract": SCOUT_TICKER_CONTRACT,
        "scouts": scouts,
        "scout_counts": {name: len(scouts.get(name, [])) for name in SCOUT_ORDER},
        "total_mentions": sum(len(scouts.get(name, [])) for name in SCOUT_ORDER),
        "total_unique_tickers": len(tickers),
        "tickers": tickers,
        "ticker_scouts": ticker_scouts,
        "overlap": overlap,
    }


def persist_scout_ticker_summary(
    summary: Mapping[str, Any],
    *,
    deal_flow_root: Path | str = Path("eval_results") / "deal_flow",
) -> None:
    """Persist scout summary and final ticker handoff; remove retired queue artifacts."""
    root = Path(deal_flow_root)
    as_of_date = str(summary.get("date") or "").strip()
    if not as_of_date:
        raise ValueError("summary date is required")

    base = root / as_of_date
    base.mkdir(parents=True, exist_ok=True)
    _remove_retired_artifacts(root=root, base=base)

    json_text = json.dumps(dict(summary), indent=2)
    markdown_text = render_scout_ticker_summary_markdown(summary)
    (base / "scout_ticker_summary.json").write_text(json_text)
    (base / "scout_ticker_summary.md").write_text(markdown_text)
    (root / "latest_scout_ticker_summary.json").write_text(json_text)
    (root / "latest_scout_ticker_summary.md").write_text(markdown_text)

    handoff = _build_final_handoff(summary)
    handoff_json = json.dumps(handoff, indent=2)
    tickers = list(handoff.get("tickers", []) or [])
    handoff_txt = "\n".join(tickers) + ("\n" if tickers else "")
    (base / "final_dealflow_tickers.json").write_text(handoff_json)
    (base / "final_dealflow_tickers.txt").write_text(handoff_txt)
    (root / "latest_final_dealflow_tickers.json").write_text(handoff_json)
    (root / "latest_final_dealflow_tickers.txt").write_text(handoff_txt)


def render_scout_ticker_summary_markdown(summary: Mapping[str, Any]) -> str:
    date = str(summary.get("date", ""))
    scouts = dict(summary.get("scouts") or {})
    lines = [
        f"# Scout Ticker Summary - {date}",
        "",
        f"Total unique tickers: {int(summary.get('total_unique_tickers', 0) or 0)}",
        f"Total scout mentions: {int(summary.get('total_mentions', 0) or 0)}",
        "",
        "| Scout | Count | Tickers |",
        "|---|---:|---|",
    ]
    for scout_name in SCOUT_ORDER:
        symbols = list(scouts.get(scout_name, []) or [])
        tickers = ", ".join(symbols) if symbols else "None"
        lines.append(f"| {scout_name} | {len(symbols)} | {tickers} |")

    overlap = dict(summary.get("overlap") or {})
    if overlap:
        lines.extend(["", "## Overlap", ""])
        for symbol, sources in overlap.items():
            lines.append(f"- `{symbol}`: {', '.join(list(sources or []))}")
    return "\n".join(lines) + "\n"


def _build_final_handoff(summary: Mapping[str, Any]) -> Dict[str, Any]:
    tickers = [str(symbol) for symbol in list(summary.get("tickers", []) or [])]
    ticker_scouts = dict(summary.get("ticker_scouts") or {})
    return {
        "date": summary.get("date"),
        "source_stage": "scout_ticker_summary",
        "count": len(tickers),
        "tickers": tickers,
        "metadata_by_ticker": {
            symbol: {"scouts": list(ticker_scouts.get(symbol, []) or [])}
            for symbol in tickers
        },
        "contract": FINAL_TICKER_CONTRACT,
    }


def _remove_retired_artifacts(*, root: Path, base: Path) -> None:
    day_names = [
        "research_" + "queue.json",
        "short" + "list_" + "top20.json",
        "all_" + "scored_candidates.json",
        "short" + "list_" + "integrity.json",
        "deep_" + "selection_integrity.json",
    ]
    root_names = ["latest_" + "research_" + "queue.json"]
    for path in [
        *[base / name for name in day_names],
        *[root / name for name in root_names],
    ]:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _iv_symbols(rows: Iterable[Any]) -> List[Any]:
    symbols: List[Any] = []
    for row in rows:
        if isinstance(row, Mapping):
            symbols.append(row.get("ticker") or row.get("symbol"))
        else:
            symbols.append(row)
    return symbols


def _normalize_symbols(values: Iterable[Any]) -> List[str]:
    seen: set[str] = set()
    symbols: List[str] = []
    for value in values:
        symbol = _normalize_symbol(value)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
    return symbols


def _normalize_symbol(value: Any) -> str:
    symbol = str(value or "").upper().strip()
    if symbol.startswith("$"):
        symbol = symbol[1:]
    return symbol.replace(".", "-")
