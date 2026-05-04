# Industry Disruption First Principles Skill Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a reusable first-principles industry disruption skill and immediately apply it to Aeternus as a worked strategic memo.

**Architecture:** Create one auto-loading workflow skill with a tight structured memo contract, put the Aeternus worked example in a reference file, and produce one separate Aeternus memo using the same framework.

**Tech Stack:** Markdown skills, repo documentation

---

### Task 1: Create the skill shell

**Files:**
- Create: `.agents/skills/industry-disruption-first-principles/SKILL.md`

**Step 1: Write the frontmatter**

Include:
- `name`
- `description`

**Step 2: Write the workflow**

Include:
- when to use / when not to use
- the first-principles sequence
- the required output memo sections

**Step 3: Verify the file exists**

Run:

```bash
ls -la .agents/skills/industry-disruption-first-principles/SKILL.md
```

### Task 2: Add the Aeternus worked example reference

**Files:**
- Create: `.agents/skills/industry-disruption-first-principles/references/aeternus-worked-example.md`

**Step 1: Write the worked example**

Cover:
- finance as inherited analyst workflow
- agent inheritance opportunity
- wedge
- scorecard loop
- platform path

**Step 2: Verify the reference exists**

Run:

```bash
ls -la .agents/skills/industry-disruption-first-principles/references/aeternus-worked-example.md
```

### Task 3: Run Aeternus through the framework

**Files:**
- Create: `docs/plans/2026-03-08-aeternus-first-principles-memo.md`

**Step 1: Write the memo using the exact skill contract**

Use the required sections from the skill.

**Step 2: Keep it concrete**

Include:
- company thesis
- wedge
- inherited infrastructure
- scorecard loop
- platform expansion path
- failure modes

### Task 4: Verify skill quality

**Files:**
- Read: `.agents/skills/industry-disruption-first-principles/SKILL.md`

**Step 1: Check frontmatter**

Confirm:
- YAML delimiters
- quoted description
- clear trigger language

**Step 2: Dry-run the trigger mentally**

Ask:
- if a user says “pressure-test this industry wedge”
- or “what is the Zero-to-One company here?”
- will the description clearly match?

### Task 5: Memory updates

**Files:**
- Modify: `memory/WORKING.md`
- Modify: `memory/2026-03-08.md`
- Modify: `memory/MEMORY.md`

**Step 1: Document the new skill**

Include:
- skill path
- worked example path
- Aeternus memo path
- current recommendation: use it as the strategic gate for future company / wedge / disruption thinking
