# Task Queue

Opus writes task specs here. Sonnet and Haiku pick them up from their worktrees.

## Workflow
1. Opus creates `<task-id>.md` from TEMPLATE.md
2. User tells the target session to pick up the task
3. Assignee reads the spec, implements, commits on their branch
4. User tells Opus to review — Opus merges if accepted

## Naming Convention
- `S-001-short-description.md` — Sonnet tasks
- `H-001-short-description.md` — Haiku tasks

## Status Values
- `pending` — Written by Opus, not yet started
- `in-progress` — Assignee is working on it
- `done` — Assignee committed, awaiting Opus review
- `merged` — Opus reviewed and merged into feature/opus46
