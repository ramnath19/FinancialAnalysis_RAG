"""Check local readiness without displaying credentials or making API calls."""

import importlib.util
import json
import os
from pathlib import Path

from .config import load_env


def main():
    load_env()
    required = ["OPENAI_API_KEY", "PINECONE_API_KEY", "PINECONE_INDEX_HOST", "NEBIUS_API_KEY"]
    status = {
        "credentials": {k: bool(os.getenv(k)) for k in required},
        "dependencies": {
            m: bool(importlib.util.find_spec(m))
            for m in [
                "langchain_text_splitters",
                "langchain_experimental",
                "langchain_openai",
                "flashrank",
                "ragas",
                "pinecone",
            ]
        },
        "reference_chunks": {
            s: (Path("data/chunks/reference") / (s + ".jsonl")).exists()
            for s in ["fixed", "semantic"]
        },
    }
    status["semantic_embedding_provider"] = os.getenv(
        "SEMANTIC_EMBEDDING_PROVIDER", os.getenv("EMBEDDING_PROVIDER", "openai")
    )
    status["openai_key_required"] = (
        status["semantic_embedding_provider"] == "openai"
        or os.getenv("RAGAS_JUDGE_PROVIDER", "openai") == "openai"
    )
    print(json.dumps(status, indent=2))
    Path("reports/readiness.json").write_text(json.dumps(status, indent=2) + "\n")
    return status


if __name__ == "__main__":
    main()
