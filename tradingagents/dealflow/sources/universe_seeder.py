"""Seed AKG with tickers from S&P500, NASDAQ, Russell 2000, Dow, ARK, ETFs, and growth watchlist."""

import json
import time
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph

# ---------------------------------------------------------------------------
# Static lists
# ---------------------------------------------------------------------------

DOW_30 = [
    "AAPL", "AMGN", "AMZN", "AXP", "BA", "CAT", "CRM", "CSCO", "CVX", "DIS",
    "GS", "HD", "HON", "IBM", "JNJ", "JPM", "KO", "MCD", "MMM", "MRK",
    "MSFT", "NKE", "NVDA", "PG", "SHW", "TRV", "UNH", "V", "VZ", "WMT",
]

SECTOR_ETFS = [
    "XLF", "XLE", "XLK", "XLV", "XLY", "XLP", "XLI", "XLU", "XLRE", "XLB", "XLC",
    "SMH", "XBI", "IBB", "XHB", "XRT", "KRE", "KBE", "XOP", "OIH", "ITB",
    "HACK", "SKYY", "BOTZ", "ROBO", "LIT", "TAN", "ICLN", "QCLN", "PBW",
]

EM_ETFS = [
    "EEM", "VWO", "IEMG", "EFA", "EWZ", "EWJ", "FXI", "INDA", "EWT", "EWY",
    "EWG", "EWU", "KWEB", "MCHI", "ASHR",
]

COMMODITY_ETFS = [
    "GLD", "SLV", "PPLT", "USO", "UNG", "DBC", "DBA", "CORN", "WEAT", "SOYB",
    "GDX", "GDXJ", "SIL", "COPX", "XME", "PDBC", "GSG", "CPER",
]

BROAD_ETFS = [
    "SPY", "QQQ", "IWM", "DIA", "VTI", "IVV",
    "TLT", "IEF", "HYG", "LQD",
    "ARKK", "USMV", "SPLV", "ITA", "XAR",
]

ARK_URLS = {
    "ARKK": "https://ark-funds.com/wp-content/uploads/funds-etf-csv/ARK_INNOVATION_ETF_ARKK_HOLDINGS.csv",
    "ARKG": "https://ark-funds.com/wp-content/uploads/funds-etf-csv/ARK_GENOMIC_REVOLUTION_ETF_ARKG_HOLDINGS.csv",
}

_DEFAULT_WATCHLIST_PATH = Path("eval_results/control/growth_watchlist.json")


# ---------------------------------------------------------------------------
# Classification data (moved from universe.py — used by backfill_metadata)
# ---------------------------------------------------------------------------

_ASSET_CLASS_BY_SYMBOL = {
    **{s: "Equity" for s in [
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "BRK-B", "JPM", "V", "UNH", "XOM", "JNJ", "WMT", "PG", "MA", "HD", "CVX", "ABBV", "KO",
        "PEP", "COST", "MRK", "AVGO", "BAC", "ORCL", "CRM", "NFLX", "TMO", "ACN", "AMD", "CSCO", "MCD", "LIN", "DHR", "ABT", "WFC", "QCOM", "TXN",
        "PM", "DIS", "VZ", "IBM", "NOW", "CAT", "GE", "GS", "BK", "SPGI", "BLK", "AMGN", "ISRG", "INTU", "GILD", "LRCX", "MU", "PANW", "ADBE", "BA",
        "NKE", "PFE", "HON", "UPS", "RTX", "DE", "C", "ANET", "SHOP", "UBER", "PLTR", "SNOW", "CRWD", "MDB", "ARM", "ARKB", "ASML", "AVAV", "BITO",
        "CCJ", "COIN", "ENPH", "ETHA", "FBTC", "FSLR", "HII", "HOOD", "ICLN", "IBIT", "KTOS", "LDOS", "LIT", "LMT", "MARA", "MSTR", "NEE", "NOC",
        "OKLO", "RIOT", "SEDG", "SMCI", "TAN", "TSM", "URNM",
    ]},
    **{s: "ETF" for s in [
        "SPY", "QQQ", "IWM", "DIA", "VTI", "IVV", "XLF", "XLK", "XLE", "XLI", "XLP", "XLU", "XLV", "XLY", "XLC", "XLB", "TLT", "IEF", "HYG", "LQD",
        "SMH", "XBI", "ARKK", "USMV", "SPLV", "ITA", "XAR",
    ]},
    **{s: "CommodityProxy" for s in [
        "GLD", "SLV", "PPLT", "USO", "UNG", "DBC", "DBA",
    ]},
}

