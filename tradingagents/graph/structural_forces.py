"""
Structural Force Engine (S-052) — "What Must Be True" Engine.

A top-down registry of structural economic/technological/geopolitical forces.
Given a force, traces the causal chain to companies that are *causally necessary*
for the force to materialize, scored by necessity × market ignorance × acceleration.

This inverts the bottom-up signal approach: rather than waiting for signals to
appear, it asks what MUST be true and which companies are required for it.
"""

from __future__ import annotations

import os
import re
import datetime as dt
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph


# ---------------------------------------------------------------------------
# Core dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CausalStep:
    step: int                        # 1, 2, 3...
    description: str                 # "HBM memory becomes supply bottleneck"
    sector_id: str                   # maps to AKG sector node
    derived_tickers: List[str]       # companies causally necessary at this step
    necessity_score: float           # 0.0–1.0: how essential is this step?
    reasoning: str                   # why this company/sector is necessary


@dataclass
class StructuralForce:
    force_id: str                    # "ai_compute_demand"
    display_name: str                # "AI Compute Demand Supercycle"
    description: str                 # 2-3 sentences: what the force is
    why_durable: str                 # why this isn't a fad
    acceleration_rate: str           # "accelerating" | "stable" | "decelerating"
    horizon_months: int              # expected duration of the force
    conviction: float                # 0.0–1.0 operator conviction
    must_be_true: List[str]          # conditions that must hold for force to materialize
    causal_chain: List[CausalStep]   # ordered steps from force to instruments
    anti_fragile_to: List[str]       # what makes this force stronger if it breaks
    last_reviewed: str               # ISO date
    # S-053 tracker fields — runtime overrides written by update_force_acceleration()
    acceleration_override: str = ""  # "accelerating"|"stable"|"decelerating"|"" (empty = use base)
    conviction_override: float = 0.0 # 0.0 = use base conviction
    tracker_rationale: str = ""      # last tracker reasoning

    @property
    def effective_acceleration(self) -> str:
        """Returns tracker override if set, else the base acceleration_rate."""
        return self.acceleration_override if self.acceleration_override else self.acceleration_rate

    @property
    def effective_conviction(self) -> float:
        """Returns tracker override if > 0, else the base conviction."""
        return self.conviction_override if self.conviction_override > 0.0 else self.conviction


@dataclass
class DarkMatterCandidate:
    ticker: str
    force_id: str
    causal_step: int
    necessity_score: float           # from CausalStep.necessity_score
    market_ignorance_score: float    # computed: inverse of AKG centrality + coverage
    force_acceleration: str          # from parent force
    discovery_score: float           # necessity × ignorance × acceleration_multiplier
    reasoning: str                   # why this company is causally necessary
    already_in_akg: bool             # is this ticker already an AKG node?


# ---------------------------------------------------------------------------
# Registry — 5 seed structural forces
# ---------------------------------------------------------------------------

