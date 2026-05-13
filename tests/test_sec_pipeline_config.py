import json
from pathlib import Path

from tradingagents.research.fundamental.src.sec_pipeline import cache_coverage_manifest as coverage
from tradingagents.research.fundamental.src.sec_pipeline import cache_download_queue as download
from tradingagents.research.fundamental.src.sec_pipeline import complete_submission_validation as validation
from tradingagents.research.fundamental.src.sec_pipeline import incremental_state
from tradingagents.research.fundamental.src.sec_pipeline.config import DEFAULT_QUARTERS, SecPipelineConfig, quarter_window_slug


def test_sec_pipeline_config_preserves_default_window_names():
    cfg = SecPipelineConfig()
    assert cfg.quarters == DEFAULT_QUARTERS
    assert cfg.window_slug == "2021Q4_2026Q1"
    assert cfg.coverage_manifest_csv.name == "sec_coverage_manifest_2021Q4_2026Q1.csv"
    assert cfg.download_manifest_json.name == "sec_download_manifest_2021Q4_2026Q1.json"


def test_sec_pipeline_config_derives_single_and_range_window_names(tmp_path):
    single = SecPipelineConfig(out=tmp_path / "single", live=tmp_path / "live", quarters=("2026Q2",))
    assert single.window_slug == "2026Q2"
    assert single.coverage_manifest_csv.name == "sec_coverage_manifest_2026Q2.csv"

    ranged = SecPipelineConfig(out=tmp_path / "range", live=tmp_path / "live", quarters=("2025Q4", "2026Q1", "2026Q2"))
    assert ranged.window_slug == "2025Q4_2026Q2"
    assert ranged.download_manifest_json.name == "sec_download_manifest_2025Q4_2026Q2.json"
    assert quarter_window_slug(["2026Q1", "2026Q2"]) == "2026Q1_2026Q2"


def test_coverage_configure_uses_requested_quarter_window(tmp_path):
    out = tmp_path / "out"
    live = tmp_path / "live_sec"
    coverage.configure(out=out, live=live, quarters=["2026Q2"])

    assert coverage.QUARTERS == ["2026Q2"]
    assert coverage.OUT == out
    assert coverage.LIVE == live
    assert coverage._CONFIG.coverage_manifest_csv == out / "sec_coverage_manifest_2026Q2.csv"
    assert coverage._CONFIG.fetch_queue_json == out / "sec_fetch_queue_resumable.json"


def test_validation_and_incremental_configure_use_requested_manifest_window(tmp_path):
    out = tmp_path / "out"
    live = tmp_path / "live_sec"
    validation.configure(out=out, live=live, quarters=["2026Q2"])
    incremental_state.configure(out=out, live=live, quarters=["2026Q2"])

    assert validation.MANIFEST_CSV == out / "sec_coverage_manifest_2026Q2.csv"
    assert incremental_state.MANIFEST_CSV == out / "sec_coverage_manifest_2026Q2.csv"
    assert incremental_state.QUEUE_JSON == out / "sec_fetch_queue_resumable.json"


def test_download_configure_uses_requested_window_slug(tmp_path):
    out = tmp_path / "out"
    live = tmp_path / "live_sec"
    download.configure(out=out, live=live, quarters=["2026Q1", "2026Q2"])

    assert download.QUEUE_PATH == out / "sec_fetch_queue_resumable.json"
    assert download.ELIGIBLE_PATH == out / "final_dealflow_tickers_sec_eligible.json"
    assert download.PROGRESS_PATH == out / "sec_download_progress.json"
    assert download.DOWNLOAD_MANIFEST_PATH == out / "sec_download_manifest_2026Q1_2026Q2.json"


def test_coverage_main_writes_dynamic_manifest_and_queue_quarters(tmp_path):
    out = tmp_path / "out"
    live = tmp_path / "live_sec"
    out.mkdir()
    live.mkdir()
    (out / "final_dealflow_tickers_sec_eligible.json").write_text(
        json.dumps({"items": [{"ticker": "AAA", "symbol": "AAA", "cik": "", "company_title": "AAA"}]}),
        encoding="utf-8",
    )
    (out / "dealflow_universe.csv").write_text("ticker,cik,company_title,cik_status\nAAA,,AAA,missing\n", encoding="utf-8")

    coverage.configure(out=out, live=live, quarters=["2026Q2"])
    coverage.main()

    assert (out / "sec_coverage_manifest_2026Q2.csv").exists()
    assert not (out / "sec_coverage_manifest_2021Q4_2026Q1.csv").exists()
    queue = json.loads((out / "sec_fetch_queue_resumable.json").read_text(encoding="utf-8"))
    assert queue["quarters"] == ["2026Q2"]
