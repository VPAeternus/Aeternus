import os
import pandas as pd
import yfinance as yf
import datetime
import threading

CACHE_DIR = "market_data_cache"
_download_lock = threading.Lock()

def get_cached_ticker_data(ticker, start_date):
    """
    Retrieves ticker data from local CSV cache.
    If missing or outdated, fetches the delta from Yahoo Finance and appends it.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    safe_ticker = ticker.replace("^", "") # For ^VIX
    cache_file = os.path.join(CACHE_DIR, f"{safe_ticker}.csv")
    
    today = datetime.datetime.now().date()
    
    if os.path.exists(cache_file):
        try:
            df = pd.read_csv(cache_file)
            df.columns = [c.lower() for c in df.columns]
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            
            last_date = df.index[-1].date()
            
            if last_date < today:
                fetch_start = last_date + datetime.timedelta(days=1)
                with _download_lock:
                    new_df = yf.download(ticker, start=fetch_start.strftime("%Y-%m-%d"), progress=False, auto_adjust=False)
                
                if not new_df.empty:
                    if isinstance(new_df.columns, pd.MultiIndex): 
                        new_df.columns = new_df.columns.get_level_values(0)
                    new_df.reset_index(inplace=True)
                    new_df.columns = [c.lower() for c in new_df.columns]
                    if 'datetime' in new_df.columns: new_df.rename(columns={'datetime': 'date'}, inplace=True)
                    if 'date' in new_df.columns:
                        new_df['date'] = pd.to_datetime(new_df['date'])
                        new_df.set_index('date', inplace=True)
                    
                    df = pd.concat([df, new_df])
                    df = df[~df.index.duplicated(keep='last')]
                    df.to_csv(cache_file)
            
            # Filter by requested start date
            start_dt = pd.to_datetime(start_date) - pd.DateOffset(days=365)
            return df[df.index >= start_dt].copy()
            
        except Exception as e:
             print(f"[-] Cache read failed for {ticker}: {e}. Redownloading.")
             pass

    # Full Download
    start_dt = pd.to_datetime(start_date) - pd.DateOffset(days=365)
    with _download_lock:
        df = yf.download(ticker, start=start_dt.strftime("%Y-%m-%d"), progress=False, auto_adjust=False)
    
    if not df.empty:
        if isinstance(df.columns, pd.MultiIndex): 
            df.columns = df.columns.get_level_values(0)
        df.reset_index(inplace=True)
        df.columns = [c.lower() for c in df.columns]
        if 'datetime' in df.columns: df.rename(columns={'datetime': 'date'}, inplace=True)
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            
        df.to_csv(cache_file)
        
    return df
