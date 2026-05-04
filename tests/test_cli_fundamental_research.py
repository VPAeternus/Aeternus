import json
import sys
import types
from pathlib import Path

import cli.commands.fundamental_research as fundamental_research_module
import pytest
from typer.testing import CliRunner

# Stub chromadb before cli.main import
if "chromadb" not in sys.modules or not hasattr(sys.modules.get("chromadb", None), "__path__"):
    _stub = types.ModuleType("chromadb")
    _stub.__path__ = []
    _stub.Client = None
    _config_stub = types.ModuleType("chromadb.config")
    _config_stub.Settings = type("Settings", (), {})
    sys.modules["chromadb"] = _stub
    sys.modules["chromadb.config"] = _config_stub

from cli.main import app


runner = CliRunner()


def test_fundamental_research_command_runs_on_prepared_rows_and_writes_summary(tmp_path: Path):
    prepared_path = tmp_path / "prepared_rows.json"
    prepared_path.write_text(
        json.dumps(
            [
                {
                    "ticker": "AAPL",
                    "effective_market_date": "2026-01-30",
                    "sector": "Technology",
                    "revenue_growth_yoy_pct": 8.5,
                    "fcf_growth_yoy_pct": 11.0,
                    "share_count_change_pct": -1.5,
                    "equity_change_pct": 6.0,
                    "gross_margin": 0.47,
                    "operating_margin": 0.31,
                    "debt_to_equity": 1.25,
                    "current_ratio": 1.10,
                    "ev_to_sales": 6.2,
                    "earnings_yield": 0.045,
                    "data_coverage_score": 0.92,
                    "return_60d": 0.10,
                },
                {
                    "ticker": "MSFT",
                    "effective_market_date": "2026-01-30",
                    "sector": "Technology",
                    "revenue_growth_yoy_pct": 7.0,
                    "fcf_growth_yoy_pct": 8.0,
                    "share_count_change_pct": -0.5,
                    "equity_change_pct": 4.0,
                    "gross_margin": 0.42,
                    "operating_margin": 0.28,
                    "debt_to_equity": 0.90,
                    "current_ratio": 1.20,
                    "ev_to_sales": 5.4,
                    "earnings_yield": 0.038,
                    "data_coverage_score": 0.90,
                    "return_60d": 0.08,
                },
                {
                    "ticker": "XOM",
                    "effective_market_date": "2026-01-30",
                    "sector": "Energy",
                    "revenue_growth_yoy_pct": 4.0,
                    "fcf_growth_yoy_pct": 5.0,
                    "share_count_change_pct": -2.0,
                    "equity_change_pct": 3.0,
                    "gross_margin": 0.25,
                    "operating_margin": 0.16,
                    "debt_to_equity": 0.55,
                    "current_ratio": 1.00,
                    "ev_to_sales": 2.8,
                    "earnings_yield": 0.070,
                    "data_coverage_score": 0.88,
                    "return_60d": 0.05,
                },
                {
                    "ticker": "CVX",
                    "effective_market_date": "2026-01-30",
                    "sector": "Energy",
                    "revenue_growth_yoy_pct": 2.5,
                    "fcf_growth_yoy_pct": 3.0,
                    "share_count_change_pct": -1.0,
                    "equity_change_pct": 2.0,
                    "gross_margin": 0.22,
                    "operating_margin": 0.13,
                    "debt_to_equity": 0.65,
                    "current_ratio": 0.95,
                    "ev_to_sales": 3.1,
                    "earnings_yield": 0.060,
                    "data_coverage_score": 0.87,
                    "return_60d": 0.03,
                },
            ]
        )
    )

    result = runner.invoke(
        app,
        [
            "fundamental-research",
            "--prepared-json",
            str(prepared_path),
            "--results-root",
            str(tmp_path / "results"),
            "--run-date",
            "2026-03-08",
            "--experiment-name",
            "baseline",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["dataset_name"] == "prepared_json"
    assert payload["score_version"] == "baseline_v1"
    assert payload["artifact_path"].endswith("summary.json")
    assert (tmp_path / "results" / "2026-03-08" / "baseline" / "summary.json").exists()


def test_fundamental_research_cache_fill_command_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def _fake_resolve(tickers, **kwargs):
        assert tickers == ["AAPL"]
        return {"AAPL": "0000320193"}

    def _fake_fill(universe, **kwargs):
        assert universe == ["AAPL"]
        assert kwargs["ticker_to_cik"] == {"AAPL": "0000320193"}
        return {"cached": ["AAPL"], "skipped_missing_cik": [], "failed": []}

    monkeypatch.setattr(fundamental_research_module, "resolve_ticker_cik_map", _fake_resolve)
    monkeypatch.setattr(fundamental_research_module, "fill_sec_cache_for_universe", _fake_fill)

    result = runner.invoke(
        app,
        [
            "fundamental-research-cache-fill",
            "--symbols",
            "AAPL",
            "--cache-root",
            str(tmp_path / "sec_cache"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["cached"] == ["AAPL"]
    assert payload["skipped_missing_cik"] == []
    assert payload["failed"] == []


def test_fundamental_research_cache_fill_command_accepts_universe_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    def _fake_get(name):
        assert name == "liquid_core_v1"
        return ["AAPL", "XOM"]

    def _fake_resolve(tickers, **kwargs):
        assert tickers == ["AAPL", "XOM"]
        return {"AAPL": "0000320193", "XOM": "0000034088"}

    def _fake_fill(universe, **kwargs):
        assert universe == ["AAPL", "XOM"]
        return {"cached": ["AAPL", "XOM"], "skipped_missing_cik": [], "failed": []}

    monkeypatch.setattr(fundamental_research_module, "get_v1_universe", _fake_get)
    monkeypatch.setattr(fundamental_research_module, "resolve_ticker_cik_map", _fake_resolve)
    monkeypatch.setattr(fundamental_research_module, "fill_sec_cache_for_universe", _fake_fill)

    result = runner.invoke(
        app,
        [
            "fundamental-research-cache-fill",
            "--universe-name",
            "liquid_core_v1",
            "--cache-root",
            str(tmp_path / "sec_cache"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["cached"] == ["AAPL", "XOM"]


def test_fundamental_research_prepare_command_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    sector_map_path = tmp_path / "sector_map.json"
    sector_map_path.write_text(json.dumps({"AAPL": "Technology"}))

    def _fake_build(*, cache_root, universe, sector_map=None, include_history=False, latest_only=True, start_year=None):
        assert universe == ["AAPL"]
        assert sector_map == {"AAPL": "Technology"}
        assert include_history is False
        assert latest_only is True
        assert start_year is None
        return [{"ticker": "AAPL", "effective_market_date": "2026-01-30"}]

    def _fake_write(rows, *, cache_root, run_name):
        path = Path(cache_root) / "prepared" / f"{run_name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows))
        return path

    monkeypatch.setattr(fundamental_research_module, "build_prepared_rows_from_cache", _fake_build)
    monkeypatch.setattr(fundamental_research_module, "write_prepared_rows", _fake_write)

    result = runner.invoke(
        app,
        [
            "fundamental-research-prepare",
            "--symbols",
            "AAPL",
            "--cache-root",
            str(tmp_path / "sec_cache"),
            "--sector-map-json",
            str(sector_map_path),
            "--run-name",
            "large_cap_v1-latest",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["rows"] == 1
    assert payload["artifact_path"].endswith("large_cap_v1-latest.json")


def test_fundamental_research_prepare_command_uses_large_cap_sector_map(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def _fake_build(*, cache_root, universe, sector_map=None, include_history=False, latest_only=True, start_year=None):
        assert universe == ["AAPL"]
        assert sector_map == {"AAPL": "Technology"}
        assert include_history is False
        assert latest_only is True
        assert start_year is None
        return [{"ticker": "AAPL", "effective_market_date": "2026-01-30", "sector": "Technology"}]

    def _fake_write(rows, *, cache_root, run_name):
        path = Path(cache_root) / "prepared" / f"{run_name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows))
        return path

    monkeypatch.setattr(fundamental_research_module, "build_prepared_rows_from_cache", _fake_build)
    monkeypatch.setattr(fundamental_research_module, "write_prepared_rows", _fake_write)

    result = runner.invoke(
        app,
        [
            "fundamental-research-prepare",
            "--symbols",
            "AAPL",
            "--cache-root",
            str(tmp_path / "sec_cache"),
            "--run-name",
            "large_cap_v1-latest",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout


def test_fundamental_research_prepare_command_accepts_universe_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def _fake_get(name):
        assert name == "liquid_core_v1"
        return ["AAPL", "XOM"]

    def _fake_sector_map(name):
        assert name == "liquid_core_v1"
        return {"AAPL": "Technology", "XOM": "Energy"}

    def _fake_build(*, cache_root, universe, sector_map=None, include_history=False, latest_only=True, start_year=None):
        assert universe == ["AAPL", "XOM"]
        assert sector_map == {"AAPL": "Technology", "XOM": "Energy"}
        return [{"ticker": "AAPL", "effective_market_date": "2026-01-30"}]

    def _fake_write(rows, *, cache_root, run_name):
        path = Path(cache_root) / "prepared" / f"{run_name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows))
        return path

    monkeypatch.setattr(fundamental_research_module, "get_v1_universe", _fake_get)
    monkeypatch.setattr(fundamental_research_module, "get_universe_sector_map", _fake_sector_map)
    monkeypatch.setattr(fundamental_research_module, "build_prepared_rows_from_cache", _fake_build)
    monkeypatch.setattr(fundamental_research_module, "write_prepared_rows", _fake_write)

    result = runner.invoke(
        app,
        [
            "fundamental-research-prepare",
            "--universe-name",
            "liquid_core_v1",
            "--cache-root",
            str(tmp_path / "sec_cache"),
            "--run-name",
            "liquid_core_v1-latest",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["rows"] == 1


def test_fundamental_research_build_universe_command_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def _fake_build(**kwargs):
        path = tmp_path / "liquid_core_v1.json"
        path.write_text(
            json.dumps(
                {
                    "name": "liquid_core_v1",
                    "count": 2,
                    "entries": [
                        {"ticker": "AAPL", "sector": "Technology"},
                        {"ticker": "XOM", "sector": "Energy"},
                    ],
                }
            )
        )
        return path

    def _fake_load(name, *, universe_root):
        assert name == "liquid_core_v1"
        return {
            "name": "liquid_core_v1",
            "count": 2,
            "entries": [
                {"ticker": "AAPL", "sector": "Technology"},
                {"ticker": "XOM", "sector": "Energy"},
            ],
        }

    monkeypatch.setattr(fundamental_research_module, "build_liquid_core_v1", _fake_build)
    monkeypatch.setattr(fundamental_research_module, "load_research_universe", _fake_load)

    result = runner.invoke(
        app,
        [
            "fundamental-research-build-universe",
            "--name",
            "liquid_core_v1",
            "--universe-root",
            str(tmp_path),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["name"] == "liquid_core_v1"
    assert payload["count"] == 2


def test_fundamental_research_attach_returns_command_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prepared_path = tmp_path / "prepared_rows.json"
    output_path = tmp_path / "prepared_rows_with_returns.json"
    prepared_path.write_text(json.dumps([{"ticker": "AAPL", "effective_market_date": "2026-01-30"}]))

    def _fake_load(path):
        assert Path(path) == prepared_path
        return [{"ticker": "AAPL", "effective_market_date": "2026-01-30"}]

    def _fake_enrich(rows, **kwargs):
        assert rows == [{"ticker": "AAPL", "effective_market_date": "2026-01-30"}]
        return [{"ticker": "AAPL", "effective_market_date": "2026-01-30", "return_60d": 0.1}]

    monkeypatch.setattr(fundamental_research_module, "load_prepared_rows", _fake_load)
    monkeypatch.setattr(fundamental_research_module, "enrich_prepared_rows_with_market_data", _fake_enrich)

    result = runner.invoke(
        app,
        [
            "fundamental-research-attach-returns",
            "--prepared-json",
            str(prepared_path),
            "--output-json",
            str(output_path),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout


def test_fundamental_research_qwen_autoresearch_command_reports_runner_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    prepared_path = tmp_path / "prepared_rows.json"
    prepared_path.write_text(json.dumps([{"ticker": "AAPL", "effective_market_date": "2026-01-30"}]))

    class _FakeError(RuntimeError):
        pass

    monkeypatch.setattr(
        fundamental_research_module,
        "load_prepared_rows",
        lambda path: [{"ticker": "AAPL", "effective_market_date": "2026-01-30"}],
    )
    monkeypatch.setattr(
        fundamental_research_module,
        "run_qwen_autoresearch",
        lambda *args, **kwargs: (_ for _ in ()).throw(_FakeError("Qwen server unavailable")),
    )

    result = runner.invoke(
        app,
        [
            "fundamental-research-qwen-autoresearch",
            "--prepared-json",
            str(prepared_path),
            "--results-root",
            str(tmp_path / "results"),
            "--run-date",
            "2026-03-09",
            "--experiment-name",
            "qwen-autoresearch",
            "--format",
            "json",
        ],
    )

    assert result.exit_code != 0
    assert "Qwen server unavailable" in result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["error"] == "Qwen server unavailable"


def test_fundamental_research_qwen_feature_lab_command_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    prepared_path = tmp_path / "prepared_rows.json"
    prepared_path.write_text(json.dumps([{"ticker": "AAPL", "effective_market_date": "2026-01-30"}]))

    monkeypatch.setattr(
        fundamental_research_module,
        "load_prepared_rows",
        lambda path: [{"ticker": "AAPL", "effective_market_date": "2026-01-30"}],
    )
    monkeypatch.setattr(
        fundamental_research_module,
        "run_qwen_feature_lab",
        lambda *args, **kwargs: {
            "leaderboard": [
                {
                    "strategy": "qwen_feature__base_0p8__growth_acceleration_0p1__margin_expansion_0p1",
                    "primary_metric_name": "rank_ic_60d_sector_neutral",
                    "primary_metric_value": 0.09,
                    "coverage_ratio": 0.98,
                    "observations": 100,
                }
            ],
            "best_strategy": {
                "strategy": "qwen_feature__base_0p8__growth_acceleration_0p1__margin_expansion_0p1",
                "primary_metric_name": "rank_ic_60d_sector_neutral",
                "primary_metric_value": 0.09,
                "coverage_ratio": 0.98,
                "observations": 100,
            },
            "proposal_count": 2,
            "accepted_count": 1,
            "rejected_count": 1,
            "model": "mlx-qwen-test",
        },
    )

    def _fake_write_summary(payload, *, results_root, run_date, experiment_name):
        path = Path(results_root) / run_date / experiment_name / "autoresearch_summary.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
        return path

    def _fake_write_best(payload, *, results_root, run_date, experiment_name):
        path = Path(results_root) / run_date / experiment_name / "best_strategy.json"
        path.write_text(json.dumps(payload))
        return path

    def _fake_write_leaderboard(payload, *, results_root, run_date, experiment_name):
        path = Path(results_root) / run_date / experiment_name / "leaderboard.json"
        path.write_text(json.dumps(payload))
        return path

    monkeypatch.setattr(fundamental_research_module, "write_autoresearch_summary", _fake_write_summary)
    monkeypatch.setattr(fundamental_research_module, "write_best_strategy", _fake_write_best)
    monkeypatch.setattr(fundamental_research_module, "write_leaderboard", _fake_write_leaderboard)

    result = runner.invoke(
        app,
        [
            "fundamental-research-qwen-feature-lab",
            "--prepared-json",
            str(prepared_path),
            "--results-root",
            str(tmp_path / "results"),
            "--run-date",
            "2026-03-09",
            "--experiment-name",
            "qwen-feature-lab",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["best_strategy"]["strategy"].startswith("qwen_feature__base_")
    assert payload["artifact_path"].endswith("autoresearch_summary.json")


def test_fundamental_research_compare_baselines_command_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prepared_path = tmp_path / "prepared_rows.json"
    prepared_path.write_text(json.dumps([{"ticker": "AAPL", "effective_market_date": "2026-01-30"}]))

    def _fake_compare(rows, *, dataset_name):
        assert rows == [{"ticker": "AAPL", "effective_market_date": "2026-01-30"}]
        assert dataset_name == "prepared_json"
        return [
            {
                "strategy": "baseline_v1",
                "primary_metric_name": "rank_ic_60d_sector_neutral",
                "primary_metric_value": 0.01,
                "coverage_ratio": 1.0,
                "observations": 1,
            }
        ]

    def _fake_write(rows, *, results_root, run_date, experiment_name):
        path = Path(results_root) / run_date / experiment_name / "baseline_comparison.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows))
        return path

    monkeypatch.setattr(fundamental_research_module, "compare_baseline_strategies", _fake_compare)
    monkeypatch.setattr(fundamental_research_module, "write_baseline_comparison", _fake_write)

    result = runner.invoke(
        app,
        [
            "fundamental-research-compare-baselines",
            "--prepared-json",
            str(prepared_path),
            "--results-root",
            str(tmp_path / "results"),
            "--run-date",
            "2026-03-08",
            "--experiment-name",
            "baseline-comparison",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["strategies"] == 1
    assert payload["artifact_path"].endswith("baseline_comparison.json")


def test_fundamental_research_autoresearch_command_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prepared_path = tmp_path / "prepared_rows.json"
    prepared_path.write_text(json.dumps([{"ticker": "AAPL", "effective_market_date": "2026-01-30"}]))

    def _fake_run(rows, *, dataset_name, top_n, robustness_top_n):
        assert rows == [{"ticker": "AAPL", "effective_market_date": "2026-01-30"}]
        assert dataset_name == "prepared_json"
        assert top_n == 5
        assert robustness_top_n == 2
        return {
            "strategy_count": 12,
            "leaderboard": [
                {
                    "strategy": "health_0p5__inv_growth_0p1__inv_quality_0p4",
                    "primary_metric_name": "rank_ic_60d_sector_neutral",
                    "primary_metric_value": 0.087029,
                    "coverage_ratio": 0.98,
                    "observations": 100,
                }
            ],
            "best_strategy": {
                "strategy": "health_0p5__inv_growth_0p1__inv_quality_0p4",
                "primary_metric_name": "rank_ic_60d_sector_neutral",
                "primary_metric_value": 0.087029,
                "coverage_ratio": 0.98,
                "observations": 100,
            },
            "top_robustness": {
                "health_0p5__inv_growth_0p1__inv_quality_0p4": {
                    "by_horizon": {"60d": {"primary_metric_value": 0.087029}}
                }
            },
        }

    def _fake_write_summary(payload, *, results_root, run_date, experiment_name):
        path = Path(results_root) / run_date / experiment_name / "autoresearch_summary.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
        return path

    def _fake_write_best(payload, *, results_root, run_date, experiment_name):
        path = Path(results_root) / run_date / experiment_name / "best_strategy.json"
        path.write_text(json.dumps(payload))
        return path

    def _fake_write_leaderboard(payload, *, results_root, run_date, experiment_name):
        path = Path(results_root) / run_date / experiment_name / "leaderboard.json"
        path.write_text(json.dumps(payload))
        return path

    def _fake_write_top_robustness(payload, *, results_root, run_date, experiment_name):
        path = Path(results_root) / run_date / experiment_name / "top_robustness.json"
        path.write_text(json.dumps(payload))
        return path

    def _fake_save_registry(rows, *, results_root, run_date, registry_name):
        path = Path(results_root) / run_date / f"{registry_name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows))
        return path

    monkeypatch.setattr(fundamental_research_module, "run_constrained_autoresearch", _fake_run)
    monkeypatch.setattr(fundamental_research_module, "write_autoresearch_summary", _fake_write_summary)
    monkeypatch.setattr(fundamental_research_module, "write_best_strategy", _fake_write_best)
    monkeypatch.setattr(fundamental_research_module, "write_leaderboard", _fake_write_leaderboard)
    monkeypatch.setattr(fundamental_research_module, "write_top_robustness", _fake_write_top_robustness)
    monkeypatch.setattr(fundamental_research_module, "save_signal_registry", _fake_save_registry)

    result = runner.invoke(
        app,
        [
            "fundamental-research-autoresearch",
            "--prepared-json",
            str(prepared_path),
            "--results-root",
            str(tmp_path / "results"),
            "--run-date",
            "2026-03-08",
            "--experiment-name",
            "autoresearch",
            "--top-n",
            "5",
            "--robustness-top-n",
            "2",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["strategy_count"] == 12
    assert payload["best_strategy"]["strategy"] == "health_0p5__inv_growth_0p1__inv_quality_0p4"
    assert payload["artifact_path"].endswith("autoresearch_summary.json")
    assert payload["registry_artifact_path"].endswith("fundamental_signals.json")


def test_fundamental_research_replay_arena_command_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prepared_path = tmp_path / "prepared_rows.json"
    prepared_path.write_text(json.dumps([{"ticker": "AAPL", "effective_market_date": "2026-01-30"}]))

    def _fake_run(rows, *, strategies, baseline_strategy, dataset_name):
        assert rows == [{"ticker": "AAPL", "effective_market_date": "2026-01-30"}]
        assert strategies == ["baseline_v1", "health_only", "quality_only_inverted"]
        assert baseline_strategy == "baseline_v1"
        assert dataset_name == "prepared_json"
        return {
            "baseline_strategy": "baseline_v1",
            "strategies": ["baseline_v1", "health_only", "quality_only_inverted"],
            "winners_by_horizon": {"60d": {"strategy": "health_only", "primary_metric_value": 0.08}},
            "by_strategy": {},
            "vs_baseline": {},
        }

    def _fake_write(payload, *, results_root, run_date, experiment_name):
        path = Path(results_root) / run_date / experiment_name / "replay_arena.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
        return path

    monkeypatch.setattr(fundamental_research_module, "run_replay_arena", _fake_run)
    monkeypatch.setattr(fundamental_research_module, "write_replay_arena", _fake_write)

    result = runner.invoke(
        app,
        [
            "fundamental-research-replay-arena",
            "--prepared-json",
            str(prepared_path),
            "--results-root",
            str(tmp_path / "results"),
            "--run-date",
            "2026-03-09",
            "--experiment-name",
            "arena",
            "--strategies",
            "baseline_v1,health_only,quality_only_inverted",
            "--baseline-strategy",
            "baseline_v1",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["artifact_path"].endswith("replay_arena.json")
    assert payload["result"]["winners_by_horizon"]["60d"]["strategy"] == "health_only"


def test_fundamental_research_promote_strategy_command_marks_shadow(tmp_path: Path):
    results_root = tmp_path / "results"
    summary_dir = results_root / "2026-03-09" / "broad-search"
    summary_dir.mkdir(parents=True)
    summary_path = summary_dir / "autoresearch_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "best_strategy": {
                    "strategy": "health_0p4__inv_quality_0p6",
                    "primary_metric_value": 0.023818,
                    "coverage_ratio": 0.98,
                    "observations": 15142,
                },
                "registry_rows": [
                    {
                        "strategy": "health_0p4__inv_quality_0p6",
                        "primary_metric_value": 0.023818,
                        "coverage_ratio": 0.98,
                        "observations": 15142,
                        "status": "candidate",
                        "recommended_status": "candidate",
                    },
                    {
                        "strategy": "old_shadow",
                        "primary_metric_value": 0.019036,
                        "coverage_ratio": 0.98,
                        "observations": 15142,
                        "status": "shadow",
                        "recommended_status": "shadow",
                    },
                ],
            }
        )
    )
    robustness_path = summary_dir / "robustness.json"
    robustness_path.write_text(
        json.dumps(
            {
                "by_horizon": {
                    "20d": {"primary_metric_value": 0.002496},
                    "60d": {"primary_metric_value": 0.023818},
                    "120d": {"primary_metric_value": 0.039137},
                    "252d": {"primary_metric_value": 0.059721},
                },
                "by_era": {
                    "2010_2019": {"primary_metric_value": 0.028461},
                    "2020_2026": {"primary_metric_value": 0.017939},
                },
                "by_sector": {
                    "Technology": {"primary_metric_value": 0.037672},
                    "Financials": {"primary_metric_value": 0.010000},
                    "Healthcare": {"primary_metric_value": 0.005000},
                },
            }
        )
    )

    result = runner.invoke(
        app,
        [
            "fundamental-research-promote-strategy",
            "--autoresearch-summary-json",
            str(summary_path),
            "--robustness-json",
            str(robustness_path),
            "--results-root",
            str(results_root),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["strategy"] == "health_0p4__inv_quality_0p6"
    assert payload["status"] == "shadow"
    assert payload["registry_artifact_path"].endswith("fundamental_signals.json")

    registry_path = results_root / "2026-03-09" / "fundamental_signals.json"
    rows = json.loads(registry_path.read_text())
    promoted = next(row for row in rows if row["strategy"] == "health_0p4__inv_quality_0p6")
    demoted = next(row for row in rows if row["strategy"] == "old_shadow")
    assert promoted["status"] == "shadow"
    assert promoted["manual_override"] is True
    assert promoted["gate_status"] == "FAILED"
    assert demoted["status"] == "candidate"


def test_fundamental_research_constrained_search_command_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prepared_path = tmp_path / "prepared_rows.json"
    prepared_path.write_text(json.dumps([{"ticker": "AAPL", "effective_market_date": "2026-01-30"}]))

    def _fake_search(rows, *, dataset_name):
        assert rows == [{"ticker": "AAPL", "effective_market_date": "2026-01-30"}]
        assert dataset_name == "prepared_json"
        return [
            {
                "strategy": "health_0p7__inv_quality_0p3",
                "weights": {"health": 0.7, "growth": 0.0, "quality": -0.3},
                "primary_metric_name": "rank_ic_60d_sector_neutral",
                "primary_metric_value": 0.07,
                "coverage_ratio": 1.0,
                "observations": 1,
            }
        ]

    def _fake_write(rows, *, results_root, run_date, experiment_name):
        path = Path(results_root) / run_date / experiment_name / "constrained_search.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows))
        return path

    monkeypatch.setattr(fundamental_research_module, "run_constrained_search", _fake_search)
    monkeypatch.setattr(fundamental_research_module, "write_constrained_search", _fake_write)

    result = runner.invoke(
        app,
        [
            "fundamental-research-constrained-search",
            "--prepared-json",
            str(prepared_path),
            "--results-root",
            str(tmp_path / "results"),
            "--run-date",
            "2026-03-08",
            "--experiment-name",
            "constrained-search",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["strategies"] == 1
    assert payload["artifact_path"].endswith("constrained_search.json")


def test_fundamental_research_robustness_command_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prepared_path = tmp_path / "prepared_rows.json"
    prepared_path.write_text(json.dumps([{"ticker": "AAPL", "effective_market_date": "2026-01-30"}]))

    def _fake_evaluate(rows, *, strategy):
        assert rows == [{"ticker": "AAPL", "effective_market_date": "2026-01-30"}]
        assert strategy == "health_0p5__inv_growth_0p1__inv_quality_0p4"
        return {
            "strategy": strategy,
            "by_horizon": {"60d": {"primary_metric_value": 0.08}},
            "by_era": {},
            "by_sector": {},
        }

    def _fake_write(payload, *, results_root, run_date, experiment_name):
        path = Path(results_root) / run_date / experiment_name / "robustness.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
        return path

    monkeypatch.setattr(fundamental_research_module, "evaluate_strategy_robustness", _fake_evaluate)
    monkeypatch.setattr(fundamental_research_module, "write_robustness_report", _fake_write)

    result = runner.invoke(
        app,
        [
            "fundamental-research-robustness",
            "--prepared-json",
            str(prepared_path),
            "--strategy",
            "health_0p5__inv_growth_0p1__inv_quality_0p4",
            "--results-root",
            str(tmp_path / "results"),
            "--run-date",
            "2026-03-08",
            "--experiment-name",
            "robustness",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["artifact_path"].endswith("robustness.json")
    assert payload["result"]["strategy"] == "health_0p5__inv_growth_0p1__inv_quality_0p4"


def test_fundamental_research_cache_fill_command_can_include_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def _fake_resolve(tickers, **kwargs):
        return {"AAPL": "0000320193"}

    def _fake_fill(universe, **kwargs):
        assert kwargs["include_history"] is True
        return {"cached": ["AAPL"], "skipped_missing_cik": [], "failed": []}

    monkeypatch.setattr(fundamental_research_module, "resolve_ticker_cik_map", _fake_resolve)
    monkeypatch.setattr(fundamental_research_module, "fill_sec_cache_for_universe", _fake_fill)

    result = runner.invoke(
        app,
        [
            "fundamental-research-cache-fill",
            "--symbols",
            "AAPL",
            "--include-history",
            "--cache-root",
            str(tmp_path / "sec_cache"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout


def test_fundamental_research_prepare_command_can_build_all_filings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def _fake_build(*, cache_root, universe, sector_map=None, include_history=False, latest_only=True, start_year=None):
        assert universe == ["AAPL"]
        assert sector_map == {"AAPL": "Technology"}
        assert include_history is True
        assert latest_only is False
        assert start_year == 2009
        return [{"ticker": "AAPL", "effective_market_date": "2026-01-30", "sector": "Technology"}]

    def _fake_write(rows, *, cache_root, run_name):
        path = Path(cache_root) / "prepared" / f"{run_name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows))
        return path

    monkeypatch.setattr(fundamental_research_module, "build_prepared_rows_from_cache", _fake_build)
    monkeypatch.setattr(fundamental_research_module, "write_prepared_rows", _fake_write)

    result = runner.invoke(
        app,
        [
            "fundamental-research-prepare",
            "--symbols",
            "AAPL",
            "--cache-root",
            str(tmp_path / "sec_cache"),
            "--all-filings",
            "--start-year",
            "2009",
            "--run-name",
            "large_cap_v1-2009plus",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout
