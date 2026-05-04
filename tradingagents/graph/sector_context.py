# tradingagents/graph/sector_context.py

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
import yfinance as yf

# Classification dicts removed — AKG is the source of truth.
EQUITY_SECTOR_BASELINE: dict = {}
SECTOR_NORMALIZATION: dict = {}
SECTOR_OVERRIDES: dict = {}


SECTOR_CACHE_PATH = Path("eval_results") / "deal_flow" / "sector_cache.json"

class SectorContext:
    """Provides sector-level context and peer comparison for tickers."""
    
    def __init__(self):
        # In a real app, this could be backed by a database or a more robust cache
        self._sector_cache = {}
        self._peer_cache = {}
        self._dealflow_sector_cache = None

    def get_context(self, ticker: str) -> Dict[str, Any]:
        """Get full sector context for a ticker."""
        normalized_ticker = self._normalize_ticker(ticker)
        info = self._get_ticker_info(normalized_ticker)
        sector = info.get("sector", "Unknown")
        industry = info.get("industry", "Unknown")
        
        peers = self.get_peers(normalized_ticker, sector)
        
        return {
            "sector": sector,
            "industry": industry,
            "peers": peers,
            "market_cap": info.get("marketCap"),
            "forward_pe": info.get("forwardPE"),
            "price_to_book": info.get("priceToBook"),
            "peer_comparison": self._compute_peer_comparison(info, peers)
        }

    def get_sector(self, ticker: str) -> str:
        """Get the sector for a ticker."""
        return self._get_ticker_info(self._normalize_ticker(ticker)).get("sector", "Unknown")

    def get_peers(self, ticker: str, sector: str = None) -> List[str]:
        """
        Get similar peers for a ticker.
        """
        # 1. Check Cache
        normalized_ticker = self._normalize_ticker(ticker)
        if normalized_ticker in self._peer_cache:
            return self._peer_cache[normalized_ticker]
            
        # 2. Hardcoded common peers (Expanded Universe)
        common_peers = {
            # Tech / AI
            "AAPL": ["MSFT", "GOOGL", "META", "AMZN"],
            "MSFT": ["AAPL", "GOOGL", "ORCL", "CRM"],
            "GOOGL": ["META", "AMZN", "MSFT", "AAPL"],
            "META": ["GOOGL", "SNAP", "PINS", "MSFT"],
            "NVDA": ["AMD", "INTC", "AVGO", "MU"],
            "AMD": ["NVDA", "INTC", "TSM", "ARM"],
            "TSM": ["NVDA", "INTC", "AMD", "AVGO"],
            # EVs / Auto
            "TSLA": ["F", "GM", "RIVN", "LCID", "TM"],
            "RIVN": ["TSLA", "F", "GM", "LCID"],
            "F": ["GM", "TM", "HMC", "STLA"],
            "GM": ["F", "TM", "HMC", "STLA"],
            # Retail / E-commerce
            "AMZN": ["WMT", "TGT", "EBAY", "BABA"],
            "WMT": ["TGT", "COST", "AMZN", "DG"],
            "TGT": ["WMT", "COST", "M", "KSS"],
            # Finance
            "JPM": ["BAC", "WFC", "C", "GS"],
            "BAC": ["JPM", "WFC", "C", "MS"],
            "V": ["MA", "AXP", "PYPL", "DFS"],
            "MA": ["V", "AXP", "PYPL", "DFS"]
        }
        
        peers = common_peers.get(normalized_ticker, [])
        self._peer_cache[normalized_ticker] = peers
        return peers

    def _get_ticker_info(self, ticker: str) -> Dict[str, Any]:
        """Fetch ticker info via yfinance with caching."""
        normalized_ticker = self._normalize_ticker(ticker)
        if normalized_ticker in self._sector_cache:
            return self._sector_cache[normalized_ticker]
            
        info: Dict[str, Any] = {}
        try:
            t = yf.Ticker(normalized_ticker)
            fetched = t.info
            if isinstance(fetched, dict):
                info = fetched
        except Exception:
            info = {}

        canonical_sector = self._canonicalize_sector(str(info.get("sector") or ""))
        if canonical_sector:
            info["sector"] = canonical_sector
        else:
            fallback_sector = self._resolve_fallback_sector(normalized_ticker)
            if fallback_sector:
                info["sector"] = fallback_sector

        self._sector_cache[normalized_ticker] = info
        return info

    def _resolve_fallback_sector(self, normalized_ticker: str) -> str:
        baseline_sector = self._canonicalize_sector(
            str(SECTOR_OVERRIDES.get(normalized_ticker) or EQUITY_SECTOR_BASELINE.get(normalized_ticker) or "")
        )
        if baseline_sector:
            return baseline_sector

        dealflow_cache = self._load_dealflow_sector_cache()
        return self._canonicalize_sector(str(dealflow_cache.get(normalized_ticker) or ""))

    def _load_dealflow_sector_cache(self) -> Dict[str, str]:
        if self._dealflow_sector_cache is not None:
            return self._dealflow_sector_cache

        cache: Dict[str, str] = {}
        try:
            if SECTOR_CACHE_PATH.exists():
                payload = json.loads(SECTOR_CACHE_PATH.read_text())
                if isinstance(payload, dict):
                    for raw_symbol, raw_sector in payload.items():
                        symbol = self._normalize_ticker(raw_symbol)
                        sector = str(raw_sector or "").strip()
                        if symbol and sector:
                            cache[symbol] = sector
        except Exception:
            cache = {}

        self._dealflow_sector_cache = cache
        return cache

    def _normalize_ticker(self, ticker: str) -> str:
        text = str(ticker or "").upper().strip()
        if text.startswith("$"):
            text = text[1:]
        return text.replace(".", "-").replace("/", "-").replace("_", "-")

    def _canonicalize_sector(self, raw: str) -> str:
        text = str(raw or "").strip()
        if not text:
            return ""
        lowered = text.lower()
        if lowered in {"unknown", "n/a", "none", "nan"}:
            return ""
        return str(SECTOR_NORMALIZATION.get(lowered, text))

    def _compute_peer_comparison(self, ticker_info: Dict[str, Any], peers: List[str]) -> Dict[str, Any]:
        """Compare ticker metrics against peers using real-time data."""
        if not peers:
            return {"status": "No peers found for comparison"}
            
        # 1. Fetch Peer Metrics
        peer_metrics = []
        peer_pes = []
        peer_pb_ratios = []
        
        for p in peers:
            p_info = self._get_ticker_info(p)
            if not p_info:
                continue
                
            pe = p_info.get("forwardPE")
            pb = p_info.get("priceToBook")
            mc = p_info.get("marketCap")
            
            if pe: peer_pes.append(pe)
            if pb: peer_pb_ratios.append(pb)
            
            peer_metrics.append({
                "ticker": p,
                "pe": pe,
                "price_to_book": pb,
                "market_cap": mc
            })

        # 2. Calculate Averages
        avg_pe = sum(peer_pes) / len(peer_pes) if peer_pes else None
        avg_pb = sum(peer_pb_ratios) / len(peer_pb_ratios) if peer_pb_ratios else None
        
        # 3. Compare with Target
        target_pe = ticker_info.get("forwardPE")
        valuation_status = "Unknown"
        
        if target_pe and avg_pe:
            if target_pe > avg_pe * 1.1:
                valuation_status = "Premium"
            elif target_pe < avg_pe * 0.9:
                valuation_status = "Discount"
            else:
                valuation_status = "Fair Value"

        return {
            "peer_count": len(peer_metrics),
            "peer_average_pe": avg_pe,
            "peer_average_pb": avg_pb,
            "valuation_status": valuation_status,
            "target_pe": target_pe,
            "premium_discount_percent": ((target_pe / avg_pe) - 1.0) * 100 if (target_pe and avg_pe) else None,
            "details": peer_metrics
        }