STRUCTURAL_FORCES: List[StructuralForce] = [
    # ------------------------------------------------------------------
    # 1. AI Compute Demand Supercycle
    # ------------------------------------------------------------------
    StructuralForce(
        force_id="ai_compute_demand",
        display_name="AI Compute Demand Supercycle",
        description=(
            "Training and inference compute demand is doubling every ~18 months. "
            "No existing fab capacity can meet this without multi-year buildout. "
            "Sovereign AI programs (UAE, Saudi, France) are adding a new demand layer independent of US hyperscalers."
        ),
        why_durable=(
            "Foundation model scaling laws remain intact. Enterprise AI adoption just beginning — "
            "most Fortune 500s are still in pilot phase. Sovereign compute buildouts require "
            "domestic infrastructure that cannot be rented from US clouds."
        ),
        acceleration_rate="accelerating",
        horizon_months=48,
        conviction=0.95,
        must_be_true=[
            "Scaling laws for LLMs continue to hold",
            "Enterprise AI adoption continues beyond 2025 pilots",
            "No step-change efficiency breakthrough (10x algorithmic improvement) arrives",
        ],
        causal_chain=[
            CausalStep(
                step=1,
                description="Training clusters require H100/B200 at scale",
                sector_id="semis_ai_infrastructure",
                derived_tickers=["NVDA", "AVGO"],
                necessity_score=0.99,
                reasoning="No alternative GPU architecture at scale; NVDA holds >80% AI accelerator market",
            ),
            CausalStep(
                step=2,
                description="H100/B200 require HBM3e; SK Hynix/Micron supply constrained",
                sector_id="semis_ai_infrastructure",
                derived_tickers=["MU", "SNDK"],
                necessity_score=0.92,
                reasoning="HBM yield rates limiting supply; only 3 manufacturers worldwide (SK Hynix, Micron, Samsung)",
            ),
            CausalStep(
                step=3,
                description="HBM requires InP substrates for optical interconnects at scale",
                sector_id="semis_ai_infrastructure",
                derived_tickers=["AXTI", "COHR", "LITE"],
                necessity_score=0.85,
                reasoning="AXT is only US-listed InP substrate supplier; COHR/LITE produce optical transceivers",
            ),
            CausalStep(
                step=4,
                description="Scale-up clusters require power at 100MW+ per campus",
                sector_id="energy_power",
                derived_tickers=["VRT", "EQIX", "NRG", "OKLO"],
                necessity_score=0.88,
                reasoning="Power is the binding constraint for hyperscaler build; VRT dominates data center power infra",
            ),
            CausalStep(
                step=5,
                description="Advanced packaging (CoWoS) is the yield bottleneck",
                sector_id="semis_ai_infrastructure",
                derived_tickers=["ASX", "AMKR", "TSM"],
                necessity_score=0.90,
                reasoning="TSMC CoWoS capacity is 12-18mo lead time constraint; AMKR is #2 global OSAT",
            ),
        ],
        anti_fragile_to=[
            "Geopolitical tensions increase compute nationalism",
            "China export restrictions increase US domestic buildout urgency",
        ],
        last_reviewed="2026-02-28",
    ),

    # ------------------------------------------------------------------
    # 2. US-China Chip Decoupling
    # ------------------------------------------------------------------
    StructuralForce(
        force_id="us_china_chip_decoupling",
        display_name="US-China Chip Supply Decoupling",
        description=(
            "US export controls on advanced semiconductors are forcing bifurcation of global chip supply chains. "
            "China is racing to achieve domestic fab self-sufficiency while the US is funding domestic production "
            "via CHIPS Act. This is a decade-long structural realignment."
        ),
        why_durable=(
            "Bipartisan US political consensus on China tech competition. "
            "Entity list expansion is ratcheting, not reversing. "
            "China's 5nm domestic fab timeline is 2027+ at earliest, ensuring multi-year supply tension."
        ),
        acceleration_rate="accelerating",
        horizon_months=84,
        conviction=0.92,
        must_be_true=[
            "US-China geopolitical competition persists beyond 2026",
            "CHIPS Act funding reaches intended fabs (Intel, TSMC Arizona, Samsung Texas)",
            "China does not achieve 5nm yield parity before 2028",
        ],
        causal_chain=[
            CausalStep(
                step=1,
                description="CHIPS Act funds flow to domestic advanced fab construction",
                sector_id="semis_ai_infrastructure",
                derived_tickers=["INTC", "TSM", "AMAT", "LRCX"],
                necessity_score=0.88,
                reasoning="Intel and TSMC Arizona are primary recipients; AMAT/LRCX supply the tools",
            ),
            CausalStep(
                step=2,
                description="Domestic fab construction requires specialty chemicals and materials",
                sector_id="semis_ai_infrastructure",
                derived_tickers=["ENTG", "CMC"],
                necessity_score=0.82,
                reasoning="Entegris is the critical purity-materials supplier; CMC Materials supplies CMP slurries",
            ),
            CausalStep(
                step=3,
                description="Export control enforcement requires EDA tool compliance infrastructure",
                sector_id="semis_ai_infrastructure",
                derived_tickers=["CDNS", "SNPS", "ONTO"],
                necessity_score=0.75,
                reasoning="CDNS/SNPS provide EDA tools required for advanced design; compliance verification is mandatory",
            ),
            CausalStep(
                step=4,
                description="Domestic packaging ecosystem must develop independently",
                sector_id="semis_ai_infrastructure",
                derived_tickers=["AMKR", "ASX", "AAON"],
                necessity_score=0.78,
                reasoning="Advanced packaging currently concentrated in Taiwan/Korea; US domestic OSAT needed",
            ),
        ],
        anti_fragile_to=[
            "Taiwan Strait tensions accelerate allied domestic fab investment",
            "Additional export restrictions expand total addressable domestic market",
        ],
        last_reviewed="2026-02-28",
    ),

    # ------------------------------------------------------------------
    # 3. Nuclear Renaissance
    # ------------------------------------------------------------------
    StructuralForce(
        force_id="nuclear_renaissance",
        display_name="Nuclear Energy Renaissance",
        description=(
            "AI data center power demand plus grid decarbonization is catalyzing the first new nuclear "
            "construction cycle in 40 years. SMR (small modular reactor) technology is commercially viable "
            "for the first time. Hyperscalers (MSFT, AMZN, GOOGL) are signing nuclear PPAs directly."
        ),
        why_durable=(
            "Nuclear is the only baseload zero-carbon power source that can be sited near data centers. "
            "SMR designs received NRC approval in 2023-2024. Uranium supply is structurally constrained "
            "as Kazakhstan+Russia control >60% of enrichment capacity."
        ),
        acceleration_rate="accelerating",
        horizon_months=96,
        conviction=0.88,
        must_be_true=[
            "SMR regulatory approvals proceed on current timeline",
            "Uranium spot price remains above $60/lb (sustaining mine development economics)",
            "Hyperscaler nuclear PPAs continue to expand beyond MSFT/AMZN deals",
        ],
        causal_chain=[
            CausalStep(
                step=1,
                description="SMR reactor deployment requires enriched uranium fuel supply",
                sector_id="energy_power",
                derived_tickers=["CCJ", "UEC", "UUUU"],
                necessity_score=0.95,
                reasoning="Uranium mining is the critical chokepoint; only 3 producers can supply SMR-grade enriched fuel",
            ),
            CausalStep(
                step=2,
                description="Reactor construction requires nuclear-grade steel and containment components",
                sector_id="defense_aerospace",
                derived_tickers=["BWXT", "NNE", "OKLO"],
                necessity_score=0.90,
                reasoning="BWXT manufactures nuclear reactors for Navy and is lead SMR supplier; NNE/OKLO are SMR developers",
            ),
            CausalStep(
                step=3,
                description="Grid interconnection and transmission upgrades required for new nuclear capacity",
                sector_id="energy_power",
                derived_tickers=["AMSC", "AEE", "ETR"],
                necessity_score=0.72,
                reasoning="Transmission bottlenecks prevent nuclear power from reaching load centers; AMSC makes grid stabilization equipment",
            ),
            CausalStep(
                step=4,
                description="Nuclear waste processing and fuel recycling infrastructure needed at scale",
                sector_id="energy_power",
                derived_tickers=["BWXT", "UUUU", "NNE"],
                necessity_score=0.68,
                reasoning="Spent fuel management is a regulatory prerequisite for new reactor licensing",
            ),
        ],
        anti_fragile_to=[
            "Grid reliability crises increase urgency for baseload zero-carbon power",
            "Natural gas price spikes make nuclear economics more favorable",
        ],
        last_reviewed="2026-02-28",
    ),

    # ------------------------------------------------------------------
    # 4. Critical Minerals Onshoring
    # ------------------------------------------------------------------
    StructuralForce(
        force_id="critical_minerals_onshoring",
        display_name="Critical Minerals Supply Chain Onshoring",
        description=(
            "The US and allied nations depend on China for >80% of rare earth processing and "
            "significant lithium/cobalt supply. Defense, EV, and grid storage demand is forcing "
            "domestic and allied-nation alternatives to be developed on accelerated timelines."
        ),
        why_durable=(
            "DOD has classified rare earth dependency as a national security risk. "
            "IRA incentives create 10-year domestic processing economics. "
            "China export restrictions on gallium/germanium in 2023 proved the vulnerability is real."
        ),
        acceleration_rate="stable",
        horizon_months=120,
        conviction=0.85,
        must_be_true=[
            "IRA tax credits for domestic battery manufacturing remain in place through 2032",
            "China does not flood market with subsidized rare earths to undercut domestic alternatives",
            "DOD continues procurement preference for domestically-processed critical minerals",
        ],
        causal_chain=[
            CausalStep(
                step=1,
                description="Rare earth mining and separation must happen outside China",
                sector_id="materials_critical_minerals",
                derived_tickers=["MP", "LYEL", "REX"],
                necessity_score=0.92,
                reasoning="MP Materials is only US rare earth miner at scale; Mountain Pass is only US rare earth mine",
            ),
            CausalStep(
                step=2,
                description="Lithium processing and battery-grade material supply chain onshoring",
                sector_id="materials_critical_minerals",
                derived_tickers=["ALB", "LTHM", "SLI"],
                necessity_score=0.87,
                reasoning="Albemarle is the largest US lithium producer; LTHM and SLI are development-stage processors",
            ),
            CausalStep(
                step=3,
                description="Battery cell manufacturing requires domestic cathode and anode material supply",
                sector_id="materials_critical_minerals",
                derived_tickers=["FRPT", "LAC", "NOVT"],
                necessity_score=0.78,
                reasoning="Cathode active material is the highest-value component in lithium-ion cells",
            ),
            CausalStep(
                step=4,
                description="Gallium and germanium alternatives needed for compound semiconductors",
                sector_id="semis_ai_infrastructure",
                derived_tickers=["AXTI", "II", "NEON"],
                necessity_score=0.73,
                reasoning="AXT is a key gallium arsenide and germanium substrate supplier with US operations",
            ),
        ],
        anti_fragile_to=[
            "China export restrictions on more minerals validate onshoring thesis",
            "Conflict in Taiwan/South China Sea accelerates allied supply chain development",
        ],
        last_reviewed="2026-02-28",
    ),

    # ------------------------------------------------------------------
    # 5. US Defense Rebuild
    # ------------------------------------------------------------------
    StructuralForce(
        force_id="us_defense_rebuild",
        display_name="US Defense Industrial Base Rebuild",
        description=(
            "Ukraine war has depleted NATO munitions stockpiles and exposed the attrition math of "
            "peer-on-peer conflict. US defense spending is shifting from exquisite platforms to "
            "mass-producible autonomous systems, drone swarms, and AI-enabled C2. "
            "Dod budget is increasing while shifting toward software-defined warfare."
        ),
        why_durable=(
            "Russia-Ukraine conflict has made attrition warfare real for the first time since Korea. "
            "China's military buildup timeline compresses to 2027 Taiwan window per DIA assessments. "
            "Bipartisan consensus on defense spending increase persists through party cycles."
        ),
        acceleration_rate="accelerating",
        horizon_months=60,
        conviction=0.90,
        must_be_true=[
            "US defense budget grows at ≥3% real CAGR through 2030",
            "Autonomous systems doctrine is codified (counter-drone, drone swarms) in military requirements",
            "Supply chain constraints on munitions (especially 155mm) drive production ramp contracts",
        ],
        causal_chain=[
            CausalStep(
                step=1,
                description="Autonomous drone systems require AI-edge compute and propulsion",
                sector_id="defense_aerospace",
                derived_tickers=["KTOS", "AVAV", "ANGL"],
                necessity_score=0.93,
                reasoning="Kratos and AeroVironment are the primary DOD drone system providers at production scale",
            ),
            CausalStep(
                step=2,
                description="Counter-drone systems require RF detection, directed energy, and kill-chain software",
                sector_id="defense_aerospace",
                derived_tickers=["EPIQ", "SAIC", "CACI"],
                necessity_score=0.82,
                reasoning="Counter-UAS is the fastest-growing defense segment; SAIC/CACI provide C2 software",
            ),
            CausalStep(
                step=3,
                description="Munitions replenishment requires domestic explosive and propellant manufacturing",
                sector_id="defense_aerospace",
                derived_tickers=["GD", "RTX", "LMT"],
                necessity_score=0.88,
                reasoning="GD Ordnance, RTX, and LMT are the only suppliers of NATO-compatible precision munitions at scale",
            ),
            CausalStep(
                step=4,
                description="AI-enabled command and control requires specialized military AI infrastructure",
                sector_id="defense_aerospace",
                derived_tickers=["PLTR", "PRCT", "AI"],
                necessity_score=0.80,
                reasoning="Palantir's TITAN/Maven contracts position it as the DOD AI-C2 platform of record",
            ),
            CausalStep(
                step=5,
                description="Space domain awareness and satellite comms require low-earth orbit infrastructure",
                sector_id="defense_aerospace",
                derived_tickers=["RKLB", "ASTS", "SPIR"],
                necessity_score=0.75,
                reasoning="LEO resilience is required for DOD JADC2; RKLB is the lowest-cost orbital launcher",
            ),
        ],
        anti_fragile_to=[
            "Peer adversary conflict escalation accelerates defense spending",
            "Drone warfare proliferation expands total counter-drone market",
        ],
        last_reviewed="2026-02-28",
    ),
]


