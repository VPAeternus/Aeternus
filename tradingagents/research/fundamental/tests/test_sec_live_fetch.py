from pathlib import Path

from src.config.cache_paths import SEC_CACHE_ROOT
from src.ingest.filings import SecClient, SecFetchConfig, discover_required_filings


def test_default_sec_cache_root_is_aeternus_holdings_cache():
    assert SEC_CACHE_ROOT == Path("/Users/aeternusholdings/Documents/GitHub/AeternusHoldings/cache/sec")


def test_sec_client_uses_cache_and_does_not_refetch(tmp_path: Path):
    calls = {"count": 0}

    def fetcher(url: str, headers: dict[str, str], timeout: int) -> bytes:
        calls["count"] += 1
        return b'{"ok": true}'

    client = SecClient(SecFetchConfig(cache_root=tmp_path, user_agent="test@example.com", sleep_seconds=0), fetcher=fetcher)

    first = client.get_json("https://data.sec.gov/submissions/CIK0000000001.json", "submissions/one.json")
    second = client.get_json("https://data.sec.gov/submissions/CIK0000000001.json", "submissions/one.json")

    assert first == second == {"ok": True}
    assert calls["count"] == 1


def test_discover_required_filings_finds_item_202_and_periodic():
    submissions = {
        "filings": {
            "recent": {
                "form": ["10-Q", "8-K"],
                "filingDate": ["2024-08-01", "2024-08-07"],
                "reportDate": ["2024-06-30", ""],
                "acceptanceDateTime": ["2024-08-01T16:01:00", "2024-08-07T16:05:00"],
                "accessionNumber": ["0001-24-000001", "0001-24-000002"],
                "items": ["", "2.02"],
                "primaryDocument": ["q2.htm", "8k.htm"],
            }
        }
    }
    indexes = {
        "0001-24-000002": ["8k.htm", "ex99-1.htm", "xbrl.xml"],
        "0001-24-000001": ["q2.htm", "xbrl.xml"],
    }

    result = discover_required_filings("ABC", "1", "2024Q3", submissions, indexes)

    assert result["document_status"] == "ready_for_fetch"
    assert result["earnings_8k_accession"] == "0001-24-000002"
    assert result["earnings_exhibit_document"] == "ex99-1.htm"
    assert result["periodic_accession"] == "0001-24-000001"
