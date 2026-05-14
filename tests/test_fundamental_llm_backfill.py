import csv
import json

from typer.testing import CliRunner

from cli.main import app
from tradingagents.research.fundamental.src.panel.llm_backfill import prepare_historical_llm_backfill


runner = CliRunner()


def _write_panel(path):
    rows = [
        {
            "ticker": "AAA",
            "quarter": "2022Q1",
            "llm_required_derived_flag": "1",
            "llm_complete_derived_flag": "0",
            "llm_status": "",
            "entry_score_0_100": "82",
            "earnings_8k_accession": "0000000000-22-000001",
            "earnings_8k_primary_document": "aaa-8k.htm",
            "earnings_exhibit_document": "aaa-ex991.htm",
        },
        {
            "ticker": "BBB",
            "quarter": "2022Q2",
            "llm_required_derived_flag": "",
            "llm_required_for_full_buy_flag": "1",
            "llm_complete_derived_flag": "0",
            "llm_status": "",
            "entry_score_0_100": "79",
            "earnings_8k_accession": "0000000000-22-000002",
            "earnings_8k_primary_document": "bbb-8k.htm",
            "earnings_exhibit_document": "bbb-ex991.htm",
        },
        {
            "ticker": "NNN",
            "quarter": "2022Q2",
            "llm_required_derived_flag": "0",
            "llm_required_for_full_buy_flag": "0",
            "llm_complete_derived_flag": "0",
            "llm_status": "",
            "entry_score_0_100": "70",
            "earnings_8k_accession": "",
            "earnings_8k_primary_document": "",
            "earnings_exhibit_document": "",
        },
        {
            "ticker": "CCC",
            "quarter": "2022Q2",
            "llm_required_derived_flag": "1",
            "llm_complete_derived_flag": "1",
            "llm_status": "",
            "entry_score_0_100": "88",
            "earnings_8k_accession": "",
            "earnings_8k_primary_document": "",
            "earnings_exhibit_document": "",
        },
        {
            "ticker": "DDD",
            "quarter": "2022Q3",
            "llm_required_derived_flag": "1",
            "llm_complete_derived_flag": "",
            "llm_status": "complete",
            "entry_score_0_100": "91",
            "earnings_8k_accession": "",
            "earnings_8k_primary_document": "",
            "earnings_exhibit_document": "",
        },
        {
            "ticker": "EEE",
            "quarter": "2022Q3",
            "llm_required_derived_flag": "1",
            "llm_complete_derived_flag": "0",
            "llm_status": "",
            "entry_score_0_100": "77",
            "earnings_8k_accession": "",
            "earnings_8k_primary_document": "",
            "earnings_exhibit_document": "",
        },
        {
            "ticker": "ZZZ",
            "quarter": "2023Q1",
            "llm_required_derived_flag": "1",
            "llm_complete_derived_flag": "0",
            "llm_status": "",
            "entry_score_0_100": "90",
            "earnings_8k_accession": "",
            "earnings_8k_primary_document": "",
            "earnings_exhibit_document": "",
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "ticker",
        "quarter",
        "llm_required_derived_flag",
        "llm_required_for_full_buy_flag",
        "llm_complete_derived_flag",
        "llm_status",
        "entry_score_0_100",
        "earnings_8k_accession",
        "earnings_8k_primary_document",
        "earnings_exhibit_document",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_prepare_historical_llm_backfill_filters_editable_quarter_range(tmp_path):
    panel = tmp_path / "panel.csv"
    _write_panel(panel)

    result = prepare_historical_llm_backfill(
        panel_csv=panel,
        start_quarter="2022Q2",
        end_quarter="2022Q3",
        output_root=tmp_path / "out",
    )

    assert result["summary"]["missing_required_count"] == 2
    assert result["summary"]["counts_by_quarter"] == {"2022Q2": 1, "2022Q3": 1}
    assert result["missing_tickers"] == ["BBB", "EEE"]


def test_prepare_historical_llm_backfill_writes_outputs_and_manifest(tmp_path):
    panel = tmp_path / "panel.csv"
    _write_panel(panel)

    result = prepare_historical_llm_backfill(
        panel_csv=panel,
        start_quarter="2022Q1",
        end_quarter="2022Q3",
        output_root=tmp_path / "out",
    )

    paths = result["output_paths"]
    for key in ("missing_rows_csv", "ticker_list_txt", "summary_json", "manifest_jsonl", "evidence_packets_jsonl", "evidence_missing_csv"):
        assert paths[key]
        assert (tmp_path / "out" / paths[key]).exists()

    with (tmp_path / "out" / paths["summary_json"]).open(encoding="utf-8") as handle:
        summary = json.load(handle)
    assert summary["missing_required_count"] == 3
    assert summary["counts_by_quarter"] == {"2022Q1": 1, "2022Q2": 1, "2022Q3": 1}
    assert summary["evidence_packet_count"] == 0
    assert summary["evidence_missing_count"] == 3
    assert summary["llm_runnable_count"] == 0

    with (tmp_path / "out" / paths["manifest_jsonl"]).open(encoding="utf-8") as handle:
        packets = [json.loads(line) for line in handle]
    assert packets[0]["sample_id"] == "AAA_2022Q1"
    assert packets[0]["ticker"] == "AAA"
    assert packets[0]["quarter"] == "2022Q1"
    assert packets[0]["panel_row"]["entry_score_0_100"] == "82"


def test_prepare_historical_llm_backfill_builds_evidence_packets_from_sec_text(tmp_path):
    panel = tmp_path / "panel.csv"
    sec_text_root = tmp_path / "sec_text"
    sec_text_root.mkdir()
    _write_panel(panel)
    (sec_text_root / "AAA_000000000022000001_aaa-ex991.htm.txt").write_text(
        "AAA earnings exhibit evidence text",
        encoding="utf-8",
    )
    (sec_text_root / "AAA_000000000022000001_aaa-8k.htm.txt").write_text(
        "AAA primary 8-K text",
        encoding="utf-8",
    )

    result = prepare_historical_llm_backfill(
        panel_csv=panel,
        start_quarter="2022Q1",
        end_quarter="2022Q1",
        output_root=tmp_path / "out",
        sec_text_root=sec_text_root,
    )

    assert result["summary"]["missing_required_count"] == 1
    assert result["summary"]["evidence_packet_count"] == 1
    assert result["summary"]["evidence_missing_count"] == 0
    packets_path = tmp_path / "out" / result["output_paths"]["evidence_packets_jsonl"]
    packet = json.loads(packets_path.read_text(encoding="utf-8").strip())
    assert packet["sample_id"] == "AAA_2022Q1"
    assert packet["evidence_snippets"] == ["AAA earnings exhibit evidence text", "AAA primary 8-K text"]
    assert [ref["document_type"] for ref in packet["document_refs"]] == ["earnings_exhibit", "primary_8k"]


def test_prepare_historical_llm_backfill_sanitizes_outcome_fields_from_evidence_packets(tmp_path):
    panel = tmp_path / "panel.csv"
    sec_text_root = tmp_path / "sec_text"
    sec_text_root.mkdir()
    fieldnames = [
        "ticker",
        "quarter",
        "company_title",
        "pre_llm_fundamental_score",
        "tier_1_bucket",
        "llm_required_derived_flag",
        "llm_complete_derived_flag",
        "earnings_8k_accession",
        "earnings_exhibit_document",
        "winner_90d_30pct",
        "loser_90d_minus30pct",
        "return_90d_pct",
        "entry_open",
        "prior_entry_qoq_pct",
        "hp0_high_price_broad",
        "rm1_low_price_dislocation_momentum",
        "rm3_mid_price_dislocation_momentum",
        "tier1_L6_mid_price_rerater",
        "causal_change",
        "proof_alignment",
        "narrative_delta_score",
        "score_addition",
        "final_rank_score_0_100",
        "eligible_for_backtest",
        "candidate_state",
        "decision_type",
        "monitor_status",
        "primary_theme",
        "theme_confidence",
        "theme_driver_summary",
        "theme_evidence_summary",
        "theme_tailwind_score",
        "theme_acceleration_score",
        "filing_theme_growth_flag",
        "top15_bucket",
        "shadow_refill_status",
        "selection_rank",
    ]
    row = {
        "ticker": "AAA",
        "quarter": "2022Q1",
        "company_title": "AAA Inc",
        "pre_llm_fundamental_score": "82",
        "tier_1_bucket": "Tier 1",
        "llm_required_derived_flag": "1",
        "llm_complete_derived_flag": "0",
        "earnings_8k_accession": "0000000000-22-000001",
        "earnings_exhibit_document": "aaa-ex991.htm",
        "winner_90d_30pct": "1",
        "loser_90d_minus30pct": "0",
        "return_90d_pct": "42.0",
        "entry_open": "10.50",
        "prior_entry_qoq_pct": "12.3",
        "hp0_high_price_broad": "1",
        "rm1_low_price_dislocation_momentum": "1",
        "rm3_mid_price_dislocation_momentum": "1",
        "tier1_L6_mid_price_rerater": "1",
        "causal_change": "3",
        "proof_alignment": "3",
        "narrative_delta_score": "8",
        "score_addition": "3",
        "final_rank_score_0_100": "99",
        "eligible_for_backtest": "1",
        "candidate_state": "published",
        "decision_type": "buy",
        "monitor_status": "active",
        "primary_theme": "stale_theme",
        "theme_confidence": "high",
        "theme_driver_summary": "stale LLM theme summary",
        "theme_evidence_summary": "stale LLM evidence summary",
        "theme_tailwind_score": "20",
        "theme_acceleration_score": "15",
        "filing_theme_growth_flag": "1",
        "top15_bucket": "Top 10 core",
        "shadow_refill_status": "shadow",
        "selection_rank": "1",
    }
    with panel.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(row)
    (sec_text_root / "AAA_000000000022000001_aaa-ex991.htm.txt").write_text("evidence", encoding="utf-8")

    result = prepare_historical_llm_backfill(
        panel_csv=panel,
        start_quarter="2022Q1",
        end_quarter="2022Q1",
        output_root=tmp_path / "out",
        sec_text_root=sec_text_root,
    )

    packet = json.loads((tmp_path / "out" / result["output_paths"]["evidence_packets_jsonl"]).read_text(encoding="utf-8").strip())
    for blocked in (
        "winner_90d_30pct",
        "loser_90d_minus30pct",
        "return_90d_pct",
        "entry_open",
        "prior_entry_qoq_pct",
        "hp0_high_price_broad",
        "rm1_low_price_dislocation_momentum",
        "rm3_mid_price_dislocation_momentum",
        "tier1_L6_mid_price_rerater",
        "causal_change",
        "proof_alignment",
        "narrative_delta_score",
        "score_addition",
        "final_rank_score_0_100",
        "eligible_for_backtest",
        "candidate_state",
        "decision_type",
        "monitor_status",
        "primary_theme",
        "theme_confidence",
        "theme_driver_summary",
        "theme_evidence_summary",
        "theme_tailwind_score",
        "theme_acceleration_score",
        "filing_theme_growth_flag",
        "top15_bucket",
        "shadow_refill_status",
        "selection_rank",
    ):
        assert blocked not in packet
    assert packet["ticker"] == "AAA"
    assert packet["company_title"] == "AAA Inc"
    assert packet["pre_llm_fundamental_score"] == "82"


def test_prepare_historical_llm_backfill_rejects_generic_text_path(tmp_path):
    sec_text_root = tmp_path / "sec_text"
    sec_text_root.mkdir()
    text_path = sec_text_root / "AAA_000000000022000001_aaa_10q_q1x2022.htm.txt"
    text_path.write_text("10-Q text must not become LLM evidence", encoding="utf-8")
    panel = tmp_path / "panel.csv"
    panel.write_text(
        "ticker,quarter,llm_required_derived_flag,llm_complete_derived_flag,text_path\n"
        f"AAA,2022Q1,1,0,{text_path}\n",
        encoding="utf-8",
    )

    result = prepare_historical_llm_backfill(
        panel_csv=panel,
        start_quarter="2022Q1",
        end_quarter="2022Q1",
        output_root=tmp_path / "out",
        sec_text_root=sec_text_root,
    )

    assert result["summary"]["evidence_packet_count"] == 0
    assert result["summary"]["evidence_missing_count"] == 1


def test_prepare_historical_llm_backfill_falls_back_to_ticker_quarter_filename_scan(tmp_path):
    panel = tmp_path / "panel.csv"
    sec_text_root = tmp_path / "sec_text"
    sec_text_root.mkdir()
    panel.write_text(
        "ticker,quarter,llm_required_derived_flag,llm_complete_derived_flag,llm_status,entry_score_0_100,earnings_8k_accession,earnings_8k_primary_document,earnings_exhibit_document\n"
        "AAP,2024Q1,1,0,,80,,,,\n",
        encoding="utf-8",
    )
    (sec_text_root / "AAP_000115844924000120_aap_exhibit991xq1x2024.htm.txt").write_text(
        "AAP Q1 2024 exhibit evidence",
        encoding="utf-8",
    )
    (sec_text_root / "AAP_000115844924000121_aap_10q_q1x2024.htm.txt").write_text(
        "generic 10-Q must not be used",
        encoding="utf-8",
    )

    result = prepare_historical_llm_backfill(
        panel_csv=panel,
        start_quarter="2024Q1",
        end_quarter="2024Q1",
        output_root=tmp_path / "out",
        sec_text_root=sec_text_root,
    )

    assert result["summary"]["evidence_packet_count"] == 1
    packet = json.loads((tmp_path / "out" / result["output_paths"]["evidence_packets_jsonl"]).read_text(encoding="utf-8").strip())
    assert packet["sample_id"] == "AAP_2024Q1"
    assert packet["evidence_snippets"] == ["AAP Q1 2024 exhibit evidence"]
    assert packet["document_refs"][0]["document_type"] == "earnings_exhibit"


def test_prepare_historical_llm_backfill_falls_back_to_short_quarter_earnings_release(tmp_path):
    panel = tmp_path / "panel.csv"
    sec_text_root = tmp_path / "sec_text"
    sec_text_root.mkdir()
    panel.write_text(
        "ticker,quarter,llm_required_derived_flag,llm_complete_derived_flag,llm_status,entry_score_0_100,earnings_8k_accession,earnings_8k_primary_document,earnings_exhibit_document\n"
        "AAT,2023Q4,1,0,,80,,,,\n",
        encoding="utf-8",
    )
    (sec_text_root / "AAT_000150021724000003_a4q23earningsreleaseng.htm.txt").write_text(
        "AAT Q4 2023 earnings release",
        encoding="utf-8",
    )

    result = prepare_historical_llm_backfill(
        panel_csv=panel,
        start_quarter="2023Q4",
        end_quarter="2023Q4",
        output_root=tmp_path / "out",
        sec_text_root=sec_text_root,
    )

    assert result["summary"]["evidence_packet_count"] == 1
    packet = json.loads((tmp_path / "out" / result["output_paths"]["evidence_packets_jsonl"]).read_text(encoding="utf-8").strip())
    assert packet["sample_id"] == "AAT_2023Q4"
    assert packet["evidence_snippets"] == ["AAT Q4 2023 earnings release"]
    assert packet["document_refs"][0]["document_type"] == "earnings_exhibit"


def test_prepare_historical_llm_backfill_accepts_short_quarter_press_release(tmp_path):
    panel = tmp_path / "panel.csv"
    sec_text_root = tmp_path / "sec_text"
    sec_text_root.mkdir()
    panel.write_text(
        "ticker,quarter,llm_required_derived_flag,llm_complete_derived_flag,llm_status,entry_score_0_100,earnings_8k_accession,earnings_8k_primary_document,earnings_exhibit_document\n"
        "ADSK,2023Q4,1,0,,80,,,,\n",
        encoding="utf-8",
    )
    (sec_text_root / "ADSK_000076939723000022_q423pressrelease.htm.txt").write_text(
        "ADSK Q4 2023 press release",
        encoding="utf-8",
    )

    result = prepare_historical_llm_backfill(
        panel_csv=panel,
        start_quarter="2023Q4",
        end_quarter="2023Q4",
        output_root=tmp_path / "out",
        sec_text_root=sec_text_root,
    )

    assert result["summary"]["evidence_packet_count"] == 1
    packet = json.loads((tmp_path / "out" / result["output_paths"]["evidence_packets_jsonl"]).read_text(encoding="utf-8").strip())
    assert packet["sample_id"] == "ADSK_2023Q4"
    assert packet["evidence_snippets"] == ["ADSK Q4 2023 press release"]
    assert packet["document_refs"][0]["document_type"] == "earnings_exhibit"


def test_fundamental_llm_backfill_help_exposes_quarter_options():
    result = runner.invoke(app, ["fundamental-llm-backfill", "--help"])

    assert result.exit_code == 0
    assert "--start-quarter" in result.output
    assert "--end-quarter" in result.output
    assert "--llm-mode" in result.output


def test_fundamental_llm_backfill_non_prepare_without_packets_exits_nonzero(tmp_path):
    panel = tmp_path / "panel.csv"
    _write_panel(panel)

    result = runner.invoke(app, [
        "fundamental-llm-backfill",
        "--panel-csv", str(panel),
        "--start-quarter", "2022Q3",
        "--end-quarter", "2022Q3",
        "--output-root", str(tmp_path / "out"),
        "--llm-mode", "subagent",
    ])

    assert result.exit_code != 0
    assert "evidence packets" in result.output.lower()


def test_fundamental_llm_backfill_post_file_validates_sample_ids(tmp_path):
    panel = tmp_path / "panel.csv"
    sec_text_root = tmp_path / "sec_text"
    out = tmp_path / "out"
    post_llm = tmp_path / "post_llm.csv"
    sec_text_root.mkdir()
    _write_panel(panel)
    (sec_text_root / "AAA_000000000022000001_aaa-ex991.htm.txt").write_text("evidence", encoding="utf-8")
    post_llm.write_text(
        "sample_id,quarter,ticker,causal_change,proof_alignment,durability,operating_leverage_quality,negative_revision_risk,story_vs_numbers_gap_penalty,narrative_delta_bucket,confidence,theme_confidence,theme_role,theme_driver_type,theme_momentum,post_llm_demote_severity,post_llm_demote_reason_code,post_llm_demote_overrideable\n"
        "AAA_2022Q1,2022Q1,AAA,1,1,1,1,0,0,constructive,medium,none,none,none,unknown,none,,0\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, [
        "fundamental-llm-backfill",
        "--panel-csv", str(panel),
        "--start-quarter", "2022Q1",
        "--end-quarter", "2022Q1",
        "--output-root", str(out),
        "--sec-text-root", str(sec_text_root),
        "--llm-mode", "post-file",
        "--post-llm", str(post_llm),
        "--format", "json",
    ])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["llm_mode"] == "post-file"
    assert payload["post_file_validation"]["status"] == "pass"


def test_fundamental_llm_backfill_post_file_accepts_runner_shaped_json_list_fields(tmp_path):
    panel = tmp_path / "panel.csv"
    sec_text_root = tmp_path / "sec_text"
    out = tmp_path / "out"
    post_llm = tmp_path / "post_llm.csv"
    sec_text_root.mkdir()
    _write_panel(panel)
    (sec_text_root / "AAA_000000000022000001_aaa-ex991.htm.txt").write_text("evidence", encoding="utf-8")
    post_llm.write_text(
        "sample_id,quarter,ticker,causal_change,proof_alignment,durability,operating_leverage_quality,negative_revision_risk,story_vs_numbers_gap_penalty,narrative_delta_bucket,confidence,theme_confidence,theme_role,theme_driver_type,theme_momentum,secondary_themes,theme_tags,theme_evidence,post_llm_demote_severity,post_llm_demote_reason_code,post_llm_demote_overrideable\n"
        'AAA_2022Q1,2022Q1,AAA,1,1,1,1,0,0,constructive,medium,medium,direct_beneficiary,revenue,accelerating,"[""cloud""]","[""ai""]","[""revenue accelerated""]",none,,0\n',
        encoding="utf-8",
    )

    result = runner.invoke(app, [
        "fundamental-llm-backfill",
        "--panel-csv", str(panel),
        "--start-quarter", "2022Q1",
        "--end-quarter", "2022Q1",
        "--output-root", str(out),
        "--sec-text-root", str(sec_text_root),
        "--llm-mode", "post-file",
        "--post-llm", str(post_llm),
        "--format", "json",
    ])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["post_file_validation"]["status"] == "pass"


def test_fundamental_llm_backfill_post_file_rejects_ticker_quarter_mismatch(tmp_path):
    panel = tmp_path / "panel.csv"
    sec_text_root = tmp_path / "sec_text"
    out = tmp_path / "out"
    post_llm = tmp_path / "post_llm.csv"
    sec_text_root.mkdir()
    _write_panel(panel)
    (sec_text_root / "AAA_000000000022000001_aaa-ex991.htm.txt").write_text("evidence", encoding="utf-8")
    post_llm.write_text(
        "sample_id,quarter,ticker,causal_change,proof_alignment,durability,operating_leverage_quality,negative_revision_risk,story_vs_numbers_gap_penalty,narrative_delta_bucket,confidence,theme_confidence,theme_role,theme_driver_type,theme_momentum,post_llm_demote_severity,post_llm_demote_reason_code,post_llm_demote_overrideable\n"
        "AAA_2022Q1,2022Q2,BBB,1,1,1,1,0,0,constructive,medium,none,none,none,unknown,none,,0\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, [
        "fundamental-llm-backfill",
        "--panel-csv", str(panel),
        "--start-quarter", "2022Q1",
        "--end-quarter", "2022Q1",
        "--output-root", str(out),
        "--sec-text-root", str(sec_text_root),
        "--llm-mode", "post-file",
        "--post-llm", str(post_llm),
        "--format", "json",
    ])

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["post_file_validation"]["status"] == "hard_stop"
    assert "identity_mismatches" in payload["post_file_validation"]["summary"]


