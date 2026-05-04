from typer.testing import CliRunner
from cli.main import app
from tradingagents.graph.track_record import TrackRecord
from tradingagents.graph.audit import RatingAuditLog
import uuid
import sys
import shutil
from pathlib import Path

runner = CliRunner()

def run_test():
    print("Setting up test data...")
    tr = TrackRecord()
    rating_id = str(uuid.uuid4())
    rating = {
        "rating_id": rating_id,
        "ticker": "MANUAL_TEST",
        "aeternus_score": 99.9,
        "rating": "Strong Buy",
        "status": "OPEN",
        "date": "2025-01-01",
        "price_at_rating": 100.0,
        "price_target": 120.0
    }
    tr.append(rating)
    
    audit = RatingAuditLog()
    audit.log_event("RATING_CREATED", rating_id, rating)
    
    print("\n--- Testing 'track-record' ---")
    result = runner.invoke(app, ["track-record"])
    if result.exit_code != 0:
        print(f"FAILED: Exit code {result.exit_code}")
        print(result.stdout)
        sys.exit(1)
    if "MANUAL_TEST" not in result.stdout:
        print("FAILED: Output missing ticker")
        print(result.stdout)
        sys.exit(1)
    print("PASSED")
    
    print("\n--- Testing 'performance' ---")
    result = runner.invoke(app, ["performance"])
    if result.exit_code != 0:
        print(f"FAILED: Exit code {result.exit_code}")
        print(result.stdout)
        sys.exit(1)
    if "Performance Metrics" not in result.stdout:
        print("FAILED: Output missing title")
        print(result.stdout)
        sys.exit(1)
    print("PASSED")

    print(f"\n--- Testing 'rating-history {rating_id}' ---")
    result = runner.invoke(app, ["rating-history", rating_id])
    if result.exit_code != 0:
        print(f"FAILED: Exit code {result.exit_code}")
        print(result.stdout)
        sys.exit(1)
    if "Audit History" not in result.stdout:
         print("FAILED: Output missing title")
         print(result.stdout)
         sys.exit(1)
    print("PASSED")

    print("\n✅ All CLI tests passed!")

if __name__ == "__main__":
    run_test()
