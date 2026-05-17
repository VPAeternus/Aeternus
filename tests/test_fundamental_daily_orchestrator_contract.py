import csv
import json
import tradingagents.research.fundamental.src.daily_run.orchestrator as orchestrator_module
from tradingagents.research.fundamental.src.daily_run.models import DailyRunConfig, DailyRunState, GateResult, GateStatus
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


def _weak_companyfacts_payload():
    return {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [{"end": "2026-03-31", "val": 500_000_000}]}},
                "NetIncomeLoss": {"units": {"USD": [{"end": "2026-03-31", "val": -100_000_000}]}},
                "Assets": {"units": {"USD": [{"end": "2026-03-31", "val": 1_000_000_000}]}},
                "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [{"end": "2026-03-31", "val": -50_000_000}]}},
                "NetCashProvidedByUsedInInvestingActivities": {"units": {"USD": [{"end": "2026-03-31", "val": -50_000_000}]}},
                "NetCashProvidedByUsedInFinancingActivities": {"units": {"USD": [{"end": "2026-03-31", "val": 100_000_000}]}},
            }
        }
    }


def _write_prior_context(path, tickers=("T0", "T1", "T2", "T3", "T4"), quarter="2026Q1"):
    rows = [
        {
            "ticker": ticker,
            "quarter": quarter,
            "entry_open": "10",
            "entry_qoq_pct": "5",
            "pre_llm_fundamental_score": "1",
            "score_addition": "10",
            "causal_change": "2",
            "negative_revision_risk": "1",
            "narrative_delta_bucket": "constructive",
            "operating_leverage_quality": "1",
            "durability": "1",
            "proof_alignment": "2",
            "post_llm_candidate_flag": "1",
            "post_llm_high_priority_flag": "0",
            "post_llm_demote_flag": "0",
        }
        for ticker in tickers
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)


def test_prior_recovery_treats_missing_prior_filing_as_impossible():
    row = {
        "coverage_status": "BLOCKED_METADATA_OR_ISSUER_REALITY",
        "missing_inputs": "10q_10k_metadata",
        "notes": "no_item_2_02_8k_using_periodic_only",
        "earnings_8k_accession": "",
        "earnings_8k_primary_document": "",
        "earnings_exhibit_document": "",
    }
    assert orchestrator_module._coverage_proves_no_earnings_evidence(row) is True


def _fake_orchestrator_fixture(tmp_path, mode="broad-master-final", skip_llm=False, fake_llm=None):
    master = tmp_path / "master.json"; _write_master(master, count=5)
    handoff = tmp_path / "handoff.json"; handoff.write_text(json.dumps({"tickers": [], "metadata_by_ticker": {}, "source_stage": "daily_scout"}))
    prior = tmp_path / "prior_scores.csv"; _write_prior_context(prior)
    live = tmp_path / "live_sec"; (live / "companyfacts").mkdir(parents=True)
    for i in range(5):
        if i in {3, 4}:
            continue
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
        opens = {"T0": 20, "T1": 12, "T2": 8, "T3": 30, "T4": 30}
        return [{"ticker": t, "date": "2026-05-11", "open": opens[t], "close": opens[t]} for t in tickers]
    def default_llm(*, packets_path, output_root, config):
        packets = [json.loads(line) for line in packets_path.read_text().splitlines() if line.strip()]
        assert [p["ticker"] for p in packets] == ["T1", "T2"]
        out = output_root / "post_llm_scores.csv"
        rows = [{"sample_id": p["sample_id"], "ticker": p["ticker"], "quarter": p["quarter"], "post_llm_candidate_flag": "1", "post_llm_high_priority_flag": "1", "post_llm_demote_flag": "0", "causal_change": "3", "negative_revision_risk": "1", "narrative_delta_bucket": "constructive", "operating_leverage_quality": "1", "durability": "1", "proof_alignment": "2"} for p in packets]
        with out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
        return out
    def fake_publish(*, scores_csv, output_root, as_of, broad_universe_count, explicit_invalid_quarantine_count=0, coverage_manifest=None):
        import pandas as pd
        assert len(pd.read_csv(scores_csv)) + explicit_invalid_quarantine_count == broad_universe_count == 5
        top15_csv = output_root / "high_conviction_top15.csv"
        top15_json = output_root / "high_conviction_top15.json"
        top15_md = output_root / "high_conviction_top15_daily_recommendation.md"
        top15_csv.write_text("ticker,top15_bucket\nT1,Top 10 core\n", encoding="utf-8")
        top15_json.write_text(json.dumps({"selected_rows": [{"ticker": "T1"}]}), encoding="utf-8")
        top15_md.write_text("# Top 10 + Plus 5\n", encoding="utf-8")
        return GateResult(
            10,
            "Top10 + Plus5 + shadow refill publish",
            GateStatus.PASS,
            {"input_rows": 5},
            {"scores_csv": str(scores_csv), "top15_csv": str(top15_csv), "top15_json": str(top15_json), "top15_recommendation_md": str(top15_md)},
        )
    cfg = DailyRunConfig(as_of="2026-05-12", quarter="2026Q2", mode=mode, output_root=tmp_path / "run", master_universe_path=master, handoff_path=handoff, sec_live_root=live, skip_llm=skip_llm, prior_context_path=prior, min_broad_universe_count=5)
    return cfg, DailyRunServices(price_provider=fake_prices, run_coverage=fake_coverage, run_llm=fake_llm or default_llm, publish=fake_publish)


def test_orchestrator_diagnostic_writes_manifest_and_stops_before_publish_when_skip_llm(tmp_path):
    master = tmp_path / "master.json"; handoff = tmp_path / "handoff.json"
    _write_master(master); _write_handoff(handoff)
    cfg = DailyRunConfig(as_of="2026-05-12", quarter="2026Q2", mode="diagnostic-only", output_root=tmp_path / "run", master_universe_path=master, handoff_path=handoff, skip_fetch=True, skip_llm=True, min_broad_universe_count=3)
    result = run_daily_fundamental(cfg)
    assert (cfg.output_root / "run_manifest.json").exists()
    assert result.summary["final"] is False
    assert any(g.gate_number == 1 for g in result.gates)


