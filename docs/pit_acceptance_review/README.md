# PIT Acceptance Review Bundle

Purpose: make GPT Pro review possible from GitHub without access to local `/Users/...` run folders.

Accepted code commit: `5a32fe5d1d87e3922c2da80539e45427de01a57a`

What is included:
- `acceptance_summary.json`: compact pass/fail summary for both full runs.
- `2022Q1_gate_summary.json`, `2026Q1_gate_summary.json`: Gate 1-11 statuses and summaries.
- `*_publish_readiness_summary.json`: publish readiness evidence.
- `*_complete_panel_validation.json`: complete-panel validation evidence.
- `reconciliation_audit_summary.csv`: blocking/warning row counts.
- `artifact_hashes.csv`: SHA-256 hashes for large local outputs, without committing the large CSVs.
- `commands.md`: exact commands used.

Result:
- 2022Q1: all gates pass, Gate 8 pass, Gate 10 pass, publish readiness pass.
- 2026Q1: all gates pass, Gate 8 pass, Gate 10 pass, publish readiness pass.
- Blocking errors: 0 for both.
- Warnings: 0 for both.
- Selection future-field leakage: none found in local acceptance audit.

Important caveat:
- These are portable summaries and hashes, not the full local run folders.
- Full CSVs remain local because they are large run artifacts.
