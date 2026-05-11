"""Manual X Feed Scout — 16-pass sector sweep with full archival.

User pastes Grok output per sector → parse → velocity_z → merge → AKG.
Zero API calls. All raw pastes archived verbatim for backtesting.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from .x_feed_scout import (
    _compute_batch_velocity_z,
    _extract_json_payload,
    _is_valid_ticker,
    SENTIMENT_MAP,
    SKIP_SYMBOLS,
)

VELOCITY_MAP = {
    "ACCELERATING": "rising",
    "STEADY": "stable",
    "FADING": "falling",
}

PASS_CONFIGS: List[Dict[str, str]] = [
    {"pass": 1, "label": "Technology & Semiconductors", "type": "sector"},
    {"pass": 2, "label": "Healthcare & Biotech", "type": "sector"},
    {"pass": 3, "label": "Financials & Fintech", "type": "sector"},
    {"pass": 4, "label": "Consumer Discretionary", "type": "sector"},
    {"pass": 5, "label": "Consumer Staples", "type": "sector"},
    {"pass": 6, "label": "Energy", "type": "sector"},
    {"pass": 7, "label": "Industrials & Defense", "type": "sector"},
    {"pass": 8, "label": "Materials & Mining", "type": "sector"},
    {"pass": 9, "label": "Real Estate & Utilities", "type": "sector"},
    {"pass": 10, "label": "Communication Services", "type": "sector"},
    {"pass": 11, "label": "Small Cap & Emerging", "type": "sector"},
    {"pass": 12, "label": "Cross-Sector / Thematic", "type": "thematic"},
    {"pass": 13, "label": "Contrarian & Silent Movers", "type": "contrarian"},
    {"pass": 14, "label": "Unusual Options Activity", "type": "options_flow"},
    {"pass": 15, "label": "Market GEX / Dealer Gamma", "type": "gex_regime"},
    {"pass": 16, "label": "Blindspot & Unmapped Ticker Audit", "type": "blindspot"},
]

PASS_NUMBERS: Tuple[int, ...] = tuple(int(cfg["pass"]) for cfg in PASS_CONFIGS)
_PASS_FILE_RE = re.compile(r"^pass_(\d{2})(?:_v\d+)?\.json$")

_MICRO_CATALYST_TAGS = {
    "earnings", "earnings_beat", "earnings_catalyst", "analyst_upgrade",
    "guidance_outlook", "post_earnings_reaction", "fda_label_expansion",
    "phase_3_clinical_success", "acquisition_speculation", "m_a_bid",
    "acquisition_proposal", "financing_doubts", "breakout_retest",
    "ceo_warning",
}

_CANONICAL_THEME_ALIASES = {
    "ai_memory": "ai_data_center_infrastructure",
    "hbm": "ai_data_center_infrastructure",
    "data_center": "ai_data_center_infrastructure",
    "ai_data_center": "ai_data_center_infrastructure",
    "ai_demand": "ai_data_center_infrastructure",
    "rare_earth_magnets": "critical_minerals_supply_chain",
    "rare_earth_setups": "critical_minerals_supply_chain",
    "critical_minerals": "critical_minerals_supply_chain",
    "oil_price_surge": "oil_supply_shock",
    "hormuz_closure": "oil_supply_shock",
    "geopolitical_supply_shock": "oil_supply_shock",
    "drone_programs": "defense_autonomy",
    "directed_energy": "defense_autonomy",
    "military_readiness": "defense_autonomy",
    "humanoid_robots": "robotics_automation",
}

_CATALYST_THEME_PATTERNS = [
    ("ai_data_center_infrastructure", re.compile(r"\b(AI|HBM|data centers?|hyperscaler|Blackwell|ASIC|memory)\b", re.I)),
    ("critical_minerals_supply_chain", re.compile(r"\b(rare earth|critical mineral|magnet|lithium|copper|uranium)\b", re.I)),
    ("oil_supply_shock", re.compile(r"\b(Hormuz|oil supply|crude|OPEC|geopolitical supply)\b", re.I)),
    ("defense_autonomy", re.compile(r"\b(drone|directed energy|missile|defense|military|Pentagon)\b", re.I)),
    ("robotics_automation", re.compile(r"\b(robot|humanoid|automation)\b", re.I)),
    ("grid_power_infrastructure", re.compile(r"\b(grid|power demand|electricity|utility|nuclear|SMR)\b", re.I)),
]

_SECTOR_PROMPT_TEMPLATE = """\
You are a financial markets analyst scanning X (Twitter) right now.

TASK: Find US stock tickers in the {SECTOR} sector with unusual social attention in the last 24 hours.

WHAT COUNTS AS "UNUSUAL ATTENTION":
- Ticker mentioned by 3+ distinct accounts in the last 24 hours
- Mention volume visibly above its normal baseline (not just steady chatter)
- Active debate or disagreement between traders (not just news retweets)
- Specific catalyst driving the attention (earnings, FDA, M&A, guidance, insider activity)

WHAT DOES NOT COUNT — DO NOT INCLUDE:
- Tickers you "expect" to be trending because they are large-cap names — only include if you find actual posts
- Generic sector commentary not tied to a specific ticker
- Tickers where the only "catalyst" is price movement with no discussion of why
- Any ticker where you cannot point to at least one real post or account discussing it

SOURCE ATTRIBUTION: For each ticker, cite at least one X account or post. If you cannot find a real source, write "NO_SOURCE_FOUND" in the catalyst field. Entries with NO_SOURCE_FOUND are acceptable but will be weighted lower downstream.

SCOPE: US equities only. No crypto, no indices (no SPY/SPX/QQQ), no forex, no ETFs tracking indices.

CALIBRATION:
- VERY_BULLISH: multiple accounts calling for breakout, price targets being raised, >10 bullish posts
- BULLISH: net positive tone, buying interest, 5-10 supportive posts
- NEUTRAL: mixed or balanced debate, no clear directional lean
- BEARISH: net negative tone, selling pressure, warnings, 5-10 negative posts
- VERY_BEARISH: multiple accounts calling for crash/short, downgrades, >10 bearish posts
- ACCELERATING: buzz volume increasing hour-over-hour or day-over-day
- STEADY: consistent mention rate, not growing or shrinking
- FADING: buzz peaked earlier and is now declining

LOW DATA RULE: If the {SECTOR} sector genuinely has fewer than 5 tickers with unusual attention today, return only what you find. Do NOT pad the list with mega-caps that have normal-level chatter. A short honest list beats a long fabricated one.

EXAMPLE OF A GOOD ENTRY:
{{"ticker": "MRVL", "buzz_rank": 3, "sentiment": "BULLISH", "velocity": "ACCELERATING", "catalyst": "@SemiAnalysis and @ResearchDelta both flagging custom ASIC wins at MSFT and AMZN, 8+ posts in last 6 hours", "sector": "Technology"}}

EXAMPLE OF A BAD ENTRY (do NOT return entries like this):
{{"ticker": "AAPL", "buzz_rank": 1, "sentiment": "BULLISH", "velocity": "STEADY", "catalyst": "Apple continues to be a popular stock among investors", "sector": "Technology"}}