def test_orchestrator_broad_final_hard_stops_when_handoff_missing(tmp_path):
    cfg, services = _fake_orchestrator_fixture(tmp_path)
    cfg = DailyRunConfig(**{**cfg.__dict__, "mode": "broad-master-final", "handoff_path": None})
    result = run_daily_fundamental(cfg, services=services)
    assert result.summary["final"] is False
    assert result.gates[-1].gate_number == 2
    assert result.gates[-1].status == GateStatus.HARD_STOP
    assert result.gates[-1].summary["reason"] == "missing_daily_handoff"


def test_orchestrator_diagnostic_only_reports_missing_handoff_plainly(tmp_path):
    cfg, services = _fake_orchestrator_fixture(tmp_path, mode="diagnostic-only", skip_llm=True)
    cfg = DailyRunConfig(**{**cfg.__dict__, "handoff_path": None})
    result = run_daily_fundamental(cfg, services=services)
    gate2 = next(g for g in result.gates if g.gate_number == 2)
    assert gate2.status == GateStatus.PASS
    assert gate2.summary["handoff_missing"] is True
    assert gate2.summary["handoff_policy"] == "allowed_missing"


def test_orchestrator_scout_smoke_hard_stops_without_handoff_or_override(tmp_path):
    cfg, services = _fake_orchestrator_fixture(tmp_path, mode="scout-smoke", skip_llm=True)
    cfg = DailyRunConfig(**{**cfg.__dict__, "handoff_path": None})
    result = run_daily_fundamental(cfg, services=services)
    assert result.summary["final"] is False
    assert result.gates[-1].gate_number == 2
    assert result.gates[-1].status == GateStatus.HARD_STOP
    assert result.gates[-1].summary["reason"] == "missing_daily_handoff"


def test_orchestrator_broad_final_hard_stops_on_scout_only_universe(tmp_path):
    master = tmp_path / "master.json"; handoff = tmp_path / "handoff.json"
    _write_master(master, count=2); _write_handoff(handoff)
    cfg = DailyRunConfig(as_of="2026-05-12", quarter="2026Q2", mode="broad-master-final", output_root=tmp_path / "run", master_universe_path=master, handoff_path=handoff, skip_fetch=True, skip_llm=True, min_broad_universe_count=1000)
    result = run_daily_fundamental(cfg)
    assert result.summary["final"] is False
    assert result.gates[-1].status == GateStatus.HARD_STOP
    assert not (cfg.output_root / "high_conviction_top15.csv").exists()


def test_orchestrator_final_mode_preserves_broad_rows_filters_llm_and_requires_qoq(tmp_path):
    cfg, services = _fake_orchestrator_fixture(tmp_path)
    assert cfg.emit_complete_panel is False
    result = run_daily_fundamental(cfg, services=services)
    assert result.summary["final"] is True
    assert result.gates[-1].gate_number == 10
    assert result.gates[-1].status == GateStatus.PASS
    gate9 = next(g for g in result.gates if g.gate_number == 9)
    assert gate9.summary["prior_context_loaded"] is True
    assert gate9.summary["llm_complete_qoq_missing_rows"] == 0
    assert gate9.summary["llm_complete_rows"] == 2
    assert (cfg.output_root / "fundamental_final_scores_2026-05-12.csv").exists()
    assert (cfg.output_root / "lake" / "artifacts" / "2026Q2_llm_packets.jsonl").exists()
    final_dir = cfg.output_root / "final"
    assert (final_dir / "fundamental_final_scores.csv").exists()
    assert (final_dir / "high_conviction_top15.csv").read_text(encoding="utf-8").startswith("ticker,top15_bucket")
    assert (final_dir / "high_conviction_top15.json").exists()
    assert (final_dir / "high_conviction_top15_daily_recommendation.md").exists()
    guard = json.loads((final_dir / "publish_guard_summary.json").read_text(encoding="utf-8"))
    assert guard["status"] == "pass"
    assert result.artifacts["operator_final_scores_csv"] == str(final_dir / "fundamental_final_scores.csv")
    assert "complete_panel_csv" not in result.artifacts


def test_orchestrator_writes_plain_publish_readiness_summary(tmp_path):
    cfg, services = _fake_orchestrator_fixture(tmp_path)
    result = run_daily_fundamental(cfg, services=services)

    readiness_json = cfg.output_root / "publish_readiness_summary.json"
    readiness_md = cfg.output_root / "publish_readiness_summary.md"
    assert readiness_json.exists()
    assert readiness_md.exists()
    readiness = json.loads(readiness_json.read_text(encoding="utf-8"))
    assert readiness["status"] == "pass"
    assert readiness["gates_passed"] is True
    assert readiness["llm_complete"] is True
    assert readiness["prior_context_complete"] is True
    assert readiness["qoq_missing_count"] == 0
    assert readiness["top15_emitted"] is True
    assert readiness["shadow_replacement_count"] == 0
    assert result.artifacts["publish_readiness_summary_json"] == str(readiness_json)
    assert "Status: pass" in readiness_md.read_text(encoding="utf-8")


def test_publish_readiness_does_not_mark_missing_prior_context_complete(tmp_path):
    cfg, services = _fake_orchestrator_fixture(tmp_path, mode="scout-smoke", skip_llm=True)
    cfg = DailyRunConfig(**{**cfg.__dict__, "prior_context_path": None})

    result = run_daily_fundamental(cfg, services=services)

    readiness = json.loads((cfg.output_root / "publish_readiness_summary.json").read_text(encoding="utf-8"))
    assert result.summary["final"] is False
    assert readiness["prior_context_loaded"] is False
    assert readiness["prior_context_complete"] is False
    assert readiness["prior_context_reason"] == "missing_prior_final_scores"


