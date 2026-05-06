from __future__ import annotations

from typing import Any

from src.features.common import clean, to_float


NARRATIVE_RANK = {"deteriorating": 0, "neutral": 1, "constructive": 2, "inflecting": 3}


def classify_thesis_refresh(current_row: dict[str, Any], prior_row: dict[str, Any] | None = None) -> dict[str, Any]:
    prior = prior_row or {}
    current_score = to_float(current_row.get("entry_score_0_100"))
    prior_score = to_float(prior.get("entry_score_0_100"))
    score_change = "" if current_score is None or prior_score is None else int(current_score - prior_score)
    current_narrative = clean(current_row.get("narrative_delta_bucket"))
    prior_narrative = clean(prior.get("narrative_delta_bucket"))
    narrative_change = NARRATIVE_RANK.get(current_narrative, 1) - NARRATIVE_RANK.get(prior_narrative, 1)
    if score_change != "" and score_change >= 8 and narrative_change >= 0:
        status = "thesis_improved"
    elif current_narrative == "deteriorating" or (score_change != "" and score_change <= -15):
        status = "thesis_broken"
    elif score_change != "" and score_change <= -5:
        status = "thesis_weakened"
    elif score_change != "" and abs(score_change) <= 5 and narrative_change >= 0:
        status = "thesis_confirmed"
    else:
        status = "thesis_neutral"
    return {
        "prior_quarter_entry_score": "" if prior_score is None else int(prior_score),
        "score_change_qoq": score_change,
        "prior_narrative_bucket": prior_narrative,
        "narrative_change_qoq": narrative_change,
        "thesis_refresh_status": status,
    }
