"""
Insider Alpha Score Backtest
Computes per-ticker insider buying predictiveness from 5 years of SEC Form 4 data.

For each S&P 500 ticker:
  1. Fetches Form 4 insider purchase filings from EDGAR (free, no API key)
  2. Measures forward returns at 5d/10d/20d/30d after each open-market buy
  3. Computes an Alpha Score (0-100) reflecting the predictiveness of insider buying

Usage: python3 scripts/backtest_insider_alpha.py
Output:
  eval_results/insider_alpha_scores.json
  eval_results/insider_alpha_scores.csv
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import datetime as dt
import json
import math
import time
import warnings
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
import yfinance as yf

warnings.filterwarnings("ignore")

# Reuse Form 4 XML parser from existing infrastructure
from tradingagents.dealflow.sources.sec_catalyst import _parse_form4_transactions

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EDGAR_HEADERS = {"User-Agent": "AeternusAgentsAG/1.0 (research@aeternus.ai)"}
EDGAR_DELAY_S = 0.15        # EDGAR politeness limit
EDGAR_RETRY_WAIT_S = 2.0    # Wait on 429
MAX_FILINGS_PER_TICKER = 200
LOOKBACK_YEARS = 5
MIN_BUYS_REQUIRED = 5
HORIZONS = [5, 10, 20, 30]  # forward return windows in trading days
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval_results")

COMPUTED_DATE = dt.date.today().strftime("%Y-%m-%d")
CUTOFF_DATE = (dt.date.today() - dt.timedelta(days=LOOKBACK_YEARS * 365)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Progress helpers
# ---------------------------------------------------------------------------

def _progress_print(i: int, n: int, ticker: str) -> None:
    """Print progress every 10 tickers if tqdm is not available."""
    if i % 10 == 0 or i == n - 1:
        print(f"  Processing {i + 1}/{n}: {ticker}")


try:
    from tqdm import tqdm
    _HAS_TQDM = True
except ImportError:
    _HAS_TQDM = False


# ---------------------------------------------------------------------------
# Step 1: Load S&P 500 tickers
# ---------------------------------------------------------------------------

def load_sp500_tickers() -> List[str]:
    """Fetch S&P 500 constituent tickers from Wikipedia."""
    print("Loading S&P 500 tickers from Wikipedia...")
    try:
        sp500 = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")[0]
        tickers = sp500["Symbol"].str.replace(".", "-", regex=False).tolist()
        print(f"  Loaded {len(tickers)} S&P 500 tickers")
        return tickers
    except Exception as e:
        print(f"  Warning: could not load from Wikipedia ({e}), using fallback list")
        # Fallback: representative subset
        return [
            "AAPL", "MSFT", "AMZN", "NVDA", "META", "GOOGL", "AVGO", "TSLA", "COST",
            "NFLX", "AMD", "ADBE", "PEP", "CSCO", "QCOM", "INTU", "TXN", "AMGN",
            "AMAT", "BKNG", "MU", "LRCX", "ADI", "KLAC", "GILD", "REGN", "MELI",
            "PYPL", "VRTX", "CRWD", "MRVL", "ABNB", "WDAY", "ADSK", "CRM", "NOW",
            "SNOW", "COIN", "SHOP", "NET", "PLTR", "UBER", "JPM", "BAC", "GS", "MS",
            "V", "MA", "WMT", "UNH", "JNJ", "PFE", "MRK", "ABBV", "LLY", "BMY",
        ]


# ---------------------------------------------------------------------------
# Step 2: CIK lookup
# ---------------------------------------------------------------------------

def load_cik_map() -> Dict[str, str]:
    """
    Fetch EDGAR company tickers JSON (one call) and build ticker → zero-padded CIK dict.
    Returns dict: ticker (uppercase) → CIK (10-digit zero-padded string).
    """
    print("Fetching CIK map from EDGAR...")
    url = "https://www.sec.gov/files/company_tickers.json"
    try:
        resp = requests.get(url, headers=EDGAR_HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        cik_map: Dict[str, str] = {}
        for entry in data.values():
            ticker = str(entry.get("ticker", "")).upper().strip()
            cik_raw = entry.get("cik_str", entry.get("cik", ""))
            if ticker and cik_raw:
                cik_map[ticker] = str(cik_raw).zfill(10)
        print(f"  Loaded {len(cik_map)} CIK entries")
        return cik_map
    except Exception as e:
        print(f"  Error loading CIK map: {e}")
        return {}


# ---------------------------------------------------------------------------
# Step 3: Fetch Form 4 filings per ticker
# ---------------------------------------------------------------------------

def _get_with_retry(url: str, headers: Dict[str, str], timeout: float = 20.0) -> Optional[requests.Response]:
    """GET with a single 429 retry."""
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 429:
            time.sleep(EDGAR_RETRY_WAIT_S)
            resp = requests.get(url, headers=headers, timeout=timeout)
        return resp
    except Exception:
        return None


def fetch_form4_purchases(ticker: str, cik_padded: str) -> List[Dict[str, Any]]:
    """
    Fetch recent Form 4 filings for a ticker's CIK, parse open-market purchases,
    and return a list of purchase dicts: {date, shares, price, value_usd, owner_name}.

    Capped at MAX_FILINGS_PER_TICKER to keep runtime reasonable.
    """
    cik_numeric = cik_padded.lstrip("0") or "0"
    purchases: List[Dict[str, Any]] = []

    # Fetch submission history
    submissions_url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    time.sleep(EDGAR_DELAY_S)
    resp = _get_with_retry(submissions_url, EDGAR_HEADERS)
    if resp is None or resp.status_code != 200:
        return purchases

    try:
        sub_data = resp.json()
    except Exception:
        return purchases

    recent = sub_data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    accession_numbers = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    if not forms:
        return purchases

    # Filter to Form 4 filings within last 5 years
    form4_filings: List[Tuple[str, str, str]] = []  # (date, accession, primary_doc)
    for i, form in enumerate(forms):
        if form != "4":
            continue
        fdate = filing_dates[i] if i < len(filing_dates) else ""
        if fdate < CUTOFF_DATE:
            continue
        acc = accession_numbers[i] if i < len(accession_numbers) else ""
        pdoc = primary_docs[i] if i < len(primary_docs) else ""
        if acc:
            form4_filings.append((fdate, acc, pdoc))
        if len(form4_filings) >= MAX_FILINGS_PER_TICKER:
            break

    for filing_date, accession, primary_doc in form4_filings:
        # Normalize accession number — EDGAR submissions API returns dashed format
        acc_path = accession.replace("-", "")

        # Extract just the filename from primary_doc (may be "xslF345X05/filename.xml")
        primary_doc_basename = primary_doc.split("/")[-1] if primary_doc else ""

        # Try to fetch the XML — first try primary document name, then index
        xml_text = None

        # Attempt 1: fetch primary document directly using basename only
        if primary_doc_basename and primary_doc_basename.lower().endswith(".xml"):
            xml_url = (
                f"https://www.sec.gov/Archives/edgar/data/"
                f"{cik_numeric}/{acc_path}/{primary_doc_basename}"
            )
            time.sleep(EDGAR_DELAY_S)
            xml_resp = _get_with_retry(xml_url, EDGAR_HEADERS)
            if xml_resp is not None and xml_resp.status_code == 200:
                xml_text = xml_resp.text

        # Attempt 2: fetch the filing index and pick the first .xml file
        if xml_text is None:
            index_url = (
                f"https://www.sec.gov/Archives/edgar/data/"
                f"{cik_numeric}/{acc_path}/index.json"
            )
            time.sleep(EDGAR_DELAY_S)
            idx_resp = _get_with_retry(index_url, EDGAR_HEADERS)
            if idx_resp is not None and idx_resp.status_code == 200:
                try:
                    idx_data = idx_resp.json()
                    items = idx_data.get("directory", {}).get("item", [])
                    for item in items:
                        name = item.get("name", "")
                        # Pick any .xml file in the filing folder
                        if name.lower().endswith(".xml"):
                            xml_url = (
                                f"https://www.sec.gov/Archives/edgar/data/"
                                f"{cik_numeric}/{acc_path}/{name}"
                            )
                            time.sleep(EDGAR_DELAY_S)
                            xml_resp2 = _get_with_retry(xml_url, EDGAR_HEADERS)
                            if xml_resp2 is not None and xml_resp2.status_code == 200:
                                xml_text = xml_resp2.text
                                break
                except Exception:
                    pass

        if xml_text is None:
            continue

        # Parse transactions
        try:
            txns = _parse_form4_transactions(xml_text)
        except Exception:
            continue

        for txn in txns:
            if str(txn.get("transaction_code", "")).strip().upper() != "P":
                continue
            if txn.get("value_usd", 0) <= 0 or txn.get("shares", 0) <= 0:
                continue
            purchases.append({
                "date": filing_date,  # Use filing date as proxy for transaction date
                "shares": txn["shares"],
                "price": txn["price"],
                "value_usd": txn["value_usd"],
                "owner_name": txn.get("owner_name", ""),
            })

    return purchases


# ---------------------------------------------------------------------------
# Step 4: Forward returns
# ---------------------------------------------------------------------------

def compute_forward_returns(
    ticker: str,
    purchases: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Fetch 6y price history once and attach forward returns to each purchase.
    Returns enriched purchase list with fwd_5d, fwd_10d, fwd_20d, fwd_30d keys.
    """
    try:
        hist = yf.download(ticker, period="6y", interval="1d", progress=False, auto_adjust=True)
        if hist is None or hist.empty:
            return []

        # Flatten MultiIndex columns if present
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)

        # Ensure timezone-naive DatetimeIndex
        if hasattr(hist.index, "tz") and hist.index.tz is not None:
            hist.index = hist.index.tz_localize(None)

        closes = hist["Close"].dropna()
        if len(closes) < 35:
            return []

        dates_sorted = closes.index.sort_values()
        enriched: List[Dict[str, Any]] = []

        for purchase in purchases:
            try:
                purchase_date = pd.Timestamp(purchase["date"])
                # Find entry price: closing price on or after the purchase date
                future_dates = dates_sorted[dates_sorted >= purchase_date]
                if len(future_dates) == 0:
                    continue
                entry_date = future_dates[0]
                entry_idx = dates_sorted.get_loc(entry_date)
                entry_price = closes.iloc[entry_idx]
                if entry_price <= 0:
                    continue

                fwd_returns: Dict[str, Optional[float]] = {}
                for h in HORIZONS:
                    fwd_idx = entry_idx + h
                    if fwd_idx < len(closes):
                        fwd_price = closes.iloc[fwd_idx]
                        fwd_returns[f"fwd_{h}d"] = float((fwd_price - entry_price) / entry_price)
                    else:
                        fwd_returns[f"fwd_{h}d"] = None

                enriched.append({**purchase, **fwd_returns, "entry_date": str(entry_date.date())})
            except Exception:
                continue

        return enriched

    except Exception:
        return []