Return up to 30 tickers ranked by buzz. Return JSON only — no prose before or after:

{{"trending": [{{"ticker": "NVDA", "buzz_rank": 1, "sentiment": "BULLISH", "velocity": "ACCELERATING", "catalyst": "@account: specific reason with detail", "sector": "Technology", "accounts_cited": ["@account"], "theme_links": ["ai_infrastructure"], "co_mentions": ["AMD", "MRVL"], "why_this_is_new": "new today vs prior chatter", "order_type": "first_order"}}, ...]}}

Field rules:
- buzz_rank: integer, 1 = most talked about
- sentiment: VERY_BULLISH | BULLISH | NEUTRAL | BEARISH | VERY_BEARISH
- velocity: ACCELERATING | STEADY | FADING
- catalyst: MUST include @account or specific source. One sentence with specific detail, not generic. If no source found, write "NO_SOURCE_FOUND: [general observation]"
- sector: GICS sector label
- accounts_cited: X accounts explicitly cited; empty only if NO_SOURCE_FOUND
- theme_links: snake_case themes connected to this ticker
- co_mentions: related US equity tickers mentioned in the same thesis
- why_this_is_new: one sentence explaining novelty/acceleration today
- order_type: first_order | second_order | hedge | unknown"""

_THEMATIC_PROMPT = """\
You are a financial markets analyst scanning X (Twitter) right now.

TASK: Identify cross-sector investment themes driving unusual stock attention in the last 24 hours.
Look for: supply chain plays, second-order beneficiaries, policy-driven rotations, emerging narratives, and regime shifts.

WHAT COUNTS AS A "THEME":
- A narrative connecting 3+ tickers across sectors (e.g., "AI infrastructure buildout" linking semis + utilities + REITs)
- A policy or macro event creating winners/losers across sectors (e.g., tariff announcement, rate decision)
- A supply chain disruption creating second-order plays (e.g., port strike benefiting rail + air freight)
- Must be supported by actual posts/discussion on X, not just your inference

WHAT DOES NOT COUNT:
- Single-stock stories (that belongs in sector passes)
- Themes you "expect" to be trending without finding posts about them
- Generic themes like "tech is doing well" without a specific catalyst

SOURCE ATTRIBUTION: For each ticker, cite the @account or post driving the discussion. If you cannot find a real source, write "NO_SOURCE_FOUND" in catalyst.

SCOPE: US equities only. No crypto, no indices, no forex.

LOW DATA RULE: If you find fewer than 3 genuine cross-sector themes, return only what you find. Do NOT invent themes to fill space.

EXAMPLE OF A GOOD THEME:
{"theme": "nuclear_renaissance", "sectors": ["Utilities", "Industrials", "Materials"], "conviction": 0.8, "reasoning": "@EnergyArb and @NuclearTwit flagging 5 utility CEOs mentioning SMR commitments in Q4 calls, driving OKLO, SMR, CCJ, VST discussion"}

EXAMPLE OF A BAD THEME (do NOT return like this):
{"theme": "tech_growth", "sectors": ["Technology"], "conviction": 0.7, "reasoning": "Technology stocks continue to attract investor interest"}

Return up to 30 tickers ranked by buzz. Return JSON only — no prose before or after:

{"trending": [{"ticker": "NVDA", "buzz_rank": 1, "sentiment": "BULLISH", "velocity": "ACCELERATING", "catalyst": "@account: specific reason", "sector": "Technology"}, ...], "active_themes": [{"theme": "snake_case_name", "sectors": ["Sector1", "Sector2"], "conviction": 0.9, "reasoning": "one sentence with @source and specific detail"}]}

Field rules:
- buzz_rank: integer, 1 = most talked about
- sentiment: VERY_BULLISH | BULLISH | NEUTRAL | BEARISH | VERY_BEARISH
- velocity: ACCELERATING | STEADY | FADING
- catalyst: MUST include @account or "NO_SOURCE_FOUND". One specific sentence, not generic.
- sector: GICS sector label
- active_themes: each theme has snake_case name, linked sectors, conviction 0-1, one-sentence reasoning with source attribution"""

_CONTRARIAN_PROMPT = """\
You are a financial markets analyst scanning X (Twitter) right now.

TASK: Find US stock tickers that are contrarian opportunities — where social consensus is likely wrong.

WHAT COUNTS AS A CONTRARIAN SIGNAL:
- Heavily shorted name where short thesis is weakening (cite the @account or data point showing the shift)
- Stock with BEARISH social sentiment but improving fundamentals (earnings beat, guidance raise, insider buying)
- Zero-buzz name with quiet institutional accumulation (dark pool prints, 13F filings, block trades)
- Consensus "dead money" name where a catalyst is being overlooked
- Stock where bears are loudest but price is quietly making higher lows

WHAT DOES NOT COUNT:
- Cheap stocks that are cheap for good reason with no catalyst for change
- Your own opinion about what "should" be contrarian without finding X posts about it
- Names that are bearish AND deserve to be bearish — contrarian requires a reason the crowd is wrong
- General "value investing" picks without a specific contrarian trigger

EVIDENCE RULE: For each entry, you MUST explain WHY the crowd is wrong. The catalyst field must name the specific disconnect between sentiment and reality.

SOURCE ATTRIBUTION: Cite @accounts discussing the contrarian angle. "NO_SOURCE_FOUND" is acceptable but weighted lower.

SCOPE: US equities only. No crypto, no indices, no forex.

LOW DATA RULE: If you find fewer than 5 genuine contrarian setups, return only what you find. A short honest list of real contrarian signals beats 30 fabricated ones.

EXAMPLE OF A GOOD ENTRY:
{"ticker": "INTC", "buzz_rank": 1, "sentiment": "BEARISH", "velocity": "FADING", "catalyst": "@DeepValueETF flagging INTC 18A test chip yield at 85%+ while social sentiment still pricing in foundry failure — disconnect between technical progress and crowd narrative", "sector": "Technology"}

EXAMPLE OF A BAD ENTRY (do NOT return like this):
{"ticker": "F", "buzz_rank": 5, "sentiment": "BEARISH", "velocity": "STEADY", "catalyst": "Ford is undervalued compared to peers", "sector": "Consumer Discretionary"}

Return up to 30 tickers ranked by contrarian signal strength. Return JSON only — no prose before or after:

{"trending": [{"ticker": "INTC", "buzz_rank": 1, "sentiment": "BEARISH", "velocity": "FADING", "catalyst": "@account: specific contrarian thesis with named disconnect", "sector": "Technology"}, ...]}

