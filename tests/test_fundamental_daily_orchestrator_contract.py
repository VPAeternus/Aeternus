import csv
import json
from tradingagents.research.fundamental.src.daily_run.models import DailyRunConfig, GateResult, GateStatus
from tradingagents.research.fundamental.src.daily_run.orchestrator import DailyRunServices, run_daily_fundamental


def _write_master(path, count=5):
    path.write_text(json.dumps({"items": [{"symbol": f"T{i}", "cik": str(i + 1), "company_title": f"T{i} Inc"} for i in range(count)]}))


def _write_handoff(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"tickers": ["T1"], "metadata_by_ticker": {}, "source_stage": "daily_scout"}))


def _companyfacts_payload():
    return {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [{"end": "2026-03-31", "val": 1_000_000_000}]}},
                "NetIncomeLoss": {"units": {"USD": [{"end": "2026-03-31", "val": 120_000_000}]}},
                "Assets": {"units": {"USD": [{"end": "2026-03-31", "val": 800_000_000}]}},
                "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [{"end": "2026-03-31", "val": 150_000_000}]}},
                "NetCashProvidedByUsedInInvestingActivities": {"units": {"USD": [{"end": "2026-03-31", "val": -50_000_000}]}},
                "NetCashProvidedByUsedInFinancingActivities": {"units": {"USD": [{"end": "2026-03-31", "val": -10_000_000}]}},
            }
        }
    }


def _fake_orchestrator_fixture(tmp_path, mode="broad-master-final", skip_llm=False, fake_llm=None):
    master = tmp_path / "master.json"; _write_master(master, count=5)
    live = tmp_path / "live_sec"; (live / "companyfacts").mkdir(parents=True)
    for i in range(5):
        (live / "companyfacts" / f"CIK{str(i + 1).zfill(10)}.json").write_text(json.dumps(_companyfacts_payload()))
    def fake_coverage(*, out_root, universe_csv, eligible_json, quarter, live_sec_root):
        manifest = out_root / f"sec_coverage_manifest_{quarter}.csv"
        rows = []
        for ticker in ["T0", "T1", "T2", "T3", "T4"]:
            status = "CACHED_READY" if ticker in {"T1", "T2"} else "BLOCKED_METADATA_OR_ISSUER_REALITY"
            rows.append({"ticker": ticker, "quarter": quarter, "coverage_status": status, "missing_inputs": "" if status == "CACHED_READY" else "earnings_exhibit_metadata", "earnings_8k_accession": f"00000000-{ticker}", "earnings_8k_filing_date": "2026-05-08", "earnings_8k_primary_document": "8k.htm", "earnings_exhibit_document": "ex99.htm", "periodic_accession": f"00000000-{ticker}Q", "periodic_form": "10-Q", "periodic_filing_date": "2026-05-08", "periodic_primary_document": "10q.htm"})
        with manifest.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
        for ticker in ["T1", "T2"]:
            for accession, doc in [(f"00000000-{ticker}", "8k.htm"), (f"00000000-{ticker}", "ex99.htm"), (f"00000000-{ticker}Q", "10q.htm")]:
                path = live / "documents" / f"{ticker}_{accession.replace('-', '')}_{doc}"
                path.parent.mkdir(parents=True, exist_ok=True); path.write_text("<html>Management raised guidance and margins improved.</html>")
        return {"ticker_count": 5, "status_counts": {"CACHED_READY": 2, "BLOCKED_METADATA_OR_ISSUER_REALITY": 3}, "missing_input_counts": {"earnings_exhibit_metadata": 3}, "fetch_queue_count": 0, "blocked_tickers": [], "outputs": {"manifest_csv": str(manifest)}}
    def fake_prices(tickers, *, start, end):
        opens = {"T0": 20, "T1": 12, "T2": 8, "T3": 7, "T4": 30}
        return [{"ticker": t, "date": "2026-05-11", "open": opens[t], "close": opens[t]} for t in tickers]
    def default_llm(*, packets_path, output_root, config):
        packets = [json.loads(line) for line in packets_path.read_text().splitlines() if line.strip()]
        assert [p["ticker"] for p in packets] == ["T1", "T2"]
        out = output_root / "post_llm_scores.csv"
        rows = [{"sample_id": p["sample_id"], "ticker": p["ticker"], "quarter": p["quarter"], "post_llm_candidate_flag": "1", "post_llm_high_priority_flag": "1", "post_llm_demote_flag": "0", "causal_change": "3", "negative_revision_risk": "1", "narrative_delta_bucket": "constructive", "operating_leverage_quality": "1", "durability": "1", "proof_alignment": "2"} for p in packets]
        with out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
        return out
    def fake_publish(*, scores_csv, output_root, as_of, broad_universe_count, coverage_manifest):
        import pandas as pd
        assert len(pd.read_csv(scores_csv)) == broad_universe_count == 5
        return GateResult(10, "Top10 + Plus5 + shadow refill publish", GateStatus.PASS, {"input_rows": 5}, {"scores_csv": str(scores_csv)})
    cfg = DailyRunConfig(as_of="2026-05-12", quarter="2026Q2", mode=mode, output_root=tmp_path / "run", master_universe_path=master, handoff_path=None, sec_live_root=live, skip_llm=skip_llm, min_broad_universe_count=5)
    return cfg, DailyRunServices(price_provider=fake_prices, run_coverage=fake_coverage, run_llm=fake_llm or default_llm, publish=fake_publish)


