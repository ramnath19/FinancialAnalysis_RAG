"""Reproduce chunking, uploads and evaluation using configured project services."""

import argparse
import os
import subprocess
import sys

from financial_rag.config import load_env


def main():
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reuse-chunks", action="store_true")
    parser.add_argument("--skip-upload", action="store_true")
    args = parser.parse_args()
    missing = [
        key
        for key in ["PINECONE_API_KEY", "PINECONE_INDEX_HOST", "NEBIUS_API_KEY"]
        if not os.getenv(key)
    ]
    if os.getenv("SEMANTIC_EMBEDDING_PROVIDER", "openai") == "openai" and not os.getenv(
        "OPENAI_API_KEY"
    ):
        missing.append("OPENAI_API_KEY")
    if missing:
        raise SystemExit("Missing local settings: " + ", ".join(missing))

    def run(module, *arguments):
        subprocess.run([sys.executable, "-m", module, *arguments], check=True)

    if not args.reuse_chunks:
        run("financial_rag.reference_chunk", "--strategy", "both")
    if not args.skip_upload:
        for strategy in ["fixed", "semantic"]:
            run("financial_rag.vector_store", "upload", "--strategy", strategy)
    run("financial_rag.evaluate", "--resume", "--ragas")
    run("scripts.report_results")


if __name__ == "__main__":
    main()
