# S-077: X Feed Scout Writes Emergence Fields — Replace Cashtag Enricher

**Assignee:** Sonnet
**Status:** done
**Branch:** feature/sonnet46 (branch from feature/opus46)
**Estimated files:** 1 modified, 1 test modified

---

## Context

The X Feed Discovery Scout (S-076) writes `x_trending_mentions`, `x_trending_context`, and
`x_trending_at` to AKG nodes. But the emergence formula (`compute_emergence_score`) reads
`cashtag_velocity_z` (40% weight) and `cashtag_sentiment` (20% weight). The scout's fields are
**dead data** — nothing reads them. Emergence tiers never progress.

The cashtag_enricher was supposed to write those fields, but it has 3 blockers (circular
active-sector dependency, no scheduler, wrong model name) and costs $0.25/run (50 individual
xAI calls). It has never successfully run.

**Fix:** Upgrade x_feed_scout to also write the emergence-relevant fields. This replaces
cashtag_enricher entirely. Same $0.005/run. Zero blockers.

---

## What Already Exists (Do Not Rebuild)

| Component | Location | Notes |
|---|---|---|
| `scan_x_feed()` | `sources/x_feed_scout.py:41` | Returns tickers with `mentions_estimate` and `context` |
| `DISCOVERY_PROMPT` | `sources/x_feed_scout.py:29` | Single xAI x_search prompt |
| `_extract_json_payload()` | `sources/x_feed_scout.py:177` | Robust JSON extraction |
| `_is_valid_ticker()` | `sources/x_feed_scout.py:168` | Ticker validation |
| `akg.enrich_node_cashtag()` | `knowledge_graph.py:789` | Writes velocity_z, sentiment, recomputes emergence |
| `akg.compute_emergence_score()` | `knowledge_graph.py:812` | Formula: 0.40×centrality + 0.40×velocity_z + 0.20×sentiment |
| Existing tests (8) | `tests/test_x_feed_scout.py` | All passing |

---

## NOT in Scope

- Modifying `knowledge_graph.py` — no changes needed
- Modifying `compute_emergence_score()` or tier logic
- Deleting `cashtag_enricher.py` — keep file, it's just unused now
- Adding scheduling — separate concern
- Modifying the CLI command — no changes needed
- Modifying any connector

---

## Implementation

### MODIFY: `tradingagents/dealflow/sources/x_feed_scout.py`

**Change 1: Update DISCOVERY_PROMPT to request sentiment (line 29)**

Replace the current `DISCOVERY_PROMPT` with:

```python
DISCOVERY_PROMPT = (
    "Search X for financial discussions in the last 24 hours. "
    "Which US stock tickers (equities only — no crypto, no forex, no indices) are: "
    "(1) getting the most total mentions, "
    "(2) showing unusual mention volume spikes vs their baseline, or "
    "(3) generating the most debate and excitement among traders and financial accounts? "
    "Combine all three signals into a single ranked list. "
    'Return JSON only: {"trending": [{"ticker": "NVDA", "mentions_estimate": 1000, '
    '"sentiment": 0.7, "context": "brief reason for attention"}, ...]}. '
    "Top 30 tickers. No BTC, ETH, or other crypto. "
    "sentiment is a float from -1.0 (very bearish) to +1.0 (very bullish) based on "
    "the overall tone of X posts about this ticker."
)
```

Only change: added `"sentiment": 0.7` to the JSON example and a one-line explanation of the sentiment scale.

**Change 2: Add `_compute_batch_velocity_z()` helper function**

Add this function after `_is_valid_ticker()`:

```python
def _compute_batch_velocity_z(tickers: Dict[str, Dict[str, Any]]) -> None:
    """Compute velocity z-score in-place from mentions_estimate across the batch.

    z = (mentions - mean) / std for each ticker. If std == 0, all get z = 0.
    """
    if not tickers:
        return
    mentions = [t["mentions_estimate"] for t in tickers.values()]
    mean = sum(mentions) / len(mentions)
    variance = sum((m - mean) ** 2 for m in mentions) / len(mentions)
    std = variance ** 0.5
    for entry in tickers.values():
        if std > 0:
            entry["velocity_z"] = round((entry["mentions_estimate"] - mean) / std, 4)
        else:
            entry["velocity_z"] = 0.0
```

**Change 3: Parse sentiment from response (inside the `for entry in parsed.get("trending", [])` loop)**

After line 98 (`context = str(entry.get("context", ""))[:200]`), add:

```python
                sentiment = entry.get("sentiment")
                try:
                    sentiment = float(sentiment) if sentiment is not None else 0.0
                    sentiment = max(-1.0, min(1.0, sentiment))
                except (ValueError, TypeError):
                    sentiment = 0.0
```

And update the dict on line 99:
```python
                all_tickers[ticker] = {
                    "ticker": ticker,
                    "mentions_estimate": mentions,
                    "sentiment": sentiment,
                    "context": context,
                }
```

**Change 4: Compute velocity_z and write emergence fields (write phase, after line 128)**

After `ticker_list = []` (line 128), add:

```python
    _compute_batch_velocity_z(all_tickers)
```

Then in the per-ticker loop (lines 130-151), REPLACE the three `update_node_field` calls with a call to `enrich_node_cashtag`:

```python
    for ticker, entry in sorted(all_tickers.items(), key=lambda kv: -kv[1]["mentions_estimate"]):
        is_new = ticker not in akg._nodes
        if is_new:
            akg.add_node(
                ticker,
                node_type="company",
                metadata={
                    "seed_sources": ["x_feed_scout"],
                    "discovered_at": now_iso,
                    "discovery_context": entry["context"],
                },
            )
            new_count += 1
        else:
            updated_count += 1

        # Write emergence-relevant fields via enrich_node_cashtag
        akg.enrich_node_cashtag(
            ticker=ticker,
            velocity_z=entry.get("velocity_z", 0.0),
            mentions_7d=entry["mentions_estimate"],
            velocity_trend="rising" if entry.get("velocity_z", 0) > 0.5 else "stable",
            sentiment=entry.get("sentiment", 0.0),
            as_of_date=now_iso,
        )

        # Keep x_trending fields for display/audit
        akg.update_node_field(ticker, "x_trending_at", now_iso)
        akg.update_node_field(ticker, "x_trending_mentions", entry["mentions_estimate"])
        akg.update_node_field(ticker, "x_trending_context", entry["context"])

        entry["is_new"] = is_new
        ticker_list.append(entry)
```

**Change 5: Remove the separate `compute_all_emergence_scores()` call (line 153)**

Delete line 153 (`akg.compute_all_emergence_scores()`). It's now redundant because
`enrich_node_cashtag()` calls `compute_emergence_score()` per-ticker internally.

**Change 6: Update the return dict's tickers to include new fields**

The tickers list entries should now include `velocity_z` and `sentiment`:
```python
        # Already in the entry dict from earlier — no extra code needed
```

---

## MODIFY: `tests/test_x_feed_scout.py`

**Import the new helper:**
Add `_compute_batch_velocity_z` to the imports from `x_feed_scout`.

**Update `_make_xai_response` to include sentiment:**
Each ticker dict in test data should include `"sentiment": 0.7` (or similar).

**Add test: `test_compute_batch_velocity_z`**
```python
def test_compute_batch_velocity_z():
    """Verify z-score computation from mentions data."""
    from tradingagents.dealflow.sources.x_feed_scout import _compute_batch_velocity_z
    tickers = {
        "NVDA": {"mentions_estimate": 1000, "ticker": "NVDA"},
        "AAPL": {"mentions_estimate": 500, "ticker": "AAPL"},
        "TSLA": {"mentions_estimate": 200, "ticker": "TSLA"},
    }
    _compute_batch_velocity_z(tickers)
    # NVDA has highest mentions → highest z-score
    assert tickers["NVDA"]["velocity_z"] > tickers["AAPL"]["velocity_z"]
    assert tickers["AAPL"]["velocity_z"] > tickers["TSLA"]["velocity_z"]
    # Mean of [1000, 500, 200] = 566.67 → TSLA (200) should be negative
    assert tickers["TSLA"]["velocity_z"] < 0
```

**Add test: `test_compute_batch_velocity_z_uniform`**
```python
def test_compute_batch_velocity_z_uniform():
    """All same mentions → all z-scores = 0 (std = 0)."""
    from tradingagents.dealflow.sources.x_feed_scout import _compute_batch_velocity_z
    tickers = {
        "NVDA": {"mentions_estimate": 500, "ticker": "NVDA"},
        "AAPL": {"mentions_estimate": 500, "ticker": "AAPL"},
    }
    _compute_batch_velocity_z(tickers)
    assert tickers["NVDA"]["velocity_z"] == 0.0
    assert tickers["AAPL"]["velocity_z"] == 0.0
```

**Add test: `test_scan_writes_emergence_fields`**
```python
def test_scan_writes_emergence_fields():
    """Scout must call enrich_node_cashtag with velocity_z and sentiment."""
    resp = _make_xai_response([
        {"ticker": "NVDA", "mentions_estimate": 1000, "sentiment": 0.8, "context": "AI"},
        {"ticker": "AAPL", "mentions_estimate": 300, "sentiment": -0.2, "context": "miss"},
    ])

    mock_akg = MagicMock()
    mock_akg._nodes = {"NVDA": {}, "AAPL": {}}

    with patch.dict(os.environ, {"XAI_API_KEY": "fake-key"}), \
         patch("tradingagents.dealflow.sources.x_feed_scout.OpenAI") as MockOpenAI, \
         patch("tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph") as MockAKG:
        MockOpenAI.return_value = _make_client(resp)
        MockAKG.load.return_value = mock_akg

        result = scan_x_feed()

    # enrich_node_cashtag called once per ticker
    assert mock_akg.enrich_node_cashtag.call_count == 2

    # Verify sentiment was passed through
    calls = {c.kwargs["ticker"]: c.kwargs for c in mock_akg.enrich_node_cashtag.call_args_list}
    assert calls["NVDA"]["sentiment"] == 0.8
    assert calls["AAPL"]["sentiment"] == -0.2

    # Verify velocity_z was computed (NVDA > AAPL since more mentions)
    assert calls["NVDA"]["velocity_z"] > calls["AAPL"]["velocity_z"]
```

**Add test: `test_scan_sentiment_defaults_to_zero`**
```python
def test_scan_sentiment_defaults_to_zero():
    """Missing sentiment in response → defaults to 0.0."""
    resp = _make_xai_response([
        {"ticker": "MSFT", "mentions_estimate": 400, "context": "cloud"},  # no sentiment key
    ])

    mock_akg = MagicMock()
    mock_akg._nodes = {"MSFT": {}}

    with patch.dict(os.environ, {"XAI_API_KEY": "fake-key"}), \
         patch("tradingagents.dealflow.sources.x_feed_scout.OpenAI") as MockOpenAI, \
         patch("tradingagents.graph.knowledge_graph.AeternusKnowledgeGraph") as MockAKG:
        MockOpenAI.return_value = _make_client(resp)
        MockAKG.load.return_value = mock_akg

        result = scan_x_feed()

    calls = mock_akg.enrich_node_cashtag.call_args_list
    assert calls[0].kwargs["sentiment"] == 0.0
```

**Update existing `test_scan_writes_to_akg`:**
Change the assertion from `update_node_field.call_count == 6` to `== 6` (still 3 x_trending fields
per ticker). Also add assertion for `enrich_node_cashtag.call_count == 2`.

Change `compute_all_emergence_scores.assert_called_once()` to `compute_all_emergence_scores.assert_not_called()` (because `enrich_node_cashtag` handles it per-ticker now).

---

## DO NOT TOUCH

- `knowledge_graph.py` — no modifications
- `cashtag_enricher.py` — leave as-is (dead code, not deleted)
- `cli/commands/x_feed_scout.py` — no changes needed
- `default_config.py` — no new keys needed
- `pipeline.py` — separate concern
- Any connector files

---

## Tests

All existing 8 tests must still pass. 4 new tests added:

| # | Test | What it verifies |
|---|---|---|
| 9 | `test_compute_batch_velocity_z` | Z-score math: highest mentions = highest z, lowest = negative |
| 10 | `test_compute_batch_velocity_z_uniform` | All same mentions → z = 0 (std = 0 case) |
| 11 | `test_scan_writes_emergence_fields` | `enrich_node_cashtag` called with velocity_z + sentiment per ticker |
| 12 | `test_scan_sentiment_defaults_to_zero` | Missing sentiment key in response → defaults to 0.0 |

---

## Verification

```bash
# 1. Tests (all 12 must pass)
python3 -m pytest tests/test_x_feed_scout.py -v

# 2. Dry run
aeternus x-discover --dry-run

# 3. Regression
python3 -m pytest tests/test_knowledge_graph.py -v

# 4. Verify emergence fields written (after live run)
python3 -c "
from tradingagents.graph.knowledge_graph import AeternusKnowledgeGraph
akg = AeternusKnowledgeGraph.load()
nodes = [n for n in akg._nodes.values() if n.get('cashtag_velocity_z') is not None]
print(f'Nodes with velocity_z: {len(nodes)}')
for n in sorted(nodes, key=lambda x: -(x.get('cashtag_velocity_z') or 0))[:10]:
    print(f'  {n[\"id\"]:6s}  vz={n.get(\"cashtag_velocity_z\", 0):+.2f}  sent={n.get(\"cashtag_sentiment\", 0):+.2f}  tier={n.get(\"emergence_tier\", \"?\")}')
"
```

---

## Expected Outcome

- Same $0.005/run cost (no extra xAI calls)
- Scout writes `cashtag_velocity_z` and `cashtag_sentiment` directly to AKG nodes
- Emergence tiers actually progress: high-mention, positive-sentiment tickers move DARK → ROCKY → ATMOSPHERE → HABITABLE
- `enrich_node_cashtag()` handles per-ticker emergence recomputation automatically
- Cashtag enricher is no longer needed in the loop (kept as dead code, not deleted)
- 12 tests pass (8 existing + 4 new)
