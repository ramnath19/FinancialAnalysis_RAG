"""LangChain chunking profile matching the reviewed solution architecture."""

import argparse
import hashlib
import json
import re
import time
from pathlib import Path

from .config import load_env
from .remote_embeddings import configured_embedder


def make_embeddings(cache_dir):
    from langchain_core.embeddings import Embeddings

    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    import os

    remote = configured_embedder(
        os.getenv("SEMANTIC_EMBEDDING_PROVIDER") or None,
        os.getenv("SEMANTIC_EMBEDDING_MODEL") or None,
    )

    class CachedEmbeddings(Embeddings):
        def embed_documents(self, texts):
            results = [None] * len(texts)
            missing = []
            for i, text in enumerate(texts):
                key = hashlib.sha256(
                    (remote.base_url + remote.model_name + text).encode()
                ).hexdigest()
                path = cache_dir / (key + ".json")
                if path.exists():
                    results[i] = json.loads(path.read_text())
                else:
                    missing.append((i, text, path))
            if missing:
                values = remote([x[1] for x in missing])
                for (i, text, path), vector in zip(missing, values):
                    path.write_text(json.dumps(vector))
                    results[i] = vector
            return results

        def embed_query(self, text):
            return self.embed_documents([text])[0]

    return CachedEmbeddings()


def split_block(block, strategy, embeddings=None):
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    if block["kind"] != "text":
        return []
    if strategy == "fixed":
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=512, chunk_overlap=64, add_start_index=True
        )
    else:
        from langchain_experimental.text_splitter import SemanticChunker

        splitter = SemanticChunker(
            embeddings,
            breakpoint_threshold_type="percentile",
            breakpoint_threshold_amount=65,
            add_start_index=True,
        )
    docs = splitter.create_documents([block["text"]])
    pieces = []
    for doc in docs:
        start = doc.metadata["start_index"]
        if start < 0 or block["text"][start : start + len(doc.page_content)] != doc.page_content:
            # SemanticChunker joins sentences with spaces; locate financial evidence
            # using original source ranges rather than claiming synthetic exact offsets.
            # Keep a bounded chunk even when LangChain normalizes whitespace.
            for child in RecursiveCharacterTextSplitter(
                chunk_size=8000, chunk_overlap=100
            ).split_text(doc.page_content):
                pieces.append((child, None, None))
        elif len(doc.page_content) > 8000:
            for child in RecursiveCharacterTextSplitter(
                chunk_size=8000, chunk_overlap=100, add_start_index=True
            ).create_documents([doc.page_content]):
                a = start + child.metadata["start_index"]
                pieces.append((child.page_content, a, a + len(child.page_content)))
        else:
            pieces.append((doc.page_content, start, start + len(doc.page_content)))
    result = []
    for index, (text, start, end) in enumerate(pieces):
        identity = f"{block['block_id']}:{strategy}:reference-v1:{index}:{text}"
        metadata = {
            k: v for k, v in block.items() if k not in ("text", "kind", "includes_table_text")
        }
        result.append(
            {
                **metadata,
                "chunk_id": hashlib.sha256(identity.encode()).hexdigest()[:24],
                "source_block_id": block["block_id"],
                "strategy": strategy,
                "profile": "reference-v1",
                "text": text,
                "start_char": start,
                "end_char": end,
                "exact_source_span": start is not None,
            }
        )
    return result


def main():
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/normalized"))
    parser.add_argument("--output", type=Path, default=Path("data/chunks/reference"))
    parser.add_argument("--strategy", choices=["fixed", "semantic", "both"], default="both")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    summary = []
    for strategy in ["fixed", "semantic"] if args.strategy == "both" else [args.strategy]:
        embeddings = make_embeddings("data/embedding-cache") if strategy == "semantic" else None
        if embeddings is not None:
            # Batch across document boundaries to avoid thousands of tiny remote
            # calls; the cache keys still isolate individual sentence windows.
            from langchain_experimental.text_splitter import combine_sentences

            windows = []
            for p in sorted(args.input.glob("*.jsonl")):
                for line in p.read_text().splitlines():
                    block = json.loads(line)
                    if block["kind"] != "text":
                        continue
                    sentences = re.split(r"(?<=[.?!])\s+", block["text"])
                    if len(sentences) <= 1:
                        continue
                    windows.extend(
                        x["combined_sentence"]
                        for x in combine_sentences(
                            [
                                {"sentence": sentence, "index": i}
                                for i, sentence in enumerate(sentences)
                            ]
                        )
                    )
            for start in range(0, len(windows), 128):
                embeddings.embed_documents(windows[start : start + 128])
                print(
                    f"Cached semantic windows: {min(start + 128, len(windows))}/{len(windows)}",
                    flush=True,
                )
        count = 0
        started = time.perf_counter()
        lengths = []
        temporary = args.output / (strategy + ".jsonl.partial")
        with temporary.open("w") as f:
            for p in sorted(args.input.glob("*.jsonl")):
                for line in p.read_text().splitlines():
                    for c in split_block(json.loads(line), strategy, embeddings):
                        f.write(json.dumps(c, ensure_ascii=False) + "\n")
                        lengths.append(len(c["text"]))
                        count += 1
                print(strategy, p.stem, count, flush=True)
        temporary.replace(args.output / (strategy + ".jsonl"))
        summary.append(
            dict(
                strategy=strategy,
                chunks=count,
                mean_chars=sum(lengths) / count if count else 0,
                elapsed_seconds=time.perf_counter() - started,
            )
        )
        (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
