# Task: S-001

## Tier
sonnet

## Summary
Create GitHub Actions CI/CD pipeline that runs pytest on push and PR.

## Context
The project has no `.github/workflows/` directory. Tests use pytest with 46 test files in `tests/`. Python >= 3.10 is required (pyproject.toml). Dependencies are in `requirements.txt`. No dedicated test dependencies file exists — pytest and unittest.mock are the only test tools needed.

## Requirements
1. Create `.github/workflows/ci.yml` with a single job that:
   - Triggers on push to `main`, `feature/*` branches and on pull requests to `main`
   - Uses `ubuntu-latest` with Python 3.10 and 3.12 matrix
   - Installs dependencies from `requirements.txt` plus `pytest`
   - Runs `python -m pytest tests/ -v --tb=short`
2. Cache pip dependencies for faster runs (`actions/cache` or `setup-python` cache)
3. Set a 15-minute timeout on the test job
4. Add a concurrency group so pushes to the same branch cancel in-flight runs

## Files to Touch
- `.github/workflows/ci.yml` (new)

## Acceptance Criteria
- [ ] `.github/workflows/ci.yml` exists and is valid YAML
- [ ] Matrix tests Python 3.10 and 3.12
- [ ] pip cache is configured
- [ ] Concurrency group cancels superseded runs
- [ ] All existing tests pass locally: `python -m pytest tests/ -v`

## Status
pending
