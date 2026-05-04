# Prompt Engineering Patterns

Reusable patterns for LLM prompts across the system — agent prompts, scout prompts, x-feed passes, diagnostic outputs.

## Sequential Diagnostic Protocol

**Pattern:** Structure multi-step LLM interactions as numbered rounds that progressively narrow the search space. Each round probes deeper than the last — surface → behavior → environment → belief → commitment.

**Why it works:** Prevents the model from dumping generic output. Each round constrains the next round's hypothesis space. The model synthesizes incrementally instead of guessing everything upfront.

**Application:** Any LLM call that needs to classify or diagnose — regime classification, position review, research debate. Instead of one prompt asking "analyze everything," use sequential passes where each pass builds on the prior.

**Example structure:**
1. Round 1: Establish baseline facts (what is the situation?)
2. Round 2: Audit behavior/output (what is actually happening vs expected?)
3. Round 3: Probe environment/context (what external factors are at play?)
4. Round 4: Surface hidden assumptions (what beliefs are driving the behavior?)
5. Transition rule: Between rounds, deliver one sharp observation before moving on

## Constraint Taxonomy with Signal Patterns

**Pattern:** Define named categories (3-6) with explicit signal lists that map observable evidence to a diagnosis. The model classifies into categories rather than generating freeform analysis.

**Why it works:** Converts open-ended generation into structured classification. The model's output becomes auditable — you can check whether the cited signals actually appeared in the input.

**Application:** Already used in regime classification (VOL_SHOCK, BEAR, RISK_OFF, etc.). Applicable to any diagnostic output: position health, signal quality assessment, data quality flags.

**Template:**
```
categories:
  - id: "C1"
    name: "Named Category"
    description: "What this means"
    signals: ["observable pattern 1", "observable pattern 2", "observable pattern 3"]
```

## Forbidden Behaviors List (Anti-Sycophancy)

**Pattern:** Explicitly list what the model must NOT do. More effective than positive instructions for preventing common LLM failure modes.

**Why it works:** LLMs default to agreeable, validating, generic output. Positive instructions ("be specific") are weaker than negative constraints ("never give generic advice not tied to the input data"). The model treats forbidden behaviors as hard boundaries.

**Key forbidden behaviors for our system:**
- Validating a signal without citing the source data
- Giving generic market commentary not specific to the ticker's actual situation
- Accepting vague inputs without pushing for specificity
- Moving forward without flagging contradictions in the input
- Producing a recommendation before the analysis is complete
- Softening a bearish conclusion because other signals are bullish

**Application:** Every agent prompt, every scout prompt, every x-feed pass. Add a `forbidden_behaviors` section.

## One Observation Between Rounds

**Pattern:** After each diagnostic round, force the model to deliver exactly one sharp observation (one sentence) before proceeding. No advice, no summary — just the single most important thing the current round revealed.

**Why it works:** Prevents information loss between rounds. Forces the model to synthesize incrementally instead of holding everything for a final dump. Also serves as a self-check — if the observation is generic, the round didn't probe deep enough.

**Application:** Multi-pass analysis (e.g., bull/bear debate rounds), position review sequences, any prompt chain where later steps build on earlier ones.

## Persona Theater vs Structural Engineering

**Lesson:** ~90% of prompt quality comes from structure (what questions to ask, in what order, with what constraints). ~10% comes from persona/tone instructions. Aggressive personas ("brutally honest," "zero tolerance") produce style without substance — the model says confrontational-sounding things regardless of accuracy.

**Rule for our system:** Never use persona instructions as a substitute for structural constraints. If you want the model to challenge weak evidence, don't say "be brutally honest" — say "if the bull case cites no specific data points, flag it as unsupported." Structure beats persona every time.
