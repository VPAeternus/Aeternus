from __future__ import annotations

import argparse
import subprocess
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "Growth" / "earnings_8k_sec_parser"


def quarter_start(quarter: str) -> date:
    year = int(quarter[:4])
    q = int(quarter[-1])
    return date(year, (q - 1) * 3 + 1, 1)


def path(name: str, quarter: str) -> Path:
    return OUT / name.format(q=quarter)


def run(cmd: list[str], *, dry_run: bool) -> None:
    printable = " ".join(cmd)
    if dry_run:
        print(printable)
        return
    print(printable, flush=True)
    subprocess.run(cmd, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run repeatable quarterly no-LLM earnings universe/scoring pipeline")
    parser.add_argument("--quarter", required=True, help="Quarter like 2024Q3")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running")
    parser.add_argument("--start-at", choices=[
        "viability",
        "metadata",
        "doc-quality",
        "coverage",
        "repair",
        "extract",
        "stage-csv",
        "fundamental",
    ], default="viability")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    q = args.quarter
    asof = quarter_start(q).isoformat()
    py = str(ROOT / ".venv" / "bin" / "python")
    stages = [
        ("viability", [
            py, "Growth/akg_quarter_viability_tester.py",
            "--quarter", q,
            "--output", str(path("akg_quarter_viability_{q}.csv", q)),
        ]),
        ("metadata", [
            py, "Growth/sec_filing_metadata_pass.py",
            "--quarter", q,
            "--input", str(path("akg_quarter_viability_included_{q}.csv", q)),
            "--output", str(path("sec_filing_metadata_{q}.csv", q)),
        ]),
        ("doc-quality", [
            py, "Growth/sec_document_quality_gate.py",
            "--input", str(path("sec_filing_metadata_passed_{q}.csv", q)),
            "--output", str(path("sec_document_quality_{q}.csv", q)),
        ]),
        ("coverage", [
            py, "Growth/filing_coverage_audit.py",
            "--input", str(path("final_pre_extraction_universe_{q}.csv", q)),
            "--metadata", str(path("sec_filing_metadata_{q}.csv", q)),
            "--repair-report", str(path("missing_earnings_docs_fetch_report_{q}.csv", q)),
            "--output", str(path("filing_coverage_audit_{q}.csv", q)),
            "--fetch-plan", str(path("missing_doc_fetch_plan_{q}.csv", q)),
        ]),
        ("repair", [
            py, "Growth/fetch_missing_earnings_docs.py",
            "--audit", str(path("filing_coverage_audit_{q}.csv", q)),
            "--output", str(path("missing_earnings_docs_fetch_report_{q}.csv", q)),
            "--quarter", q,
        ]),
        ("extract", [
            py, "Growth/local_earnings_extraction.py",
            "--audit", str(path("filing_coverage_audit_{q}.csv", q)),
            "--xbrl", str(path("xbrl_universal_features_through_ocf_{q}_final_active.csv", q)),
            "--manifest", str(path("local_earnings_extraction_manifest_{q}_secparser.csv", q)),
            "--output-root", str(path("local_extractions_{q}_secparser", q)),
        ]),
        ("fundamental", [
            py, "Growth/build_pre_llm_fundamental_score.py",
            "--xbrl", str(path("xbrl_universal_features_through_ocf_{q}_final_active.csv", q)),
            "--returns", str(path("no_llm_earnings_score_{q}.csv", q)),
            "--events", str(path("filing_coverage_audit_{q}.csv", q)),
            "--output", str(path("pre_llm_fundamental_score_{q}.csv", q)),
        ]),
    ]
    start_index = next(i for i, (name, _) in enumerate(stages) if name == args.start_at)
    print(f"# quarter={q} asof={asof}")
    print("# NOTE: universe construction CSV steps still require explicit generated intermediate files:")
    print(f"# - akg_quarter_viability_included_{q}.csv")
    print(f"# - sec_filing_metadata_passed_{q}.csv")
    print(f"# - final_pre_extraction_universe_{q}.csv")
    print(f"# - xbrl_universal_features_through_ocf_{q}_final_active.csv")
    print(f"# - no_llm_earnings_score_{q}.csv")
    for _, cmd in stages[start_index:]:
        run(cmd, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