Field rules:
- buzz_rank: integer, 1 = strongest contrarian signal
- sentiment: VERY_BULLISH | BULLISH | NEUTRAL | BEARISH | VERY_BEARISH (this is the CROWD's sentiment, not yours)
- velocity: ACCELERATING | STEADY | FADING (is the contrarian thesis gaining or losing traction?)
- catalyst: MUST explain the specific disconnect between crowd sentiment and reality. Include @account or "NO_SOURCE_FOUND".
- sector: GICS sector label"""


_OPTIONS_FLOW_PROMPT = """\
You are a quantitative options flow analyst. Your ONLY job is to find posts from dedicated options flow tracking accounts on X (Twitter) that report specific, verifiable unusual options trades on individual US equities.

SOURCES TO SCAN: Posts from accounts like @unusual_whales, @PellegriniFlow, @optionflow, @FlowAlgo, @caborotate, @DarkPoolData, @InsiderFinance, @SwaggyStocks, @OptionsHawk, @ConvexValue, and similar options flow aggregators. If you cannot find a post from a real flow account, DO NOT fabricate one — omit the ticker.

WHAT COUNTS AS UNUSUAL OPTIONS FLOW:
- Call or put sweeps at the ask with specific strike/expiry and dollar premium
- Block trades with named size (e.g. "$4M in BABA 200C June")
- Unusual open interest spikes with specific contract details
- Dark pool prints on individual stocks with share count and price

WHAT DOES NOT COUNT — DO NOT INCLUDE:
- General market sentiment or opinions about a stock
- Index-level flow (no SPY, SPX, QQQ, IWM, DIA — skip these entirely)
- ETF flow (no XLE, XLF, XLK, etc.)
- Geopolitical speculation or news headlines
- Insider trading reports or SEC filings
- Price action observations without a specific options trade attached
- Any entry where you cannot name the strike price, expiry, or premium size

CONSOLIDATION: If multiple flow accounts post about the same ticker, that is 1 entry with accounts_flagged = the number of distinct accounts. Higher accounts_flagged = stronger signal.

EVIDENCE RULE: For each entry, you MUST cite the X account that posted it. If you cannot attribute a flow observation to a specific account, write "NOT_FOUND" in the detail field. Entries with NOT_FOUND are acceptable but will be weighted lower.

EXAMPLE OF A GOOD ENTRY:
{"ticker": "BABA", "flow_type": "sweep", "direction": "calls", "expiry_bucket": "monthly", "premium_size": "whale", "accounts_flagged": 3, "detail": "@unusual_whales: $4.2M in BABA 200C June swept at ask, 8,500 contracts"}

EXAMPLE OF A BAD ENTRY (do not return entries like this):
{"ticker": "XOM", "flow_type": "sweep", "direction": "calls", "expiry_bucket": "monthly", "premium_size": "large", "accounts_flagged": 1, "detail": "Oil prices rising, bullish sentiment on energy stocks"}

Return up to 30 individual equity tickers ranked by flow significance. Return JSON only — no prose before or after:

{"trending": [{"ticker": "BABA", "buzz_rank": 1, "sentiment": "BULLISH", "velocity": "ACCELERATING", "catalyst": "$4.2M call sweep at 200 strike June expiry", "sector": "Consumer Discretionary"}, ...], "options_flow": [{"ticker": "BABA", "flow_type": "sweep", "direction": "calls", "expiry_bucket": "monthly", "premium_size": "whale", "accounts_flagged": 3, "detail": "@unusual_whales: $4.2M in BABA 200C June swept at ask, 8,500 contracts"}, ...]}

Field rules:
- buzz_rank: integer, 1 = most significant flow
- sentiment: VERY_BULLISH | BULLISH | NEUTRAL | BEARISH | VERY_BEARISH
- velocity: ACCELERATING | STEADY | FADING
- catalyst: describe the specific options trade, NOT general news
- sector: GICS sector label
- flow_type: sweep | block | dark_pool | unusual_oi
- direction: calls | puts | mixed
- expiry_bucket: weekly | monthly | leaps
- premium_size: small (<$500K) | medium ($500K-$2M) | large ($2M-$5M) | whale (>$5M)
- accounts_flagged: integer, how many distinct X flow accounts posted about this ticker
- detail: MUST start with @account_name or "NOT_FOUND". Include strike, expiry, premium, and contract count where available"""


_GEX_REGIME_PROMPT = """\
You are a financial markets analyst scanning X (Twitter) right now.

TASK: Assess the current SPY/SPX gamma exposure (GEX) regime and key dealer positioning levels.

SOURCES TO CHECK: @SqueezeMetrics, @spotgamma, @GEXBot, @Tier1Alpha, @VolSignals, @MacroUnchained, any GEX/DIX discussion.

WHAT TO REPORT:
1. Net GEX level (positive = long gamma = supportive, negative = short gamma = fragile)
2. Key gamma strike (the SPX/SPY strike with highest OI concentration — the "pin")
3. Gamma flip level (strike where dealer gamma flips from long to short)
4. DIX reading if available (Dark Index — high = institutional accumulation)
5. Vol regime context (VIX level, term structure contango/backwardation)

WHAT DOES NOT COUNT:
- Your own opinion about what GEX "should" be — only report what sources are posting
- Inferred GEX from price action alone — GEX requires options positioning data
- Stale data from more than 2 days ago — flag if the most recent post you find is old

LOW DATA RULE: If you cannot find GEX-specific posts from the accounts above, set net_gex to "NEUTRAL", gex_magnitude to "low", strikes to 0, and write "NO GEX DATA FOUND — sources checked but no recent posts" in regime_summary. Do NOT fabricate levels.

Return JSON only — no prose before or after:

{"gex_regime": {"net_gex": "LONG_GAMMA", "gex_magnitude": "elevated", "key_pin_strike": 570, "gamma_flip_strike": 555, "dix_reading": 0.45, "dix_signal": "accumulation", "vix_level": 18.5, "vix_term_structure": "contango", "regime_summary": "Dealers long gamma above 555, supportive for mean-reversion. Pin at 570 likely to cap upside. DIX elevated suggesting institutional accumulation.", "sources_cited": ["@spotgamma", "@SqueezeMetrics"], "data_freshness": "2026-03-07"}}

Field rules:
- net_gex: LONG_GAMMA | SHORT_GAMMA | NEUTRAL
- gex_magnitude: extreme | elevated | moderate | low
- key_pin_strike: integer SPX strike (or 0 if unknown)
- gamma_flip_strike: integer SPX strike (or 0 if unknown)
- dix_reading: float 0-1 (or null if unavailable)
- dix_signal: accumulation | distribution | neutral | unknown
- vix_level: float (or null)
- vix_term_structure: contango | flat | backwardation | unknown
- regime_summary: one specific paragraph with actionable context. MUST cite @accounts. If no data found, say so.
- sources_cited: list of @accounts cited (empty list if none found)
- data_freshness: YYYY-MM-DD of the data being reported"""


_BLINDSPOT_AUDIT_SEEDS = ("NOK", "AAOI", "PENG", "P", "MP", "SKYX")

_BLINDSPOT_PROMPT_TEMPLATE = """\
You are a financial markets analyst scanning X (Twitter) right now.

TASK: Find US-listed common stocks and ADRs with unusual stock-specific X attention in the last 24 hours that the prior 15-pass manual X-feed sweep likely missed.

This is a BLINDSPOT AUDIT, not a normal sector list. Look especially for:
- ADRs or foreign issuers with US-listed tickers that sector prompts may skip
- Single-letter or ambiguous tickers such as P
- Small/microcap names that do not fit cleanly into one sector label
- Cross-classified companies where posts use product language instead of GICS sector language
- Second-order suppliers, component vendors, contract manufacturers, or infrastructure beneficiaries
- Tickers present only as co-mentions in earlier passes but now deserving their own entry

KNOWN CONTEXT FROM PASSES 1-15:
{CAPTURED_CONTEXT}

WATCHLIST AUDIT SEEDS:
{AUDIT_SEEDS}

Seed rule: audit seeds are allowed, but label them target_seeded=true. Do not force them into output unless you find real recent X evidence. Also search organically beyond the seed list.

WHAT COUNTS:
- Specific US-listed stock or ADR with 3+ distinct X accounts or a credible high-signal account discussing it in the last 24 hours
- Evidence that explains why earlier prompts missed it
- Ticker disambiguation for ambiguous symbols, ADRs, or one-letter tickers
- A source account or post for every entry

WHAT DOES NOT COUNT:
- Tickers already captured directly in passes 1-15 unless the blindspot is a materially different thesis
- Generic watchlist names with no fresh X posts
- Crypto, indices, ETFs, forex, OTC-only names unless explicitly noted as not eligible
- Pure price movement without a post-level catalyst
- Fabricated source attribution

Return up to 30 tickers ranked by blindspot importance. Return JSON only — no prose before or after:

{"trending": [{"ticker": "NOK", "buzz_rank": 1, "sentiment": "BULLISH", "velocity": "ACCELERATING", "catalyst": "@account: specific source-backed reason this was missed", "sector": "Technology", "accounts_cited": ["@account"], "theme_links": ["private_wireless", "networking_reacceleration"], "co_mentions": ["ERIC", "CSCO"], "why_this_is_new": "new today vs prior chatter", "order_type": "second_order", "already_seen_status": "not_seen", "why_15_passes_missed_it": "ADR plus telecom/networking cross-classification likely fell between Technology and Communication Services prompts", "best_existing_pass": 1, "new_theme_if_needed": "private_wireless_ai_edge", "ticker_disambiguation": "Nokia Oyj ADR, NYSE:NOK", "target_seeded": true, "should_add_to_prompt_map": false}, ...]}

Field rules:
- buzz_rank: integer, 1 = strongest blindspot
- sentiment: VERY_BULLISH | BULLISH | NEUTRAL | BEARISH | VERY_BEARISH
- velocity: ACCELERATING | STEADY | FADING
- catalyst: MUST start with @account or "NO_SOURCE_FOUND". One specific sentence; no generic prose.
- sector: best GICS sector label, even if the reason it was missed is cross-sector ambiguity
- accounts_cited: X accounts explicitly cited; empty only if NO_SOURCE_FOUND
- theme_links: snake_case themes connected to this ticker
- co_mentions: related US equity tickers mentioned in the same thesis
- why_this_is_new: one sentence explaining novelty/acceleration today
- order_type: first_order | second_order | hedge | unknown
- already_seen_status: not_seen | already_captured | co_mentioned_only | theme_seen
- why_15_passes_missed_it: specific prompt-map blindspot, not generic "missed by prior prompts"
- best_existing_pass: integer 1-15 for where it should have been caught, or 0 if no existing pass fits
- new_theme_if_needed: snake_case theme name only if current theme map lacks the right bucket
- ticker_disambiguation: company/security identity, exchange if useful, and ADR/common-stock note when relevant
- target_seeded: true if found because of the audit seed list, otherwise false
- should_add_to_prompt_map: true only if this reveals a recurring structural prompt gap"""


def _blindspot_context(as_of_date: str = "") -> str:
    merged = load_merged(as_of_date) if as_of_date else {}
    captured = sorted(str(symbol).upper().strip() for symbol in merged.keys() if str(symbol).strip())
    co_mentions = sorted({
        symbol
        for row in merged.values()
        for symbol in _normalize_symbol_list(row.get("co_mentions", []))
        if symbol not in captured
    })
    themes = sorted({
        _theme_key(theme)
        for row in merged.values()
        for theme in _normalize_string_list(row.get("theme_links", []) or row.get("raw_theme_links", []))
        if _theme_key(theme)
    })
    payload = {
        "captured_count": len(captured),
        "captured_tickers": captured[:150],
        "co_mentions_not_directly_captured": co_mentions[:150],
        "theme_links_seen": themes[:100],
    }
    return json.dumps(payload, separators=(",", ":"))


def _blindspot_prompt(as_of_date: str = "") -> str:
    return (
        _BLINDSPOT_PROMPT_TEMPLATE
        .replace("{CAPTURED_CONTEXT}", _blindspot_context(as_of_date))
        .replace("{AUDIT_SEEDS}", ", ".join(_BLINDSPOT_AUDIT_SEEDS))
    )


def generate_prompts(as_of_date: str = "") -> List[Tuple[int, str, str]]:
    """Return (pass_num, label, prompt_text) for all passes."""
    result = []
    for cfg in PASS_CONFIGS:
        pnum = cfg["pass"]
        label = cfg["label"]
        ptype = cfg["type"]
        if ptype == "thematic":
            prompt = _THEMATIC_PROMPT
        elif ptype == "contrarian":
            prompt = _CONTRARIAN_PROMPT
        elif ptype == "options_flow":
            prompt = _OPTIONS_FLOW_PROMPT
        elif ptype == "gex_regime":
            prompt = _GEX_REGIME_PROMPT
        elif ptype == "blindspot":
            prompt = _blindspot_prompt(as_of_date)
        else:
            prompt = _SECTOR_PROMPT_TEMPLATE.format(SECTOR=label)
        result.append((pnum, label, prompt))
    return result


def _strip_markdown_fence(raw_text: str) -> str:
    text = str(raw_text or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines[1:] if not line.strip().startswith("```")]
        text = "\n".join(lines)
    return text


def parse_pass(raw_text: str, pass_num: int) -> List[Dict[str, Any]]:
    """Extract ticker entries from raw Grok paste. Returns list of internal dicts."""
    text = _strip_markdown_fence(raw_text)

    parsed = _extract_json_payload(text)
    if not isinstance(parsed, dict):
        return []

    now_iso = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    pass_cfg = PASS_CONFIGS[pass_num - 1] if 1 <= pass_num <= len(PASS_CONFIGS) else {}
    pass_type = pass_cfg.get("type", "sector")

    # Normalize alternate top-level keys to "trending"
    if "trending" not in parsed:
        for alt_key in ("contrarian_signals", "options_flow"):
            if alt_key in parsed and isinstance(parsed[alt_key], list):
                parsed["trending"] = parsed.pop(alt_key)
                break

    entries = []
    for item in parsed.get("trending", []):
        ticker = str(item.get("ticker", "")).strip().upper().replace(".", "-")
        if not _is_valid_ticker(ticker):
            continue

        buzz_rank = int(item.get("buzz_rank", 0) or 0)
        raw_sentiment = str(item.get("sentiment", "")).strip().upper()
        sentiment = SENTIMENT_MAP.get(raw_sentiment, 0.0)
        raw_velocity = str(item.get("velocity", "")).strip().upper()
        velocity_trend = VELOCITY_MAP.get(raw_velocity, "stable")
        catalyst = str(item.get("catalyst", ""))[:200]
        sector = str(item.get("sector", ""))[:50]

        accounts_cited = _normalize_accounts(item.get("accounts_cited")) or _extract_accounts(catalyst)
        raw_theme_links = _normalize_string_list(item.get("theme_links") or item.get("themes"))
        theme_links, catalyst_tags = _normalize_themes(raw_theme_links, catalyst)
        co_mentions = [s for s in _normalize_symbol_list(item.get("co_mentions")) if s != ticker]
        no_source = "NO_SOURCE_FOUND" in catalyst.upper() or not accounts_cited
        extra_fields: Dict[str, Any] = {}
        if pass_type == "blindspot":
            try:
                best_existing_pass = int(item.get("best_existing_pass", 0) or 0)
            except (TypeError, ValueError):
                best_existing_pass = 0
            extra_fields = {
                "already_seen_status": str(item.get("already_seen_status", "unknown") or "unknown")[:40],
                "why_15_passes_missed_it": str(item.get("why_15_passes_missed_it", ""))[:240],
                "best_existing_pass": best_existing_pass,
                "new_theme_if_needed": _theme_key(str(item.get("new_theme_if_needed", "") or ""))[:80],
                "ticker_disambiguation": str(item.get("ticker_disambiguation", ""))[:160],
                "target_seeded": bool(item.get("target_seeded", False)),
                "should_add_to_prompt_map": bool(item.get("should_add_to_prompt_map", False)),
            }

        row = {
            "ticker": ticker,
            "buzz_rank": buzz_rank,
            "mentions_estimate": buzz_rank,
            "sentiment": sentiment,
            "velocity_trend": velocity_trend,
            "catalyst": catalyst,
            "sector": sector,
            "pass_number": pass_num,
            "source_pass_type": pass_type,
            "timestamp": now_iso,
            "accounts_cited": accounts_cited,
            "raw_theme_links": raw_theme_links,
            "theme_links": theme_links,
            "catalyst_tags": catalyst_tags,
            "co_mentions": co_mentions,
            "why_this_is_new": str(item.get("why_this_is_new", ""))[:240],
            "order_type": str(item.get("order_type", "unknown") or "unknown")[:30],
            "source_quality": "unverified" if no_source else "cited",
            "no_source_found": bool(no_source),
        }
        row.update(extra_fields)
        entries.append(row)

    return entries


def _normalize_string_list(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    values: List[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text and text not in values:
            values.append(text[:80])
    return values


def _normalize_accounts(raw: Any) -> List[str]:
    accounts = []
    for item in _normalize_string_list(raw):
        if not item.startswith("@"):
            item = "@" + item.lstrip("@")
        if re.match(r"^@[A-Za-z0-9_]{1,15}$", item) and item not in accounts:
            accounts.append(item)
    return accounts


def _extract_accounts(text: str) -> List[str]:
    return _normalize_accounts(re.findall(r"@[A-Za-z0-9_]{1,15}", str(text or "")))


def _normalize_symbol_list(raw: Any) -> List[str]:
    symbols = []
    for item in _normalize_string_list(raw):
        ticker = item.strip().upper().replace(".", "-")
        if _is_valid_ticker(ticker) and ticker not in symbols:
            symbols.append(ticker)
    return symbols


def _theme_key(raw: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(raw or "").strip().lower()).strip("_")


def _normalize_themes(raw_theme_links: List[str], catalyst: str) -> Tuple[List[str], List[str]]:
    themes: List[str] = []
    catalyst_tags: List[str] = []

    for raw in raw_theme_links:
        key = _theme_key(raw)
        if not key:
            continue
        if key in _MICRO_CATALYST_TAGS:
            if key not in catalyst_tags:
                catalyst_tags.append(key)
            continue
        canonical = _CANONICAL_THEME_ALIASES.get(key, key)
        if canonical not in themes:
            themes.append(canonical)

    for canonical, pattern in _CATALYST_THEME_PATTERNS:
        if pattern.search(str(catalyst or "")) and canonical not in themes:
            themes.append(canonical)

    return themes, catalyst_tags


def _extract_options_flow_payload(raw_text: str, pass_num: int) -> List[Dict[str, Any]]:
    if pass_num != 14:
        return []
    parsed = _extract_json_payload(_strip_markdown_fence(raw_text))
    if not isinstance(parsed, dict):
        return []
    options_flow = parsed.get("options_flow", [])
    return list(options_flow) if isinstance(options_flow, list) else []


def _entries_from_options_flow(
    options_flow: List[Dict[str, Any]],
    pass_num: int,
) -> List[Dict[str, Any]]:
    """Build minimal ticker entries for pass 14 when only options_flow is present."""
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    pass_cfg = PASS_CONFIGS[pass_num - 1] if 1 <= pass_num <= len(PASS_CONFIGS) else {}
    pass_type = pass_cfg.get("type", "options_flow")

    entries: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for idx, flow in enumerate(options_flow, start=1):
        if not isinstance(flow, dict):
            continue
        ticker = str(flow.get("ticker", "")).strip().upper().replace(".", "-")
        if not _is_valid_ticker(ticker) or ticker in seen:
            continue
        seen.add(ticker)

        direction = str(flow.get("direction", "")).strip().upper()
        if direction == "CALLS":
            sentiment = 0.5
        elif direction == "PUTS":
            sentiment = -0.5
        else:
            sentiment = 0.0

        try:
            mentions_estimate = int(flow.get("accounts_flagged", 0) or 0)
        except (TypeError, ValueError):
            mentions_estimate = 0
        if mentions_estimate <= 0:
            mentions_estimate = idx

        flow_type = str(flow.get("flow_type", "")).strip().lower() or "flow"
        detail = str(flow.get("detail", "")).strip()
        catalyst = str(flow.get("catalyst", "")).strip() or detail
        if not catalyst:
            catalyst = f"options_flow:{flow_type}/{direction.lower() or 'mixed'}"

        entries.append({
            "ticker": ticker,
            "mentions_estimate": mentions_estimate,
            "sentiment": sentiment,
            "velocity_trend": "stable",
            "catalyst": catalyst[:200],
            "sector": str(flow.get("sector", ""))[:50],
            "pass_number": pass_num,
            "source_pass_type": pass_type,
            "timestamp": now_iso,
        })
    return entries


def _raw_dir(as_of_date: str) -> str:
    return os.path.join("eval_results", "x_feed", as_of_date, "raw")


def save_raw_pass(as_of_date: str, pass_num: int, raw_text: str) -> str:
    """Archive raw paste verbatim. Never overwrites — adds _v2, _v3 on collision."""
    d = _raw_dir(as_of_date)
    os.makedirs(d, exist_ok=True)
    base = f"pass_{pass_num:02d}.json"
    path = os.path.join(d, base)
    if os.path.exists(path):
        v = 2
        while True:
            path = os.path.join(d, f"pass_{pass_num:02d}_v{v}.json")
            if not os.path.exists(path):
                break
            v += 1
    with open(path, "w") as f:
        f.write(raw_text)
    return path


def _merged_path(as_of_date: str) -> str:
    return os.path.join("eval_results", "x_feed", as_of_date, "merged.json")


def _theme_graph_path(as_of_date: str) -> str:
    return os.path.join("eval_results", "x_feed", as_of_date, "theme_emergence_graph.json")


def _final_manifest_path(as_of_date: str) -> str:
    return os.path.join("eval_results", "x_feed", as_of_date, "final_manifest.json")


def get_readiness(as_of_date: str) -> Dict[str, Any]:
    """Return manual X-feed readiness for a given date."""
    raw_dir = _raw_dir(as_of_date)
    completed_passes = set()
    raw_archives: List[str] = []
    if os.path.isdir(raw_dir):
        for name in sorted(os.listdir(raw_dir)):
            match = _PASS_FILE_RE.match(name)
            if not match:
                continue
            completed_passes.add(int(match.group(1)))
            raw_archives.append(os.path.join(raw_dir, name))

    merged = load_merged(as_of_date)
    merged_path = _merged_path(as_of_date)
    graph_path = _theme_graph_path(as_of_date)
    manifest_path = _final_manifest_path(as_of_date)
    merged_exists = os.path.isfile(merged_path)
    graph_exists = os.path.isfile(graph_path)
    manifest = load_final_manifest(as_of_date)
    missing_passes = [p for p in PASS_NUMBERS if p not in completed_passes]
    finalized = bool(manifest.get("finalized")) and graph_exists
    ready = not missing_passes and merged_exists and bool(merged) and finalized

    return {
        "date": as_of_date,
        "required_passes": list(PASS_NUMBERS),
        "completed_passes": sorted(completed_passes),
        "missing_passes": missing_passes,
        "raw_archive_count": len(raw_archives),
        "raw_archives": raw_archives,
        "merged_exists": merged_exists,
        "merged_path": merged_path,
        "merged_symbol_count": len(merged),
        "theme_graph_exists": graph_exists,
        "theme_graph_path": graph_path,
        "final_manifest_exists": os.path.isfile(manifest_path),
        "final_manifest_path": manifest_path,
        "finalized": finalized,
        "ready": ready,
    }


def load_merged(as_of_date: str) -> Dict[str, Dict[str, Any]]:
    """Load merged dict keyed by ticker. Returns {} if absent."""
    path = _merged_path(as_of_date)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def load_recent_merged(
    as_of_date: str,
    *,
    lookback_days: int = 0,
    dealflow_base_dir: str = os.path.join("eval_results", "deal_flow"),
) -> Dict[str, Dict[str, Any]]:
    """Load same-day merged tickers plus recent unprocessed X-feed gaps.

    Prior dates are included only when their X-feed exists but no same-date dealflow
    directory was created. Newer dates win on duplicates.
    """
    try:
        as_of = dt.datetime.strptime(as_of_date, "%Y-%m-%d").date()
    except Exception:
        return load_merged(as_of_date)

    merged: Dict[str, Dict[str, Any]] = {}
    max_lookback = max(0, int(lookback_days or 0))
    for offset in range(max_lookback, -1, -1):
        source_date = str(as_of - dt.timedelta(days=offset))
        source_payload = load_merged(source_date)
        if not source_payload:
            continue
        if offset > 0:
            dealflow_dir = os.path.join(dealflow_base_dir, source_date)
            if os.path.isdir(dealflow_dir):
                continue
        for symbol, payload in source_payload.items():
            row = dict(payload or {})
            row.setdefault("ticker", str(symbol).upper().strip())
            row["x_feed_source_date"] = source_date
            row["x_feed_carryforward_days"] = int(offset)
            merged[str(symbol).upper().strip()] = row
    return merged


def save_merged(as_of_date: str, merged: Dict[str, Dict[str, Any]]) -> str:
    """Write merged dict. Returns path."""
    path = _merged_path(as_of_date)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(merged, f, indent=2)
    return path


def save_theme_emergence_graph(as_of_date: str, graph: Dict[str, Any]) -> str:
    path = _theme_graph_path(as_of_date)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(graph, f, indent=2)
    return path


def load_final_manifest(as_of_date: str) -> Dict[str, Any]:
    path = _final_manifest_path(as_of_date)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r") as f:
            payload = json.load(f)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def finalize_x_feed(as_of_date: str) -> Dict[str, Any]:
    """Rebuild final X-feed artifacts after all pass input is complete."""
    readiness = get_readiness_pre_finalize(as_of_date)
    merged = load_merged(as_of_date)
    graph = build_theme_emergence_graph(as_of_date, merged)
    graph_path = save_theme_emergence_graph(as_of_date, graph)

    pass_counts = {str(p): 0 for p in PASS_NUMBERS}
    duplicate_pass_symbols: Dict[str, List[int]] = {}
    for symbol, row in merged.items():
        seen: List[int] = []
        for evidence in list(row.get("evidence", []) or []):
            pnum = int(evidence.get("pass_number", 0) or 0)
            if pnum:
                pass_counts[str(pnum)] = int(pass_counts.get(str(pnum), 0)) + 1
                seen.append(pnum)
        if len(seen) != len(set(seen)):
            duplicate_pass_symbols[str(symbol)] = seen

    low_yield_passes = [int(p) for p, count in pass_counts.items() if int(count) == 0]
    manifest = {
        "date": as_of_date,
        "finalized": True,
        "finalized_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "completed_passes": list(readiness.get("completed_passes", [])),
        "missing_passes": list(readiness.get("missing_passes", [])),
        "symbol_count": len(merged),
        "theme_count": len(graph.get("themes", {}) or {}),
        "edge_count": len(graph.get("edges", []) or []),
        "filtered_one_ticker_theme_count": len(graph.get("filtered_one_ticker_themes", []) or []),
        "low_yield_passes": low_yield_passes,
        "pass_ticker_counts": pass_counts,
        "duplicate_pass_symbols": duplicate_pass_symbols,
        "merged_path": _merged_path(as_of_date),
        "theme_graph_path": graph_path,
        "ready_for_dealflow": not readiness.get("missing_passes") and bool(merged),
    }
    path = _final_manifest_path(as_of_date)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest


def get_readiness_pre_finalize(as_of_date: str) -> Dict[str, Any]:
    raw_dir = _raw_dir(as_of_date)
    completed_passes = set()
    raw_archives: List[str] = []
    if os.path.isdir(raw_dir):
        for name in sorted(os.listdir(raw_dir)):
            match = _PASS_FILE_RE.match(name)
            if not match:
                continue
            completed_passes.add(int(match.group(1)))
            raw_archives.append(os.path.join(raw_dir, name))
    merged = load_merged(as_of_date)
    missing_passes = [p for p in PASS_NUMBERS if p not in completed_passes]
    return {
        "date": as_of_date,
        "required_passes": list(PASS_NUMBERS),
        "completed_passes": sorted(completed_passes),
        "missing_passes": missing_passes,
        "raw_archive_count": len(raw_archives),
        "raw_archives": raw_archives,
        "merged_symbol_count": len(merged),
    }


def _merge_entry_preserving_evidence(merged: Dict[str, Dict[str, Any]], entry: Dict[str, Any]) -> None:
    ticker = str(entry.get("ticker", "")).upper().strip()
    if not ticker:
        return
    existing = dict(merged.get(ticker, {}) or {})
    evidence = list(existing.get("evidence", []) or [])
    observation = dict(entry)
    observation.pop("evidence", None)
    evidence.append(observation)

    cited_evidence = [e for e in evidence if not bool(e.get("no_source_found"))]
    score_rows = cited_evidence or evidence
    latest = dict(score_rows[-1])
    latest["ticker"] = ticker
    latest["evidence"] = evidence
    latest["pass_numbers"] = sorted({int(e.get("pass_number", 0) or 0) for e in evidence if e.get("pass_number")})
    latest["source_pass_types"] = sorted({str(e.get("source_pass_type", "")) for e in evidence if e.get("source_pass_type")})
    latest["accounts_cited"] = sorted({a for e in evidence for a in list(e.get("accounts_cited", []) or [])})
    latest["raw_theme_links"] = sorted({t for e in evidence for t in list(e.get("raw_theme_links", []) or [])})
    latest["theme_links"] = sorted({t for e in evidence for t in list(e.get("theme_links", []) or [])})
    latest["catalyst_tags"] = sorted({t for e in evidence for t in list(e.get("catalyst_tags", []) or [])})
    latest["co_mentions"] = sorted({s for e in evidence for s in list(e.get("co_mentions", []) or []) if s != ticker})
    latest["evidence_count"] = max(1, len(latest["accounts_cited"])) + max(0, len(evidence) - 1)
    latest["no_source_found"] = not bool(latest["accounts_cited"])
    latest["theme_emergence_score"] = _theme_emergence_score(latest)
    merged[ticker] = latest


def _theme_emergence_score(row: Dict[str, Any]) -> float:
    evidence = list(row.get("evidence", []) or [])
    accounts = set(row.get("accounts_cited", []) or [])
    themes = set(row.get("theme_links", []) or [])
    co_mentions = set(row.get("co_mentions", []) or [])
    velocity_bonus = {"rising": 18.0, "stable": 8.0, "falling": -6.0}.get(str(row.get("velocity_trend", "stable")), 0.0)
    source_penalty = -20.0 if row.get("no_source_found") else 0.0
    score = 35.0 + min(25.0, len(accounts) * 6.0) + min(15.0, len(themes) * 5.0) + min(10.0, len(co_mentions) * 2.0) + min(12.0, len(evidence) * 3.0) + velocity_bonus + source_penalty
    return float(round(max(0.0, min(100.0, score)), 4))


def build_theme_emergence_graph(as_of_date: str, merged: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    account_edges: List[Dict[str, Any]] = []
    theme_edges: List[Dict[str, Any]] = []
    co_mention_edges: List[Dict[str, Any]] = []
    themes: Dict[str, Dict[str, Any]] = {}
    tickers: Dict[str, Dict[str, Any]] = {}

    for ticker, row in sorted((merged or {}).items()):
        symbol = str(ticker).upper().strip()
        if not symbol:
            continue
        normalized_themes, catalyst_tags = _normalize_themes(
            _normalize_string_list(row.get("theme_links", []) or []),
            str(row.get("catalyst", "") or ""),
        )
        tickers[symbol] = {
            "theme_emergence_score": float(row.get("theme_emergence_score", 0.0) or 0.0),
            "evidence_count": int(row.get("evidence_count", 0) or 0),
            "accounts_cited": list(row.get("accounts_cited", []) or []),
            "theme_links": normalized_themes,
            "raw_theme_links": list(row.get("raw_theme_links", row.get("theme_links", [])) or []),
            "catalyst_tags": sorted(set(list(row.get("catalyst_tags", []) or []) + catalyst_tags)),
            "co_mentions": list(row.get("co_mentions", []) or []),
            "source_pass_types": list(row.get("source_pass_types", []) or []),
        }
        for account in row.get("accounts_cited", []) or []:
            account_edges.append({"from": account, "to": symbol, "type": "account_mentions_ticker"})
        for theme in normalized_themes:
            theme_edges.append({"from": symbol, "to": theme, "type": "ticker_linked_to_theme"})
            bucket = themes.setdefault(theme, {"tickers": set(), "accounts": set(), "sectors": set()})
            bucket["tickers"].add(symbol)
            bucket["accounts"].update(row.get("accounts_cited", []) or [])
            if row.get("sector"):
                bucket["sectors"].add(str(row.get("sector")))
        for peer in row.get("co_mentions", []) or []:
            co_mention_edges.append({"from": symbol, "to": peer, "type": "ticker_co_mentioned"})

    theme_rows = {}
    filtered_one_ticker_themes = []
    for theme, data in themes.items():
        tickerset = sorted(data["tickers"])
        accounts = sorted(data["accounts"])
        sectors = sorted(data["sectors"])
        if len(tickerset) < 2 and theme not in set(_CANONICAL_THEME_ALIASES.values()):
            filtered_one_ticker_themes.append(theme)
            continue
        theme_rows[theme] = {
            "tickers": tickerset,
            "accounts": accounts,
            "sectors": sectors,
            "theme_emergence_score": float(round(min(100.0, 30.0 + len(tickerset) * 8.0 + len(accounts) * 5.0 + len(sectors) * 4.0), 4)),
        }

    return {
        "date": as_of_date,
        "tickers": tickers,
        "themes": theme_rows,
        "filtered_one_ticker_themes": sorted(filtered_one_ticker_themes),
        "edges": account_edges + [e for e in theme_edges if e.get("to") in theme_rows] + co_mention_edges,
        "prompt_design_recommendation": {
            "keep_pass_count": 16,
            "reason": "Broad sector recall plus a final blindspot audit improves edge-case ticker capture; graph merge removes destructive overlap. Future compression can combine low-yield passes after yield telemetry.",
        },
    }


def ingest_pass(
    as_of_date: str,
    raw_text: str,
    pass_num: int,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Orchestrator: archive raw → parse → velocity_z → merge → AKG → xai cache.

    Returns summary dict with counts and entries.
    """
    # 1. Archive raw
    raw_path = save_raw_pass(as_of_date, pass_num, raw_text)

    # 2. Parse
    entries = parse_pass(raw_text, pass_num)
    options_flow = _extract_options_flow_payload(raw_text, pass_num)
    if pass_num == 14 and not entries and options_flow:
        entries = _entries_from_options_flow(options_flow, pass_num)
    # 2b. Extract GEX regime from pass 15 (before early return — no trending entries)
    gex_regime: Dict[str, Any] = {}
    if pass_num == 15:
        text = _strip_markdown_fence(raw_text)
        gex_parsed = _extract_json_payload(text)
        if isinstance(gex_parsed, dict):
            gex_regime = gex_parsed.get("gex_regime", {})

    merged_existing_count = len(load_merged(as_of_date))
    if not entries and not gex_regime:
        return {
            "pass_num": pass_num,
            "raw_path": raw_path,
            "tickers_parsed": 0,
            "tickers_merged": merged_existing_count,
            "akg_written": 0,
            "dry_run": dry_run,
            "entries": [],
            "themes": [],
            "options_flow": options_flow,
            "gex_regime": {},
        }

    if not entries and gex_regime:
        # GEX-only pass: no tickers to merge, but persist the regime data
        if dry_run:
            return {
                "pass_num": pass_num,
                "raw_path": raw_path,
                "tickers_parsed": 0,
                "tickers_merged": merged_existing_count,
                "akg_written": 0,
                "dry_run": True,
                "entries": [],
                "themes": [],
                "options_flow": options_flow,
                "gex_regime": gex_regime,
            }
        # Write GEX to AKG + state file
        akg_result = write_akg([], as_of_date, gex_regime=gex_regime)
        gex_state_path = os.path.join("eval_results", "control", "gex_regime_state.json")
        os.makedirs(os.path.dirname(gex_state_path), exist_ok=True)
        gex_state = dict(gex_regime)
        gex_state["gex_updated_at"] = as_of_date
        with open(gex_state_path, "w") as f:
            json.dump(gex_state, f, indent=2)
        return {
            "pass_num": pass_num,
            "raw_path": raw_path,
            "tickers_parsed": 0,
            "tickers_merged": merged_existing_count,
            "akg_written": akg_result.get("written", 0),
            "dry_run": False,
            "entries": [],
            "themes": [],
            "options_flow": options_flow,
            "gex_regime": gex_regime,
        }

    # 3. Compute velocity_z within this cohort
    cohort = {e["ticker"]: e for e in entries}
    _compute_batch_velocity_z(cohort)
    entries = list(cohort.values())

    # 4. Merge without losing prior-pass evidence.
    merged = load_merged(as_of_date)
    for e in entries:
        _merge_entry_preserving_evidence(merged, e)
    save_merged(as_of_date, merged)
    graph = build_theme_emergence_graph(as_of_date, merged)
    save_theme_emergence_graph(as_of_date, graph)

    # 5. Extract themes from pass 12
    themes = []
    if pass_num == 12:
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines[1:] if not l.strip().startswith("```")]
            text = "\n".join(lines)
        parsed = _extract_json_payload(text)
        if isinstance(parsed, dict):
            themes = parsed.get("active_themes", [])

    # 5b. Pass 14 options flow was extracted earlier (before empty-entry early return).

    if dry_run:
        return {
            "pass_num": pass_num,
            "raw_path": raw_path,
            "tickers_parsed": len(entries),
            "tickers_merged": len(merged),
            "akg_written": 0,
            "dry_run": True,
            "entries": entries,
            "themes": themes,
            "options_flow": options_flow,
            "gex_regime": gex_regime,
        }

    # 6. Write AKG
    akg_result = write_akg(entries, as_of_date, themes=themes, options_flow=options_flow, gex_regime=gex_regime)

    # 7. Persist GEX regime state for consumers (morning brief, portfolio plan)
    if gex_regime:
        gex_state_path = os.path.join("eval_results", "control", "gex_regime_state.json")
        os.makedirs(os.path.dirname(gex_state_path), exist_ok=True)
        gex_state = dict(gex_regime)
        gex_state["gex_updated_at"] = as_of_date
        with open(gex_state_path, "w") as f:
            json.dump(gex_state, f, indent=2)

    return {
        "pass_num": pass_num,
        "raw_path": raw_path,
        "tickers_parsed": len(entries),
        "tickers_merged": len(merged),
        "akg_written": akg_result.get("written", 0),
        "dry_run": False,
        "entries": entries,
        "themes": themes,
        "options_flow": options_flow,
        "gex_regime": gex_regime,
    }


