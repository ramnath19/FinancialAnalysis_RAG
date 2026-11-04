# Market Buddy README scenario coverage review

**Pre-change snapshot.** For the implemented changes, test evidence, new six-way results and remaining gaps, read [scenario-implementation.md](scenario-implementation.md).

Source: https://github.com/vtati/market-buddy-rag/blob/main/README.md

Reviewed November 3, 2026 against our current source code and saved runs. The other repository was not executed or source-audited: its feature descriptions and scores are README claims. No implementation was changed by this review.

Covered means implemented in our project; partial means related functionality exists without the full contract or scenario validation. Missing means no matching implementation was found. Different libraries alone are not gaps.

| Scenario | Our status | Finding | Evidence |
|---|---|---|---|
| Public financial-document corpus | Covered | 13 annual-report/earnings sources across JPMorgan, Apple, Alphabet, Microsoft; NVIDIA is not in our corpus. | data/manifest.json |
| SEC Item 1/1A/7/8 selection | Partial | PDF/HTML extraction and some heading metadata exist; no canonical SEC Item map or whole-Item selection. | financial_rag/extract.py |
| Fixed-size chunking | Covered | Recursive 512/64 reference profile; settings differ from their 1000/200 profile. | financial_rag/reference_chunk.py |
| Section-aware chunking | Missing | Embedding-based semantic chunking is implemented, but it is not their Item-aware paragraph packer. | financial_rag/reference_chunk.py |
| Vector retrieval | Covered | Pinecone integrated text-embedding-3-small; FAISS/local BGE is an architectural alternative. | financial_rag/vector_store.py |
| BM25 + vector hybrid / RRF | Missing | No BM25 branch or reciprocal-rank fusion. | financial_rag/vector_store.py |
| CrossEncoder reranking | Covered | FlashRank top10 to top3; L-12 model rather than their L-6 model. | financial_rag/pipeline.py |
| LangGraph conditional workflow | Missing | LCEL generation and ordinary Python orchestration exist; no LangGraph state machine. | financial_rag/pipeline.py |
| Prediction / out-of-corpus scope gate | Missing | No deterministic scope decision before retrieval; prompt-based restraint is insufficient to claim this scenario. | financial_rag/pipeline.py |
| Evidence relevance grade | Missing | Reranking orders candidates, but no calibrated accept/clarify/refuse grading step exists. | financial_rag/pipeline.py |
| Weak-evidence query rewrite and retry | Missing | No bounded query-rewrite loop; network retries are a different mechanism. | financial_rag/pipeline.py |
| Ambiguous question clarification | Missing | No explicit ask-which-company or fiscal-year clarification path. | financial_rag/pipeline.py |
| Multi-turn company/year memory | Missing | UI keeps visible messages only; each API question is independent. | financial_rag/ui.py |
| Balanced cross-company comparison | Partial | All companies are searchable, but global top10 retrieval does not reserve evidence per company. No comparison scenario benchmark. | financial_rag/pipeline.py |
| Cited answers and evidence cards | Covered | Citation IDs, source URLs, page/section locations, expandable passages. Citation presence does not prove claim support. | financial_rag/pipeline.py; financial_rag/web/app.js |
| Verify every answer number against cited evidence | Missing | Offline expected-number presence checks are not a runtime per-claim verifier; units, scales and fiscal periods are not validated. | financial_rag/evaluate.py |
| Regenerate once after failed number verification | Missing | Invalid citation IDs cause a safe abstention; no numeric verification/regeneration loop. | financial_rag/pipeline.py |
| Insufficient-evidence refusal | Partial | Prompted abstention and invalid-citation fallback exist. No deterministic relevance gate or negative-query evaluation set. | financial_rag/pipeline.py |
| SEC company-facts figures table | Missing | No structured XBRL company-facts dataset or reconciled fiscal-period figures table. | data/manifest.json |
| Figures-first performance / YoY headline | Missing | No deterministic headline construction or YoY arithmetic verification. | financial_rag/pipeline.py |
| Provider-pluggable answer generation | Partial | Nebius generation works and embedding providers are configurable; no explicit multi-provider generation selector. | financial_rag/remote_embeddings.py; financial_rag/pipeline.py |
| Zero-key extractive generation | Missing | Current route needs Pinecone and Nebius keys. No separate OpenAI key is needed, which is not the same as zero keys. | financial_rag/pipeline.py |
| Add any company at runtime | Missing | Downloader uses fixed manifest URLs; no runtime ticker resolver or ingestion job API. | scripts/download_reports.py |
| Ticker/CIK resolution and SEC pacing | Missing | No SEC company-map resolver, accession-aware fetcher or SEC-specific fair-access pacing. | scripts/download_reports.py |
| Latest filing refresh / already-current response | Missing | Frozen source URLs are reproducible, but do not discover newer filings. | scripts/download_reports.py |
| Persistent bundled/session registry and corpus selector | Missing | Files and vectors persist; no dynamic active/bundled/ticker registry or scope selection. | financial_rag/ui.py; financial_rag/vector_store.py |
| Precached new-company ingestion demo | Missing | No Tesla precache or refuse → ingest → answer scenario. | data/manifest.json |
| Chat UI with retrieval controls | Covered | Local web page, fixed/semantic selection, reranking toggle, example questions and source cards. | financial_rag/web/index.html |
| Live execution trace / context chip | Missing | A loading message and final timing exist; no per-stage stream or resolved conversation context chip. | financial_rag/web/app.js |
| Add-company UI / ingestion visualizer | Missing | No add-company screen or stage-by-stage ingestion job display. | financial_rag/web/index.html |
| Chunking Lab / evaluation dashboard | Missing | Saved reports exist, but no corresponding interactive UI pages. | reports/final-comparison.md |
| Market strip, quotes, charts, trending | Missing | No market-data integrations; optional expansion beyond the original financial RAG deliverable. | financial_rag/ui.py |
| Market fallback/cache/unavailable behaviour | Missing | No Yahoo/Stooq adapters or delayed/as_of market payloads. | financial_rag/ui.py |
| Measured chunking/reranking comparison | Covered | Four configurations, 14 shared development queries, 56 answer trials, 168 RAGAS metric scores. | reports/evaluation/ragas-summary.json |
| Hit@k and MRR retrieval experiments | Missing | RAGAS context metrics exist, but no section-labelled Hit@k/MRR benchmark or hybrid six-way matrix. | financial_rag/evaluate.py |
| Ambiguous/unanswerable/follow-up/forecast scenario evaluation | Missing | Current questions are numeric-heavy development queries; local guard unit tests do not establish full scenario coverage. | data/evaluation/development.json; tests/test_pipeline.py |
| Corpus isolation for benchmark after runtime ingestion | Partial | Versioned namespaces and dataset hashes exist; no session ingestion layer to test against benchmark isolation. | reports/run-manifest.json |
| Public-demo quotas, daily cap and ingest cap | Missing | Local loopback binding, Origin checks and a request lock exist; these are not public API quotas or per-IP limits. | financial_rag/ui.py |
| Reproducible artifacts, dependency lock, provenance | Covered | Source hashes, dependency lock, saved runs and generated comparison report. | reports/run-manifest.json; requirements-lock.txt |

