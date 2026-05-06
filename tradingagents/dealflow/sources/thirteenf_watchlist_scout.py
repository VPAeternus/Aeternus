"""13F watchlist scout — turns top-manager 13F changes into dealflow candidates."""

from __future__ import annotations

import datetime as dt
import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from tradingagents.backtesting.thirteenf.history import build_13f_deltas, fetch_historical_13f_holdings
from tradingagents.dealflow.scout_audit import append_scout_audit

DEFAULT_WATCHLIST_SUMMARY = Path("eval_results/13f/proper_manager_backtest_296/backtest/top15_watchlist_summary.json")
DEFAULT_APPROVED_SEED = Path("eval_results/13f/manager_scan_quality_probe/proper_manager_stage/approved_manager_seed.json")
DEFAULT_GLOBAL_SEED = Path("tradingagents/backtesting/thirteenf/managers_seed.json")
DEFAULT_CUSIP_MAP = Path("tradingagents/backtesting/thirteenf/cusip_ticker_seed.json")
DEFAULT_CACHE_DIR = Path("eval_results/13f/cache/sec")


def scan_thirteenf_watchlist(
    *,
    as_of_date: Optional[str] = None,
    dry_run: bool = False,
    max_filings_per_manager: int = 6,
    min_value_usd: float = 10_000_000.0,
    watchlist_summary_path: Path | str = DEFAULT_WATCHLIST_SUMMARY,
    approved_seed_path: Path | str = DEFAULT_APPROVED_SEED,
    global_seed_path: Path | str = DEFAULT_GLOBAL_SEED,
    cusip_map_path: Path | str = DEFAULT_CUSIP_MAP,
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
    akg: Any = None,
) -> Dict[str, Any]:
    """Fetch/update Top-15 watchlist 13Fs and emit latest new/add candidates."""
    date_str = as_of_date or dt.date.today().isoformat()
    out_dir = Path("eval_results") / "deal_flow" / date_str
    out_dir.mkdir(parents=True, exist_ok=True)

    watchlist = _load_json(Path(watchlist_summary_path)) or {}
    manager_ids = [str(row.get("manager_id", "")) for row in watchlist.get("managers", []) if row.get("manager_id")]
    if not manager_ids:
        return _empty(date_str, "no_watchlist_managers")

    managers = _resolve_managers(manager_ids, [Path(approved_seed_path), Path(global_seed_path)])
    if not managers:
        return _empty(date_str, "no_manager_seed_matches")

    seed_path = out_dir / "13f_watchlist_manager_seed.json"
    seed_path.write_text(json.dumps(managers, indent=2))
    history_dir = out_dir / "13f_watchlist_history"
    holdings_path = history_dir / "holdings_raw.csv"
    delta_path = history_dir / "holdings_delta.csv"

    if dry_run:
        fetch_manifest = {"dry_run": True, "manager_count": len(managers)}
        delta_manifest = {"dry_run": True}
        delta_rows: List[Dict[str, Any]] = []
    else:
        fetch_manifest = fetch_historical_13f_holdings(
            manager_seed_path=seed_path,
            out_path=holdings_path,
            cusip_ticker_map=_load_cusip_map(Path(cusip_map_path)),
            max_filings_per_manager=max_filings_per_manager,
            cache_dir=cache_dir,
        )
        delta_manifest = build_13f_deltas(
            holdings_path=holdings_path,
            out_path=delta_path,
            min_value_usd=min_value_usd,
            resolved_only=True,
        )
        delta_rows = _read_records(delta_path)

    manager_quality = {str(row.get("manager_id", "")): row for row in watchlist.get("managers", [])}
    candidates = _latest_change_candidates(delta_rows, manager_quality)
    symbols = sorted({row["ticker"] for row in candidates})
    payload = {
        "as_of_date": date_str,
        "scout": "thirteenf_watchlist",
        "policy_id": ((watchlist.get("policy") or {}).get("policy_id") or "top15_180d_excess_v1"),
        "manager_count": len(managers),
        "candidate_count": len(candidates),
        "symbols": symbols,
        "candidates": candidates,
        "fetch_manifest": fetch_manifest,
        "delta_manifest": delta_manifest,
    }
    (out_dir / "13f_watchlist_candidates.json").write_text(json.dumps(payload, indent=2, default=str))

    if not dry_run:
        _write_akg(candidates, akg=akg)

    append_scout_audit(
        scout="thirteenf_watchlist",
        as_of_date=date_str,
        symbols=symbols,
        records=candidates,
        metadata={"policy_id": payload["policy_id"], "manager_count": len(managers)},
    )
    return payload