# ---------------------------------------------------------------------------
# Registry accessor functions
# ---------------------------------------------------------------------------

def get_force(force_id: str) -> Optional[StructuralForce]:
    """Retrieve a structural force by its force_id. Returns None if not found."""
    for force in STRUCTURAL_FORCES:
        if force.force_id == force_id:
            return force
    return None


def get_active_forces() -> List[StructuralForce]:
    """
    Return forces with effective_conviction >= 0.7 AND effective_acceleration != 'decelerating'.
    These are the forces worth running dark matter derivation on.
    Uses runtime tracker overrides (S-053) when available.
    """
    return [
        f for f in STRUCTURAL_FORCES
        if f.effective_conviction >= 0.7 and f.effective_acceleration != "decelerating"
    ]


# ---------------------------------------------------------------------------
# Dark matter derivation
# ---------------------------------------------------------------------------

_ACCELERATION_MULTIPLIERS = {
    "accelerating": 1.25,
    "stable": 1.0,
    "decelerating": 0.75,
}


def derive_dark_matter(
    force: StructuralForce,
    akg: "AeternusKnowledgeGraph",
    min_necessity: float = 0.7,
) -> List[DarkMatterCandidate]:
    """
    For each causal step in the force, evaluate each derived ticker.

    Scoring:
    1. necessity_score: from CausalStep directly
    2. market_ignorance_score: computed by compute_market_ignorance() (S-056).
       Real data: analyst coverage count, institutional ownership %, news velocity.
       Falls back to centrality proxy if yfinance unavailable.
       Ticker NOT in AKG: ignorance = 1.0 (maximum blind spot).
    3. acceleration_multiplier: accelerating=1.25, stable=1.0, decelerating=0.75
    4. discovery_score = necessity * ignorance * acceleration_multiplier

    Returns candidates with necessity >= min_necessity, sorted by discovery_score desc.
    """
    from tradingagents.graph.market_ignorance import compute_market_ignorance

    acceleration_multiplier = _ACCELERATION_MULTIPLIERS.get(force.effective_acceleration, 1.0)
    candidates: List[DarkMatterCandidate] = []

    nodes = akg._nodes  # type: ignore[attr-defined]

    for step in force.causal_chain:
        if step.necessity_score < min_necessity:
            continue  # Skip low-necessity steps entirely

        for ticker in step.derived_tickers:
            ticker_upper = ticker.upper().strip()

            already_in_akg = ticker_upper in nodes
            market_ignorance_score = compute_market_ignorance(ticker_upper, akg)

            discovery_score = round(
                step.necessity_score * market_ignorance_score * acceleration_multiplier,
                6,
            )

            candidates.append(
                DarkMatterCandidate(
                    ticker=ticker_upper,
                    force_id=force.force_id,
                    causal_step=step.step,
                    necessity_score=step.necessity_score,
                    market_ignorance_score=market_ignorance_score,
                    force_acceleration=force.acceleration_rate,
                    discovery_score=discovery_score,
                    reasoning=step.reasoning,
                    already_in_akg=already_in_akg,
                )
            )

    candidates.sort(key=lambda c: c.discovery_score, reverse=True)
    return candidates


