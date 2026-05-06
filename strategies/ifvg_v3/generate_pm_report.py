import pandas as pd
import json
import os
import datetime
from pathlib import Path

# Paths to data artifacts
SIGNALS_FILE = "live_signals.json"
PORTFOLIO_FILE = "portfolio_ticker_results.csv"
REPORTS_DIR = "execution_reports"
WATCHLIST_DB = "watchlist.db" # Required for Market Cap and Sector filtering

def generate_pm_report():
    print("[*] Generating PM Execution Report...")
    
    # 1. Load Live Signals
    if not os.path.exists(SIGNALS_FILE):
        print("[!] No live_signals.json found. Engine must run first.")
        return
        
    with open(SIGNALS_FILE, "r") as f:
        signals = json.load(f)
        
    if not signals:
        print("[*] No active signals to report today.")
        return
        
    sig_df = pd.DataFrame(signals)
    
    # 2. Extract specific actionable setups
    # We want to give the PM the raw LIMIT entries.
    # We also want to give them "Radar" setups (EXPANDING_CASCADE)
    limit_entries = sig_df[sig_df['Action'].str.contains("SHORT LIMIT", na=False)].copy()
    radar_entries = sig_df[sig_df['Type'] == "EXPANDING_CASCADE"].copy()
    
    print(f"[*] Found {len(limit_entries)} raw resting limit signals.")
    
    # 3. Load Portfolio Alpha Metrics to filter noise
    if not os.path.exists(PORTFOLIO_FILE):
        print("[!] No portfolio_ticker_results.csv found. Cannot score alpha.")
        return
        
    port_df = pd.read_csv(PORTFOLIO_FILE)
    
    # Clean Portfolio metrics for matching
    port_df['Win Rate'] = port_df['Win Rate'].str.rstrip('%').astype(float)
    port_df['Total PnL Value'] = port_df['Total PnL'].str.replace('$', '').astype(float)
    port_df['Avg R:R'] = port_df['Avg R:R'].str.rstrip('R').astype(float)
    
    # Merge signal data with historical performance
    merged = pd.merge(limit_entries, port_df, on='Ticker', how='inner')
    
    # 4. Step 1 Filter: Institutional Untradables & Low Alpha
    # Filter 1: Must make money historically (Win Rate > 35%, R:R > 1.1)
    # Filter 2: Market Cap > $1B (Assuming naive string parse for now, or assume it's pre-filtered in SQLite)
    
    # First, parse Market Cap from string like $102.5B or $800M
    def parse_mcap(mcap_str):
        if pd.isna(mcap_str) or mcap_str == "Unknown" or mcap_str == 0.0:
            return 0.0
        try:
            val_str = str(mcap_str).replace('$', '').replace(',', '').strip()
            multiplier = 1
            if val_str.upper().endswith('T'):
                multiplier = 1e12
                val_str = val_str[:-1]
            elif val_str.upper().endswith('B'):
                multiplier = 1e9
                val_str = val_str[:-1]
            elif val_str.upper().endswith('M'):
                multiplier = 1e6
                val_str = val_str[:-1]
            return float(val_str) * multiplier
        except:
            return 0.0

    merged['MarketCap_Num'] = merged['Market Cap'].apply(parse_mcap)

    # ── No-Short Exclusion List ────────────────────────────────────────
    # Major indices and top 25 market cap companies — too big to short
    NO_SHORT = {
        # Major Index ETFs
        'SPY', 'QQQ', 'IWM', 'DIA', 'VOO', 'VTI',
        # Top 25 by Market Cap (mega-caps)
        'AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL', 'GOOG', 'META', 'BRK-B', 'TSLA',
        'AVGO', 'LLY', 'JPM', 'V', 'UNH', 'WMT', 'XOM', 'MA', 'JNJ', 'PG',
        'COST', 'HD', 'ORCL', 'ABBV', 'CRM', 'NFLX',
    }
    pre_exclusion = len(merged)
    merged = merged[~merged['Ticker'].isin(NO_SHORT)]
    excluded_count = pre_exclusion - len(merged)
    if excluded_count > 0:
        print(f"[*] Excluded {excluded_count} mega-cap / index signals (no-short list).")
    
    # Apply Baseline Institutional Filters
    filtered = merged[
        (merged['Win Rate'] >= 35.0) & 
        (merged['Avg R:R'] >= 1.1) & 
        (merged['MarketCap_Num'] >= 1_000_000_000) # Only > $1B MCAP
    ].copy()
    
    print(f"[*] {len(filtered)} signals survived Institutional Liquidity and Alpha filters.")
    
    if len(filtered) == 0:
        print("[*] No signals survived the baseline filter today.")
        _write_empty_report()
        return

    # 5. The Ranking Heuristic Score
    # We want the limit to be close to the current price (Proximity)
    # And we want high absolute historical PnL
    
    def extract_limit_price(price_str):
        try:
            return float(str(price_str).replace('$', '').replace(',', '').strip())
        except:
            return 0.0
            
    filtered['Limit_Price'] = filtered['Price'].apply(extract_limit_price)
    
    # Assume 'price' from today's live_signals to calculate proximity
    # We don't have exact close price in live_signals, we just have 'action' limit prices. 
    # For now, we weight purely by Historical Yield and R:R
    
    # Normalize Yield 0-1
    max_pnl = filtered['Total PnL Value'].max()
    if max_pnl > 0:
        filtered['Yield_Score'] = filtered['Total PnL Value'] / max_pnl
    else:
        filtered['Yield_Score'] = 0.0
        
    filtered['Alpha_Score'] = (filtered['Win Rate'] / 100) * filtered['Avg R:R']
    
    filtered['Total_Score'] = (filtered['Yield_Score'] * 0.4) + (filtered['Alpha_Score'] * 0.6)
    filtered = filtered.sort_values(by='Total_Score', ascending=False)
    
    # 6. Sector Diversification Constraints
    # PM wants Top 10, max 2 per sector.
    
    top_10 = []
    bench = []
    sector_counts = {}
    
    for _, row in filtered.iterrows():
        sector = str(row['Sector'])
        if sector not in sector_counts:
            sector_counts[sector] = 0
            
        if len(top_10) < 10:
            if sector_counts[sector] < 2:
                top_10.append(row)
                sector_counts[sector] += 1
            else:
                # Sector capped out, push to bench
                bench.append(row)
        else:
            bench.append(row)

    # Convert back to DFs
    top_10_df = pd.DataFrame(top_10)
    bench_df = pd.DataFrame(bench).head(10) # Next 10
    
    _write_report(top_10_df, bench_df, radar_entries)

