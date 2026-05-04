# Macro Bucket Definitions

These are the working Wall Street-style names for the finalized macro buckets in:

```text
eval_results/macro_backtest/adaptive_proxy_1999/daily_spy_adaptive_regime_buckets_1999_2026.csv
```

The bucket rules still use the four raw state columns:

```text
regime
technical_panic_state
adaptive_combined_panic_state
stress_layer3_state
```

The human-readable name lives in:

```text
macro_bucket_name
```

Return columns are SPY point moves, not percentage returns:

```text
AH  = next_day_open - current_day_close
RTH = next_day_close - next_day_open
```

---

## Bucket 1 — Bear Dollar-Rates Squeeze

Raw bucket:

```text
BEAR_OTHER_STRESS_MIXED_RATES_DOLLAR_SQUEEZE
```

Rule:

```text
regime = BEAR
technical_panic_state = OTHER_STRESS
adaptive_combined_panic_state = MIXED_STRESS
stress_layer3_state = RATES_DOLLAR_SQUEEZE
```

Stats:

```text
daily rows: 88
AH sum:  -14.84
RTH sum:  -5.22
net SPY point move: -20.06
average net move per active day: -0.23
profile: negative AH, negative RTH
```

Narrative:

This is a hostile bear-market tape where the pressure is coming from the dollar/rates complex rather than a clean equity-only panic. The market is already in a bear regime, the technical read is stressed but not cleanly capitulative, and the cross-asset message says liquidity is tightening. Both after-hours and regular-session behavior are negative, which means there is no obvious session where buyers consistently rescue the tape. This bucket should be treated like a real de-risking environment: avoid aggressive longs, avoid high-beta exposure, and assume rallies are suspect until the dollar/rates pressure fades.

---

## Bucket 2 — Bull Overnight Carry / RTH Fade

Raw bucket:

```text
BULL_NON_STRESS_NON_STRESS_NON_STRESS
```

Rule:

```text
regime = BULL
technical_panic_state = NON_STRESS
adaptive_combined_panic_state = NON_STRESS
stress_layer3_state = NON_STRESS
```

Stats:

```text
daily rows: 2144
AH sum:   126.36
RTH sum:  -64.66
net SPY point move: 61.70
average net move per active day: 0.03
profile: positive AH, negative RTH
```

Narrative:

This is the normal bull-market carry regime. The macro backdrop is not under stress, the tape is not panicking, and risk appetite is generally healthy. The interesting feature is that gains show up mostly overnight, while regular trading hours tend to fade. In Wall Street terms, this looks like a benign carry tape: investors are willing to hold risk overnight, but cash-session strength is often sold or digested. The regime is constructive, but the execution lesson is not to blindly chase intraday strength.

---

## Bucket 3 — Euphoria Overnight Melt-Up

Raw bucket:

```text
EUPHORIA_NON_STRESS_NON_STRESS_NON_STRESS
```

Rule:

```text
regime = EUPHORIA
technical_panic_state = NON_STRESS
adaptive_combined_panic_state = NON_STRESS
stress_layer3_state = NON_STRESS
```

Stats:

```text
daily rows: 1640
AH sum:   109.69
RTH sum:  -16.13
net SPY point move: 93.56
average net move per active day: 0.06
profile: positive AH, negative RTH
```

Narrative:

This is the high-confidence risk-on tape where sentiment and positioning are strong enough to push prices higher outside normal trading hours. It is not a stress regime; it is a momentum/carry regime. The overnight bid is strong, but regular trading hours are not where most of the edge appears. That pattern is typical of a crowded but still-functioning risk-on market: good news, liquidity, and passive flows lift prices between sessions, while the cash market often consolidates. The main risk is chasing late-cycle enthusiasm after the overnight move has already happened.

---

## Bucket 4 — Falling-Knife Cash-Session Liquidation

Raw bucket:

```text
STRESS_FALLING_KNIFE_RISK_FALLING_KNIFE_FALLING_KNIFE
```

Rule:

```text
regime in [BEAR, VOL_SHOCK, RISK_OFF]
technical_panic_state = FALLING_KNIFE_RISK
adaptive_combined_panic_state = FALLING_KNIFE
stress_layer3_state = FALLING_KNIFE
```

Stats:

```text
daily rows: 176
AH sum:    13.05
RTH sum:  -62.61
net SPY point move: -49.56
average net move per active day: -0.28
profile: positive AH, negative RTH
```

