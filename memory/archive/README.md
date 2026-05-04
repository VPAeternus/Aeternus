# Five-Tier Persistent Memory System

This folder implements a persistent memory hierarchy for AI agents working on the Aeternus project. The system enables any IDE, agent, or model to continue work from where previous sessions left off.

---

## Control-Plane Overlay (Complementary)

The five-tier memory remains the operational backbone. We additionally maintain a durable control-plane set for long-horizon coherence:

| File | Purpose |
|------|---------|
| `Prompt.md` | Stable mission, scope, spec, and deliverables |
| `Plans.md` | Milestones, sequencing, and validation gates |
| `Architecture.md` | Principles, boundaries, interfaces, and constraints |
| `DeepWiki_System_Architecture.md` | Canonical As-Is + Target-State architecture with diagrams and contract maps |
| `Implement.md` | Reusable implementation prompt/workflow for agents |
| `Documentation.md` | Milestone status and architectural decision ledger |

These files are designed to be low-churn and should link to `WORKING.md` and daily logs rather than duplicate tactical details.

---

## Memory Tiers

| Tier | File | Purpose | Update Frequency |
|------|------|---------|------------------|
| **Working Memory** | `WORKING.md` | Current task state, next steps, blockers | After every action |
| **Short-term Memory** | `YYYY-MM-DD.md` | Timestamped activity logs | Throughout the day |
| **Long-term Memory** | `MEMORY.md` | Curated knowledge, decisions, system facts | Periodically |
| **Identity Layer** | `../AGENTS.md` | Operating manual and personality | Rarely |
| **Session Memory** | `conversation.jsonl` | Full chat history (if available) | Automatic |

---

## Golden Rules

1. **READ `WORKING.md` FIRST** on every wake-up
2. **UPDATE `WORKING.md`** after every significant action
3. **"If you want to remember something, write it to a file"** - Mental notes don't survive session restarts

---

## Usage Protocol

### Starting a Session
```
1. Read memory/WORKING.md → Current state
2. Scan memory/MEMORY.md → Architecture context (if needed)
3. Check recent daily logs → Recent activity
```

### Ending a Session
```
1. Update memory/WORKING.md → New state, blockers
2. Append to memory/YYYY-MM-DD.md → What was done
3. Update memory/MEMORY.md → Only if new decisions made
```

---

## File Templates

### Daily Log Template (YYYY-MM-DD.md)
```markdown
# Activity Log: YYYY-MM-DD

## Session: HH:MM - Topic

### Actions
- **HH:MM** - What was done

### Observations
- Insights gained

### Tomorrow's Priorities
- Next steps
```

---

*System implemented: 2026-02-04*
