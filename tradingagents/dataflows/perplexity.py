"""Perplexity sonar connector for AKG enrichment (S-051)."""
from __future__ import annotations
import os
from typing import Optional


def get_company_enrichment(
    ticker: str,
    display_name: str,
    sector_display: str,
    velocity_z: float = 0.0,
) -> Optional[str]:
    """
    Call Perplexity sonar for a 2-3 paragraph company briefing.
    Returns enrichment text or None on any failure.

    Cost: ~$0.003/call (sonar model).
    Requires PERPLEXITY_API_KEY in environment.
    """
    api_key = os.environ.get("PERPLEXITY_API_KEY", "").strip()
    if not api_key:
        return None

    prompt = (
        f"Company: {display_name} ({ticker}) | Sector: {sector_display}\n\n"
        f"Provide a concise 2-3 paragraph briefing:\n"
        f"1. What this company does and why it is gaining momentum in the {sector_display} sector\n"
        f"2. Key supply chain relationships (main customers, suppliers, partners)\n"
        f"3. Most significant recent development or catalyst\n\n"
        f"Be factual and brief. Focus on what makes this company notable right now."
    )

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://api.perplexity.ai")
        resp = client.chat.completions.create(
            model="sonar",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0.2,
        )
        text = resp.choices[0].message.content.strip()
        return text if text else None
    except Exception:
        return None


def get_company_enrichment_dark_matter(
    ticker: str,
    display_name: str,
    force_id: str,
    necessity_score: float,
    causal_reasoning: str,
    sector_display: str,
) -> Optional[str]:
    """
    Call Perplexity sonar for a force-aware company briefing targeting dark matter candidates.
    Returns enrichment text or None on any failure.

    Cost: ~$0.003/call (sonar model).
    Requires PERPLEXITY_API_KEY in environment.
    """
    api_key = os.environ.get("PERPLEXITY_API_KEY", "").strip()
    if not api_key:
        return None

    prompt = (
        f"Company: {display_name} ({ticker}) | Force: {sector_display} | "
        f"Necessity: {necessity_score:.0%}\n\n"
        f"Why this company is causally necessary: {causal_reasoning}\n\n"
        f"Provide a concise 2-3 paragraph briefing:\n"
        f"1. What this company does and its specific role in the {sector_display} supply chain\n"
        f"2. Key relationships: who are their customers, and why are those customers dependent on them?\n"
        f"3. Most significant recent catalyst or risk to their necessity in the chain\n\n"
        f"Be factual. Focus on why this company is structurally necessary, not just what they do."
    )

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://api.perplexity.ai")
        resp = client.chat.completions.create(
            model="sonar",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0.2,
        )
        text = resp.choices[0].message.content.strip()
        return text if text else None
    except Exception:
        return None
