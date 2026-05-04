import json
from pathlib import Path

try:
    import chromadb
    from chromadb.config import Settings
    _CHROMADB_AVAILABLE = True
except Exception:
    chromadb = None
    Settings = None
    _CHROMADB_AVAILABLE = False

from openai import OpenAI


def get_api_key(url):
    import os
    if "x.ai" in url:
        return os.environ.get("XAI_API_KEY")
    if "minimaxi" in url or "minimax" in url:
        return os.environ.get("MINIMAX_API_KEY")
    if "google" in url:
        return os.environ.get("GOOGLE_API_KEY")
    if "anthropic" in url:
        return os.environ.get("ANTHROPIC_API_KEY")
    return os.environ.get("OPENAI_API_KEY")

class _NullCollection:
    """No-op ChromaDB collection stub for environments where chromadb is unavailable."""
    def count(self): return 0
    def add(self, **kwargs): pass
    def query(self, **kwargs): return {"documents": [[]], "metadatas": [[]], "distances": [[]]}


class FinancialSituationMemory:
    def __init__(self, name, config):
        import os
        self.name = name
        self.provider = config.get("llm_provider", "openai").lower()
        self.backend_url = config.get("backend_url", "https://api.openai.com/v1")
        
        # Determine Embedding Provider and Model
        self.embed_client = None
        self.embed_model = "text-embedding-3-small" # Default
        
        # Check for Google Fallback (since it's common and user has it)
        google_key = os.environ.get("GOOGLE_API_KEY")
        openai_key = os.environ.get("OPENAI_API_KEY")
        xai_key = os.environ.get("XAI_API_KEY")
        
        if self.backend_url == "http://localhost:11434/v1":
            self.embed_type = "ollama"
            self.embed_model = "nomic-embed-text"
            self.embed_client = OpenAI(base_url=self.backend_url, api_key="ollama")
        elif "x.ai" in self.backend_url or self.provider == "xai":
            # xAI doesn't have an embeddings API yet. Use Google or OpenAI as fallback.
            if google_key:
                from langchain_google_genai import GoogleGenerativeAIEmbeddings
                self.embed_type = "google"
                self.embed_model = "models/text-embedding-004"
                self.embed_client = GoogleGenerativeAIEmbeddings(model=self.embed_model, google_api_key=google_key)
            elif openai_key:
                self.embed_type = "openai"
                self.embed_client = OpenAI(api_key=openai_key)
            else:
                self.embed_type = "none"
                print(f"[WARNING] No embedding provider available for xAI. Memory will be disabled.")
        elif "minimaxi" in self.backend_url or "minimax" in self.backend_url:
            self.embed_type = "openai"
            self.embed_model = "text-embedding-3-small"
            api_key = os.environ.get("MINIMAX_API_KEY")
            self.embed_client = OpenAI(base_url=self.backend_url, api_key=api_key)
        elif self.provider in {"claude_cli", "codex_cli"} or self.backend_url in {"claude_cli", "codex_cli"}:
            # Local CLI providers do not expose embeddings. Use a real embeddings vendor
            # only when one is configured; otherwise disable memory gracefully.
            if google_key:
                from langchain_google_genai import GoogleGenerativeAIEmbeddings
                self.embed_type = "google"
                self.embed_model = "models/text-embedding-004"
                self.embed_client = GoogleGenerativeAIEmbeddings(model=self.embed_model, google_api_key=google_key)
            elif openai_key:
                self.embed_type = "openai"
                self.embed_client = OpenAI(api_key=openai_key)
            else:
                self.embed_type = "none"
                print(f"[WARNING] No embedding provider available for {self.provider or self.backend_url}. Memory will be disabled.")
        else:
            # Default to OpenAI
            self.embed_type = "openai"
            self.embed_client = OpenAI(base_url=self.backend_url, api_key=openai_key or xai_key)

        print(f"[DEBUG-MEMORY] {name} init | Type: {self.embed_type} | Model: {self.embed_model}")

        if _CHROMADB_AVAILABLE:
            self.chroma_client = chromadb.Client(Settings(allow_reset=True))
            try:
                self.situation_collection = self.chroma_client.create_collection(name=name)
            except Exception:
                self.situation_collection = self.chroma_client.get_collection(name=name)
        else:
            self.chroma_client = None
            self.situation_collection = _NullCollection()

    def get_embedding(self, text):
        """Get embedding for a text with provider-aware logic."""
        if self.embed_type == "none" or not self.embed_client:
            return [0.0] * 1536 # Fallback zero vector
            
        try:
            if self.embed_type == "google":
                return self.embed_client.embed_query(text)
            else:
                response = self.embed_client.embeddings.create(
                    model=self.embed_model, input=text
                )
                return response.data[0].embedding
        except Exception as e:
            print(f"[ERROR-MEMORY] Failed to get embedding: {e}")
            return [0.0] * 1536

    def add_situations(self, situations_and_advice):
        """Add financial situations and their corresponding advice. Parameter is a list of tuples (situation, rec)"""
        if not _CHROMADB_AVAILABLE:
            return

        situations = []
        advice = []
        ids = []
        embeddings = []

        offset = self.situation_collection.count()

        for i, (situation, recommendation) in enumerate(situations_and_advice):
            situations.append(situation)
            advice.append(recommendation)
            ids.append(str(offset + i))
            embeddings.append(self.get_embedding(situation))

        self.situation_collection.add(
            documents=situations,
            metadatas=[{"recommendation": rec} for rec in advice],
            embeddings=embeddings,
            ids=ids,
        )

    def get_memories(self, current_situation, n_matches=1):
        """Find matching recommendations using OpenAI embeddings"""
        if not _CHROMADB_AVAILABLE:
            return []

        query_embedding = self.get_embedding(current_situation)

        results = self.situation_collection.query(
            query_embeddings=[query_embedding],
            n_results=n_matches,
            include=["metadatas", "documents", "distances"],
        )

        matched_results = []
        for i in range(len(results["documents"][0])):
            matched_results.append(
                {
                    "matched_situation": results["documents"][0][i],
                    "recommendation": results["metadatas"][0][i]["recommendation"],
                    "similarity_score": 1 - results["distances"][0][i],
                }
            )

        return matched_results


