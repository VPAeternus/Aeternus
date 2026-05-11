# MiroFish Audit -> Aeternus Scout Compiler + Scenario Retriever

Date: 2026-03-15

## Purpose

This memo captures the full substance of the design conversation around:

- what MiroFish actually does well
- where Aeternus is already stronger
- what exact missing layer sits between Aeternus scouts and a future scenario runtime
- why the first missing component is a `Scout Compiler`
- why the second missing component is a separate `Scenario Retriever`

This document is intentionally conversation-heavy. It is meant to preserve the reasoning, not just the conclusions.

## Core Conclusion

The right framing is not:

- "Aeternus should become MiroFish"

The right framing is:

- Aeternus already has stronger ambient sensing, richer market-specific data collection, stronger durable memory, and stronger learning loops
- MiroFish is ahead on question-conditioned compilation into a runnable scenario world
- the missing Aeternus layer is a compiler/runtime bridge between scouts and scenario answers

In short:

- MiroFish has a compiler from language -> social runtime
- Aeternus needs a compiler from language -> market runtime

## What MiroFish Actually Is

The open-source repo does not appear to maintain a giant all-world persistent knowledge graph or dispatch broad scouts based on a question.

Instead, it behaves like a compiler pipeline:

1. user provides files plus `simulation_requirement`
2. files are turned into text
3. text plus requirement are turned into an ontology
4. ontology plus text are turned into a graph in Zep
5. filtered graph entities are turned into actor profiles
6. the question is compiled into runtime config and seed events
7. OASIS runs the simulation
8. actions are written back into graph memory
9. query/report tools explain the resulting world

Important implication:

- MiroFish assumes the relevant evidence packet is already handed to it
- it is not, in the OSS repo, an always-on market scout fabric

## The First Big Correction

The initial risk was understating MiroFish as "just scenario generation" and overstating Aeternus as "already better."

The corrected understanding is:

- MiroFish's real strength is not just simulation output
- its real strength is compiling `data + question` into a temporary, queryable runtime world

That is exactly the layer Aeternus does not yet have.

## Aeternus Strengths vs MiroFish Strengths

### Aeternus is stronger at:

- ambient data collection through scouts and collectors
- market-specific source coverage
- durable AKG memory
- portfolio, candidate_list, and execution context
- diagnostics like `why_missed`
- learning loops, hindsight, source attribution, and signal-family IC

### MiroFish is stronger at:

- question-conditioned compilation
- converting unstructured evidence into a temporary world schema
- turning graph entities into runtime participants
- seeding a scenario runtime from a specific question
- answering over the post-simulation world

## MiroFish Components That Matter Most

### 1. Ontology compile

MiroFish forces structure early.

It does not simulate raw documents.

It first decides:

- what entity types matter
- what relationship types matter
- what should survive into the runtime

Lesson for Aeternus:

- we need a scenario-conditioned runtime schema, not just a durable graph

### 2. Entity filter

MiroFish filters graph outputs down to ontology-matching entities before actor generation.

Lesson for Aeternus:

- not all AKG nodes should matter for every scenario
- a scenario-local relevance filter is required

### 3. Actor compiler

MiroFish does not simulate raw nodes. It compiles them into runtime actors with memory and behavior.

Lesson for Aeternus:

- we need market actors, not just stored nodes

### 4. Event compiler

MiroFish turns the user's question into hot topics, seeded events, and runtime configuration.

Lesson for Aeternus:

- we need freeform question -> structured market shock compilation

### 5. Writeback + queryability

MiroFish closes the loop by updating graph memory and then querying the updated world.

Lesson for Aeternus:

- scenario outputs should become memory, but only after being separated into durable facts vs temporary hypotheses

## Aeternus-First Mapping

The conversation intentionally flipped the direction of comparison.

The right question became:

- "How do Aeternus components map into the roles MiroFish performs?"

### Level 1: Question / requirement capture

Current Aeternus status:

- missing as a first-class scenario object

We can run the pipeline, and we can run `why_missed`, but we do not yet have a durable structure for:

- scenario question
- requested answer type
- required coverage dimensions
- missing coverage state

### Level 2: Evidence packet

Current Aeternus status:

- partial

We have rich evidence, but it is fragmented:

- scouts
- collector artifacts
- macro cache
- x-feed
- SEC caches
- AKG

We do not yet create one daily evidence packet or question-specific evidence packet.

### Level 3: Ontology / runtime schema

Current Aeternus status:

- partial

