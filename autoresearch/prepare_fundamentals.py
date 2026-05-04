"""Autoresearch eval harness — EDGAR XBRL fundamentals — DO NOT MODIFY.

Downloads S&P 500 XBRL company facts from EDGAR, extracts point-in-time
financial ratios at each filing date, builds sector-neutral forward return
snapshots, and provides evaluate(score_fn) for measuring Spearman rank IC.

Data leakage prevention:
  - Snapshot date = filed date (SEC acceptance), not period end
  - First filing only per (ticker, end, fp) — no restatements
  - Forward returns start T+1 (first trading day after filed date)
  - Sector-neutral: subtract sector median return

Standalone: python autoresearch/prepare_fundamentals.py
"""

import datetime as dt
import hashlib
import json
import math
import os
import time
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
from scipy import stats as sp_stats

warnings.filterwarnings("ignore")

CACHE_DIR = Path.home() / ".cache" / "autoresearch_fundamentals"
CACHE_TTL_DAYS = 7

SEC_USER_AGENT = "AeternusAgentsAG/1.0 (research@aeternus.ai)"
SEC_SLEEP = 0.15
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

HORIZONS = [20, 60, 120, 252]
VALID_FORMS = {"10-K", "10-Q"}

# S&P 500 sector map (GICS) — from Wikipedia, used for sector-neutral returns.
# Tickers not in this map get sector "Unknown".
SP500_SECTORS: Dict[str, str] = {}  # populated by load_sp500_tickers()

# Hardcoded S&P 500 fallback (subset, 100 large caps)
SP500_FALLBACK = [
    "AAPL", "ABBV", "ABT", "ACN", "ADBE", "AIG", "AMD", "AMGN", "AMT", "AMZN",
    "AVGO", "AXP", "BA", "BAC", "BK", "BKNG", "BLK", "BMY", "BRK-B", "C",
    "CAT", "CHTR", "CL", "CMCSA", "COF", "COP", "COST", "CRM", "CSCO", "CVS",
    "CVX", "DE", "DHR", "DIS", "DOW", "DUK", "EMR", "EXC", "F", "FDX",
    "GD", "GE", "GILD", "GM", "GOOG", "GOOGL", "GS", "HD", "HON", "IBM",
    "INTC", "INTU", "ISRG", "JNJ", "JPM", "KHC", "KO", "LIN", "LLY", "LMT",
    "LOW", "MA", "MCD", "MDLZ", "MDT", "MET", "META", "MMM", "MO", "MRK",
    "MS", "MSFT", "NEE", "NFLX", "NKE", "NVDA", "ORCL", "PEP", "PFE", "PG",
    "PM", "PYPL", "QCOM", "RTX", "SBUX", "SCHW", "SO", "SPG", "T", "TGT",
    "TMO", "TMUS", "TXN", "UNH", "UNP", "UPS", "USB", "V", "VZ", "WFC",
    "WMT", "XOM",
]


# ---------------------------------------------------------------------------
# SEC / data fetching
# ---------------------------------------------------------------------------

def _sec_headers() -> Dict[str, str]:
    return {
        "User-Agent": SEC_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
    }


def load_sp500_tickers() -> Tuple[List[str], Dict[str, str]]:
    """Load S&P 500 tickers + sector map from Wikipedia. Falls back to hardcoded list."""
    global SP500_SECTORS
    try:
        import ssl
        ssl._create_default_https_context = ssl._create_unverified_context
        tables = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            match="Symbol",
        )
        df = tables[0]
        tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
        if "GICS Sector" in df.columns:
            for _, row in df.iterrows():
                t = str(row["Symbol"]).replace(".", "-")
                SP500_SECTORS[t] = str(row["GICS Sector"])
        return tickers, dict(SP500_SECTORS)
    except Exception:
        return list(SP500_FALLBACK), {}


