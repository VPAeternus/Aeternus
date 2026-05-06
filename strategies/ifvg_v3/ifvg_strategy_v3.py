import yfinance as yf
import pandas as pd
import numpy as np
import data_cache
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class FVG:
    top: float      
    bottom: float   
    date_formed: pd.Timestamp
    middle: float   
    lowest_low: float = 0.0
    highest_high: float = 0.0
    type: str = "BULLISH" # BULLISH or BEARISH

@dataclass
class ImpulseLeg:
    state: str = "HUNTING" # HUNTING, EXPANDING, RETRACING
    swing_high: float = 0.0
    swing_low: float = 0.0
    equilibrium: float = 0.0

@dataclass
class Trade:
    ticker: str
    type: str
    entry_date: pd.Timestamp
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    exit_date: Optional[pd.Timestamp] = None
    exit_price: float = 0.0
    reason: str = ""
    pnl: float = 0.0
    status: str = "OPEN"

class EquilibriumStrategyV3:
    def __init__(self, ticker="QQQ", start_date="2000-01-01", target_pct=0.10, sma50_filter="ANY", sma10_exit="CLOSE", vix_filter=False, verbose=True, preloaded_vix=None, entry_level=0.618):
        self.ticker = ticker
        self.start_date = start_date
        self.target_pct = target_pct
        self.sma50_filter = sma50_filter # "ABOVE", "BELOW", or "ANY"
        self.sma10_exit = sma10_exit # "CLOSE" or "OPEN_OR_CLOSE"
        self.vix_filter = vix_filter
        self.verbose = verbose
        self.entry_level = entry_level
        self.preloaded_vix = preloaded_vix
        self.data: pd.DataFrame = None
        self.vix_data: pd.DataFrame = None
        
        # Structural Zones
        self.active_bullish_fvgs: List[FVG] = []
        self.active_bearish_fvgs: List[FVG] = []
        self.all_historical_bullish_fvgs: List[FVG] = [] # Memory for hunt evaluation
        
        self.impulse = ImpulseLeg()
        
        # Order Tracking
        self.active_shorts: List[Trade] = []
        self.trades: List[Trade] = []
        self.equity_curve = []
        
        # Metric tracking (1-Share Basis)
        self.current_equity = 10000.0 # Base

    def download_data(self):
        if hasattr(self, 'verbose') and self.verbose:
            print(f"Downloading Structural Data for {self.ticker}...")
        
        df = data_cache.get_cached_ticker_data(self.ticker, self.start_date)
        
        # Calculate Technical Baselines
        df['sma50'] = df['close'].rolling(window=50).mean()
        df['sma20'] = df['close'].rolling(window=20).mean()
        df['sma10'] = df['close'].rolling(window=10).mean()
        
        self.data = df[df.index >= self.start_date]
        
        if self.vix_filter:
            if self.preloaded_vix is not None:
                self.vix_data = self.preloaded_vix
            else:
                if self.verbose:
                    print("Downloading VIX data (^VIX)...")
                start_dt = pd.to_datetime(self.start_date) - pd.DateOffset(days=365)
                vix_df = yf.download("^VIX", start=start_dt.strftime("%Y-%m-%d"), progress=False, auto_adjust=False)
                if isinstance(vix_df.columns, pd.MultiIndex): vix_df.columns = vix_df.columns.get_level_values(0)
                vix_df.columns = [c.lower() for c in vix_df.columns]
                vix_df.reset_index(inplace=True)
                if 'datetime' in vix_df.columns: vix_df.rename(columns={'datetime': 'date'}, inplace=True)
                if 'date' in vix_df.columns:
                    vix_df['date'] = pd.to_datetime(vix_df['date'])
                    vix_df.set_index('date', inplace=True)
                self.vix_data = vix_df

            if self.vix_data is not None and not self.vix_data.empty:
                if getattr(self.data.index, 'tz', None) is not None:
                    self.data.index = self.data.index.tz_localize(None)
                if getattr(self.vix_data.index, 'tz', None) is not None:
                    self.vix_data.index = self.vix_data.index.tz_localize(None)
                    
                vix_series = self.vix_data['open'].rename('vix_open')
                self.data = self.data.merge(vix_series, left_index=True, right_index=True, how='left')

    def _close_trade(self, trade, date, price, reason):
        trade.exit_date = date
        trade.exit_price = price
        trade.status = "CLOSED"
        trade.reason = reason
        trade.pnl = (trade.entry_price - price) * trade.quantity

    def run_simulation(self):
        print(f"Running V3 Equilibrium Simulation on {self.ticker}...")
        
        for i in range(len(self.data)):
            curr = self.data.iloc[i]
            date = self.data.index[i]
            
            # --- 1. Manage Active Short Trades ---
            active_shorts_keep = []
            for trade in self.active_shorts:
                closed_this_bar = False
                
                # We will check if it hits SP or TP.
                # If gap up over stop loss, execute at open or SP.
                if curr['high'] >= trade.stop_loss:
                    self._close_trade(trade, date, trade.stop_loss, "STOP_LOSS")
                    self.trades.append(trade)
                    self.current_equity += trade.pnl
                    closed_this_bar = True
                    
                    # Optional: reset impulse leg if stopped out
                    self.impulse.state = "HUNTING"
                    
                elif curr['low'] <= trade.take_profit:
                    self._close_trade(trade, date, trade.take_profit, "TAKE_PROFIT")
                    self.trades.append(trade)
                    self.current_equity += trade.pnl
                    closed_this_bar = True
                    
                    self.impulse.state = "HUNTING"

                # SMA10 Trailing Stop Exit
                elif self.sma10_exit == "OPEN_OR_CLOSE" and curr['open'] > curr['sma10']:
                    self._close_trade(trade, date, curr['open'], "SMA10_TRAIL_GAP_UP")
                    self.trades.append(trade)
                    self.current_equity += trade.pnl
                    closed_this_bar = True
                    self.impulse.state = "HUNTING"
                
                elif curr['close'] > curr['sma10']:
                    self._close_trade(trade, date, curr['close'], "SMA10_TRAIL")
                    self.trades.append(trade)
                    self.current_equity += trade.pnl
                    closed_this_bar = True
                    self.impulse.state = "HUNTING"

                if not closed_this_bar:
                    active_shorts_keep.append(trade)
            
            self.active_shorts = active_shorts_keep

            # --- 2. Phase 4: The Trap (Entry) ---
            if self.impulse.state == "RETRACING" and len(self.active_shorts) == 0:
                if self.verbose and "2022-03-01" <= date.strftime("%Y-%m-%d") <= "2022-03-15":
                    print(f"[{date.date()}] Retracing... Target Eq: {self.impulse.equilibrium:.2f} | Today's High: {curr['high']:.2f} | Open: {curr['open']:.2f} | Close: {curr['close']:.2f} | SMA50: {curr['sma50']:.2f}")
                    print(f"    -> Anchors: Swing High = {self.impulse.swing_high:.2f} | Swing Low = {self.impulse.swing_low:.2f}")

                # Limit short order resting at equilibrium
                if curr['high'] >= self.impulse.equilibrium:
                    
                    # Filter by SMA50 baseline bias
                    allow_entry = True
                    if self.sma50_filter == "BELOW" and curr['close'] >= curr['sma50']:
                        allow_entry = False
                    elif self.sma50_filter == "ABOVE" and curr['close'] <= curr['sma50']:
                        allow_entry = False
                        
                    # Filter by VIX Open Regime
                    if allow_entry and getattr(self, "vix_filter", False) and self.vix_data is not None:
                        vix_open = 20.0 # fallback default if nothing exists
                        if date in self.vix_data.index:
                            v_val = self.vix_data.loc[date, 'open']
                            if isinstance(v_val, pd.Series): v_val = v_val.iloc[0]
                            vix_open = float(v_val)
                        else:
                            try:
                                nearest_idx = self.vix_data.index.get_indexer([date], method='pad')[0]
                                v_val = self.vix_data.iloc[nearest_idx]['close']
                                if isinstance(v_val, pd.Series): v_val = v_val.iloc[0]
                                vix_open = float(v_val)
                            except: pass
                            
                        # Goldilocks (15-30) or Crisis (>40)
                        if not ((15 <= vix_open <= 30) or (vix_open >= 40)):
                            allow_entry = False
                    
                    if allow_entry:
                        # Real-world limit order mechanics: 
                        # If the market gaps up and opens above our limit price, we get filled at the open.
                        if curr['open'] > self.impulse.equilibrium:
                            entry_price = curr['open']
                        else:
                            entry_price = self.impulse.equilibrium
                            
                        stop_loss = self.impulse.swing_high
                        take_profit = entry_price * (1.0 - self.target_pct)
                        
                        trade = Trade(
                            ticker=self.ticker,
                            type="EQ_SHORT",
                            entry_date=date,
                            entry_price=entry_price,
                            quantity=1.0,
                            stop_loss=stop_loss,
                            take_profit=take_profit
                        )
                        
                        # Handle same-bar stop or TP (Unlikely, but for completeness)
                        closed_same_bar = False
                        if curr['high'] >= trade.stop_loss:
                            self._close_trade(trade, date, trade.stop_loss, "STOP_LOSS")
                            self.trades.append(trade)
                            self.current_equity += trade.pnl
                            closed_same_bar = True
                        elif curr['low'] <= trade.take_profit:
                            self._close_trade(trade, date, trade.take_profit, "TAKE_PROFIT")
                            self.trades.append(trade)
                            self.current_equity += trade.pnl
                            closed_same_bar = True
                        
                        # Apply SMA10 Exit logic on the entry day
                        elif self.sma10_exit == "OPEN_OR_CLOSE" and curr['open'] > curr['sma10']:
                            self._close_trade(trade, date, curr['open'], "SMA10_TRAIL_GAP_UP")
                            self.trades.append(trade)
                            self.current_equity += trade.pnl
                            closed_same_bar = True
                            
                        elif curr['close'] > curr['sma10']:
                            self._close_trade(trade, date, curr['close'], "SMA10_TRAIL")
                            self.trades.append(trade)
                            self.current_equity += trade.pnl
                            closed_same_bar = True
                            
                        if not closed_same_bar:
                            self.active_shorts.append(trade)
                    
                    # ALWAYS reset state machine to HUNTING once the equilibrium trap is triggered 
                    # (whether we took the trade or filtered it out)
                    self.impulse.state = "HUNTING"

            # --- 3. Phase 1-3: Impulse Tracking ---
            new_bearish_fvg_today = None
            
            if i >= 2:
                bar_minus_2 = self.data.iloc[i-2]
                bar_minus_1 = self.data.iloc[i-1]
                
                # Detect Bullish FVG
                if curr['low'] > bar_minus_2['high']:
                    if curr['low'] > bar_minus_2['high']: # redundancy
                         lowest_low = min(curr['low'], bar_minus_1['low'], bar_minus_2['low'])
                         new_fvg = FVG(
                             top=curr['low'],
                             bottom=bar_minus_2['high'],
                             date_formed=date,
                             middle=(curr['low'] + bar_minus_2['high']) / 2,
                             lowest_low=lowest_low,
                             type="BULLISH"
                         )
                         self.active_bullish_fvgs.append(new_fvg)
                         self.all_historical_bullish_fvgs.append(new_fvg)
                         
                # Detect Bearish FVG
                if curr['high'] < bar_minus_2['low']:
                    highest_high = max(curr['high'], bar_minus_1['high'], bar_minus_2['high'])
                    new_bearish_fvg_today = FVG(
                        top=bar_minus_2['low'],
                        bottom=curr['high'],
                        date_formed=date,
                        middle=(bar_minus_2['low'] + curr['high']) / 2,
                        highest_high=highest_high,
                        type="BEARISH"
                    )
                    self.active_bearish_fvgs.append(new_bearish_fvg_today)

            # State Machine Logic
            if self.impulse.state == "HUNTING":
                if new_bearish_fvg_today:
                    # To confirm displacement, the Bearish FVG must break a Bullish FVG that was active right before the drop started.
                    # We check all historical FVGs that were valid right before bar_minus_2
                    valid_targets = []
                    for f in self.all_historical_bullish_fvgs:
                        # Only target FVGs formed before this bearish cascade started
                        if f.date_formed < bar_minus_2.name: 
                            valid_targets.append(f)
                            
                    if len(valid_targets) > 0:
                        highest_target_fvg = max(valid_targets, key=lambda f: f.bottom)
                        if curr['close'] < highest_target_fvg.lowest_low:
                            self.impulse.state = "EXPANDING"
                            self.impulse.swing_high = new_bearish_fvg_today.highest_high
                            self.impulse.swing_low = min(curr['low'], bar_minus_1['low'], bar_minus_2['low'])
            
            elif self.impulse.state == "EXPANDING":
                if new_bearish_fvg_today:
                    self.impulse.swing_high = new_bearish_fvg_today.highest_high
                    self.impulse.equilibrium = self.impulse.swing_low + (self.impulse.swing_high - self.impulse.swing_low) * self.entry_level
                    
                if curr['low'] < self.impulse.swing_low:
                    self.impulse.swing_low = curr['low']
                    self.impulse.equilibrium = self.impulse.swing_low + (self.impulse.swing_high - self.impulse.swing_low) * self.entry_level
                    
                # If we've closed higher than the swing low but haven't hit target
                if curr['close'] >= self.impulse.swing_low:
                    self.impulse.state = "RETRACING"
                    self.impulse.equilibrium = self.impulse.swing_low + (self.impulse.swing_high - self.impulse.swing_low) * self.entry_level
            
            elif self.impulse.state == "RETRACING":
                # If we haven't entered the trade yet, the anchors can still dynamically drop
                if len(self.active_shorts) == 0:
                    # If a new Bearish FVG prints during a temporary pause in the cascade, drop the Swing High
                    if new_bearish_fvg_today:
                        self.impulse.swing_high = new_bearish_fvg_today.highest_high
                        self.impulse.equilibrium = self.impulse.swing_low + (self.impulse.swing_high - self.impulse.swing_low) * self.entry_level
                        
                    # If the daily close flushes the Swing Low, resume the Expansion Phase
                    if curr['close'] < self.impulse.swing_low:
                        self.impulse.state = "EXPANDING"
                        self.impulse.swing_low = curr['low']
                


            # --- Maintain active bullish FVGs ---
            # Remove them if they were structurally broken (Close < Bottom)
            active_bulls_keep = []
            for f in self.active_bullish_fvgs:
                if curr['close'] >= f.bottom:
                    active_bulls_keep.append(f)
            self.active_bullish_fvgs = active_bulls_keep

    def calculate_metrics(self, save_csv=False, filename="v3_trades.csv"):
        if not self.trades:
             print("No trades generated.")
             return
             
        t_df = pd.DataFrame([t.__dict__ for t in self.trades])
        
        if save_csv:
             export_df = t_df[['ticker', 'type', 'status', 'reason', 'entry_date', 'entry_price', 'exit_date', 'exit_price', 'stop_loss', 'take_profit', 'pnl']]
             export_df.to_csv(filename, index=False)
             print(f"Exported {len(export_df)} trades to {filename}")
             
        total_pnl = t_df['pnl'].sum()
        winners = t_df[t_df['pnl'] > 0]
        losers = t_df[t_df['pnl'] <= 0]
        
        win_rate = len(winners) / len(t_df)
        avg_win = winners['pnl'].mean() if len(winners) > 0 else 0
        avg_loss = losers['pnl'].mean() if len(losers) > 0 else 0
        
        print(f"\n=== V3 EQUILIBRIUM STRATEGY (1 SHARE QQQ) ===")
        print(f"Target: {self.target_pct:.1%} | SMA50 Filter: {self.sma50_filter} | SMA10 Exit: {self.sma10_exit}")
        print(f"Total Trades: {len(t_df)}")
        print(f"Win Rate:     {win_rate*100:.1f}%")
        print(f"Total PnL:    ${total_pnl:.2f}")
        print(f"Avg Winner:   ${avg_win:.2f}")
        print(f"Avg Loser:    ${avg_loss:.2f}")
        
        if avg_loss != 0:
            reward_risk = abs(avg_win / avg_loss)
            print(f"Avg R:R:      {reward_risk:.2f}R")
            
        print("\nExit Reasons Breakdown:")
        print(t_df['reason'].value_counts())


