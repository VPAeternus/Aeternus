"""Export operator gateway OpenAPI schema to a JSON file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradingagents.operator_gateway.app import create_app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export operator gateway OpenAPI schema.")
    parser.add_argument(
        "--output",
        default="docs/operator_gateway_openapi.json",
        help="Output file path (default: docs/operator_gateway_openapi.json)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app = create_app()
    schema = app.openapi()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(schema, indent=2, sort_keys=True))
    print(f"Wrote OpenAPI schema to {output_path}")


if __name__ == "__main__":
    main()
