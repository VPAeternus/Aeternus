"""
Aeternus Core — Phase Engine
Wyckoff market cycle classification with adaptive per-ticker thresholds.

The key insight: fixed FVG ratio thresholds (0.70/0.39) only work on QQQ because
QQQ has a specific FVG frequency distribution. SPY, TSLA, NVDA all have different
distributions. Using expanding percentiles adapts to each instrument's personality.

Phases:
  MARK_UP   — bullish FVGs dominating, trend confirmed → longs valid
  MARK_DOWN — bearish FVGs dominating, trend confirmed → shorts valid
  DIST_ACCUM — mixed or transitional → selective entries only

Dual gate (FVG ratio + SMA alignment):
  MARK_UP requires:   ratio >= 75th pctile AND sma10 > sma20 AND close > sma50
  MARK_DOWN requires:  ratio <= 25th pctile AND sma10 < sma20 AND close < sma50

Empty window rule (Wyckoff-derived):
  If zero FVGs in the 20-bar window → hold previous phase (no false MARK_DOWN).
"""

import numpy as np
import pandas as pd
from . import config as cfg


def classify_phases(df: pd.DataFrame) -> pd.Series:
    """
    Classify each bar into a Wyckoff phase using adaptive percentile thresholds.

    Args:
        df: DataFrame from data_engine.load() with fvg_ratio, sma10, sma20, sma50, close, fvg_bull, fvg_bear

    Returns:
        pd.Series of phase labels: "MARK_UP", "MARK_DOWN", "DIST_ACCUM"
    """
    n = len(df)
    phases = np.full(n, "DIST_ACCUM", dtype=object)

    ratio   = df['fvg_ratio'].values
    bull    = df['fvg_bull'].values
    bear    = df['fvg_bear'].values
    close   = df['close'].values
    sma10   = df['sma10'].values
    sma20   = df['sma20'].values
    sma50   = df['sma50'].values

    # Compute expanding percentile thresholds (adaptive per-ticker)
    # Use expanding window with minimum 252 bars (1 year) for stability
    ratio_series = df['fvg_ratio'].copy()
    min_p = cfg.PHASE_MIN_HISTORY

    ratio_75 = ratio_series.expanding(min_periods=min_p).quantile(0.01 * cfg.MARKUP_PERCENTILE).values
    ratio_25 = ratio_series.expanding(min_periods=min_p).quantile(0.01 * cfg.MARKDN_PERCENTILE).values

    prev_phase = "DIST_ACCUM"

    for i in range(n):
        r  = ratio[i]
        bc = bull[i] if not np.isnan(bull[i]) else 0
        brc = bear[i] if not np.isnan(bear[i]) else 0
        s10 = sma10[i]
        s20 = sma20[i]
        s50 = sma50[i]
        c   = close[i]

        # Skip if SMAs not ready
        sma_ok = not (np.isnan(s10) or np.isnan(s20) or np.isnan(s50))

        # Empty window rule: if no FVGs in window, hold previous phase
        if np.isnan(r) or (bc == 0 and brc == 0):
            phases[i] = prev_phase
            prev_phase = phases[i]
            continue

        # Thresholds not ready yet (need PHASE_MIN_HISTORY bars)
        r75 = ratio_75[i]
        r25 = ratio_25[i]
        if np.isnan(r75) or np.isnan(r25):
            phases[i] = prev_phase
            prev_phase = phases[i]
            continue

        # Dual gate: ratio threshold + SMA alignment
        if r >= r75 and sma_ok and s10 > s20 and c > s50:
            phases[i] = "MARK_UP"
        elif r <= r25 and sma_ok and s10 < s20 and c < s50:
            phases[i] = "MARK_DOWN"
        else:
            phases[i] = "DIST_ACCUM"

        prev_phase = phases[i]

    return pd.Series(phases, index=df.index, name='phase')


def is_macro_bearish(df: pd.DataFrame, i: int) -> bool:
    """
    F1 filter: SMA200 must be declining over MACRO_SMA200_LOOKBACK bars.

    This blocks shallow corrections where the 200-day MA is structurally rising
    (e.g., 2019-01-03 where Q4'18 dip didn't break the long-term trend).

    Args:
        df: DataFrame with 'sma200' column
        i: current bar index
    Returns:
        True if SMA200 has declined over the lookback period
    """
    lb = cfg.MACRO_SMA200_LOOKBACK
    if i < lb:
        return False

    sma200_now = df.iloc[i]['sma200']
    sma200_prev = df.iloc[i - lb]['sma200']

    if np.isnan(sma200_now) or np.isnan(sma200_prev):
        return False

    return sma200_now < sma200_prev



