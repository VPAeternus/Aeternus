# PIT Acceptance Review Bundle

Purpose: make GPT Pro review possible from GitHub without access to local `/Users/...` run folders.

Accepted code commit: `364b91933ff6d6cccc6afa6c64609a5f0cf5a322`

What is included:
- `acceptance_summary.json`: compact pass/fail summary for both full runs.
- `2022Q1_gate_summary.json`, `2026Q1_gate_summary.json`: Gate 1-11 statuses and summaries.
- `*_publish_readiness_summary.json`: publish readiness evidence.
- `*_complete_panel_validation.json`: complete-panel validation evidence.
- `complete_panel_provenance_audit.csv`: proof that complete panel now retains PIT period fields and field-level financial provenance.
- `reconciliation_audit_summary.csv`: blocking/warning row counts.
- `artifact_hashes.csv`: SHA-256 hashes for large local outputs, without committing large CSVs.
- `commands.md`: exact commands used.

Result:
- 2022Q1: all gates pass, Gate 8 pass, Gate 10 pass, Gate 11 pass, publish readiness pass.
- 2026Q1: all gates pass, Gate 8 pass, Gate 10 pass, Gate 11 pass, publish readiness pass.
- Blocking errors: 0 for both.
- Warnings: 0 for both.
- Complete panel schema: `fundamental_complete_panel_v2`.
- Complete panel now retains `target_period_end`, `fiscal_period_*`, row acceptance flags, and per-field financial provenance columns.
- Final-score to complete-panel key/value mismatch count for audited PIT fields: 0 for both quarters.

Important caveat:
- Full CSVs remain local because they are large run artifacts. Use `artifact_hashes.csv` to verify uploaded copies byte-for-byte.
