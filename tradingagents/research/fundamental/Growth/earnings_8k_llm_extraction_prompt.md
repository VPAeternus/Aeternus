# Earnings 8-K LLM Extraction Prompt

You are extracting facts from an SEC 8-K Item 2.02 EX-99.1 earnings release.

Use only the provided filing text, SEC-parser semantic elements, tables, and edgartools context. Do not use Wall Street expectations, market data, news, or outside knowledge.

Return only valid JSON matching this schema:

```json
{
  "schema_version": "earnings_8k_llm_extraction_v1",
  "source_method": "llm_json",
  "reported_period": {
    "period_text": "",
    "period_end_date": ""
  },
  "reported_results": {
    "revenue_millions": null,
    "revenue_yoy_pct": null,
    "revenue_qoq_pct": null,
    "gross_margin_pct": null,
    "non_gaap_gross_margin_pct": null,
    "eps": null,
    "non_gaap_eps": null
  },
  "forward_guidance": {
    "revenue_millions_midpoint": null,
    "revenue_low_millions": null,
    "revenue_high_millions": null,
    "revenue_growth_yoy_pct": null,
    "gross_margin_pct": null,
    "non_gaap_gross_margin_pct": null,
    "guide_direction": ""
  },
  "qualitative": {
    "demand_signal": "",
    "wave_signal": "",
    "margin_signal": "",
    "risk_signal": "",
    "customer_signal": ""
  },
  "evidence": [
    {
      "field": "",
      "quote": ""
    }
  ],
  "missing_fields": [],
  "confidence": 0
}
```

Rules:
- Normalize all revenue values to millions.
- If guidance is given as a range, fill low, high, and midpoint.
- If a value is absent, use `null` and include the field path in `missing_fields`.
- Do not infer missing values from prior quarters.
- Every non-null field must have a supporting quote in `evidence`.
- `guide_direction` should be one of `raised`, `lowered`, `maintained`, `positive`, `negative`, `mixed`, or `not_provided`.
- `confidence` is 0 to 1 based on extraction certainty.