AKG has a durable schema, but not a question-conditioned runtime schema.

### Level 4: Durable world memory

Current Aeternus status:

- strong

AKG already fills this role.

### Level 5: Relevance filtering

Current Aeternus status:

- partial

We filter for universe / liquidity / technical conditions, but not yet for scenario-local relevance.

### Level 6: Actor compiler

Current Aeternus status:

- missing

We do not yet compile AKG nodes into market-native runtime actors.

### Level 7: Shock compiler

Current Aeternus status:

- partial

We have fixed shock logic in a few places, but not freeform question -> structured shock compilation.

### Level 8: Runtime

Current Aeternus status:

- partial

We have per-ticker research runtime and some stress/scenario logic, but not a multi-entity scenario runtime.

### Level 9: Memory writeback

Current Aeternus status:

- partial to strong

We already write back signals and observed edges, but not scenario-specific outputs.

### Level 10: Query / explanation

Current Aeternus status:

- partial

We have analysis and diagnostics, but not a first-class scenario query layer.

### Level 11: Learning

Current Aeternus status:

- strong

This is one place where Aeternus is already ahead of MiroFish.

## The First Pipeline Stage To Improve: Scouts

The conversation then narrowed to the first concrete step:

- Aeternus step 1 is `Scouts`
- how should scouts be improved with MiroFish functionality?

The key answer:

- scouts are not the problem
- scout compilation is the problem

Scouts today are strong at:

- sensing
- surfacing symbols
- preserving provenance
- giving us recall

Scouts today are weak at:

- merging evidence across scout families
- turning text into structured events
- turning text into reusable scenario seeds
- extracting second-order implications

## The Missing Layer: Scout Compiler

The conversation converged on a new component:

- `Scout Compiler`

Placement:

- after scouts run
- before universe filtering and collectors

Job:

- merge scout evidence
- normalize entities
- extract events
- dedupe overlapping narratives
- emit scenario seeds
- enrich AKG with structured event objects

Critical constraint:

- it should not interfere with the existing pipeline

That led to the decision:

- `Pass 1` should be a shadow sidecar

Meaning:

- `discover` continues to behave the same
- the compiler runs alongside it
- the compiler writes artifacts and safe AKG enrichments
- no stage should depend on compiler outputs at first

## Event Card Output

A major refinement from the conversation:

- the compiler output should be turned into a daily `Event Card` JSON

Reason:

- later, an LLM can turn Event Cards into narrative investor-facing output
- those narratives can be pushed into investor docs
- the Event Card is the structured bridge between daily sensing and later narrative generation

So the daily run should not just create raw compiled events.

It should create durable, reusable daily event artifacts.

## Daily Scenario Principle

One of the strongest conclusions in the discussion:

- every daily run should become a daily scenario

This means:

- cross-scout relationships become a first-class artifact
- a merged multi-source event becomes a signal in itself
- the daily scenario layer can later feed both runtime and narrative generation

Example:

- X-feed says Iran escalation
- commodity shock scout says oil disruption cluster
- macro layer implies risk-off
- portfolio context shows airline or tech exposure

That combined object is more powerful than each scout on its own.

## Scout Compiler Contract (v1)

### Inputs

The compiler should consume existing scout/discovery outputs:

- manual X-feed merged payload
- breakout scout result
- insider sweep result
- technical ignition result
- earnings/options scout result
- FVG recall artifact
- FMA recall artifact
- optional AKG snapshot
- optional macro cache if available
- optional `question_context`

### Outputs

The compiler should write a durable artifact with:

- normalized entities
- extracted events
- consolidated narratives
- scenario seeds
- promoted symbols
- AKG writeback candidates
- warnings

### Scenario/Event objects should capture:

- event type
- direct entities
- second-order entities
- channels
- expected direction
- confidence
- urgency
- time horizon
- provenance

## AKG vs Temporary Runtime State

The conversation drew an important line.

Persist into AKG:

- durable facts
- durable normalized relations
- high-confidence event summaries

Keep temporary:

- scenario seeds
- urgency
- hedge suggestions
- question-specific relevance scoring
- speculative second-order paths
- unresolved hypotheses

Rule:

- durable facts go into AKG
- scenario hypotheses stay outside AKG until validated

## Should The Compiler Also Retrieve?

This became the next architecture decision.

Initial thought:

- maybe the compiler should retrieve from the universe too

Refined conclusion:

- the compiler should not own retrieval
- retrieval should be a separate lane

Recommended split:

