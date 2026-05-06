# Earnings Narrative Delta Framework

This framework adds an LLM-reviewed unstructured-data layer to the deterministic earnings score.

Core idea:
The most valuable signal in an earnings release is not just whether revenue grew or guidance rose. It is whether the filing reveals a new causal business reality: demand source, customer behavior, pricing power, capacity constraint, product cycle, regulatory shock, or execution failure.

This layer is called `narrative_delta`.

## Why This Is The Moat

Everyone can scrape revenue, EPS, guidance, and returns. Fewer systems can read the unstructured parts of `8-K Item 2.02 / EX-99.1` and answer:

- What changed?
- Why did it change?
- Is the change durable?
- Is it already visible in hard numbers?
- Is management explaining a temporary blip or a new operating regime?
- Is the opportunity accelerating, or is the story outrunning proof?

The useful edge is turning language into a falsifiable signal.

## Inputs

The LLM should receive:

```json
{
  "metadata": {},
  "reported_period": {},
  "quarter_results": {},
  "next_quarter_guidance": {},
  "earnings_score": {},
  "evidence_buckets": {
    "numeric_evidence": [],
    "guidance_evidence": [],
    "wave_or_demand_evidence": [],
    "warning_or_risk_evidence": []
  }
}
```

Use only these inputs. Do not use stock price, future returns, analyst expectations, news, or outside knowledge.

## Output Fields

```json
{
  "ticker": "",
  "filed": "",
  "narrative_delta_score": null,
  "narrative_delta_bucket": "inflecting|constructive|neutral|deteriorating|unscorable",
  "causal_change": {
    "score": null,
    "label": "none|weak|clear|powerful",
    "evidence": [],
    "rationale": ""
  },
  "proof_alignment": {
    "score": null,
    "label": "unsupported|partial|clear|strong",
    "evidence": [],
    "rationale": ""
  },
  "durability": {
    "score": null,
    "label": "one_time|unclear|multi_quarter|structural",
    "evidence": [],
    "rationale": ""
  },
  "operating_leverage_quality": {
    "score": null,
    "label": "absent|weak|clear|strong",
    "evidence": [],
    "rationale": ""
  },
  "negative_revision_risk": {
    "score": null,
    "label": "none|watch|elevated|severe",
    "evidence": [],
    "rationale": ""
  },
  "story_vs_numbers_gap": {
    "score": null,
    "label": "numbers_lead|aligned|story_leads|story_breaks",
    "evidence": [],
    "rationale": ""
  },
  "detected_driver": {
    "category": "demand|guidance|pricing|margin|capacity|product_cycle|customer_adoption|regulation|inventory|macro|execution|unknown",
    "name": "",
    "rationale": ""
  },
  "single_sentence_thesis": "",
  "score_addition": null,
  "confidence": "low|medium|high",
  "blocking_issues": []
}
```

## Scoring

`narrative_delta_score` range: `-5` to `+10`

Formula:

```text
narrative_delta_score =
  causal_change
+ proof_alignment
+ durability
+ operating_leverage_quality
- negative_revision_risk
- story_vs_numbers_gap_penalty
```

### causal_change

Range: `0` to `3`

Question:
Does the release explain a real business change, not just report numbers?

Score:
- `0`: no causal explanation
- `1`: vague explanation
- `2`: clear cause, such as demand, product cycle, customer adoption, capacity, pricing, regulation, inventory, or macro
- `3`: powerful cause that appears to change the forward trajectory

Good evidence:
- demand source named
- customer behavior changed
- product cycle accelerating
- new market/use case emerging
- pricing or capacity changed
- regulation/export control changed demand
- inventory correction or channel reset explained

### proof_alignment

Range: `0` to `3`

Question:
Does the narrative line up with hard numbers?

Score:
- `0`: no hard-number support
- `1`: partial support
- `2`: clear support from revenue, segment revenue, guidance, margin, EPS, or cash flow
- `3`: multiple hard metrics confirm the same narrative

Do not give high score for story-only claims.

### durability

Range: `0` to `2`

Question:
Does the release imply a multi-quarter or structural change?

Score:
- `0`: one-time or temporary
- `1`: unclear or one-quarter
- `2`: multi-quarter, structural, or explicitly ongoing

Positive evidence:
- backlog, customer buildout, platform transition, multi-year demand, capacity expansion, recurring adoption, sustained pricing/margin improvement.

