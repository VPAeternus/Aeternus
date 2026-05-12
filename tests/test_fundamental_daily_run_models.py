import json
import pytest
from tradingagents.research.fundamental.src.daily_run.artifacts import write_json_atomic
from tradingagents.research.fundamental.src.daily_run.models import DailyRunConfig, GateResult, GateStatus, RunMode, StopGateError


def test_daily_run_config_rejects_missing_mode(tmp_path):
    with pytest.raises(ValueError, match="mode"):
        DailyRunConfig(as_of="2026-05-12", quarter="2026Q2", mode="", output_root=tmp_path).run_mode


def test_daily_run_config_accepts_broad_master_final(tmp_path):
    cfg = DailyRunConfig(as_of="2026-05-12", quarter="2026Q2", mode="broad-master-final", output_root=tmp_path)
    assert cfg.run_mode == RunMode.BROAD_MASTER_FINAL
    assert cfg.output_root == tmp_path


def test_gate_result_hard_stop_raises_stop_gate_error():
    result = GateResult(2, "Universe construction", GateStatus.HARD_STOP, {"reason": "scout_only_universe"}, {})
    with pytest.raises(StopGateError, match="Gate 2"):
        result.raise_if_hard_stop()


def test_write_json_atomic_round_trips(tmp_path):
    path = tmp_path / "run_manifest.json"
    write_json_atomic(path, {"status": "ok", "rows": 1276})
    assert json.loads(path.read_text()) == {"status": "ok", "rows": 1276}
