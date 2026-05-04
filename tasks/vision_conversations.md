# Aeternus — Strategic Vision Conversations

Rolling log of high-signal strategic discussions. Append-only. Never delete.

---

## 2026-02-28 — The Three-Company Frame + Zero-to-One

### Context
System had just gone live on Alpaca. AKG Universe Brain complete (S-037–S-051). Conversation shifted from execution to vision.

### The Perplexity + Rentech + Berkshire Frame

**User insight:** What we are building is a combination of Perplexity AI + Rentech + Berkshire Hathaway. Perplexity gives you the inside but there is no deal sourcing. There are recommendations for stocks but no moat, nothing proven. Rentech and Berkshire have no Agentic AIs. They are big ships with small rudder that take a long time to move.

**Synthesis:**

Each firm has a structural gap:

| Firm | What They Do | What Breaks Them |
|------|-------------|-----------------|
| Perplexity | Synthesizes information at machine speed | Doesn't act on it. No outcome memory. No thesis, sizing, or exit. |
| Rentech | Statistical pattern recognition at scale | Epistemically blind — can't reason WHY. Slow regime adaptation. AUM ceiling. Can't trade small-cap. |
| Berkshire | Genius-level fundamental conviction | Human bottleneck. Doesn't scale. Can't monitor 10,000 earnings calls. $800B AUM = can't move. |

**Aeternus inverts each weakness:**
- From Perplexity: real-time intelligence synthesis — but we *act* on it
- From Rentech: systematic, evidence-based — but we combine quant with LLM qualitative reasoning
- From Berkshire: thesis-driven conviction, structured debate — but we're fast and autonomous
- The new thing: **agentic** — learns from every outcome, updates signal weights, improves

**The moat:**
1. Outcome memory (AKG S-047 outcome weight feedback) — proprietary, compounds
2. Structured debate as signal (bull/bear coherence, dissent tracking) — process edge
3. Theme discovery before consensus (cluster detection → dark matter)
4. Small-cap access — the alpha Rentech and Citadel structurally cannot touch

**The "small rudder" advantage:** Large funds cannot move fast even if they want to. $100B in longs doesn't exit in a day. Every alpha dollar in the $1M–$50M range is alpha that large funds structurally cannot access. That long tail of small-cap alpha is permanently available to small, fast, systematic capital.

**The honest tension:** LLM reasoning is trained on historical text. In truly novel regimes with no historical precedent, both reasoning and signals could fail simultaneously. Mitigation already partially built: phase engine (Wyckoff, structural) + macro overlay (FRED, yield curve) as circuit breakers that fire before the model reasoning layer.

**Category name:** *Agentic Conviction Investing* — real-time intelligence + systematic process + machine speed, operating at a capital size that large funds cannot reach.

---

### The Zero-to-One: "What Must Be True" Engine

**The gap in all existing investment systems:** Every system ever built — Rentech, Berkshire, every quant fund, every analyst — operates the same way: *Start with a company. Research it. Form a thesis.* That's confirmation bias institutionalized. You picked the stock. Now you're rationalizing it.

**The zero-to-one question nobody has automated:**
> Start with a structural force. Derive which companies must exist, must grow, or must be acquired — before the market has named them.

**The Druckenmiller model:** He doesn't start with tickers. He starts with a view: "Interest rates are going to do X, which means Y breaks, which means Z sector gets destroyed, which means the survivors of Z get acquired by A, which makes A's suppliers B and C the quiet winners." That causal chain — from structural force to obscure supplier nobody covers — is where the alpha lives. He runs it in his head. Nobody has built a machine that runs it systematically.

**The key insight about the AKG:** The supply chain graph already exists. Cluster detection already finds rising nodes. But neither one asks the prior question: *What structural force CAUSED this cluster to form? And what's the next cluster that hasn't formed yet, because the force exists but the market hasn't traced it downstream?*

**The three outputs of the engine:**
1. **Causal Chain Map** — Force → Sector → Sub-sector → Companies, each link scored by causal necessity
2. **Discovery Score** — causal necessity × market ignorance × force acceleration rate
3. **The Dark Matter Portfolio** — companies structurally required by forces already in motion, currently invisible to institutional capital

**Why the moat is durable:** Information edges erode. Statistical edges erode. Sentiment edges erode. Causal reasoning from structural forces doesn't erode because the Structural Force Registry is *your* proprietary view of the world. Your causal chains are your intellectual property.

**Why nobody else can build it:** Requires macro-to-micro causal reasoning, not pattern matching. Rentech can't — bottom-up statistical. Berkshire does it in Buffett's head — doesn't scale. Perplexity can tell you the force exists — can't trace the causal chain to the instrument. Requires: LLM reasoning engine + supply chain graph + structured universe + hypothesis generation and challenge process. Aeternus has all four.

