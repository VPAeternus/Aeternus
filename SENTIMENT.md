# Aeternus Research Platform - Complete Architecture

## 🏗️ System Overview

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           AETERNUS RESEARCH PLATFORM                                 │
│                         (Elon/Steve/Jony Principles Applied)                         │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                      │
│   ┌───────────────────────────────────────────────────────────────────────────────┐  │
│   │                        INPUT LAYER (Data Sources)                              │  │
│   ├───────────────────────────────────────────────────────────────────────────────┤  │
│   │                                                                                │  │
│   │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐              │  │
│   │  │  X/Twitter      │  │   Reddit        │  │   Any URL       │              │  │
│   │  │  (Bird Scraper) │  │   (Playwright)  │  │   (News/SEC)    │              │  │
│   │  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘              │  │
│   │           │                    │                    │                        │  │
│   │           └────────────────────┼────────────────────┘                        │  │
│   │                                │                                             │  │
│   │                      ┌─────────▼─────────┐                                    │  │
│   │                      │  Bird Scraper     │                                    │  │
│   │                      │  (Stealth Mode)   │                                    │  │
│   │                      │  scripts/         │                                    │  │
│   │                      │  deal_source.py   │                                    │  │
│   │                      └─────────┬─────────┘                                    │  │
│   └────────────────────────────────┼───────────────────────────────────────────────┘  │
│                                    │                                                  │
│                                    ▼                                                  │
│   ┌───────────────────────────────────────────────────────────────────────────────┐  │
│   │                    QUALITY LAYER (xAI-Inspired Scoring)                        │  │
│   ├───────────────────────────────────────────────────────────────────────────────┤  │
│   │                                                                                │  │
│   │  ┌─────────────────────────────────────────────────────────────────────────┐  │  │
│   │  │              XAI QUALITY SCORER v2.0                                     │  │  │
│   │  │         scripts/xai_quality_scorer_v2.py                                 │  │  │
│   │  │                                                                          │  │  │
│   │  │  Multi-Dimensional Scoring:                                              │  │  │
│   │  │  ├─ Actionability (30%)     → Clear thesis, time horizon, exit strategy  │  │  │
│   │  │  ├─ Risk Awareness (25%)    → Downside acknowledgment                    │  │  │
│   │  │  ├─ Evidence Quality (25%)  → Data, charts, fundamentals                 │  │  │
│   │  │  ├─ Originality (5%)        → Contrarian thinking                        │  │  │
│   │  │  └─ Engagement Velocity (15%) → Relative engagement (replies > likes)    │  │  │
│   │  │                                                                          │  │  │
│   │  │  KEY INNOVATION:                                                         │  │  │
│   │  │  • Hidden Gem Detection (small accounts, high quality)                   │  │  │
│   │  │  • Discovery Score (predicted performance if exposed)                    │  │  │
│   │  │  • Quality-First Weighting (content > popularity)                        │  │  │
│   │  │                                                                          │  │  │
│   │  │  Example:                                                                │  │  │
│   │  │  @microcap_mike (850 followers, 81/100) > @celebrity (500K, 54/100)      │  │  │
│   │  └─────────────────────────────────────────────────────────────────────────┘  │  │
│   │                                    │                                           │  │
│   │                                    ▼                                           │  │
│   │  ┌─────────────────────────────────────────────────────────────────────────┐  │  │
│   │  │                   SPAM FILTER (Two-Stage)                                │  │  │
│   │  │  Stage 1: Pre-scoring                                                   │  │  │
│   │  │  • Spam keywords ("pump", "guaranteed", "100%")                         │  │  │
│   │  │  • Low effort (< 15 words)                                              │  │  │
│   │  │  • Ticker spam (> 5 tickers)                                            │  │  │
│   │  │  • Repetitive mentions                                                  │  │  │
│   │  │  • Fake follower detection                                              │  │  │
│   │  │                                                                          │  │  │
│   │  │  Stage 2: Quality Scoring (only if passes Stage 1)                      │  │  │
│   │  └─────────────────────────────────────────────────────────────────────────┘  │  │
│   └────────────────────────────────┼───────────────────────────────────────────────┘  │
│                                    │                                                  │
│                                    ▼                                                  │
│   ┌───────────────────────────────────────────────────────────────────────────────┐  │
│   │                 ANALYST LAYER (The Account IS the Product)                     │  │
│   ├───────────────────────────────────────────────────────────────────────────────┤  │
│   │                                                                                │  │
│   │  ┌─────────────────────────────────────────────────────────────────────────┐  │  │
│   │  │           ANALYST DISCOVERY ENGINE                                       │  │  │
│   │  │      scripts/analyst_discovery_engine.py                                 │  │  │
│   │  │                                                                          │  │  │
│   │  │  Commands:                                                               │  │  │
│   │  │  • discover @handle --quality-score 85                                   │  │  │
│   │  │  • analyze @handle --depth full                                          │  │  │
│   │  │  • leaderboard --min-tier B                                              │  │  │
│   │  │  • promote @handle --reason "Consistent DD"                              │  │  │
│   │  │                                                                          │  │  │
│   │  │  4-Tier System:                                                          │  │  │
│   │  │  ├─ ELITE (A)      → 100K+ followers, proven track record               │  │  │
│   │  │  ├─ ESTABLISHED (B) → 10K-100K, consistent quality                      │  │  │
│   │  │  ├─ RISING (C)     → 1K-10K, showing promise                            │  │  │
│   │  │  └─ EMERGING (D)   → <1K, high potential (hidden gems)                  │  │  │
│   │  │                                                                          │  │  │
│   │  │  Track Record Tracking:                                                  │  │  │
│   │  │  • Historical quality scores (rolling 20)                               │  │  │
│   │  │  • Consistency score (std dev of quality)                               │  │  │
│   │  │  • Prediction accuracy (outcome validation)                             │  │  │
│   │  │  • Tickers covered over time                                            │  │  │
│   │  └─────────────────────────────────────────────────────────────────────────┘  │  │
│   │                                    │                                           │  │
│   │                                    ▼                                           │  │
│   │  ┌─────────────────────────────────────────────────────────────────────────┐  │  │
│   │  │              ANALYST DATABASE                                            │  │  │
│   │  │                                                                          │  │  │
│   │  │  analyst_discovery_data/                                                 │  │  │
│   │  │  ├── analyst_index.json          → Master index & metadata              │  │  │
│   │  │  └── analysts/                   → Individual profiles                  │  │  │
│   │  │      ├── @charliebilello.json    → Quality: 92, Tier: A                 │  │  │
│   │  │      ├── @ycharts.json           → Quality: 89, Tier: A                 │  │  │
│   │  │      ├── @microcap_mike.json     → Quality: 81, Tier: C (Hidden Gem)    │  │  │
│   │  │      └── ...                       (12 analysts total)                  │  │  │
│   │  │                                                                          │  │  │
│   │  │  Each Profile Contains:                                                │  │  │
│   │  │  • Handle, platform, discovery date                                    │  │  │
│   │  │  • Follower count, following, post count                               │  │  │
│   │  │  • Quality scores history                                              │  │  │
│   │  │  • Tickers covered, sectors, style                                     │  │  │
│   │  │  • Tier assignment, promotion status                                   │  │  │
│   │  └─────────────────────────────────────────────────────────────────────────┘  │  │
│   └────────────────────────────────┼───────────────────────────────────────────────┘  │
│                                    │                                                  │
│                                    ▼                                                  │
│   ┌───────────────────────────────────────────────────────────────────────────────┐  │
│   │                   DEAL FLOW LAYER (Signal Generation)                          │  │
│   ├───────────────────────────────────────────────────────────────────────────────┤  │
│   │                                                                                │  │
│   │  ┌─────────────────────────────────────────────────────────────────────────┐  │  │
│   │  │              SOCIAL DEAL FLOW                                            │  │  │
│   │  │         scripts/social_dealflow.py                                       │  │  │
│   │  │                                                                          │  │  │
│   │  │  Continuous Monitoring:                                                  │  │  │
│   │  │  • Every 15 minutes                                                      │  │  │
│   │  │  • Scrapes promoted analysts only                                        │  │  │
│   │  │  • Extracts tickers from posts                                           │  │  │
│   │  │  • Analyzes sentiment                                                    │  │  │
│   │  │  • Submits to research if quality >= 60                                  │  │  │
│   │  │                                                                          │  │  │
│   │  │  Quality Filtering:                                                      │  │  │
│   │  │  • Only tier B+ analysts                                                 │  │  │
│   │  │  • Only sentiment confidence >= 50                                       │  │  │
│   │  │  • Max 3 tickers per submission                                          │  │  │
│   │  └─────────────────────────────────────────────────────────────────────────┘  │  │
│   │                                    │                                           │  │
│   │                                    ▼                                           │  │
│   │  ┌─────────────────────────────────────────────────────────────────────────┐  │  │
│   │  │         TRADINGAGENTS DEAL FLOW SOURCES                                  │  │  │
│   │  │                                                                          │  │  │
│   │  │  tradingagents/dealflow/sources/                                         │  │  │
│   │  │  ├─ analyst_discovery.py     → NEW: Analyst signals                     │  │  │
│   │  │  ├─ cashtag_stream.py        → $TICKER mentions                         │  │  │
│   │  │  ├─ x_social.py              → X API direct                             │  │  │
│   │  │  ├─ macro.py                 → Macro indicators                         │  │  │
│   │  │  ├─ price_momentum.py        → Technical signals                       │  │  │
│   │  │  ├─ smart_money.py           → Institutional flow                      │  │  │
│   │  │  └─ social_news.py           → News sentiment                          │  │  │
│   │  │                                                                          │  │  │
│   │  │  Analyst Discovery Source:                                               │  │  │
│   │  │  • Reads from analyst database                                          │  │  │
│   │  │  • Aggregates signals by ticker                                         │  │  │
│   │  │  • Weights by analyst quality + consistency                             │  │  │
│   │  │  • Generates DealFlowSignal objects                                     │  │  │
│   │  └─────────────────────────────────────────────────────────────────────────┘  │  │
│   └────────────────────────────────┼───────────────────────────────────────────────┘  │
│                                    │                                                  │
│                                    ▼                                                  │
│   ┌───────────────────────────────────────────────────────────────────────────────┐  │
│   │                   RESEARCH LAYER (TradingAgents Pipeline)                      │  │
│   ├───────────────────────────────────────────────────────────────────────────────┤  │
│   │                                                                                │  │
│   │  ┌─────────────────────────────────────────────────────────────────────────┐  │  │
│   │  │         OPERATOR GATEWAY                                                 │  │  │
│   │  │                                                                          │  │  │
│   │  │  POST /ops/adhoc/research                                                │  │  │
│   │  │  {                                                                       │  │  │
│   │  │    "symbol": "ENVX",                                                     │  │  │
│   │  │    "symbols": ["ENVX"],                                                  │  │  │
│   │  │    "lane_preference": "MOMENTUM",  ← Social signals                      │  │  │
│   │  │    "analysis_mode": "quick",       ← Fast turnaround                     │  │  │
│   │  │    "note": "Analyst:@microcap_mike | Quality:81 | Sentiment:BULLISH"     │  │  │
│   │  │  }                                                                       │  │  │
│   │  │                                                                          │  │  │
│   │  │  Lane Assignment:                                                        │  │  │
│   │  │  • CORE → High quality (80+), long-term                                  │  │  │
│   │  │  • MOMENTUM → Social signals, short-term                                 │  │  │
│   │  │                                                                          │  │  │
│   │  │  Mode Assignment:                                                        │  │  │
│   │  │  • deep → A-tier analysts, thorough research                             │  │  │
│   │  │  • quick → B/C-tier, faster turnaround                                   │  │  │
│   │  └─────────────────────────────────────────────────────────────────────────┘  │  │
│   │                                    │                                           │  │
│   │                                    ▼                                           │  │
│   │  ┌─────────────────────────────────────────────────────────────────────────┐  │  │
│   │  │         TRADINGAGENTS GRAPH                                              │  │  │
│   │  │                                                                          │  │  │
│   │  │  Multi-Agent Research Pipeline:                                          │  │  │
│   │  │  ├─ Market Analyst      → Technical analysis                            │  │  │
│   │  │  ├─ Bull Researcher     → Bull case                                     │  │  │
│   │  │  ├─ Bear Researcher     → Bear case                                     │  │  │
│   │  │  ├─ Debate Panel        → Bull vs Bear                                  │  │  │
│   │  │  ├─ Risk Manager        → Risk assessment                               │  │  │
│   │  │  └─ Trader              → Final decision                                │  │  │
│   │  │                                                                          │  │  │
│   │  │  Output: Aeternus Score (0-100) + Rating + Thesis                       │  │  │
│   │  └─────────────────────────────────────────────────────────────────────────┘  │  │
│   └────────────────────────────────┼───────────────────────────────────────────────┘  │
│                                    │                                                  │
│                                    ▼                                                  │
│   ┌───────────────────────────────────────────────────────────────────────────────┐  │
│   │                   REPORTING LAYER (Insights & Validation)                      │  │
│   ├───────────────────────────────────────────────────────────────────────────────┤  │
│   │                                                                                │  │
│   │  ┌─────────────────────────────────────────────────────────────────────────┐  │  │
│   │  │         ANALYST DISCOVERY REPORT                                         │  │  │
│   │  │    scripts/analyst_discovery_report.py                                   │  │  │
│   │  │                                                                          │  │  │
│   │  │  Generates:                                                              │  │  │
│   │  │  • Executive Summary (stats, tiers, tickers)                            │  │  │
│   │  │  • Analyst Leaderboard (quality rankings)                               │  │  │
│   │  │  • Ticker Coverage (consensus by ticker)                                │  │  │
│   │  │  • Analyst Research Highlights (deep profiles)                          │  │  │
│   │  │  • Key Insights (hidden gems, opportunities)                            │  │  │
│   │  │  • Action Items (promote, monitor, validate)                            │  │  │
│   │  │                                                                          │  │  │
│   │  │  Usage:                                                                  │  │  │
│   │  │  python analyst_discovery_report.py generate --output report.md         │  │  │
│   │  │  python analyst_discovery_report.py consensus --ticker NVDA             │  │  │
│   │  │  python analyst_discovery_report.py leaderboard --tier C                │  │  │
│   │  └─────────────────────────────────────────────────────────────────────────┘  │  │
│   │                                    │                                           │  │
│   │                                    ▼                                           │  │
│   │  ┌─────────────────────────────────────────────────────────────────────────┐  │  │
│   │  │         VALIDATION & FEEDBACK LOOP                                       │  │  │
│   │  │                                                                          │  │  │
│   │  │  Track:                                                                  │  │  │
│   │  │  • Did the analyst's prediction come true?                              │  │  │
│   │  │  • What was the actual return?                                          │  │  │
│   │  │  • Update prediction_accuracy score                                     │  │  │
│   │  │  • Adjust quality scores based on outcomes                              │  │  │
│   │  │  • Promote/demote analysts dynamically                                  │  │  │
│   │  │                                                                          │  │  │
│   │  │  Result: Self-improving analyst curation                                │  │  │
│   │  └─────────────────────────────────────────────────────────────────────────┘  │  │
│   └───────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                      │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## 🔄 Complete Workflow

