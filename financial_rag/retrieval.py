"""Local lexical vectors, BM25, and RRF; optional Pinecone vector search."""

import json
import logging
import math
import os
import threading
import time

import numpy as np
from sklearn.feature_extraction.text import CountVectorizer, TfidfTransformer

from .logging_config import event
from .registry import Registry


def rrf(rankings, k=60, limit=20):
    scores = {}
    documents = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, 1):
            identity = hit["id"]
            scores[identity] = scores.get(identity, 0) + 1 / (k + rank)
            documents[identity] = hit
    return [
        {**documents[i], "fusion_score": score}
        for i, score in sorted(scores.items(), key=lambda x: (-x[1], x[0]))[:limit]
    ]


def hit(chunk, score):
    metadata = {k: v for k, v in chunk.items() if k not in ("text", "location")}
    metadata["location_json"] = json.dumps(chunk["location"])
    metadata["chunk_text"] = chunk["text"]
    return {
        "id": chunk["chunk_id"],
        "text": chunk["text"],
        "score": float(score),
        "metadata": metadata,
    }


class LocalIndex:
    def __init__(self, chunks):
        self.chunks = chunks
        self.vectorizer = CountVectorizer(
            stop_words="english", max_features=100000, token_pattern=r"(?u)\b\w[\w,.-]*\b"
        )
        self.counts = self.vectorizer.fit_transform([c["text"] for c in chunks]).tocsr()
        self.columns = self.counts.tocsc()
        self.lengths = np.asarray(self.counts.sum(axis=1)).ravel()
        self.average = max(1, float(self.lengths.mean()))
        self.transformer = TfidfTransformer()
        self.vectors = self.transformer.fit_transform(self.counts)

    def search(self, query, tickers, allowed, method="bm25", limit=20):
        query_vector = self.vectorizer.transform([query])
        if method == "vector":
            scores = (self.vectors @ self.transformer.transform(query_vector).T).toarray().ravel()
        else:
            scores = np.zeros(len(self.chunks))
            for column in query_vector.indices:
                start, end = self.columns.indptr[column : column + 2]
                docs = self.columns.indices[start:end]
                freq = self.columns.data[start:end]
                idf = math.log(1 + (len(self.chunks) - len(docs) + 0.5) / (len(docs) + 0.5))
                scores[docs] += (
                    idf
                    * (freq * 2.5)
                    / (freq + 1.5 * (0.25 + 0.75 * self.lengths[docs] / self.average))
                )
        mask = np.array(
            [c.get("ticker") in tickers and c["document_id"] in allowed for c in self.chunks]
        )
        scores[~mask] = -1
        order = np.argsort(-scores, kind="stable")
        return [hit(self.chunks[i], scores[i]) for i in order[:limit] if scores[i] > 0]


class Retriever:
    def __init__(self, registry=None, online=True):
        self.registry = registry or Registry()
        self.online = online
        self.cache = {}
        self.lock = threading.RLock()
        self.store = None

    def index(self, strategy, selector="active"):
        root = self.registry.root
        files = [root / f"data/chunks/reference/{strategy}.jsonl"]
        if selector != "bundled":
            files += list((root / "data/session").glob(f"*/{strategy}.jsonl"))
        key = (strategy, selector == "bundled")
        existing = [p for p in files if p.exists()]
        signature = tuple((str(p), p.stat().st_mtime_ns) for p in existing)
        with self.lock:
            if key not in self.cache or self.cache[key][0] != signature:
                chunks = [json.loads(line) for p in existing for line in p.read_text().splitlines()]
                if not chunks:
                    raise ValueError("No chunks available for this strategy")
                started = time.perf_counter()
                self.cache[key] = (signature, LocalIndex(chunks))
                event(
                    "retrieval.index_built",
                    strategy=strategy,
                    bundled_only=selector == "bundled",
                    chunks=len(chunks),
                    elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
                )
            return self.cache[key][1]

    def search(
        self,
        query,
        tickers,
        strategy="fixed",
        mode="hybrid",
        selector="active",
        limit=10,
        offline=False,
    ):
        started = time.perf_counter()
        docs = self.registry.documents(selector)
        allowed = {d["document_id"] for d in docs}
        company_docs = {t: {d["document_id"] for d in docs if d["ticker"] == t} for t in tickers}
        index = self.index(strategy, selector)
        local_bm = index.search(query, tickers, allowed, "bm25", 30) if mode != "vector" else []
        vector = []
        backend = "local TF-IDF (lexical vectors)"
        remote_enabled = (
            self.online
            and not offline
            and mode != "offline"
            and strategy in ("fixed", "semantic")
            and bool(os.getenv("PINECONE_API_KEY"))
        )
        if remote_enabled:
            try:
                from .pipeline import normalize_hits
                from .vector_store import PineconeDocumentStore

                if self.store is None:
                    self.store = PineconeDocumentStore()
                for ticker in tickers:
                    company = self.registry.company(ticker)
                    if not company:
                        continue
                    response = self.store.search_documents(
                        f"{company['name']} {query}", strategy, top_k=50
                    )
                    vector.extend(
                        h
                        for h in normalize_hits(response, self.store.field)
                        if h["metadata"].get("document_id") in company_docs[ticker]
                    )
                if vector:
                    backend = "Pinecone dense embeddings"
            except Exception as error:
                event(
                    "retrieval.remote_fallback",
                    level=logging.WARNING,
                    strategy=strategy,
                    error_type=type(error).__name__,
                )
                vector = []
        if not vector:
            vector = index.search(query, tickers, allowed, "vector", 30)
        else:
            missing = [
                t
                for t in tickers
                if not any(h["metadata"].get("document_id") in company_docs[t] for h in vector)
            ]
            if missing:
                vector += index.search(query, missing, allowed, "vector", 30)
                backend += " + local TF-IDF (lexical vectors)"
        results = vector[:limit] if mode == "vector" else rrf([vector, local_bm], limit=limit)
        event(
            "retrieval.completed",
            strategy=strategy,
            mode=mode,
            backend=backend,
            candidates=len(results),
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return results, backend
