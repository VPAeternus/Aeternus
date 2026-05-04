# Aeternus — Investment Strategy & Business Plan

*A self-running investment firm powered by sovereign AI agents.*

---

## 1. Mission

Build the first fully autonomous AI hedge fund that researches, debates, decides, executes, and monitors continuously — generating verifiable alpha at institutional scale while publishing its reasoning transparently to build the most trusted investment process in existence.

This is not a prop shop. This is an investment firm.

---

## 2. The Competitive Opening

The firms managing trillions — BlackRock, Vanguard, Two Sigma, D.E. Shaw, Citadel — are built on factor models, statistical arbitrage, and armies of PhDs. They are not using SOTA LLM reasoning with structured debate and coherence analysis. They are playing an old game with old tools.

**The window where AI-native investment management has a genuine, compounding edge over traditional quant is right now.** Models are improving faster than quant shops can adapt. We are building in that window.

| Traditional Quant | Human Social PM | Aeternus |
|---|---|---|
| Factor models, backtested signals | Manual trades, intuition-driven | LLM-structured bull/bear debate + coherence synthesis |
| Black-box decisions | Emotional, inconsistent | Every decision documented, attributed, auditable |
| Human analysts with cognitive limits | One person's bandwidth | Agents that never sleep, never tire, never anchor |
| Signals refresh daily at best | Reacts to news manually | Intraday risk sentinel watches for macro shocks |
| Silent, invisible | Builds audience through personality | Builds audience through verifiable process |

The moat is not any single algorithm. The moat is the **reasoning layer** — how SOTA LLMs interpret, critique, and synthesize financial data in a structured debate architecture that no traditional quant shop replicates.

---

## 3. Total Addressable Market

### TAM: Global Asset Management — $120T+ AUM

The global asset management industry manages over $120 trillion. Active management (non-index) is approximately $60T, of which quantitative and systematic strategies represent $3-5T and growing at 15%+ annually.

### SAM: AI-Native Systematic Strategies — $500B

Emerging managers using AI/ML approaches, alternative data, and systematic strategies. This segment is growing fastest as institutional allocators seek uncorrelated alpha sources. Family offices ($6T+ globally) are the earliest adopters of novel strategies.

### SOM: Year 1-3 Realistic Target — $5-50M AUM

- **Year 1:** $25-100K personal capital + subscription revenue
- **Year 2:** $500K-2M (personal capital growth + first external allocators from subscriber base)
- **Year 3:** $5-50M (seed allocation from family office or fund-of-funds, subscriber conversions)

### The FICO Precedent

FICO scores rate 90%+ of US consumer credit decisions. A single algorithmic system that institutions trust because it is consistent, auditable, and backtested over decades. Aeternus Score aims to become the FICO of equity investment ratings — a transparent, reproducible scoring system that institutions reference because the methodology is open and the track record is public.

---

## 4. The Publisher's Exclusion

**Publish the process. Never the portfolio.**

There is a critical legal and strategic distinction: publishing investment *research and analysis* (ratings, score breakdowns, reasoning) is protected speech under the publisher's exclusion from investment adviser registration. Publishing *specific portfolio allocations with instructions to follow* crosses into advisory territory.

Aeternus publishes:
- Individual stock ratings with full reasoning chains
- Score breakdowns across 5 pillars
- Bull/bear debate transcripts
- Conviction levels and uncertainty
- Track record statistics (after the fact)

Aeternus does NOT publish:
- Specific portfolio weights or position sizes
- "Buy X shares at Y price" instructions
- Real-time entry/exit signals for subscribers to copy-trade

This distinction allows us to build audience and credibility without triggering registration requirements until we are ready for a formal fund structure.

---

## 5. Business Model — Four Revenue Tiers

### Tier 1: Subscription Float (Month 1+)

Monthly subscription for access to published analysis, ratings, and track record dashboard.

| Metric | Conservative | Base | Optimistic |
|--------|-------------|------|-----------|
| Subscribers (Year 1) | 200 | 500 | 2,000 |
| Price/month | $25 | $29 | $29 |
| Annual MRR | $60K | $174K | $696K |

**The float is the key insight.** A fund manager charging 1.5% on AUM needs $10M to generate $150K in management fees. A subscription portfolio needs 500 subscribers at $29/month to generate the same. And those subscribers are a pre-qualified investor pipeline.

