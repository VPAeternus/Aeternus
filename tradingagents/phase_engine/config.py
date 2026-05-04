"""
Aeternus Core — Configuration
All tunable parameters in one place. No magic numbers in engine code.

SYSTEM: Phase Detection Engine + Data Infrastructure
The Wyckoff Adaptive Phase Engine is the proven edge.
Everything else gets built on top of this foundation.
"""

# ─── Universe ─────────────────────────────────────────────────────────────────

UNIVERSE = [
    "QQQ", "SPY", "IWM",                   # indices
    "NVDA", "AMD", "TSLA", "META",          # mega-cap momentum
    "AAPL", "MSFT", "GOOGL", "AMZN",        # mega-cap core
    "NFLX", "AVGO", "CRM", "SNOW",          # growth
]

START_DATE = "1999-01-01"

# ─── Data Engine ──────────────────────────────────────────────────────────────

CACHE_DIR           = "/tmp/aeternus_cache"
CACHE_STALE_DAYS    = 1         # re-download if cache older than this
WARMUP_DAYS         = 400       # extra days before start_date for indicator warmup
ADR_WINDOW          = 14        # Average Daily Range lookback
VOLUME_AVG_WINDOW   = 20        # volume moving average lookback
SMA_SLOPE_LOOKBACK  = 5         # bars to measure SMA slope

# ─── Phase Engine (Wyckoff Adaptive) ─────────────────────────────────────────

FVG_RATIO_WINDOW    = 20        # rolling bar count for FVG ratio
MARKUP_PERCENTILE   = 75        # ratio in top 25% of history → MARK_UP
MARKDN_PERCENTILE   = 25        # ratio in bottom 25% → MARK_DOWN
PHASE_MIN_HISTORY   = 252       # minimum bars before percentile calc is valid

# Macro regime filters
MACRO_SMA200_LOOKBACK = 60      # F1: SMA200 must decline over this many bars
MACRO_VIX_THRESHOLD   = 22      # F4: VIX SMA20 must be >= this for "sustained fear"
MACRO_VIX_STRESS      = 25      # VIX SMA20 > this → market-wide stress regime
MARKET_HEALTH_TICKER  = "QQQ"   # check this ticker for market regime

# ─── RTH Avoidance Signal ─────────────────────────────────────────────────────
# DIST_ACCUM + low volume + VIX sweet spot → next-day RTH bleeds
# QQQ backtest: 1013 trades, +$220 short PnL in VIX 15-25 bucket

VOLUME_AVG_SHORT    = 3         # 3-day volume average for signal
VIX_FLOOR           = 15        # min VIX for signal (below = too complacent, shorts lose)
VIX_CEILING         = 25        # max VIX for signal (above = too panicky, mean-reversion kills shorts)

# ─── Signal Eligibility ──────────────────────────────────────────────────────
# S3 (markup_fade) only works on indices — loses on single stocks cross-ticker.
# S2 (rth_avoid) and S4 (markdown_crush) are universal.

INDEX_TICKERS = {"QQQ", "SPY", "IWM"}  # tickers eligible for all 3 signals

# ─── Metals Sub-System ───────────────────────────────────────────────────────
# Metals have inverted volume logic vs equities:
#   - High volume = demand (central banks, physical buyers) → NOT continuation
#   - Volume filters are FLIPPED: high vol signals overbought/oversold fades
# GLD is the signal leader — SLV and other metal ETFs follow GLD's phases.
#
# S5 (metals_md_flush): GLD MARK_DOWN + Vol>3d → short next RTH
#   GLD: 449 trades, +$43.58 | SLV (GLD-led): 449 trades, +$7.89
# S6 (metals_mu_spike): GLD MARK_UP + Vol>3d + C>SMA10 → short next RTH
#   GLD: 453 trades, +$58.04 | SLV (GLD-led): 384 trades, +$8.25

METALS_LEADER     = "GLD"                # signal source for all metals
METALS_TICKERS    = {"GLD", "SLV"}       # tickers that use metals sub-system

# ─── S7: Weak Regime Bear ────────────────────────────────────────────────────
# Below SMA200 with specific SMA stack → overnight gaps bleed + RTH sells off.
# Indices only (stocks lose money aggregate). VIX buckets isolate the edge.
#
# S7a (overnight): Close→Open short, VIX 20-30 + 40+
#   QQQ: 227 trades, +$83, PF 1.88 | SPY: 227 trades, +$112, PF 2.01
# S7b (RTH): Open→Close short, VIX 20-25 + 30-40
#   QQQ: 177 trades, +$74, PF 1.79 | SPY: 171 trades, +$40, PF 1.26

S7_TICKERS = {"QQQ", "SPY"}                # indices only — stocks lose money
S7_OVERNIGHT_VIX = [(20, 30), (40, 200)]   # VIX 20-30 + VIX 40+
S7_RTH_VIX = [(20, 25), (30, 40)]          # VIX 20-25 + VIX 30-40

# ─── Cost Model ───────────────────────────────────────────────────────────────

TRANSACTION_BPS     = 10        # round-trip cost per trade
STOP_SLIPPAGE_BPS   = 20        # extra slippage on stop-loss exits
