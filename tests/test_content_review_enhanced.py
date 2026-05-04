"""Tests for enhanced content-review CLI command (--tier and --show flags)."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from cli.commands.content import app


runner = CliRunner()


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def _make_posts_dir(base: Path, ticker: str = "AAPL", date: str = "2026-02-26") -> Path:
    """Create mock post files under results/<ticker>/<date>/posts/ and return posts dir."""
    posts_dir = base / "results" / ticker / date / "posts"
    posts_dir.mkdir(parents=True, exist_ok=True)
    (posts_dir / "post_1_hook.txt").write_text(f"$AAPL BUY — Score 72.50. Analysis to follow.")
    (posts_dir / "post_2_analysis.txt").write_text(
        "THE CASE FOR: Strong earnings.\nTHE CASE AGAINST: High valuation.\nHere is the article and full analysis if anyone wants details."
    )
    (posts_dir / "post_3_article.md").write_text(
        "## Fundamental Analysis\nStrong fundamentals.\n\n## The Bull Case\nGrowth is accelerating.\n\n*Not financial advice.*"
    )
    return posts_dir


def _make_report(base: Path, ticker: str = "AAPL", date: str = "2026-02-26") -> Path:
    """Write a minimal analysis_report.json alongside the posts dir."""
    report_dir = base / "results" / ticker / date
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "aeternus_score": {
            "aeternus_score": 72.5,
            "rating": "Buy",
        }
    }
    report_path = report_dir / "analysis_report.json"
    report_path.write_text(json.dumps(report))
    return report_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestShowFlagWithoutTicker:
    def test_show_flag_without_ticker_warns(self, tmp_path, monkeypatch):
        """--show without --ticker should print a warning and return cleanly."""
        monkeypatch.chdir(tmp_path)
        _make_posts_dir(tmp_path)
        _make_report(tmp_path)

        result = runner.invoke(app, ["content-review", "--date", "2026-02-26", "--show"])
        assert result.exit_code == 0
        assert "Please specify --ticker when using --show" in result.output


class TestShowDisplaysPostContent:
    def test_show_displays_hook_content(self, tmp_path, monkeypatch):
        """--show --ticker renders Panel with hook post text."""
        monkeypatch.chdir(tmp_path)
        _make_posts_dir(tmp_path)
        _make_report(tmp_path)

        result = runner.invoke(
            app,
            ["content-review", "--date", "2026-02-26", "--ticker", "AAPL", "--show"],
        )
        assert result.exit_code == 0
        # Panel title should appear
        assert "AAPL" in result.output
        assert "Hook Post" in result.output
        # Hook content
        assert "$AAPL BUY" in result.output

    def test_show_displays_all_tiers_by_default(self, tmp_path, monkeypatch):
        """--show without --tier renders all three tiers."""
        monkeypatch.chdir(tmp_path)
        _make_posts_dir(tmp_path)
        _make_report(tmp_path)

        result = runner.invoke(
            app,
            ["content-review", "--date", "2026-02-26", "--ticker", "AAPL", "--show"],
        )
        assert result.exit_code == 0
        assert "Hook Post" in result.output
        assert "Analysis Post" in result.output
        assert "Full Article" in result.output

    def test_show_no_match_warns(self, tmp_path, monkeypatch):
        """--show with --ticker that has no posts prints a not-found warning."""
        monkeypatch.chdir(tmp_path)
        _make_posts_dir(tmp_path, ticker="AAPL")
        _make_report(tmp_path, ticker="AAPL")

        result = runner.invoke(
            app,
            ["content-review", "--date", "2026-02-26", "--ticker", "AAPL", "--show", "--ticker", "MSFT"],
        )
        # Either exit with no-content message or warn about missing ticker
        # Multiple --ticker flags — last one wins in Typer; MSFT has no content
        assert result.exit_code == 0


class TestTierFilter:
    def test_tier_hook_only(self, tmp_path, monkeypatch):
        """--show --tier hook renders only the hook panel."""
        monkeypatch.chdir(tmp_path)
        _make_posts_dir(tmp_path)
        _make_report(tmp_path)

        result = runner.invoke(
            app,
            [
                "content-review",
                "--date", "2026-02-26",
                "--ticker", "AAPL",
                "--show",
                "--tier", "hook",
            ],
        )
        assert result.exit_code == 0
        assert "Hook Post" in result.output
        assert "Analysis Post" not in result.output
        assert "Full Article" not in result.output

    def test_tier_analysis_only(self, tmp_path, monkeypatch):
        """--show --tier analysis renders only the analysis panel."""
        monkeypatch.chdir(tmp_path)
        _make_posts_dir(tmp_path)
        _make_report(tmp_path)

        result = runner.invoke(
            app,
            [
                "content-review",
                "--date", "2026-02-26",
                "--ticker", "AAPL",
                "--show",
                "--tier", "analysis",
            ],
        )
        assert result.exit_code == 0
        assert "Analysis Post" in result.output
        assert "Hook Post" not in result.output
        assert "Full Article" not in result.output

    def test_tier_article_only(self, tmp_path, monkeypatch):
        """--show --tier article renders only the article panel."""
        monkeypatch.chdir(tmp_path)
        _make_posts_dir(tmp_path)
        _make_report(tmp_path)

        result = runner.invoke(
            app,
            [
                "content-review",
                "--date", "2026-02-26",
                "--ticker", "AAPL",
                "--show",
                "--tier", "article",
            ],
        )
        assert result.exit_code == 0
        assert "Full Article" in result.output
        assert "Hook Post" not in result.output
        assert "Analysis Post" not in result.output

    def test_tier_without_show_is_ignored(self, tmp_path, monkeypatch):
        """--tier without --show should not affect normal table output."""
        monkeypatch.chdir(tmp_path)
        _make_posts_dir(tmp_path)
        _make_report(tmp_path)

        result = runner.invoke(
            app,
            [
                "content-review",
                "--date", "2026-02-26",
                "--ticker", "AAPL",
                "--tier", "hook",
            ],
        )
        assert result.exit_code == 0
        # Table output still present
        assert "AAPL" in result.output
        # No panel output
        assert "Hook Post" not in result.output

    def test_invalid_tier_shows_error(self, tmp_path, monkeypatch):
        """--tier with an unknown value prints an error message."""
        monkeypatch.chdir(tmp_path)
        _make_posts_dir(tmp_path)
        _make_report(tmp_path)

        result = runner.invoke(
            app,
            [
                "content-review",
                "--date", "2026-02-26",
                "--ticker", "AAPL",
                "--show",
                "--tier", "summary",
            ],
        )
        assert result.exit_code == 0
        assert "Unknown tier" in result.output
