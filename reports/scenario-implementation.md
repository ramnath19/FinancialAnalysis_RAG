# Scenario implementation — November 3, 2026

This update implements original project code informed by the Market Buddy README requirements. The reference repository was not executed or source-audited. The earlier `market-buddy-coverage.md` table is the pre-change snapshot; this document records the new state.

## Implemented

- SEC Item-aware paragraph packing, 1,839 bundled chunks, with document/block/page lineage; fixed and embedding-based semantic modes remain available. Heading recognition is heuristic and does not guarantee canonical whole-Item reconstruction in every PDF.
- BM25 + vector reciprocal-rank fusion. Fixed/semantic use Pinecone when available. Section and newly ingested documents currently use local TF-IDF lexical vectors. Backend labels disclose fallbacks; these are not pretrained semantic embeddings.
- Company/year context in the browser session, explicit clarification, basic forecast/out-of-corpus gates, balanced comparisons of up to four companies. New conversation clears context and preserves corpus.
- Topic relevance check, one retrieval retry when no hits, and a LangGraph generation/verification loop with at most two generation calls. This is not the reference's full scope/retrieval state graph or calibrated evidence grader.
- Per-paragraph, citation-scoped literal numeric checks; one regeneration followed by abstention if unsupported numbers remain. This does **not** validate fiscal columns, accounting concepts, unit conversions, scales, calculations, or all nonnumeric claims. A live answer can pass while still containing an incorrect explanation of currency. This limitation remains material.
- Zero-generation-key extractive excerpts using local retrieval. Excerpts retain citations but are not financial conclusions.
- Persistent bundled/session company registry, corpus selection, ticker/CIK lookup, SEC pacing, latest recent 10-K lookup, accession-aware refresh, ingestion progress, cleaned HTML, local fixed/section chunks and SEC company-facts parser. New session filings are not remotely embedded and do not yet support semantic chunking. SEC live access requires a real contact in SEC_USER_AGENT. New-company ingestion and already-current paths passed mocked tests; live SEC ingestion remains unverified. Only recent submissions are searched.
- Candidate annual figures parser and SEC XBRL figures persisted separately. They are **not** used as verified figures-first answers: fiscal-period reconciliation and table-column audit are still needed.
- Chat, Add Company, Chunk Lab, Evaluation and optional Market Context views; evidence cards, resolved-context chip and completed execution trail. Trace is returned after completion, not live streamed. Add-company progress is polled while running.
- Optional delayed history with Yahoo then Stooq fallback, 15-minute cache, source/currency/as-of metadata and graceful unavailable result. Market data never enters filing answers or evaluation. No separate live quote/trending endpoints.
- Process-local per-IP 30/hour and 600/day ask limits; 6/hour and 40/day ingestion starts; 40 registered session-company limit; one ingestion at a time. Server remains localhost-only with serialized answers, not a production multi-worker deployment.

## Verification

34 unit tests pass, covering bounded generation, numeric citation scope, ambiguous/forecast/out-of-corpus cases, follow-up memory, balanced comparisons, source section boundaries, lexical retrieval scope, RRF, registry persistence, mocked SEC ingestion/refresh, cache/fallback, and limits. Existing 23 tests remain included. JavaScript syntax and dependency compatibility checks pass.

Live HTTP checks passed for page delivery, invalid/cross-origin rejection, one Pinecone/Nebius answer, section-based two-company retrieval, prior-year follow-up, and tool endpoints. See `ui-smoke.json` and `ui-expanded-smoke.json`. Browser automation was unavailable; no visual or accessibility audit was completed.

The separate six-way local retrieval experiment uses the same 14 development questions, bundled-only corpus, and expected source-block IDs. It is not a held-out test or dense-vector comparison; a relevant source page can contain multiple metrics.

| Chunking | Retrieval | Rerank | Hit@1 | Hit@5 | MRR@10 |
|---|---|---|---:|---:|---:|
| Fixed | TF-IDF | Off | .071 | .143 | .107 |
| Fixed | TF-IDF + BM25 | Off | .071 | .143 | .124 |
| Fixed | TF-IDF + BM25 | On | .214 | .286 | .250 |
| Section | TF-IDF | Off | .000 | .286 | .107 |
| Section | TF-IDF + BM25 | Off | .214 | .286 | .271 |
| Section | TF-IDF + BM25 | On | .500 | .571 | .524 |

These results support trying section + hybrid + reranking for local retrieval; they do not establish financial-answer correctness or superiority to the saved Pinecone benchmark. Raw trials are in `local-retrieval-comparison.json`; reproduce with `python scripts/evaluate_local_retrieval.py`.

## Remaining gaps

Full company/metric/fiscal-period/unit/scale verification; reconciled figures-first and YoY responses; dense section/session indexing; full conditional scope/retrieve/grade graph; real-time trace streaming; live SEC and market-provider validation; precached Tesla; larger held-out scenario evaluations; production concurrency/distributed quotas; complete quote/trending product features. These are not claimed as covered.