_SECTOR_OVERRIDES = {
    "SPY": "Broad Market", "QQQ": "Large Cap Growth", "IWM": "Small Cap", "DIA": "Large Cap Value",
    "VTI": "Broad Market", "IVV": "Broad Market", "XLF": "Financials", "XLK": "Technology",
    "XLE": "Energy", "XLI": "Industrials", "XLP": "Consumer Staples", "XLU": "Utilities",
    "XLV": "Healthcare", "XLY": "Consumer Discretionary", "XLC": "Communication Services",
    "XLB": "Materials", "SMH": "Semiconductors", "XBI": "Biotechnology", "ARKK": "Innovation",
    "USMV": "Broad Market", "SPLV": "Broad Market", "TLT": "Rates", "IEF": "Rates",
    "HYG": "Credit", "LQD": "Credit", "GLD": "Metals", "SLV": "Metals", "PPLT": "Metals",
    "USO": "Energy", "UNG": "Energy", "DBC": "Commodities", "DBA": "Agriculture",
}

_EQUITY_SECTOR_BASELINE = {
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology", "AMZN": "Consumer Discretionary",
    "GOOGL": "Communication Services", "META": "Communication Services", "TSLA": "Consumer Discretionary",
    "BRK-B": "Financials", "JPM": "Financials", "V": "Financials", "UNH": "Healthcare", "XOM": "Energy",
    "JNJ": "Healthcare", "WMT": "Consumer Staples", "PG": "Consumer Staples", "MA": "Financials",
    "HD": "Consumer Discretionary", "CVX": "Energy", "ABBV": "Healthcare", "KO": "Consumer Staples",
    "PEP": "Consumer Staples", "COST": "Consumer Staples", "MRK": "Healthcare", "AVGO": "Technology",
    "BAC": "Financials", "ORCL": "Technology", "CRM": "Technology", "NFLX": "Communication Services",
    "TMO": "Healthcare", "ACN": "Technology", "AMD": "Technology", "CSCO": "Technology",
    "MCD": "Consumer Discretionary", "LIN": "Materials", "DHR": "Healthcare", "ABT": "Healthcare",
    "WFC": "Financials", "QCOM": "Technology", "TXN": "Technology", "PM": "Consumer Staples",
    "DIS": "Communication Services", "VZ": "Communication Services", "IBM": "Technology",
    "NOW": "Technology", "CAT": "Industrials", "GE": "Industrials", "GS": "Financials",
    "BK": "Financials", "SPGI": "Financials", "BLK": "Financials", "AMGN": "Healthcare",
    "ISRG": "Healthcare", "INTU": "Technology", "GILD": "Healthcare", "LRCX": "Technology",
    "MU": "Technology", "PANW": "Technology", "ADBE": "Technology", "BA": "Industrials",
    "NKE": "Consumer Discretionary", "PFE": "Healthcare", "HON": "Industrials", "UPS": "Industrials",
    "RTX": "Industrials", "DE": "Industrials", "C": "Financials", "ANET": "Technology",
    "SHOP": "Technology", "UBER": "Industrials", "PLTR": "Technology", "SNOW": "Technology",
    "CRWD": "Technology", "MDB": "Technology",
}

_SECTOR_NORMALIZATION = {
    "technology": "Technology", "financial services": "Financials", "financial": "Financials",
    "healthcare": "Healthcare", "consumer cyclical": "Consumer Discretionary",
    "consumer defensive": "Consumer Staples", "communication services": "Communication Services",
    "basic materials": "Materials", "real estate": "Real Estate", "industrials": "Industrials",
    "energy": "Energy", "utilities": "Utilities", "semiconductors": "Semiconductors",
    "biotechnology": "Biotechnology",
}

_ALIASES = {
    "GLD": ["gold", "xau", "precious metals"],
    "SLV": ["silver", "xag", "precious metals"],
    "USO": ["oil", "crude", "wti"],
    "UNG": ["natural gas", "natgas"],
    "DBC": ["commodities", "commodity basket"],
    "DBA": ["agriculture", "grains", "softs"],
    "PPLT": ["platinum", "metals"],
}