Narrative:

This is the classic falling-knife liquidation tape. The market is in a stress regime, price action is still deteriorating, and the macro/cross-asset layer does not provide enough support to call it buyable. The key behavior is that overnight relief does not hold; the damage happens during the regular session. That is a dangerous execution profile because apparent stabilization before the open can turn into cash-session selling. This bucket should suppress aggressive dip-buying and favor patience, hedging, or waiting for a cleaner stabilization signal.

---

## Bucket 5 — Macro-Cushioned Falling Knife

Raw bucket:

```text
STRESS_FALLING_KNIFE_RISK_FALLING_BUT_MACRO_OK_FALLING_BUT_MACRO_OK
```

Rule:

```text
regime in [BEAR, VOL_SHOCK, RISK_OFF]
technical_panic_state = FALLING_KNIFE_RISK
adaptive_combined_panic_state = FALLING_BUT_MACRO_OK
stress_layer3_state = FALLING_BUT_MACRO_OK
```

Stats:

```text
daily rows: 714
AH sum:  -17.82
RTH sum:   6.00
net SPY point move: -11.82
average net move per active day: -0.02
profile: negative AH, positive RTH
```

Narrative:

This is a stressed tape where price is still falling, but the macro backdrop is not confirming a full liquidity breakdown. The market often marks down overnight, but the regular session shows some ability to absorb selling. That is why this is not the same as a true falling knife. The right read is “watchlist, not green light.” There may be tradable intraday repair, but the technical trend is still weak. In practice, this bucket favors patience, smaller size, and waiting for price confirmation rather than buying the overnight weakness automatically.

---

## Bucket 6 — Vol-Shock Capitulation Reversal

Raw bucket:

```text
VOL_SHOCK_CAPITULATION_REBOUND_CANDIDATE_BUYABLE_PANIC_BUYABLE_PANIC
```

Rule:

```text
regime = VOL_SHOCK
technical_panic_state = CAPITULATION_REBOUND_CANDIDATE
adaptive_combined_panic_state = BUYABLE_PANIC
stress_layer3_state = BUYABLE_PANIC
```

Stats:

```text
daily rows: 84
AH sum:  -59.93
RTH sum:  81.45
net SPY point move: 21.52
average net move per active day: 0.26
profile: negative AH, positive RTH
```

Narrative:

This is the cleanest “panic but potentially buyable” bucket. Volatility is shocked, the tape looks capitulative, and the macro filter says the panic is not a full falling-knife breakdown. The return split is important: overnight action is ugly, but regular-session trading has historically repaired hard. In market language, this is a gap-down/panic-open reversal setup. It does not mean buy anything blindly; it means rebound research is allowed, especially in liquid, high-quality names, with confirmation from the cash session.

---

## Bucket 7 — Fragile Post-Panic Relief Fade

Raw bucket:

```text
STRESS_POST_PANIC_STABILIZATION_CAPITULATION_BUT_MACRO_WEAK_CAPITULATION_BUT_MACRO_WEAK
```

Rule:

```text
regime in [VOL_SHOCK, RISK_OFF, HIGH_VOL]
technical_panic_state = POST_PANIC_STABILIZATION
adaptive_combined_panic_state = CAPITULATION_BUT_MACRO_WEAK
stress_layer3_state = CAPITULATION_BUT_MACRO_WEAK
```

Stats:

```text
daily rows: 38
AH sum:   10.82
RTH sum: -20.06
net SPY point move: -9.25
average net move per active day: -0.24
profile: positive AH, negative RTH
```

Narrative:

This is a fragile post-panic tape. Price has started to stabilize after stress, but the macro backdrop is still weak. The market can catch an overnight relief bid, but that relief tends to fade during regular trading hours. This is not a clean buyable panic; it is a tactical bounce environment where the easy move may occur before the cash session. The operational message is to avoid chasing opens, take signals with smaller size, and demand confirmation that stabilization can survive the regular session.

---

## Current Bucket Grouping by AH/RTH Behavior

Negative AH and negative RTH:

```text
Bear Dollar-Rates Squeeze
```

Positive AH and negative RTH:

```text
Bull Overnight Carry / RTH Fade
Euphoria Overnight Melt-Up
Falling-Knife Cash-Session Liquidation
Fragile Post-Panic Relief Fade
```

Negative AH and positive RTH:

```text
Macro-Cushioned Falling Knife
Vol-Shock Capitulation Reversal
```