def test_fundamental_llm_backfill_post_file_rejects_invalid_values(tmp_path):
    panel = tmp_path / "panel.csv"
    sec_text_root = tmp_path / "sec_text"
    out = tmp_path / "out"
    post_llm = tmp_path / "post_llm.csv"
    sec_text_root.mkdir()
    _write_panel(panel)
    (sec_text_root / "AAA_000000000022000001_aaa-ex991.htm.txt").write_text("evidence", encoding="utf-8")
    post_llm.write_text(
        "sample_id,post_llm_candidate_flag,post_llm_high_priority_flag,post_llm_demote_flag,causal_change,negative_revision_risk,narrative_delta_bucket,operating_leverage_quality,durability,proof_alignment\n"
        "AAA_2022Q1,1,1,0,1,0,positive,good,good,aligned\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, [
        "fundamental-llm-backfill",
        "--panel-csv", str(panel),
        "--start-quarter", "2022Q1",
        "--end-quarter", "2022Q1",
        "--output-root", str(out),
        "--sec-text-root", str(sec_text_root),
        "--llm-mode", "post-file",
        "--post-llm", str(post_llm),
        "--format", "json",
    ])

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["post_file_validation"]["status"] == "hard_stop"
    assert "strict_value_errors" in payload["post_file_validation"]["summary"]


