import json
from pathlib import Path

from tradingagents.dealflow.discovery_reports import write_discovery_delta_report, write_theme_heatmap_report
from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph


def test_write_discovery_delta_report_persists_artifact(tmp_path):
    payload = write_discovery_delta_report(
        as_of_date="2026-05-05",
        out_dir=tmp_path,
        scout_audit={"date": "2026-05-05"},
        fvg_recall={"symbols": []},
        fma_recall={"symbols": []},
    )

    saved = json.loads((tmp_path / "discovery_delta.json").read_text())
    assert payload == saved
    assert "coverage_summary" in payload


def test_write_theme_heatmap_report_skips_when_akg_missing(tmp_path):
    assert write_theme_heatmap_report(None, as_of_date="2026-05-05", out_dir=tmp_path) is None


def test_write_theme_heatmap_report_default_path_compatibility(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    akg = AeternusKnowledgeGraph()
    akg.add_theme_node("optical_networking")
    akg.update_theme_acceleration_signal("GLW", {
        "as_of_date": "2026-05-05",
        "primary_theme": "optical_networking",
        "theme_confidence": "high",
        "theme_evidence": ["Optical demand drove segment growth."],
        "theme_acceleration_score": 10,
    })

    path = write_theme_heatmap_report(akg, as_of_date="2026-05-05")

    assert path == Path("eval_results") / "deal_flow" / "theme_heatmap_2026-05-05.json"
    assert (tmp_path / path).exists()


def test_write_theme_heatmap_report_persists_when_akg_present(tmp_path):
    akg = AeternusKnowledgeGraph()
    akg.add_theme_node("optical_networking")
    akg.update_theme_acceleration_signal("GLW", {
        "as_of_date": "2026-05-05",
        "primary_theme": "optical_networking",
        "theme_confidence": "high",
        "theme_evidence": ["Optical demand drove segment growth."],
        "theme_acceleration_score": 10,
    })

    path = write_theme_heatmap_report(akg, as_of_date="2026-05-05", out_dir=tmp_path)

    assert path == tmp_path / "theme_heatmap_2026-05-05.json"
    assert path.exists()
