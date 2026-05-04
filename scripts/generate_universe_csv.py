"""
scripts/generate_universe_csv.py — ONE-TIME generation script for S-049.

Fetches S&P 500 from Wikipedia (free) and a small hardcoded Russell 2000
sample. Writes tradingagents/graph/data/universe_constituents.csv.

Run once:
    python scripts/generate_universe_csv.py

Do NOT call this from production code. The CSV is committed to the repo.
"""

import csv
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Output path
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent
OUTPUT_PATH = REPO_ROOT / "tradingagents" / "graph" / "data" / "universe_constituents.csv"


# ---------------------------------------------------------------------------
# Hardcoded Russell 2000 sample (~100 well-known small caps).
# Used as fallback if yfinance funds_data is unavailable.
# sector_yf left blank — cashtag enricher / SEC catalyst will fill it in.
# ---------------------------------------------------------------------------
RUSSELL_2000_SAMPLE = [
    ("AEHR", "Aehr Test Systems", "NASDAQ", "Technology"),
    ("AMTB", "Amerant Bancorp", "NASDAQ", "Financial Services"),
    ("AMSF", "AMERITAS Life Partners", "NASDAQ", "Financial Services"),
    ("ANDE", "Andersons Inc", "NASDAQ", "Consumer Defensive"),
    ("APOG", "Apogee Enterprises", "NASDAQ", "Industrials"),
    ("ARWR", "Arrowhead Pharmaceuticals", "NASDAQ", "Healthcare"),
    ("ASRV", "AmeriServ Financial", "NASDAQ", "Financial Services"),
    ("ATRC", "AtriCure Inc", "NASDAQ", "Healthcare"),
    ("AVAV", "AeroVironment Inc", "NASDAQ", "Industrials"),
    ("AXNX", "Axonics Inc", "NASDAQ", "Healthcare"),
    ("BCML", "BayCom Corp", "NASDAQ", "Financial Services"),
    ("BLFS", "BioLife Solutions", "NASDAQ", "Healthcare"),
    ("BMBL", "Bumble Inc", "NASDAQ", "Communication Services"),
    ("BRKL", "Brookline Bancorp", "NASDAQ", "Financial Services"),
    ("CAMT", "Camtek Ltd", "NASDAQ", "Technology"),
    ("CBAN", "Colony Bankcorp", "NASDAQ", "Financial Services"),
    ("CCOI", "Cogent Communications", "NASDAQ", "Communication Services"),
    ("CDNA", "CareDx Inc", "NASDAQ", "Healthcare"),
    ("CDXS", "Codexis Inc", "NASDAQ", "Healthcare"),
    ("CGEM", "Cullinan Therapeutics", "NASDAQ", "Healthcare"),
    ("CLBK", "Columbia Financial", "NASDAQ", "Financial Services"),
    ("CLFD", "Clearfield Inc", "NASDAQ", "Technology"),
    ("CMPO", "CompoSecure Inc", "NASDAQ", "Technology"),
    ("CNMD", "CONMED Corp", "NASDAQ", "Healthcare"),
    ("COHU", "Cohu Inc", "NASDAQ", "Technology"),
    ("CPRX", "Catalyst Pharmaceuticals", "NASDAQ", "Healthcare"),
    ("CRDO", "Credo Technology", "NASDAQ", "Technology"),
    ("CSGS", "CSG Systems International", "NASDAQ", "Technology"),
    ("CTBI", "Community Trust Bancorp", "NASDAQ", "Financial Services"),
    ("CVCO", "Cavco Industries", "NASDAQ", "Consumer Cyclical"),
    ("DFIN", "Donnelley Financial Solutions", "NYSE", "Technology"),
    ("DLX", "Deluxe Corp", "NYSE", "Industrials"),
    ("DORM", "Dorman Products", "NASDAQ", "Consumer Cyclical"),
    ("EDIT", "Editas Medicine", "NASDAQ", "Healthcare"),
    ("EFSC", "Enterprise Financial Services", "NASDAQ", "Financial Services"),
    ("ENOV", "Enovis Corp", "NYSE", "Healthcare"),
    ("ENTA", "Enanta Pharmaceuticals", "NASDAQ", "Healthcare"),
    ("EPAC", "Enerpac Tool Group", "NYSE", "Industrials"),
    ("ESNT", "Essent Group", "NYSE", "Financial Services"),
    ("EVTC", "EVERTEC Inc", "NYSE", "Financial Services"),
    ("EXPO", "Exponent Inc", "NASDAQ", "Industrials"),
    ("FBIZ", "First Business Financial", "NASDAQ", "Financial Services"),
    ("FCFS", "FirstCash Holdings", "NASDAQ", "Financial Services"),
    ("FFBC", "First Financial Bancorp", "NASDAQ", "Financial Services"),
    ("FHB", "First Hawaiian Inc", "NASDAQ", "Financial Services"),
    ("FIBK", "First Interstate BancSystem", "NASDAQ", "Financial Services"),
    ("FIZZ", "National Beverage Corp", "NASDAQ", "Consumer Defensive"),
    ("FLGT", "Fulgent Genetics", "NASDAQ", "Healthcare"),
    ("FORM", "FormFactor Inc", "NASDAQ", "Technology"),
    ("FORR", "Forrester Research", "NASDAQ", "Industrials"),
    ("FRST", "Primis Financial Corp", "NASDAQ", "Financial Services"),
    ("FULT", "Fulton Financial", "NASDAQ", "Financial Services"),
    ("GATO", "Gatos Silver", "NYSE", "Basic Materials"),
    ("GIII", "G-III Apparel Group", "NASDAQ", "Consumer Cyclical"),
    ("GNW", "Genworth Financial", "NYSE", "Financial Services"),
    ("GPRE", "Green Plains Inc", "NASDAQ", "Energy"),
    ("HAFC", "Hanmi Financial", "NASDAQ", "Financial Services"),
    ("HALO", "Halozyme Therapeutics", "NASDAQ", "Healthcare"),
    ("HBNC", "Horizon Bancal", "NASDAQ", "Financial Services"),
    ("HCKT", "Hackett Group", "NASDAQ", "Technology"),
    ("HIBB", "Hibbett Inc", "NASDAQ", "Consumer Cyclical"),
    ("HONE", "HarborOne Bancorp", "NASDAQ", "Financial Services"),
    ("HOPE", "Hope Bancorp", "NASDAQ", "Financial Services"),
    ("HRTX", "Heron Therapeutics", "NASDAQ", "Healthcare"),
    ("HTBK", "Heritage Commerce Corp", "NASDAQ", "Financial Services"),
    ("IBCP", "Independent Bank Corp (MI)", "NASDAQ", "Financial Services"),
    ("ICHR", "Ichor Holdings", "NASDAQ", "Technology"),
    ("IDCC", "InterDigital Inc", "NASDAQ", "Technology"),
    ("IIIN", "Insteel Industries", "NYSE", "Basic Materials"),
    ("IIVIP", "IVI Inc", "NASDAQ", "Healthcare"),
    ("INBK", "First Internet Bancorp", "NASDAQ", "Financial Services"),
    ("INVA", "Innoviva Inc", "NASDAQ", "Healthcare"),
    ("IREN", "Iris Energy", "NASDAQ", "Energy"),
    ("ITRI", "Itron Inc", "NASDAQ", "Technology"),
    ("ITOS", "iTeos Therapeutics", "NASDAQ", "Healthcare"),
    ("JACK", "Jack in the Box", "NASDAQ", "Consumer Cyclical"),
    ("JJSF", "J&J Snack Foods", "NASDAQ", "Consumer Defensive"),
    ("JNCE", "Jounce Therapeutics", "NASDAQ", "Healthcare"),
    ("KELYA", "Kelly Services", "NASDAQ", "Industrials"),
    ("KFRC", "Kforce Inc", "NASDAQ", "Industrials"),
    ("KOP", "Koppers Holdings", "NYSE", "Basic Materials"),
    ("KRTX", "Karuna Therapeutics", "NASDAQ", "Healthcare"),
    ("KTOS", "Kratos Defense", "NASDAQ", "Industrials"),
    ("LAKE", "Lakeland Industries", "NASDAQ", "Industrials"),
    ("LCII", "LCI Industries", "NYSE", "Consumer Cyclical"),
    ("LGIH", "LGI Homes", "NASDAQ", "Consumer Cyclical"),
    ("LKFN", "Lakeland Financial", "NASDAQ", "Financial Services"),
    ("LOVE", "Lovesac Co", "NASDAQ", "Consumer Cyclical"),
    ("LQDT", "Liquidity Services", "NASDAQ", "Industrials"),
    ("MBIN", "Merchants Financial Group", "NASDAQ", "Financial Services"),
    ("MBTF", "MBT Financial Corp", "NASDAQ", "Financial Services"),
    ("MCBS", "MetroCity Bankshares", "NASDAQ", "Financial Services"),
    ("MDXG", "MiMedx Group", "NASDAQ", "Healthcare"),
    ("MGPI", "MGP Ingredients", "NASDAQ", "Consumer Defensive"),
    ("MLAB", "Mesa Labs", "NASDAQ", "Healthcare"),
    ("MLKN", "MillerKnoll Inc", "NASDAQ", "Consumer Cyclical"),
    ("MMSI", "Merit Medical Systems", "NASDAQ", "Healthcare"),
    ("MNKD", "MannKind Corp", "NASDAQ", "Healthcare"),
    ("MPWR", "Monolithic Power Systems", "NASDAQ", "Technology"),
    ("MRKR", "Marker Therapeutics", "NASDAQ", "Healthcare"),
    ("MRTN", "Marten Transport", "NASDAQ", "Industrials"),
    ("MRUS", "Merus NV", "NASDAQ", "Healthcare"),
    ("MYGN", "Myriad Genetics", "NASDAQ", "Healthcare"),
    ("NAPA", "Duckwall-ALCO Stores", "NYSE", "Consumer Defensive"),
    ("NBTB", "NBT Bancorp", "NASDAQ", "Financial Services"),
    ("NKLA", "Nikola Corp", "NASDAQ", "Consumer Cyclical"),
    ("NTST", "NETSTREIT Corp", "NYSE", "Real Estate"),
    ("NUVL", "Nuvalent Inc", "NASDAQ", "Healthcare"),
    ("NVRO", "Nevro Corp", "NYSE", "Healthcare"),
    ("NWFL", "Norwood Financial", "NASDAQ", "Financial Services"),
    ("OCFC", "OceanFirst Financial", "NASDAQ", "Financial Services"),
    ("OFIX", "Orthofix Medical", "NASDAQ", "Healthcare"),
    ("OMCL", "Omnicell Inc", "NASDAQ", "Healthcare"),
    ("OPCH", "Option Care Health", "NASDAQ", "Healthcare"),
    ("OSGB", "Overseas Shipholding Group", "NYSE", "Industrials"),
    ("OTTR", "Otter Tail Corp", "NASDAQ", "Utilities"),
    ("PATK", "Patrick Industries", "NASDAQ", "Consumer Cyclical"),
    ("PFIS", "Peoples Financial Services", "NASDAQ", "Financial Services"),
    ("PLAB", "Photronics Inc", "NASDAQ", "Technology"),
    ("PLXS", "Plexus Corp", "NASDAQ", "Technology"),
    ("PMVP", "PMV Pharmaceuticals", "NASDAQ", "Healthcare"),
    ("PPBI", "Pacific Premier Bancorp", "NASDAQ", "Financial Services"),
    ("PRAA", "PRA Group", "NASDAQ", "Financial Services"),
    ("PRFT", "Perficient Inc", "NASDAQ", "Technology"),
    ("PTCT", "PTC Therapeutics", "NASDAQ", "Healthcare"),
    ("QCRH", "QCR Holdings", "NASDAQ", "Financial Services"),
    ("QLYS", "Qualys Inc", "NASDAQ", "Technology"),
    ("RAMP", "LiveRamp Holdings", "NYSE", "Technology"),
    ("RBCAA", "Republic Bancorp", "NASDAQ", "Financial Services"),
    ("RCM", "R1 RCM Inc", "NASDAQ", "Healthcare"),
    ("REX", "REX Energy Corp", "NYSE", "Energy"),
    ("RLGT", "Radiant Logistics", "NYSE", "Industrials"),
    ("ROCK", "Gibraltar Industries", "NASDAQ", "Industrials"),
    ("RSKIA", "George Risk Industries", "NASDAQ", "Technology"),
    ("RUSHA", "Rush Enterprises", "NASDAQ", "Industrials"),
    ("RYAM", "Rayonier Advanced Materials", "NYSE", "Basic Materials"),
    ("SAFE", "Safehold Inc", "NYSE", "Real Estate"),
    ("SANA", "Sana Biotechnology", "NASDAQ", "Healthcare"),
    ("SBCF", "Seacoast Banking Corp", "NASDAQ", "Financial Services"),
    ("SBSI", "Southside Bancshares", "NASDAQ", "Financial Services"),
    ("SCHL", "Scholastic Corp", "NASDAQ", "Communication Services"),
    ("SCVL", "Shoe Carnival", "NASDAQ", "Consumer Cyclical"),
    ("SFBS", "ServisFirst Bancshares", "NASDAQ", "Financial Services"),
    ("SFNC", "Simmons First National", "NASDAQ", "Financial Services"),
    ("SGH", "SMART Global Holdings", "NASDAQ", "Technology"),
    ("SHBI", "Shore Bankshares", "NASDAQ", "Financial Services"),
    ("SIGI", "Selective Insurance Group", "NASDAQ", "Financial Services"),
    ("SITM", "SiTime Corp", "NASDAQ", "Technology"),
    ("SKIN", "Beauty Health Co", "NASDAQ", "Consumer Cyclical"),
    ("SLGN", "Silgan Holdings", "NASDAQ", "Consumer Defensive"),
    ("SMBC", "Southern Missouri Bancorp", "NASDAQ", "Financial Services"),
    ("SMBK", "SmartFinancial Bancshares", "NASDAQ", "Financial Services"),
    ("SMPL", "Simply Good Foods", "NASDAQ", "Consumer Defensive"),
    ("SNBR", "Sleep Number Corp", "NASDAQ", "Consumer Cyclical"),
    ("SPOK", "Spok Holdings", "NASDAQ", "Communication Services"),
    ("SRCE", "1st Source Corp", "NASDAQ", "Financial Services"),
    ("SRPT", "Sarepta Therapeutics", "NASDAQ", "Healthcare"),
    ("STBA", "S&T Bancorp", "NASDAQ", "Financial Services"),
    ("STEP", "StepStone Group", "NASDAQ", "Financial Services"),
    ("STRL", "Sterling Infrastructure", "NASDAQ", "Industrials"),
    ("SUPN", "Supernus Pharmaceuticals", "NASDAQ", "Healthcare"),
    ("SVRA", "Savara Inc", "NASDAQ", "Healthcare"),
    ("SWBI", "Smith & Wesson Brands", "NASDAQ", "Industrials"),
    ("TALO", "Talos Energy", "NYSE", "Energy"),
    ("TBK", "Triumph Bancorp", "NASDAQ", "Financial Services"),
    ("TCBK", "TriCo Bancshares", "NASDAQ", "Financial Services"),
    ("TCMD", "Tactile Systems Technology", "NASDAQ", "Healthcare"),
    ("TGTX", "TG Therapeutics", "NASDAQ", "Healthcare"),
    ("TILE", "Interface Inc", "NASDAQ", "Industrials"),
    ("TNDM", "Tandem Diabetes Care", "NASDAQ", "Healthcare"),
    ("TOWN", "TowneBank", "NASDAQ", "Financial Services"),
    ("TPIC", "TPI Composites", "NASDAQ", "Industrials"),
    ("TRNS", "Transcat Inc", "NASDAQ", "Industrials"),
    ("TRUP", "Trupanion Inc", "NASDAQ", "Financial Services"),
    ("TTEC", "TTEC Holdings", "NASDAQ", "Industrials"),
    ("TTEK", "Tetra Tech Inc", "NASDAQ", "Industrials"),
    ("TTSH", "Tile Shop Holdings", "NASDAQ", "Consumer Cyclical"),
    ("TVTX", "Travere Therapeutics", "NASDAQ", "Healthcare"),
    ("TZOO", "Travelzoo", "NASDAQ", "Consumer Cyclical"),
    ("UCBI", "United Community Banks", "NASDAQ", "Financial Services"),
    ("UCTT", "Ultra Clean Holdings", "NASDAQ", "Technology"),
    ("UDMY", "Udemy Inc", "NASDAQ", "Consumer Cyclical"),
    ("UMBF", "UMB Financial", "NASDAQ", "Financial Services"),
    ("UMPQ", "Umpqua Holdings", "NASDAQ", "Financial Services"),
    ("UNFI", "United Natural Foods", "NYSE", "Consumer Defensive"),
    ("UNTY", "Unity Bancorp", "NASDAQ", "Financial Services"),
    ("UPWK", "Upwork Inc", "NASDAQ", "Technology"),
    ("USCF", "United States Commodity Fund", "NYSE", "Financial Services"),
    ("UVSP", "Univest Financial", "NASDAQ", "Financial Services"),
    ("VBTX", "Veritex Holdings", "NASDAQ", "Financial Services"),
    ("VCNX", "Vaccinex Inc", "NASDAQ", "Healthcare"),
    ("VIAV", "Viavi Solutions", "NASDAQ", "Technology"),
    ("VIVO", "Meridian Bioscience", "NASDAQ", "Healthcare"),
    ("VRTS", "Virtus Investment Partners", "NASDAQ", "Financial Services"),
    ("VSCO", "Victoria's Secret & Co", "NYSE", "Consumer Cyclical"),
    ("VSEC", "VSE Corp", "NASDAQ", "Industrials"),
    ("WABC", "Westamerica Bancorporation", "NASDAQ", "Financial Services"),
    ("WAFD", "Washington Federal", "NASDAQ", "Financial Services"),
    ("WASH", "Washington Trust Bancorp", "NASDAQ", "Financial Services"),
    ("WERN", "Werner Enterprises", "NASDAQ", "Industrials"),
    ("WEYS", "Weyco Group", "NASDAQ", "Consumer Cyclical"),
    ("WLKP", "Westlake Chemical Partners", "NYSE", "Basic Materials"),
    ("WNC", "Wabash National Corp", "NYSE", "Industrials"),
    ("WRLD", "World Acceptance Corp", "NASDAQ", "Financial Services"),
    ("WTBA", "West Bancorporation", "NASDAQ", "Financial Services"),
    ("WTTR", "Select Water Solutions", "NYSE", "Energy"),
    ("XNCR", "Xencor Inc", "NASDAQ", "Healthcare"),
    ("YELP", "Yelp Inc", "NYSE", "Communication Services"),
    ("YMAB", "Y-mAbs Therapeutics", "NASDAQ", "Healthcare"),
    ("YORW", "York Water Co", "NASDAQ", "Utilities"),
    ("ZEUS", "Olympic Steel", "NASDAQ", "Basic Materials"),
]