def is_market_stress(df: pd.DataFrame, i: int) -> bool:
    """
    F4 filter: VIX SMA20 must be >= MACRO_VIX_THRESHOLD (sustained fear regime).

    Uses SMA20 of VIX to smooth spike noise. This ensures genuine sustained fear,
    not a single-day VIX pop.

    Args:
        df: DataFrame with 'vix_sma20' column
        i: current bar index
    Returns:
        True if VIX SMA20 >= threshold
    """
    vix_sma = df.iloc[i].get('vix_sma20', np.nan)
    if isinstance(vix_sma, float) and np.isnan(vix_sma):
        return False
    return float(vix_sma) >= cfg.MACRO_VIX_THRESHOLD


def is_severe_stress(df: pd.DataFrame, i: int) -> bool:
    """
    Severe stress: VIX SMA20 > MACRO_VIX_STRESS AND SMA200 declining.
    Used for Tier 3 catastrophic shorts — very selective.

    Args:
        df: DataFrame with 'vix_sma20' and 'sma200' columns
        i: current bar index
    Returns:
        True if both severe VIX stress and SMA200 declining
    """
    vix_sma = df.iloc[i].get('vix_sma20', np.nan)
    if isinstance(vix_sma, float) and np.isnan(vix_sma):
        return False
    vix_severe = float(vix_sma) >= cfg.MACRO_VIX_STRESS
    return vix_severe and is_macro_bearish(df, i)


def is_market_health_bearish(market_df: pd.DataFrame, i: int) -> bool:
    """
    Market-wide regime: check if market health ticker (QQQ) SMA10 < SMA20.
    Used for Tier 3 catastrophic shorts.

    Args:
        market_df: DataFrame for the market health ticker (QQQ)
        i: bar index (must be aligned with the market_df index)
    Returns:
        True if SMA10 < SMA20 on the market ticker
    """
    if i >= len(market_df):
        return False
    row = market_df.iloc[i]
    s10 = row.get('sma10', np.nan)
    s20 = row.get('sma20', np.nan)
    if np.isnan(s10) or np.isnan(s20):
        return False
    return s10 < s20


def is_rth_avoid(df: pd.DataFrame, phases: pd.Series, i: int) -> bool:
    """
    RTH Avoidance Signal: next day's intraday session is expected to bleed.

    Conditions (all must be true):
      1. Phase = DIST_ACCUM (market in distribution/accumulation — no clear trend)
      2. Volume < 3-day average volume (low conviction day)
      3. VIX between 15-25 (nervous but functional — the sweet spot for shorts)

    When this fires on day i, the action is on day i+1:
      - Short at Open[i+1], cover at Close[i+1]
      - OR simply sit out the RTH session (sell at open, buy back at close)

    QQQ backtest (1999-2026): 1013 trades in VIX 15-25 bucket, +$220 short PnL.

    Args:
        df: DataFrame with volume, vix columns
        phases: Series from classify_phases()
        i: current bar index (signal day)
    Returns:
        True if next day's RTH should be avoided/shorted
    """
    if phases.iloc[i] != "DIST_ACCUM":
        return False

    # Volume < 3-day average
    if i < cfg.VOLUME_AVG_SHORT:
        return False
    vol = df.iloc[i]['volume']
    vol_avg = 0.0
    for j in range(cfg.VOLUME_AVG_SHORT):
        vol_avg += df.iloc[i - j]['volume']
    vol_avg /= cfg.VOLUME_AVG_SHORT
    if vol >= vol_avg:
        return False

    # VIX sweet spot
    vix = df.iloc[i].get('vix', np.nan)
    if np.isnan(vix):
        return False
    if vix < cfg.VIX_FLOOR or vix >= cfg.VIX_CEILING:
        return False

    return True


