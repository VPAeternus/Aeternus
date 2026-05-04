"""Insider Sweep Scout — Discovery-first Form 4 EDGAR sweep.

Sweeps ALL SEC Form 4 filings daily, stores C-suite purchases AND sales
in a rolling 30-day window, detects clusters, and feeds signals into
the pipeline.

Architecture shift: old connector hit EDGAR per-ticker (slow, broken URL,
wrong parser). New design sweeps ALL filings once per day, stores results
in a rolling JSON file, then the connector reads the store instantly.

Data source: EDGAR EFTS Search API + Form 4 XML (free, 10 req/s limit)
"""

from __future__ import annotations

import datetime as dt
import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

from ..contracts import DealFlowSignal, UniverseRow

ROLLING_STORE_PATH = "eval_results/deal_flow/insider_sweep_rolling.json"
EFTS_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
SEC_ARCHIVE_URL = (
    "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dash}/{filename}"
)


# ---------------------------------------------------------------------------
# C-suite title filter (kept from original)
# ---------------------------------------------------------------------------

def _is_csuite_title(title: str) -> bool:
    """Check if an officer title qualifies as C-suite for cluster detection."""
    title_upper = title.upper().strip()

    # Exact matches for C-level titles
    c_level_exact = {"CEO", "CFO", "COO", "CTO", "CAO", "CRO", "CMO"}
    if title_upper in c_level_exact:
        return True

    # President/Chair only if exact (not "Vice President")
    if title_upper in {"PRESIDENT", "CHAIRMAN", "CHAIR"}:
        return True

    # Starts with CHIEF (Chief Executive, Chief Financial, etc.)
    if title_upper.startswith("CHIEF"):
        return True

    return False


# ---------------------------------------------------------------------------
# Section A: Rolling Store
# ---------------------------------------------------------------------------

def _load_rolling_store() -> dict:
    """Load the rolling insider sweep store from disk."""
    path = Path(ROLLING_STORE_PATH)
    if not path.exists():
        return {"last_sweep_date": "", "transactions": []}
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return {"last_sweep_date": "", "transactions": []}
        return data
    except Exception:
        return {"last_sweep_date": "", "transactions": []}


def _save_rolling_store(store: dict) -> None:
    """Atomically write the rolling store to disk."""
    path = Path(ROLLING_STORE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(store, indent=2))
    tmp_path.replace(path)


def _prune_transactions(txns: list, window_days: int) -> list:
    """Drop transactions older than the window."""
    cutoff = (dt.datetime.now().date() - dt.timedelta(days=window_days)).isoformat()
    return [t for t in txns if str(t.get("date", "")) >= cutoff]


# ---------------------------------------------------------------------------
# Section B: EDGAR Sweep
# ---------------------------------------------------------------------------

def _sec_headers(config: Optional[Dict] = None) -> Dict[str, str]:
    """Build SEC-compliant request headers."""
    cfg = config or {}
    user_agent = str(
        cfg.get("dealflow_sec_user_agent", "")
        or "AeternusAgentsAG/1.0 (research@aeternus.ai)"
    )
    return {
        "User-Agent": user_agent,
        "Accept": "application/json, text/plain, */*",
    }