# AKG thematic sector -> GICS reverse map (same as in akg_universe.py)
_AKG_TO_GICS = {
    "semis_ai_infrastructure": "Technology",
    "biotech_pharma": "Healthcare",
    "defense_aerospace": "Industrials",
    "energy_power": "Energy",
    "materials_critical_minerals": "Materials",
    "fintech_banking": "Financials",
    "macro_rates": "Financials",
    "china_geopolitics": "Industrials",
}


# ---------------------------------------------------------------------------
# Ticker sanitization
# ---------------------------------------------------------------------------

def _sanitize(raw: str) -> str:
    """Strip, uppercase, replace dot with dash (BRK.B → BRK-B)."""
    return raw.strip().upper().replace(".", "-")


def _is_valid_ticker(ticker: str) -> bool:
    """Reject non-equity symbols: ^ prefix, /, or >5 chars with no letters."""
    if not ticker:
        return False
    if ticker.startswith("^") or "/" in ticker:
        return False
    if len(ticker) > 5 and not any(c.isalpha() for c in ticker):
        return False
    return True


# ---------------------------------------------------------------------------
# Fetch functions (each returns List[Tuple[ticker, source_tag]])
# ---------------------------------------------------------------------------

def fetch_sp500() -> List[Tuple[str, str]]:
    """Return [(ticker, 'sp500'), ...] from GitHub-hosted S&P 500 constituents CSV."""
    try:
        import requests
        import csv
        from io import StringIO
        print("[universe_seeder] Fetching S&P 500 (GitHub CSV)...", file=sys.stderr)
        url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        reader = csv.DictReader(StringIO(resp.text))
        result = []
        for row in reader:
            raw = row.get("Symbol", "").strip().replace(".", "-")
            t = _sanitize(raw)
            if _is_valid_ticker(t):
                result.append((t, "sp500"))
        print(f"[universe_seeder] Fetching S&P 500... got {len(result)} tickers", file=sys.stderr)
        return result
    except Exception as e:
        print(f"[universe_seeder] S&P 500 fetch failed: {e}", file=sys.stderr)
        return []


def fetch_nasdaq_listed() -> List[Tuple[str, str]]:
    """Return [(ticker, 'nasdaq'), ...] from GitHub-hosted NASDAQ symbols list."""
    try:
        import requests
        print("[universe_seeder] Fetching NASDAQ listed (GitHub)...", file=sys.stderr)
        url = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/nasdaq/nasdaq_tickers.txt"
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        result = []
        for line in resp.text.splitlines():
            t = _sanitize(line.strip())
            if _is_valid_ticker(t):
                result.append((t, "nasdaq"))
        print(f"[universe_seeder] Fetching NASDAQ... got {len(result)} tickers", file=sys.stderr)
        return result
    except Exception as e:
        print(f"[universe_seeder] NASDAQ fetch failed: {e}", file=sys.stderr)
        return []


def fetch_russell2000() -> List[Tuple[str, str]]:
    """Return [(ticker, 'russell2000'), ...] from iShares IWM holdings CSV."""
    try:
        import requests
        import csv
        import io
        print("[universe_seeder] Fetching Russell 2000 (IWM holdings)...", file=sys.stderr)
        url = (
            "https://www.ishares.com/us/products/239710/ishares-russell-2000-etf/"
            "1467271812596.ajax?fileType=csv&fileName=IWM_holdings&dataType=fund"
        )
        headers = {"User-Agent": "Mozilla/5.0 (compatible; AeternusBot/1.0)"}
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()

        # Skip header rows until we find the line starting with "Ticker"
        lines = resp.text.splitlines()
        header_idx = None
        for i, line in enumerate(lines):
            if line.strip().startswith("Ticker"):
                header_idx = i
                break

        if header_idx is None:
            print("[universe_seeder] Russell 2000 CSV format unrecognized", file=sys.stderr)
            return []

        reader = csv.DictReader(lines[header_idx:])
        result = []
        for row in reader:
            raw = row.get("Ticker", "").strip()
            if not raw or raw == "-":
                continue
            t = _sanitize(raw)
            if _is_valid_ticker(t):
                result.append((t, "russell2000"))

        print(f"[universe_seeder] Fetching Russell 2000 (IWM holdings)... got {len(result)} tickers", file=sys.stderr)
        return result
    except Exception as e:
        print(f"[universe_seeder] Russell 2000 fetch failed: {e}", file=sys.stderr)
        return []


