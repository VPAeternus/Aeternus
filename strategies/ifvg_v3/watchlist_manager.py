import sqlite3
import argparse
from datetime import datetime
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "watchlist.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tickers (
            symbol TEXT PRIMARY KEY,
            added_date TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_tickers(symbols):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    for symbol in symbols:
        symbol = symbol.upper().strip()
        try:
            cursor.execute("INSERT INTO tickers (symbol, added_date) VALUES (?, ?)", 
                           (symbol, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            print(f"[+] Successfully added {symbol} to the watchlist.")
        except sqlite3.IntegrityError:
            print(f"[*] {symbol} is already in the watchlist.")
    conn.commit()
    conn.close()

def remove_tickers(symbols):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    for symbol in symbols:
        symbol = symbol.upper().strip()
        cursor.execute("DELETE FROM tickers WHERE symbol = ?", (symbol,))
        if cursor.rowcount > 0:
            print(f"[-] Successfully removed {symbol} from the watchlist.")
        else:
            print(f"[!] {symbol} was not found in the watchlist.")
    conn.commit()
    conn.close()

def get_tickers():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT symbol FROM tickers ORDER BY symbol ASC")
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]

def get_enriched_tickers():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Check if new columns exist
    try:
        cursor.execute("SELECT symbol, etfs, sector, market_cap FROM tickers")
        rows = cursor.fetchall()
        conn.close()
        return {r[0]: {"etfs": r[1] or "", "sector": r[2] or "Unknown", "market_cap": r[3] or 0} for r in rows}
    except sqlite3.OperationalError:
        # Columns don't exist yet
        conn.close()
        return {}

def list_tickers():
    tickers = get_tickers()
    if not tickers:
        print("Watchlist is currently empty.")
    else:
        print(f"=== WATCHLIST ({len(tickers)} Tickers) ===")
        for t in tickers:
            print(f" - {t}")

if __name__ == "__main__":
    init_db()
    
    parser = argparse.ArgumentParser(description="VolGapAutoAG Watchlist Manager")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Add command
    parser_add = subparsers.add_parser("add", help="Add one or more tickers to the watchlist")
    parser_add.add_argument("symbols", nargs='+', type=str, help="Ticker symbol(s) (e.g. AAPL MSFT TSLA)")
    
    # Remove command
    parser_remove = subparsers.add_parser("remove", help="Remove one or more tickers from the watchlist")
    parser_remove.add_argument("symbols", nargs='+', type=str, help="Ticker symbol(s) (e.g. AAPL MSFT TSLA)")
    
    # List command
    parser_list = subparsers.add_parser("list", help="List all tickers in the watchlist")
    
    args = parser.parse_args()
    
    if args.command == "add":
        add_tickers(args.symbols)
    elif args.command == "remove":
        remove_tickers(args.symbols)
    elif args.command == "list":
        list_tickers()
    else:
        parser.print_help()
