# Perplexity Computer + Manus: Deep Review for Aeternus Harness Design

Date: 2026-03-20  
Scope: Official product/help/docs surfaces only; focus on reusable harness patterns for Aeternus.

---

## Executive Summary

Both Perplexity Computer and Manus are proving the same point: value comes from the runtime harness, not just model quality.

For Aeternus, the highest-value transfer is:
- single-query orchestrated execution,
- visible state/progress,
- bounded manual intervention loops,
- strict policy gates before action output,
- artifact-first memory and learning linkage.

Their broad productivity scope is not the target. Aeternus should apply these patterns narrowly to investment decisioning.

---

## Verified Findings (Source-Backed)

## Perplexity Computer

Key verified capabilities:
- Unified multi-step execution in one agent surface ("What Computer Does" + "How Computer Works").
- Asynchronous/background execution and proactive scheduling.
- Connector-driven workflow execution (Gmail, Outlook, GitHub, Linear, Slack, Notion, Snowflake, Databricks, Salesforce, etc.).
- Persistent memory and secure cloud sandbox.
- Enterprise controls: SOC2 inheritance, audit logs, model configurability, no-training-on-customer-data commitments.
- Skill system with built-in and custom uploaded skills (`SKILL.md`/zip workflow).

References:
- [Computer for Enterprise](https://www.perplexity.ai/help-center/en/articles/13901210-computer-for-enterprise)
- [How to use Computer Skills](https://www.perplexity.ai/help-center/en/articles/13914413-how-to-use-computer-skills)
- [What We Shipped (Feb 27, 2026)](https://www.perplexity.ai/changelog/what-we-shipped---february-27-2026)

## Manus

Key verified capabilities:
- Isolated cloud sandbox per task as core execution primitive.
- "Wide Research" framing that addresses context-window bottlenecks via decomposition and parallelized orchestration.
- Browser Operator and local `My Computer` mode with explicit user authorization/intervention controls.
- Project Skills and project-level reusable instruction context.
- Connector-enabled project workflows (including custom APIs).
- Public API surface centered on `projects`, `tasks`, `files`, `webhooks` (+ connectors/integrations docs).
- Credit consumption model includes model/compute/external integration factors (from help center materials).

References:
- [Wide Research: Beyond the Context Window](https://manus.im/blog/manus-wide-research-solve-context-problem)
- [Understanding Manus sandbox](https://manus.im/blog/manus-sandbox)
- [Project Skills](https://manus.im/blog/manus-project-skills)
- [Browser Operator](https://manus.im/blog/manus-browser-operator)
- [Projects + Connectors](https://manus.im/blog/projects-connectors)
- [Manus API Overview](https://open.manus.ai/docs)
- [Credits rules (FR help)](https://help.manus.im/fr/articles/11711097-quelles-sont-les-regles-de-consommation-des-credits-et-comment-puis-je-en-obtenir)

---

## Comparative Harness Pattern Matrix

| Pattern | Perplexity Computer | Manus | Aeternus Relevance |
|---|---|---|---|
| Single query -> multi-step runtime | Strong | Strong | Must-have |
| Parallel decomposition | Strong | Strong | Must-have for multi-symbol/scenario tasks |
| Isolated execution environment | Strong | Strong | Must-have for safe external/tool actions |
| Skills as reusable behavior units | Strong | Strong | Must-have (`scouts`, `committee`, `scenario`) |
| Connector-first integrations | Strong | Strong | High-value (data and workflow expansion) |
| Explicit operator intervention | Moderate | Strong | Must-have for manual Grok loops |
| Enterprise audit/governance posture | Strong | Moderate | Must-have for trust and replayability |
| Financial domain policy gating | Not core | Not core | Aeternus-specific moat |

---

## What Aeternus Already Has (Advantage)

- Strong structured pipeline with stage artifacts.
- Stage-level miss diagnosis and drop metadata.
- Score decomposition and pre/post-LLM influence visibility.
- Manual X-feed workflow and operator-driven passes.
- Policy-aware committee packeting and output validation.
- Research-to-portfolio trace primitives already present.

This means Aeternus is not "starting from zero."  
The primary gap is unification into one user-facing harness runtime.

---

## Main Gaps to Close (Harness v1)

1. **Single orchestration entrypoint**  
Current flows are command-fragmented; users still stitch steps manually.

2. **Run-state visibility**  
Need deterministic progress events at every stage for operator trust.

3. **Manual intervention runtime state**  
Manual scout input exists, but should be standardized as a WAIT/RESUME state machine.

4. **Mode-native execution policy**  
Need explicit mode routing (`DECIDE/SCENARIO/DIAGNOSE_MISS/PORTFOLIO_ACTION`) under one contract.

5. **Unified persistence schema**  
Need one harness run artifact linking question -> stages -> decision -> hindsight.

---

## Concrete Adoption Plan (First 30 Days)

## Week 1
- Implement `HarnessRouter` + run IDs + event stream states.
- Add mode classifier with confidence and mode-hint reconciliation.

## Week 2
- Integrate unified precheck gate (freshness/coverage/manual-readiness).
- Wire `DECIDE` and `DIAGNOSE_MISS` engines into router.

## Week 3
- Add manual-input state machine (prompt, pause, validate, resume).
- Add `SCENARIO` and `PORTFOLIO_ACTION` handlers.

## Week 4
- Harden policy gates and contract tests.
- Persist canonical run artifact and hindsight linkage.
- Ship CLI output contract with deterministic step updates.

---

## Pushbacks / Risk Notes

- Do not optimize for edge count or generic agent breadth before harness reliability.
- Do not auto-execute trades in v1.
- Do not hide stale context under "best effort" recommendations.
- Do not let external search overwrite canonical packet values without explicit conflict logs.

---

## Decision

The correct next move is to build Aeternus Harness v1 now as a runtime unification layer, not a model swap and not a new data-source sprint.

This preserves current moat (financial policy + diagnostics + attribution) and adds the missing product surface users actually experience.

