# Model Router V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a conservative Pi model-router v2 extension with weighted classification, fallback chains, manual lock behavior, persisted auto-routing toggle, and inspection commands/tools.

**Architecture:** Keep the extension in one focused TypeScript file, but separate logic into exported pure helpers for config loading, route scoring, policy decisions, and fallback selection so tests can cover behavior without Pi runtime dependencies. Persist only `autoRoutingEnabled` using extension custom entries and keep lock state in memory.

**Tech Stack:** Pi extensions API, TypeBox, Node built-ins (`fs`, `path`, `os`), Node test runner with `--experimental-strip-types`.

---

### Task 1: Add failing tests for routing logic

**Files:**
- Create: `tests/pi_extensions/test_model_router_v2.mjs`
- Create: `.pi/extensions/model-router-v2.ts`

- [ ] **Step 1: Write failing tests**
- [ ] **Step 2: Run test to verify it fails**
  - Run: `node --experimental-strip-types --test tests/pi_extensions/test_model_router_v2.mjs`
  - Expected: FAIL because helper exports do not exist yet
- [ ] **Step 3: Implement minimal exported helpers in `.pi/extensions/model-router-v2.ts`**
- [ ] **Step 4: Run test to verify it passes**
  - Run: `node --experimental-strip-types --test tests/pi_extensions/test_model_router_v2.mjs`
- [ ] **Step 5: Commit**

### Task 2: Implement extension runtime behavior

**Files:**
- Modify: `.pi/extensions/model-router-v2.ts`

- [ ] **Step 1: Add session-start restoration and status updates**
- [ ] **Step 2: Add config loading + validation helpers**
- [ ] **Step 3: Add before-agent conservative routing flow with fallbacks**
- [ ] **Step 4: Add model-select lock behavior**
- [ ] **Step 5: Run targeted tests**
  - Run: `node --experimental-strip-types --test tests/pi_extensions/test_model_router_v2.mjs`
- [ ] **Step 6: Commit**

### Task 3: Add commands and tools

**Files:**
- Modify: `.pi/extensions/model-router-v2.ts`

- [ ] **Step 1: Add slash commands for status, auto, lock, test, validate, reset**
- [ ] **Step 2: Add LLM tools for current info, model listing, switching, and recommendations**
- [ ] **Step 3: Ensure manual switching locks the router**
- [ ] **Step 4: Run targeted tests**
  - Run: `node --experimental-strip-types --test tests/pi_extensions/test_model_router_v2.mjs`
- [ ] **Step 5: Commit**

### Task 4: Verify and document usage

**Files:**
- Modify: `memory/WORKING.md`
- Create: `memory/2026-03-28.md` (append if exists)

- [ ] **Step 1: Run tests and inspect output**
  - Run: `node --experimental-strip-types --test tests/pi_extensions/test_model_router_v2.mjs`
- [ ] **Step 2: If Pi runtime is available, optionally sanity-check extension load path manually**
- [ ] **Step 3: Update working memory with what changed and any follow-ups**
- [ ] **Step 4: Commit**