def test_publish_readiness_requires_prior_match_for_llm_eligible_rows(tmp_path):
    cfg = DailyRunConfig(as_of="2026-05-12", quarter="2026Q2", mode="scout-smoke", output_root=tmp_path / "run")
    state = DailyRunState(config=cfg, run_id="test")
    for gate_number in range(1, 11):
        summary = {}
        if gate_number == 7:
            summary = {"llm_eligible_count": 2}
        if gate_number == 8:
            summary = {"packet_count": 2}
        if gate_number == 9:
            summary = {
                "prior_context_loaded": True,
                "expected_prior_context_rows": 10,
                "prior_duplicate_key_count": 0,
                "qoq_context_match_rows": 0,
                "llm_complete_qoq_missing_rows": 0,
                "prior_llm_extract_missing_for_final_count": 0,
            }
        state.record(GateResult(gate_number, f"Gate {gate_number}", GateStatus.PASS, summary, {}))

    artifacts = orchestrator_module._write_publish_readiness_summary(state, final=False, stopped="publish_skipped")

    readiness = json.loads((cfg.output_root / "publish_readiness_summary.json").read_text(encoding="utf-8"))
    assert artifacts["publish_readiness_summary_json"] == str(cfg.output_root / "publish_readiness_summary.json")
    assert readiness["prior_context_complete"] is False
    assert readiness["llm_eligible_count"] == 2
    assert readiness["qoq_context_match_rows"] == 0


def test_publish_readiness_preserves_packet_count_when_llm_is_queued(tmp_path):
    cfg, services = _fake_orchestrator_fixture(tmp_path)
    result = run_daily_fundamental(cfg, services=DailyRunServices(**{**services.__dict__, "run_llm": None}))

    gate8 = next(g for g in result.gates if g.gate_number == 8)
    assert gate8.status == GateStatus.HARD_STOP
    assert gate8.summary["packet_count"] == 2

    readiness = json.loads((cfg.output_root / "publish_readiness_summary.json").read_text(encoding="utf-8"))
    assert readiness["llm_expected_count"] == 2
    assert readiness["llm_completed_count"] == 0
    assert "LLM complete: False (0/2)" in (cfg.output_root / "publish_readiness_summary.md").read_text(encoding="utf-8")


