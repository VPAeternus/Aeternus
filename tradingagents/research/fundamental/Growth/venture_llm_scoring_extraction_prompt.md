# Venture Scoring LLM Extraction Prompt

Use this prompt to extract filing-grounded facts needed to calculate the venture score.

Goal:
Replace brittle keyword assumptions with structured evidence. The LLM should not calculate returns or use outside knowledge. It only extracts evidence and component scores from the filing text.

## Prompt

You are analyzing an SEC filing for a deterministic investment research pipeline.

Use only the filing text provided. Do not use outside knowledge, market prices, analyst views, news, or future events. Do not infer beyond the text. If required evidence is missing, mark it missing. Do not fill gaps.

Return valid JSON only. No Markdown. No commentary.

Filing metadata:
- ticker: `{ticker}`
- company: `{company}`
- form: `{form}`
- filed: `{filed}`
- accession: `{accn}`

Filing text:
```text
{filing_text}
```

Extract:

```json
{
  "ticker": "",
  "company": "",
  "form": "",
  "filed": "",
  "accn": "",
  "required_sections_present": {
    "business": true,
    "risk_factors": true,
    "mda": true
  },
  "missing_required_sections": [],
  "wave_exposure": {
    "score": null,
    "detected_wave": "",
    "evidence": [],
    "rationale": ""
  },
  "asymmetric_upside": {
    "score": null,
    "evidence": [],
    "rationale": ""
  },
  "fundable_scaling": {
    "score": null,
    "evidence": [],
    "rationale": ""
  },
  "wave_torque_operating_leverage": {
    "score": null,
    "evidence": [],
    "rationale": ""
  },
  "incumbent_saturation_penalty": {
    "score": null,
    "evidence": [],
    "rationale": ""
  },
  "false_promise_penalty": {
    "score": null,
    "evidence": [],
    "rationale": ""
  },
  "data_completeness": {
    "can_score": false,
    "blocking_missing_information": [],
    "confidence": "low"
  },
  "decision_summary": ""
}
```

## Hard Rule

If any required section is missing, set:
- `data_completeness.can_score = false`
- the affected component `score = null`
- `blocking_missing_information` to the missing section or missing fact

Do not compute a score when one required input is missing.

For `10-K`, required sections are:
- business
- risk_factors
- mda

For `10-Q`, required sections are:
- risk_factors
- mda

## Score Fields

### wave_exposure

Range: `0` to `5`

Question:
Does the filing tie the company directly to a large demand wave?

Look for:
- AI, data center, cloud, storage, power, networking, optical, grid, energy infrastructure, robotics, defense autonomy, healthcare supply chain, or another explicitly named demand wave.
- Product or service sits in an enabling layer or bottleneck layer.
- Demand, revenue, shipments, deployments, backlog, or customer activity rising because of that wave.
- Wave evidence appears in business and/or MD&A, not only risk factors.

Do not award:
- generic macro optimism
- one isolated keyword
- risk-only mentions
- broad technology words without customer, product, demand, or deployment context

### asymmetric_upside

Range: `0` to `5`

Question:
Does the filing show underappreciated upside rather than already-obvious incumbent strength?

Look for:
- smaller base scaling into larger demand surface
- new commercial adoption
- expanding product portfolio tied to customer demand
- specialist/challenger positioning
- multi-year demand runway
- new customer verticals or use cases

Do not award:
- generic words like "large" or "broad" without context
- ordinary revenue growth with no market expansion
- obvious market-leader or dominant-incumbent framing
- risk-only upside language

### fundable_scaling

Range: `0` to `5`

Question:
Can the company fund and execute the growth opportunity?

Look for:
- cash, liquidity, credit facility, financing access, operating cash flow
- strategic partner, utility partner, tax credit, policy support, financing framework
- manufacturing capacity, supply chain capacity, production readiness
- pricing, gross margin, ASP, revenue, profitability, or capital efficiency improvement
- multi-year demand runway with resources to serve it

Do not award:
- demand with no capacity or funding path
- liquidity language that only says cash is limited or insufficient
- risk-only capacity statements

### wave_torque_operating_leverage

Range: `0` to `3`

Question:
Is the demand wave already converting into operating leverage?

Look for:
- revenue growth tied to wave demand
- shipment growth tied to wave demand
- pricing power, ASP improvement, margin improvement, utilization improvement
- supply-demand tightness benefiting company economics
- bottleneck supplier or enabling-layer position

Score guide:
- `0`: no operating leverage evidence
- `1`: exposure exists, conversion weak or unclear
- `2`: clear revenue/shipment/pricing/margin torque
- `3`: strong torque across multiple hard metrics

### incumbent_saturation_penalty

Range: `0` to `2`

Question:
Does the filing make the company look like an already saturated incumbent?

Look for:
- dominant market share
- largest provider / clear leader framing
- mature category with limited incremental surprise
- growth described as continuation of existing scale

Score guide:
- `0`: no saturation evidence
- `1`: some incumbent or maturity evidence
- `2`: strong dominant-incumbent or saturation evidence

### false_promise_penalty

Range: `0` to `2`

Question:
Does the filing show promise without near-term proof?

Look for:
- demand claims without revenue, shipments, deployments, backlog, or customer proof
- commercialization repeatedly delayed
- material going-concern, liquidity, execution, customer concentration, or supply risk that undermines the opportunity
- heavy reliance on future plans without current traction

Score guide:
- `0`: no false-promise evidence
- `1`: some execution gap or weak proof
- `2`: strong promise/proof mismatch

## Evidence Rules

For each component:
- Include up to 5 short exact excerpts.
- Each excerpt must come from the provided filing text.
- Keep excerpts short, ideally under 40 words.
- Prefer MD&A and business evidence for positive scores.
- Use risk-factor evidence mainly for penalties or missing-confidence notes.
- If evidence is absent, use an empty array and explain the absence.

## Completeness Rules

`data_completeness.can_score` is `true` only if:
- every required section is present
- every component has enough filing evidence to assign a score
- no component score is `null`

If the filing has enough sections but a component lacks evidence:
- set that component score to `null`
- set `can_score = false`
- add the missing component to `blocking_missing_information`

## Final Score Formula

Do not return this unless `can_score = true`.

Formula:
`venture_score = wave_exposure + asymmetric_upside + fundable_scaling + wave_torque_operating_leverage - incumbent_saturation_penalty - false_promise_penalty`

If `can_score = false`, do not calculate `venture_score`.