def _strip_ns(tag: str) -> str:
    """Strip XML namespace prefix."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _find_text(parent, target: str) -> str:
    """Find text of first descendant matching tag name (namespace-agnostic)."""
    for child in parent.iter():
        if _strip_ns(child.tag) == target and child.text:
            return child.text.strip()
    return ""


def _is_10b5_1(txn_node, footnotes_text: str) -> bool:
    """Check if a transaction is part of a 10b5-1 pre-scheduled plan."""
    for child in txn_node.iter():
        tag = _strip_ns(child.tag)
        if tag == "equitySwapInvolved" and (child.text or "").strip() == "1":
            return True
    if "10b5-1" in footnotes_text.lower() or "10b5" in footnotes_text.lower():
        return True
    return False


def _parse_form4_xml(xml_text: str) -> List[Dict[str, Any]]:
    """Parse a Form 4 XML document into transaction dicts.

    Returns list of dicts with keys:
        ticker, person, title, code (P/S), shares, price, date, is_10b5_1
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    # Extract issuer trading symbol
    ticker = ""
    for node in root.iter():
        if _strip_ns(node.tag) == "issuerTradingSymbol":
            ticker = (node.text or "").strip().upper()
            break
    if not ticker:
        return []

    # Extract reporting owner info
    person = ""
    title = ""
    for node in root.iter():
        tag = _strip_ns(node.tag)
        if tag == "rptOwnerName" and not person:
            person = (node.text or "").strip()
        elif tag == "officerTitle" and not title:
            title = (node.text or "").strip()

    if not _is_csuite_title(title):
        return []

    # Collect footnotes text for 10b5-1 detection
    footnotes_text = ""
    for node in root.iter():
        if _strip_ns(node.tag) == "footnote":
            footnotes_text += " " + (node.text or "")

    # Extract transactions from nonDerivativeTable
    transactions: List[Dict[str, Any]] = []
    for node in root.iter():
        if _strip_ns(node.tag) != "nonDerivativeTransaction":
            continue

        code = _find_text(node, "transactionCode")
        if code not in ("P", "S"):
            continue

        # Parse shares, price, date from nested <value> elements
        shares = 0.0
        price = 0.0
        txn_date = ""

        for child in node.iter():
            tag = _strip_ns(child.tag)
            if tag == "transactionShares":
                val = _find_text(child, "value")
                try:
                    shares = float(val.replace(",", ""))
                except (ValueError, AttributeError):
                    pass
            elif tag == "transactionPricePerShare":
                val = _find_text(child, "value")
                try:
                    price = float(val.replace(",", ""))
                except (ValueError, AttributeError):
                    pass
            elif tag == "transactionDate":
                txn_date = _find_text(child, "value")

        if shares <= 0 or price <= 0:
            continue

        transactions.append({
            "ticker": ticker,
            "person": person,
            "title": title,
            "code": code,
            "shares": shares,
            "price": price,
            "date": txn_date,
            "is_10b5_1": _is_10b5_1(node, footnotes_text),
        })

    return transactions