def test_orchestrator_quarantines_no_periodic_filing_before_price_gate(tmp_path):
    master = tmp_path / "master.json"
    master.write_text(json.dumps({"items": [{"symbol": "GOOD", "cik": "1", "company_title": "Good Inc"}, {"symbol": "ADR", "cik": "2", "company_title": "Foreign ADR"}]}))
    handoff = tmp_path / "handoff.json"
    handoff.write_text(json.dumps({"tickers": [], "metadata_by_ticker": {}, "source_stage": "daily_scout"}))
    prior = tmp_path / "prior_scores.csv"
    _write_prior_context(prior, tickers=("GOOD",), quarter="2026Q1")
    live = tmp_path / "live_sec"
    (live / "companyfacts").mkdir(parents=True)
    (live / "companyfacts" / "CIK0000000001.json").write_text(json.dumps(_weak_companyfacts_payload()))
    (live / "companyfacts" / "CIK0000000002.json").write_text(json.dumps(_weak_companyfacts_payload()))

    def fake_coverage(*, out_root, universe_csv, eligible_json, quarter, live_sec_root):
        manifest = out_root / f"sec_coverage_manifest_{quarter}.csv"
        rows = [
            {"ticker": "GOOD", "quarter": quarter, "coverage_status": "CACHED_READY", "missing_inputs": "", "notes": "", "earnings_8k_accession": "00000000-GOOD", "earnings_8k_filing_date": "2026-05-08", "earnings_8k_primary_document": "8k.htm", "earnings_exhibit_document": "ex99.htm", "periodic_accession": "00000000-GOODQ", "periodic_form": "10-Q", "periodic_filing_date": "2026-05-08", "periodic_primary_document": "10q.htm"},
            {"ticker": "ADR", "quarter": quarter, "coverage_status": "BLOCKED_METADATA_OR_ISSUER_REALITY", "missing_inputs": "10q_10k_metadata", "notes": "foreign_issuer_or_no_domestic_10q_10k", "earnings_8k_accession": "", "earnings_8k_filing_date": "", "earnings_8k_primary_document": "", "earnings_exhibit_document": "", "periodic_accession": "", "periodic_form": "", "periodic_filing_date": "", "periodic_primary_document": ""},
        ]
        with manifest.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return {"ticker_count": 2, "status_counts": {"CACHED_READY": 1, "BLOCKED_METADATA_OR_ISSUER_REALITY": 1}, "missing_input_counts": {"10q_10k_metadata": 1}, "fetch_queue_count": 0, "blocked_tickers": ["ADR"], "outputs": {"manifest_csv": str(manifest)}}

    def fake_prices(tickers, *, start, end, **kwargs):
        assert tickers == ["GOOD"]
        return [{"ticker": "GOOD", "date": "2026-05-11", "open": 8, "close": 8}]

    cfg = DailyRunConfig(
        as_of="2026-05-12",
        quarter="2026Q2",
        mode="broad-master-final",
        output_root=tmp_path / "run",
        master_universe_path=master,
        handoff_path=handoff,
        sec_live_root=live,
        skip_llm=True,
        prior_context_path=prior,
        min_broad_universe_count=2,
    )
    result = run_daily_fundamental(cfg, services=DailyRunServices(price_provider=fake_prices, run_coverage=fake_coverage))

    gate6 = next(g for g in result.gates if g.gate_number == 6)
    assert gate6.status == GateStatus.PASS
    assert gate6.summary["missing_entry_open"] == 0
    assert gate6.summary["sec_reality_quarantine_count"] == 1
    with (cfg.output_root / "score_input_quarantine.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["ticker"] == "ADR"
    assert rows[0]["score_input_quarantine_reason"] == "missing_periodic_10q_10k"


def test_orchestrator_rejects_llm_required_rows_when_no_earnings_8k_exists(tmp_path):
    master = tmp_path / "master.json"
    master.write_text(json.dumps({"items": [{"symbol": "GOOD", "cik": "1", "company_title": "Good Inc"}, {"symbol": "NO8K", "cik": "2", "company_title": "No 8-K Inc"}]}))
    handoff = tmp_path / "handoff.json"
    handoff.write_text(json.dumps({"tickers": [], "metadata_by_ticker": {}, "source_stage": "daily_scout"}))
    prior = tmp_path / "prior_scores.csv"
    _write_prior_context(prior, tickers=("GOOD",), quarter="2026Q1")
    live = tmp_path / "live_sec"
    (live / "companyfacts").mkdir(parents=True)
    (live / "companyfacts" / "CIK0000000001.json").write_text(json.dumps(_weak_companyfacts_payload()))
    (live / "companyfacts" / "CIK0000000002.json").write_text(json.dumps(_companyfacts_payload()))

    def fake_coverage(*, out_root, universe_csv, eligible_json, quarter, live_sec_root):
        manifest = out_root / f"sec_coverage_manifest_{quarter}.csv"
        rows = [
            {"ticker": "GOOD", "quarter": quarter, "coverage_status": "CACHED_READY", "missing_inputs": "", "notes": "", "earnings_8k_accession": "00000000-GOOD", "earnings_8k_filing_date": "2026-05-08", "earnings_8k_primary_document": "8k.htm", "earnings_exhibit_document": "ex99.htm", "periodic_accession": "00000000-GOODQ", "periodic_form": "10-Q", "periodic_filing_date": "2026-05-08", "periodic_primary_document": "10q.htm"},
            {"ticker": "NO8K", "quarter": quarter, "coverage_status": "CACHED_READY", "missing_inputs": "", "notes": "no_item_2_02_8k_using_periodic_only", "earnings_8k_accession": "", "earnings_8k_filing_date": "", "earnings_8k_primary_document": "", "earnings_exhibit_document": "", "periodic_accession": "00000000-NO8KQ", "periodic_form": "10-Q", "periodic_filing_date": "2026-05-08", "periodic_primary_document": "10q.htm"},
        ]
        with manifest.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return {"ticker_count": 2, "status_counts": {"CACHED_READY": 2}, "missing_input_counts": {}, "fetch_queue_count": 0, "blocked_tickers": [], "outputs": {"manifest_csv": str(manifest)}}

    def fake_prices(tickers, *, start, end, **kwargs):
        return [{"ticker": ticker, "date": "2026-05-11", "open": 8, "close": 8} for ticker in tickers]

    cfg = DailyRunConfig(
        as_of="2026-05-12",
        quarter="2026Q2",
        mode="broad-master-final",
        output_root=tmp_path / "run",
        master_universe_path=master,
        handoff_path=handoff,
        sec_live_root=live,
        skip_llm=True,
        prior_context_path=prior,
        min_broad_universe_count=2,
    )
    result = run_daily_fundamental(cfg, services=DailyRunServices(price_provider=fake_prices, run_coverage=fake_coverage))

    gate7 = next(g for g in result.gates if g.gate_number == 7)
    assert gate7.status == GateStatus.PASS
    assert gate7.summary["non_fetchable_llm_evidence_rejection_count"] == 1
    assert gate7.summary["llm_required_quarantine_count"] == 0
    with (cfg.output_root / "score_input_quarantine.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["ticker"] == "NO8K"
    assert rows[0]["score_input_quarantine_reason"] == "no_earnings_8k_or_press_release_found"


def test_orchestrator_attaches_prior_llm_extract_to_packets(tmp_path):
    cfg, services = _fake_orchestrator_fixture(tmp_path, skip_llm=True)
    _write_prior_context(cfg.prior_context_path, tickers=("T0", "T1", "T2", "T3", "T4"), quarter="2026Q1")
    rows = []
    with cfg.prior_context_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if row["ticker"] == "T1":
            row.update({"causal_change": "3", "narrative_delta_bucket": "constructive", "post_llm_candidate_flag": "1", "post_llm_high_priority_flag": "1", "post_llm_demote_flag": "0", "negative_revision_risk": "1", "operating_leverage_quality": "2", "durability": "2", "proof_alignment": "3"})
    with cfg.prior_context_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(dict.fromkeys(key for row in rows for key in row)))
        writer.writeheader()
        writer.writerows(rows)

    result = run_daily_fundamental(cfg, services=services)

    assert next(g for g in result.gates if g.gate_number == 8).status == GateStatus.SKIPPED
    packets = [json.loads(line) for line in (cfg.output_root / "lake" / "artifacts" / "2026Q2_llm_packets.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    t1 = next(packet for packet in packets if packet["ticker"] == "T1")
    assert t1["prior_llm_extract"]["causal_change"] == 3.0
    assert t1["prior_llm_extract"]["narrative_delta_bucket"] == "constructive"


def test_orchestrator_builds_prior_llm_recovery_packet_and_requires_completion(tmp_path):
    cfg, services = _fake_orchestrator_fixture(tmp_path)
    rows = []
    with cfg.prior_context_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if row["ticker"] == "T1":
            for field in orchestrator_module.PRIOR_LLM_FIELDS:
                row[field] = ""
    with cfg.prior_context_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(dict.fromkeys(key for row in rows for key in row)))
        writer.writeheader()
        writer.writerows(rows)

    def fake_llm(*, packets_path, output_root, config):
        packets = [json.loads(line) for line in packets_path.read_text().splitlines() if line.strip()]
        assert [packet["sample_id"] for packet in packets] == ["T1_2026Q2", "T2_2026Q2", "T1_2026Q1"]
        out = output_root / "post_llm_scores.csv"
        output_rows = [
            {
                "sample_id": packet["sample_id"],
                "ticker": packet["ticker"],
                "quarter": packet["quarter"],
                "post_llm_candidate_flag": "1",
                "post_llm_high_priority_flag": "1",
                "post_llm_demote_flag": "0",
                "causal_change": "3",
                "negative_revision_risk": "1",
                "narrative_delta_bucket": "constructive",
                "operating_leverage_quality": "1",
                "durability": "1",
                "proof_alignment": "2",
            }
            for packet in packets
        ]
        with out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(output_rows[0]))
            writer.writeheader()
            writer.writerows(output_rows)
        return out

    result = run_daily_fundamental(cfg, services=DailyRunServices(**{**services.__dict__, "run_llm": fake_llm}))

    assert result.summary["final"] is True
    gate7 = next(g for g in result.gates if g.gate_number == 7)
    assert gate7.summary["prior_llm_recovery_needed_count"] == 1
    assert gate7.summary["prior_llm_recovery_packet_count"] == 1
    gate8 = next(g for g in result.gates if g.gate_number == 8)
    assert gate8.summary["expected_count"] == 3


def test_partial_prior_llm_defaults_still_require_recovery():
    missing = orchestrator_module._prior_llm_missing_rows(
        rows=[{"ticker": "T1", "quarter": "2026Q2"}],
        prior_rows=[{"ticker": "T1", "quarter": "2026Q1", "post_llm_demote_severity": "none"}],
        expected_prior_quarter="2026Q1",
    )

    assert [row["ticker"] for row in missing] == ["T1"]


def test_readiness_uses_post_recovery_qoq_context_for_final_run(tmp_path):
    cfg, services = _fake_orchestrator_fixture(tmp_path)
    with cfg.prior_context_path.open(newline="", encoding="utf-8") as handle:
        rows = [row for row in csv.DictReader(handle) if row["ticker"] != "T1"]
    with cfg.prior_context_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    def fake_llm(*, packets_path, output_root, config):
        packets = [json.loads(line) for line in packets_path.read_text().splitlines() if line.strip()]
        assert [packet["sample_id"] for packet in packets] == ["T1_2026Q2", "T2_2026Q2", "T1_2026Q1"]
        out = output_root / "post_llm_scores.csv"
        output_rows = [
            {
                "sample_id": packet["sample_id"],
                "ticker": packet["ticker"],
                "quarter": packet["quarter"],
                "post_llm_candidate_flag": "1",
                "post_llm_high_priority_flag": "1",
                "post_llm_demote_flag": "0",
                "causal_change": "3",
                "negative_revision_risk": "1",
                "narrative_delta_bucket": "constructive",
                "operating_leverage_quality": "1",
                "durability": "1",
                "proof_alignment": "2",
            }
            for packet in packets
        ]
        with out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(output_rows[0]))
            writer.writeheader()
            writer.writerows(output_rows)
        return out

    result = run_daily_fundamental(cfg, services=DailyRunServices(**{**services.__dict__, "run_llm": fake_llm}))

    assert result.summary["final"] is True
    gate7 = next(g for g in result.gates if g.gate_number == 7)
    assert gate7.summary["llm_eligible_qoq_context_match_rows"] == 1
    readiness = json.loads((cfg.output_root / "publish_readiness_summary.json").read_text(encoding="utf-8"))
    assert readiness["status"] == "pass"
    assert readiness["prior_context_complete"] is True
    assert readiness["qoq_context_match_rows"] == 2
    assert readiness["llm_eligible_count"] == 2


