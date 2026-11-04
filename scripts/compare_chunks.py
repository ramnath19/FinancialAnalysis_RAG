"""Validate chunk provenance and compare size/coverage for both strategies."""

import csv
import json
from collections import defaultdict
from pathlib import Path


def main():
    sources = {
        b["block_id"]: b
        for p in Path("data/normalized").glob("*.jsonl")
        for line in p.read_text().splitlines()
        for b in [json.loads(line)]
        if b["kind"] == "text"
    }
    results = []
    for strategy in ["fixed", "semantic"]:
        chunks = [
            json.loads(line)
            for line in Path(f"data/chunks/{strategy}.jsonl").read_text().splitlines()
        ]
        grouped = defaultdict(list)
        for c in chunks:
            source = sources[c["source_block_id"]]
            assert c["text"] == source["text"][c["start_char"] : c["end_char"]]
            assert len(c["text"]) <= 1800
            assert c["location"] == source["location"]
            grouped[c["document_id"]].append(c)
        assert {c["source_block_id"] for c in chunks} == set(sources)
        for doc, cs in grouped.items():
            lengths = sorted(len(c["text"]) for c in cs)
            source_chars = sum(len(b["text"]) for b in sources.values() if b["document_id"] == doc)
            # Check complete coverage of non-whitespace source content.
            by_block = defaultdict(list)
            for c in cs:
                by_block[c["source_block_id"]].append((c["start_char"], c["end_char"]))
            for bid, spans in by_block.items():
                text = sources[bid]["text"]
                end = 0
                for a, b in sorted(spans):
                    assert not text[end:a].strip(), (bid, end, a)
                    end = max(end, b)
                assert not text[end:].strip()
            results.append(
                dict(
                    document_id=doc,
                    strategy=strategy,
                    chunks=len(cs),
                    mean_chars=round(sum(lengths) / len(lengths), 1),
                    median_chars=lengths[len(lengths) // 2],
                    p90_chars=lengths[int((len(lengths) - 1) * 0.9)],
                    max_chars=max(lengths),
                    below_200_chars=sum(x < 200 for x in lengths),
                    character_volume_ratio=round(sum(lengths) / source_chars, 3),
                )
            )
    Path("reports/chunk-comparison.json").write_text(json.dumps(results, indent=2) + "\n")
    with Path("reports/chunk-comparison.csv").open("w") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0]))
        w.writeheader()
        w.writerows(results)
    for strategy in ["fixed", "semantic"]:
        rows = [r for r in results if r["strategy"] == strategy]
        print(strategy, "chunks", sum(r["chunks"] for r in rows), "documents", len(rows))
    print(
        "Verified exact offsets, metadata, size limits, and non-whitespace coverage for all source text blocks."
    )


if __name__ == "__main__":
    main()
