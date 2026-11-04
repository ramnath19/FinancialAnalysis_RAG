# Financial RAG comparison report

Observed results from the saved development-set run. No reference-kit scores are used.

## Chunking

| Strategy | Chunks | Mean characters | Median | Maximum |
|---|---:|---:|---:|---:|
| fixed | 12570 | 386.9 | 460.0 | 512 |
| semantic | 12277 | 380.2 | 248 | 4559 |

## Retrieval and answer evaluation

| Configuration | Completed | Standard abstentions | Numeric reference presence | Mean seconds | Faithfulness | Context precision | Context recall |
|---|---:|---:|---:|---:|---:|---:|---:|
| fixed-direct | 14/14 | 3 | 0.286 | 1.44 | 0.650 | 0.595 | 0.357 |
| fixed-rerank | 14/14 | 3 | 0.429 | 1.66 | 0.719 | 0.726 | 0.571 |
| semantic-direct | 14/14 | 9 | 0.214 | 1.63 | 0.448 | 0.589 | 0.500 |
| semantic-rerank | 14/14 | 5 | 0.214 | 1.65 | 0.579 | 0.565 | 0.357 |

## Reranking impact

- fixed: answer numeric-reference presence changed by +14.3 percentage points; expected-number presence in selected context changed by +21.4 points.
- semantic: answer numeric-reference presence changed by +0.0 percentage points; expected-number presence in selected context changed by -14.3 points.

These are observed changes on this dataset, not a guarantee that reranking improves every query.
The report deliberately preserves negative and neutral results. Long-passage truncation and loss of year headers are plausible failure modes to investigate, not established explanations.

## Interpretation limits

- Fourteen development questions cover all four companies; this is a small, numeric-heavy set, not a held-out benchmark.
- Expected answers were checked against extracted evidence; a full independent source audit is pending.
- Numeric reference presence checks numeric tokens ignoring commas and trailing zeros, not units, complete reasoning, or equivalent scaled values.
- Fixed chunks use 512 characters/64 overlap. Semantic chunks use a 65th-percentile threshold and an 8000-character ceiling. Size and overlap confound the comparison.
- Semantic boundaries use Pinecone llama-text-embed-v2. Pinecone text-embedding-3-small supplies retrieval embeddings for both strategies.
- Nebius Gemma generates answers and judges RAGAS metrics. Self-judging bias and judge variability apply.
- Both paths retrieve ten candidates, select three passages, and share a 4000-token context budget. FlashRank truncates inputs to 512 tokens.
- PDF page-text extraction still includes table text and may interleave multi-column prose. Separate unverified table candidates remain excluded.
- Reported times include network/model latency and warm caches; they are not controlled latency benchmarks.
- Generation token usage and billed monetary cost were not measured in this run.
- Undefined judge metrics (for example, faithfulness on a complete abstention) are excluded from means; per-metric sample counts are recorded in ragas-summary.json.
- Answers with missing or invalid citation IDs are replaced by explicit abstentions. A completed trial does not imply an answered question.
- Standard-abstention counts include the canonical no-evidence response; additional qualified refusals with citations may also appear.

## Reproduction

Use the installed versions in requirements-lock.txt, the dataset manifest, versioned Pinecone namespaces, and the commands in README.md.
Per-query answers, retrieved passages, and citations are in reports/evaluation/runs.jsonl. Per-query RAGAS scores are saved alongside it.
