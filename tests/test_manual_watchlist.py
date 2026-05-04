import json
from pathlib import Path

from tradingagents.dealflow.manual_watchlist import add_idea, list_active_ideas, load_watchlist, remove_idea


def test_add_idea_persists_minimal_schema_with_context_snapshot(tmp_path: Path):
    watchlist_path = tmp_path / "manual_watchlist.json"

    idea = add_idea(
        symbol="aapl",
        path=watchlist_path,
        context_provider=lambda symbol: {
            "akg": {
                "found": True,
                "display_name": f"{symbol} name",
                "sector": "Technology",
                "aeternus_score": 81,
                "node": {
                    "asset_class": "Equity",
                    "last_scored_date": "2026-03-22",
                },
            }
        },
    )

    assert idea["symbol"] == "AAPL"
    assert idea["active"] is True
    assert "created_at" in idea
    assert "context_snapshot" in idea
    assert idea["context_snapshot"]["display_name"] == "AAPL name"
    assert "priority" not in idea
    assert "lane_preference" not in idea
    assert "note" not in idea
    assert "expires_at" not in idea

    payload = json.loads(watchlist_path.read_text())
    assert payload["items"][0]["symbol"] == "AAPL"
    assert payload["items"][0]["context_snapshot"]["sector"] == "Technology"


def test_list_active_ideas_ignores_legacy_expiry_and_returns_active_only(tmp_path: Path):
    watchlist_path = tmp_path / "manual_watchlist.json"
    watchlist_path.write_text(
        json.dumps(
            {
                "updated_at": "2026-03-22T00:00:00Z",
                "items": [
                    {
                        "symbol": "AAPL",
                        "created_at": "2026-03-01T00:00:00Z",
                        "active": True,
                    },
                    {
                        "symbol": "MSFT",
                        "created_at": "2026-03-01T00:00:00Z",
                        "active": False,
                        "expires_at": "2026-03-05T00:00:00Z",
                    },
                ],
            }
        )
    )

    active = list_active_ideas(as_of_date="2026-12-31", path=watchlist_path)

    assert [row["symbol"] for row in active] == ["AAPL"]


def test_remove_idea_deactivates_symbol_without_deleting_history(tmp_path: Path):
    watchlist_path = tmp_path / "manual_watchlist.json"
    add_idea(symbol="AAPL", path=watchlist_path, context_provider=lambda _symbol: {"akg": {}})

    removed = remove_idea("AAPL", path=watchlist_path)

    assert removed is True
    rows = load_watchlist(watchlist_path)["items"]
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["active"] is False
