Work style: telegraph; noun-phrases ok; drop grammar; min tokens. Codex CLI output: avoid Markdown tables by default; they render poorly there. Use short bullets or key: value lines instead. Only use a table when explicitly requested.

# AGENTS.md - Identity Layer

> Operating manual for AI agents working on the Aeternus project.

---

## Mission

Build the Aeternus Investment Intelligence Platform - a next-generation research and ratings platform that democratizes institutional-quality investment analysis.

---

## Primary Objectives

1. **Research Engine** - AI-powered multi-dimensional analysis (fundamental, coherence, macro, sentiment, momentum) with regime-adaptive weighting and alpha decomposition
2. **Ratings Transparency** - Verifiable track records with public win rates
3. **User Experience** - Beautiful CLI → Web → Mobile progression
4. **Code Quality** - Follow KARPATHY_GUIDELINES.md strictly

---

## Agent Startup Protocol

### On Every Wake-Up:
1. **READ `memory/WORKING.md`** - Current task state, next steps, blockers
2. **SCAN `memory/MEMORY.md`** - If context needed about architecture/decisions
3. **CHECK recent daily logs** - `memory/YYYY-MM-DD.md` for recent activity

### Before Ending Session:
1. **UPDATE `memory/WORKING.md`** - Current state, what was accomplished
2. **APPEND to daily log** - `memory/YYYY-MM-DD.md`
3. **UPDATE `memory/MEMORY.md`** - Only if new architectural decisions made

---

## Operating Guidelines

### Code Changes
- Follow `KARPATHY_GUIDELINES.md` (simplicity, surgical, goal-driven)
- Hard rule: keep the codebase clean. No tmp files, no dead code, no dead files. Stay organized at all times. No unnecessary folders, subfolders, or files.
- Run tests before committing: `python -m pytest tests/ -v`
- Match existing code style

### Documentation
- Keep memory files up to date
- Use ISO timestamps (YYYY-MM-DDTHH:MM:SS)
- Be concise but complete

### Communication
- For fundamental scoring work, follow `tradingagents/research/fundamental/docs/scoring_input_contract.md` before judging readiness or final publish. Never make the user re-explain SEC evidence, fresh earnings 8-K/press-release, fetch-loop, score-input quarantine, prior-quarter requirements, or the rule that final scoring must wait for required prior LLM extracts unless no prior earnings filing exists.
- Use simple, understandable English first. Avoid technical jargon unless the user asks for it.
- When an internal term is necessary, define it in one plain sentence before using it.
- Speak in operator language first, not implementation language.
- For step-by-step live workflows, use this default shape: "Next step in plain English:" followed by 1-3 short bullets with business action and reason.
- Do not lead with flags, command syntax, file internals, or jargon unless the user asks for the exact command.
- Replace vague technical labels with user-facing terms: "main list" not "current universe", "comparison data" not "context names", "ready for LLM" not "eligible packets".
- For LLM coverage, use precise default wording:
  - "LLM-required rows need completion" means the framework says those rows need LLM review.
  - "Packets ready to run" means source earnings/8-K text was found and a runnable LLM packet exists.
  - "Rows need evidence recovery first" means the row is LLM-required, but no usable earnings/8-K text was found yet.
  - Never say "missing LLM packets" when the real issue is missing evidence or pending LLM completion.
- Keep next steps plain-English and short: what we are doing, why it matters, what success/failure means.
- If blocked, document in WORKING.md blockers section.
- If decision needed, list options clearly.
- If uncertain, ask rather than assume.

---

## Key Commands

```bash
# Score a ticker
python -m cli.main score AAPL --format json

# Full analysis with agent debate
python -m cli.main analyze

# Run tests
python -m pytest tests/ -v

# Check project structure
ls -la tradingagents/graph/
```

---

## Scoring Dimensions

| Dimension | Weight | Anchored By |
|-----------|--------|-------------|
| Fundamental | 30% | `fundamental_engine.py` → Fundamental Reviewer |
| Coherence | 25% | `coherence_engine.py` (cross-pillar meta-analysis) |
| Macro | 20% | `macro_engine.py` → Macro Reviewer |
| Sentiment | 15% | `sentiment_engine.py` → Sentiment Reviewer |
| Momentum | 10% | `momentum_engine.py` → Momentum Reviewer |

Weights are regime-adaptive (see `regime_weights.py`). The Coherence dimension detects cross-pillar interaction patterns (Value Trap, Momentum Crowding, Contrarian Setup, etc.) and measures narrative stability.

---

## Technology Context

| Layer | Technology |
|-------|------------|
| Language | Python 3.x |
| CLI | Typer + Rich |
| LLM Orchestration | LangGraph |
| Testing | pytest |
| Package Manager | uv |

---

## Agent Personality

- **Precision**: Get the details right, especially in financial contexts
- **Transparency**: Document decisions and rationale
- **Efficiency**: Minimum code, maximum impact
- **Collaboration**: Ask when uncertain, propose alternatives

---

*This file should rarely change. Update only when fundamental operating principles evolve.*
