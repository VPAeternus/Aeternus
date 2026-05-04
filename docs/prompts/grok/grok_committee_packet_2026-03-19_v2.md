# Grok Committee Packet v2 (Upload-Ready) - 2026-03-19

Use this single markdown file as the upload artifact.

## Prompt (paste this)

```text
Use the attached markdown packet as the only canonical input.

Run a 4-role investment committee in one conversation:
1) Bull Researcher
2) Bear Researcher
3) Trader
4) Risk Manager

Hard rules:
- Ground every claim in packet fields only. Do not invent prices, events, or metrics.
- Use inline `aeternus_packet.inline_evidence` as primary per-ticker evidence, not just headline scores.
- Respect `constraints.max_position_pct` and `constraints.allow_new_positions`.
- Treat stale context explicitly: if `data_freshness.portfolio_snapshot_stale=true`, reduce confidence and call out sizing risk.
- Do not use a brittle threshold-only policy. Apply `decision_policy.near_boundary_band` for score-boundary cases.
- Enforce gate policy: if `execution_readiness.status != "PASS"`, do not propose OPEN/INCREASE trades.
- If `search_policy.allow_external_search=true`, run an external enrichment pass with citations.
- External facts may enrich but never silently overwrite packet values; any conflict must be listed in `external_enrichment.conflicts_with_packet`.

Decision discipline:
- If score is inside boundary band and evidence is mixed, prefer `HOLD`/`WATCHLIST` over hard `AVOID`.
- Every BUY/ADD must include: entry trigger, invalidation trigger, and review trigger.
- Every AVOID must include the specific disqualifier(s) and what would change the decision.
- WATCHLIST decisions must still include thesis-invalidating conditions.
- Triggers must be numeric and machine-checkable (metric/operator/value), not prose-only.

Required output format (strict JSON only):
{
  "as_of_date": "...",
  "input_tickers": ["..."],
  "execution_gate": {
    "status": "PASS|BLOCKED_STALE_CONTEXT|BLOCKED_MISSING_LIVE_MARKS|BLOCKED_OTHER",
    "reasons": ["..."]
  },
  "external_enrichment": {
    "used": true,
    "queries": ["..."],
    "citations": [
      {
        "id": "C1",
        "url": "https://...",
        "source": "...",
        "published_at": "YYYY-MM-DD",
        "claim": "...",
        "supports": ["ticker:CF", "portfolio"]
      }
    ],
    "conflicts_with_packet": [
      {
        "field": "...",
        "packet_value": "...",
        "external_value": "...",
        "resolution": "..."
      }
    ]
  },
  "portfolio_snapshot_used": {
    "account_mode": "...",
    "current_positions": [...],
    "cash_pct": ...,
    "market_regime": "...",
    "hedge_mode": "...",
    "snapshot_stale": true
  },
  "per_ticker_decisions": [
    {
      "ticker": "...",
      "action": "BUY|ADD|HOLD|WATCHLIST|TRIM|AVOID",
      "target_weight_pct": 0.0,
      "time_horizon_days": 20,
      "confidence": 0.0,
      "thesis_bull": "...",
      "thesis_bear": "...",
      "key_catalysts": ["..."],
      "key_risks": ["..."],
      "x_feed_support": ["..."],
      "score_context": {
        "pre_llm_score": 0.0,
        "final_score": 0.0,
        "score_delta": 0.0,
        "rating": "..."
      },
      "entry_trigger": "...",
      "entry_trigger_numeric": [
        {"metric": "vix_close", "operator": "<=", "value": 20.0}
      ],
      "invalidation_trigger": "...",
      "invalidation_trigger_numeric": [
        {"metric": "final_score", "operator": "<", "value": 60.0}
      ],
      "review_trigger": "...",
      "review_trigger_numeric": [
        {"metric": "days_since_decision", "operator": ">=", "value": 5}
      ],
      "decision_rationale": "..."
    }
  ],
  "portfolio_actions": {
    "keep_current_positions": true,
    "new_positions_allowed": true,
    "recommended_changes": [
      {
        "symbol": "...",
        "change_type": "OPEN|INCREASE|DECREASE|CLOSE|NONE",
        "weight_change_pct": 0.0,
        "reason": "..."
      }
    ],
    "hedge_view": {
      "action": "NO_CHANGE|INCREASE_HEDGE|DECREASE_HEDGE|DEFER_UNTIL_FRESH_CONTEXT",
      "instrument": "SPY|QQQ|NONE",
      "target_hedge_pct": 0.0,
      "reason": "..."
    }
  },
  "ranked_conviction": [
    {"ticker": "...", "rank": 1, "action": "...", "confidence": 0.0}
  ],
  "gaps_and_followups": {
    "known_gaps_from_packet": ["..."],
    "extra_data_needed_before_execution": ["..."]
  }
}
```