def fetch_ark_holdings() -> List[Tuple[str, str]]:
    """Return [(ticker, 'ark'), ...] via yfinance ARKK + ARKG holdings."""
    import yfinance as yf
    result = []
    for fund in ARK_URLS:
        try:
            print(f"[universe_seeder] Fetching {fund} holdings (via yfinance)...", file=sys.stderr)
            df = yf.Ticker(fund).funds_data.top_holdings
            tickers = df.index.tolist() if df is not None else []
            fund_tickers = [(_sanitize(str(t)), "ark") for t in tickers if _is_valid_ticker(_sanitize(str(t)))]
            print(f"[universe_seeder] Fetching {fund} holdings... got {len(fund_tickers)} tickers", file=sys.stderr)
            result.extend(fund_tickers)
            time.sleep(0.5)
        except Exception as e:
            print(f"[universe_seeder] {fund} fetch failed: {e}", file=sys.stderr)
    return result


def get_static_etfs() -> List[Tuple[str, str]]:
    """Return static ETF tickers: broad, sector, EM, commodity."""
    result = []
    for t in BROAD_ETFS:
        result.append((_sanitize(t), "broad_etf"))
    for t in SECTOR_ETFS:
        result.append((_sanitize(t), "sector_etf"))
    for t in EM_ETFS:
        result.append((_sanitize(t), "em_etf"))
    for t in COMMODITY_ETFS:
        result.append((_sanitize(t), "commodity_etf"))
    print(f"[universe_seeder] Static ETFs: {len(result)} tickers", file=sys.stderr)
    return result


def load_growth_watchlist(path: Path = None) -> List[Tuple[str, str]]:
    """Return [(ticker, 'growth_watchlist'), ...] from user-maintained JSON."""
    if path is None:
        path = _DEFAULT_WATCHLIST_PATH
    path = Path(path)
    if not path.exists():
        print(f"[universe_seeder] Growth watchlist not found at {path}, skipping", file=sys.stderr)
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        tickers = data.get("tickers", [])
        result = [(_sanitize(t), "growth_watchlist") for t in tickers if _is_valid_ticker(_sanitize(t))]
        print(f"[universe_seeder] Growth watchlist: {len(result)} tickers", file=sys.stderr)
        return result
    except Exception as e:
        print(f"[universe_seeder] Growth watchlist load failed: {e}", file=sys.stderr)
        return []


# ---------------------------------------------------------------------------
# Universe assembly
# ---------------------------------------------------------------------------

def build_full_seed_universe() -> Dict[str, List[str]]:
    """
    Fetch all sources, dedupe, return {ticker: [source1, source2, ...]}.
    A ticker in both sp500 and nasdaq gets both tags.
    """
    universe: Dict[str, List[str]] = {}

    def _add_batch(pairs: List[Tuple[str, str]]) -> None:
        for ticker, source in pairs:
            if ticker not in universe:
                universe[ticker] = []
            if source not in universe[ticker]:
                universe[ticker].append(source)

    # Dow first (static, no network)
    dow_pairs = [(_sanitize(t), "dow") for t in DOW_30]
    _add_batch(dow_pairs)
    print(f"[universe_seeder] Dow 30: {len(dow_pairs)} tickers", file=sys.stderr)

    # Static ETFs (no network)
    _add_batch(get_static_etfs())

    # Growth watchlist (local file)
    _add_batch(load_growth_watchlist())

    # Network sources with rate limiting
    time.sleep(0.5)
    _add_batch(fetch_sp500())

    time.sleep(0.5)
    _add_batch(fetch_nasdaq_listed())

    time.sleep(0.5)
    _add_batch(fetch_russell2000())

    time.sleep(0.5)
    _add_batch(fetch_ark_holdings())

    print(f"[universe_seeder] Total unique tickers: {len(universe)}", file=sys.stderr)
    return universe