def fetch_sp500():
    """Fetch S&P 500 from Wikipedia. Returns list of (ticker, name, exchange, sector_yf)."""
    try:
        import requests
        import pandas as pd
        from io import StringIO
        import warnings

        headers = {"User-Agent": "Mozilla/5.0 (compatible; AeternusResearch/1.0)"}
        resp = requests.get(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers=headers,
            timeout=30,
            verify=False,  # corporate proxy / cert store issue on dev Mac
        )
        resp.raise_for_status()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            dfs = pd.read_html(StringIO(resp.text))

        df = dfs[0]
        df.columns = [c.strip() for c in df.columns]
        rows = []
        for _, row in df.iterrows():
            ticker = str(row.get("Symbol", "") or "").strip().replace(".", "-")
            name = str(row.get("Security", "") or "").strip()
            # Wikipedia table has no Exchange column; use GICS to infer
            exchange = "NYSE"
            gics_sector = str(row.get("GICS Sector", "") or "").strip()
            sector_yf = _gics_to_yfinance(gics_sector)
            if ticker and len(ticker) <= 6:
                rows.append((ticker, name, exchange, sector_yf))
        print(f"  S&P 500: fetched {len(rows)} tickers from Wikipedia")
        return rows
    except Exception as e:
        print(f"  WARNING: Could not fetch S&P 500 from Wikipedia: {e}")
        return []


