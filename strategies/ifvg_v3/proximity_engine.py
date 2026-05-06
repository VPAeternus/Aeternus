"""
Live Proximity Engine
Fetches current prices for the Top 10 PM conviction tickers and calculates
the percentage distance from each current price to its resting limit entry.
Outputs a small JSON file consumed by the Next.js dashboard.
"""

import json
import os
import datetime
import yfinance as yf

STACK_FILE = "execution_reports/pm_conviction_stack.json"
OUTPUT_FILE = "execution_reports/proximity_data.json"


def run_proximity_engine():
    # 1. Load conviction stack
    if not os.path.exists(STACK_FILE):
        print("[!] No pm_conviction_stack.json found. Run generate_pm_report.py first.")
        return

    with open(STACK_FILE, "r") as f:
        stack = json.load(f)

    tickers_data = stack.get("top_10", [])
    if not tickers_data:
        print("[*] No tickers in conviction stack.")
        return

    symbols = [t["Ticker"] for t in tickers_data]
    limit_map = {t["Ticker"]: t["Limit_Price"] for t in tickers_data}

    print(f"[*] Fetching live prices for {len(symbols)} tickers: {', '.join(symbols)}")

    # 2. Fetch current prices individually for reliability
    current_prices = {}
    for sym in symbols:
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="5d")
            if not hist.empty:
                current_prices[sym] = float(hist["Close"].iloc[-1])
            else:
                current_prices[sym] = None
        except Exception:
            current_prices[sym] = None

    # 3. Calculate proximity
    results = []
    for ticker_data in tickers_data:
        ticker = ticker_data["Ticker"]
        limit = ticker_data["Limit_Price"]
        current = current_prices.get(ticker)

        if current is None or current == 0:
            results.append({
                "ticker": ticker,
                "limit": limit,
                "current": None,
                "distance_pct": None,
                "heat": "UNKNOWN"
            })
            continue

        # Distance: how far current price is ABOVE the limit (positive = price still above limit)
        # Negative = price already below limit (order would have been filled)
        distance_pct = round(((current - limit) / current) * 100, 2)

        if distance_pct < 0:
            heat = "FILLED"
        elif distance_pct <= 2.0:
            heat = "HOT"
        elif distance_pct <= 5.0:
            heat = "WARM"
        else:
            heat = "COLD"

        results.append({
            "ticker": ticker,
            "limit": limit,
            "current": round(current, 2),
            "distance_pct": distance_pct,
            "heat": heat
        })

    # Sort by proximity (closest first)
    results.sort(key=lambda x: x["distance_pct"] if x["distance_pct"] is not None else 999)

    # 4. Write output
    output = {
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "tickers": results
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n[+] Proximity data written to {OUTPUT_FILE}")
    for r in results:
        icon = {"HOT": "🔴", "WARM": "🟡", "COLD": "⚪", "FILLED": "✅", "UNKNOWN": "❓"}[r["heat"]]
        dist = f"{r['distance_pct']}%" if r['distance_pct'] is not None else "N/A"
        print(f"    {icon} {r['ticker']:6s}  Limit: ${r['limit']:<10.2f}  Current: ${r.get('current', 'N/A')}  Distance: {dist}  [{r['heat']}]")


if __name__ == "__main__":
    run_proximity_engine()
