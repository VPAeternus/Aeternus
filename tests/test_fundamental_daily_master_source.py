import json

from tradingagents.research.fundamental.src.daily_run.master_source import load_master_universe_rows, materialize_master_universe


def test_master_source_merges_start_rows_and_additions(tmp_path):
    start = tmp_path / "start.json"
    start.write_text(json.dumps({"items": [{"ticker": "aaa", "cik": "1", "company_title": "AAA Start"}, {"ticker": "bbb", "cik": "2", "company_title": "BBB Start"}]}), encoding="utf-8")
    additions = tmp_path / "additions.jsonl"
    additions.write_text("\n".join([
        json.dumps({"ticker": "bbb", "cik": "22", "company_title": "BBB Add"}),
        json.dumps({"ticker": "ccc", "cik": "3", "company_title": "CCC Add"}),
    ]) + "\n", encoding="utf-8")

    rows = load_master_universe_rows(start_path=start, additions_path=additions)

    assert [row["ticker"] for row in rows] == ["AAA", "BBB", "CCC"]
    assert rows[1]["cik"] == "2"
    assert rows[1]["company_title"] == "BBB Start"
    assert rows[2]["cik"] == "3"


def test_master_source_last_wins_for_duplicate_additions(tmp_path):
    start = tmp_path / "start.json"
    start.write_text(json.dumps({"items": [{"ticker": "aaa", "cik": "1", "company_title": "AAA Start"}]}), encoding="utf-8")
    additions = tmp_path / "additions.jsonl"
    additions.write_text("\n".join([
        json.dumps({"ticker": "bbb", "cik": "2", "company_title": "BBB First"}),
        json.dumps({"ticker": "bbb", "cik": "22", "company_title": "BBB Last"}),
    ]) + "\n", encoding="utf-8")

    rows = load_master_universe_rows(start_path=start, additions_path=additions)

    assert [row["ticker"] for row in rows] == ["AAA", "BBB"]
    assert rows[1]["cik"] == "22"
    assert rows[1]["company_title"] == "BBB Last"


def test_master_source_keeps_start_rows_immutable(tmp_path):
    start = tmp_path / "start.json"
    start.write_text(json.dumps({"items": [{"ticker": "aaa", "cik": "1", "company_title": "AAA Start"}]}), encoding="utf-8")
    additions = tmp_path / "additions.jsonl"
    additions.write_text(json.dumps({"ticker": "aaa", "cik": "9", "company_title": "AAA Add"}) + "\n", encoding="utf-8")
    out = materialize_master_universe(output_root=tmp_path, start_path=start, additions_path=additions)

    assert json.loads(start.read_text(encoding="utf-8"))["items"][0]["cik"] == "1"
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["items"][0]["cik"] == "1"


def test_master_source_missing_start_file_is_clear(tmp_path):
    start = tmp_path / "missing.json"

    try:
        load_master_universe_rows(start_path=start, additions_path=tmp_path / "additions.jsonl")
    except ValueError as exc:
        assert str(start) in str(exc)
        assert "not found" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_master_source_malformed_start_file_is_clear(tmp_path):
    start = tmp_path / "bad.json"
    start.write_text("{", encoding="utf-8")

    try:
        load_master_universe_rows(start_path=start, additions_path=tmp_path / "additions.jsonl")
    except ValueError as exc:
        assert str(start) in str(exc)
        assert "malformed" in str(exc)
    else:
        raise AssertionError("expected ValueError")