def test_prior_llm_recovery_candidates_keep_current_identity_when_prior_context_has_blank_cik():
    candidates = orchestrator_module._prior_recovery_candidate_rows(
        current_rows=[
            {
                "ticker": "T1",
                "symbol": "T1",
                "cik": "123456",
                "company_title": "T1 Inc",
                "title": "T1 Inc",
            }
        ],
        prior_rows=[
            {
                "ticker": "T1",
                "quarter": "2026Q1",
                "cik": "",
                "company_title": "",
                "entry_open": "10",
            }
        ],
        expected_prior_quarter="2026Q1",
    )

    assert candidates == [
        {
            "ticker": "T1",
            "quarter": "2026Q1",
            "cik": "123456",
            "company_title": "T1 Inc",
            "entry_open": "10",
            "symbol": "T1",
            "title": "T1 Inc",
            "llm_eligible": 1,
            "llm_recovery_role": "prior_quarter_required_for_final_scoring",
        }
    ]


def test_prior_recovery_context_builds_prior_price_and_pre_llm_score(tmp_path):
    live = tmp_path / "live_sec"
    (live / "companyfacts").mkdir(parents=True)
    (live / "companyfacts" / "CIK0000123456.json").write_text(json.dumps(_companyfacts_payload()))
    cfg = DailyRunConfig(as_of="2026-05-15", quarter="2026Q2", mode="broad-master-final", output_root=tmp_path / "run")

    def fake_prices(tickers, *, start, end, **kwargs):
        assert tickers == ["T1"]
        return [{"ticker": "T1", "date": "2026-02-10", "open": 10, "close": 10}]

    rows, quarantine, summary = orchestrator_module._build_prior_recovery_context_rows(
        candidates=[{"ticker": "T1", "quarter": "2026Q1", "cik": "123456", "company_title": "T1 Inc"}],
        coverage_rows=[
            {
                "ticker": "T1",
                "quarter": "2026Q1",
                "earnings_8k_filing_date": "2026-02-06",
                "periodic_filing_date": "2026-02-06",
                "periodic_accession": "00000000-T1Q",
                "periodic_primary_document": "10q.htm",
            }
        ],
        expected_prior_quarter="2026Q1",
        config=cfg,
        live_root=live,
        price_provider=fake_prices,
    )

    assert quarantine == []
    assert summary["prior_recovery_context_ready_count"] == 1
    assert rows[0]["entry_open"] == 10
    assert rows[0]["pre_llm_fundamental_score"] != ""