if __name__ == "__main__":
    print("\n--- Testing Entries BELOW SMA50 with SMA10 [CLOSE] Trailing Stop ---")
    bot_close = EquilibriumStrategyV3(ticker="QQQ", start_date="2000-01-01", target_pct=0.05, sma50_filter="BELOW", sma10_exit="CLOSE", vix_filter=False)
    bot_close.download_data()
    bot_close.run_simulation()
    bot_close.calculate_metrics(save_csv=False)
    
    print("\n--- Testing Entries BELOW SMA50 + SMA10 [CLOSE] + VIX Filter ---")
    bot_vix = EquilibriumStrategyV3(ticker="QQQ", start_date="2000-01-01", target_pct=0.05, sma50_filter="BELOW", sma10_exit="CLOSE", vix_filter=True)
    bot_vix.download_data()
    bot_vix.run_simulation()
    bot_vix.calculate_metrics(save_csv=True, filename="ifvg_v3_5pct_BELOW_sma50_trail10_VIX.csv")

    print("\n--- Testing Entries BELOW SMA50 + SMA10 [CLOSE] + VIX Filter (SPY) ---")
    bot_spy = EquilibriumStrategyV3(ticker="SPY", start_date="2000-01-01", target_pct=0.05, sma50_filter="BELOW", sma10_exit="CLOSE", vix_filter=True)
    bot_spy.download_data()
    bot_spy.run_simulation()
    bot_spy.calculate_metrics(save_csv=False)