# ---------------------------------------------------------------------------
# Step 5: Alpha Score computation
# ---------------------------------------------------------------------------

def compute_alpha_score(ticker: str, enriched_purchases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compute per-ticker Alpha Score from enriched purchase list.
    Returns score dict with alpha_score, win_rate_30d, avg_fwd_return_30d, etc.
    """
    # Filter to rows with a valid 30d forward return
    valid = [p for p in enriched_purchases if p.get("fwd_30d") is not None]
    buy_count = len(valid)
    total_value_usd = sum(p.get("value_usd", 0) for p in enriched_purchases)

    if buy_count < MIN_BUYS_REQUIRED:
        return {
            "alpha_score": 50.0,
            "win_rate_30d": None,
            "avg_fwd_return_30d": None,
            "avg_fwd_return_5d": None,
            "avg_fwd_return_10d": None,
            "avg_fwd_return_20d": None,
            "buy_count": buy_count,
            "total_value_usd": total_value_usd,
            "insufficient_data": True,
        }

    returns_30d = [p["fwd_30d"] for p in valid]
    win_rate_30d = sum(1 for r in returns_30d if r > 0) / len(returns_30d)
    avg_fwd_return_30d = sum(returns_30d) / len(returns_30d)

    # Additional horizons (best-effort)
    def _avg(key: str) -> Optional[float]:
        vals = [p[key] for p in valid if p.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    avg_fwd_5d = _avg("fwd_5d")
    avg_fwd_10d = _avg("fwd_10d")
    avg_fwd_20d = _avg("fwd_20d")

    # Score components (each 0-100)
    win_rate_score = win_rate_30d * 100
    return_score = min(100.0, max(0.0, avg_fwd_return_30d / 0.10 * 100))
    frequency_score = min(100.0, buy_count / 20 * 100)
    value_score = min(100.0, max(0.0, math.log10(max(1, total_value_usd)) / math.log10(1e9) * 100))

    alpha_score = (
        0.40 * win_rate_score
        + 0.30 * return_score
        + 0.20 * frequency_score
        + 0.10 * value_score
    )

    return {
        "alpha_score": round(alpha_score, 2),
        "win_rate_30d": round(win_rate_30d, 4),
        "avg_fwd_return_30d": round(avg_fwd_return_30d, 6),
        "avg_fwd_return_5d": round(avg_fwd_5d, 6) if avg_fwd_5d is not None else None,
        "avg_fwd_return_10d": round(avg_fwd_10d, 6) if avg_fwd_10d is not None else None,
        "avg_fwd_return_20d": round(avg_fwd_20d, 6) if avg_fwd_20d is not None else None,
        "buy_count": buy_count,
        "total_value_usd": round(total_value_usd, 2),
        "insufficient_data": False,
    }


# ---------------------------------------------------------------------------
# Step 6: Sector lookup (cached)
# ---------------------------------------------------------------------------

_sector_cache: Dict[str, str] = {}

def get_sector(ticker: str) -> str:
    """Fetch sector from yfinance .info, cached."""
    if ticker in _sector_cache:
        return _sector_cache[ticker]
    try:
        info = yf.Ticker(ticker).info
        sector = info.get("sector", "Unknown") or "Unknown"
    except Exception:
        sector = "Unknown"
    _sector_cache[ticker] = sector
    return sector


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_outputs(scores: Dict[str, Dict[str, Any]]) -> None:
    """Write JSON and CSV to eval_results/."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # JSON
    output = {
        "computed_date": COMPUTED_DATE,
        "ticker_count": len(scores),
        "scores": scores,
    }
    json_path = os.path.join(OUTPUT_DIR, "insider_alpha_scores.json")
    with open(json_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nWrote {json_path}")

    # CSV
    rows = []
    for ticker, s in scores.items():
        rows.append({
            "ticker": ticker,
            "alpha_score": s["alpha_score"],
            "win_rate_30d": s["win_rate_30d"],
            "avg_fwd_return_30d": s["avg_fwd_return_30d"],
            "avg_fwd_return_5d": s.get("avg_fwd_return_5d"),
            "avg_fwd_return_10d": s.get("avg_fwd_return_10d"),
            "avg_fwd_return_20d": s.get("avg_fwd_return_20d"),
            "buy_count": s["buy_count"],
            "total_value_usd": s["total_value_usd"],
            "insufficient_data": s["insufficient_data"],
        })
    df = pd.DataFrame(rows)
    csv_path = os.path.join(OUTPUT_DIR, "insider_alpha_scores.csv")
    df.to_csv(csv_path, index=False)
    print(f"Wrote {csv_path}")


def print_summary(scores: Dict[str, Dict[str, Any]]) -> None:
    """Print top 20 by alpha_score, top 20 by win_rate_30d, and sector breakdown."""
    valid_scores = {t: s for t, s in scores.items() if not s["insufficient_data"]}

    print("\n" + "=" * 70)
    print("TOP 20 BY ALPHA SCORE")
    print("=" * 70)
    top_alpha = sorted(valid_scores.items(), key=lambda x: x[1]["alpha_score"], reverse=True)[:20]
    print(f"{'Ticker':<8} {'AlphaScore':>10} {'WinRate30d':>10} {'AvgRet30d':>10} {'Buys':>6}")
    print("-" * 50)
    for ticker, s in top_alpha:
        wr = f"{s['win_rate_30d']:.1%}" if s["win_rate_30d"] is not None else "N/A"
        ar = f"{s['avg_fwd_return_30d']:.2%}" if s["avg_fwd_return_30d"] is not None else "N/A"
        print(f"{ticker:<8} {s['alpha_score']:>10.1f} {wr:>10} {ar:>10} {s['buy_count']:>6}")

    print("\n" + "=" * 70)
    print("TOP 20 BY WIN RATE (>=5 buys)")
    print("=" * 70)
    top_wr = sorted(
        [(t, s) for t, s in valid_scores.items() if s["win_rate_30d"] is not None],
        key=lambda x: x[1]["win_rate_30d"],
        reverse=True,
    )[:20]
    print(f"{'Ticker':<8} {'WinRate30d':>10} {'AlphaScore':>10} {'AvgRet30d':>10} {'Buys':>6}")
    print("-" * 52)
    for ticker, s in top_wr:
        wr = f"{s['win_rate_30d']:.1%}"
        ar = f"{s['avg_fwd_return_30d']:.2%}" if s["avg_fwd_return_30d"] is not None else "N/A"
        print(f"{ticker:<8} {wr:>10} {s['alpha_score']:>10.1f} {ar:>10} {s['buy_count']:>6}")

    # Sector breakdown
    print("\n" + "=" * 70)
    print("SECTOR BREAKDOWN (avg alpha score, sufficient data only)")
    print("=" * 70)
    sector_groups: Dict[str, List[float]] = {}
    for ticker, s in valid_scores.items():
        sector = _sector_cache.get(ticker, "Unknown")
        sector_groups.setdefault(sector, []).append(s["alpha_score"])

    sector_rows = [
        (sector, sum(vals) / len(vals), len(vals))
        for sector, vals in sector_groups.items()
    ]
    sector_rows.sort(key=lambda x: x[1], reverse=True)
    print(f"{'Sector':<35} {'AvgAlpha':>9} {'Count':>6}")
    print("-" * 52)
    for sector, avg, count in sector_rows:
        print(f"{sector:<35} {avg:>9.1f} {count:>6}")

    print("\n" + "=" * 70)
    total = len(scores)
    sufficient = len(valid_scores)
    insufficient = total - sufficient
    print(f"Total tickers processed: {total}")
    print(f"  Sufficient data (>={MIN_BUYS_REQUIRED} buys): {sufficient}")
    print(f"  Insufficient data:                            {insufficient}")
    print("=" * 70)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"\nInsider Alpha Score Backtest — {COMPUTED_DATE}")
    print(f"Lookback: {LOOKBACK_YEARS} years ({CUTOFF_DATE} to today)")
    print(f"Max filings per ticker: {MAX_FILINGS_PER_TICKER}")
    print(f"Minimum buys required: {MIN_BUYS_REQUIRED}\n")

    tickers = load_sp500_tickers()
    cik_map = load_cik_map()
    time.sleep(EDGAR_DELAY_S)  # Be polite after loading CIK map

    scores: Dict[str, Dict[str, Any]] = {}
    n = len(tickers)

    iterator = tqdm(enumerate(tickers), total=n, desc="Tickers") if _HAS_TQDM else enumerate(tickers)

    for i, ticker in iterator:
        if not _HAS_TQDM:
            _progress_print(i, n, ticker)

        cik_padded = cik_map.get(ticker)
        if not cik_padded:
            scores[ticker] = {
                "alpha_score": 50.0,
                "win_rate_30d": None,
                "avg_fwd_return_30d": None,
                "avg_fwd_return_5d": None,
                "avg_fwd_return_10d": None,
                "avg_fwd_return_20d": None,
                "buy_count": 0,
                "total_value_usd": 0.0,
                "insufficient_data": True,
                "skip_reason": "no_cik",
            }
            continue

        try:
            # Fetch Form 4 open-market purchases from EDGAR
            purchases = fetch_form4_purchases(ticker, cik_padded)

            if not purchases:
                scores[ticker] = {
                    "alpha_score": 50.0,
                    "win_rate_30d": None,
                    "avg_fwd_return_30d": None,
                    "avg_fwd_return_5d": None,
                    "avg_fwd_return_10d": None,
                    "avg_fwd_return_20d": None,
                    "buy_count": 0,
                    "total_value_usd": 0.0,
                    "insufficient_data": True,
                    "skip_reason": "no_purchases",
                }
                continue

            # Enrich with forward returns
            enriched = compute_forward_returns(ticker, purchases)

            # Compute alpha score
            score = compute_alpha_score(ticker, enriched)
            scores[ticker] = score

            # Prefetch sector now while we have the ticker in context
            # (cached for summary later)
            if not score["insufficient_data"]:
                get_sector(ticker)

        except Exception as e:
            print(f"\n  Warning: {ticker} failed — {e}")
            scores[ticker] = {
                "alpha_score": 50.0,
                "win_rate_30d": None,
                "avg_fwd_return_30d": None,
                "avg_fwd_return_5d": None,
                "avg_fwd_return_10d": None,
                "avg_fwd_return_20d": None,
                "buy_count": 0,
                "total_value_usd": 0.0,
                "insufficient_data": True,
                "skip_reason": str(e)[:80],
            }
            continue

    # Write outputs
    write_outputs(scores)

    # Print summary tables
    print_summary(scores)


if __name__ == "__main__":
    main()
