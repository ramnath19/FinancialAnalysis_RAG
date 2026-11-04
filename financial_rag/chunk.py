"""Fixed-size and embedding-based semantic chunking of extracted evidence."""

import argparse
import hashlib
import json
import math
import os
import re
import time
from pathlib import Path


def fixed_spans(text, size=1800, overlap=200):
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("Require size > 0 and 0 <= overlap < size")
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        yield start, end
        if end == len(text):
            break
        start = end - overlap


def sentence_spans(text):
    # Keep numeric decimals intact; preserve exact source offsets.
    boundaries = (
        [0] + [m.end() for m in re.finditer(r"(?<=[.!?])\s+(?=[A-Z])|\n\s*\n", text)] + [len(text)]
    )
    return [(a, b) for a, b in zip(boundaries, boundaries[1:]) if text[a:b].strip()]


def cosine_distance(a, b):
    if len(a) != len(b) or not a:
        raise ValueError("Invalid embedding dimensions")
    norm = math.sqrt(sum(x * x for x in a) * sum(x * x for x in b))
    if not norm or not all(math.isfinite(x) for x in list(a) + list(b)):
        raise ValueError("Embeddings must be finite and nonzero")
    return 1 - sum(x * y for x, y in zip(a, b)) / norm


def semantic_spans(text, embed, max_size=1800, percentile=80):
    if max_size <= 0 or not 0 <= percentile <= 100:
        raise ValueError("Invalid semantic chunk settings")
    spans = sentence_spans(text)
    if not spans:
        return []
    # Neighbouring sentences supply context for each boundary decision.
    windows = [
        text[spans[max(0, i - 1)][0] : spans[min(len(spans) - 1, i + 1)][1]]
        for i in range(len(spans))
    ]
    vectors = embed(windows)
    if len(vectors) != len(spans):
        raise ValueError("Embedding count does not match sentence count")
    distances = [cosine_distance(vectors[i], vectors[i + 1]) for i in range(len(vectors) - 1)]
    ordered = sorted(distances)
    threshold = (
        ordered[min(len(ordered) - 1, int((len(ordered) - 1) * percentile / 100))]
        if ordered
        else math.inf
    )
    result = []
    start = spans[0][0]
    for i, (a, b) in enumerate(spans):
        if b - start > max_size and a > start:
            result.extend(
                (start + x, start + y) for x, y in fixed_spans(text[start:a], max_size, 0)
            )
            start = a
        if i == len(spans) - 1 or distances[i] > threshold:
            result.extend(
                (start + x, start + y) for x, y in fixed_spans(text[start:b], max_size, 0)
            )
            start = b
    return result


class SentenceEmbedder:
    def __init__(self, model):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model)
        self.model_name = model

    def __call__(self, texts):
        # Avoid silent model truncation by pooling token-safe windows.
        tokenizer = self.model.tokenizer
        budget = self.model.max_seq_length - 2
        parts = []
        groups = []
        for text in texts:
            tokens = tokenizer.encode(text, add_special_tokens=False)
            ids = []
            for start in range(0, len(tokens), budget):
                ids.append(len(parts))
                parts.append(
                    tokenizer.decode(tokens[start : start + budget], skip_special_tokens=True)
                )
            groups.append(ids)
        encoded = self.model.encode(parts, normalize_embeddings=True, show_progress_bar=False)
        return [
            [sum(float(encoded[i][j]) for i in group) / len(group) for j in range(len(encoded[0]))]
            for group in groups
        ]


def chunk_block(block, strategy, embed=None, size=1800, overlap=200, percentile=80):
    if block["kind"] == "table" and not block.get("index_eligible", False):
        return []
    text = block["text"]
    if strategy == "fixed":
        spans = list(fixed_spans(text, size, overlap))
    elif strategy == "semantic":
        if embed is None:
            raise ValueError("Semantic chunking requires an embedding model")
        spans = semantic_spans(text, embed, size, percentile)
    else:
        raise ValueError(f"Unknown strategy: {strategy}")
    result = []
    config = {
        "size_chars": size,
        "overlap_chars": overlap if strategy == "fixed" else 0,
        "percentile": percentile if strategy == "semantic" else None,
        "embedding_model": getattr(embed, "model_name", None) if strategy == "semantic" else None,
    }
    for start, end in spans:
        if not text[start:end].strip():
            continue
        identity = json.dumps([block["block_id"], strategy, config, start, end], sort_keys=True)
        result.append(
            {
                k: block[k]
                for k in (
                    "document_id",
                    "company",
                    "ticker",
                    "report_fiscal_year",
                    "report_period_end",
                    "document_type",
                    "source_url",
                    "source_sha256",
                    "location",
                )
                if k in block
            }
            | {
                "chunk_id": hashlib.sha256(identity.encode()).hexdigest()[:24],
                "source_block_id": block["block_id"],
                "strategy": strategy,
                "config": config,
                "start_char": start,
                "end_char": end,
                "text": text[start:end],
            }
        )
    return result


def main():
    from .config import load_env

    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/normalized"))
    parser.add_argument("--output", type=Path, default=Path("data/chunks"))
    parser.add_argument("--strategy", choices=["fixed", "semantic", "both"], default="both")
    parser.add_argument("--size", type=int, default=1800)
    parser.add_argument("--overlap", type=int, default=200)
    parser.add_argument("--percentile", type=float, default=80)
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--provider",
        choices=["local", "nebius", "openai", "pinecone"],
        default=os.environ.get("EMBEDDING_PROVIDER", "local"),
    )
    args = parser.parse_args()
    args.model = (
        args.model
        or (
            {
                "nebius": os.environ.get("NEBIUS_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B"),
                "openai": os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
                "pinecone": os.environ.get("PINECONE_EMBEDDING_MODEL", "text-embedding-3-small"),
                "local": "sentence-transformers/all-MiniLM-L6-v2",
            }[args.provider]
        )
    )
    if args.provider == "nebius" and not args.model:
        parser.error("Set NEBIUS_EMBEDDING_MODEL or pass --model with your embedding model ID")
    list(fixed_spans("", args.size, args.overlap))
    strategies = ["fixed", "semantic"] if args.strategy == "both" else [args.strategy]
    embed = None
    if "semantic" in strategies:
        if args.provider in ("nebius", "openai", "pinecone"):
            from .remote_embeddings import configured_embedder

            embed = configured_embedder(args.provider, args.model)
        else:
            embed = SentenceEmbedder(args.model)
    sources = sorted(args.input.glob("*.jsonl"))
    if not sources:
        parser.error("No extracted JSONL files found")
    args.output.mkdir(parents=True, exist_ok=True)
    summary = []
    for strategy in strategies:
        started = time.perf_counter()
        count = 0
        lengths = []
        with (args.output / f"{strategy}.jsonl").open("w") as output:
            for path in sources:
                before = count
                for line in path.read_text().splitlines():
                    block = json.loads(line)
                    for chunk in chunk_block(
                        block, strategy, embed, args.size, args.overlap, args.percentile
                    ):
                        output.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                        count += 1
                        lengths.append(len(chunk["text"]))
                print(f"{strategy}: {path.stem}: {count - before} chunks", flush=True)
        summary.append(
            {
                "strategy": strategy,
                "chunks": count,
                "mean_chars": sum(lengths) / count if count else 0,
                "max_chars": max(lengths, default=0),
                "model": args.model if strategy == "semantic" else None,
                "elapsed_seconds": time.perf_counter() - started,
            }
        )
    (args.output / f"summary-{args.strategy}.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
