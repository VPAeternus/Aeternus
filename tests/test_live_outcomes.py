from tradingagents.evidence.live_outcomes import _extract_analysis_prediction


def test_extract_analysis_prediction_prefers_recommendation_direction():
    prediction = _extract_analysis_prediction(
        analysis_item={
            "recommendation": "BUY",
            "rating": "Hold",
            "confidence": 5,
        },
        track_entry=None,
    )

    assert prediction["recommendation"] == "BUY"
    assert prediction["rating"] == "Hold"
    assert prediction["predicted_direction"] == "LONG"
