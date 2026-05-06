# Asymmetric Upside Extraction Prompt

Use this prompt to extract filing-grounded evidence for `asymmetric_upside`.

Goal:
Determine whether the filing shows underappreciated upside, not just ordinary growth language or already-known incumbent strength.

## Prompt

You are analyzing an SEC filing for a deterministic investment research pipeline.

Use only the filing text provided. Do not use outside knowledge, market prices, analyst views, news, or future events. Do not infer beyond the text. If evidence is weak or absent, say so.

Return valid JSON only. No Markdown. No commentary.

Filing metadata:
- ticker: `{ticker}`
- form: `{form}`
- filed: `{filed}`

Filing text:
```text
{filing_text}
```

Extract the following fields:

```json
{
  "ticker": "",
  "form": "",
  "filed": "",
  "asymmetric_upside": {
    "non_incumbent_upside": {
      "score": 0,
      "label": "absent|weak|present|strong",
      "evidence": [],
      "rationale": ""
    },
    "growth_surface": {
      "score": 0,
      "label": "absent|weak|present|strong",
      "evidence": [],
      "rationale": ""
    },
    "not_obvious_incumbent": {
      "score": 0,
      "label": "absent|weak|present|strong",
      "evidence": [],
      "rationale": ""
    },
    "developing_wave_optional": {
      "score": 0,
      "label": "absent|weak|present|strong",
      "evidence": [],
      "rationale": ""
    },
    "total_score": 0,
    "confidence": "low|medium|high",
    "decision_summary": ""
  }
}
```

## Scoring Rules

Total score range: `0` to `5`

### 1. non_incumbent_upside (`0` or `2`)

Question:
Does the filing make the company look like a beneficiary with room for upside rather than an already dominant, obvious incumbent?

Score:
- `0` if filing presents company as dominant, mature, fully scaled, or obvious leader.
- `2` if filing presents company as a smaller, emerging, newly scaling, specialized, or less obvious beneficiary.

Evidence to look for:
- early scaling
- new commercial adoption
- smaller base expanding into larger market
- differentiated niche becoming more important
- customer adoption from a new or growing demand source

Do not award credit just because the company is not famous. Use filing evidence only.

### 2. growth_surface (`0` or `1`)

Question:
Does the filing describe a large or expanding opportunity that the company can plausibly address?

Score:
- `0` if no concrete growth surface is described.
- `1` if filing ties company products/services to a large, expanding, high-demand, multi-customer, multi-year, or broad deployment opportunity.

Valid evidence:
- addressable market expansion
- new customer verticals
- expanding product portfolio tied to customer demand
- large deployment base
- multi-year demand runway
- capacity expansion serving identified demand
- customer demand across multiple markets or geographies
- specific use cases that imply a broader market opening

Invalid evidence:
- generic words like "large" or "broad" without context
- ordinary revenue growth with no market expansion
- boilerplate optimism
- risk-factor-only statements
- vague "we believe" statements with no product/customer/demand support

### 3. not_obvious_incumbent (`0` or `1`)

Question:
Does the filing avoid obvious incumbent-leader language?

Score:
- `0` if filing describes the company as a clear market leader, dominant incumbent, largest provider, category leader, or already scaled leader in the relevant market.
- `1` if filing does not contain obvious leadership/dominance language, or if the company is positioned as challenger/specialist rather than incumbent.

Important:
This is not a reward for weak companies. It is a reward for upside not already framed as dominant, obvious leadership.

### 4. developing_wave_optional (`0` or `1`)

Question:
Does upside depend on a still-developing wave rather than continuation of already mature scale?

Score:
- `0` if filing only describes continuation of existing scale.
- `1` if filing ties upside to an emerging or still-developing demand wave.

Valid evidence:
- early-stage adoption
- accelerating customer deployments
- new demand category
- AI/data center/grid/energy transition/robotics/defense/autonomy/healthcare supply chain or other named wave, if filing explicitly supports it
- multi-year customer buildout
- supply-demand imbalance tied to emerging demand

Invalid evidence:
- generic macro optimism
- mature recurring demand with no new wave
- risk-only mentions

## Evidence Requirements

For each field:
- Include up to 3 exact short evidence excerpts.
- Evidence must come from the filing text.
- Each excerpt should be short, ideally under 35 words.
- If evidence absent, use empty array.
- `rationale` must explain why evidence does or does not support asymmetric upside.

## Anti-Hallucination Rules

- Do not mention facts outside the filing.
- Do not say the company is small, large, underappreciated, dominant, or a challenger unless the filing supports it.
- Do not use market cap, stock price, analyst consensus, or industry knowledge.
- Do not award credit for generic adjectives alone.
- Do not award credit for risk-factor-only upside language.
- If unsure, score lower.

## Decision Summary

In `decision_summary`, write one concise sentence:
- what asymmetric upside exists
- why it is or is not supported
- which evidence type matters most

Example:
`"The filing supports moderate asymmetric upside because the company ties expanding production capacity to multi-year customer demand, but it does not show a clearly new market opening."`

## Score Consistency

Set:
`total_score = non_incumbent_upside.score + growth_surface.score + not_obvious_incumbent.score + developing_wave_optional.score`

Allowed component scores:
- `non_incumbent_upside.score`: `0` or `2`
- `growth_surface.score`: `0` or `1`
- `not_obvious_incumbent.score`: `0` or `1`
- `developing_wave_optional.score`: `0` or `1`

Allowed total:
`0` to `5`
