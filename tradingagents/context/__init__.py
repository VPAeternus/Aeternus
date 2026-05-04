"""Reusable context-query backends for CLI and future harness surfaces."""

from .company_context import get_company_context
from .event_state import get_event_state

__all__ = ["get_event_state", "get_company_context"]
