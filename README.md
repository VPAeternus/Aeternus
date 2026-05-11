<p align="center">
  <img src="assets/TauricResearch.png" style="width: 60%; height: auto;">
</p>

<div align="center" style="line-height: 1;">
  <a href="https://arxiv.org/abs/2412.20138" target="_blank"><img alt="arXiv" src="https://img.shields.io/badge/arXiv-2412.20138-B31B1B?logo=arxiv"/></a>
  <a href="https://discord.com/invite/hk9PGKShPK" target="_blank"><img alt="Discord" src="https://img.shields.io/badge/Discord-TradingResearch-7289da?logo=discord&logoColor=white&color=7289da"/></a>
  <a href="./assets/wechat.png" target="_blank"><img alt="WeChat" src="https://img.shields.io/badge/WeChat-TauricResearch-brightgreen?logo=wechat&logoColor=white"/></a>
  <a href="https://x.com/TauricResearch" target="_blank"><img alt="X Follow" src="https://img.shields.io/badge/X-TauricResearch-white?logo=x&logoColor=white"/></a>
  <br>
  <a href="https://github.com/TauricResearch/" target="_blank"><img alt="Community" src="https://img.shields.io/badge/Join_GitHub_Community-TauricResearch-14C290?logo=discourse"/></a>
</div>

<div align="center">
  <!-- Keep these links. Translations will automatically update with the README. -->
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=de">Deutsch</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=es">Español</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=fr">français</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ja">日本語</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ko">한국어</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=pt">Português</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ru">Русский</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=zh">中文</a>
</div>

---

# TradingAgents: Multi-Agents LLM Financial Trading Framework 

> 🎉 **TradingAgents** officially released! We have received numerous inquiries about the work, and we would like to express our thanks for the enthusiasm in our community.
>
> So we decided to fully open-source the framework. Looking forward to building impactful projects with you!

<div align="center">
<a href="https://www.star-history.com/#TauricResearch/TradingAgents&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=TauricResearch/TradingAgents&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=TauricResearch/TradingAgents&type=Date" />
   <img alt="TradingAgents Star History" src="https://api.star-history.com/svg?repos=TauricResearch/TradingAgents&type=Date" style="width: 80%; height: auto;" />
 </picture>
</a>
</div>

<div align="center">