def build_ticker_cik_map(tickers: List[str]) -> Dict[str, str]:
    """SEC company_tickers.json -> {ticker: "0000320193"} (10-digit zero-padded)."""
    print("Fetching CIK map from EDGAR...")
    try:
        resp = requests.get(COMPANY_TICKERS_URL, headers=_sec_headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  CIK map fetch failed: {e}")
        return {}

    cik_map: Dict[str, str] = {}
    ticker_set = set(t.upper() for t in tickers)
    for entry in data.values():
        t = str(entry.get("ticker", "")).upper().strip()
        cik_raw = entry.get("cik_str", entry.get("cik", ""))
        if t in ticker_set and cik_raw:
            cik_map[t] = str(cik_raw).zfill(10)
    print(f"  Matched {len(cik_map)}/{len(tickers)} tickers to CIKs")
    return cik_map


def fetch_companyfacts(cik: str, ticker: str) -> Optional[dict]:
    """GET companyfacts JSON from EDGAR. Cached per-ticker with 7-day TTL."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"facts_{ticker}.json"

    if cache_path.exists():
        age_days = (time.time() - cache_path.stat().st_mtime) / 86400
        if age_days < CACHE_TTL_DAYS:
            try:
                return json.loads(cache_path.read_text())
            except Exception:
                pass

    url = COMPANY_FACTS_URL.format(cik=cik)
    time.sleep(SEC_SLEEP)
    try:
        resp = requests.get(url, headers=_sec_headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json()
        cache_path.write_text(json.dumps(data))
        return data
    except Exception:
        return None


# ---------------------------------------------------------------------------
# XBRL extraction
# ---------------------------------------------------------------------------

def _pick_entries(facts: dict, *tag_candidates: str, units: str = "USD") -> List[dict]:
    """Try XBRL tags in order, return entries from first match.
    Filter: form in {10-K, 10-Q}, deduplicate (end, fp) keeping EARLIEST filed."""
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    dei = facts.get("facts", {}).get("dei", {})

    for tag in tag_candidates:
        concept = us_gaap.get(tag) or dei.get(tag)
        if not concept:
            continue
        entries = concept.get("units", {}).get(units, [])
        if not entries:
            continue

        # Filter valid forms
        valid = [e for e in entries if e.get("form") in VALID_FORMS]
        if not valid:
            continue

        # Deduplicate: keep EARLIEST filed per (end, fp) — first filing only
        seen: Dict[Tuple[str, str], dict] = {}
        for e in sorted(valid, key=lambda x: x.get("filed", "")):
            key = (e.get("end", ""), e.get("fp", ""))
            if key not in seen:
                seen[key] = e
        return list(seen.values())

    return []


def extract_fundamentals(facts: dict) -> List[dict]:
    """Extract quarterly fundamentals from XBRL company facts.
    Returns list sorted by filed date, each with raw financial data."""
    revenue = _pick_entries(
        facts, "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
    )
    net_income = _pick_entries(facts, "NetIncomeLoss")
    eps = _pick_entries(
        facts, "EarningsPerShareDiluted", "EarningsPerShareBasic",
        units="USD/shares",
    )
    assets = _pick_entries(facts, "Assets")
    equity = _pick_entries(
        facts, "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    )
    ocf = _pick_entries(facts, "NetCashProvidedByUsedInOperatingActivities")
    gross_profit = _pick_entries(facts, "GrossProfit")
    shares = _pick_entries(
        facts,
        "CommonStockSharesOutstanding",
        "EntityCommonStockSharesOutstanding",
        units="shares",
    )

    # Index by (end, fp) for joining
    def _index(entries: List[dict]) -> Dict[Tuple[str, str], dict]:
        idx: Dict[Tuple[str, str], dict] = {}
        for e in entries:
            key = (e.get("end", ""), e.get("fp", ""))
            if key not in idx:
                idx[key] = e
        return idx

    rev_idx = _index(revenue)
    ni_idx = _index(net_income)
    eps_idx = _index(eps)
    asset_idx = _index(assets)
    eq_idx = _index(equity)
    ocf_idx = _index(ocf)
    gp_idx = _index(gross_profit)
    sh_idx = _index(shares)

    # Use revenue as the primary timeline (most companies report it)
    # Fall back to net_income if revenue is empty
    primary = rev_idx if rev_idx else ni_idx
    if not primary:
        return []

    quarters: List[dict] = []
    for key in primary:
        ref = primary[key]
        filed = ref.get("filed", "")
        end = ref.get("end", "")
        fp = ref.get("fp", "")
        fy = ref.get("fy")

        if not filed or not end:
            continue
        # Only quarterly or annual
        if fp not in ("Q1", "Q2", "Q3", "Q4", "FY"):
            continue

        q = {
            "filed": filed,
            "period_end": end,
            "fy": fy,
            "fp": fp,
            "revenue": rev_idx.get(key, {}).get("val"),
            "net_income": ni_idx.get(key, {}).get("val"),
            "eps": eps_idx.get(key, {}).get("val"),
            "assets": asset_idx.get(key, {}).get("val"),
            "equity": eq_idx.get(key, {}).get("val"),
            "ocf": ocf_idx.get(key, {}).get("val"),
            "gross_profit": gp_idx.get(key, {}).get("val"),
            "shares_out": sh_idx.get(key, {}).get("val"),
        }
        quarters.append(q)

    quarters.sort(key=lambda x: x["filed"])
    return quarters


# ---------------------------------------------------------------------------
# Ratio computation
# ---------------------------------------------------------------------------

def _safe_div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _safe_growth(current: Optional[float], prior: Optional[float]) -> Optional[float]:
    if current is None or prior is None or prior == 0:
        return None
    return (current - prior) / abs(prior)


def compute_ratios(quarters: List[dict], idx: int, price: Optional[float] = None) -> Dict[str, Optional[float]]:
    """Compute financial ratios for quarter at idx, using prior quarters for YoY."""
    q = quarters[idx]
    ratios: Dict[str, Optional[float]] = {}

    # Find the quarter 4 periods ago (YoY)
    q4_ago = quarters[idx - 4] if idx >= 4 else None

    # Revenue growth YoY
    ratios["revenue_growth_yoy"] = _safe_growth(
        q.get("revenue"), q4_ago.get("revenue") if q4_ago else None,
    )

    # Gross margin
    ratios["gross_margin"] = _safe_div(q.get("gross_profit"), q.get("revenue"))

    # Net margin
    ratios["net_margin"] = _safe_div(q.get("net_income"), q.get("revenue"))

    # Margin expansion (current gross_margin - 4q ago gross_margin)
    if q4_ago:
        gm_now = _safe_div(q.get("gross_profit"), q.get("revenue"))
        gm_ago = _safe_div(q4_ago.get("gross_profit"), q4_ago.get("revenue"))
        if gm_now is not None and gm_ago is not None:
            ratios["margin_expansion"] = gm_now - gm_ago
        else:
            ratios["margin_expansion"] = None
    else:
        ratios["margin_expansion"] = None

    # ROE: net_income_ttm / avg(equity)
    # TTM = sum of last 4 quarters' net income
    if idx >= 3:
        ni_ttm = sum(
            quarters[i].get("net_income", 0) or 0
            for i in range(idx - 3, idx + 1)
        )
        eq_now = q.get("equity")
        eq_ago = quarters[idx - 3].get("equity")
        if eq_now and eq_ago:
            avg_eq = (eq_now + eq_ago) / 2
            ratios["roe"] = _safe_div(ni_ttm, avg_eq)
        else:
            ratios["roe"] = None
    else:
        ratios["roe"] = None

    # ROA: net_income_ttm / avg(assets)
    if idx >= 3:
        ni_ttm = sum(
            quarters[i].get("net_income", 0) or 0
            for i in range(idx - 3, idx + 1)
        )
        a_now = q.get("assets")
        a_ago = quarters[idx - 3].get("assets")
        if a_now and a_ago:
            avg_a = (a_now + a_ago) / 2
            ratios["roa"] = _safe_div(ni_ttm, avg_a)
        else:
            ratios["roa"] = None
    else:
        ratios["roa"] = None

    # Debt-to-equity: (assets - equity) / equity
    assets_val = q.get("assets")
    equity_val = q.get("equity")
    if assets_val and equity_val and equity_val > 0:
        ratios["debt_to_equity"] = (assets_val - equity_val) / equity_val
    else:
        ratios["debt_to_equity"] = None

    # FCF yield: (ocf - capex_proxy) / market_cap
    # capex_proxy = assets growth (simple proxy, since CapEx isn't always in XBRL)
    ocf_val = q.get("ocf")
    shares_val = q.get("shares_out")
    if ocf_val is not None and shares_val and price and price > 0:
        market_cap = shares_val * price
        # Simple FCF proxy: just use OCF (CapEx data unreliable in XBRL)
        ratios["fcf_yield"] = ocf_val / market_cap if market_cap > 0 else None
    else:
        ratios["fcf_yield"] = None

    # Earnings momentum: (eps - eps_4q_ago) / abs(eps_4q_ago)
    ratios["earnings_momentum"] = _safe_growth(
        q.get("eps"), q4_ago.get("eps") if q4_ago else None,
    )

    # Accrual quality: (net_income - ocf) / assets (lower = better)
    ni = q.get("net_income")
    ocf_q = q.get("ocf")
    assets_q = q.get("assets")
    if ni is not None and ocf_q is not None and assets_q and assets_q > 0:
        ratios["accrual_quality"] = (ni - ocf_q) / assets_q
    else:
        ratios["accrual_quality"] = None

    # Dilution: shares growth YoY (lower = better)
    ratios["dilution"] = _safe_growth(
        q.get("shares_out"), q4_ago.get("shares_out") if q4_ago else None,
    )

    return ratios


# ---------------------------------------------------------------------------
# Snapshot building
# ---------------------------------------------------------------------------

def _get_close_on_or_before(close: pd.Series, date_str: str) -> Optional[float]:
    """Get the closing price on or just before a date."""
    ts = pd.Timestamp(date_str)
    before = close[close.index <= ts]
    if before.empty:
        return None
    return float(before.iloc[-1])


def _forward_return(close: pd.Series, filed_date: str, horizon: int) -> Optional[float]:
    """Forward return starting T+1 from filed date."""
    ts = pd.Timestamp(filed_date)
    future = close[close.index > ts]
    if future.empty or len(future) <= horizon:
        return None
    entry = float(future.iloc[0])
    if entry <= 0:
        return None
    return (float(future.iloc[horizon]) - entry) / entry


def build_filing_snapshots(
    all_fundamentals: Dict[str, List[dict]],
    close_map: Dict[str, pd.Series],
    sector_map: Dict[str, str],
) -> List[dict]:
    """Group filings by quarter-end window, compute ratios + sector-neutral returns.

    Each snapshot = one earnings season window (~45 days after quarter end).
    """
    # Collect all filings with their ratios
    filing_events: List[dict] = []
    for ticker, quarters in all_fundamentals.items():
        close = close_map.get(ticker)
        for idx in range(4, len(quarters)):  # need 4 prior quarters
            q = quarters[idx]
            filed = q["filed"]

            # Point-in-time price at filing date
            price = _get_close_on_or_before(close, filed) if close is not None else None

            ratios = compute_ratios(quarters, idx, price)
            # Need at least 3 non-None ratios to be useful
            non_none = sum(1 for v in ratios.values() if v is not None)
            if non_none < 3:
                continue

            filing_events.append({
                "ticker": ticker,
                "filed": filed,
                "period_end": q["period_end"],
                "ratios": ratios,
                "sector": sector_map.get(ticker, "Unknown"),
            })

    if not filing_events:
        return []

    # Sort by filed date
    filing_events.sort(key=lambda x: x["filed"])

    # Group into quarterly windows (cluster filings within 45 days of each other)
    snapshots: List[dict] = []
    window_start = filing_events[0]["filed"]
    window_events: List[dict] = []

    for event in filing_events:
        days_diff = (
            dt.datetime.strptime(event["filed"], "%Y-%m-%d")
            - dt.datetime.strptime(window_start, "%Y-%m-%d")
        ).days
        if days_diff > 45 and window_events:
            snapshot = _build_single_snapshot(window_events, close_map, sector_map)
            if snapshot:
                snapshots.append(snapshot)
            window_events = [event]
            window_start = event["filed"]
        else:
            window_events.append(event)

    # Last window
    if window_events:
        snapshot = _build_single_snapshot(window_events, close_map, sector_map)
        if snapshot:
            snapshots.append(snapshot)

    return snapshots


def _build_single_snapshot(
    events: List[dict],
    close_map: Dict[str, pd.Series],
    sector_map: Dict[str, str],
) -> Optional[dict]:
    """Build one snapshot from a cluster of filing events."""
    if len(events) < 5:
        return None

    # Use the median filed date as the snapshot date
    filed_dates = sorted(e["filed"] for e in events)
    snapshot_date = filed_dates[len(filed_dates) // 2]

    # Build fundamentals dict: {ticker: ratios}
    fundamentals: Dict[str, Dict[str, Optional[float]]] = {}
    for e in events:
        fundamentals[e["ticker"]] = e["ratios"]

    # Compute forward returns (sector-neutral)
    fwd_returns: Dict[str, Dict[str, float]] = {f"forward_{h}d": {} for h in HORIZONS}

    # First pass: raw returns
    raw_returns: Dict[str, Dict[str, float]] = {f"forward_{h}d": {} for h in HORIZONS}
    for e in events:
        ticker = e["ticker"]
        close = close_map.get(ticker)
        if close is None:
            continue
        for h in HORIZONS:
            r = _forward_return(close, e["filed"], h)
            if r is not None:
                raw_returns[f"forward_{h}d"][ticker] = r

    # Second pass: subtract sector median for sector neutrality
    for h in HORIZONS:
        key = f"forward_{h}d"
        raw = raw_returns[key]
        if not raw:
            continue

        # Group by sector
        sector_returns: Dict[str, List[float]] = {}
        for t, r in raw.items():
            sec = sector_map.get(t, "Unknown")
            sector_returns.setdefault(sec, []).append(r)

        # Sector medians
        sector_medians: Dict[str, float] = {}
        for sec, rets in sector_returns.items():
            sorted_rets = sorted(rets)
            n = len(sorted_rets)
            sector_medians[sec] = sorted_rets[n // 2]

        # Subtract sector median
        for t, r in raw.items():
            sec = sector_map.get(t, "Unknown")
            fwd_returns[key][t] = r - sector_medians.get(sec, 0.0)

    return {
        "date": snapshot_date,
        "fundamentals": fundamentals,
        **fwd_returns,
    }


# ---------------------------------------------------------------------------
# Evaluation API
# ---------------------------------------------------------------------------

def spearman_ic(scores: List[float], returns: List[float]) -> Optional[float]:
    if len(scores) < 5:
        return None
    pairs = [(s, r) for s, r in zip(scores, returns) if math.isfinite(s) and math.isfinite(r)]
    if len(pairs) < 5:
        return None
    s_vals, r_vals = zip(*pairs)
    corr, _ = sp_stats.spearmanr(s_vals, r_vals)
    if math.isnan(corr):
        return None
    return round(corr, 4)


def _stats(vals: List[float]) -> Tuple[float, float, float]:
    if not vals:
        return 0.0, 0.0, 0.0
    n = len(vals)
    m = sum(vals) / n
    std = (sum((v - m) ** 2 for v in vals) / max(n - 1, 1)) ** 0.5
    t = (m / (std / math.sqrt(n))) if std > 0 else 0.0
    hr = sum(1 for v in vals if v > 0) / n
    return round(m, 4), round(t, 2), round(hr, 4)


def evaluate(score_fn) -> dict:
    """Run score_fn against quarterly filing snapshots, return IC stats.

    Args:
        score_fn: callable(fundamentals: dict[ticker, dict[ratio, value]]) -> dict[ticker, float]
    Returns:
        dict with mean_ic_{20,60,120,252}d, t_stat_*, hit_rate_*, n_snapshots, etc.
    """
    # Import price download from the scoring harness
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from prepare import download_bulk, extract_series

    tickers, sector_map = load_sp500_tickers()
    cik_map = build_ticker_cik_map(tickers)

    # Check for cached snapshots
    snap_hash = hashlib.md5(
        f"{sorted(cik_map.keys())}|fundamentals".encode()
    ).hexdigest()[:12]
    snap_path = CACHE_DIR / f"snapshots_{snap_hash}.json"

    snapshots = None
    if snap_path.exists():
        age_days = (time.time() - snap_path.stat().st_mtime) / 86400
        if age_days < CACHE_TTL_DAYS:
            try:
                snapshots = json.loads(snap_path.read_text())
                print(f"Loaded {len(snapshots)} cached fundamental snapshots.")
            except Exception:
                snapshots = None

    if snapshots is None:
        print(f"Fetching EDGAR XBRL data for {len(cik_map)} tickers...")
        all_fundamentals: Dict[str, List[dict]] = {}
        fetched = 0
        for ticker, cik in sorted(cik_map.items()):
            facts = fetch_companyfacts(cik, ticker)
            if facts:
                quarters = extract_fundamentals(facts)
                if len(quarters) >= 5:
                    all_fundamentals[ticker] = quarters
            fetched += 1
            if fetched % 50 == 0:
                print(f"  Fetched {fetched}/{len(cik_map)}...")

        print(f"  {len(all_fundamentals)} tickers with sufficient fundamental data")

        # Download price data
        price_tickers = list(all_fundamentals.keys())
        raw_df = download_bulk(price_tickers, days=2000)  # ~8 years for YoY
        if raw_df is None:
            return {"error": "no price data"}

        close_map: Dict[str, pd.Series] = {}
        for sym in price_tickers:
            c = extract_series(raw_df, sym, "Close")
            if c is not None and not c.empty:
                if hasattr(c.index, "tz") and c.index.tz is not None:
                    c.index = c.index.tz_localize(None)
                close_map[sym] = c

        print(f"  {len(close_map)} tickers with price data")
        print("Building filing snapshots...")
        snapshots = build_filing_snapshots(all_fundamentals, close_map, sector_map)
        print(f"  Built {len(snapshots)} snapshots")

        # Cache
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        snap_path.write_text(json.dumps(snapshots))
        print(f"  Cached to {snap_path}")

    # Evaluate
    ic_by_horizon: Dict[str, List[float]] = {f"{h}d": [] for h in HORIZONS}
    ticker_counts: List[int] = []

    for snap in snapshots:
        scores = score_fn(snap["fundamentals"])
        ticker_counts.append(len(scores))

        for h in HORIZONS:
            fwd_key = f"forward_{h}d"
            fwd = snap.get(fwd_key, {})
            common = set(scores.keys()) & set(fwd.keys())
            if len(common) >= 5:
                s_list = [scores[t] for t in common]
                r_list = [fwd[t] for t in common]
                ic = spearman_ic(s_list, r_list)
                if ic is not None:
                    ic_by_horizon[f"{h}d"].append(ic)

    result = {}
    for h in HORIZONS:
        key = f"{h}d"
        m, t, hr = _stats(ic_by_horizon[key])
        result[f"mean_ic_{key}"] = m
        result[f"t_stat_{key}"] = t
        result[f"hit_rate_{key}"] = hr

    avg_tickers = round(sum(ticker_counts) / max(len(ticker_counts), 1), 0)
    n_with_data = sum(1 for c in ticker_counts if c > 0)

    result["n_snapshots"] = len(snapshots)
    result["n_tickers_avg"] = int(avg_tickers)
    result["coverage_pct"] = round(
        len(set().union(*(snap["fundamentals"].keys() for snap in snapshots)))
        / max(len(cik_map), 1) * 100, 1
    ) if snapshots else 0.0

    # Era stability: split snapshots in half, compare IC
    half = len(snapshots) // 2
    if half > 2:
        early_ic = ic_by_horizon["60d"][:half]
        late_ic = ic_by_horizon["60d"][half:]
        e_m, _, _ = _stats(early_ic)
        l_m, _, _ = _stats(late_ic)
        result["era_stability"] = round(min(e_m, l_m) / max(abs(max(e_m, l_m)), 0.0001), 2)
    else:
        result["era_stability"] = 0.0

    return result


# ---------------------------------------------------------------------------
# Standalone sanity check
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    def uniform_scorer(fundamentals):
        return {ticker: 50.0 for ticker in fundamentals}

    print("Autoresearch fundamentals harness — sanity check")
    print("Running uniform scorer (IC should be ~0.0)...\n")
    results = evaluate(uniform_scorer)
    print("\n---")
    for k, v in results.items():
        fmt = f"{v:.4f}" if isinstance(v, float) else str(v)
        print(f"{k + ':':20s} {fmt}")
    print("\nExpected: mean_ic ≈ 0.0 (uniform scores carry no information)")
