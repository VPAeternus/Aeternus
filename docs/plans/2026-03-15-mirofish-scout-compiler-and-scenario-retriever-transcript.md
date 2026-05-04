# Reconstructed Transcript — MiroFish Audit -> Aeternus Scout Compiler + Scenario Retriever

Date: 2026-03-15

## Note

This is a reconstructed Q/A transcript of the architecture discussion from this session.

It is intended to preserve the substance and progression of the conversation in a readable form.

It is not a raw machine-exported transcript.

---

## Part 1 — Initial Positioning

**User**

Here is a recent article. This project immediately received 4.1m in funding. Are you telling me ours is better in some way and that we only need to use some parts of it? The claim is that it can literally predict anything.

**Assistant**

No, I would not say “ours is just better.” I would say it is better for a different job.

Based on the article, MiroFish looks strong at:

- scenario generation
- social / narrative simulation
- document-to-graph worldbuilding
- “what happens if X changes?” exploration

Aeternus is stronger at:

- verifiable scoring
- benchmarked decision quality
- portfolio gating
- execution / monitoring
- learning from actual outcomes

So the right takeaway is not “copy the whole thing.” The right takeaway is “use a MiroFish-like layer where simulation actually helps.”

---

## Part 2 — Scenario Simulation Is Not Optional

**User**

Yes i want you to do a concrete memo but one thing to consider: Scenario simulation is a critical piece to any investment. It happens every sec of every day. “QQQ close down 2% and VIX is up 20%, president just posted this, Apple announced this and that, etc.”

**Assistant**

Yes, and that changes the conclusion in an important way.

Scenario simulation is not optional for investing. It is central.

The right conclusion is:

- Aeternus needs a scenario engine.
- But it should not copy MiroFish wholesale.
- It should adopt the parts that improve investment decisions and reject the parts that are mostly theater.

The distinction became:

- MiroFish = scenario-generation engine
- Aeternus = decision-and-learning engine

And the right architecture became:

- `Scenario Engine` -> generates plausible market paths, reaction maps, and second-order beneficiaries
- `Aeternus` -> scores, ranks, gates, sizes, tracks, and learns

---

## Part 3 — User Pushback: AKG Is Already The Brain

**User**

This is very important and I think you just glossed over it:

“What MiroFish appears to do better

Turn unstructured documents into a simulation world quickly.
Model second-order reactions instead of only first-order facts.
Let operators inject shocks and watch cascade effects.
Treat narrative, coordination, and opinion dynamics as first-class.”

MiroFish can only do this and manage tens of thousands of agents and predict outcomes based on scenarios because it collected a LOT OF DATA. AKG is the brain in MiroFish but instead of waiting for a user to ask what will happen in this scenario, our scouts automatically do that. The only thing we are missing is a manual user input to ask questions scouts arent about to source. We also have a structure in place to answer “Why didnt we flag NVDA as a good investment?”

**Assistant**

You’re right. I glossed over the most important part.

The better framing is not:

- “MiroFish has simulation, we have scoring.”

It is:

- MiroFish has a queryable world model with a simulation runtime.
- Aeternus already has much of the world model and the sensing layer.
- What we’re missing is the runtime that turns AKG + scouts into forward scenario answers.

The revised view became:

- we already have the beginnings of the “brain”
- we already have the sensors
- we already have diagnosis and postmortems
- what we do not have is a first-class scenario runtime

The missing pieces were named as:

- scenario query interface
- shock compiler
- propagation engine over AKG
- market-actor layer
- stateful scenario memory
- scenario evaluation loop

---

## Part 4 — Audit MiroFish Directly

**User**

This looks like we are on the right track. But we need to make sure we dissect how MiroFish is actually doing all this one by one before we implement everything. I want to learn step by step on what is happening inside MiroFish. Here is the github: https://github.com/666ghj/MiroFish?tab=readme-ov-file. Audit and let’s start dissecting it.

**Assistant**

Yes. The right way to learn this is not “copy the impressive output,” but dissect the machine one layer at a time.

The first important correction from the repo itself was:

- in the open-source code, MiroFish does not appear to have some giant autonomous data-collection engine
- what it clearly has is:
  - user-provided seed material
  - LLM-generated ontology
  - Zep graph construction
  - LLM-generated agent profiles
  - OASIS simulation runtime
  - graph memory writeback
  - report/query layer

That led to the first strong conclusion:

- MiroFish is a compiler pipeline, not a single “predict anything” model

---

## Part 5 — Why MiroFish Is Ahead On Compilation

**User**

We need to understand this much better:

“What MiroFish does well here:

forces structure early
turns unstructured text into a runnable world
builds a bridge from document -> graph -> simulation”

because we have lots of unstructured data like SEC filing texts, macro news and texts, actual news, x posts, reddit, etc. I’m sure MiroFish is doing some of this already.

**Assistant**

Yes. And the repo makes this much clearer than the README does.

The important thing to understand is:

- MiroFish is not magic at source-specific understanding
- in the open-source repo it is doing something more general and more reusable:
  - it turns mixed text into a constrained simulation world

The pipeline was described as:

1. raw source files become one text corpus
2. that corpus is forced into a runtime ontology
3. the graph is built under that ontology
4. generic entities are filtered out
5. only then does it become a “world”

The strongest takeaway here was:

- Aeternus is already ahead on collection
- the missing piece is the compilation layer from collected evidence into runtime state

---

## Part 6 — Data + Question -> Runnable World

**User**

This is exactly where we need to spend most of our time on “What MiroFish is ahead on is the compilation layer from collected evidence into a scenario runtime.”
We have LOTS of data and we can get a LOT more data but we are VERY BAD at compiling all that data so that we can run scenarios. I can say “Trump just announced war on Iran, how will it impact our portfolio and what stocks should we divest into right away? Should we hedge with SPY asap??” or “The SEC filing says SNDK Flash Storage as Q+1 Leading Indicator of AI Compute Deployment, which companies will this impact?”

**Assistant**

This is the heart of it.

The most important thing learned from the repo was:

- MiroFish is not just compiling data
- it is compiling `data + question` into a runnable world

That was broken into:

1. question compiler
2. ontology compiler
3. actor compiler
4. scenario config compiler
5. runtime compiler

And your examples mapped directly:

- “Trump announced war on Iran” should compile into oil, defense, airline, vol, ETF, hedge, and portfolio impacts
- “SNDK filing implies flash storage as leading indicator of AI deployment” should compile into supply-chain and lagged beneficiary logic

The conclusion at this stage:

- Aeternus needs a scenario runtime on top of AKG
- not more raw data

---

## Part 7 — Actor Compiler + Event Compiler

**User**

Yes lets do it and make sure to tie it back to Aeternus.

**Assistant**

This led to a deeper dissection of:

- `oasis_profile_generator.py`
- `simulation_config_generator.py`
- `run_parallel_simulation.py`

The key conclusions were:

### Actor compiler

MiroFish takes graph entities and turns them into runtime actors with:

- context
- role
- memory
- behavior priors

Tie-back to Aeternus:

- we have AKG memory
- but we do not yet compile AKG nodes into market actors

### Event compiler

MiroFish turns the user’s question into seeded runtime inputs:

- hot topics
- narrative direction
- initial posts

Tie-back to Aeternus:

- we need freeform question -> structured market shock objects
- not just social or narrative seed posts

### Runtime

MiroFish’s runtime is not magical market microstructure.
It is a seeded round-based environment.

Tie-back to Aeternus:

- the main lesson is the compiler architecture, not the social simulation skin

---

## Part 8 — We Need Full Script-Level Understanding

**User**

Yes let's investigate it thoroughly. WE need to understand all details.

**Assistant**

The full MiroFish loop was then laid out end-to-end:

1. ingest
2. ontology compile
3. graph build
4. entity filter
5. actor compile
6. scenario compile
7. runtime
8. memory writeback
9. query/report

The most important conclusion from this stage:

- MiroFish feels powerful because it has a complete loop:
  - `question -> runtime world -> actions -> memory update -> queryable answer`
- that is the exact loop Aeternus is missing

---

## Part 9 — User Requested Full Script Map

**User**

let's dig deeper and then give me a super detail step by step of each py script and it's purpose, what it's taking in, what it's doing, and what it's pushing out.

