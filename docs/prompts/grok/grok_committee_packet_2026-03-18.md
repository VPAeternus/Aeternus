# Grok Committee Packet (Upload-Ready) - 2026-03-18

Use this file as the single upload artifact.

## Prompt (paste this)

```text
Use the attached markdown file as the only canonical input packet.

Run a 4-role investment committee in one conversation:
1) Bull Researcher
2) Bear Researcher
3) Trader
4) Risk Manager

Hard rules:
- Ground every claim in fields from the attached packet (portfolio_context, baseline_scores, x_feed_context, constraints, known_gaps).
- Do not invent data or prices not in the packet.
- If evidence is weak, say so explicitly and lower confidence.
- Respect constraints.max_position_pct and constraints.allow_new_positions.
- Keep reasoning focused on alpha and risk-adjusted action, not generic macro chatter.

Process:
A) Bull: best long case per ticker.
B) Bear: strongest failure case per ticker.
C) Trader: convert debate to executable action candidates.
D) Risk: size/risk checks, concentration/hedge implications, vetoes if needed.
E) Committee synthesis: final action per ticker + portfolio-level plan.

Required output format (strict JSON only, no markdown):
{
  "as_of_date": "...",
  "input_tickers": ["..."],
  "portfolio_snapshot_used": {
    "account_mode": "...",
    "current_positions": [...],
    "cash_pct": ...,
    "market_regime": "...",
    "hedge_mode": "..."
  },
  "per_ticker_decisions": [
    {
      "ticker": "...",
      "action": "BUY|ADD|HOLD|TRIM|AVOID",
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
      "action": "NO_CHANGE|INCREASE_HEDGE|DECREASE_HEDGE",
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
  "as_of_date": "2026-03-18",
  "tickers": [
    "OXY",
    "VRT",
    "CF",
    "CVX",
    "RTX"
  ],
  "primary_question": "Given the latest signals, what action should we take and why?",
  "portfolio_context": {
    "account_mode": "paper",
    "as_of": "2026-03-10T15:22:11.295026Z",
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
      "min_confidence": 3
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
      "active_debate_components": [
        "research_debate"
      ]
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
      "active_debate_components": [
        "research_debate"
      ]
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
      "active_debate_components": [
        "research_debate"
      ]
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
      "active_debate_components": [
        "research_debate"
      ]
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
      "active_debate_components": [
        "research_debate"
      ]
    }
  },
  "aeternus_packet": {
    "evidence_summary": {
      "notes": "Populate additional per-ticker catalyst/event snippets if you want stronger debate quality."
    },
    "source_reports": {
      "OXY": "results/OXY/2026-03-18/analysis_report.json",
      "VRT": "results/VRT/2026-03-18/analysis_report.json",
      "CF": "results/CF/2026-03-18/analysis_report.json",
      "CVX": "results/CVX/2026-03-18/analysis_report.json",
      "RTX": "results/RTX/2026-03-18/analysis_report.json"
    }
  },
  "x_feed_context": {
    "summary": "Manual X-feed is complete for 2026-03-18 (15/15 passes, READY, 43 merged symbols). For this basket, strongest live narratives are Iran-linked energy/defense rotation (CVX, RTX), AI datacenter power-infrastructure buildout (VRT), and bullish flow in CF/OXY.",
    "coverage": {
      "status": "READY",
      "passes_completed": 15,
      "passes_total": 15,
      "merged_symbols": 43,
      "target_tickers": [
        "OXY",
        "VRT",
        "CF",
        "CVX",
        "RTX"
      ],
      "covered_tickers": [
        "OXY",
        "VRT",
        "CF",
        "CVX",
        "RTX"
      ],
      "coverage_ratio": 1.0,
      "source_artifact": "eval_results/x_feed/2026-03-18/merged.json"
    },
    "active_themes": [
      {
        "theme": "ai_nuclear_power_buildout",
        "conviction": 0.85,
        "reasoning": "@AirbnBoost @EmmanuelInvest @AlAlphaResearch flagging nuclear beneficiaries and AI power/cooling infrastructure upgrades."
      },
      {
        "theme": "iran_war_energy_shock",
        "conviction": 0.9,
        "reasoning": "@TrueGemHunter @TheWealtharian highlighting Iran escalation impacts across oil and defense beneficiaries."
      }
    ],
    "high_signal_posts": [
      {
        "ticker": "CVX",
        "pass_number": 12,
        "source_pass_type": "thematic",
        "buzz_rank": 1,
        "sentiment": "BULLISH",
        "velocity": "ACCELERATING",
        "catalyst": "@TrueGemHunter: Iran war attacks on energy facilities spiking oil prices and sector rotation buzz"
      },
      {
        "ticker": "CVX",
        "pass_number": 6,
        "source_pass_type": "sector",
        "buzz_rank": 3,
        "sentiment": "BULLISH",
        "velocity": "ACCELERATING",
        "catalyst": "@rdd147 and @SeerFlooringInc pairing $CVX with XOM in energy pre-market watch and oil volatility posts"
      },
      {
        "ticker": "RTX",
        "pass_number": 12,
        "source_pass_type": "thematic",
        "buzz_rank": 19,
        "sentiment": "BULLISH",
        "velocity": "ACCELERATING",
        "catalyst": "@TheWealtharian: RTX munitions demand surge from Iran conflict narrative"
      },
      {
        "ticker": "VRT",
        "pass_number": 12,
        "source_pass_type": "thematic",
        "buzz_rank": 8,
        "sentiment": "BULLISH",
        "velocity": "STEADY",
        "catalyst": "@AlAlphaResearch: VRT cooling/power upgrades in AI data center 800V narrative"
      },
      {
        "ticker": "CF",
        "pass_number": 8,
        "source_pass_type": "sector",
        "buzz_rank": 2,
        "sentiment": "BULLISH",
        "velocity": "ACCELERATING",
        "catalyst": "@optionproclub flags $372k aggressive call buying on $CF + @3dotfunds ties to oil/fertilizer surge with @MrDKSpecial and @_TP888 adding flow alerts"
      },
      {
        "ticker": "OXY",
        "pass_number": 6,
        "source_pass_type": "sector",
        "buzz_rank": 4,
        "sentiment": "BULLISH",
        "velocity": "ACCELERATING",
        "catalyst": "@jsolo81 and @InvestmentGuru_ flagging $OXY in short-term energy momentum and Permian plays amid oil cooling signals"
      }
    ],
    "ticker_snapshot": {
      "OXY": {
        "mentions_estimate": 4,
        "sentiment_score": 0.5,
        "velocity_trend": "rising"
      },
      "VRT": {
        "mentions_estimate": 8,
        "sentiment_score": 0.5,
        "velocity_trend": "stable"
      },
      "CF": {
        "mentions_estimate": 2,
        "sentiment_score": 0.5,
        "velocity_trend": "rising"
      },
      "CVX": {
        "mentions_estimate": 1,
        "sentiment_score": 0.5,
        "velocity_trend": "rising"
      },
      "RTX": {
        "mentions_estimate": 19,
        "sentiment_score": 0.5,
        "velocity_trend": "rising"
      }
    }
  },
  "web_search_allowed": true,
  "constraints": {
    "max_position_pct": 0.1,
    "allow_new_positions": true
  },
  "known_gaps": [
    "Portfolio context is sourced from latest paper artifacts dated 2026-03-10 (not intraday live).",
    "Pass 14 options-flow payload for 2026-03-18 was empty after validation.",
    "Web search is allowed but not pre-populated with external citations in this packet."
  ]
}
```