### Tier 2: Institutional API (Year 2+)

Aeternus Score as a service — institutional clients query ratings programmatically.

- Per-query pricing: $0.50-2.00 per ticker rating
- Monthly seat licensing for unlimited queries: $500-2,000/month
- Initial market: RIAs, family offices, alternative data consumers

### Tier 3: Fund Management (Year 2-3+)

Traditional 2/20 (or 1.5/15) fund structure.

- LP/GP structure, RIA or exempt reporting adviser registration
- Seed from subscriber-to-investor pipeline (warm, not cold)
- Track record is public and timestamped — more credible than a private PDF

### Tier 4: Licensing & White-Label (Year 3+)

License the scoring methodology and agent architecture to other firms.

- Technology licensing for the multi-agent debate framework
- White-label scoring for broker-dealers or wealth platforms
- Not a priority until the track record validates the approach

---

## 6. Investment Philosophy

### Core Principles

**This is an investment firm, not a prop shop.**

1. **No arbitrary stop losses, trailing stops, or take profits.** We hedge. We already have a proven hedging strategy (Wyckoff phase engine + regime overlay). Panic selling on a percentage is amateur hour.

2. **Exit when the ANALYSIS says to exit.** Thesis invalidation. Conviction decay. Score deterioration. Regime shift. Not because some number was hit.

3. **Position sizing by conviction.** Concentration wins. Buffett's top 5 holdings are ~70% of Berkshire. Nobody made asymmetric returns through diversification. If the analysis says BUY with 5/5 conviction, size it.

4. **Hold as long as the thesis is valid.** Could be 5 days, could be 5 months. The re-analysis engine reviews positions periodically and exits when the score deteriorates.

5. **Paper trading first.** At least 1 month of real analysis cycles before any live capital. Then live.

### Risk Management Stack

Instead of arbitrary stops, our risk management is a 5-layer stack:

| Layer | Mechanism | What It Does |
|-------|-----------|-------------|
| 1. Regime Overlay | Hedging engine (VIX/SPY/regime classification) | Deploys index hedges automatically during stress |
| 2. Thesis Invalidation | Price-based conditions from analysis | Exits when price crosses analyst-defined invalidation levels |
| 3. Conviction Decay | Exponential decay over holding period | Exits when original conviction decays below threshold |
| 4. Score Deterioration | Re-analysis engine (periodic score refresh) | Exits when score drops below threshold or flips direction |
| 5. Index Overlay | v3 VIX system | Removes positions when market structure breaks |

### Position Sizing Configuration

| Setting | Value | Rationale |
|---------|-------|-----------|
| Max weight per position | 40% | Buffett concentrates. High-conviction positions earn asymmetric returns. |
| Stop loss | 0% (disabled) | Hedging engine protects at portfolio level. Individual names held on thesis. |
| Take profit | 0% (disabled) | Don't sell winners because they hit a number. Re-analysis engine handles thesis exhaustion. |
| Trailing stop | 0% (disabled) | Portfolio-level hedge overlay protects gains, not position-level stops. |
| Max hold days | 0 (disabled) | Hold as long as thesis is valid. Re-analysis reviews periodically. |
| Gross exposure | 100% | Full deployment. Cash is a position only when conviction is absent. |
| Hedge shorts | Allowed | Wyckoff phase engine + VIX system manage portfolio protection via index hedges. |

---

## 7. Technology Foundation

### Scoring Engine — 5 Pillars, Regime-Adaptive

| Pillar | Weight (Neutral) | What It Measures |
|--------|-------------------|-----------------|
| Fundamental | 30% | Financial ratios, F-Score, earnings quality, valuation |
| Coherence | 25% | Cross-pillar agreement, bull/bear debate synthesis, epistemic confidence |
| Macro | 20% | FRED data, yield curve, regime classification, sector rotation |
| Sentiment | 15% | News sentiment, social sentiment, Alpha Vantage + Google blend |
| Momentum | 10% | Price momentum, volume, RSI/MACD, trend strength |

Weights shift with market regime (CRASH, BEAR_STRESS, VOLATILITY_SHOCK, etc.). Fundamental weight increases in BEAR regimes; Momentum weight increases in NEUTRAL/EUPHORIA.

