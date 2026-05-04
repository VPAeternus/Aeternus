from tradingagents.graph.audit import RatingAuditLog
from tradingagents.graph.track_record import TrackRecord
import uuid
import json
import shutil
from pathlib import Path

# Setup temporary test environment
test_dir = Path("test_eval_results")
if test_dir.exists():
    shutil.rmtree(test_dir)
test_dir.mkdir()

# Mock Rating
rating_id = str(uuid.uuid4())
mock_rating = {
    "rating_id": rating_id,
    "ticker": "TSLA",
    "rating": "Buy",
    "aeternus_score": 85.0
}

print(f"Testing with Rating ID: {rating_id}")

try:
    # 1. Test Audit Log
    audit = RatingAuditLog(path=f"{test_dir}/audit_log.json")
    
    # Log Creation
    print("Logging creation event...")
    audit.log_event("RATING_CREATED", rating_id, mock_rating)
    
    # Log Update
    print("Logging update event...")
    audit.log_event("RATING_UPDATED", rating_id, {"rating": "Strong Buy", "score": 90.0})
    
    # Verify History
    history = audit.get_rating_history(rating_id)
    print(f"Audit History Length: {len(history)}")
    if len(history) != 2:
        raise Exception("Audit history length mismatch!")

    # 2. Test Track Record
    tr = TrackRecord(path=f"{test_dir}/track_record.json")
    print("Appending to Track Record...")
    tr.append(mock_rating)
    
    stats = tr.get_stats()
    print(f"Track Record Stats: {json.dumps(stats)}")
    
    if stats["count"] != 1:
         raise Exception("Track Record count mismatch!")

    print("✅ Trust & Verification Tests Passed!")

except Exception as e:
    print(f"❌ Test Failed: {e}")
    exit(1)
finally:
    # Cleanup
    if test_dir.exists():
        shutil.rmtree(test_dir)