- `Scout Compiler` = compiles what we already know
- `Scenario Retriever` = answers a specific question by searching internal state first

Reason:

- clean separation of responsibilities
- no hidden network/API side effects inside `discover`
- much easier to audit
- much safer for pipeline stability

## Scenario Retriever

The user requested:

- `Scenario Retriever` should exist from day 1
- it should be testable immediately
- it should help expose gaps early

This was accepted as a strong requirement.

Role of the retriever:

- search daily scenario packet
- search AKG
- search universe
- search portfolio
- search cached macro
- search cached SEC/news/x-feed artifacts
- determine whether current coverage is enough to answer the question

The retriever should then classify coverage as:

- `COMPLETE`
- `PARTIAL`
- `MISSING`

## Coverage States

The conversation explicitly flagged that these must be defined carefully.

Preliminary working definitions:

### `COMPLETE`

- all core entities in the question are resolved
- direct impact paths are found or explicitly ruled out
- the minimum required evidence dimensions are present
- no critical coverage dimension is missing

### `PARTIAL`

- some core entities are resolved
- some impact paths are found
- one or more required evidence dimensions are missing or stale
- the system can provide a provisional answer plus a clear gap list

### `MISSING`

- the main entities or event cannot be resolved confidently
- there is no meaningful internal evidence packet for the question
- the system should not attempt a confident answer

These are still design-level definitions and need to be finalized in implementation planning.

## Manual-Only Gap Fill

One of the most important user constraints:

- if the retriever flags a gap, it should **not** automatically go fetch external data

Instead, it should:

- list what it needs
- explain why the gap matters
- wait for user input

Reason:

- avoid wasting API spend
- let the user decide whether to upload free/manual evidence
- keep operator control over external retrieval

So the rule is:

- gap detection is automatic
- gap fill is user-mediated

This is a major operating principle and should remain explicit.

## What If The Scenario Is New And Scouts Have Not Covered It?

This was one of the strongest questions in the conversation.

Answer:

- Aeternus needs a hybrid model

### Lane 1: Ambient daily sensing

- daily scouts maintain the standing world-state

### Lane 2: Query-time retrieval / gap detection

- a user question may introduce a scenario that ambient scouts did not cover well
- retriever checks internal coverage
- if insufficient, retriever produces a gap report and waits for user

This is one place where Aeternus should intentionally go beyond MiroFish.

MiroFish assumes:

- the user already gave it the relevant evidence

Aeternus should be able to say:

- what we already know
- what we do not know
- what additional inputs are required

## Non-Interference Requirement

The user explicitly required:

- the new layer should not interfere with the pipeline at all

The recommended answer was:

- shadow-sidecar compiler in `Pass 1`
- no gating behavior
- no universe dependency yet
- no collector dependency yet

Only once outputs prove useful should anything downstream consume them.

## Conversation Summary In One Architecture

### Pass 1

- add `Scout Compiler`
- run it in shadow mode after scouts
- produce daily `Event Card` / scenario artifacts
- optionally add safe AKG enrichments
- do not change current pipeline behavior

### Pass 2

- add `Scenario Retriever`
- let it search internal state first
- classify coverage as `COMPLETE`, `PARTIAL`, or `MISSING`
- if coverage is insufficient, emit a gap request and wait for user

### Later

- scenario runtime
- narrative generation from Event Cards
- investor-doc publishing

## Direct Design Decisions Agreed In The Conversation

These were explicitly agreed:

- Aeternus needs MiroFish functionality, not MiroFish's entire architecture
- the first missing layer is `Scout Compiler`
- the compiler belongs after scouts and before universe filter / collectors
- the compiler should be a shadow sidecar first
- every run should become a daily scenario
- compiler output should become a daily `Event Card` JSON
- `Scenario Retriever` is needed from day 1
- `Scenario Retriever` should not auto-run external gap fill
- on gaps, the system should say what is missing and wait for user
- compiler and retriever should be separate lanes

## Open Design Work Remaining

- finalize the exact `Event Card` schema
- finalize `COMPLETE / PARTIAL / MISSING`
- define which AKG edge types are safe for compiler writeback
- define what counts as "minimum evidence dimensions" for a question
- define how question-specific retrieval ranks internal sources
- decide how Event Cards feed investor-doc generation

## Recommended Next Step

The next concrete design step should be:

- formalize `Scout Compiler v1`
- formalize `Scenario Retriever v1`
- save exact contracts, artifact names, and pipeline insertion points

That should happen before implementation begins.