**Codebase audit result (2026-02-28):** Confirmed fully absent. Building blocks exist (theme nodes, macro_trigger fields, cluster detection, supply chain edges, macro_reviewer with Dalio framing) but none assembled into a top-down force → universe derivation system. Architecture is purely bottom-up. The "force → causal chain → dark matter beneficiaries" pattern is completely unbuilt.

**Task spec:** S-052 (to be written)

---

## Append new conversations below this line

---

## 2026-02-28 — S-053/054/055/056 Shipped

**S-053 Force Acceleration Tracker:** Weekly xAI grok-3-mini re-evaluation of each force's conviction/acceleration_rate. Keeps the registry alive. `effective_acceleration` + `effective_conviction` properties on StructuralForce — overrides without mutating the base definition. Gated: `akg_force_tracker_enabled=False`.

**S-054 Causal Chain Auto-Extension:** `propose_causal_extension(force_id)` — LLM proposes missing causal steps. Returns proposal dict only, does NOT write to registry. Human-in-the-loop approval required. CLI: `aeternus forces propose-extension <force_id>`. Printed with "PROPOSED — NOT YET ADDED" warning.

**S-055 Dark Matter → Perplexity Bridge:** `get_company_enrichment_dark_matter()` — enhanced sonar prompt with force context (necessity %, causal reasoning, supply chain role). Fires for dark matter candidates with `discovery_score > 0.75` that aren't yet enriched. Wired into `_maybe_run_perplexity_enricher()` scheduler method.

**S-056 Market Ignorance Enrichment (dispatched):** Replaces centrality proxy with real data: analyst coverage count (yfinance), institutional ownership % (yfinance), news velocity (AKG field). Formula: 0.50×analyst_ig + 0.35×inst_ig + 0.15×news_ig. 7-day cache on AKG node. `aeternus forces dark-matter --enrich` shows analyst_count + inst_pct columns.

**Total after S-053/054/055:** 30/30 structural force tests, 1444 total passing, zero regressions.

---

## 2026-02-28 — Epistemic Honesty: Where Does the Insight Come From?

**Context:** After dispatching S-052, Opus made a claim about which forces would produce the most interesting dark matter candidates. User asked where that insight came from.

**The exchange exposed an important principle:**

Opus stated: *"AI compute (InP substrates, CoWoS packaging), US-China decoupling (domestic RF, specialty gases, photomask), and nuclear renaissance (uranium enrichment, zirconium cladding) — sectors where the gap between causal necessity and market awareness is widest."*

**What was actually grounded in the system's data:**
- InP substrates (AXTI), silicon photonics (COHR, LITE) → already in AKG with NVDA supply_chain edges (read from viz JSON)
- Advanced packaging (ASX, AMKR) → in AKG with TSM/MU edges
- Nuclear names (BWXT, OKLO, NNE, LEU, UUUU) → seeded AKG nodes with supply chain edges

**What was LLM training knowledge, NOT data-derived:**
- "Specialty gases, photomask" for US-China decoupling
- "Zirconium cladding" for nuclear
- The institutional coverage claim ("almost no coverage") — no live market data, no analyst coverage ratios, no ownership percentages

**The principle established:** Claims about market ignorance, institutional coverage, or "widest gap" must come from the `market_ignorance_score` computation in the engine (AKG centrality + times_surfaced), NOT from LLM pattern-matching. The engine exists precisely to ground these intuitions in data.

**Design implication:** When `aeternus forces dark-matter` surfaces a candidate, the `market_ignorance_score` field IS the authoritative answer to "how blind is the market to this." That's computed, not opined. The LLM's role is causal chain reasoning — not coverage assessment.

---

## 2026-02-28 — S-052 Structural Force Engine: SHIPPED

**Status:** Done. 18/18 tests. 1,432 total passing. Zero regressions.

**What was built:**
- `tradingagents/graph/structural_forces.py` — StructuralForce + CausalStep + DarkMatterCandidate dataclasses
- 5 seed forces with full causal chains: ai_compute_demand, us_china_chip_decoupling, nuclear_renaissance, critical_minerals_onshoring, us_defense_rebuild
- `get_dark_matter_candidates()` on AeternusKG — deduplicates, sorts by discovery_score
- Pipeline integration (gated: structural_force_engine_enabled=False)
- `aeternus forces list / show / dark-matter` CLI

**Discovery score formula:** necessity × market_ignorance × acceleration_multiplier (1.25/1.0/0.75)

**Next three specs already written in S-052:**
- S-053: Force Acceleration Tracker — weekly LLM re-evaluation of conviction/acceleration_rate
- S-054: Causal Chain Auto-Extension — LLM proposes new causal steps, human approves
- S-055: Dark Matter → Perplexity Sonar Bridge — auto-enrich dark matter candidates with sonar when discovery_score > 0.75

---