def is_markup_fade(df: pd.DataFrame, phases: pd.Series, i: int) -> bool:
    """
    Markup Fade Signal: shallow pullback in uptrend → next-day RTH bleeds.

    Conditions (all must be true):
      1. Phase = MARK_UP (strong trend confirmed by FVG ratio + SMA alignment)
      2. Volume < 3-day average volume (low conviction day)
      3. Close < SMA3 (short-term pullback — price dipping below 3-day MA)
      4. Close > SMA10 (not too deep — still holding intermediate support)

    The setup: in a confirmed uptrend, a weak low-volume day where price slips
    just below the 3-day MA but stays above the 10-day MA. The next day's RTH
    session tends to bleed (continuation of the intraday weakness).

    When this fires on day i, the action is on day i+1:
      - Short at Open[i+1], cover at Close[i+1]

    QQQ backtest (1999-2026): 172 trades, -$30.92 RTH sum (profitable if shorted).

    Args:
        df: DataFrame with volume, sma3, sma10, close columns
        phases: Series from classify_phases()
        i: current bar index (signal day)
    Returns:
        True if next day's RTH should be shorted
    """
    if phases.iloc[i] != "MARK_UP":
        return False

    # Volume < 3-day average
    if i < cfg.VOLUME_AVG_SHORT:
        return False
    vol = df.iloc[i]['volume']
    vol_avg = 0.0
    for j in range(cfg.VOLUME_AVG_SHORT):
        vol_avg += df.iloc[i - j]['volume']
    vol_avg /= cfg.VOLUME_AVG_SHORT
    if vol >= vol_avg:
        return False

    # SMA gate: close below SMA3 but above SMA10 (shallow pullback)
    c = df.iloc[i]['close']
    sma3 = df.iloc[i].get('sma3', np.nan)
    sma10 = df.iloc[i].get('sma10', np.nan)
    if np.isnan(sma3) or np.isnan(sma10):
        return False
    if c >= sma3 or c <= sma10:
        return False

    return True


def is_markdown_crush(df: pd.DataFrame, phases: pd.Series, i: int) -> bool:
    """
    Markdown Crush Signal: high-volume bounce attempt in downtrend → next-day RTH bleeds.

    Conditions (all must be true):
      1. Phase = MARK_DOWN (bearish trend confirmed by FVG ratio + SMA alignment)
      2. Volume > 3-day average volume (high activity — forced selling or failed bounce)
      3. Close < SMA10 (below intermediate MA — trend intact)
      4. Close > SMA3 (short-term bounce above 3-day MA — relief rally attempt)

    The setup: in a confirmed downtrend, a high-volume day where price bounces
    above the 3-day MA but stays below the 10-day MA. The next day's RTH
    session crushes (failed bounce continuation).

    When this fires on day i, the action is on day i+1:
      - Short at Open[i+1], cover at Close[i+1]

    QQQ backtest (1999-2026): 77 trades, -$27.77 RTH sum (profitable if shorted).
    Avg = -$0.36/trade. ~3 trades/year.

    Args:
        df: DataFrame with volume, sma3, sma10, close columns
        phases: Series from classify_phases()
        i: current bar index (signal day)
    Returns:
        True if next day's RTH should be shorted
    """
    if phases.iloc[i] != "MARK_DOWN":
        return False

    # Volume > 3-day average (high volume, not low)
    if i < cfg.VOLUME_AVG_SHORT:
        return False
    vol = df.iloc[i]['volume']
    vol_avg = 0.0
    for j in range(cfg.VOLUME_AVG_SHORT):
        vol_avg += df.iloc[i - j]['volume']
    vol_avg /= cfg.VOLUME_AVG_SHORT
    if vol <= vol_avg:
        return False

    # SMA gate: close above SMA3 but below SMA10 (failed bounce in downtrend)
    c = df.iloc[i]['close']
    sma3 = df.iloc[i].get('sma3', np.nan)
    sma10 = df.iloc[i].get('sma10', np.nan)
    if np.isnan(sma3) or np.isnan(sma10):
        return False
    if c <= sma3 or c >= sma10:
        return False

    return True


# ─── Metals Sub-System ────────────────────────────────────────────────────────
# GLD phases drive signals for all metal ETFs (GLD, SLV).
# Volume logic is INVERTED vs equities: high volume = demand spike = fades.


