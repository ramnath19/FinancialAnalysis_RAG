"""Pinecone REST adapter for an existing dense-vector index.

Commands: python -m financial_rag.vector_store stats
          python -m financial_rag.vector_store upload --strategy fixed
          python -m financial_rag.vector_store search 'question' --strategy fixed
"""

import argparse
import hashlib
import json
import math
import os
import time
from pathlib import Path
from urllib.request import Request, urlopen

from .config import load_env
from .remote_embeddings import configured_embedder


def vector_metadata(chunk, model):
    metadata = {
        k: v
        for k, v in chunk.items()
        if k
        in (
            "text",
            "document_id",
            "company",
            "ticker",
            "report_fiscal_year",
            "report_period_end",
            "document_type",
            "source_url",
            "source_block_id",
            "strategy",
        )
        and v is not None
    }
    metadata["location_json"] = json.dumps(chunk["location"], sort_keys=True)
    metadata["embedding_model"] = model
    return metadata


class PineconeStore:
    def __init__(self):
        load_env()
        self.key = os.environ.get("PINECONE_API_KEY")
        self.host = os.environ.get("PINECONE_INDEX_HOST", "").removeprefix("https://").rstrip("/")
        if not self.key or not self.host:
            raise ValueError("Set PINECONE_API_KEY and PINECONE_INDEX_HOST in .env")
        if "/" in self.host or not self.host.endswith(".pinecone.io"):
            raise ValueError("Use the index host from your Pinecone console")
        self.prefix = os.environ.get("PINECONE_NAMESPACE_PREFIX", "financial-rag-v1")

    def request(self, path, body):
        req = Request(
            "https://" + self.host + path,
            data=json.dumps(body).encode(),
            headers={
                "Api-Key": self.key,
                "Content-Type": "application/json",
                "X-Pinecone-API-Version": "2025-10",
            },
        )
        with urlopen(req, timeout=90) as response:
            return json.load(response)

    def namespace(self, strategy, model):
        if strategy not in ("fixed", "semantic"):
            raise ValueError("Unknown strategy")
        suffix = hashlib.sha256(model.encode()).hexdigest()[:10]
        return f"{self.prefix}-{strategy}-{suffix}"

    def upload(self, chunks, embed, strategy):
        stats = self.request("/describe_index_stats", {})
        dimension = stats["dimension"]
        namespace = self.namespace(strategy, embed.model_name)
        for start in range(0, len(chunks), 16):
            batch = chunks[start : start + 16]
            if any(c["strategy"] != strategy for c in batch):
                raise ValueError("Chunk strategy mismatch")
            values = embed([c["text"] for c in batch])
            if len(values) != len(batch):
                raise ValueError("Embedding count mismatch")
            if any(len(v) != dimension or not all(math.isfinite(x) for x in v) for v in values):
                raise ValueError("Embedding dimensions do not match the Pinecone index")
            vectors = [
                {"id": c["chunk_id"], "values": v, "metadata": vector_metadata(c, embed.model_name)}
                for c, v in zip(batch, values)
            ]
            self.request("/vectors/upsert", {"namespace": namespace, "vectors": vectors})
        return {"namespace": namespace, "uploaded": len(chunks)}

    def search(self, question, embed, strategy, top_k=5):
        return self.request(
            "/query",
            {
                "namespace": self.namespace(strategy, embed.model_name),
                "vector": embed([question])[0],
                "topK": top_k,
                "includeMetadata": True,
            },
        )


class PineconeDocumentStore(PineconeStore):
    """Support the console's string field with integrated embeddings."""

    def __init__(self):
        super().__init__()
        from pinecone import Pinecone

        self.client = Pinecone(api_key=self.key)
        self.index = self.client.index(host=self.host)
        self.model = os.environ.get("PINECONE_EMBEDDING_MODEL", "text-embedding-3-small")
        self.field = os.environ.get("PINECONE_TEXT_FIELD", "chunk_text")

    def upload_documents(self, chunks, strategy):
        namespace = self.namespace(strategy, self.model)
        for start in range(0, len(chunks), 16):
            documents = []
            for c in chunks[start : start + 16]:
                if c["strategy"] != strategy:
                    raise ValueError("Chunk strategy mismatch")
                metadata = vector_metadata(c, self.model)
                metadata.pop("text", None)
                documents.append(
                    {
                        "_id": c["chunk_id"],
                        self.field: c["text"],
                        "title": c["document_id"],
                        **metadata,
                    }
                )
            self.index.documents.upsert(namespace=namespace, documents=documents)
        return {"namespace": namespace, "uploaded": len(chunks)}

    def search_documents(self, question, strategy, top_k=5):
        from pinecone import EmbedQuery
        from pinecone.errors import PineconeConnectionError

        for attempt in range(3):
            try:
                response = self.index.documents.search(
                    namespace=self.namespace(strategy, self.model),
                    top_k=top_k,
                    score_by=[EmbedQuery(field=self.field, query=question)],
                    include_fields=[
                        self.field,
                        "title",
                        "document_id",
                        "company",
                        "ticker",
                        "report_fiscal_year",
                        "location_json",
                        "source_url",
                        "source_block_id",
                        "document_type",
                        "embedding_model",
                        "strategy",
                    ],
                    timeout=60,
                )
                break
            except PineconeConnectionError:
                if attempt == 2:
                    raise
                time.sleep(2**attempt)
        return response.to_dict()

    def upload_documents_bulk(self, chunks, strategy):
        namespace = self.namespace(strategy, self.model)
        documents = []
        for c in chunks:
            if c["strategy"] != strategy:
                raise ValueError("Chunk strategy mismatch")
            metadata = vector_metadata(c, self.model)
            metadata.pop("text", None)
            documents.append(
                {"_id": c["chunk_id"], self.field: c["text"], "title": c["document_id"], **metadata}
            )
        result = self.index.documents.batch_upsert(
            namespace=namespace,
            documents=documents,
            batch_size=50,
            max_concurrency=4,
            show_progress=True,
            total_timeout=600,
        )
        if result.errors:
            raise RuntimeError(
                f"{len(result.errors)} upload batches failed; rerun with stable IDs to resume"
            )
        return {"namespace": namespace, "uploaded": len(chunks)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["stats", "upload", "search"])
    parser.add_argument("question", nargs="?")
    parser.add_argument("--strategy", choices=["fixed", "semantic"], default="fixed")
    args = parser.parse_args()
    load_env()
    documents = os.environ.get("PINECONE_API_MODE", "vectors") == "documents"
    store = PineconeDocumentStore() if documents else PineconeStore()
    if args.action == "stats":
        result = store.request("/describe_index_stats", {})
    else:
        embed = None if documents else configured_embedder()
        if args.action == "upload":
            directory = Path(os.environ.get("CHUNK_DIR", "data/chunks/reference"))
            chunks = [
                json.loads(line)
                for line in (directory / f"{args.strategy}.jsonl").read_text().splitlines()
            ]
            result = (
                store.upload_documents_bulk(chunks, args.strategy)
                if documents
                else store.upload(chunks, embed, args.strategy)
            )
        else:
            if not args.question:
                parser.error("Provide a search question")
            result = (
                store.search_documents(args.question, args.strategy)
                if documents
                else store.search(args.question, embed, args.strategy)
            )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
