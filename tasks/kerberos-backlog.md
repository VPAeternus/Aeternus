# Kerberos007 Strategy Backlog

Source: @kerberos007 (X/Twitter, 2018-2023, retired quant)
Reviewed: 2026-03-03
Status: Research backlog — not yet task-spec'd

---

## The Core Idea

**%B(20,2) mean-reversion system** with an asymmetric Bollinger Band threshold:

| Action | Signal | Meaning |
|--------|--------|---------|
| Buy  | `%B(20,2)` crosses above 0 | Price bounced off lower 2-SD BB — extreme statistical oversold |
| Sell | `%B(20,1)` crosses above 1 | Price reached upper 1-SD BB — take profits early |

**Key filter (the real alpha):** VIX term structure in **backwardation** (spot VIX > near-term futures).
With backwardation added, Kerberos claims 90%+ win rate. Mechanism: backwardation = fear-driven selling, not structural breakdown → mean reversion likely.

Backtest (2011-2019, SPX, long-only): 94% win rate, PF 22.87, 312 trades.
Caveats: pure bull market period, no short trades, broke in Dec 2017/Jan 2018 (XIV blowup).
2022 bear market would have been painful unmodified.

---

## To-Do

- [ ] **Audit existing coverage** — Check `tradingagents/agents/utils/macro_engine.py` and
      `tradingagents/phase_engine/` for VIX term structure tracking. Does the macro_engine
      already compute VIX backwardation? If yes, we have the filter for free.

- [ ] **%B(20,2) as technical pillar signal** — Add to the technical scoring pillar
      (`tradingagents/agents/analysts/`). Not a trade trigger — a regime-entry flag.
      "Market is in statistically extreme oversold territory" → boost CORE entry scores.
      Applies at both index level (SPX %B = macro signal) and stock level (individual %B = entry timing).

- [ ] **Backwardation gate** — Wire VIX term structure as confirmation layer.
      Only fire %B oversold signals when VIX term structure is in backwardation or flat.
      In contango (normal, calm market), skip the signal — dips are not fear-driven.
      Data source: VIX vs VIX3M or VX futures front-month vs second-month.

- [ ] **Asymmetric exit concept** — 1-SD exit on 2-SD entry.
      Apply to CC roll decisions and position trimming: don't wait for full mean reversion,
      take profits at +1 SD (upper 1-SD band) rather than holding for +2 SD.
      Check if this improves the CC roll monitor exit logic.

- [ ] **Regime dependency test** — Before wiring into scoring, backtest %B signals
      against the existing regime classifier. Hypothesis: %B works in bull/neutral regimes
      (SMA200 uptrend) and fails in bear regimes. Confirm this is the gating condition.

- [ ] **Task spec** — Once audit complete, write S-0XX for Sonnet to implement
      %B as a new signal in the technical analyst (`agents/analysts/technical_analyst.py`).

---

## Multi-Timeframe (MTF) Trend Alignment Framework

Kerberos's broader system beyond %B. The %B strategy is the *entry mechanism* within this framework.

### The 8-State Trend Cycle
```
1. Up Trend → 2. Up OB → 3. Up OB Reversal → 4. Up Reversal
                                                        ↓
8. Dn Reversal ← 7. Dn OS Reversal ← 6. Dn OS ← 5. Dn Trend
```
Fast model simplifies to 4 states: Up, Up-Rev, Dn, Dn-Rev.
**Key concept**: trade the SLOPE, not the phase. A reversal = new direction immediately.

### MTF Hierarchy
```
Monthly = Tide        (structural direction, rarely changes)
Weekly  = Large Waves (trend confirmation)
Daily   = Small Waves (entry timing)
4 Hour  = Ripples     (execution precision)
```

### Entry Rule
Only enter when ALL timeframes align in one direction.
Example SHORT: Month=DN, Week=DN, Daily=XU, 4Hr=XU → short with tight stop, wide target.
Claims: 80% win rate, R/R > 4:1 when fully aligned.

### To-Do (MTF-specific)

- [ ] **Compare 8-state cycle vs Wyckoff phases** — The 8 states map closely to Wyckoff
      (Accumulation ≈ Dn OS Reversal, Markup ≈ Up Trend, Distribution ≈ Up OB Reversal,
      Markdown ≈ Dn Trend). Check `tradingagents/phase_engine/` for overlap. If Wyckoff
      phases already cover these states, the cycle model adds nothing. If not, the slope-based
      simplification (4-state fast model) may be faster-acting than Wyckoff.

- [ ] **MTF regime confirmation** — Add weekly + monthly trend direction as a confirmation
      layer on top of the daily regime classifier (`market_regime.py`). When daily says "bull"
      but weekly/monthly are "bear", reduce conviction. When all three agree, boost conviction.
      Data: weekly/monthly SMA slopes or %B states computed on weekly/monthly candles.

- [ ] **Slope-as-signal for phase_engine** — Emit "slope direction" (up/down) as a faster
      signal alongside the existing Wyckoff phase classification. Phase says "where we are";
      slope says "which direction we're moving right now." Slope changes before phase transitions.

---

## Credibility Notes

- Macro calls (2023): consistently bearish, largely wrong on the AI rally. Discount opinion.
- Strategy mechanics: sound. The %B asymmetry and backwardation filter are independent of market
  view bias — they're systematic.
- Backtest inflation: 2011-2019 bull market overstates win rate. Add a bear-market regime gate
  before treating the 94% number as reliable.
- Account went dark mid-2023 — possibly after a rough 2022 short book.