### **Phase 1: Discovery** (Daily/Weekly)
```
Watchlist → Bird Scraper → xAI Quality Scorer → Analyst Database
     ↓
Input: List of handles (fintwit.txt)
Process: Scrape posts → Score quality → Filter spam
Output: New analysts with quality scores
```

### **Phase 2: Tracking** (Continuous)
```
Analyst Database → Social Deal Flow → Quality Updates → Tier Adjustments
        ↓
Every 15 minutes:
- Scrape promoted analysts
- Extract tickers
- Update quality scores
- Recalculate tiers
```

### **Phase 3: Promotion** (On-demand)
```
Analyst Leaderboard → Manual Review → Promote to Deal Flow → Curated Watchlist
        ↓
Criteria:
- Quality score >= 75
- Consistency >= 70
- Minimum 3 posts tracked
```

### **Phase 4: Signal Generation** (Continuous)
```
Curated Analysts → Social Deal Flow → DealFlowSignal → TradingAgents
        ↓
For each post:
- Extract tickers
- Analyze sentiment
- Score quality
- Submit to /ops/adhoc/research
```

### **Phase 5: Research** (Per request)
```
DealFlowSignal → Operator Gateway → TradingAgents Graph → Research Output
        ↓
Lane: MOMENTUM (social signals)
Mode: quick (fast turnaround)
Result: Aeternus Score + Rating
```

