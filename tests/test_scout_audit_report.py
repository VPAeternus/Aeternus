import json

from tradingagents.dealflow.scout_audit_report import build_and_write_scout_audit


def test_build_and_write_scout_audit_persists_compact_daily_record(tmp_path):
    audit = build_and_write_scout_audit(
        as_of_date="2026-05-05",
        breakout_result={"alerts": [{"ticker": "GLW", "score": 91, "near_high": 0.12345}]},
        iv_result={"force_queue": [{"ticker": "MP"}], "akg_enriched": ["MP"]},
        insider_result={"buy_clusters": [{"ticker": "META", "cluster_score": 70, "distinct_insiders": 2}], "sell_clusters": []},
        technical_ignition_result={"promoted_count": 1, "promoted_symbols": ["GLW"], "signals": [{"symbol": "GLW"}]},
        thirteenf_result={"candidate_count": 1, "symbols": ["GLW"], "policy_id": "top15"},
        out_root=tmp_path,
    )

    saved = json.loads((tmp_path / "2026-05-05" / "scout_audit.json").read_text())
    assert saved == audit
    assert audit["breakout"]["alerts"][0] == {"ticker": "GLW", "score": 91, "near_high": 0.1235}
    assert audit["technical_ignition"]["promoted_symbols"] == ["GLW"]
    assert audit["signals"] == [{"symbol": "GLW"}]
    assert audit["thirteenf_watchlist"]["policy_id"] == "top15"
