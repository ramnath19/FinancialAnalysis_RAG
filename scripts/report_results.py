"""Build the comparison report only from actual chunk files and evaluation runs."""

import json
import statistics
from pathlib import Path


def main():
    statistics_rows = []
    source = {
        b["block_id"]: b
        for p in Path("data/normalized").glob("*.jsonl")
        for line in p.read_text().splitlines()
        for b in [json.loads(line)]
        if b["kind"] == "text"
    }
    for strategy in ["fixed", "semantic"]:
        path = Path(f"data/chunks/reference/{strategy}.jsonl")
        if not path.exists():
            raise SystemExit(f"Missing chunk output: {strategy}")
        chunks = [json.loads(line) for line in path.read_text().splitlines()]
        for c in chunks:
            original = source[c["source_block_id"]]["text"]
            if c["exact_source_span"]:
                assert original[c["start_char"] : c["end_char"]] == c["text"]
            else:
                assert "".join(c["text"].split()) in "".join(original.split())
        assert {c["source_block_id"] for c in chunks} == set(source)
        lengths = sorted(len(c["text"]) for c in chunks)
        statistics_rows.append(
            dict(
                strategy=strategy,
                chunks=len(chunks),
                documents=len({c["document_id"] for c in chunks}),
                mean_chars=round(statistics.mean(lengths), 1),
                median_chars=statistics.median(lengths),
                p90_chars=lengths[int((len(lengths) - 1) * 0.9)],
                max_chars=max(lengths),
                exact_span_fraction=sum(c["exact_source_span"] for c in chunks) / len(chunks),
            )
        )
    Path("reports/reference-chunk-comparison.json").write_text(
        json.dumps(statistics_rows, indent=2) + "\n"
    )
    scores = json.loads(Path("reports/evaluation/ragas-summary.json").read_text())
    runs = json.loads(Path("reports/evaluation/comparison.json").read_text())
    md = [
        "# Financial RAG comparison report",
        "",
        "Observed results from the saved development-set run. No reference-kit scores are used.",
        "",
        "## Chunking",
        "",
        "| Strategy | Chunks | Mean characters | Median | Maximum |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in statistics_rows:
        md.append(
            f"| {r['strategy']} | {r['chunks']} | {r['mean_chars']} | {r['median_chars']} | {r['max_chars']} |"
        )
    md += [
        "",
        "## Retrieval and answer evaluation",
        "",
        "| Configuration | Completed | Standard abstentions | Numeric reference presence | Mean seconds | Faithfulness | Context precision | Context recall |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in runs:
        score = next(
            (r["scores"] for r in scores if r["configuration"] == row["configuration"]), {}
        )

        def metric(name):
            return f"{score[name]:.3f}" if score.get(name) is not None else "not measured"

        md.append(
            f"| {row['configuration']} | {row['completed']}/{row['questions']} | {row.get('abstentions', 0)} | {row['numeric_reference_presence']:.3f} | {row['mean_seconds']:.2f} | {metric('faithfulness')} | {metric('llm_context_precision_with_reference')} | {metric('context_recall')} |"
        )
    md += ["", "## Reranking impact", ""]
    for strategy in ["fixed", "semantic"]:
        direct = next(r for r in runs if r["configuration"] == strategy + "-direct")
        rerank = next(r for r in runs if r["configuration"] == strategy + "-rerank")
        delta = 100 * (rerank["numeric_reference_presence"] - direct["numeric_reference_presence"])
        evidence_delta = 100 * (
            rerank["reference_number_in_context"] - direct["reference_number_in_context"]
        )
        md.append(
            f"- {strategy}: answer numeric-reference presence changed by {delta:+.1f} percentage points; expected-number presence in selected context changed by {evidence_delta:+.1f} points."
        )
    md += [
        "",
        "These are observed changes on this dataset, not a guarantee that reranking improves every query.",
        "The report deliberately preserves negative and neutral results. Long-passage truncation and loss of year headers are plausible failure modes to investigate, not established explanations.",
    ]
    md += [
        "",
        "## Interpretation limits",
        "",
        "- Fourteen development questions cover all four companies; this is a small, numeric-heavy set, not a held-out benchmark.",
        "- Expected answers were checked against extracted evidence; a full independent source audit is pending.",
        "- Numeric reference presence checks numeric tokens ignoring commas and trailing zeros, not units, complete reasoning, or equivalent scaled values.",
        "- Fixed chunks use 512 characters/64 overlap. Semantic chunks use a 65th-percentile threshold and an 8000-character ceiling. Size and overlap confound the comparison.",
        "- Semantic boundaries use Pinecone llama-text-embed-v2. Pinecone text-embedding-3-small supplies retrieval embeddings for both strategies.",
        "- Nebius Gemma generates answers and judges RAGAS metrics. Self-judging bias and judge variability apply.",
        "- Both paths retrieve ten candidates, select three passages, and share a 4000-token context budget. FlashRank truncates inputs to 512 tokens.",
        "- PDF page-text extraction still includes table text and may interleave multi-column prose. Separate unverified table candidates remain excluded.",
        "- Reported times include network/model latency and warm caches; they are not controlled latency benchmarks.",
        "- Generation token usage and billed monetary cost were not measured in this run.",
        "- Undefined judge metrics (for example, faithfulness on a complete abstention) are excluded from means; per-metric sample counts are recorded in ragas-summary.json.",
        "- Answers with missing or invalid citation IDs are replaced by explicit abstentions. A completed trial does not imply an answered question.",
        "- Standard-abstention counts include the canonical no-evidence response; additional qualified refusals with citations may also appear.",
        "",
        "## Reproduction",
        "",
        "Use the installed versions in requirements-lock.txt, the dataset manifest, versioned Pinecone namespaces, and the commands in README.md.",
        "Per-query answers, retrieved passages, and citations are in reports/evaluation/runs.jsonl. Per-query RAGAS scores are saved alongside it.",
    ]
    Path("reports/final-comparison.md").write_text("\n".join(md) + "\n")
    print(json.dumps(statistics_rows, indent=2))


if __name__ == "__main__":
    main()