def test_orchestrator_broad_final_hard_stops_when_required_llm_evidence_stays_quarantined(tmp_path):
    master = tmp_path / "master.json"
    master.write_text(json.dumps({"items": [{"symbol": "LOW", "cik": "1", "company_title": "Low Price Inc"}]}))
    handoff = tmp_path / "handoff.json"
    handoff.write_text(json.dumps({"tickers": [], "metadata_by_ticker": {}, "source_stage": "daily_scout"}))
    prior = tmp_path / "prior_scores.csv"
    _write_prior_context(prior, tickers=("LOW",))
    live = tmp_path / "live_sec"
    (live / "companyfacts").mkdir(parents=True)
    (live / "companyfacts" / "CIK0000000001.json").write_text(json.dumps(_companyfacts_payload()))

    def fake_coverage(*, out_root, universe_csv, eligible_json, quarter, live_sec_root):
        manifest = out_root / f"sec_coverage_manifest_{quarter}.csv"
        rows = [
            {
                "ticker": "LOW",
                "quarter": quarter,
                "coverage_status": "NEEDS_FETCH",
                "missing_inputs": "earnings_exhibit_document",
                "earnings_8k_accession": "00000000-LOW",
                "earnings_8k_filing_date": "2026-05-08",
                "earnings_8k_primary_document": "8k.htm",
                "earnings_exhibit_document": "",
                "periodic_accession": "00000000-LOWQ",
                "periodic_form": "10-Q",
                "periodic_filing_date": "2026-05-08",
                "periodic_primary_document": "10q.htm",
            }
        ]
        with manifest.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return {
            "ticker_count": 1,
            "status_counts": {"NEEDS_FETCH": 1},
            "missing_input_counts": {},
            "fetch_queue_count": 0,
            "blocked_tickers": [],
            "outputs": {"manifest_csv": str(manifest)},
        }

    cfg = DailyRunConfig(
        as_of="2026-05-12",
        quarter="2026Q2",
        mode="broad-master-final",
        output_root=tmp_path / "run",
        master_universe_path=master,
        handoff_path=handoff,
        sec_live_root=live,
        skip_fetch=True,
        skip_llm=False,
        prior_context_path=prior,
        min_broad_universe_count=1,
    )
    services = DailyRunServices(
        price_provider=lambda tickers, *, start, end: [{"ticker": "LOW", "date": "2026-05-11", "open": 8, "close": 8}],
        run_coverage=fake_coverage,
    )

    result = run_daily_fundamental(cfg, services=services)

    assert result.summary["final"] is False
    gate7 = next(g for g in result.gates if g.gate_number == 7)
    assert gate7.status == GateStatus.HARD_STOP
    assert gate7.summary["reason"] == "llm_required_rows_still_missing_evidence"
    assert gate7.summary["llm_required_quarantine_count"] == 1
    assert not (cfg.output_root / "fundamental_final_scores_2026-05-12.csv").exists()


def test_master_additions_ledger_only_persists_scored_new_dealflow(tmp_path):
    master = tmp_path / "master.json"
    master.write_text(
        json.dumps(
            {
                "items": [
                    {"symbol": "M0", "cik": "1", "company_title": "Master Zero Inc"},
                    {"symbol": "M1", "cik": "2", "company_title": "Master One Inc"},
                ]
            }
        )
    )
    handoff = tmp_path / "handoff.json"
    handoff.write_text(json.dumps({"tickers": ["NEW"], "metadata_by_ticker": {}, "source_stage": "daily_scout"}))
    prior = tmp_path / "prior_scores.csv"
    _write_prior_context(prior, tickers=("M0", "M1"))
    ledger = tmp_path / "additions.jsonl"
    live = tmp_path / "live_sec"
    (live / "companyfacts").mkdir(parents=True)
    for cik in ["1", "2"]:
        (live / "companyfacts" / f"CIK{cik.zfill(10)}.json").write_text(json.dumps(_companyfacts_payload()))

    def resolver(ticker):
        return orchestrator_module.IdentityResolution("NEW", "NEW", "NEW", "", "3", "New Inc", "resolved_from_sec_ticker_map", "")

    def fake_coverage(*, out_root, universe_csv, eligible_json, quarter, live_sec_root):
        manifest = out_root / f"sec_coverage_manifest_{quarter}.csv"
        rows = []
        for ticker in ["M0", "M1", "NEW"]:
            rows.append(
                {
                    "ticker": ticker,
                    "quarter": quarter,
                    "coverage_status": "CACHED_READY",
                    "missing_inputs": "",
                    "earnings_8k_accession": f"00000000-{ticker}",
                    "earnings_8k_filing_date": "2026-05-08",
                    "earnings_8k_primary_document": "8k.htm",
                    "earnings_exhibit_document": "ex99.htm",
                    "periodic_accession": f"00000000-{ticker}Q",
                    "periodic_form": "10-Q",
                    "periodic_filing_date": "2026-05-08",
                    "periodic_primary_document": "10q.htm",
                }
            )
        with manifest.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        for ticker in ["M0", "M1"]:
            for accession, doc in [(f"00000000-{ticker}", "8k.htm"), (f"00000000-{ticker}", "ex99.htm"), (f"00000000-{ticker}Q", "10q.htm")]:
                path = live_sec_root / "documents" / f"{ticker}_{accession.replace('-', '')}_{doc}"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("<html>Management raised guidance and margins improved.</html>")
        return {
            "ticker_count": 3,
            "status_counts": {"CACHED_READY": 3},
            "missing_input_counts": {},
            "fetch_queue_count": 0,
            "blocked_tickers": [],
            "outputs": {"manifest_csv": str(manifest)},
        }

    def fake_prices(tickers, *, start, end):
        return [{"ticker": ticker, "date": "2026-05-11", "open": 30, "close": 30} for ticker in tickers]

    def fake_llm(*, packets_path, output_root, config):
        packets = [json.loads(line) for line in packets_path.read_text().splitlines() if line.strip()]
        out = output_root / "post_llm_scores.csv"
        fieldnames = [
            "sample_id",
            "ticker",
            "quarter",
            "post_llm_candidate_flag",
            "post_llm_high_priority_flag",
            "post_llm_demote_flag",
            "causal_change",
            "negative_revision_risk",
            "narrative_delta_bucket",
            "operating_leverage_quality",
            "durability",
            "proof_alignment",
        ]
        rows = [
            {
                "sample_id": packet["sample_id"],
                "ticker": packet["ticker"],
                "quarter": packet["quarter"],
                "post_llm_candidate_flag": "1",
                "post_llm_high_priority_flag": "1",
                "post_llm_demote_flag": "0",
                "causal_change": "3",
                "negative_revision_risk": "1",
                "narrative_delta_bucket": "constructive",
                "operating_leverage_quality": "1",
                "durability": "1",
                "proof_alignment": "2",
            }
            for packet in packets
        ]
        with out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return out

    def fake_publish(**kwargs):
        return GateResult(10, "Top10 + Plus5 + shadow refill publish", GateStatus.PASS, {"input_rows": 2}, {})

    cfg = DailyRunConfig(
        as_of="2026-05-12",
        quarter="2026Q2",
        mode="broad-master-final",
        output_root=tmp_path / "run",
        master_universe_path=master,
        handoff_path=handoff,
        sec_live_root=live,
        skip_llm=False,
        prior_context_path=prior,
        min_broad_universe_count=3,
        master_additions_ledger_path=ledger,
    )

    result = run_daily_fundamental(
        cfg,
        services=DailyRunServices(
            price_provider=fake_prices,
            run_coverage=fake_coverage,
            resolve_identity=resolver,
            run_llm=fake_llm,
            publish=fake_publish,
        ),
    )

    assert result.summary["final"] is True
    assert not ledger.exists()


