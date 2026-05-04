# Autoresearch Decision Gate Design

## Goal

Create a reusable skill that forces structured thinking before any optimization or autoresearch work begins.

## Core Idea

The skill prevents wasted time by making the agent decide:
- the metric
- the evaluator
- the size of the search space
- whether brute force or autoresearch is actually appropriate
- the promotion ladder from experiment to production

## Output Contract

The skill produces a short memo with:
- Problem
- Metric
- Evaluator
- Search Surface
- Best Tool
- Promotion Ladder
- Primary Risks
- Recommendation

## Design Choice

This is an auto-loading workflow skill, not background knowledge, because it should trigger when users discuss tuning, parameter search, autoresearch, or optimization strategy.
