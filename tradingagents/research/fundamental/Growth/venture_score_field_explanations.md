# Venture Score Field Explanations

## wave_exposure

`wave_exposure` measures how directly the filing ties the company to a large demand wave, especially AI, data center, cloud, storage, power, networking, optical, or infrastructure demand.

Range: `0` to `5`

Current triggers:
- Explicit AI, AI/ML, artificial intelligence, data center, or datacenter context.
- Product sits in a wave-enabling layer such as power, storage, NAND, SSD, optical, interconnect, network, infrastructure, or fuel cell.
- Filing shows demand, revenue, shipments, or deployments increasing.
- Filing names deployment contexts like enterprise SSDs, public clouds, cloud service providers, AI infrastructure builders, datacenters, data center customers, grid infrastructure, or interconnection.
- Wave support appears across multiple sections or contexts.

Plain English:
Higher `wave_exposure` means the filing is not just generally positive; it links the company to a major external growth wave.

Current limitation:
The scorer does not dynamically know which wave is currently relevant. Today `wave_exposure` is hardcoded around the AI / data-center infrastructure wave. That includes AI, cloud, storage, power, networking, optical, and related infrastructure terms. If the next major wave is GLP-1 supply chain, defense drones, robotics, nuclear, grid hardening, insurance repricing, or another theme, the current scorer may miss it unless those terms are added.

How relevance is determined today:
- Manually selected by us.
- Encoded in Python term lists.
- Matched deterministically against filing text.
- No market/news discovery.
- No LLM judgment.
- No dynamic wave ranking.

Better architecture:
Separate `wave_definition` from the scorer. Instead of one hardcoded AI/data-center wave, maintain wave config files such as:
- `ai_datacenter`
- `power_grid`
- `robotics`
- `defense_autonomy`
- `glp1_supply_chain`
- `nuclear_power`

Each wave config should define:
- wave terms
- enabling layer terms
- demand terms
- bottleneck terms
- deployment context terms
- relevant penalty terms

Then the scanner can run each filing across all active wave configs and output a `detected_wave` column. That would make `wave_exposure` mean exposure to a named wave rather than only exposure to the current hardcoded AI/data-center theme.

## asymmetric_upside

`asymmetric_upside` measures whether the company looks like a less-obvious beneficiary with room for surprise upside rather than an already dominant, fully recognized incumbent.

Range: `0` to `5`

Current triggers:
- Company is not tagged as an incumbent leader in the comparison set.
- Filing describes a large growth surface, broad opportunity, expanding portfolio, high-demand market, or similar category expansion.
- Filing does not use obvious leadership language like "industry leader based on revenue and market share."
- Upside depends on a still-developing wave rather than continuation of already-known scale.

Plain English:
Higher `asymmetric_upside` means the filing points to possible underappreciated upside, not just a known winner getting more known.

How growth surface is scored today:
This is deterministic keyword matching, not LLM judgment. The scorer scans only the `business` and `mda` sections for `GROWTH_SURFACE_TERMS` plus `DEPLOYMENT_CONTEXT_TERMS`.

Current growth surface terms:
- `large`
- `broad`
- `expanding portfolio`
- `growing needs`
- `growth surface`
- `massive`
- `high-demand`

Current deployment context terms also count toward this trigger:
- `enterprise ssd`
- `public clouds`
- `cloud service providers`
- `ai infrastructure builders`
- `semi-custom`
- `datacenters`
- `data center customers`
- `grid infrastructure`
- `interconnection`

If any of those terms appear in `business` or `mda`, the scorer adds `+1` for growth surface.

Current limitation:
This trigger is noisy. Words like `large` and `broad` are too generic and can fire in ordinary filing language that does not really describe asymmetric upside. The scorer does not currently require the term to appear near product, customer, demand, TAM, market, or deployment context.

Better architecture:
Replace generic single-word matches with phrase and proximity rules. Examples:
- `large addressable market`
- `large opportunity`
- `broad deployment`
- `broad adoption`
- `expanding portfolio`
- `high-demand applications`
- `cloud service providers`
- `data center customers`
- `multi-year demand`

Better trigger rule:
Only award growth surface credit when expansion language appears near product, customer, market, demand, deployment, backlog, or capacity language. This would reduce false positives from generic words like `large` or `broad`.

## fundable_scaling

`fundable_scaling` measures whether the company can realistically fund, supply, and execute against the growth opportunity.

Range: `0` to `5`

Current triggers:
- Liquidity, cash, credit facility, cash flow, or financing access is stated.
- Strategic partner, utility, policy, tax credit, safe harbor, financing framework, or deployment scaffold is stated.
- Manufacturing, supply, production, commercial capacity, supplier capacity, or shipment capacity is stated.
- Pricing, gross margin, revenue, ASP, profitability, or capital efficiency improved.
- Filing describes multi-year runway, durable demand, persistent tightness, or demand beyond current year.

Plain English:
Higher `fundable_scaling` means the company has resources and operating capacity to turn wave exposure into actual business.

## wave_torque_operating_leverage

`wave_torque_operating_leverage` measures whether the filing shows the demand wave already translating into hard operating leverage.

Range: `0` to `3`

Current triggers:
- Company is in an enabling layer or bottleneck supplier position.
- Numeric growth appears in the same section as demand evidence, such as revenue increase, shipments, stronger demand, datacenter revenue, or enterprise SSD shipments.
- Pricing, margin, utilization, mix, ASP, or supply-demand leverage is present.

Plain English:
Higher `wave_torque_operating_leverage` means the filing shows the company is not merely exposed to the wave; it is already converting the wave into revenue, shipment, pricing, or margin torque.

Scoring implication:
- `0` or `1` usually maps to `Expansion Bridge`.
- `2` or `3` maps to `Torque Bottleneck`.

Current backtest read:
This is the strongest current signal in the framework. Higher torque buckets showed better forward returns than total score alone.
