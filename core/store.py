import numpy as np
import chromadb
from chromadb.utils import embedding_functions
from rank_bm25 import BM25Okapi
from typing import List, Dict, Any

import config


class DocumentStore:
    """Vector + BM25 store scoped to a single department collection."""

    def __init__(self, collection_name: str):
        self._client = chromadb.PersistentClient(path=config.CHROMA_DIR)
        self._embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=config.EMBED_MODEL
        )
        # ChromaDB collection names: 3-63 chars, alphanumeric + hyphens/underscores
        safe_name = collection_name[:63]
        self.collection = self._client.get_or_create_collection(
            name=safe_name,
            embedding_function=self._embed_fn,
            metadata={"hnsw:space": "cosine"},
        )
        self._bm25: BM25Okapi | None = None
        self._bm25_ids: List[str] = []
        self._bm25_texts: List[str] = []
        self._rebuild_bm25()

    def _rebuild_bm25(self):
        results = self.collection.get(include=["documents"])
        if not results["documents"]:
            return
        self._bm25_ids = results["ids"]
        self._bm25_texts = results["documents"]
        tokenized = [t.lower().split() for t in self._bm25_texts]
        self._bm25 = BM25Okapi(tokenized)

    def add_chunks(self, chunks: List[Dict[str, Any]]):
        ids = [c["id"] for c in chunks]
        texts = [c["text"] for c in chunks]
        metadatas = [c["metadata"] for c in chunks]
        self.collection.add(ids=ids, documents=texts, metadatas=metadatas)

        self._bm25_ids.extend(ids)
        self._bm25_texts.extend(texts)
        tokenized = [t.lower().split() for t in self._bm25_texts]
        self._bm25 = BM25Okapi(tokenized)

    def hybrid_search(self, query: str, k: int | None = None) -> List[Dict]:
        k = k or config.TOP_K
        total = len(self._bm25_texts)
        if total == 0:
            return []

        fetch = min(k * 2, total)
        scores: Dict[str, float] = {}

        # Semantic
        sem = self.collection.query(query_texts=[query], n_results=fetch)
        distances = sem["distances"][0]
        max_dist = max(distances) or 1.0
        for id_, dist in zip(sem["ids"][0], distances):
            scores[id_] = config.SEMANTIC_WEIGHT * (1 - dist / max_dist)

        # BM25
        bm25_scores = self._bm25.get_scores(query.lower().split())
        top_idx = np.argsort(bm25_scores)[::-1][:fetch]
        max_bm25 = bm25_scores[top_idx[0]] if len(top_idx) else 1.0
        if max_bm25 == 0:
            max_bm25 = 1.0
        for idx in top_idx:
            id_ = self._bm25_ids[idx]
            scores[id_] = scores.get(id_, 0.0) + config.BM25_WEIGHT * (
                bm25_scores[idx] / max_bm25
            )

        top_ids = sorted(scores, key=lambda x: scores[x], reverse=True)[:k]
        if not top_ids:
            return []

        fetched = self.collection.get(ids=top_ids, include=["documents", "metadatas"])
        return [
            {
                "id": id_,
                "text": text,
                "metadata": meta,
                "score": round(scores[id_], 4),
            }
            for id_, text, meta in zip(
                fetched["ids"], fetched["documents"], fetched["metadatas"]
            )
        ]

    def list_documents(self) -> List[Dict]:
        results = self.collection.get(include=["metadatas"])
        seen: Dict[str, Dict] = {}
        for meta in results["metadatas"]:
            doc_id = meta.get("doc_id")
            if doc_id and doc_id not in seen:
                seen[doc_id] = {
                    "doc_id": doc_id,
                    "filename": meta.get("filename"),
                    "ingested_at": meta.get("ingested_at"),
                    "total_chunks": meta.get("total_chunks"),
                }
        return list(seen.values())

    def delete_document(self, doc_id: str):
        results = self.collection.get(where={"doc_id": doc_id})
        if results["ids"]:
            self.collection.delete(ids=results["ids"])
            self._rebuild_bm25()


class StoreManager:
    """Singleton pool — one DocumentStore per department."""

    _instance: "StoreManager | None" = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._stores: Dict[str, DocumentStore] = {}
        return cls._instance

    def get(self, dept_id: str) -> DocumentStore:
        if dept_id not in self._stores:
            # Prefix keeps collection names distinct and readable
            self._stores[dept_id] = DocumentStore(f"dept-{dept_id}")
        return self._stores[dept_id]

    def evict(self, dept_id: str):
        """Remove a department's store from the pool (call after deletion)."""
        self._stores.pop(dept_id, None)