# ---------------------------------------------------------------------------
# AKG seeding
# ---------------------------------------------------------------------------

def seed_akg(dry_run: bool = False) -> dict:
    """
    Load AKG, add all tickers from build_full_seed_universe().
    For each new node: add_node with seed_sources metadata.
    For existing nodes: append new sources to existing seed_sources.
    Sets asset_class, sector_gics, and aliases on all touched nodes.
    Save AKG if not dry_run.

    Returns {"total_fetched": int, "new_nodes_added": int, "existing_updated": int, "errors": [...]}
    """
    errors = []
    universe = build_full_seed_universe()

    print(f"[universe_seeder] Loading AKG...", file=sys.stderr)
    try:
        akg = AeternusKnowledgeGraph.load()
    except Exception as e:
        errors.append(f"AKG load failed: {e}")
        return {"total_fetched": len(universe), "new_nodes_added": 0, "existing_updated": 0, "errors": errors}

    new_nodes_added = 0
    existing_updated = 0

    for ticker, sources in universe.items():
        try:
            if ticker in akg._nodes:
                # Existing node: merge seed_sources without overwriting
                existing_meta = akg._nodes[ticker].get("metadata", {})
                existing_sources = existing_meta.get("seed_sources", [])
                merged = list(existing_sources)
                changed = False
                for s in sources:
                    if s not in merged:
                        merged.append(s)
                        changed = True
                if changed:
                    akg._nodes[ticker].setdefault("metadata", {})["seed_sources"] = merged
                    existing_updated += 1
            else:
                # New node
                akg.add_node(ticker, node_type="company", metadata={"seed_sources": sources})
                new_nodes_added += 1

            # Set universe metadata on the node
            _apply_classification(akg, ticker)

        except Exception as e:
            errors.append(f"{ticker}: {e}")

    if not dry_run:
        print(f"[universe_seeder] Saving AKG ({new_nodes_added} new, {existing_updated} updated)...", file=sys.stderr)
        try:
            akg.save()
        except Exception as e:
            errors.append(f"AKG save failed: {e}")
    else:
        print(f"[universe_seeder] Dry run — AKG not saved", file=sys.stderr)

    return {
        "total_fetched": len(universe),
        "new_nodes_added": new_nodes_added,
        "existing_updated": existing_updated,
        "errors": errors,
    }


def _apply_classification(akg: "AeternusKnowledgeGraph", ticker: str) -> None:
    """Set asset_class, sector_gics, and aliases on a single AKG node."""
    if ticker not in akg._nodes:
        return
    node = akg._nodes[ticker]

    # asset_class
    if not node.get("asset_class"):
        ac = _ASSET_CLASS_BY_SYMBOL.get(ticker)
        if not ac:
            # Infer from seeder lists
            if ticker in COMMODITY_ETFS:
                ac = "CommodityProxy"
            elif ticker in SECTOR_ETFS or ticker in EM_ETFS or ticker in BROAD_ETFS:
                ac = "ETF"
            else:
                ac = "Equity"
        node["asset_class"] = ac

    # sector_gics
    if not node.get("sector_gics"):
        gics = _SECTOR_OVERRIDES.get(ticker) or _EQUITY_SECTOR_BASELINE.get(ticker)
        if not gics:
            # Try AKG thematic sector -> GICS reverse map
            akg_sector = node.get("sector")
            if akg_sector:
                gics = _AKG_TO_GICS.get(str(akg_sector).strip(), "")
        if gics:
            node["sector_gics"] = gics

    # aliases
    if not node.get("aliases") and ticker in _ALIASES:
        node["aliases"] = list(_ALIASES[ticker])


def backfill_metadata() -> dict:
    """Read existing AKG and apply classification rules to ALL company nodes.

    Returns {"total": int, "asset_class_set": int, "sector_gics_set": int, "errors": [...]}.
    """
    errors = []
    try:
        akg = AeternusKnowledgeGraph.load()
    except Exception as e:
        return {"total": 0, "asset_class_set": 0, "sector_gics_set": 0, "errors": [str(e)]}

    ac_set = 0
    sg_set = 0
    total = 0

    for node_id, node in akg._nodes.items():
        if node.get("node_type") != "company":
            continue
        total += 1

        had_ac = bool(node.get("asset_class"))
        had_sg = bool(node.get("sector_gics"))

        _apply_classification(akg, node_id)

        if not had_ac and node.get("asset_class"):
            ac_set += 1
        if not had_sg and node.get("sector_gics"):
            sg_set += 1

    try:
        akg.save()
        print(f"[universe_seeder] backfill_metadata: {total} nodes, {ac_set} asset_class set, {sg_set} sector_gics set", file=sys.stderr)
    except Exception as e:
        errors.append(f"AKG save failed: {e}")

    return {"total": total, "asset_class_set": ac_set, "sector_gics_set": sg_set, "errors": errors}


