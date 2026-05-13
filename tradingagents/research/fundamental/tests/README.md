# Fundamental Test Map

Package-local tests live here. Root-level tests remain for repo-wide pytest compatibility and CLI integration.

Source-of-truth root tests for this framework:

- `/tests/test_cli_fundamental_run_today.py`
- `/tests/test_cli_fundamental_top10.py`
- `/tests/test_cli_fundamental_top15_refill_shadow.py`
- `/tests/test_fundamental_daily_coverage_gate.py`
- `/tests/test_fundamental_daily_eligibility_gate.py`
- `/tests/test_fundamental_daily_finalize_gate.py`
- `/tests/test_fundamental_daily_llm_validation.py`
- `/tests/test_fundamental_daily_orchestrator_contract.py`
- `/tests/test_fundamental_daily_run_models.py`
- `/tests/test_fundamental_daily_scoring_inputs.py`
- `/tests/test_fundamental_daily_universe_gate.py`
- `/tests/test_fundamental_high_conviction_top10.py`
- `/tests/test_high_conviction_top15_exception_sleeve.py`
- `/tests/test_llm_packets.py`
- `/tests/test_sec_coverage_manifest_parser.py`

Do not fork or copy these tests into multiple places. Move them only in a dedicated pytest/CI migration.