def _gics_to_yfinance(gics_sector: str) -> str:
    """Map GICS sector name to yfinance sector name."""
    _MAP = {
        "Information Technology": "Technology",
        "Health Care": "Healthcare",
        "Financials": "Financial Services",
        "Consumer Discretionary": "Consumer Cyclical",
        "Communication Services": "Communication Services",
        "Industrials": "Industrials",
        "Consumer Staples": "Consumer Defensive",
        "Energy": "Energy",
        "Utilities": "Utilities",
        "Real Estate": "Real Estate",
        "Materials": "Basic Materials",
    }
    return _MAP.get(gics_sector, "")


def main():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    print("Generating universe_constituents.csv...")

    # Step 1: S&P 500 from Wikipedia
    sp500_rows = fetch_sp500()

    # Step 2: Russell 2000 sample (hardcoded)
    russell_rows = [
        (ticker, name, exchange, sector_yf)
        for ticker, name, exchange, sector_yf in RUSSELL_2000_SAMPLE
    ]
    print(f"  Russell 2000 sample: {len(russell_rows)} tickers (hardcoded)")

    # Merge and deduplicate (S&P 500 takes priority)
    seen = set()
    all_rows = []
    for ticker, name, exchange, sector_yf in sp500_rows + russell_rows:
        ticker = ticker.upper().strip()
        if not ticker or len(ticker) > 6:
            continue
        if ticker in seen:
            continue
        seen.add(ticker)
        all_rows.append((ticker, name, exchange, sector_yf))

    all_rows.sort(key=lambda r: r[0])

    # Write CSV
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ticker", "name", "exchange", "sector_yf"])
        for ticker, name, exchange, sector_yf in all_rows:
            writer.writerow([ticker, name, exchange, sector_yf])

    print(f"Wrote {len(all_rows)} rows to {OUTPUT_PATH}")
    return len(all_rows)


if __name__ == "__main__":
    count = main()
    sys.exit(0)
