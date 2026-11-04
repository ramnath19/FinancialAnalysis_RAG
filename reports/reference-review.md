# Reference review

Reviewed 2026-11-03. Reference code was inspected, not executed.

## Sources

- Jev document: https://docs.google.com/document/d/1oJtpCI5vf-DA2KO0g_meGe2hfejSwYSOV9qNKD_QZ08/edit
- Repository: https://github.com/The-Gen-Academy/2B-Financial-RAG-Jev
- Original Word kit preview in the supplied Drive folder: architecture, component
  table, and answer prompt inspected. This was a partial document review.
- Original kit links a second repository:
  https://github.com/The-Gen-Academy/2B-Financial-Document-Intelligence-Pipeline/tree/39d2249c8135d24af99e99d2a6c33488ad2f6dc0
  This second repository has not yet been reviewed.

## Findings from the Jev notebook

- The downloader uses `limit=2`, so the corpus changes as new filings arrive.
- File discovery collects HTML and text files recursively without an explicit
  primary-document selection or content deduplication step.
- Regex stripping flattens HTML structure. Filtering number-heavy chunks can
  discard useful financial evidence.
- Fixed chunks use 512 characters with 64 overlap. Semantic chunk sizes differ;
  a token-window safeguard further splits oversized chunks before indexing.
- Only fixed/no-rerank, semantic/no-rerank, and semantic/rerank are evaluated.
- Ten questions are used, primarily about Apple FY2024. Ground-truth answers
  are embedded in the notebook without evidence passage annotations.
- The saved output reports faithfulness 0.567/0.794/1.000, precision
  0.208/0.617/0.892, and recall 0.550/0.650/0.800. Narrative zero/perfect-score
  claims elsewhere conflict with these outputs. These results were not reproduced.
- Context formatting includes passage text but omits source identifiers from the
  generation prompt, limiting verifiable answer citations.
- Dependency installation is mostly unpinned; saved installation output includes
  a dependency conflict. The workflow is tied to Colab secrets and notebook state.
- The original kit describes BGE embeddings and local FlashRank reranking;
  the Jev variant uses MPNet and TypeSafe API scoring.

## Independent contribution

Build a reproducible four-way experiment with structure-preserving extraction,
source-level relevance labels, held-out questions, numeric/unit checks, source
citations, and measured latency. Avoid presenting reference scores as our results.