def test_fundamental_llm_backfill_post_file_rejects_wrong_deterministic_fields(tmp_path):
    panel = tmp_path / "panel.csv"
    sec_text_root = tmp_path / "sec_text"
    out = tmp_path / "out"
    post_llm = tmp_path / "post_llm.csv"
    sec_text_root.mkdir()
    _write_panel(panel)
    (sec_text_root / "AAA_000000000022000001_aaa-ex991.htm.txt").write_text("evidence", encoding="utf-8")
    post_llm.write_text(
        "sample_id,quarter,ticker,causal_change,proof_alignment,durability,operating_leverage_quality,negative_revision_risk,story_vs_numbers_gap_penalty,narrative_delta_bucket,confidence,theme_confidence,theme_role,theme_driver_type,theme_momentum,post_llm_demote_severity,post_llm_demote_reason_code,post_llm_demote_overrideable,score_addition,post_llm_demote_flag\n"
        "AAA_2022Q1,2022Q1,AAA,1,1,1,1,0,0,constructive,medium,none,none,none,unknown,none,,0,-3,1\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, [
        "fundamental-llm-backfill",
        "--panel-csv", str(panel),
        "--start-quarter", "2022Q1",
        "--end-quarter", "2022Q1",
        "--output-root", str(out),
        "--sec-text-root", str(sec_text_root),
        "--llm-mode", "post-file",
        "--post-llm", str(post_llm),
        "--format", "json",
    ])

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["post_file_validation"]["status"] == "hard_stop"
    assert "deterministic_mismatches" in payload["post_file_validation"]["summary"]