def scan_insider_sweep(
    sweep_date: Optional[str] = None,
    window_days: int = 30,
    dry_run: bool = False,
    config: Optional[Dict] = None,
    akg: Any = None,
) -> dict:
    """Sweep all SEC Form 4 filings for a given date, detect C-suite clusters.

    Args:
        sweep_date: Date to sweep (YYYY-MM-DD). Defaults to today.
        window_days: Rolling window in days.
        dry_run: If True, don't write files or AKG.
        config: Optional config dict.
        akg: Optional AKG instance for signal writeback.

    Returns:
        dict with: date, new_transactions, total_transactions, buy_clusters,
        sell_clusters, pages_fetched, total_filings
    """
    cfg = config or {}
    if not bool(cfg.get("dealflow_insider_cluster_enabled", True)):
        return {"date": sweep_date or "", "skipped": True, "reason": "disabled"}

    date_str = sweep_date or dt.datetime.now().date().isoformat()

    # Load rolling store
    store = _load_rolling_store()
    window = int(cfg.get("dealflow_insider_sweep_window_days", window_days))

    # Skip if already swept today
    if store.get("last_sweep_date") == date_str and not dry_run:
        return {
            "date": date_str,
            "skipped": True,
            "reason": "already_swept_today",
            "total_transactions": len(store.get("transactions", [])),
        }

    # Sweep EFTS for Form 4 filings
    headers = _sec_headers(cfg)
    sleep_seconds = float(cfg.get("dealflow_edgar_sleep_seconds", 0.15))
    new_transactions: List[Dict[str, Any]] = []
    page_size = 100
    total_filings = 0
    offset = 0
    pages_fetched = 0
    max_pages = 20  # safety cap

    while pages_fetched < max_pages:
        try:
            params = {
                "q": '""',
                "forms": "4",
                "dateRange": "custom",
                "startdt": date_str,
                "enddt": date_str,
                "from": str(offset),
            }
            resp = requests.get(
                EFTS_SEARCH_URL, params=params, headers=headers, timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            break

        hits_obj = data.get("hits", {})
        if pages_fetched == 0:
            total_val = hits_obj.get("total", {})
            if isinstance(total_val, dict):
                total_filings = int(total_val.get("value", 0))
            elif isinstance(total_val, (int, float)):
                total_filings = int(total_val)

        hit_list = hits_obj.get("hits", [])
        if not hit_list:
            break

        for hit in hit_list:
            _id = str(hit.get("_id", ""))
            source = hit.get("_source", {}) or {}

            # Extract accession and filename from _id
            if ":" in _id:
                accession, filename = _id.split(":", 1)
            else:
                accession = _id
                filename = ""

            if not accession or not filename:
                continue

            # CIK from source metadata
            cik = str(
                source.get("entity_id", "")
                or source.get("entity", "")
                or source.get("ciks", [""])[0]
                if isinstance(source.get("ciks"), list) and source.get("ciks")
                else source.get("entity_id", "")
            ).strip()
            if not cik:
                continue

            # Build XML URL
            accession_no_dash = accession.replace("-", "")
            xml_url = SEC_ARCHIVE_URL.format(
                cik=cik,
                accession_no_dash=accession_no_dash,
                filename=filename,
            )

            time.sleep(sleep_seconds)

            try:
                xml_resp = requests.get(xml_url, headers=headers, timeout=10)
                xml_resp.raise_for_status()
                xml_text = xml_resp.text
            except Exception:
                continue

            txns = _parse_form4_xml(xml_text)
            for txn in txns:
                code = txn.get("code", "")
                # Skip pre-scheduled 10b5-1 sales (not a conviction signal)
                if code == "S" and txn.get("is_10b5_1", False):
                    continue

                new_transactions.append({
                    "ticker": txn["ticker"],
                    "person": txn["person"],
                    "title": txn["title"],
                    "code": code,
                    "shares": txn["shares"],
                    "price": txn["price"],
                    "date": txn.get("date", date_str),
                    "value_usd": round(txn["shares"] * txn["price"], 2),
                })

        pages_fetched += 1
        offset += page_size
        if total_filings > 0 and offset >= total_filings:
            break

    # Merge into rolling store (unless dry_run)
    if not dry_run:
        existing = list(store.get("transactions", []))
        existing.extend(new_transactions)
        pruned = _prune_transactions(existing, window)
        store["transactions"] = pruned
        store["last_sweep_date"] = date_str
        _save_rolling_store(store)

    # Detect clusters
    all_txns = store.get("transactions", []) if not dry_run else new_transactions
    buy_clusters = _detect_clusters_from_store(all_txns, code_filter="P", min_insiders=2)
    sell_clusters = _detect_clusters_from_store(all_txns, code_filter="S", min_insiders=3)

    # Write buy clusters to AKG
    if akg is not None and not dry_run:
        for cluster in buy_clusters:
            try:
                akg.enrich_node_insider_cluster(
                    cluster["ticker"],
                    score=cluster["score"],
                    buyer_count=cluster["distinct_insiders"],
                    as_of_date=date_str,
                )
            except Exception:
                pass

        # Write sell clusters to AKG — sell pressure is a valid signal
        for cluster in sell_clusters:
            try:
                akg.enrich_node_insider_sell(
                    cluster["ticker"],
                    score=cluster["score"],
                    seller_count=cluster["distinct_insiders"],
                    as_of_date=date_str,
                )
            except Exception:
                pass

    return {
        "date": date_str,
        "new_transactions": len(new_transactions),
        "total_transactions": len(all_txns),
        "buy_clusters": buy_clusters,
        "sell_clusters": sell_clusters,
        "pages_fetched": pages_fetched,
        "total_filings": total_filings,
    }


def _detect_clusters_from_store(
    transactions: list,
    code_filter: str,
    min_insiders: int,
) -> list:
    """Group transactions by ticker and detect clusters of distinct insiders."""
    by_ticker: Dict[str, List[Dict]] = {}
    for txn in transactions:
        if txn.get("code") != code_filter:
            continue
        ticker = str(txn.get("ticker", "")).upper()
        if not ticker:
            continue
        by_ticker.setdefault(ticker, []).append(txn)

    clusters: List[Dict[str, Any]] = []
    for ticker, txns in by_ticker.items():
        persons = {t.get("person", "unknown") for t in txns}
        if len(persons) < min_insiders:
            continue

        total_value = sum(float(t.get("value_usd", 0)) for t in txns)
        n = len(persons)

        if code_filter == "P":
            # Buy cluster scores
            score = 88.0 if n >= 4 else 80.0 if n >= 3 else 72.0
        else:
            # Sell cluster scores (lower — sells are noisier)
            score = 80.0 if n >= 5 else 72.0 if n >= 4 else 65.0

        clusters.append({
            "ticker": ticker,
            "distinct_insiders": n,
            "total_value_usd": round(total_value, 2),
            "direction": "BULLISH" if code_filter == "P" else "BEARISH",
            "score": score,
            "transaction_count": len(txns),
        })

    clusters.sort(key=lambda c: -c["total_value_usd"])
    return clusters


# ---------------------------------------------------------------------------
# Section C: Connector (pipeline-compatible, reads from rolling store)
# ---------------------------------------------------------------------------

def collect_insider_cluster_signals(
    universe: Iterable[UniverseRow],
    as_of_date: Optional[str] = None,
    config: Optional[Dict] = None,
) -> List[DealFlowSignal]:
    """Detect insider cluster signals from the rolling sweep store.

    Reads the pre-swept rolling store (no network calls). The sweep runs
    as a pre-connector step in the pipeline, so the store is always fresh.
    """
    cfg = config or {}
    if not bool(cfg.get("dealflow_insider_cluster_enabled", True)):
        return []

    rows = list(universe)
    universe_symbols = {
        str(r.get("symbol", "")).upper().strip()
        for r in rows
        if r.get("symbol")
    }

    store = _load_rolling_store()
    transactions = store.get("transactions", [])

    if not transactions:
        return []

    # Filter to universe tickers
    universe_txns = [
        t for t in transactions
        if str(t.get("ticker", "")).upper() in universe_symbols
    ]

    # Group by ticker and code
    by_ticker: Dict[str, Dict[str, List[Dict]]] = {}
    for txn in universe_txns:
        ticker = str(txn.get("ticker", "")).upper()
        code = txn.get("code", "")
        by_ticker.setdefault(ticker, {}).setdefault(code, []).append(txn)

    signals: List[DealFlowSignal] = []
    emitted: set[str] = set()

    for ticker, code_groups in by_ticker.items():
        # Buy cluster: 2+ distinct insiders purchasing
        buy_txns = code_groups.get("P", [])
        buy_persons = {t.get("person", "unknown") for t in buy_txns}
        buy_total = sum(float(t.get("value_usd", 0)) for t in buy_txns)

        if len(buy_persons) >= 2:
            n = len(buy_persons)
            score = 88.0 if n >= 4 else 80.0 if n >= 3 else 72.0
            # AKG Alpha Score modulation
            try:
                from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
                akg = AeternusKnowledgeGraph.load()
                alpha_data = akg.get_insider_alpha(ticker)
                if alpha_data and not alpha_data.get("insufficient_data"):
                    alpha_score = float(alpha_data.get("alpha_score", 50.0))
                    score = score * 0.60 + alpha_score * 0.40
                    score = max(40.0, min(95.0, score))
            except Exception:
                pass
            signals.append({  # type: ignore[typeddict-unknown-key]
                "symbol": ticker,
                "signal_family": "insider_cluster",
                "raw_score": score,
                "z_score": 0.0,
                "direction": "BULLISH",
                "evidence_count": n,
                "freshness_hours": 0.0,
                "source_status": "OK",
                "source_name": "insider_sweep",
                "cluster_size": n,
                "total_value_usd": round(buy_total, 2),
            })
            emitted.add(ticker)
            continue  # Buy cluster takes precedence over sell for same ticker

        # Sell cluster: 3+ distinct insiders selling (stricter threshold)
        sell_txns = code_groups.get("S", [])
        sell_persons = {t.get("person", "unknown") for t in sell_txns}
        sell_total = sum(float(t.get("value_usd", 0)) for t in sell_txns)

        if len(sell_persons) >= 3:
            n = len(sell_persons)
            score = 80.0 if n >= 5 else 72.0 if n >= 4 else 65.0
            # AKG Alpha Score modulation
            try:
                from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
                akg = AeternusKnowledgeGraph.load()
                alpha_data = akg.get_insider_alpha(ticker)
                if alpha_data and not alpha_data.get("insufficient_data"):
                    alpha_score = float(alpha_data.get("alpha_score", 50.0))
                    score = score * 0.60 + alpha_score * 0.40
                    score = max(40.0, min(95.0, score))
            except Exception:
                pass
            signals.append({  # type: ignore[typeddict-unknown-key]
                "symbol": ticker,
                "signal_family": "insider_cluster",
                "raw_score": score,
                "z_score": 0.0,
                "direction": "BEARISH",
                "evidence_count": n,
                "freshness_hours": 0.0,
                "source_status": "OK",
                "source_name": "insider_sweep",
                "cluster_size": n,
                "total_value_usd": round(sell_total, 2),
            })
            emitted.add(ticker)

    return signals
