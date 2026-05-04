# Fundamental Qwen Autoresearch Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a local Qwen-powered proposer loop for the deterministic fundamental autoresearch harness.

**Architecture:** A new `qwen_autoresearch.py` module will call the local MLX OpenAI-compatible server, request constrained weight proposals, normalize them, and evaluate them with the existing SEC filing harness. A thin CLI command will persist the resulting leaderboard and best strategy without changing live signal promotion.

**Tech Stack:** Python, local MLX Qwen server, OpenAI-compatible client, existing SEC fundamental autoresearch harness, pytest.

---

### Task 1: Add failing tests for proposal normalization and runner behavior

**Files:**
- Create: `tests/test_fundamental_autoresearch_qwen_autoresearch.py`

### Task 2: Implement the Qwen proposal runner

**Files:**
- Create: `tradingagents/research/fundamental_autoresearch/qwen_autoresearch.py`
- Modify: `tradingagents/research/fundamental_autoresearch/artifacts.py`

### Task 3: Add CLI command

**Files:**
- Modify: `cli/commands/fundamental_research.py`

### Task 4: Verify the focused surface

**Files:**
- Test: `tests/test_fundamental_autoresearch_qwen_autoresearch.py`
- Test: `tests/test_cli_fundamental_research.py`