def _write_empty_report():
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    report_path = Path(REPORTS_DIR) / f"execution_report_{today}.md"
    content = f"# Daily PM Execution Report: {today}\n"
    content += "## Zero high-conviction signals triggered today.\n"
    with open(report_path, "w") as f:
        f.write(content)
        
    json_output_path = Path(REPORTS_DIR) / "pm_conviction_stack.json"
    json_payload = {
        "generated_at": today,
        "top_10": []
    }
    with open(json_output_path, "w") as f:
        json.dump(json_payload, f, indent=4)
        
def _write_report(top_10, bench, radar):
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    report_path = Path(REPORTS_DIR) / f"execution_report_{today}.md"
    
    with open(report_path, "w") as f:
        f.write(f"# Daily PM Execution Report\n")
        f.write(f"**Date:** {today}\n\n")
        
        f.write("## 🎯 Top 10 Conviction Limits (For Tomorrow's Open)\n")
        f.write("> Highly filtered setups ranked by Historical Yield and algorithmic R:R. Max 2 limits per market sector to preserve correlation isolation.\n\n")
        
        f.write("> [!IMPORTANT]\n")
        f.write("> **Execution Rule:** If price closes above the **Daily SMA10** before hitting the Profit Target, the position must be terminated immediately regardless of PnL. This is our primary dynamic risk-exhaustion signal.\n\n")
        
        if top_10.empty:
            f.write("No top conviction limits cleared the $1B Liquidity constraint today.\n\n")
        else:
            f.write("| Ticker | Sector | Market Cap | Limit Entry | Hist. PnL | Win Rate | Avg R:R | Strategy Action |\n")
            f.write("|---|---|---|---|---|---|---|---|\n")
            for _, r in top_10.iterrows():
                f.write(f"| **{r['Ticker']}** | {r['Sector']} | {r['Market Cap']} | **${r['Limit_Price']:.2f}** | ${r['Total PnL Value']:.2f} | {r['Win Rate']}% | {r['Avg R:R']}R | {r['Warning']} |\n")
        
        f.write("\n---\n\n## 🪑 The Bench (Next 10 Viable Limits)\n")
        f.write("> Liquidity-approved setups that were demoted due to Sector Allocation caps or slightly weaker historical yield curves.\n\n")
        
        if bench.empty:
            f.write("No bench candidates available.\n\n")
        else:
            f.write("| Ticker | Sector | Market Cap | Limit Entry | Hist. PnL | Win Rate | Strategy Action |\n")
            f.write("|---|---|---|---|---|---|---|\n")
            for _, r in bench.iterrows():
                f.write(f"| {r['Ticker']} | {r['Sector']} | {r['Market Cap']} | ${r['Limit_Price']:.2f} | ${r['Total PnL Value']:.2f} | {r['Win Rate']}% | {r['Warning']} |\n")

        f.write("\n---\n\n## 📡 Market Radar (Expansion Cascades)\n")
        f.write("> Tickers currently experiencing violent algorithmic displacement vectors. Do not short. Wait for Daily exhaustion to print an Equilibrium level.\n\n")
        
        if radar.empty:
            f.write("No active cascades today.\n")
        else:
            # Just show top 15 radar
            radar_subset = radar.head(15)
            f.write("| Ticker | Current State | Target Eq | Note |\n")
            f.write("|---|---|---|---|\n")
            for _, r in radar_subset.iterrows():
                f.write(f"| **{r['Ticker']}** | {r['Type']} | {r['Warning']} | {r['Date']} |\n")

    # [NEW] Generate JSON payload for Next.js frontend
    json_output_path = Path(REPORTS_DIR) / "pm_conviction_stack.json"
    
    # Safely convert to list of dicts if not empty
    top_10_list = []
    if not top_10.empty:
        # Keep only essential columns to pass to frontend
        frontend_cols = ['Ticker', 'Sector', 'Market Cap', 'Limit_Price', 'Total PnL Value', 'Win Rate', 'Avg R:R']
        export_df = top_10[frontend_cols].copy()
        export_df = export_df.rename(columns={'Market Cap': 'Market_Cap', 'Total PnL Value': 'Total_PnL', 'Win Rate': 'Win_Rate', 'Avg R:R': 'Avg_RR'})
        top_10_list = export_df.to_dict(orient='records')
        
    json_payload = {
        "generated_at": today,
        "top_10": top_10_list
    }
    
    with open(json_output_path, "w") as f:
        json.dump(json_payload, f, indent=4)

    print(f"\n[+] Successfully generated PDF/MD: {report_path}")
    print(f"[+] Successfully exported React JSON: {json_output_path}")

if __name__ == "__main__":
    generate_pm_report()