### Agent Architecture

```
Data Gathering → 4 Analyst Tracks (parallel: fundamentals, technical, sentiment, news)
  → 4 Deep-Thinking Reviewers (critique each analyst's work)
  → 2 Researchers (structured bull vs bear debate, multi-round)
  → Trader (verdict with scenarios, invalidation conditions, conviction)
  → Risk Debate (3 perspectives: aggressive, conservative, balanced)
  → Portfolio Manager (position sizing, exit enforcement)
```

Every agent output is documented in the analysis report. Every debate round is preserved. Every dissent is logged. This creates the audit trail that becomes publishable content at zero marginal cost.

### Knowledge Graph — The Universe Brain

A 3,000+ node directed weighted graph (AKG) that stores derived intelligence:

- **Company nodes** with emergence tiers: DARK → ROCKY → ATMOSPHERE → HABITABLE → SCORED
- **Sector and theme nodes** with activation weights
- **Supply chain edges** from SEC filings (8-K, Form 4)
- **Hebbian learning**: outcome weights adjust edge strengths based on realized P&L
- **Emergence scoring**: centrality (40%) + velocity (40%) + sentiment (20%)

The AKG is the single source of truth for the investment universe. Writers (scheduled) write to AKG. The pipeline reads for free. This separates API cost from pipeline latency.

### Execution Infrastructure

- **Broker-agnostic adapter pattern**: paper, alpaca-paper, alpaca-live modes
- **7 pre-trade risk gates**: exposure limits, position count, short blocking, hedge caps, position parity
- **Order deduplication**: client_order_id prevents double-sends
- **Reconciliation daemon**: continuous broker sync, fill matching, P&L alerting
- **Market hours gate**: blocks orders outside RTH

### Hedging Engine

- **Regime classification**: 8 states (CRASH through EUPHORIA) based on VIX, SPY, yield curve
- **Wyckoff phase overlay**: short overlay on QQQ/SPY when distribution phases detected
- **v3 VIX system**: manages index exposure based on volatility regime
- **Priority rule**: hedge closes long before opening short; never long + short same name simultaneously

---

## 8. Go-to-Market Strategy

### Phase 1: Build the Record (Month 1-3)

- Paper trading with real analysis cycles (daily: source → analyze → plan → execute)
- Generate track record dashboard from paper results
- Generate content for every analysis (zero additional cost — template assembly)
- User reviews and posts manually on X
- Build initial audience through authentic, detailed analysis posts

### Phase 2: Go Live (Month 3-6)

- Switch from paper to live (single env var change)
- Continue publishing analysis posts after fills
- Launch subscription tier (Savvy Trader, Autopilot, or direct)
- Track record dashboard updated automatically

### Phase 3: Scale Audience (Month 6-18)

- 500+ subscribers → operating costs covered by subscription float
- Consistent posting cadence: hook + analysis + full article per rated ticker
- Track record builds credibility week over week
- Identify accredited investors in subscriber base

### Phase 4: First External Capital (Year 2-3)

- 12-18 months of live, public, timestamped track record
- Subscriber-to-investor outreach (warm, not cold)
- RIA registration or exempt reporting adviser status
- LP/GP fund structure
- Seed from family office, fund-of-funds, or sophisticated angels

---

## 9. Financial Projections

### Operating Costs (Monthly)

| Item | Cost | Notes |
|------|------|-------|
| LLM API (analysis) | $50-150 | ~$0.05-0.15/ticker, 20-30 tickers/month |
| Market data (Alpha Vantage) | $0 | Free tier sufficient for current volume |
| Alpaca brokerage | $0 | Commission-free |
| xAI (deal flow enrichment) | $5-15 | Budget-gated, disabled by default |
| Infrastructure (server) | $0-50 | Runs on local machine initially |
| **Total** | **$55-215/month** | |

### Revenue Scenarios (Year 1)

| Scenario | Subscribers | MRR | Annual | Note |
|----------|-----------|-----|--------|------|
| Conservative | 100 | $2,500 | $30K | Covers ops + small capital growth |
| Base | 500 | $14,500 | $174K | Meaningful operating float |
| Optimistic | 2,000 | $58,000 | $696K | Significant capital for live trading |