def test_orchestrator_emits_complete_panel_after_publish_when_requested(tmp_path):
    cfg, services = _fake_orchestrator_fixture(tmp_path)
    panel_root = tmp_path / "panel"
    cfg = DailyRunConfig(**{**cfg.__dict__, "emit_complete_panel": True, "complete_panel_output_root": panel_root})
    result = run_daily_fundamental(cfg, services=services)
    assert result.summary["final"] is True
    assert result.gates[-1].gate_number == 11
    assert result.gates[-1].status == GateStatus.PASS
    assert "complete_panel_csv" in result.artifacts
    assert "complete_panel_manifest" in result.artifacts
    assert "complete_panel_columns" in result.artifacts
    assert "complete_panel_validation" in result.artifacts
    assert panel_root.exists()


def test_orchestrator_final_mode_hard_stops_without_prior_qoq_context(tmp_path):
    cfg, services = _fake_orchestrator_fixture(tmp_path)
    cfg = DailyRunConfig(**{**cfg.__dict__, "prior_context_path": None})
    result = run_daily_fundamental(cfg, services=services)
    assert result.summary["final"] is False
    assert result.gates[-1].gate_number == 9
    assert result.gates[-1].status == GateStatus.HARD_STOP
    assert result.gates[-1].summary["reason"] == "missing_prior_final_scores"
    assert not (cfg.output_root / "high_conviction_top15.csv").exists()


def test_orchestrator_uses_prior_qoq_before_llm_eligibility_for_rm_only_candidate(tmp_path):
    master = tmp_path / "master.json"
    master.write_text(
        json.dumps(
            {
                "items": [
                    {"symbol": "RMX", "cik": "1", "company_title": "RMX Inc"},
                    {"symbol": "SAFE", "cik": "2", "company_title": "Safe Inc"},
                ]
            }
        )
    )
    prior = tmp_path / "prior_scores.csv"
    rows = [
        {"ticker": "RMX", "quarter": "2026Q1", "entry_open": "10", "entry_qoq_pct": "0", "pre_llm_fundamental_score": "-3", "causal_change": "2", "negative_revision_risk": "1", "narrative_delta_bucket": "constructive", "operating_leverage_quality": "1", "durability": "1", "proof_alignment": "2", "post_llm_candidate_flag": "1", "post_llm_high_priority_flag": "0", "post_llm_demote_flag": "0"},
        {"ticker": "SAFE", "quarter": "2026Q1", "entry_open": "30", "entry_qoq_pct": "0", "pre_llm_fundamental_score": "8", "causal_change": "2", "negative_revision_risk": "1", "narrative_delta_bucket": "constructive", "operating_leverage_quality": "1", "durability": "1", "proof_alignment": "2", "post_llm_candidate_flag": "1", "post_llm_high_priority_flag": "0", "post_llm_demote_flag": "0"},
    ]
    with prior.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    live = tmp_path / "live_sec"; (live / "companyfacts").mkdir(parents=True)
    handoff = tmp_path / "handoff.json"; handoff.write_text(json.dumps({"tickers": [], "metadata_by_ticker": {}, "source_stage": "daily_scout"}))
    (live / "companyfacts" / "CIK0000000001.json").write_text(json.dumps(_weak_companyfacts_payload()))
    (live / "companyfacts" / "CIK0000000002.json").write_text(json.dumps(_companyfacts_payload()))

    def fake_coverage(*, out_root, universe_csv, eligible_json, quarter, live_sec_root):
        manifest = out_root / f"sec_coverage_manifest_{quarter}.csv"
        coverage_rows = []
        for ticker in ["RMX", "SAFE"]:
            coverage_rows.append({"ticker": ticker, "quarter": quarter, "coverage_status": "CACHED_READY", "missing_inputs": "", "earnings_8k_accession": f"00000000-{ticker}", "earnings_8k_filing_date": "2026-05-08", "earnings_8k_primary_document": "8k.htm", "earnings_exhibit_document": "ex99.htm", "periodic_accession": f"00000000-{ticker}Q", "periodic_form": "10-Q", "periodic_filing_date": "2026-05-08", "periodic_primary_document": "10q.htm"})
        with manifest.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(coverage_rows[0])); writer.writeheader(); writer.writerows(coverage_rows)
        for ticker in ["RMX", "SAFE"]:
            for accession, doc in [(f"00000000-{ticker}", "8k.htm"), (f"00000000-{ticker}", "ex99.htm"), (f"00000000-{ticker}Q", "10q.htm")]:
                path = live / "documents" / f"{ticker}_{accession.replace('-', '')}_{doc}"
                path.parent.mkdir(parents=True, exist_ok=True); path.write_text("<html>Management described repricing recovery and operating leverage.</html>")
        return {"ticker_count": 2, "status_counts": {"CACHED_READY": 2}, "missing_input_counts": {}, "fetch_queue_count": 0, "blocked_tickers": [], "outputs": {"manifest_csv": str(manifest)}}

    def fake_prices(tickers, *, start, end):
        opens = {"RMX": 20, "SAFE": 30}
        return [{"ticker": t, "date": "2026-05-11", "open": opens[t], "close": opens[t]} for t in tickers]

    def fake_llm(*, packets_path, output_root, config):
        packets = [json.loads(line) for line in packets_path.read_text().splitlines() if line.strip()]
        assert [p["ticker"] for p in packets] == ["RMX"]
        out = output_root / "post_llm_scores.csv"
        rows = [{"sample_id": "RMX_2026Q2", "ticker": "RMX", "quarter": "2026Q2", "post_llm_candidate_flag": "1", "post_llm_high_priority_flag": "1", "post_llm_demote_flag": "0", "causal_change": "3", "negative_revision_risk": "1", "narrative_delta_bucket": "constructive", "operating_leverage_quality": "1", "durability": "1", "proof_alignment": "2"}]
        with out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
        return out

    def fake_publish(**kwargs):
        return GateResult(10, "Top10 + Plus5 + shadow refill publish", GateStatus.PASS, {"input_rows": 2}, {})

    cfg = DailyRunConfig(as_of="2026-05-12", quarter="2026Q2", mode="broad-master-final", output_root=tmp_path / "run", master_universe_path=master, handoff_path=handoff, sec_live_root=live, skip_llm=False, prior_context_path=prior, min_broad_universe_count=2)
    result = run_daily_fundamental(cfg, services=DailyRunServices(price_provider=fake_prices, run_coverage=fake_coverage, run_llm=fake_llm, publish=fake_publish))

    assert result.summary["final"] is True
    with (cfg.output_root / "llm_eligibility.csv").open(newline="", encoding="utf-8") as handle:
        eligible = list(csv.DictReader(handle))
    assert [row["ticker"] for row in eligible] == ["RMX"]
    assert eligible[0]["repricing_momentum_extension"]


