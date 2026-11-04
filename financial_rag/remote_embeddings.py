"""OpenAI-compatible embedding adapter for a configured Nebius endpoint."""

import json
import os
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class NebiusEmbedder:
    def __init__(self, model, base_url=None):
        self.key = os.environ.get("NEBIUS_API_KEY")
        if not self.key:
            raise ValueError("Set NEBIUS_API_KEY locally before using Nebius embeddings")
        if not model:
            raise ValueError("Specify an embedding model enabled in your Nebius account")
        self.base_url = (
            base_url or os.environ.get("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1")
        ).rstrip("/")
        if not self.base_url.startswith("https://"):
            raise ValueError("Embedding endpoint must use HTTPS")
        self.model_name = model

    def __call__(self, texts):
        vectors = []
        for start in range(0, len(texts), 16):
            batch = texts[start : start + 16]
            body = json.dumps({"model": self.model_name, "input": batch}).encode()
            for attempt in range(4):
                request = Request(
                    self.base_url + "/embeddings",
                    data=body,
                    headers={
                        "Authorization": "Bearer " + self.key,
                        "Content-Type": "application/json",
                    },
                )
                try:
                    with urlopen(request, timeout=90) as response:
                        result = json.load(response)
                    break
                except HTTPError as exc:
                    if exc.code not in (429, 500, 502, 503, 504) or attempt == 3:
                        raise RuntimeError(
                            f"Embedding service returned HTTP {exc.code}; verify endpoint, key, model and input limits"
                        ) from None
                    time.sleep(2**attempt)
            items = sorted(result["data"], key=lambda x: x["index"])
            if [x["index"] for x in items] != list(range(len(batch))):
                raise ValueError("Embedding response indexes do not match requested inputs")
            vectors.extend(x["embedding"] for x in items)
        return vectors


class OpenAIEmbedder(NebiusEmbedder):
    """Use the same validated wire format with OpenAI credentials and endpoint."""

    def __init__(self, model="text-embedding-3-small"):
        self.key = os.environ.get("OPENAI_API_KEY")
        if not self.key:
            raise ValueError("Set OPENAI_API_KEY in your local .env")
        self.base_url = "https://api.openai.com/v1"
        self.model_name = model


def configured_embedder(provider=None, model=None):
    provider = provider or os.environ.get("EMBEDDING_PROVIDER", "openai")
    if provider == "openai":
        return OpenAIEmbedder(
            model or os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        )
    if provider == "nebius":
        return NebiusEmbedder(
            model or os.environ.get("NEBIUS_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B")
        )
    if provider == "pinecone":
        return PineconeEmbedder(
            model or os.environ.get("PINECONE_EMBEDDING_MODEL", "text-embedding-3-small")
        )
    raise ValueError(f"Unsupported embedding provider: {provider}")


class PineconeEmbedder:
    def __init__(self, model="text-embedding-3-small"):
        from pinecone import Pinecone

        key = os.environ.get("PINECONE_API_KEY")
        if not key:
            raise ValueError("Set PINECONE_API_KEY in .env")
        self.client = Pinecone(api_key=key)
        self.model_name = model
        self.base_url = "pinecone-inference"

    def __call__(self, texts):
        from concurrent.futures import ThreadPoolExecutor

        def batch(start):
            from pinecone.errors import PineconeConnectionError, RateLimitError

            for attempt in range(8):
                try:
                    result = self.client.inference.embed(
                        model=self.model_name,
                        inputs=texts[start : start + 32],
                        parameters={"input_type": "passage", "truncate": "NONE"},
                    )
                    return [item["values"] for item in result.to_dict()["data"]]
                except (RateLimitError, PineconeConnectionError):
                    if attempt == 7:
                        raise
                    time.sleep(min(45, 10 * (attempt + 1)))

        with ThreadPoolExecutor(max_workers=4) as executor:
            return [
                vector
                for vectors in executor.map(batch, range(0, len(texts), 32))
                for vector in vectors
            ]
