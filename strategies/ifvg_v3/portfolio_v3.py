import pandas as pd
import json
import concurrent.futures
import yfinance as yf
from ifvg_strategy_v3 import EquilibriumStrategyV3
import watchlist_manager
import data_cache

class V3PortfolioExecutor:
    """
    Unified Portfolio Executor for the V3 Equilibrium Displacement Model.
    Executes the strategy across an array of tickers and aggregates the 
    global mathematical performance into a single report.
    """
    def __init__(self, tickers=None, start_date="2000-01-01", target_pct=0.05, 
                 sma50_filter="BELOW", sma10_exit="CLOSE", vix_filter=True):
        self.tickers = tickers if tickers else watchlist_manager.get_tickers()
        self.start_date = start_date
        self.target_pct = target_pct
        self.sma50_filter = sma50_filter
        self.sma10_exit = sma10_exit
        self.vix_filter = vix_filter
        
        # Tracking
        self.portfolio_trades = []
        self.ticker_results = []
        self.live_signals = []
        self.strategy_runs = {}
        self.enriched_data = watchlist_manager.get_enriched_tickers()
        
    def _process_ticker(self, ticker, preloaded_vix):
        try:
            bot = EquilibriumStrategyV3(
                ticker=ticker,
                start_date=self.start_date,
                target_pct=self.target_pct,
                sma50_filter=self.sma50_filter,
                sma10_exit=self.sma10_exit,
                vix_filter=self.vix_filter,
                verbose=False,
                preloaded_vix=preloaded_vix
            )
            bot.download_data()
            bot.run_simulation()
            return ticker, bot
        except Exception as e:
            print(f"[!] Error processing {ticker}: {e}")
            return ticker, None

    def run_portfolio(self):
        print(f"=== V3 EQUILIBRIUM PORTFOLIO EXECUTOR ===")
        print(f"Tickers: {len(self.tickers)}")
        print(f"Parameters: Target {self.target_pct*100}% | SMA50 {self.sma50_filter} | SMA10 {self.sma10_exit} | VIX Filter {self.vix_filter}")
        print("-" * 50)
        
        if len(self.tickers) == 0:
            print("[!] No tickers provided. Add tickers using watchlist_manager.py")
            return
            
        preloaded_vix = None
        if self.vix_filter:
            print("[*] Pre-fetching Global VIX data using Data Cache...")
            start_dt = pd.to_datetime(self.start_date) - pd.DateOffset(days=365)
            vix_df = data_cache.get_cached_ticker_data("^VIX", start_dt.strftime("%Y-%m-%d"))
            preloaded_vix = vix_df
            
        print(f"[*] Beginning threaded execution mapped across {len(self.tickers)} tickers...")
        
        processed_count = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(self._process_ticker, t, preloaded_vix): t for t in self.tickers}
            
            for future in concurrent.futures.as_completed(futures):
                ticker = futures[future]
                processed_count += 1
                if processed_count % 50 == 0:
                    print(f"    ...processed {processed_count}/{len(self.tickers)} tickers...")
                    
                _, bot = future.result()
                if bot:
                    self.strategy_runs[ticker] = bot
                    # Aggregate trades
                    for t in bot.trades:
                        self.portfolio_trades.append(t)
                    
                    # Metric calculation for individual ticker
                    trades_count = len(bot.trades)
                    edata = self.enriched_data.get(ticker, {"etfs":"", "sector":"Unknown", "market_cap":0})
                    
                    if trades_count > 0:
                        df = pd.DataFrame([t.__dict__ for t in bot.trades])
                        winners = df[df['pnl'] > 0]
                        losers = df[df['pnl'] <= 0]
                        pnl = df['pnl'].sum()
                        win_rate = len(winners) / trades_count * 100
                        
                        avg_win = winners['pnl'].mean() if len(winners) > 0 else 0
                        avg_loss = losers['pnl'].mean() if len(losers) > 0 else 0
                        rr = abs(avg_win / avg_loss) if avg_loss != 0 else 0
                        
                        self.ticker_results.append({
                            "Ticker": ticker,
                            "ETFs": edata.get("etfs", ""),
                            "Sector": edata.get("sector", "Unknown"),
                            "Market Cap": edata.get("market_cap", 0),
                            "Trades": trades_count,
                            "Win Rate": f"{win_rate:.1f}%",
                            "Total PnL": f"${pnl:.2f}",
                            "Avg R:R": f"{rr:.2f}R"
                        })
                    else:
                        self.ticker_results.append({
                            "Ticker": ticker,
                            "ETFs": edata.get("etfs", ""),
                            "Sector": edata.get("sector", "Unknown"),
                            "Market Cap": edata.get("market_cap", 0),
                            "Trades": 0,
                            "Win Rate": "0.0%",
                            "Total PnL": "$0.00",
                            "Avg R:R": "0.00R"
                        })
                        
                    # Extract Live Market State for Tomorrow
                    self._extract_live_signals(ticker, bot)

    def _extract_live_signals(self, ticker, bot):
        """
        Pulls the final state of the state machine after processing the most recent 
        Daily Close, emitting actionable signals for tomorrow's open.
        """
        if len(bot.data) == 0: return
        
        last_bar = bot.data.iloc[-1]
        last_date = last_bar.name.strftime('%Y-%m-%d')
        
        # 1. Check for Active Open Shorts
        for trade in bot.active_shorts:
            # Check if tomorrow needs a manual abort based on today's close > SMA10
            close_abort = bot.sma10_exit != "NONE" and last_bar['close'] > last_bar['sma10']
            
            self.live_signals.append({
                "Ticker": ticker,
                "Type": "ACTIVE_SHORT",
                "Action": "HOLD",
                "Price": f"${trade.entry_price:.2f}",
                "Warning": "ABORT AT TOMORROW'S CLOSE (SMA10 Breach)" if close_abort else "Monitor SMA10/Target",
                "Date": last_date
            })
            
        # 2. Check for Resting Limit Orders (Retracing Phase)
        if len(bot.active_shorts) == 0 and bot.impulse.state == "RETRACING":
            
            # Regime Filter Checks
            regime_pass = True
            if bot.sma50_filter == "BELOW" and last_bar['close'] >= last_bar['sma50']:
                regime_pass = False
            
            if regime_pass:
                # We do NOT check VIX here, because VIX must be checked at Tomorrow's Open.
                # We just alert the operator that the Limit Order is structurally live.
                self.live_signals.append({
                    "Ticker": ticker,
                    "Type": "RESTING_LIMIT",
                    "Action": "SHORT LIMIT",
                    "Price": f"${bot.impulse.equilibrium:.2f}",
                    "Warning": "Valid Equilibrium Entry",
                    "Date": last_date
                })
                
        # 3. Check for Active Displacements (Expanding)
        if len(bot.active_shorts) == 0 and bot.impulse.state == "EXPANDING":
            self.live_signals.append({
                "Ticker": ticker,
                "Type": "EXPANDING_CASCADE",
                "Action": "WAIT FOR DAILY EXHAUSTION",
                "Price": "--",
                "Warning": f"Target Eq: ${bot.impulse.equilibrium:.2f} (Shifting)",
                "Date": last_date
            })

    def generate_report(self):
        print("\n=== INDIVIDUAL TICKER PERFORMANCE ===")
        res_df = pd.DataFrame(self.ticker_results)
        print(res_df.to_string(index=False))
        
        # Export individual ticker results to CSV for analysis
        res_df.to_csv("portfolio_ticker_results.csv", index=False)
        print("\n[+] Exported portfolio_ticker_results.csv")
        
        print("\n=== MACRO PORTFOLIO PERFORMANCE ===")
        if len(self.portfolio_trades) == 0:
            print("No trades executed across portfolio.")
            return
            
        global_df = pd.DataFrame([t.__dict__ for t in self.portfolio_trades])
        total_pnl = global_df['pnl'].sum()
        total_trades = len(global_df)
        
        global_winners = global_df[global_df['pnl'] > 0]
        global_losers = global_df[global_df['pnl'] <= 0]
        
        global_win_rate = len(global_winners) / total_trades * 100
        avg_global_win = global_winners['pnl'].mean() if len(global_winners) > 0 else 0
        avg_global_loss = global_losers['pnl'].mean() if len(global_losers) > 0 else 0
        global_rr = abs(avg_global_win / avg_global_loss) if avg_global_loss != 0 else 0

        print(f"Total Unique Trades: {total_trades}")
        print(f"Global Win Rate:     {global_win_rate:.1f}%")
        print(f"Global R:R Ratio:    {global_rr:.2f}R")
        print(f"Total Portfolio PnL: ${total_pnl:.2f}")
        print(f"Avg Winner: ${avg_global_win:.2f} | Avg Loser: ${avg_global_loss:.2f}")
        
        print("\n=== 📡 LIVE SIGNALS (FOR TOMORROW'S OPEN) ===")
        if len(self.live_signals) == 0:
            print("No active structural limits or open trades detected.")
            # Still write an empty JSON array
            with open("live_signals.json", "w") as f:
                json.dump([], f)
        else:
            sig_df = pd.DataFrame(self.live_signals)
            print(sig_df.to_string(index=False))
            
            # Export to JSON
            with open("live_signals.json", "w") as f:
                json.dump(self.live_signals, f, indent=4)
            print("\n[+] Exported live_signals.json")

if __name__ == "__main__":
    # Test the unified executor using the SQLite watchlist
    executor = V3PortfolioExecutor(tickers=None, vix_filter=False)
    executor.run_portfolio()
    executor.generate_report()
