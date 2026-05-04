"""
Tests for tradingagents/dataflows/perplexity.py (S-051).

All tests run without network access and without a real PERPLEXITY_API_KEY.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.dataflows.perplexity import get_company_enrichment


def test_get_company_enrichment_returns_none_when_api_key_missing(monkeypatch):
    """Returns None immediately when PERPLEXITY_API_KEY is not set."""
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    result = get_company_enrichment(
        ticker="AXTI",
        display_name="AXT Inc",
        sector_display="Semis Ai Infrastructure",
    )
    assert result is None


def test_get_company_enrichment_returns_text_on_success(monkeypatch):
    """Returns enrichment text when the API call succeeds."""
    monkeypatch.setenv("PERPLEXITY_API_KEY", "test-perplexity-key")

    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = (
        "AXT Inc supplies indium phosphide substrates used in AI photonics. "
        "Key customers include Coherent and Lumentum. Recent catalyst: record "
        "InP wafer orders from hyperscaler supply chains."
    )

    with patch("openai.OpenAI") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_resp

        result = get_company_enrichment(
            ticker="AXTI",
            display_name="AXT Inc",
            sector_display="Semis Ai Infrastructure",
            velocity_z=2.5,
        )

    assert result is not None
    assert "AXT Inc" in result
    assert "photonics" in result


def test_get_company_enrichment_returns_none_on_api_exception(monkeypatch):
    """Returns None when the OpenAI/Perplexity API raises an exception."""
    monkeypatch.setenv("PERPLEXITY_API_KEY", "test-perplexity-key")

    with patch("openai.OpenAI") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = RuntimeError("Connection refused")

        result = get_company_enrichment(
            ticker="AXTI",
            display_name="AXT Inc",
            sector_display="Semis Ai Infrastructure",
        )

    assert result is None