## Priority order

1. Runtime numeric verification with company, fiscal period, units and scale; allow a bounded regeneration attempt before refusing.
2. Deterministic company/year scope and conversation contextualization; clarify ambiguous questions and balance evidence across companies for comparisons.
3. Relevance grading, one query rewrite, and explicit out-of-corpus/forecast refusals; add negative and follow-up scenarios to evaluation.
4. SEC Item-aware chunking and a BM25/RRF experiment, measured with source/section-labelled Hit@k and MRR alongside RAGAS.
5. Structured SEC company-facts figures and verified YoY calculations.
6. Runtime company ingestion and accession-aware refresh, followed by a corpus registry and benchmark isolation tests.
7. UI trace, comparison dashboard, and ingestion progress. Add market widgets and public-demo quotas only if those deployment/product scenarios are wanted.

## Current empirical limits

Our best development configuration is fixed-size plus reranking: context precision 0.726, recall 0.571, and expected numeric-token presence 6/14. Numeric-token presence is not financial correctness. A larger independently reviewed, held-out scenario set is needed. The other README reports a different corpus, algorithms, metrics and evaluation mode; its stated 20/20 cannot be compared directly with our 56 answer trials.

The other README also describes its evaluation as 18 questions while reporting 20/20. That counting discrepancy needs its evaluation code/results checked before citing its coverage total.