Negative evidence:
- one-time gain, temporary channel fill, pull-forward, isolated charge, short-lived recovery.

### operating_leverage_quality

Range: `0` to `2`

Question:
Is the company converting the driver into better economics?

Score:
- `0`: no conversion
- `1`: revenue/shipment conversion only
- `2`: revenue plus margin, pricing, operating income, cash flow, or EPS conversion

### negative_revision_risk

Range: `0` to `5`

Question:
Does the release imply future numbers may need to come down?

Score:
- `0`: no risk evidence
- `1`: watch item
- `2`: elevated risk
- `3`: clear negative revision risk
- `5`: severe warning, preliminary shortfall, guidance cut, large charge, demand break, liquidity issue, or export/regulatory shock

### story_vs_numbers_gap_penalty

Range: `0` to `3`

Question:
Is the narrative ahead of the numbers?

Score:
- `0`: numbers lead or align with story
- `1`: story slightly ahead of numbers
- `2`: story materially ahead of numbers
- `3`: story contradicted by numbers

This is the anti-hype control.

## Bucket Rules

```text
inflecting: narrative_delta_score >= 7
constructive: 3 to 6
neutral: 0 to 2
deteriorating: < 0
unscorable: missing required evidence
```

## Score Addition To Earnings Score

Use `score_addition` as the amount added to deterministic `earnings_score`.

```text
inflecting: +3
constructive: +1
neutral: 0
deteriorating: -3
unscorable: 0
```

Hard override:
If `negative_revision_risk >= 4`, `score_addition` must be `-3` even if positive story evidence exists.

## LLM Prompt

You are reviewing an SEC `8-K Item 2.02 / EX-99.1` earnings release for an investment research pipeline.

Your job is not to summarize the release. Your job is to identify the narrative delta: the new business reality revealed by the release, grounded only in the provided evidence.

Use only the provided JSON. Do not use stock price, market reaction, analyst estimates, news, future events, or outside knowledge.

Return valid JSON only. No Markdown. No commentary.

Input JSON:

```json
{input_json}
```

Rules:

- Use exact excerpts from `evidence_buckets` only.
- If the evidence is weak, score lower.
- Do not reward generic optimism.
- Do not reward AI, cloud, energy, healthcare, or any theme unless the evidence ties it to revenue, guidance, margin, customer adoption, demand, or capacity.
- Penalize story without numbers.
- Penalize preliminary shortfall, guide cut, demand weakness, inventory charge, export control, liquidity stress, or execution delay.
- If a field cannot be supported by provided evidence, set its score to `null`, explain the missing evidence, and set bucket to `unscorable`.

Return this schema:

```json
{
  "ticker": "",
  "filed": "",
  "narrative_delta_score": null,
  "narrative_delta_bucket": "inflecting|constructive|neutral|deteriorating|unscorable",
  "causal_change": {
    "score": null,
    "label": "none|weak|clear|powerful",
    "evidence": [],
    "rationale": ""
  },
  "proof_alignment": {
    "score": null,
    "label": "unsupported|partial|clear|strong",
    "evidence": [],
    "rationale": ""
  },
  "durability": {
    "score": null,
    "label": "one_time|unclear|multi_quarter|structural",
    "evidence": [],
    "rationale": ""
  },
  "operating_leverage_quality": {
    "score": null,
    "label": "absent|weak|clear|strong",
    "evidence": [],
    "rationale": ""
  },
  "negative_revision_risk": {
    "score": null,
    "label": "none|watch|elevated|severe",
    "evidence": [],
    "rationale": ""
  },
  "story_vs_numbers_gap": {
    "score": null,
    "label": "numbers_lead|aligned|story_leads|story_breaks",
    "evidence": [],
    "rationale": ""
  },
  "detected_driver": {
    "category": "demand|guidance|pricing|margin|capacity|product_cycle|customer_adoption|regulation|inventory|macro|execution|unknown",
    "name": "",
    "rationale": ""
  },
  "single_sentence_thesis": "",
  "score_addition": null,
  "confidence": "low|medium|high",
  "blocking_issues": []
}
```

## Example Interpretation

Bad output:
`"The company had strong AI demand."`

Good output:
`"The release shows an inflection because next-quarter revenue guidance steps up sharply while management attributes demand to accelerated computing and AI adoption; numbers and story align, but durability depends on continued customer buildout."`

Why good:
- identifies driver
- ties story to guidance
- states durability condition
- avoids pure theme hype