def _latest_change_candidates(delta_rows: List[Dict[str, Any]], manager_quality: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    latest_report_by_manager: Dict[str, str] = {}
    for row in delta_rows:
        mid = str(row.get("manager_id", ""))
        latest_report_by_manager[mid] = max(latest_report_by_manager.get(mid, ""), str(row.get("report_date", "")))

    out: List[Dict[str, Any]] = []
    for row in delta_rows:
        mid = str(row.get("manager_id", ""))
        ticker = str(row.get("ticker", "")).upper().strip()
        if not ticker or str(row.get("report_date", "")) != latest_report_by_manager.get(mid):
            continue
        shares = _float(row.get("shares"))
        if shares <= 0:
            continue
        is_new = _bool(row.get("is_new_position"))
        is_add = _bool(row.get("is_add"))
        if not (is_new or is_add):
            continue
        q = manager_quality.get(mid, {})
        avg180 = _float(q.get("avg_excess_return_180d"))
        score = max(0.0, min(100.0, 50.0 + avg180 * 100.0))
        out.append({
            "ticker": ticker,
            "symbol": ticker,
            "manager_id": mid,
            "manager_name": row.get("manager_name", ""),
            "manager_special_watchlist": bool(q.get("special_watchlist")),
            "action": "new" if is_new else "add",
            "filing_date": row.get("filing_date", ""),
            "report_date": row.get("report_date", ""),
            "issuer_name": row.get("issuer_name", ""),
            "market_value": _float(row.get("market_value")),
            "delta_market_value": _float(row.get("delta_market_value")),
            "shares": shares,
            "delta_shares": _float(row.get("delta_shares")),
            "manager_avg_excess_180d": avg180,
            "score": round(score, 4),
            "source": "thirteenf_watchlist",
        })
    out.sort(key=lambda row: (-float(row.get("score", 0)), str(row.get("ticker", ""))))
    return out


def _write_akg(candidates: List[Dict[str, Any]], *, akg: Any = None) -> None:
    if not candidates:
        return
    save_after = False
    if akg is None:
        try:
            from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
            akg = AeternusKnowledgeGraph.load()
            save_after = True
        except Exception:
            return
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    for row in candidates:
        ticker = row["ticker"]
        akg.add_node(ticker, node_type="company", metadata={"seed_sources": ["thirteenf_watchlist"], "discovered_at": now_iso})
        node = akg._nodes.get(ticker, {})
        node["signal_smart_money_score"] = max(float(node.get("signal_smart_money_score") or 0), float(row.get("score") or 0))
        node["thirteenf_watchlist_last_seen"] = str(row.get("filing_date") or now_iso)
        node["thirteenf_watchlist_manager"] = str(row.get("manager_name", ""))
        node["thirteenf_watchlist_action"] = str(row.get("action", ""))
        try:
            akg.compute_emergence_score(ticker)
        except Exception:
            pass
    if save_after and hasattr(akg, "save"):
        akg.save()


def _resolve_managers(manager_ids: List[str], seed_paths: List[Path]) -> List[Dict[str, Any]]:
    wanted = set(manager_ids)
    by_id: Dict[str, Dict[str, Any]] = {}
    for path in seed_paths:
        rows = _load_json(path) or []
        if not isinstance(rows, list):
            continue
        for row in rows:
            mid = str(row.get("manager_id", ""))
            if mid in wanted and mid not in by_id:
                by_id[mid] = row
    return [by_id[mid] for mid in manager_ids if mid in by_id]


def _load_cusip_map(path: Path) -> Dict[str, str]:
    payload = _load_json(path) or {}
    return {str(k).upper(): str(v).upper() for k, v in dict(payload).items()}


def _read_records(path: Path) -> List[Dict[str, Any]]:
    import pandas as pd
    if not path.exists():
        return []
    return pd.read_csv(path, low_memory=False).fillna("").to_dict("records")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _float(raw: Any) -> float:
    try:
        return float(raw)
    except Exception:
        return 0.0


def _bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"1", "true", "yes"}


def _empty(as_of_date: str, reason: str) -> Dict[str, Any]:
    return {"as_of_date": as_of_date, "scout": "thirteenf_watchlist", "reason": reason, "candidate_count": 0, "symbols": [], "candidates": []}