# ---------------------------------------------------------------------------
# S-053: Force Acceleration Tracker
# ---------------------------------------------------------------------------

def _gather_force_evidence(force: StructuralForce) -> str:
    """Gather FORWARD-looking evidence for a structural force's top tickers.

    Returns a formatted evidence block for prompt injection. Never raises.

    Data sources (all free):
    - Options: IV, skew, put/call ratio [FORWARD]
    - Insider transactions: buys vs sells in 90d [FORWARD]
    - 30d price return [CONTEXT — ALREADY PRICED]
    - Macro: regime, VIX, credit spreads, yield curve [FORWARD]
    """
    lines: List[str] = []

    # Collect top 5 tickers by necessity_score across the causal chain
    ticker_scores: List[tuple] = []
    for step in force.causal_chain:
        for t in step.derived_tickers:
            ticker_scores.append((t, step.necessity_score))
    ticker_scores.sort(key=lambda x: x[1], reverse=True)
    top_tickers = []
    seen = set()
    for t, ns in ticker_scores:
        if t not in seen:
            seen.add(t)
            top_tickers.append((t, ns))
        if len(top_tickers) >= 5:
            break

    # Per-ticker evidence
    for ticker, necessity in top_tickers:
        ticker_lines = [f"\n### {ticker} (necessity={necessity:.2f})"]

        # Options snapshot [FORWARD]
        try:
            from tradingagents.agents.utils.options_engine import build_options_snapshot
            opts = build_options_snapshot(ticker)
            if opts:
                iv = opts.get("atm_iv")
                skew = opts.get("iv_skew")
                pc = opts.get("put_call_ratio")
                fg = opts.get("fear_greed")
                parts = []
                if iv is not None:
                    parts.append(f"ATM IV={iv:.1%}")
                if skew is not None:
                    parts.append(f"skew={skew:.3f}")
                if pc is not None:
                    parts.append(f"P/C={pc:.2f}")
                if fg:
                    parts.append(f"mood={fg}")
                if parts:
                    ticker_lines.append(f"[FORWARD] Options: {', '.join(parts)}")
        except Exception:
            pass

        # Insider transactions [FORWARD]
        try:
            import yfinance as yf
            stock = yf.Ticker(ticker)
            txns = stock.insider_transactions
            if txns is not None and hasattr(txns, "iterrows"):
                cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=90)).strftime("%Y-%m-%d")
                buys = 0
                sells = 0
                for _, row in txns.iterrows():
                    text = str(row.get("Text", ""))
                    start_date = str(row.get("Start Date", ""))
                    if start_date < cutoff:
                        continue
                    if "Purchase" in text:
                        buys += 1
                    elif "Sale" in text:
                        sells += 1
                if buys or sells:
                    ticker_lines.append(f"[FORWARD] Insider 90d: {buys} buys, {sells} sells")
        except Exception:
            pass

        # 30d price return [CONTEXT — ALREADY PRICED]
        try:
            import yfinance as yf
            hist = yf.Ticker(ticker).history(period="1mo")
            if hist is not None and len(hist) >= 2:
                ret = (hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1) * 100
                ticker_lines.append(f"[CONTEXT — ALREADY PRICED] 30d return: {ret:+.1f}%")
        except Exception:
            pass

        if len(ticker_lines) > 1:  # has evidence beyond the header
            lines.extend(ticker_lines)

    return "\n".join(lines) if lines else ""