def test_fundamental_llm_backfill_post_file_rejects_theme_deterministic_mismatch(tmp_path):
    panel = tmp_path / "panel.csv"
    sec_text_root = tmp_path / "sec_text"
    out = tmp_path / "out"
    post_llm = tmp_path / "post_llm.csv"
    sec_text_root.mkdir()
    _write_panel(panel)
    (sec_text_root / "AAA_000000000022000001_aaa-ex991.htm.txt").write_text("evidence", encoding="utf-8")
    post_llm.write_text(
        "sample_id,quarter,ticker,causal_change,proof_alignment,durability,operating_leverage_quality,negative_revision_risk,story_vs_numbers_gap_penalty,narrative_delta_bucket,confidence,theme_confidence,theme_role,theme_driver_type,theme_momentum,theme_evidence,filing_theme_growth_flag,filing_theme_guidance_flag,filing_theme_margin_flag,filing_theme_customer_win_flag,filing_theme_capacity_expansion_flag,theme_acceleration_score,theme_tailwind_score,post_llm_demote_severity,post_llm_demote_reason_code,post_llm_demote_overrideable\n"
        'AAA_2022Q1,2022Q1,AAA,1,1,1,1,0,0,constructive,medium,medium,direct_beneficiary,revenue,accelerating,"[""growth evidence""]",1,0,0,0,0,0,20,none,,0\n',
        encoding="utf-8",
    )

    result = runner.invoke(app, [
        "fundamental-llm-backfill",
        "--panel-csv", str(panel),
        "--start-quarter", "2022Q1",
        "--end-quarter", "2022Q1",
        "--output-root", str(out),
        "--sec-text-root", str(sec_text_root),
        "--llm-mode", "post-file",
        "--post-llm", str(post_llm),
        "--format", "json",
    ])

    assert result.exit_code != 0
    payload = json.loads(result.output)
    mismatches = payload["post_file_validation"]["summary"]["deterministic_mismatches"]["AAA_2022Q1"]
    assert "theme_acceleration_score" in mismatches
