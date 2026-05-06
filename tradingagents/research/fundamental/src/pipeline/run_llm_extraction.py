from __future__ import annotations

import argparse
from pathlib import Path

from src.features.llm_extraction import read_packets, run_llm_batches, write_consolidated_csv
from src.storage import add_run_lineage, make_pipeline_run_id, read_rows, source_file_hash, write_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run post-LLM causal/narrative extraction with resume and validation")
    parser.add_argument("--packets", type=Path, required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/live/llm_batches"))
    parser.add_argument("--output-csv", type=Path, default=Path("outputs/live/post_llm_scores.csv"))
    parser.add_argument("--lake-root", type=Path, default=Path("outputs/live/parquet"))
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--pipeline-run-id", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    packets = read_packets(args.packets) if args.packets.suffix == ".jsonl" else read_rows(args.packets)
    rows = run_llm_batches(
        packets,
        output_dir=args.output_dir,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        batch_size=args.batch_size,
        resume=not args.no_resume,
    )
    write_consolidated_csv(args.output_dir, args.output_csv)
    run_id = args.pipeline_run_id or make_pipeline_run_id("llm")
    lineage = add_run_lineage(rows, pipeline_run_id=run_id, as_of_date=args.as_of, source_hash=source_file_hash(args.packets))
    write_table(args.lake_root, "post_llm_scores", lineage)
    print(f"wrote post_llm_scores rows={len(lineage)} run_id={run_id}")


if __name__ == "__main__":
    main()
