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
- Run tests before committing: `python -m pytest tests/ -v`
- Match existing code style

### Documentation
- Keep memory files up to date
- Use ISO timestamps (YYYY-MM-DDTHH:MM:SS)
- Be concise but complete

### Communication
- If blocked, document in WORKING.md blockers section
- If decision needed, list options clearly
- If uncertain, ask rather than assume

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
