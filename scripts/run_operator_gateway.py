"""Run the Aeternus Operator Gateway API server."""

from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Aeternus Operator Gateway (FastAPI).")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable autoreload for local development")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        import uvicorn
    except Exception as exc:  # pragma: no cover - startup guard
        raise SystemExit(
            "uvicorn is required to run operator gateway. Install with: pip install uvicorn"
        ) from exc

    project_root = Path(__file__).resolve().parents[1]
    uvicorn.run(
        "tradingagents.operator_gateway.app:app",
        host=args.host,
        port=args.port,
        reload=bool(args.reload),
        app_dir=str(project_root),
        reload_dirs=[str(project_root)],
    )


if __name__ == "__main__":
    main()