🚀 [TradingAgents](#tradingagents-framework) | ⚡ [Installation & CLI](#installation-and-cli) | 🎬 [Demo](https://www.youtube.com/watch?v=90gr5lwjIho) | 📦 [Package Usage](#tradingagents-package) | 🤝 [Contributing](#contributing) | 📄 [Citation](#citation)

</div>

## TradingAgents Framework

TradingAgents is a multi-agent trading framework that mirrors the dynamics of real-world trading firms. By deploying specialized LLM-powered agents: from fundamental analysts, sentiment experts, and technical analysts, to trader, risk management team, the platform collaboratively evaluates market conditions and informs trading decisions. Moreover, these agents engage in dynamic discussions to pinpoint the optimal strategy.

<p align="center">
  <img src="assets/schema.png" style="width: 100%; height: auto;">
</p>

> TradingAgents framework is designed for research purposes. Trading performance may vary based on many factors, including the chosen backbone language models, model temperature, trading periods, the quality of data, and other non-deterministic factors. [It is not intended as financial, investment, or trading advice.](https://tauric.ai/disclaimer/)

Our framework decomposes complex trading tasks into specialized roles. This ensures the system achieves a robust, scalable approach to market analysis and decision-making.

### Analyst Team
- **Fundamentals Analyst + Reviewer**: The Fundamentals Analyst evaluates company financials and performance metrics, identifying intrinsic values and potential red flags. The Fundamental Reviewer applies deep-thinking critique, cross-referencing computed metrics (Piotroski F-Score, ROE, growth rates, balance sheet health) against the analyst's qualitative assessment.
- **Sentiment Analyst + Reviewer**: The Social Media Analyst analyzes social media and public sentiment using sentiment scoring algorithms. The Sentiment Reviewer applies deep-thinking critique, computing quantitative polarity, buzz, and catalyst scores from Alpha Vantage and text-based sentiment data.
- **News Analyst + Macro Reviewer**: The News Analyst monitors global news and macroeconomic indicators. The Macro Reviewer applies deep-thinking critique, computing regime classification, monetary stress, rate headwind, and commodity cycle scores.
- **Technical Analyst + Momentum Reviewer**: The Market Analyst utilizes technical indicators (MACD, RSI, Bollinger Bands) to detect trading patterns. The Momentum Reviewer applies deep-thinking critique, computing trend strength, momentum health, regime quality, and volume confirmation scores.

<p align="center">
  <img src="assets/analyst.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

### Researcher Team
- Comprises both bullish and bearish researchers who critically assess the insights provided by the Analyst Team. Through structured debates, they balance potential gains against inherent risks.

<p align="center">
  <img src="assets/researcher.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

### Trader Agent
- Composes reports from the analysts and researchers to make informed trading decisions. It determines the timing and magnitude of trades based on comprehensive market insights.

<p align="center">
  <img src="assets/trader.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

### Risk Management and Portfolio Manager
- Continuously evaluates portfolio risk by assessing market volatility, liquidity, and other risk factors. The risk management team evaluates and adjusts trading strategies, providing assessment reports to the Portfolio Manager for final decision.
- The Portfolio Manager approves/rejects the transaction proposal. If approved, the order will be sent to the simulated exchange and executed.

<p align="center">
  <img src="assets/risk.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

### Aeternus Score

The Aeternus Score is a composite 0–100 investment rating computed from five anchored dimensions:

| Dimension | Weight (Neutral) | Sub-Scores |
|-----------|-----------------|------------|
| **Fundamental** | 30% | Quality, Growth, Health, Valuation |
| **Coherence** | 25% | Directional Alignment, Conviction Strength, Interaction Patterns, Narrative Stability |
| **Macro** | 20% | Regime Fit, Monetary Stress, Rate Headwind, Commodity Cycle |
| **Sentiment** | 15% | Polarity, Buzz, Catalyst |
| **Momentum** | 10% | Trend Strength, Momentum Health, Regime Quality, Volume Confirmation |

**Regime-Adaptive Weights**: Dimension weights shift based on the current macro regime (Bull, Bear, Vol Shock, Risk Off, Euphoria, etc.). For example, in a Bear regime, Coherence weight increases to 30% and Macro to 25%. In a Euphoria regime, Coherence rises to 35% to detect crowding and divergence patterns.

**Thesis Coherence**: The Coherence dimension is a meta-analytical pillar that measures cross-pillar agreement. It detects 8 named interaction patterns including Value Trap, Momentum Crowding, Contrarian Setup, Rising Tide, Falling Knife, Regime Transition, Quality Divergence, and Smart Money Disagrees. Each pattern fires based on specific cross-pillar conditions and contributes confidence-weighted adjustments.

**Alpha Decomposition**: A factor-neutral analysis that decomposes the Aeternus Score into factor-explained returns (macro, valuation, momentum) and residual alpha — the value generated by agent reasoning beyond standard factors.

**Catalyst Timeline**: Metadata about upcoming earnings and dividend dates, classifying earnings proximity as imminent (≤7 days), near (≤30 days), or distant.

The score maps to ratings: Strong Buy (≥80), Buy (≥60), Hold (≥40), Sell (≥20), Strong Sell (<20).

## Installation and CLI

### Quick Install from GitHub

Install directly from GitHub using pip:
```bash
pip install git+https://github.com/VPAeternus/AeternusAgentsAG.git
```

After installation, you can use the CLI commands:
```bash
# Get Aeternus score and rating for a ticker
aeternus score AAPL

# Get score in JSON format
aeternus score AAPL --format json

# Run full multi-agent analysis (interactive)
aeternus analyze
```

### Manual Installation

Clone AeternusAgentsAG:
```bash
git clone https://github.com/VPAeternus/AeternusAgentsAG.git
cd AeternusAgentsAG
```

Create a virtual environment in any of your favorite environment managers:
```bash
conda create -n tradingagents python=3.13
conda activate tradingagents
```

Install dependencies:
```bash
pip install -r requirements.txt
```

### Required APIs

You will need the OpenAI API for all the agents, and [Alpha Vantage API](https://www.alphavantage.co/support/#api-key) for fundamental and news data (default configuration).

```bash
export OPENAI_API_KEY=$YOUR_OPENAI_API_KEY
export ALPHA_VANTAGE_API_KEY=$YOUR_ALPHA_VANTAGE_API_KEY
```

Alternatively, you can create a `.env` file in the project root with your API keys (see `.env.example` for reference):
```bash
cp .env.example .env
# Edit .env with your actual API keys
```

### Optional: Build House Congress Feed URLs (for smart-money connector)

If you want House disclosure coverage in Deal Flow smart-money, generate a normalized House PTR JSON feed and host it at one or two URLs:

```bash
# Build normalized feed from official House Clerk PTR filings
./.venv/bin/python scripts/build_house_ptr_feed.py \
  --year 2026 --year 2025 \
  --out eval_results/deal_flow/house_transactions.json
```

Then host that JSON (for example on GitHub raw + a mirror), and set:

```bash
DEALFLOW_CONGRESS_HOUSE_URL=https://<primary>/house_transactions.json
DEALFLOW_CONGRESS_HOUSE_FALLBACK_URL=https://<fallback>/house_transactions.json
```

You can also run without external hosting by pointing these vars to local file paths. The smart-money connector now accepts both HTTP(S) URLs and local paths (for example `eval_results/deal_flow/house_transactions.json`).

### Optional: Scheduler Auto-Refresh + X Budget Auto-Tune

To automate House feed refresh during `aeternus orchestrate` runs and tune X call budgets from realized attribution:

```bash
DEALFLOW_HOUSE_FEED_AUTO_REFRESH=true
DEALFLOW_HOUSE_FEED_REFRESH_INTERVAL_HOURS=24
DEALFLOW_HOUSE_FEED_PRIMARY_PATH=eval_results/deal_flow/house_transactions.json
DEALFLOW_HOUSE_FEED_FALLBACK_PATH=eval_results/deal_flow/house_transactions_fallback.json

DEALFLOW_X_AUTO_TUNE_ENABLED=true
DEALFLOW_X_AUTO_TUNE_APPLY=true
DEALFLOW_X_TUNER_LOOKBACK_DAYS=30
DEALFLOW_X_TUNER_MIN_EVALUATED=6
DEALFLOW_X_TUNER_MAX_STEP_CALLS=1
DEALFLOW_X_TUNER_MIN_DAILY_BUDGET_USD=8.0
DEALFLOW_X_TUNER_MAX_DAILY_BUDGET_USD=30.0
DEALFLOW_X_TUNER_REQUIRE_HORIZON_ALIGNMENT=true
```

Each orchestrated run will emit:
- `house_feed_refresh` status in the orchestration result
- `x_budget_policy` plus persisted artifacts:
  - `eval_results/deal_flow/<date>/x_budget_policy.json`
  - `eval_results/deal_flow/x_budget_policy_latest.json`

Once pushed, anyone will be able to install the platform directly using:
`pip install git+https://github.com/VPAeternus/AeternusAgentsAG.git`

**Note:** We are happy to partner with Alpha Vantage to provide robust API support for TradingAgents. You can get a free AlphaVantage API [here](https://www.alphavantage.co/support/#api-key), TradingAgents-sourced requests also have increased rate limits to 60 requests per minute with no daily limits. Typically the quota is sufficient for performing complex tasks with TradingAgents thanks to Alpha Vantage's open-source support program. If you prefer to use OpenAI for these data sources instead, you can modify the data vendor settings in `tradingagents/default_config.py`.

### CLI Usage

#### Aeternus Score Command

Get a quick Aeternus score and rating for any ticker:
```bash
# Table format (default)
aeternus score AAPL

# JSON format
aeternus score AAPL --format json

# Specify a date
aeternus score TSLA --date 2024-05-10
```

#### Trust & Verification (Performance Tracking)

Monitor your system's accuracy and inspect the immutable audit trail:
```bash
# View full rating history
aeternus track-record

# View win rate and average return statistics
aeternus performance

# View full audit history for a specific rating (UUID)
aeternus rating-history <UUID>
```

#### Deal Flow Operations

Generate the automated scout ticker handoff:

Daily technical scout preflight:

- `technical-universe-refresh` rebuilds the current technical universe from configured index sources (`SPY`, `QQQ`, `DOW`) and stores the deduped membership snapshot in `eval_results/control/technical_universe/` plus the SQLite technical cache. This answers: “what symbols should technical scouts consider today?”
- `technical-signal-sync` syncs OHLCV history for that universe into `eval_results/control/technical_signal_cache.db`, then recomputes current KAMA/FVG signal state. This answers: “which current-universe names have live technical ignition/recall setups?”
- Run these before breakout/technical ignition/FVG/FMA recall so later scouts use current membership and fresh price-derived signals.

```bash
# Refresh current technical universe snapshot
python -m cli.main technical-universe-refresh --as-of-date 2026-05-05 --format table

# Sync OHLCV and recompute KAMA/FVG technical signals
python -m cli.main technical-signal-sync --format table

# Run deal-flow scouts and write final_dealflow_tickers.json
aeternus source --date 2026-02-06 --trigger manual --profile daily --format table

# Explicit low-cost profile (fast daily mode)
aeternus source --date 2026-02-06 --trigger daily --profile daily --format table

# Explicit max-recall profile (higher coverage / higher cost)
aeternus source --date 2026-02-06 --trigger manual --profile max-recall --format table

# Run fundamental framework from scout handoff
aeternus fundamental --date 2026-02-06

# Run orchestrator policy (daily/event/manual)
aeternus orchestrate --mode auto --profile daily --format table

# Workflow stops at scout handoff; scoring starts in the fundamental framework
aeternus workflow-run --mode auto --profile daily --execution-mode alpaca-paper --format table

# Repeated workflow automation wrapper (scheduled-style loop)
aeternus workflow-loop --mode auto --profile daily --cycles 3 --interval-seconds 900 --execution-mode alpaca-paper --format table

# Build deterministic portfolio plan from a post-fundamental summary
aeternus portfolio-plan --summary-path eval_results/fundamental/2026-02-06/analysis_summary.json --capital-usd 100000 --max-positions 8 --execution-mode alpaca-paper --format table
# Hedge overlay is enabled by default; use --skip-hedges to disable for a run.

# Execute paper orders with deterministic pre-trade risk checks
aeternus execute-paper --format table

# Execute via Alpaca paper broker adapter (submits to Alpaca API, no local fills)
aeternus execute-paper --execution-mode alpaca-paper --format table
# Quantity policy defaults to whole shares (`ALPACA_ENFORCE_WHOLE_SHARES=true`)
# Position parity gate is enabled by default for alpaca modes (broker vs shadow drift pre-check).

# Override parity behavior for diagnostics-only runs (do not block on drift)
aeternus execute-paper --execution-mode alpaca-paper --position-parity-warn-only --format table

# Pull latest Alpaca broker orders snapshot for reconciliation
aeternus pull-broker-orders --broker alpaca --mode alpaca-paper --status all --limit 500 --format table

# Pull latest Alpaca broker positions snapshot for diagnostics
aeternus pull-broker-positions --broker alpaca --mode alpaca-paper --format table

# Compare broker positions vs live shadow ledger (per-symbol drift)
aeternus positions-drift --broker alpaca --mode alpaca-paper --format table

# Reconcile live broker snapshot into outbox + shadow positions + fills
aeternus reconcile-execution --broker-snapshot-path eval_results/live_execution/broker_orders_latest.json --format table

# One-shot live sync (pull + reconcile + position/PnL refresh)
aeternus execution-sync --broker alpaca --mode alpaca-paper --once --format table

# Continuous live sync loop (example: every 300s)
aeternus execution-sync --broker alpaca --mode alpaca-paper --loop --interval-sec 300 --format table

# Live sync + readiness gate + deterministic exit submission
# (auto-remediates stale pending orders + broker/shadow drift by default)
aeternus execution-sync --broker alpaca --mode alpaca-paper --once --apply-exits --require-ready --format table

# Reconcile using explicit closed-trade ledger path (updates track record on position closures)
aeternus reconcile-execution --broker-snapshot-path eval_results/live_execution/broker_orders_latest.json --closed-trades-path eval_results/live_execution/closed_trades.json --format table

# Diagnostic run without readiness auto-remediation
aeternus execution-sync --broker alpaca --mode alpaca-paper --once --apply-exits --require-ready --no-auto-remediate-readiness --format table

# Live sync with stale-order manager + broker-shadow sync + readiness + exits (full safety cycle)
aeternus execution-sync --broker alpaca --mode alpaca-paper --once --manage-open-orders --manage-open-orders-apply --sync-shadow-positions --sync-shadow-positions-apply --apply-exits --require-ready --format table

# Evaluate broker execution readiness gate explicitly
aeternus execution-readiness --broker alpaca --mode alpaca-paper --format table

# Run one deterministic hedge evaluation cycle
# Default hedge policy is S7-only: 100% hedge only when SPY S7a/b is active.
# A/B legacy mode: AETERNUS_HEDGE_POLICY=bear_base aeternus hedge-evaluate --format table
aeternus hedge-evaluate --format table

# Inspect persisted hedge state + recent hedge actions
aeternus hedge-status --format table

# Manage stale broker open orders (preview only)
aeternus manage-open-orders --broker alpaca --mode alpaca-paper --dry-run --format table

# Manage stale broker open orders (apply cancel/replace policy)
aeternus manage-open-orders --broker alpaca --mode alpaca-paper --apply --replace-stale --format table

# Sync shadow positions from broker snapshot (preview only)
aeternus sync-positions-from-broker --broker alpaca --mode alpaca-paper --dry-run --format table

# Sync shadow positions from broker snapshot and apply changes
aeternus sync-positions-from-broker --broker alpaca --mode alpaca-paper --apply --format table

# Generate deterministic exit signals (preview only)
aeternus manage-exits --execution-mode alpaca-paper --dry-run --format table

# Generate + submit deterministic exit orders
aeternus manage-exits --execution-mode alpaca-paper --submit --format table

# Optional risk overrides for one run
aeternus execute-paper --max-gross-exposure-pct 1.0 --max-single-position-pct 0.25 --max-open-positions 12 --format table

# Hedge-specific risk overrides (when hedge intents are present)
aeternus execute-paper --allow-hedge-shorts --max-hedge-notional-pct 1.5 --format table

# Inspect current paper positions
aeternus paper-positions --format table

# Inspect current live/shadow positions
aeternus live-positions --format table

# Close one paper position and propagate outcome to track-record/audit
aeternus close-paper TSLA --close-price 265.40 --close-date 2026-02-06 --format table

# Step 1 readiness gates (stability + attribution + connector policy)
aeternus step1-readiness --date 2026-02-06 --format table

# Step 2 evidence pack (regimes + walkforward + ablation)
aeternus evidence-pack --from-date 2026-02-06 --to-date 2026-02-07 --extra-benchmark IWM --format table
aeternus evidence-regimes --date 2026-02-07 --format table
aeternus evidence-walkforward --from-date 2026-02-06 --to-date 2026-02-07 --format table
aeternus evidence-ablation --from-date 2026-02-06 --to-date 2026-02-07 --format table

# Run one symbol from queue
aeternus analyze --from-queue-id <queue_id>

# Weekly X account discovery suggestions (approval-based)
aeternus x-discovery --date 2026-02-06 --format table
```

`source` and `queue` tables now include feed provenance so each candidate shows where it came from (for example `X_FEED`, `WEB_NEWS`, `SEC_CONGRESS`, `INSIDER`, `MANUAL_WATCHLIST`).

Manual watchlist overlay:

```bash
# Add operator idea
aeternus watchlist add TSLA --priority 5 --lane MOMENTUM --note "thesis note"

# List watchlist
aeternus watchlist list --format table

# Remove operator idea
aeternus watchlist remove TSLA

# Import watchlist entries from file
aeternus watchlist import --file ./watchlist.json
```

Equivalent module-style commands (same behavior, useful in local venv):

```bash
./.venv/bin/python -m cli.main source --date 2026-02-06 --trigger manual --profile daily --format table
./.venv/bin/python -m cli.main fundamental --date 2026-02-06
./.venv/bin/python -m cli.main workflow-run --mode auto --profile daily --execution-mode alpaca-paper --format table
./.venv/bin/python -m cli.main workflow-loop --mode auto --profile daily --cycles 3 --interval-seconds 900 --execution-mode alpaca-paper --format table
./.venv/bin/python -m cli.main portfolio-plan --summary-path eval_results/fundamental/2026-02-06/analysis_summary.json --capital-usd 100000 --max-positions 8 --execution-mode alpaca-paper --format table
./.venv/bin/python -m cli.main portfolio-plan --summary-path eval_results/fundamental/2026-02-06/analysis_summary.json --skip-hedges --format table
./.venv/bin/python -m cli.main execute-paper --format table
./.venv/bin/python -m cli.main execute-paper --allow-hedge-shorts --max-hedge-notional-pct 1.5 --format table
./.venv/bin/python -m cli.main execute-paper --execution-mode alpaca-paper --format table
./.venv/bin/python -m cli.main pull-broker-orders --broker alpaca --mode alpaca-paper --status all --limit 500 --format table
./.venv/bin/python -m cli.main pull-broker-positions --broker alpaca --mode alpaca-paper --format table
./.venv/bin/python -m cli.main positions-drift --broker alpaca --mode alpaca-paper --format table
./.venv/bin/python -m cli.main reconcile-execution --broker-snapshot-path eval_results/live_execution/broker_orders_latest.json --format table
./.venv/bin/python -m cli.main reconcile-execution --broker-snapshot-path eval_results/live_execution/broker_orders_latest.json --closed-trades-path eval_results/live_execution/closed_trades.json --format table
./.venv/bin/python -m cli.main execution-sync --broker alpaca --mode alpaca-paper --once --format table
./.venv/bin/python -m cli.main execution-sync --broker alpaca --mode alpaca-paper --once --apply-exits --require-ready --format table
./.venv/bin/python -m cli.main execution-sync --broker alpaca --mode alpaca-paper --once --apply-exits --require-ready --no-auto-remediate-readiness --format table
./.venv/bin/python -m cli.main execution-sync --broker alpaca --mode alpaca-paper --once --manage-open-orders --manage-open-orders-apply --sync-shadow-positions --sync-shadow-positions-apply --apply-exits --require-ready --format table
./.venv/bin/python -m cli.main execution-readiness --broker alpaca --mode alpaca-paper --format table
./.venv/bin/python -m cli.main hedge-evaluate --format table
./.venv/bin/python -m cli.main hedge-status --format table
./.venv/bin/python -m cli.main manage-open-orders --broker alpaca --mode alpaca-paper --dry-run --format table
./.venv/bin/python -m cli.main manage-open-orders --broker alpaca --mode alpaca-paper --apply --replace-stale --format table
./.venv/bin/python -m cli.main sync-positions-from-broker --broker alpaca --mode alpaca-paper --dry-run --format table
./.venv/bin/python -m cli.main sync-positions-from-broker --broker alpaca --mode alpaca-paper --apply --format table
./.venv/bin/python -m cli.main manage-exits --execution-mode alpaca-paper --dry-run --format table
./.venv/bin/python -m cli.main manage-exits --execution-mode alpaca-paper --submit --format table
./.venv/bin/python -m cli.main paper-positions --format table
./.venv/bin/python -m cli.main live-positions --format table
./.venv/bin/python -m cli.main close-paper TSLA --close-price 265.40 --close-date 2026-02-06 --format table
```

Weekly X account discovery candidate generation:

```bash
aeternus x-discovery --date 2026-02-06 --format table
```

#### Phase Engine & Momentum Commands

The phase engine provides Wyckoff-based phase classification and momentum signal scanning, operating independently from the agent pipeline:

```bash
# Scan universe for today's phase signals
aeternus phase-scan

# Live scan using real-time Alpaca data
aeternus phase-scan --live --json

# Scan specific tickers
aeternus phase-scan --tickers AAPL MSFT NVDA

# Backtest phase engine on a single ticker
aeternus phase-backtest --ticker AAPL

# Show current Wyckoff phase classification for each ticker
aeternus phase-status

# Scan momentum signals across universe
aeternus momentum-scan
aeternus momentum-scan --tickers AAPL MSFT NVDA
```

Portfolio plans include phase overlay (short) and momentum overlay (long) intents by default:
```bash
# Build plan with both overlays (default)
aeternus portfolio-plan --summary-path eval_results/fundamental/2026-02-06/analysis_summary.json --capital-usd 100000

# Disable phase overlay
aeternus portfolio-plan --summary-path eval_results/fundamental/2026-02-06/analysis_summary.json --skip-phase-overlay

# Disable momentum overlay
aeternus portfolio-plan --summary-path eval_results/fundamental/2026-02-06/analysis_summary.json --skip-momentum-overlay
```

#### Full Analysis Command

You can also try out the CLI directly by running:
```bash
python -m cli.main
# or
aeternus analyze
```
You will see a screen where you can select your desired tickers, date, LLMs, research depth, etc.

<p align="center">
  <img src="assets/cli/cli_init.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

An interface will appear showing results as they load, letting you track the agent's progress as it runs.

<p align="center">
  <img src="assets/cli/cli_news.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

### Analysis Results

Once the analysis is complete, results are saved to `results/<ticker>/<date>/`:

- **Equity_Research_Report.md**: A comprehensive, formatted report including the Executive Summary, Aeternus Score, and detailed Analyst logs.
- **analysis_report.json**: A full JSON trace of the entire multi-agent session, including all thoughts and tool outputs.

<p align="center">
  <img src="assets/cli/cli_transaction.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

## TradingAgents Package

### Implementation Details

We built TradingAgents with LangGraph to ensure flexibility and modularity. We utilize `o1-preview` and `gpt-4o` as our deep thinking and fast thinking LLMs for our experiments. However, for testing purposes, we recommend you use `o4-mini` and `gpt-4.1-mini` to save on costs as our framework makes **lots of** API calls.

### Python Usage

To use TradingAgents inside your code, you can import the `tradingagents` module and initialize a `TradingAgentsGraph()` object. The `.propagate()` function will return a decision. You can run `main.py`, here's also a quick example:

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

ta = TradingAgentsGraph(debug=True, config=DEFAULT_CONFIG.copy())

# forward propagate
_, decision = ta.propagate("NVDA", "2024-05-10")
print(decision)
```

You can also adjust the default configuration to set your own choice of LLMs, debate rounds, etc.

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

# Create a custom config
config = DEFAULT_CONFIG.copy()
config["deep_think_llm"] = "gpt-4.1-nano"  # Use a different model
config["quick_think_llm"] = "gpt-4.1-nano"  # Use a different model
config["max_debate_rounds"] = 1  # Increase debate rounds

# Configure data vendors (default uses yfinance and Alpha Vantage)
config["data_vendors"] = {
    "core_stock_apis": "yfinance",           # Options: yfinance, alpha_vantage, local
    "technical_indicators": "yfinance",      # Options: yfinance, alpha_vantage, local
    "fundamental_data": "alpha_vantage",     # Options: openai, alpha_vantage, local
    "news_data": "alpha_vantage",            # Options: openai, alpha_vantage, google, local
}

# Initialize with custom config
ta = TradingAgentsGraph(debug=True, config=config)

# forward propagate
_, decision = ta.propagate("NVDA", "2024-05-10")
print(decision)
```

> The default configuration uses yfinance for stock price and technical data, and Alpha Vantage for fundamental and news data. For production use or if you encounter rate limits, consider upgrading to [Alpha Vantage Premium](https://www.alphavantage.co/premium/) for more stable and reliable data access. For offline experimentation, there's a local data vendor option that uses our **Tauric TradingDB**, a curated dataset for backtesting, though this is still in development. We're currently refining this dataset and plan to release it soon alongside our upcoming projects. Stay tuned!

You can view the full list of configurations in `tradingagents/default_config.py`.

## Contributing

We welcome contributions from the community! Whether it's fixing a bug, improving documentation, or suggesting a new feature, your input helps make this project better. If you are interested in this line of research, please consider joining our open-source financial AI research community [Tauric Research](https://tauric.ai/).

## Citation

Please reference our work if you find *TradingAgents* provides you with some help :)

```
@misc{xiao2025tradingagentsmultiagentsllmfinancial,
      title={TradingAgents: Multi-Agents LLM Financial Trading Framework}, 
      author={Yijia Xiao and Edward Sun and Di Luo and Wei Wang},
      year={2025},
      eprint={2412.20138},
      archivePrefix={arXiv},
      primaryClass={q-fin.TR},
      url={https://arxiv.org/abs/2412.20138}, 
}
```
