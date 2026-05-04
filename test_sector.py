from tradingagents.graph.sector_context import SectorContext
import json
import sys

try:
    ctx = SectorContext()
    print("Fetching context for TSLA...")
    data = ctx.get_context("TSLA")
    print(json.dumps(data, indent=2))
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