def test_orchestrator_final_mode_hard_stops_on_wrong_prior_quarter(tmp_path):
    cfg, services = _fake_orchestrator_fixture(tmp_path)
    wrong_prior = tmp_path / "wrong_prior.csv"; _write_prior_context(wrong_prior, quarter="2025Q4")
    cfg = DailyRunConfig(**{**cfg.__dict__, "prior_context_path": wrong_prior})
    result = run_daily_fundamental(cfg, services=services)
    assert result.summary["final"] is False
    assert result.gates[-1].gate_number == 9
    assert result.gates[-1].status == GateStatus.HARD_STOP
    assert result.gates[-1].summary["reason"] == "no_rows_for_expected_prior_quarter"


def test_orchestrator_broad_final_hard_stops_on_date_quarter_mismatch(tmp_path):
    cfg, services = _fake_orchestrator_fixture(tmp_path)
    cfg = DailyRunConfig(**{**cfg.__dict__, "quarter": "2026Q3"})
    result = run_daily_fundamental(cfg, services=services)
    assert result.summary["final"] is False
    assert result.gates[-1].gate_number == 1
    assert result.gates[-1].status == GateStatus.HARD_STOP
    assert result.gates[-1].summary["reason"] == "date_quarter_mismatch"


def test_orchestrator_final_mode_hard_stops_on_duplicate_prior_rows(tmp_path):
    cfg, services = _fake_orchestrator_fixture(tmp_path)
    dup_prior = tmp_path / "dup_prior.csv"
    rows = [
        {"ticker": "T1", "quarter": "2026Q1", "entry_open": "10", "pre_llm_fundamental_score": "1"},
        {"ticker": "T1", "quarter": "2026Q1", "entry_open": "11", "pre_llm_fundamental_score": "2"},
    ]
    with dup_prior.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    cfg = DailyRunConfig(**{**cfg.__dict__, "prior_context_path": dup_prior})
    result = run_daily_fundamental(cfg, services=services)
    assert result.summary["final"] is False
    assert result.gates[-1].gate_number == 9
    assert result.gates[-1].status == GateStatus.HARD_STOP
    assert result.gates[-1].summary["reason"] == "duplicate_prior_ticker_quarter_rows"


def test_orchestrator_diagnostic_mode_with_skip_llm_false_does_not_require_post_llm_path(tmp_path):
    def fail_if_called(**kwargs):
        raise AssertionError("diagnostic mode must not call LLM")
    cfg, services = _fake_orchestrator_fixture(tmp_path, mode="diagnostic-only", skip_llm=False, fake_llm=fail_if_called)
    result = run_daily_fundamental(cfg, services=services)
    assert result.summary["final"] is False
    assert result.summary["stopped"] == "publish_skipped"
    assert any(g.gate_number == 8 and g.status == GateStatus.SKIPPED for g in result.gates)
    assert not (cfg.output_root / "high_conviction_top15.csv").exists()


def test_orchestrator_recovers_empty_llm_packets_before_hard_stop(tmp_path, monkeypatch):
    cfg, services = _fake_orchestrator_fixture(tmp_path)
    calls = []

    def staged_loader(manifest_csv, live_sec_root):
        calls.append(1)
        text = "" if len(calls) == 1 else "Management raised guidance and margins improved."
        docs = []
        for ticker in ["T1", "T2"]:
            docs.extend(
                [
                    {
                        "ticker": ticker,
                        "quarter": "2026Q2",
                        "accession": f"00000000-{ticker}",
                        "document_type": "primary_8k",
                        "document_name": "8k.htm",
                        "raw_text": text,
                        "clean_text": text,
                    },
                    {
                        "ticker": ticker,
                        "quarter": "2026Q2",
                        "accession": f"00000000-{ticker}",
                        "document_type": "earnings_exhibit",
                        "document_name": "ex99.htm",
                        "raw_text": text,
                        "clean_text": text,
                    },
                ]
            )
        return docs

    monkeypatch.setattr(orchestrator_module, "load_raw_documents_from_coverage", staged_loader)

    result = run_daily_fundamental(cfg, services=services)

    assert len(calls) == 2
    assert result.summary["final"] is True
    gate8 = next(g for g in result.gates if g.gate_number == 8)
    assert gate8.status == GateStatus.PASS
    assert gate8.summary["empty_evidence_recovery_attempted"] is True


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
