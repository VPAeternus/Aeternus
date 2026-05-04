# Adaptive Hedge Framework

**Last Updated:** January 30, 2026  
**Status:** Active

---

## Overview

A systematic, mean-reversion based hedge framework that adjusts protection based on:
1. **SPY Deviation from SMA20** - Mean reversion opportunity
2. **VIX Sentiment** - Fear/greed indicator
3. **Bear Market Triggers** - Negative beta activation

---

## 1. SPY Deviation Hedge (Mean Reversion)

| SPY Position | Hedge % | Beta | Rationale |
|--------------|---------|------|-----------|
| >5% above SMA20 | **50%** | +0.50 | Very extended - high mean reversion risk |
| 3-5% above SMA20 | **25%** | +0.75 | Extended |
| 2-3% above SMA20 | **12.5%** | +0.875 | Mildly extended |
| 0-2% above SMA20 | **0%** | +1.00 | Normal range |
| <0% (below SMA20) | **25%** | +0.75 | Below moving average |

### Calculation
```
SPY Deviation = (SPY Price - SMA20) / SMA20 * 100
```

---

## 2. VIX Sentiment Adjustment

| VIX Level | Sentiment | Adjustment |
|-----------|-----------|------------|
| <12 | Extreme Complacency (Greed) | **+10%** |
| 12-15 | Complacency | **+5%** |
| 15-20 | Normal | **+0%** |
| 20-25 | Fear | **+10%** |
| >25 | High Fear | **+20%** |

### Formula
```
Final Hedge = SPY Deviation Hedge + VIX Adjustment
```

---

## 3. Bear Market Triggers

### Bear Signal (75% Hedge)
```
IF SPY < SMA200:
    Hedge = 75%
    Beta = 0.25
```

### Negative Beta (Crash Signal)
```
IF SPY < SMA200 AND SMA200 is trending down:
    Hedge = NEGATIVE BETA (-25% to -50%)
    Action = Short exposure to profit from decline
```

---

## 4. Complete Hedge Spectrum

| Hedge % | Beta | Scenario |
|---------|------|----------|
| 0% | +1.0 | Strong bull - normal range |
| 12.5% | +0.875 | Mildly extended (2-3% above SMA20) |
| 25% | +0.75 | Extended (3-5% above SMA20) or below SMA20 |
| 50% | +0.50 | Very extended (>5% above SMA20) |
| 75% | +0.25 | Early bear (SPY < SMA200) |
| 100% | 0 | Confirmed bear |
| >100% | **NEGATIVE** | Crash - short exposure |

---

## 5. Example Scenarios

### Scenario A: Extended Bull + Complacent VIX
```
SPY: +4% above SMA20  → 25% hedge
VIX: 14               → +5% adjustment
Total Hedge:          → 30%
```

### Scenario B: Very Extended + Fear
```
SPY: +6% above SMA20  → 50% hedge
VIX: 22               → +10% adjustment
Total Hedge:          → 60%
```

### Scenario C: Normal + Normal VIX
```
SPY: +1% above SMA20  → 0% hedge
VIX: 17               → 0% adjustment
Total Hedge:          → 0%
```

### Scenario D: Bear Market
```
SPY: < SMA200         → 75% hedge
SMA200 trending down  → NEGATIVE BETA (-25%)
```

---

## 6. Today's Calculation (Jan 30, 2026)

| Factor | Value | Hedge |
|--------|-------|-------|
| SPY | $693.20 | |
| SMA20 | $690.56 | |
| Deviation | +0.4% | 0% (normal) |
| VIX | 17.0 | 0% (normal) |
| **Final** | | **0%** |

---

## 7. File Locations

| File | Purpose |
|------|---------|
| `Performance/generate_daily_report.py` | Python script with hedge logic |
| `Performance/DAILY_REPORT_YYYY-MM-DD.md` | Daily generated report |
| `ADAPTIVE_HEDGE_FRAMEWORK.md` | This document |

---

## 8. Integration

To generate daily report:
```bash
python Performance/generate_daily_report.py
```

The report includes:
- Current market conditions (SPY, SMAs, VIX)
- SPY deviation analysis
- VIX sentiment adjustment
- Bear market triggers
- Final hedge recommendation
- Hedge calculation breakdown
- Hedge spectrum table