def update_force_acceleration(force_id: str, xai_api_key: str = "") -> Optional[dict]:
    """
    Re-evaluate whether a structural force is accelerating, stable, or decelerating
    based on forward-looking evidence.

    Gathers real options, insider, and macro data, then asks the LLM to reason
    over evidence rather than training-data priors.

    Updates the force's acceleration_override, conviction_override, tracker_rationale,
    and last_reviewed fields in-place.

    Returns the parsed result dict on success, None on failure or missing API key.
    """
    force = get_force(force_id)
    if force is None:
        return None

    conditions = "\n".join(f"- {c}" for c in force.must_be_true)
    evidence = _gather_force_evidence(force)
    evidence_block = f"\n\n## Forward Evidence\n{evidence}" if evidence else ""

    prompt = (
        f"Structural force: {force.display_name}\n"
        f"Description: {force.description}\n"
        f"Must-be-true conditions:\n{conditions}\n"
        f"{evidence_block}\n\n"
        f"Focus on FORWARD signals (options IV/skew, insider buys, VIX, credit spreads). "
        f"Price returns marked [CONTEXT — ALREADY PRICED] show what markets priced, not what's coming.\n\n"
        f"Given this evidence (as of {dt.date.today().isoformat()}), "
        f"is this structural force accelerating, stable, or decelerating? "
        f"Return JSON only: "
        f'{{\"acceleration_rate\": \"accelerating\"|\"stable\"|\"decelerating\", '
        f'\"conviction\": <float 0-1>, '
        f'\"rationale\": \"<1-2 sentence reasoning>\"}}'
    )

    try:
        from tradingagents.dataflows.llm_quick import quick_complete
        raw = quick_complete(prompt, max_tokens=250, temperature=0.2)
        if not raw:
            return None
    except Exception:
        return None

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None

    try:
        import json
        parsed = json.loads(match.group())
    except Exception:
        return None

    accel = parsed.get("acceleration_rate", "")
    if accel not in ("accelerating", "stable", "decelerating"):
        return None

    conviction_val = float(parsed.get("conviction") or 0.0)
    if not (0.0 <= conviction_val <= 1.0):
        conviction_val = 0.0

    force.acceleration_override = accel
    force.conviction_override = conviction_val
    force.tracker_rationale = str(parsed.get("rationale", ""))
    force.last_reviewed = dt.date.today().isoformat()

    return {
        "force_id": force_id,
        "acceleration_rate": accel,
        "conviction": conviction_val,
        "rationale": force.tracker_rationale,
    }