## Canonical Input Packet

```json
{
  "as_of_date": "2026-03-19",
  "generated_at_utc": "2026-03-19T10:50:57.761152+00:00",
  "tickers": [
    "OXY",
    "VRT",
    "CF",
    "CVX",
    "RTX"
  ],
  "primary_question": "Given the latest signals, what action should we take and why?",
  "data_freshness": {
    "portfolio_snapshot_as_of": "2026-03-19T10:48:16.629876Z",
    "portfolio_snapshot_age_days": 0,
    "portfolio_snapshot_stale": false
  },
  "execution_readiness": {
    "status": "PASS",
    "reasons": []
  },
  "search_policy": {
    "allow_external_search": true,
    "citation_recency_days": 7,
    "max_external_citations_per_ticker": 3,
    "require_conflict_log": true,
    "require_citation_fields": [
      "id",
      "url",
      "source",
      "published_at",
      "claim",
      "supports"
    ]
  },
  "decision_policy": {
    "score_policy": {
      "min_score": 62.0,
      "near_boundary_band": 2.0,
      "guidance": {
        "clear_candidate": "final_score >= 64.0 with sufficient evidence",
        "boundary_case": "60.0 <= final_score < 64.0",
        "weak_case": "final_score < 60.0 unless asymmetry is explicitly proven"
      }
    },
    "execution_policy": {
      "require_triggers_for_new_positions": true,
      "require_invalidation_for_all_positions": true,
      "penalize_stale_portfolio_context": true,
      "block_new_positions_if_portfolio_snapshot_stale_days_gte": 2,
      "require_numeric_triggers": true
    }
  },
  "portfolio_context": {
    "account_mode": "paper",
    "as_of": "2026-03-19T10:48:16.629876Z",
    "capital_usd": 100000.0,
    "cash_pct": 0.3922,
    "invested_pct": 0.6078,
    "drawdown_mode": false,
    "drawdown_20d_pct": 0.0,
    "market_regime": "BULL",
    "hedge_mode": "BULL",
    "current_hedge_pct": 0.0,
    "target_hedge_pct": 0.0,
    "hedge_action": "NO_CHANGE",
    "current_positions": [
      {
        "symbol": "QQQ",
        "side": "LONG",
        "quantity": 100.0,
        "avg_price": 607.78,
        "last_mark_price": 607.78,
        "market_value_usd": 60778.0,
        "portfolio_weight_estimate": 0.6078,
        "opened_at": "2026-03-10T09:30:00Z",
        "lane": "MOMENTUM",
        "source_plan_id": null
      }
    ],
    "plan_constraints": {
      "max_positions": 8,
      "max_weight_per_position": 0.25,
      "long_only": true,
      "min_score": 62.0,
      "min_confidence": 3,
      "committee_cap_weight": 0.1
    }
  },
  "baseline_scores": {
    "OXY": {
      "pre_llm_score": 57.6,
      "final_score": 56.88,
      "score_delta": -0.72,
      "rating": "Hold",
      "confidence": 5,
      "pillars": {
        "fundamental": 54,
        "coherence": 56,
        "macro": 54,
        "sentiment": 57,
        "momentum": 81
      },
      "active_debate_components": []
    },
    "VRT": {
      "pre_llm_score": 58.2,
      "final_score": 61.52,
      "score_delta": 3.32,
      "rating": "Buy",
      "confidence": 5,
      "pillars": {
        "fundamental": 82,
        "coherence": 41,
        "macro": 54,
        "sentiment": 43,
        "momentum": 76
      },
      "active_debate_components": []
    },
    "CF": {
      "pre_llm_score": 60.95,
      "final_score": 63.7,
      "score_delta": 2.75,
      "rating": "Buy",
      "confidence": 5,
      "pillars": {
        "fundamental": 81,
        "coherence": 43,
        "macro": 54,
        "sentiment": 59,
        "momentum": 84
      },
      "active_debate_components": []
    },
    "CVX": {
      "pre_llm_score": 57.95,
      "final_score": 58.95,
      "score_delta": 1.0,
      "rating": "Hold",
      "confidence": 5,
      "pillars": {
        "fundamental": 55,
        "coherence": 59,
        "macro": 54,
        "sentiment": 55,
        "momentum": 75
      },
      "active_debate_components": []
    },
    "RTX": {
      "pre_llm_score": 51.95,
      "final_score": 55.48,
      "score_delta": 3.53,
      "rating": "Hold",
      "confidence": 5,
      "pillars": {
        "fundamental": 69,
        "coherence": 40,
        "macro": 38,
        "sentiment": 57,
        "momentum": 75
      },
      "active_debate_components": []
    }
  },
  "aeternus_packet": {
    "inline_evidence": {
      "OXY": {
        "trade_date": "2026-03-18",
        "score_context": {
          "pre_llm_score": 57.6,
          "final_score": 56.88,
          "score_delta": -0.72,
          "rating": "Hold",
          "confidence": 5,
          "pillars": {
            "fundamental": 54,
            "coherence": 56,
            "macro": 54,
            "sentiment": 57,
            "momentum": 81
          },
          "active_debate_components": []
        },
        "macro_context": {
          "regime": "RISK_OFF",
          "vix_close": 25.09,
          "spy_close": 661.43,
          "spy_sma20": 678.95
        },
        "momentum_context": {
          "regime": "ABOVE_BOTH",
          "signal_state": "long",
          "composite_score": 81,
          "accel_percentile": 0.8
        },
        "sentiment_context": {
          "composite_score": 56.43,
          "direction": "NEUTRAL",
          "articles": 50
        },
        "fundamental_context": {
          "piotroski_fscore": 5,
          "revenue_growth_qoq": -24.32,
          "fcf_positive": true
        },
        "decision_excerpt": "Recommendation: **HOLD**\n\nOXY presents a genuine bull/bear tension that resolves to a hold at current conditions. The stock has strong technical momentum (composite 81, ABOVE_BOTH regime, 80th percentile acceleration) and is directly positioned to benefit from the commodity cycle (DBC +19.8%, commodity subscore 99/100). FCF is $1.881B and improving, cash earnings are nearly 12x reported net income, and options flow is markedly bullish (put/call volume 0.226). These are legitimate long-side arguments. Against this: macro is RISK_OFF with VIX at 25.09 and SPY below SMA20 \u2014 a regime in which adding equity risk historically has negative expected value. Earnings are down 33.4% YoY. Balance sheet carries $21.9B in total debt. Volume confirmation is weak (44/100). The composite scores \u2014 sentiment 56, macro 54, flow 52 \u2014 all cluster near neutral, and none provide a strong directional trigger. The commodity cycle tailwind is the single most compelling bull factor for an E&P in this environment, but it is offset by macro headwind and deteriorating fundamentals. Action: hold existing positio...",
        "plan_excerpt": "Core thesis: OXY is a commodity-leveraged E&P with strong FCF generation, a low-beta profile (0.351), and constructive momentum sitting in the top quintile of price acceleration. The primary bull case rests on the commodity cycle (DBC +19.8% 20d), strong options call skew, and improving cash flow trends. The primary bear case is RISK_OFF macro (VIX 25+, SPY below SMA20), declining earnings and revenue, and a leveraged balance sheet. The strategy is to hold existing positions and not add aggressively until macro confirms: either VIX retreats below 20 and SPY reclaims SMA20, or OXY demonstrates a specific earnings catalyst that decouples it from broad market risk. For new entries: wait for macro regime improvement before initiating. Price target framework: EV/EBITDA 7.38x is fair value given current EBITDA of ~$9.74B annualized \u2014 not deeply discounted. Stop discipline: below both SMAs w...",
        "trader_view_excerpt": "{'action': 'HOLD', 'conviction': 'MEDIUM-LOW', 'rationale': 'Momentum and commodity cycle are bullish; macro RISK_OFF, earnings deterioration, and high leverage are bearish. No new entry justified. Hold existing position at current weight.', 'key_bull_factors': ['DBC +19.8% 20d \u2014 direct commodity tailwind for E&P', 'Momentum regime ABOVE_BOTH, acceleration at 80th percentile', 'Put/call volume ratio 0.226 \u2014 strong call-side demand', 'FCF $1.881B positive and improving, OCF 11.92x net income', 'Low beta 0.351 \u2014 partial insulation from broad equity selloff'], 'key_bear_factors': ['RISK_OFF macro: VIX 25.09, SPY below SMA20', 'Quarterly earnings -33.4% YoY', 'Revenue declining trend, -24.3%...",
        "blended_data_coverage": 0.93,
        "report_date_used": "2026-03-18",
        "report_fallback": true
      },
      "VRT": {
        "trade_date": "2026-03-18",
        "score_context": {
          "pre_llm_score": 58.2,
          "final_score": 61.52,
          "score_delta": 3.32,
          "rating": "Buy",
          "confidence": 5,
          "pillars": {
            "fundamental": 82,
            "coherence": 41,
            "macro": 54,
            "sentiment": 43,
            "momentum": 76
          },
          "active_debate_components": []
        },
        "macro_context": {
          "regime": "RISK_OFF",
          "vix_close": 25.09,
          "spy_close": 661.43,
          "spy_sma20": 678.95
        },
        "momentum_context": {
          "regime": "ABOVE_BOTH",
          "signal_state": "long",
          "composite_score": 76,
          "accel_percentile": 0.17
        },
        "sentiment_context": {
          "composite_score": 53.38,
          "direction": "NEUTRAL",
          "articles": 9
        },
        "fundamental_context": {
          "piotroski_fscore": 8,
          "revenue_growth_qoq": 7.63,
          "fcf_positive": true
        },
        "decision_excerpt": "Recommendation: **HOLD**\n\nRationale: VRT's fundamental profile is among the strongest in the computation set \u2014 Piotroski 8/9, 200% EPS growth YoY, expanding margins, strong FCF, and a structurally sound AI-infrastructure thesis. However, three concurrent risk factors prevent a BUY at this time:\n\n1. **Macro regime: RISK_OFF.** SPY < SMA20, VIX = 25.09. A beta-2.08 stock in a risk-off tape faces amplified drawdown pressure. VRT will underperform the broad market in a down tape at approximately 2x.\n\n2. **Options flow: bearish.** Put/call volume ratio of 2.68 is well above neutral (1.0). OI ratio of 1.55 confirms sustained hedging or directional bearish bets. ATM IV of 81% signals the market is pricing a large near-term move \u2014 and the skew of put activity suggests downside is the consensus concern.\n\n3. **Momentum decelerating.** Trend strength is 100 (price above both MAs), but acceleration is in the 17th percentile with a negative acceleration value (-0.013). Momentum is long but fading \u2014 not an entry signal.\n\nA SELL is not warranted: the fundamental thesis is intact, FCF is strong,...",
        "plan_excerpt": "Structural thesis: VRT is a core AI-infrastructure beneficiary with improving fundamentals, exceptional earnings growth, and expanding margins. The long-term risk/reward remains positive if the hyperscaler capex cycle sustains. Near-term plan: (1) Maintain existing position if held \u2014 do not add in RISK_OFF regime with beta 2.08. (2) Do not initiate new long positions until SPY reclaims SMA20 and VIX retreats below 20. (3) If VIX spikes further or SPY breaches SMA200, reduce exposure by 30\u201350% as a risk-management measure given the beta amplification. (4) Monitor put/call ratio trend \u2014 current 2.68 volume ratio is a warning signal; if it normalizes below 1.5, re-evaluate for accumulation. (5) Re-entry trigger: SPY > SMA20 + VIX < 20 + momentum acceleration turning positive. (6) Target on re-entry: scale in over 2\u20133 sessions, not a single block, given ATM IV of 81% (market pricing ~5% d...",
        "trader_view_excerpt": "{'action': 'HOLD', 'conviction': 'MEDIUM', 'position_sizing': 'No change to existing position. Do not add. If not currently held, do not initiate.', 'entry_trigger': 'SPY reclaims 20-day SMA AND VIX closes below 20 AND VRT momentum acceleration turns positive (accel_percentile > 50th)', 'stop_loss': 'SPY breach of 200-day SMA or VRT -15% from current level \u2014 reduce position 30-50% on either trigger', 'time_horizon': '3\u20136 months (structural AI infrastructure thesis)', 'key_risks': ['RISK_OFF macro amplified by beta 2.08 \u2014 max drawdown risk elevated', 'Put/call volume ratio 2.68 signals institutional hedging or directional bearish positioning', 'ATM IV 81% \u2014 options market pricing large nea...",
        "blended_data_coverage": 0.93,
        "report_date_used": "2026-03-18",
        "report_fallback": true
      },
      "CF": {
        "trade_date": "2026-03-18",
        "score_context": {
          "pre_llm_score": 60.95,
          "final_score": 63.7,
          "score_delta": 2.75,
          "rating": "Buy",
          "confidence": 5,
          "pillars": {
            "fundamental": 81,
            "coherence": 43,
            "macro": 54,
            "sentiment": 59,
            "momentum": 84
          },
          "active_debate_components": []
        },
        "macro_context": {
          "regime": "RISK_OFF",
          "vix_close": 25.09,
          "spy_close": 661.43,
          "spy_sma20": 678.95
        },
        "momentum_context": {
          "regime": "ABOVE_BOTH",
          "signal_state": "long",
          "composite_score": 84,
          "accel_percentile": 0.54
        },
        "sentiment_context": {
          "composite_score": 50.65,
          "direction": "NEUTRAL",
          "articles": 50
        },
        "fundamental_context": {
          "piotroski_fscore": 7,
          "revenue_growth_qoq": 12.84,
          "fcf_positive": true
        },
        "decision_excerpt": "Recommendation: **BUY**\n\nCF presents a risk-adjusted opportunity supported by five converging signals: (1) Bullish momentum composite of 84 with ABOVE_BOTH regime and long signal state. (2) Commodity cycle subscore of 99 \u2014 direct macro tailwind for nitrogen fertilizer pricing. (3) Fundamentals strong: F-Score 7, ROE 23%, operating margin 35%, interest coverage 21x, net income and revenue both growing materially YoY. (4) Options market signaling GREED with low put/call ratios (0.18 volume, 0.36 OI) \u2014 informed positioning is bullish. (5) Low beta (0.69) provides relative defensiveness in RISK_OFF conditions.\n\nMitigating risks: RISK_OFF macro regime (SPY<SMA20, VIX 25.09) is a real headwind. Declining FCF/OCF trends require monitoring. ATM IV at 79% is exceptionally high and may reflect near-term event uncertainty. PEG of 5.66 limits multiple expansion upside.\n\nNet assessment: The commodity cycle tailwind and strong technical/fundamental confluence outweigh macro headwinds for this specific ticker. CF is positioned to benefit from the commodity surge (DBC +19.8%) that is occurring ev...",
        "plan_excerpt": "Primary thesis: CF is a low-beta commodity-cycle beneficiary with strong fundamentals, bullish momentum, and options positioning skewed toward upside \u2014 all in a macro backdrop where the commodity cycle is surging even as broad equities are under pressure. The RISK_OFF regime creates a tactical headwind for equities broadly, but CF's defensive beta (0.69) and direct commodity tailwind partially offset this. Entry logic: Current technical posture (ABOVE_BOTH, long signal, momentum score 84) supports existing or new long positions. The very high ATM IV of 79% signals elevated near-term uncertainty \u2014 this could reflect upcoming earnings, fertilizer price volatility, or broad market dislocation. High IV makes outright long calls expensive; long stock or selling puts at support levels are preferred structures. Size: Given RISK_OFF macro, size at 50-75% of target. Risk management: Stop below...",
        "trader_view_excerpt": "{'action': 'BUY', 'conviction': 'MEDIUM-HIGH', 'size_pct_of_target': 65, 'rationale': \"Commodity cycle tailwind (DBC +19.8%, commodity subscore 99) directly benefits CF's nitrogen fertilizer economics. Momentum is strong (84 composite, ABOVE_BOTH, long). Fundamentals solid (F-Score 7, ROE 23%, interest coverage 21x, F2025 EPS growth 37% YoY). Options positioning bullish (put/call vol 0.18, GREED). Low beta (0.69) provides partial macro hedge. Size reduced from full target due to RISK_OFF macro regime (VIX 25.09, SPY < SMA20) and high ATM IV (79%) signaling near-term uncertainty.\", 'key_risks': ['RISK_OFF macro continues to deteriorate \u2014 SPY breaks SMA200 support', 'ATM IV 79% suggests unp...",
        "blended_data_coverage": 0.93,
        "report_date_used": "2026-03-18",
        "report_fallback": true
      },
      "CVX": {
        "trade_date": "2026-03-18",
        "score_context": {
          "pre_llm_score": 57.95,
          "final_score": 58.95,
          "score_delta": 1.0,
          "rating": "Hold",
          "confidence": 5,
          "pillars": {
            "fundamental": 55,
            "coherence": 59,
            "macro": 54,
            "sentiment": 55,
            "momentum": 75
          },
          "active_debate_components": []
        },
        "macro_context": {
          "regime": "RISK_OFF",
          "vix_close": 25.09,
          "spy_close": 661.43,
          "spy_sma20": 678.95
        },
        "momentum_context": {
          "regime": "ABOVE_BOTH",
          "signal_state": "long",
          "composite_score": 74,
          "accel_percentile": 0.85
        },
        "sentiment_context": {
          "composite_score": 53.81,
          "direction": "NEUTRAL",
          "articles": 50
        },
        "fundamental_context": {
          "piotroski_fscore": 6,
          "revenue_growth_qoq": -4.95,
          "fcf_positive": true
        },
        "decision_excerpt": "Recommendation: **HOLD**\n\nCVX sits at the intersection of a powerful commodity tailwind (DBC +19.8%, commodity cycle score 99) and strong technical momentum (trend strength 99, accel percentile 85th) against a RISK_OFF macro backdrop (VIX 25.09, SPY below SMA20) and deteriorating fundamentals (earnings -23.8% YoY, declining revenue, declining margins, PEG 3.876). The dividend yield (3.47%) and FCF coverage provide downside support for current holders. However, the macro regime (RISK_OFF with VIX trigger active) is not a backdrop in which to initiate new long exposure on a 29.86x earnings name with shrinking profits. Existing positions should be held given technical strength and sector tailwind, with stops placed below the key moving average support levels. New entries should wait for macro regime confirmation (VIX < 20, SPY above SMA20) or a fundamental re-rating event (earnings stabilization).",
        "plan_excerpt": "Context: CVX is a large-cap integrated energy major with defensive beta (0.658), a commodity cycle tailwind (DBC +19.8%), strong momentum technically (trend strength 99), but deteriorating fundamental trajectory and a RISK_OFF macro backdrop. Plan: (1) Do not initiate new long in a RISK_OFF macro regime with VIX above 25 and SPY below SMA20 \u2014 this is a regime that historically pressures equities even in commodity-supported sectors. (2) For existing holders: maintain position with trailing stop discipline given the strong technical momentum and commodity tailwind; CVX's low beta provides relative defense vs. SPY. (3) Monitor the SPY/SMA200 confluence \u2014 a sustained breakdown accelerates the exit thesis. (4) The 3.47% dividend yield acts as a floor support and provides return while holding. (5) Re-evaluate BUY thesis if: (a) macro regime shifts to RISK_ON (VIX drops below 20, SPY reclaim...",
        "trader_view_excerpt": "HOLD CVX. Do not add. Maintain existing position size for current holders with disciplined trailing stop. The commodity surge (DBC +19.8%) and CVX's above-both-MAs technical posture with 85th-percentile momentum acceleration are real signals \u2014 but they are insufficient to override the RISK_OFF macro regime trigger (VIX 25.09, SPY below SMA20). CVX's beta of 0.658 provides relative protection vs. the S&P, and the 3.47% dividend yield compensates for holding through volatility. Key watch levels: SPY 661 SMA200 support (breach = reduce), VIX 20 ceiling (break lower = reassess BUY). Options flow is mildly constructive (put/call volume ratio 0.21 \u2014 few hedges being bought) but ATM IV at 37.45%...",
        "blended_data_coverage": 0.93,
        "report_date_used": "2026-03-18",
        "report_fallback": true
      },
      "RTX": {
        "trade_date": "2026-03-18",
        "score_context": {
          "pre_llm_score": 51.95,
          "final_score": 55.48,
          "score_delta": 3.53,
          "rating": "Hold",
          "confidence": 5,
          "pillars": {
            "fundamental": 69,
            "coherence": 40,
            "macro": 38,
            "sentiment": 57,
            "momentum": 75
          },
          "active_debate_components": []
        },
        "macro_context": {
          "regime": "RISK_OFF",
          "vix_close": 25.09,
          "spy_close": 661.43,
          "spy_sma20": 678.95
        },
        "momentum_context": {
          "regime": "ABOVE_BOTH",
          "signal_state": "long",
          "composite_score": 74,
          "accel_percentile": 0.45
        },
        "sentiment_context": {
          "composite_score": 55.32,
          "direction": "NEUTRAL",
          "articles": 50
        },
        "fundamental_context": {
          "piotroski_fscore": 7,
          "revenue_growth_qoq": 7.83,
          "fcf_positive": true
        },
        "decision_excerpt": "Recommendation: **HOLD**\n\nRTX presents a structurally sound defense prime at a stretched valuation in a deteriorating macro environment. The bull case rests on: low beta (0.406) providing relative protection in RISK_OFF, strong momentum regime (ABOVE_BOTH, trend strength 88), improving FCF ($3.195B, trending up), Piotroski F-Score 7/9, and defense sector structural tailwinds from elevated global geopolitical tension. The bear case is: forward PE of 30.3 and PEG of 2.886 leave limited margin of safety; macro composite at 38 (BEARISH) with VIX at 25.09 and SPY below SMA20 creates near-term headwinds for all equities; margin trend is declining; ATM IV at 49.85% is anomalously elevated for a 0.406-beta stock, signaling the market is hedging near-term tail risk. Net assessment: hold existing positions \u2014 RTX's defensive characteristics and momentum argue against exit, but the risk/reward for new capital deployment is unfavorable at current valuation in a risk-off tape. Do not add. Do not exit. Re-evaluate on macro regime flip.",
        "plan_excerpt": "Primary thesis: RTX is a high-quality defense prime with strong cash generation, improving FCF trends, and low market beta operating in a structurally favorable defense spending environment. The investment case is HOLD, not BUY, due to: (1) stretched valuation (forward PE 30.3, PEG 2.886) that prices in execution with limited margin of safety, (2) RISK_OFF macro regime creating near-term equity headwinds, (3) declining margin trend despite revenue growth, (4) elevated ATM IV (49.85%) suggesting elevated short-term risk pricing. Constructive factors supporting HOLD over SELL: strong momentum (74 composite, ABOVE_BOTH regime, trend strength 88), options market positioned toward GREED (put/call OI 0.45, sentiment 66), low beta provides relative downside cushion in risk-off, FCF is positive and improving, credit spreads stable. Tactical positioning: No new long entry recommended until mac...",
        "trader_view_excerpt": "{'action': 'HOLD', 'conviction': 'MEDIUM', 'rationale': 'Strong momentum and low-beta defense positioning offset by stretched valuation (forward PE 30.3, PEG 2.886), risk-off macro regime (VIX 25.09, SPY below SMA20), and declining margin trend. FCF improving and Piotroski 7/9 prevent SELL. No new capital deployed until macro clears.', 'key_risks': ['Macro regime remains RISK_OFF \u2014 broad equity drawdown could compress RTX despite low beta', 'ATM IV 49.85% anomalously high for 0.406-beta stock \u2014 implies event risk not visible in packet', 'Margin trend declining despite revenue growth \u2014 execution risk on profitability targets', 'Valuation premium (forward PE 30.3) requires sustained 12%+ re...",
        "blended_data_coverage": 0.93,
        "report_date_used": "2026-03-18",
        "report_fallback": true
      }
    },
    "source_reports": {
      "OXY": "results/OXY/2026-03-18/analysis_report.json",
      "VRT": "results/VRT/2026-03-18/analysis_report.json",
      "CF": "results/CF/2026-03-18/analysis_report.json",
      "CVX": "results/CVX/2026-03-18/analysis_report.json",
      "RTX": "results/RTX/2026-03-18/analysis_report.json"
    },
    "report_provenance": {
      "OXY": {
        "report_path": "results/OXY/2026-03-18/analysis_report.json",
        "report_date": "2026-03-18",
        "as_of_date": "2026-03-19",
        "is_fallback_prior_date": true
      },
      "VRT": {
        "report_path": "results/VRT/2026-03-18/analysis_report.json",
        "report_date": "2026-03-18",
        "as_of_date": "2026-03-19",
        "is_fallback_prior_date": true
      },
      "CF": {
        "report_path": "results/CF/2026-03-18/analysis_report.json",
        "report_date": "2026-03-18",
        "as_of_date": "2026-03-19",
        "is_fallback_prior_date": true
      },
      "CVX": {
        "report_path": "results/CVX/2026-03-18/analysis_report.json",
        "report_date": "2026-03-18",
        "as_of_date": "2026-03-19",
        "is_fallback_prior_date": true
      },
      "RTX": {
        "report_path": "results/RTX/2026-03-18/analysis_report.json",
        "report_date": "2026-03-18",
        "as_of_date": "2026-03-19",
        "is_fallback_prior_date": true
      }
    }
  },
  "x_feed_context": {
    "summary": "Manual X-feed coverage for basket: 0/5 symbols. Pass artifacts loaded from eval_results/x_feed/2026-03-19.",
    "coverage": {
      "status": "MISSING",
      "target_tickers": [
        "OXY",
        "VRT",
        "CF",
        "CVX",
        "RTX"
      ],
      "covered_tickers": [],
      "missing_tickers": [
        "OXY",
        "VRT",
        "CF",
        "CVX",
        "RTX"
      ],
      "coverage_ratio": 0.0,
      "source_artifact": "eval_results/x_feed/2026-03-19/merged.json"
    },
    "active_themes": [],
    "high_signal_posts": [],
    "ticker_snapshot": {}
  },
  "web_search_allowed": true,
  "constraints": {
    "max_position_pct": 0.1,
    "allow_new_positions": true
  },
  "known_gaps": [
    "Using latest prior analysis reports for: OXY:2026-03-18, VRT:2026-03-18, CF:2026-03-18, CVX:2026-03-18, RTX:2026-03-18 (as_of_date=2026-03-19).",
    "X-feed missing coverage for: OXY, VRT, CF, CVX, RTX."
  ]
}
```
