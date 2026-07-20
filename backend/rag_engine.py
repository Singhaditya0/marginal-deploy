"""
rag_engine.py  (free-deploy variant)
-------------------------------------
Same interface as the local Ollama version's rag_engine.py, but implemented
with plain-Python TF-IDF instead of sentence-transformer embeddings + FAISS.

Why: free hosting tiers (e.g. Render's free 512MB instance) don't have the
RAM to load torch + a transformer model. TF-IDF needs no ML libraries at
all, installs in seconds, and runs happily in well under 100MB.

Trade-off: TF-IDF matches on word overlap, not true semantic meaning, so
retrieval is a little less forgiving of paraphrased questions than the
embedding-based version. Documented as a known limitation in the report.
"""

import re
import math
from collections import Counter
from typing import List, Dict, Tuple


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class DocumentIndex:
    """TF-IDF index for a single document's chunks."""

    def __init__(self, chunks: List[str]):
        self.chunks = chunks
        self._tokenized = [_tokenize(c) for c in chunks]

        # Document frequency across this document's own chunks
        df: Counter = Counter()
        for tokens in self._tokenized:
            df.update(set(tokens))

        n = len(chunks)
        self._idf: Dict[str, float] = {
            term: math.log((n + 1) / (freq + 1)) + 1 for term, freq in df.items()
        }

        self._vectors: List[Dict[str, float]] = [self._vectorize(tokens) for tokens in self._tokenized]

    def _vectorize(self, tokens: List[str]) -> Dict[str, float]:
        if not tokens:
            return {}
        counts = Counter(tokens)
        length = len(tokens)
        return {t: (c / length) * self._idf.get(t, 0.0) for t, c in counts.items()}

    def _query_vector(self, query: str) -> Dict[str, float]:
        tokens = _tokenize(query)
        if not tokens:
            return {}
        counts = Counter(tokens)
        length = len(tokens)
        return {t: (c / length) * self._idf[t] for t, c in counts.items() if t in self._idf}

    @staticmethod
    def _cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
        if not a or not b:
            return 0.0
        dot = sum(v * b.get(k, 0.0) for k, v in a.items())
        mag_a = math.sqrt(sum(v * v for v in a.values()))
        mag_b = math.sqrt(sum(v * v for v in b.values()))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    def search(self, query: str, k: int = 5) -> List[Tuple[str, float, int]]:
        """Returns top-k (chunk_text, similarity_score, chunk_index)."""
        if not self.chunks:
            return []
        q_vec = self._query_vector(query)
        scored = [(self._cosine(q_vec, v), i) for i, v in enumerate(self._vectors)]
        scored.sort(key=lambda x: x[0], reverse=True)
        # Hand over the top-k regardless of score — weak keyword overlap is
        # still a useful signal, and the LLM can judge relevance from there.
        top = scored[: min(k, len(scored))]
        return [(self.chunks[i], score, i) for score, i in top]


class DocumentStore:
    """In-memory registry of all uploaded documents, keyed by doc_id."""

    def __init__(self):
        self._indexes: Dict[str, DocumentIndex] = {}
        self._metadata: Dict[str, dict] = {}

    def add_document(self, doc_id: str, chunks: List[str], metadata: dict):
        self._indexes[doc_id] = DocumentIndex(chunks)
        self._metadata[doc_id] = metadata

    def get_index(self, doc_id: str) -> DocumentIndex:
        if doc_id not in self._indexes:
            raise KeyError(f"No document found with id {doc_id}")
        return self._indexes[doc_id]

    def get_metadata(self, doc_id: str) -> dict:
        return self._metadata.get(doc_id, {})

    def list_documents(self) -> List[dict]:
        return [{"doc_id": doc_id, **meta} for doc_id, meta in self._metadata.items()]

    def delete_document(self, doc_id: str):
        self._indexes.pop(doc_id, None)
        self._metadata.pop(doc_id, None)


store = DocumentStore()