def write_akg(
    entries: List[Dict[str, Any]],
    as_of_date: str,
    themes: Optional[List[Dict[str, Any]]] = None,
    options_flow: Optional[List[Dict[str, Any]]] = None,
    gex_regime: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Enrich AKG nodes with cashtag data. Returns {"written": int, "new": int}."""
    from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph

    akg = AeternusKnowledgeGraph.load()
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    new_count = 0
    written = 0

    # Index options_flow by ticker for matching
    flow_by_ticker: Dict[str, Dict[str, Any]] = {}
    for flow in (options_flow or []):
        t = str(flow.get("ticker", "")).strip().upper()
        if t:
            flow_by_ticker[t] = flow

    for entry in entries:
        ticker = entry["ticker"]
        is_new = ticker not in akg._nodes
        if is_new:
            akg.add_node(
                ticker,
                node_type="company",
                metadata={
                    "seed_sources": ["x_feed_manual"],
                    "discovered_at": now_iso,
                    "discovery_context": entry.get("catalyst", ""),
                },
            )
            new_count += 1

        akg.enrich_node_cashtag(
            ticker=ticker,
            velocity_z=entry.get("velocity_z", 0.0),
            mentions_7d=entry["mentions_estimate"],
            velocity_trend=entry.get("velocity_trend", "stable"),
            sentiment=entry.get("sentiment", 0.0),
            as_of_date=now_iso,
        )
        akg.update_node_field(ticker, "x_feed_manual_pass", entry.get("pass_number", 0))
        akg.update_node_field(ticker, "x_feed_manual_catalyst", entry.get("catalyst", "")[:200])

        # Write options flow data if present for this ticker
        if ticker in flow_by_ticker:
            akg.update_node_field(ticker, "options_flow_at", as_of_date)
            akg.update_node_field(ticker, "options_flow_data", flow_by_ticker[ticker])

        written += 1

    # Activate themes from pass 12
    for theme_entry in (themes or []):
        theme_id = str(theme_entry.get("theme", "")).strip()
        if not theme_id:
            continue
        if theme_id not in akg._nodes:
            akg.add_node(theme_id, node_type="theme", metadata={
                "discovered_by": "x_feed_manual",
                "discovered_at": now_iso,
            })
        try:
            conviction = max(0.0, min(1.0, float(theme_entry.get("conviction", 0.5))))
        except (ValueError, TypeError):
            conviction = 0.5
        akg.activate_theme(
            theme_id=theme_id,
            macro_trigger=str(theme_entry.get("reasoning", ""))[:200],
            conviction=conviction,
        )
        for sector_id in theme_entry.get("sectors", []):
            if sector_id not in akg._nodes:
                akg.add_node(sector_id, node_type="sector")
            akg.activate_sector(
                sector_id=sector_id,
                theme_ids=[theme_id],
                priority_score=conviction,
            )

    # Write GEX regime to AKG
    if gex_regime:
        if "GEX_REGIME" not in akg._nodes:
            akg.add_node("GEX_REGIME", node_type="macro_signal", metadata={
                "created_by": "x_feed_manual",
                "created_at": now_iso,
            })
        akg.update_node_field("GEX_REGIME", "gex_data", gex_regime)
        akg.update_node_field("GEX_REGIME", "gex_updated_at", as_of_date)

    akg.save()
    return {"written": written, "new": new_count}