class TradeMemory:
    """Persistent lessons from past trade outcomes via track_record.json."""

    def __init__(self, track_record_path="eval_results/track_record.json"):
        self._path = Path(track_record_path)
        self._cache = None
        self._cache_mtime = 0.0

    def get_lessons(self, ticker, sector=None, n=5):
        """Return formatted past trade outcomes for this ticker/sector."""
        records = self._load()
        if not records:
            return ""

        closed = [r for r in records if r.get("status") == "CLOSED"]

        # Priority: same ticker closed, same ticker open, same sector closed
        same_ticker_closed = [r for r in closed if r.get("ticker") == ticker]
        same_ticker_open = [
            r for r in records
            if r.get("ticker") == ticker and r.get("status") != "CLOSED"
        ]
        same_sector_closed = [
            r for r in closed
            if r.get("sector") == sector and r.get("ticker") != ticker
        ] if sector else []

        selected = (same_ticker_closed + same_ticker_open + same_sector_closed)[:n]
        if not selected:
            return ""

        return self._format(selected, ticker)

    def _load(self):
        if not self._path.exists():
            return []
        try:
            mtime = self._path.stat().st_mtime
        except OSError:
            return []
        if self._cache is not None and mtime == self._cache_mtime:
            return self._cache
        try:
            with open(self._path) as f:
                self._cache = json.load(f)
            self._cache_mtime = mtime
        except (json.JSONDecodeError, OSError):
            self._cache = []
        return self._cache

    def _format(self, records, current_ticker):
        lines = ["--- PAST TRADE OUTCOMES (Institutional Memory) ---"]
        for r in records:
            ticker = r.get("ticker", "?")
            date = r.get("date", "?")
            score = r.get("aeternus_score", "?")
            rating = r.get("rating", "?")
            price_at = r.get("price_at_rating")
            close_price = r.get("close_price")
            status = r.get("status", "OPEN")

            price_str = f"at ${price_at:.2f}" if price_at else ""
            outcome_str = ""
            if status == "CLOSED" and price_at and close_price:
                pnl_pct = (close_price - price_at) / price_at * 100
                sign = "+" if pnl_pct > 0 else ""
                won = "CORRECT" if (pnl_pct > 0 and "Buy" in rating) or (pnl_pct < 0 and "Sell" in rating) else "WRONG"
                outcome_str = f" -> ${close_price:.2f} ({sign}{pnl_pct:.1f}%) [{won}]"
            elif status == "OPEN":
                outcome_str = " [OPEN]"

            label = "" if ticker == current_ticker else f" ({r.get('sector', 'same sector')})"
            lines.append(f"- {ticker}{label} {date}: {rating} ({score}/100) {price_str}{outcome_str}")

        lines.append("Learn from CORRECT decisions and avoid repeating WRONG ones.")
        lines.append("---")
        return "\n".join(lines)


if __name__ == "__main__":
    # Example usage
    matcher = FinancialSituationMemory()

    # Example data
    example_data = [
        (
            "High inflation rate with rising interest rates and declining consumer spending",
            "Consider defensive sectors like consumer staples and utilities. Review fixed-income portfolio duration.",
        ),
        (
            "Tech sector showing high volatility with increasing institutional selling pressure",
            "Reduce exposure to high-growth tech stocks. Look for value opportunities in established tech companies with strong cash flows.",
        ),
        (
            "Strong dollar affecting emerging markets with increasing forex volatility",
            "Hedge currency exposure in international positions. Consider reducing allocation to emerging market debt.",
        ),
        (
            "Market showing signs of sector rotation with rising yields",
            "Rebalance portfolio to maintain target allocations. Consider increasing exposure to sectors benefiting from higher rates.",
        ),
    ]

    # Add the example situations and recommendations
    matcher.add_situations(example_data)

    # Example query
    current_situation = """
    Market showing increased volatility in tech sector, with institutional investors 
    reducing positions and rising interest rates affecting growth stock valuations
    """

    try:
        recommendations = matcher.get_memories(current_situation, n_matches=2)

        for i, rec in enumerate(recommendations, 1):
            print(f"\nMatch {i}:")
            print(f"Similarity Score: {rec['similarity_score']:.2f}")
            print(f"Matched Situation: {rec['matched_situation']}")
            print(f"Recommendation: {rec['recommendation']}")

    except Exception as e:
        print(f"Error during recommendation: {str(e)}")