def test_orchestrator_diagnostic_writes_manifest_and_stops_before_publish_when_skip_llm(tmp_path):
    master = tmp_path / "master.json"; handoff = tmp_path / "handoff.json"
    _write_master(master); _write_handoff(handoff)
    cfg = DailyRunConfig(as_of="2026-05-12", quarter="2026Q2", mode="diagnostic-only", output_root=tmp_path / "run", master_universe_path=master, handoff_path=handoff, skip_fetch=True, skip_llm=True, min_broad_universe_count=3)
    result = run_daily_fundamental(cfg)
    assert (cfg.output_root / "run_manifest.json").exists()
    assert result.summary["final"] is False
    assert any(g.gate_number == 1 for g in result.gates)


def test_orchestrator_broad_final_hard_stops_on_scout_only_universe(tmp_path):
    master = tmp_path / "master.json"; handoff = tmp_path / "handoff.json"
    _write_master(master, count=2); _write_handoff(handoff)
    cfg = DailyRunConfig(as_of="2026-05-12", quarter="2026Q2", mode="broad-master-final", output_root=tmp_path / "run", master_universe_path=master, handoff_path=handoff, skip_fetch=True, skip_llm=True, min_broad_universe_count=1000)
    result = run_daily_fundamental(cfg)
    assert result.summary["final"] is False
    assert result.gates[-1].status == GateStatus.HARD_STOP
    assert not (cfg.output_root / "high_conviction_top15.csv").exists()


def test_orchestrator_final_mode_preserves_broad_rows_and_filters_llm(tmp_path):
    cfg, services = _fake_orchestrator_fixture(tmp_path)
    result = run_daily_fundamental(cfg, services=services)
    assert result.summary["final"] is True
    assert result.gates[-1].gate_number == 10
    assert result.gates[-1].status == GateStatus.PASS
    assert (cfg.output_root / "fundamental_final_scores_2026-05-12.csv").exists()
    assert (cfg.output_root / "lake" / "artifacts" / "2026Q2_llm_packets.jsonl").exists()


def test_orchestrator_diagnostic_mode_with_skip_llm_false_does_not_require_post_llm_path(tmp_path):
    def fail_if_called(**kwargs):
        raise AssertionError("diagnostic mode must not call LLM")
    cfg, services = _fake_orchestrator_fixture(tmp_path, mode="diagnostic-only", skip_llm=False, fake_llm=fail_if_called)
    result = run_daily_fundamental(cfg, services=services)
    assert result.summary["final"] is False
    assert result.summary["stopped"] == "publish_skipped"
    assert any(g.gate_number == 8 and g.status == GateStatus.SKIPPED for g in result.gates)
    assert not (cfg.output_root / "high_conviction_top15.csv").exists()


def test_orchestrator_repeats_sec_fetch_until_queue_drains(tmp_path):
    master = tmp_path / "master.json"; _write_master(master, count=1)
    live = tmp_path / "live_sec"; (live / "companyfacts").mkdir(parents=True)
    (live / "companyfacts" / "CIK0000000001.json").write_text(json.dumps(_companyfacts_payload()))
    calls = {"coverage": 0, "fetch": 0}

    def fake_coverage(*, out_root, universe_csv, eligible_json, quarter, live_sec_root):
        calls["coverage"] += 1
        manifest = out_root / f"sec_coverage_manifest_{quarter}.csv"
        rows = [{"ticker": "T0", "quarter": quarter, "coverage_status": "CACHED_READY", "missing_inputs": "", "earnings_8k_accession": "1", "earnings_8k_filing_date": "2026-05-08", "earnings_8k_primary_document": "8k.htm", "earnings_exhibit_document": "ex99.htm", "periodic_accession": "2", "periodic_form": "10-Q", "periodic_filing_date": "2026-05-08", "periodic_primary_document": "10q.htm"}]
        manifest.parent.mkdir(parents=True, exist_ok=True)
        with manifest.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
        queue_by_call = {1: 2, 2: 1}
        return {"ticker_count": 1, "status_counts": {"CACHED_READY": 1}, "missing_input_counts": {}, "fetch_queue_count": queue_by_call.get(calls["coverage"], 0), "blocked_tickers": [], "outputs": {"manifest_csv": str(manifest)}}

    def fake_fetch(*, out_root, live_sec_root):
        calls["fetch"] += 1
        return {"status": "complete", "pass": calls["fetch"]}

    def fake_prices(tickers, *, start, end):
        return [{"ticker": "T0", "date": "2026-05-11", "open": 20, "close": 20}]

    cfg = DailyRunConfig(as_of="2026-05-12", quarter="2026Q2", mode="diagnostic-only", output_root=tmp_path / "run", master_universe_path=master, handoff_path=None, sec_live_root=live, skip_fetch=False, skip_llm=True, min_broad_universe_count=1)
    result = run_daily_fundamental(cfg, services=DailyRunServices(price_provider=fake_prices, run_coverage=fake_coverage, run_fetch_once=fake_fetch))
    gate4 = next(g for g in result.gates if g.gate_number == 4)
    assert gate4.status == GateStatus.PASS
    assert gate4.summary["fetch_pass_count"] == 2
    assert gate4.summary["final_fetch_queue_count"] == 0
    assert calls["fetch"] == 2