### **Phase 6: Validation** (Weekly)
```
Research Results → Price Action → Update Analyst Accuracy → Adjust Scores
        ↓
Track:
- Prediction accuracy
- Actual returns
- Quality score adjustments
- Tier promotions/demotions
```

## 📊 Data Flow

```
┌────────────────────────────────────────────────────────────────────────────┐
│                            DATA FLOW                                        │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  INPUT                    PROCESSING              OUTPUT                    │
│  ─────                    ──────────              ──────                    │
│                                                                             │
│  @handle tweets    →   Bird scrapes        →   Raw text                     │
│  Raw text          →   xAI quality scorer  →   Quality score (0-100)       │
│  Quality score     →   Spam filter         →   Pass/Fail                    │
│  Pass              →   Analyst discovery   →   Analyst profile              │
│  Analyst profile   →   Track over time     →   Tier assignment (A/B/C/D)   │
│  Tier B+           →   Promote             →   Curated watchlist           │
│  Curated analyst   →   Social deal flow    →   Ticker mentions             │
│  Ticker mentions   →   Deal flow source    →   DealFlowSignal              │
│  DealFlowSignal    →   Operator gateway    →   POST /ops/adhoc/research    │
│  Research POST     →   TradingAgents       →   Aeternus Score              │
│  Aeternus Score    →   Price tracking      →   Validation                  │
│  Validation        →   Accuracy update     →   Analyst score adjustment    │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

## 🎯 Key Innovations

### **1. The Analyst IS the Product**
Instead of extracting tickers from random posts, we:
- Track analysts over time
- Build their track records
- Curate a portfolio of minds
- Get early access to their best ideas

### **2. Engagement Velocity > Absolute Engagement**
Instead of 2500 likes = good, we use:
- 45 likes / 850 followers = 5.3% engagement rate = HIGH quality
- Relative engagement surfaces hidden gems
- Quality content rises regardless of follower count

### **3. Multi-Dimensional Scoring**
Instead of binary good/bad, we score:
- Actionability (30%) - Can you act on this?
- Risk Awareness (25%) - Does it acknowledge downside?
- Evidence Quality (25%) - Data > opinion
- Engagement Velocity (15%) - Discussion depth
- Originality (5%) - Contrarian bonus

### **4. Self-Improving System**
- Discovers analysts automatically
- Tracks prediction accuracy
- Adjusts quality scores based on outcomes
- Promotes/demotes dynamically
- Builds curated "alpha feed"

## 📈 Performance Metrics

**Current System Status:**
- Analysts Tracked: 12
- Promoted to Deal Flow: 5
- Hidden Gems Discovered: 2
- Tickers Covered: 47
- Signals Generated Today: 23
- Avg Analyst Quality: 72/100

**Quality Distribution:**
- Elite (90+): 2 analysts
- High (80-89): 2 analysts
- Good (70-79): 4 analysts
- Average (60-69): 2 analysts
- Below threshold (<60): 2 analysts

## 🚀 Usage Examples

### **Daily Workflow:**
```bash
# Morning: Check analyst leaderboard
python scripts/analyst_discovery_report.py leaderboard

# Midday: Run deal flow cycle
python scripts/integration_workflow.py full-cycle --no-dry-run

# Evening: Generate report
python scripts/analyst_discovery_report.py generate
```

### **Weekly Workflow:**
```bash
# Monday: Discover new analysts
python scripts/analyst_discovery_engine.py scan --watchlist fintwit.txt

# Wednesday: Promote qualified analysts
python scripts/analyst_discovery_engine.py promote @handle

# Friday: Review and export
python scripts/analyst_discovery_report.py export --format json
```

## 🎨 Design Principles Applied

### **Elon (First Principles)**
> "The question isn't 'Is this stock good?' The question is 'Is this person worth following for the next 1000 posts?'"

- Track analysts, not just tickers
- Build edge factories
- Quality over popularity

### **Steve (Simplicity)**
> "The analyst is the product. Everything else is just a feature."

- Clear tier badges: ✓ Trusted, ● Verified, 🌱 Emerging
- No complex numbers for users
- Focus on the mind

### **Jony (Minimalism)**
> "Remove everything except the signal. The analyst IS the signal."

- Spam filtered before scoring
- Low-quality rejected
- Only best promoted

---

## 📁 Complete File Structure

```
scripts/
├── analyst_discovery_engine.py      # Main analyst discovery CLI
├── xai_quality_scorer_v2.py         # Quality scoring with hidden gems
├── social_dealflow.py               # Continuous monitoring
├── deal_source.py                   # Bird scraping CLI
├── analyst_discovery_report.py      # Report generation
└── integration_workflow.py          # Pipeline orchestration

tradingagents/dealflow/sources/
├── analyst_discovery.py             # TradingAgents source adapter
├── __init__.py                      # Updated exports
└── [existing sources...]

data/
├── analyst_discovery_data/          # Analyst profiles
│   ├── analyst_index.json
│   └── analysts/
│       ├── @charliebilello.json
│       ├── @microcap_mike.json
│       └── ...
├── social_dealflow_data/            # Watchlists & state
└── deal_source_watches/             # Monitoring output

reports/
└── analyst_discovery_report_SAMPLE.md  # Example output
```

---

## ✨ What This Enables

1. **Early Access:** Find great analysts before the crowd
2. **Quality Curation:** Automatic spam filtering
3. **Edge Factory:** Each analyst = ongoing alpha
4. **Diversity:** Mix of technical, fundamental, macro
5. **Validation:** Track record proves quality
6. **Integration:** Feeds TradingAgents automatically
7. **Reporting:** Comprehensive insights

---

**The future of investment research isn't finding stocks. It's finding the right people to learn from.**

*Built with ❤️ using xAI principles + Elon/Steve/Jony philosophy*
