import pytest

from tradingagents.research.fundamental.src.panel import selection_annotations
from tradingagents.research.fundamental.src.panel.selection_annotations import (
    attach_selection_annotations,
)


def test_attach_selection_annotations_marks_top15_and_shadow(tmp_path):
    rows = [
        {"ticker": "AAA", "quarter": "2026Q2"},
        {"ticker": "BBB", "quarter": "2026Q2"},
    ]
    top15 = tmp_path / "high_conviction_top15.csv"
    top15.write_text(
        "ticker,selection_rank,selected_sleeve,top15_bucket\nAAA,1,core,Top 10 core\n"
    )
    shadow = tmp_path / "shadow.csv"
    shadow.write_text(
        "ticker,selection_rank,selected_sleeve,shadow_refill_status\n"
        "BBB,1,core,shadow_refill_review_only_not_official\n"
    )

    out, summary = attach_selection_annotations(
        rows,
        top15_csv=top15,
        shadow_csv=shadow,
        quarter="2026Q2",
    )
    by_ticker = {row["ticker"]: row for row in out}
    assert by_ticker["AAA"]["top15_selected"] == "1"
    assert by_ticker["AAA"]["top15_selection_rank"] == "1"
    assert by_ticker["AAA"]["top15_selected_sleeve"] == "core"
    assert by_ticker["AAA"]["top15_bucket"] == "Top 10 core"
    assert by_ticker["BBB"]["shadow_selected"] == "1"
    assert by_ticker["BBB"]["shadow_selection_rank"] == "1"
    assert by_ticker["BBB"]["shadow_selected_sleeve"] == "core"
    assert (
        by_ticker["BBB"]["shadow_refill_status"]
        == "shadow_refill_review_only_not_official"
    )
    assert summary["top15_selected_count"] == 1
    assert summary["shadow_selected_count"] == 1


def test_attach_selection_annotations_raises_when_selected_ticker_missing(tmp_path):
    rows = [{"ticker": "AAA", "quarter": "2026Q2"}]
    top15 = tmp_path / "high_conviction_top15.csv"
    top15.write_text("ticker,selection_rank\nMISSING,1\n")

    with pytest.raises(ValueError, match="MISSING"):
        attach_selection_annotations(rows, top15_csv=top15, quarter="2026Q2")


def test_attach_selection_annotations_fills_unselected_flags(tmp_path):
    rows = [{"ticker": "AAA", "quarter": "2026Q2"}]
    out, summary = attach_selection_annotations(rows, quarter="2026Q2")

    assert out[0]["ticker"] == "AAA"
    assert out[0]["quarter"] == "2026Q2"
    assert out[0]["top15_selected"] == "0"
    assert out[0]["shadow_selected"] == "0"
    assert out[0]["top15_any_variant_selected"] == "0"
    assert out[0]["shadow_any_variant_selected"] == "0"
    assert summary["top15_selected_count"] == 0
    assert summary["shadow_selected_count"] == 0


def test_attach_selection_annotations_does_not_mutate_input(tmp_path):
    rows = [{"ticker": "aaa", "quarter": "2026Q2"}]
    top15 = tmp_path / "high_conviction_top15.csv"
    top15.write_text("ticker,top15_selection_rank\nAAA,7\n")

    out, _summary = attach_selection_annotations(
        rows,
        top15_csv=top15,
        quarter="2026Q2",
    )

    assert rows == [{"ticker": "aaa", "quarter": "2026Q2"}]
    assert out[0]["ticker"] == "aaa"
    assert out[0]["top15_selected"] == "1"
    assert out[0]["top15_selection_rank"] == "7"


def test_attach_selection_annotations_auto_top15_uses_official_config(
    tmp_path,
    monkeypatch,
):
    captured = {}

    def fake_select_top15(scores_csv, output_root, config, coverage_manifest=None):
        captured["scores_csv"] = scores_csv
        captured["output_root"] = output_root
        captured["config"] = config
        captured["coverage_manifest"] = coverage_manifest
        path = tmp_path / "high_conviction_top15.csv"
        path.write_text("ticker,selection_rank\nAAA,1\n")
        return {"output_paths": {"csv": str(path)}}

    def fake_select_shadow(scores_csv, output_root, config, coverage_manifest=None):
        path = tmp_path / "shadow.csv"
        path.write_text("ticker,selection_rank\n")
        return {"output_paths": {"csv": str(path)}}

    monkeypatch.setattr(
        selection_annotations,
        "select_top15_from_csv",
        fake_select_top15,
    )
    monkeypatch.setattr(
        selection_annotations,
        "select_top15_core_deterioration_refill_shadow_from_csv",
        fake_select_shadow,
    )

    out, summary = attach_selection_annotations(
        [{"ticker": "AAA", "quarter": "2026Q2"}],
        quarter="2026Q2",
        final_scores_csv=tmp_path / "scores.csv",
        output_root=tmp_path,
        coverage_manifest=tmp_path / "coverage.csv",
        selection_date="2026-05-13",
    )

    assert out[0]["top15_selected"] == "1"
    assert summary["top15_selected_count"] == 1
    assert captured["config"] == {
        "enabled": True,
        "core_n": 10,
        "exception_slots": 5,
        "selection_date": "2026-05-13",
    }


def test_attach_selection_annotations_auto_shadow_uses_strict_refill_config(
    tmp_path,
    monkeypatch,
):
    captured = {}

    def fake_select_shadow(scores_csv, output_root, config, coverage_manifest=None):
        captured["scores_csv"] = scores_csv
        captured["output_root"] = output_root
        captured["config"] = config
        captured["coverage_manifest"] = coverage_manifest
        path = tmp_path / "high_conviction_top15_core_deterioration_refill_shadow.csv"
        path.write_text("ticker,selection_rank\nBBB,1\n")
        return {"output_paths": {"csv": str(path)}}

    def fake_select_top15(scores_csv, output_root, config, coverage_manifest=None):
        path = tmp_path / "top15.csv"
        path.write_text("ticker,selection_rank\n")
        return {"output_paths": {"csv": str(path)}}

    monkeypatch.setattr(
        selection_annotations,
        "select_top15_from_csv",
        fake_select_top15,
    )
    monkeypatch.setattr(
        selection_annotations,
        "select_top15_core_deterioration_refill_shadow_from_csv",
        fake_select_shadow,
    )

    out, summary = attach_selection_annotations(
        [{"ticker": "BBB", "quarter": "2026Q2"}],
        quarter="2026Q2",
        final_scores_csv=tmp_path / "scores.csv",
        output_root=tmp_path,
        coverage_manifest=tmp_path / "coverage.csv",
        selection_date="2026-05-13",
    )

    assert out[0]["shadow_selected"] == "1"
    assert summary["shadow_selected_count"] == 1
    assert captured["config"] == {
        "enabled": True,
        "core_n": 10,
        "exception_slots": 5,
        "selection_date": "2026-05-13",
        "core_deterioration_refill": {"enabled": True, "mode": "strict"},
    }