### Capital Growth (3-Year Model, Base Case)

| Year | Starting Capital | Subscription Revenue | Trading Returns (est. 15% annual) | Ending Capital |
|------|-----------------|---------------------|----------------------------------|---------------|
| 1 | $50,000 | $100,000 | $7,500 | $157,500 |
| 2 | $157,500 | $200,000 | $23,625 | $381,125 |
| 3 | $381,125 | $300,000 | $57,169 | $738,294 |

*Trading returns are illustrative only. Actual returns depend on market conditions and system performance.*

---

## 10. Risk Factors

### Technology Risks

- **Model degradation**: LLM capabilities may plateau or regress in future versions. Mitigation: scoring engine is model-agnostic; swap providers without architectural changes.
- **API dependency**: Reliance on third-party LLM and data APIs. Mitigation: multi-provider support, graceful fallback, local model option (Ollama).
- **Latency**: LLM inference adds latency to execution. Mitigation: we trade daily signals, not HFT. Seconds of latency are irrelevant.

### Market Risks

- **Drawdown**: Extended drawdowns erode capital and subscriber confidence. Mitigation: hedging engine, thesis-driven exits, risk circuit breakers (max daily loss, NLV floor, max drawdown).
- **Regime change**: Unprecedented market regimes may invalidate scoring models. Mitigation: regime-adaptive weights, hedging engine, human override via operator gateway.
- **Liquidity**: Small-cap positions may have adverse fill quality. Mitigation: minimum ADV filter ($50M) in deal flow pipeline.

### Business Risks

- **Regulatory**: Publishing analysis may attract regulatory scrutiny. Mitigation: publisher's exclusion, clear disclaimers, no copy-trade instructions.
- **Competition**: Other AI-native funds entering the space. Mitigation: first-mover advantage in transparent, verifiable AI investing. Track record compounds.
- **Key person**: Single operator risk. Mitigation: system is designed to run autonomously; operator reviews and overrides, not operates.

---

## 11. Competitive Advantages

1. **Reasoning as content**: Every trade decision generates publishable analysis at zero marginal cost. No human PM can produce this consistently.

2. **Transparency as trust**: Public track record with full reasoning chains. Allocators can verify methodology independently. No black box.

3. **Compounding flywheel**: Better analysis → better returns → more subscribers → more capital → better data → better analysis. Both the track record and the audience compound simultaneously.

4. **Cost structure**: Near-zero marginal cost per additional subscriber. Near-zero marginal cost per additional analysis. Traditional firms scale linearly with headcount.

5. **Speed to adapt**: New LLM models integrate in days, not quarters. Model-agnostic architecture means we ride every capability improvement immediately.

6. **Subscriber-to-investor pipeline**: 10,000 engaged subscribers who've watched 18 months of decisions = a warm investor outreach list that no placement agent can match.

---

## 12. What We Will NOT Do

- **Pivot to a general-purpose agent framework** — our moat is financial alpha, not developer tools
- **Chase features without a verified track record** — paper trading proves nothing to allocators
- **Publish before we are live** — content built on paper results is a credibility liability
- **Optimize content for engagement over authenticity** — hot takes build followers who churn; detailed reasoning builds investors who stay
- **Sanitize the reasoning** — uncertainty, debate, and close calls are the product, not a weakness to hide
- **Auto-publish without review** — user reviews and posts manually until trust in content pipeline is established
- **Trade intraday for alpha** — intraday monitoring is for risk only; signals are daily
- **Over-diversify** — concentration in high-conviction names is how asymmetric returns are made

---

## Summary

Aeternus combines three structural advantages no competitor replicates simultaneously:

1. **SOTA LLM reasoning** in a structured debate architecture that produces genuine analytical edge
2. **Radical transparency** that converts every decision into audience-building content at zero marginal cost
3. **A dual-track business model** where subscription float funds operations while the track record compounds toward institutional scale

The path from $50K personal capital to managing institutional money is shorter when you have 10,000 subscribers who've watched every decision for 18 months — and when every decision is documented, auditable, and timestamped.

---

*This document is a living strategy. Updated as the system, track record, and market conditions evolve.*

*Not financial advice. Not a solicitation. Not an offer to invest.*