**Assistant**

A detailed script-by-script decomposition was produced, including:

- Flask app shell
- API layers
- project/task persistence
- file parsing
- ontology generation
- graph building
- entity reading
- profile generation
- simulation config generation
- simulation manager
- simulation runner
- IPC
- action logging
- parallel/twitter/reddit simulation scripts
- graph memory updater
- graph query tools
- report agent

The summary again emphasized:

- Aeternus is missing the MiroFish middle:
  - question compiler
  - actor compiler
  - scenario-local runtime overlay
  - post-scenario query layer

---

## Part 10 — Flip The Direction: Map Aeternus To MiroFish Roles

**User**

let's do the mapping and then i can give my detail thoughts per level

**Assistant**

The direction was flipped.

The right question became:

- not “how does Aeternus fit MiroFish?”
- but “which Aeternus components already play the roles MiroFish needs, and which do not?”

A level-by-level mapping was then produced:

1. question capture
2. evidence packet
3. runtime schema
4. durable world memory
5. relevance filtering
6. actor compiler
7. shock compiler
8. runtime
9. writeback
10. query/explanation
11. learning

The bottom-line status became:

- Aeternus strong at durable memory and learning
- partial at evidence packet, filtering, shock logic, queryability
- missing at first-class scenario question capture and market actor compiler

---

## Part 11 — Move From Mapping To Aeternus Step 1: Scouts

**User**

This is great and it will help create a scenario level runtime but first we need to make sure our actual pipeline is ready for a scenario runtime so we need to actually map our components to MiroFish, not the other way around. We have the data, we just need MiroFish functionality.
For e.g. our first step is Scouts. How can this be improved with MiroFish? Then we go step by step.

**Assistant**

This became the first concrete Aeternus-first design pass.

Conclusion:

- scouts are not our weakness
- scout compilation is our weakness

Current scouts are good at:

- detecting catalysts
- surfacing symbols
- preserving provenance
- feeding discovery

Current scouts are weak at:

- compiling multiple signals into one world-state
- extracting reusable causal objects
- creating scenario seeds
- connecting first-order signals to second-order implications

This led to the new proposed layer:

- `Scout Compiler`

---

## Part 12 — Exact Scout Compiler Role

**User**

This are great ideas and we need to incorporate. Is this just a simple python script? Or what else is needed that we dont have?

1. Scout evidence compilation
2. Event extraction
3. Entity and relationship extraction
4. Cross-scout consolidation
5. Scenario seed creation

100% agree here:
For scouts, MiroFish tells us to add one new layer:
Scout Compiler
It should sit:
after scouts run
before universe filtering and collectors
Its job is:

merge scout evidence
normalize entities
extract events
dedupe overlapping narratives
emit scenario seeds
enrich AKG with structured event objects

Step 1A: exact Scout Compiler contract for Aeternus:

inputs
output schema
where it plugs into pipeline.py
what should be persisted into AKG versus kept as temporary runtime state

How does MiroFish handle data collection right? Surely it doesnt have an AKG style repo for ALL worlds data? Does it send out scouts based on the question?

Another thing to think about is what if the question is a scenario we HAVEN'T modeled yet? Scouts havent scoured the info yet?

**Assistant**

The answer broke into several parts.

### Is it just a Python script?

For `v0`, it can begin as one Python module.

But for it to be genuinely useful, it also needs:

- a stable data contract
- a durable artifact
- AKG writeback policy
- a pipeline insertion point
- tests
- later, a question-time retrieval lane

### How does MiroFish handle data collection?

In the open repo:

- it does not keep an all-world AKG
- it does not send out scouts
- it assumes the user hands it the relevant evidence packet

### What if the question is something scouts haven’t covered?

This led to the idea of:

- `Question Gap-Fill Retrieval`

Meaning:

- Aeternus should search internal state first
- if coverage is weak, it should say so explicitly
- it should not pretend the world is fully covered

---

## Part 13 — Compiler vs Retriever

**User**

Yes! This is exactly what we need! But it shouldn't interfere with the pipeline at all.

That means if the user asks:

“Trump announced war on Iran”
and today’s scouts have weak coverage, the system should say:
base world-state available
scenario coverage incomplete
run targeted gap-fill retrieval before final answer

Agree on Pass 1. However, the compiler shouldn’t be a one way street right? It should be able to retrieve from the Universe as well right? Or do you think we should have a separate lane called retriever? which would be similar to Pass 2 where it searches universe, if it finds what it needs, then it retrieves, if it doesn’t then it sends out the scouts. Thoughts?

But overall, i like the idea of turning EVERY run into a daily scenario and make cross relationships between scouts that could lead to potential signal in itself.

**Assistant**

This became the key architecture boundary discussion.

Recommendation:

- keep them separate
- `Scout Compiler` = compiles what we already know
- `Scenario Retriever` = answers a specific question by searching internal state first

Why not combine them?

Because one merged component would become:

- compiler
- state builder
- retriever
- gap detector
- fetcher

That would make `discover` too risky and too hard to reason about.

The cleaner architecture became:

1. scouts
2. scout compiler
3. scenario retriever
4. gap-fill retrieval

Strong agreement emerged on:

- every daily run should become a daily scenario
- cross-scout relationships can become a signal source by themselves

The recommended first passes became:

### Pass 1

- shadow-sidecar Scout Compiler
- no pipeline interference
- write daily scenario artifacts / seeds

### Pass 2

- separate Scenario Retriever
- searches daily scenario packet, AKG, universe, portfolio, caches
- returns `COMPLETE / PARTIAL / MISSING`
- gap fill is on-demand only

---

## Part 14 — Save The Conversation And Add More Precision

**User**

All of this is extremely valuable conversation. WE need save this is a markdown. ALL THE CONVO.

\#2. Scout compiler - The output should be turned into a daily "Event Card" json so that in the future we can paste that into an LLM to create a narrative and push that into investor-docs. This is where LLM will add major value. Agree with your proposal on "turn every run into a daily scenario". This is exactly what we need. Agree with the shadow sidecar
\#3. Scenario Retriever - We will need to define what Complete, Partial, and Missing actually means.
\#4. Agree with this
We need Scenario Retriever from day 1 so I can start testing out and see where the gaps are so we can start fill them sooner than later. One important distinction we need to make is when Scenario Retriever flags a gap, it lists out what it needs to answer and then waits for user. We dont want it to automatically run because that could lead to API usage waste if it does something user can easily upload for free or veto.

**Assistant**

The conversation was saved as:

- a design memo
- project memory addenda
- a daily log note

The major design refinements added here were:

### Event Card output

- the Scout Compiler should output daily `Event Card` JSON
- those Event Cards can later be turned into narrative investor docs by an LLM

### Scenario Retriever from day 1

- this is not deferred
- it is needed immediately so gaps can be found early

### Manual-only gap fill

- if the retriever detects incomplete coverage, it should:
  - list what it needs
  - explain the gap
  - wait for the user
- it should not auto-trigger external retrieval

---

## Final Agreed Architecture From This Discussion

### Scout Compiler

- runs after scouts
- shadow sidecar initially
- does not interfere with existing pipeline behavior
- merges scout evidence
- normalizes entities
- extracts events
- consolidates overlapping narratives
- emits scenario seeds
- writes daily `Event Card` JSON artifacts
- may write safe, durable enrichments into AKG

### Scenario Retriever

- separate lane from the compiler
- available from day 1
- searches:
  - daily Event Cards
  - AKG
  - universe
  - portfolio
  - cached macro / SEC / x-feed artifacts
- returns:
  - `COMPLETE`
  - `PARTIAL`
  - `MISSING`
- if incomplete:
  - lists what evidence is missing
  - waits for the user
  - does not auto-run external scouting

### Operating Philosophy

- every daily run should become a daily scenario
- cross-scout narrative consolidation is valuable in its own right
- this daily scenario layer can later feed:
  - scenario runtime
  - investor docs
  - richer portfolio monitoring
  - future question answering

---

## Documents Created From This Discussion

- [Design Memo](./2026-03-15-mirofish-scout-compiler-and-scenario-retriever-design.md)

Project memory was also updated to preserve the architecture decisions.
