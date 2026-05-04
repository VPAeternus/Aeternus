# S-054: Content Review Workflow Enhancement

**Status:** done
**Assignee:** Sonnet
**Branch:** feature/sonnet46
**Priority:** Week 2
**Touches:** 1 file

## Objective

Enhance the existing `content-review` CLI command to support showing full post text for review, and add a `--tier` filter for hook/analysis/article.

## Files to Touch

1. `cli/commands/content.py` — enhance `content-review` command (~40 lines added)
2. `tests/test_content_review_enhanced.py` — new test file

## Implementation

### Enhance `content-review` command

Add two new options:

```python
@app.command("content-review")
def content_review(
    date: Optional[str] = ...,
    ticker: Optional[str] = ...,
    tier: Optional[str] = typer.Option(None, "--tier", help="Filter by tier: hook, analysis, or article"),
    show: bool = typer.Option(False, "--show", help="Display full post text"),
    format: str = ...,
):
```

When `--show` is provided along with `--ticker`:
- If `--tier` is specified (hook, analysis, article), display that specific post's full text
- If `--tier` is not specified, display all 3 posts for that ticker
- Use `console.print(Panel(...))` to render each post in a bordered panel

When `--show` is provided without `--ticker`:
- Print a warning: "Please specify --ticker when using --show"

Tier mapping:
- `hook` → `post_1_hook.txt`
- `analysis` → `post_2_analysis.txt`
- `article` → `post_3_article.md`

### Example Usage

```
# List all posts for a date
aeternus content-review --date 2026-02-26 --format table

# Show the hook post for AAPL
aeternus content-review --date 2026-02-26 --ticker AAPL --tier hook --show

# Show all posts for AAPL
aeternus content-review --date 2026-02-26 --ticker AAPL --show
```

## Acceptance Criteria

- [ ] `--show` displays full text in a panel
- [ ] `--tier` filters to specific post type
- [ ] `--show` without `--ticker` prints a helpful warning
- [ ] Works with existing content_posts.py output format
- [ ] No changes to existing behavior when --show is not provided
- [ ] Tests verify new options

## Notes

- The content-review command already exists and works. This is an enhancement, not a rewrite.
- Keep the existing table display as-is when --show is not used.
- Match existing CLI patterns in execution.py and content.py.
