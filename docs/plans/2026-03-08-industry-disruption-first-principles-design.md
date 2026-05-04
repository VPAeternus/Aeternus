# Industry Disruption First Principles Skill Design

## Goal

Create a reusable Codex skill that forces first-principles industry disruption thinking, then apply it to Aeternus as the first worked example.

## Why

The project now has strong operational instrumentation, but the user wants a higher-order strategic capability:

- identify immutable truths in an industry
- find where incumbents are wasting time
- separate obligation work from edge work
- define a narrow wedge that can become a Zero-to-One company

The skill should turn that way of thinking into a repeatable framework instead of a one-off conversation.

## Archetype

Recommended archetype:

- auto-loading workflow
- user-invocable
- no side-effect restriction

Reason:

- the framework should auto-load during strategy / company / wedge discussions
- the user should also be able to invoke it directly when pressure-testing a new market or company idea

## Scope

v1 includes:

- a new skill under `.agents/skills/industry-disruption-first-principles/`
- one worked example reference for Aeternus
- one separate Aeternus memo produced by running the framework against the company

v1 does not include:

- tooling automation
- CLI integration
- a scoring engine
- multi-example reference library

## Skill Workflow

The skill should force this sequence:

1. What are the immutable truths?
2. What infrastructure already exists?
3. What are incumbents wasting time on?
4. What work is obligation, not edge?
5. What can software / agents inherit instead of rebuild?
6. What is the narrowest wedge with the fastest feedback loop?
7. What scorecard closes the loop?
8. What becomes the platform after the wedge wins?

## Output Contract

The skill should require a structured strategy memo with these sections:

- `Industry Thesis`
- `Immutable Truths`
- `Inherited Infrastructure`
- `Incumbent Waste`
- `Obligation Work vs Edge Work`
- `Agent Inheritance Opportunity`
- `Narrow Wedge`
- `Scorecard / Learning Loop`
- `Platform Expansion Path`
- `Why Now`
- `Failure Modes`
- `Zero-to-One Verdict`

This keeps the skill actionable and prevents it from collapsing into inspirational but vague prose.

## File Structure

Recommended structure:

- `.agents/skills/industry-disruption-first-principles/SKILL.md`
- `.agents/skills/industry-disruption-first-principles/references/aeternus-worked-example.md`
- `docs/plans/2026-03-08-aeternus-first-principles-memo.md`

## Success Criteria

The skill is successful if:

- its description is specific enough to auto-load on strategy / wedge / disruption prompts
- the workflow is concrete and falsifiable
- the Aeternus example is specific, not generic
- the resulting memo sharpens the company thesis beyond “AI investment app”

## Verification

Minimal verification for v1:

- file exists in the correct skill directory
- frontmatter is valid
- description is specific enough for auto-loading
- worked example is present
- Aeternus memo is present