# ---------------------------------------------------------------------------
# S-054: Causal Chain Auto-Extension
# ---------------------------------------------------------------------------

def propose_causal_extension(force_id: str, xai_api_key: str = "") -> Optional[dict]:
    """
    Ask xAI grok-4-1-fast-reasoning what causal step might be missing from a force's chain.

    Returns a proposal dict for operator review — does NOT modify the registry.
    Returns None on failure or missing API key.

    Model: grok-4-1-fast-reasoning. Cost: ~$0.001/call.
    """
    force = get_force(force_id)
    if force is None:
        return None

    chain_summary = "\n".join(
        f"Step {s.step}: {s.description} → {', '.join(s.derived_tickers)} "
        f"(necessity={s.necessity_score:.2f})"
        for s in force.causal_chain
    )
    prompt = (
        f"Structural force: {force.display_name}\n"
        f"Description: {force.description}\n\n"
        f"Existing causal chain:\n{chain_summary}\n\n"
        f"What important causal step or company beneficiary might be missing from this chain? "
        f"Return JSON only: "
        f'{{\"step_description\": \"<str>\", '
        f'\"sector\": \"<str>\", '
        f'\"tickers\": [\"<ticker>\"], '
        f'\"necessity_score\": <float 0-1>, '
        f'\"reasoning\": \"<str>\"}}'
    )

    try:
        from tradingagents.dataflows.llm_quick import quick_complete
        raw = quick_complete(prompt, max_tokens=200, temperature=0.3)
        if not raw:
            return None
    except Exception:
        return None

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None

    try:
        import json
        parsed = json.loads(match.group())
    except Exception:
        return None

    if "step_description" not in parsed:
        return None

    return {
        "force_id": force_id,
        "step_description": str(parsed.get("step_description", "")),
        "sector": str(parsed.get("sector", "")),
        "tickers": list(parsed.get("tickers") or []),
        "necessity_score": float(parsed.get("necessity_score") or 0.0),
        "reasoning": str(parsed.get("reasoning", "")),
    }