def is_metals_md_flush(leader_df: pd.DataFrame, leader_phases: pd.Series,
                       i: int) -> bool:
    """
    Metals Markdown Flush (S5): high-volume selling in GLD downtrend → next RTH bleeds.

    Conditions (on the LEADER ticker, i.e. GLD):
      1. Phase = MARK_DOWN (bearish trend confirmed)
      2. Volume > 3-day average (heavy selling / liquidation)

    Unlike equities where high-vol MARK_DOWN bounces fail (S4 needs SMA gate),
    metals just flush on any high-vol MARK_DOWN day. No SMA gate needed —
    the phase + volume is enough.

    GLD backtest: 449 trades, +$43.58 short PnL, avg +$0.097/trade.
    SLV (GLD-led): 449 trades, +$7.89 short PnL.

    Args:
        leader_df: DataFrame for the metals leader (GLD)
        leader_phases: phases from classify_phases(leader_df)
        i: current bar index on the leader
    Returns:
        True if next day's RTH should be shorted
    """
    if leader_phases.iloc[i] != "MARK_DOWN":
        return False

    if i < cfg.VOLUME_AVG_SHORT:
        return False
    vol = leader_df.iloc[i]['volume']
    vol_avg = 0.0
    for j in range(cfg.VOLUME_AVG_SHORT):
        vol_avg += leader_df.iloc[i - j]['volume']
    vol_avg /= cfg.VOLUME_AVG_SHORT
    if vol <= vol_avg:
        return False

    return True


def is_metals_mu_spike(leader_df: pd.DataFrame, leader_phases: pd.Series,
                       i: int) -> bool:
    """
    Metals Markup Spike (S6): high-volume overbought in GLD uptrend → next RTH fades.

    Conditions (on the LEADER ticker, i.e. GLD):
      1. Phase = MARK_UP (bullish trend confirmed)
      2. Volume > 3-day average (demand spike — central banks, physical buyers)
      3. Close > SMA10 (price holding above intermediate MA — extended)

    The setup: in a gold uptrend, a high-volume day with price above SMA10
    signals a demand spike. Unlike equities where this is bullish continuation,
    in metals this is an overbought exhaustion signal — next RTH fades.

    GLD backtest: 453 trades, +$58.04 short PnL, avg +$0.128/trade.
    SLV (GLD-led): 384 trades, +$8.25 short PnL.

    Args:
        leader_df: DataFrame for the metals leader (GLD)
        leader_phases: phases from classify_phases(leader_df)
        i: current bar index on the leader
    Returns:
        True if next day's RTH should be shorted
    """
    if leader_phases.iloc[i] != "MARK_UP":
        return False

    if i < cfg.VOLUME_AVG_SHORT:
        return False
    vol = leader_df.iloc[i]['volume']
    vol_avg = 0.0
    for j in range(cfg.VOLUME_AVG_SHORT):
        vol_avg += leader_df.iloc[i - j]['volume']
    vol_avg /= cfg.VOLUME_AVG_SHORT
    if vol <= vol_avg:
        return False

    # SMA gate: close above SMA10 (extended in uptrend)
    c = leader_df.iloc[i]['close']
    sma10 = leader_df.iloc[i].get('sma10', np.nan)
    if np.isnan(sma10):
        return False
    if c <= sma10:
        return False

    return True


def _vix_in_ranges(vix: float, ranges: list) -> bool:
    """Check if VIX falls within any of the given (lo, hi) ranges."""
    for lo, hi in ranges:
        if lo <= vix < hi:
            return True
    return False


def _weak_regime_sma_check(df: pd.DataFrame, i: int) -> bool:
    """
    Shared SMA stack check for S7a/S7b: price below SMA200 in a specific formation.

    Conditions (all must be true):
      1. Close > SMA3  (short-term bounce — NOT freefall)
      2. Close < SMA20 (below intermediate trend)
      3. Close < SMA50 (below medium trend)
      4. Close < SMA200 (below long-term trend — weak regime confirmed)
    """
    row = df.iloc[i]
    c = row['close']
    sma3 = row.get('sma3', np.nan)
    sma20 = row.get('sma20', np.nan)
    sma50 = row.get('sma50', np.nan)
    sma200 = row.get('sma200', np.nan)

    if np.isnan(sma3) or np.isnan(sma20) or np.isnan(sma50) or np.isnan(sma200):
        return False

    return c > sma3 and c < sma20 and c < sma50 and c < sma200


def is_weak_regime_overnight(df: pd.DataFrame, phases: pd.Series, i: int) -> bool:
    """
    Weak Regime Overnight Signal (S7a): below-SMA200 regime → overnight gap bleeds.

    Conditions:
      1. SMA stack: C > SMA3 AND C < SMA20 AND C < SMA50 AND C < SMA200
      2. VIX in [20-30] or [40+]

    Execution: SHORT at Close[i], COVER at Open[i+1].
    QQQ: 227 trades, +$83.47, PF 1.88 | SPY: 227 trades, +$112.44, PF 2.01.
    Indices only (cfg.S7_TICKERS).
    """
    if not _weak_regime_sma_check(df, i):
        return False

    vix = df.iloc[i].get('vix', np.nan)
    if np.isnan(vix):
        return False

    return _vix_in_ranges(vix, cfg.S7_OVERNIGHT_VIX)