def refresh_liquidity(batch_size: int = 40) -> dict:
    """Fetch 3mo yfinance history in batches, compute 60-day avg dollar volume percentile.

    Writes liquidity_score + liquidity_cached_at to AKG nodes. Saves AKG.
    Returns {"total": int, "updated": int, "errors": [...]}.
    """
    import contextlib
    import io
    import datetime as dt

    import pandas as pd
    import yfinance as yf

    errors = []
    try:
        akg = AeternusKnowledgeGraph.load()
    except Exception as e:
        return {"total": 0, "updated": 0, "errors": [str(e)]}

    company_symbols = [
        nid for nid, n in akg._nodes.items() if n.get("node_type") == "company"
    ]
    if not company_symbols:
        return {"total": 0, "updated": 0, "errors": []}

    dollar_volumes: Dict[str, float] = {}

    for i in range(0, len(company_symbols), batch_size):
        batch = company_symbols[i : i + batch_size]
        try:
            sink = io.StringIO()
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                data = yf.download(
                    batch if len(batch) > 1 else batch[0],
                    period="3mo",
                    interval="1d",
                    auto_adjust=False,
                    progress=False,
                    group_by="ticker",
                    threads=False,
                )
            if data is None or data.empty:
                continue
            for sym in batch:
                close_s = _extract_series(data, sym, "Close", len(batch) > 1)
                vol_s = _extract_series(data, sym, "Volume", len(batch) > 1)
                if close_s is None or vol_s is None:
                    continue
                frame = pd.DataFrame({"close": close_s, "volume": vol_s}).dropna()
                if frame.empty:
                    continue
                frame["dv"] = frame["close"] * frame["volume"]
                avg_dv = float(frame["dv"].tail(60).mean())
                if avg_dv > 0:
                    dollar_volumes[sym] = avg_dv
        except Exception as e:
            errors.append(f"batch {i}: {e}")

    if not dollar_volumes:
        return {"total": len(company_symbols), "updated": 0, "errors": errors}

    # Percentile scoring
    vals = sorted(dollar_volumes.values())
    min_v, max_v = vals[0], vals[-1]

    updated = 0
    today_iso = dt.date.today().isoformat()
    for sym in company_symbols:
        dv = dollar_volumes.get(sym)
        if dv is None:
            continue
        if max_v == min_v:
            score = 70.0
        else:
            score = 20.0 + 80.0 * ((dv - min_v) / (max_v - min_v))
        akg._nodes[sym]["liquidity_score"] = round(score, 2)
        akg._nodes[sym]["liquidity_cached_at"] = today_iso
        updated += 1

    try:
        akg.save()
        print(f"[universe_seeder] refresh_liquidity: {updated}/{len(company_symbols)} updated", file=sys.stderr)
    except Exception as e:
        errors.append(f"AKG save failed: {e}")

    return {"total": len(company_symbols), "updated": updated, "errors": errors}


def _extract_series(data, symbol: str, field: str, multi: bool):
    """Extract a single series from a yfinance download frame."""
    import pandas as pd
    try:
        if not multi:
            if field in data.columns:
                return pd.to_numeric(data[field], errors="coerce")
            return None
        if isinstance(data.columns, pd.MultiIndex):
            if (symbol, field) in data.columns:
                return pd.to_numeric(data[(symbol, field)], errors="coerce")
            if (field, symbol) in data.columns:
                return pd.to_numeric(data[(field, symbol)], errors="coerce")
            if symbol in data.columns.get_level_values(0):
                sub = data[symbol]
                if field in sub.columns:
                    return pd.to_numeric(sub[field], errors="coerce")
        return None
    except Exception:
        return None
