"""
Export SMA10/lb5 acceleration signals for QQQ to CSV.

Signal column values:
  accel_dn — acceleration flips negative (buy signal in backtest)
  accel_up — acceleration flips positive (sell signal in backtest)
  ""       — no signal
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from tradingagents.phase_engine import data_engine

TICKER = "QQQ"
OUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "eval_results",
    "accel_signals_QQQ.csv",
)

df = data_engine.load(TICKER)

# Acceleration computation (SMA10, 5-bar slope lookback)
sma = df["sma10"]
slope = (sma - sma.shift(5)) / (df["close"] * 5)
accel = slope - slope.shift(5)
prev_accel = accel.shift(1)

signal = pd.Series("", index=df.index)
signal[(accel < 0) & (prev_accel >= 0)] = "accel_dn"
signal[(accel > 0) & (prev_accel <= 0)] = "accel_up"

# Build output DataFrame
price_cols = ["open", "high", "low", "close"]
sma_cols   = ["sma3", "sma10", "sma20", "sma50", "sma200"]

out = pd.DataFrame({
    "Date":   df["date"].dt.strftime("%Y-%m-%d"),
    "Open":   df["open"].round(2),
    "High":   df["high"].round(2),
    "Low":    df["low"].round(2),
    "Close":  df["close"].round(2),
    "Volume": df["volume"].astype(int),
    "Signal": signal,
    "SMA3":   df["sma3"].round(2),
    "SMA10":  df["sma10"].round(2),
    "SMA20":  df["sma20"].round(2),
    "SMA50":  df["sma50"].round(2),
    "SMA200": df["sma200"].round(2),
})

os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
out.to_csv(OUT_PATH, index=False)

n_dn = (signal == "accel_dn").sum()
n_up = (signal == "accel_up").sum()
print(f"accel_dn signals : {n_dn}")
print(f"accel_up signals : {n_up}")
print(f"Output           : {OUT_PATH}")