def is_weak_regime_rth(df: pd.DataFrame, phases: pd.Series, i: int) -> bool:
    """
    Weak Regime RTH Signal (S7b): below-SMA200 regime → next RTH session sells off.

    Conditions:
      1. SMA stack: C > SMA3 AND C < SMA20 AND C < SMA50 AND C < SMA200
      2. VIX in [20-25] or [30-40]

    Execution: SHORT at Open[i+1], COVER at Close[i+1] (same as S2-S4).
    QQQ: 177 trades, +$73.96, PF 1.79 | SPY: 171 trades, +$40.24, PF 1.26.
    Indices only (cfg.S7_TICKERS).
    """
    if not _weak_regime_sma_check(df, i):
        return False

    vix = df.iloc[i].get('vix', np.nan)
    if np.isnan(vix):
        return False

    return _vix_in_ranges(vix, cfg.S7_RTH_VIX)


def should_short_overnight(df: pd.DataFrame, phases: pd.Series, i: int,
                           ticker: str = "QQQ") -> str:
    """
    Overnight signal router: returns which overnight signal fired, or "".

    Currently only S7a (weak_regime_overnight) for QQQ/SPY.
    Separate from should_short_rth() because execution model is different:
      - Overnight: SHORT at Close[i], COVER at Open[i+1]
      - RTH:       SHORT at Open[i+1], COVER at Close[i+1]
    """
    t = ticker.upper()
    if t not in cfg.S7_TICKERS:
        return ""
    if is_weak_regime_overnight(df, phases, i):
        return "weak_regime_overnight"
    return ""


def should_short_rth(df: pd.DataFrame, phases: pd.Series, i: int,
                     ticker: str = "QQQ",
                     leader_df: pd.DataFrame = None,
                     leader_phases: pd.Series = None) -> str:
    """
    Master signal router: returns which signal fired, or empty string if none.

    Three sub-systems:
      Indices (QQQ, SPY, IWM):  S2 + S3 + S4 + S7b
      Stocks (everything else): S2 + S4
      Metals (GLD, SLV):        S5 + S6 (uses GLD as leader)

    For metals tickers, caller must provide leader_df and leader_phases
    (pre-loaded GLD data). The bar index i must be date-aligned between
    the trade ticker and the leader.

    Args:
        df: DataFrame for the ticker being traded
        phases: phases from classify_phases(df)
        i: current bar index
        ticker: ticker symbol (determines sub-system routing)
        leader_df: DataFrame for metals leader (GLD). Required for metals.
        leader_phases: phases for metals leader. Required for metals.
    Returns:
        Signal name or ""
    """
    t = ticker.upper()

    # ── Metals sub-system: S5 + S6 (GLD-led) ──
    if t in cfg.METALS_TICKERS:
        if leader_df is None or leader_phases is None:
            return ""  # caller must provide leader data
        if is_metals_md_flush(leader_df, leader_phases, i):
            return "metals_md_flush"
        if is_metals_mu_spike(leader_df, leader_phases, i):
            return "metals_mu_spike"
        return ""

    # ── Equity sub-systems ──
    if is_rth_avoid(df, phases, i):
        return "rth_avoid"
    if t in cfg.INDEX_TICKERS and is_markup_fade(df, phases, i):
        return "markup_fade"
    if is_markdown_crush(df, phases, i):
        return "markdown_crush"
    if t in cfg.S7_TICKERS and is_weak_regime_rth(df, phases, i):
        return "weak_regime_rth"
    return ""


def phase_summary(phases: pd.Series) -> dict:
    """
    Return phase distribution stats for quick validation.
    """
    total = len(phases)
    counts = phases.value_counts()
    return {
        'total_bars': total,
        'MARK_UP':    counts.get('MARK_UP', 0),
        'MARK_DOWN':  counts.get('MARK_DOWN', 0),
        'DIST_ACCUM': counts.get('DIST_ACCUM', 0),
        'pct_markup':  counts.get('MARK_UP', 0) / total * 100,
        'pct_markdn':  counts.get('MARK_DOWN', 0) / total * 100,
        'pct_dist':    counts.get('DIST_ACCUM', 0) / total * 100,
    }
