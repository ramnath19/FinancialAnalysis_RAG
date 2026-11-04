# Refactor review — November 3, 2026

## Changes

- Removed unused imports and normalized Python formatting/import ordering across package, scripts and tests. Added Ruff configuration and a pinned development dependency for repeatable maintenance. Preserved the extraction/chunking experiments and saved benchmarks because they are still used by CLI commands and comparison reports.
- Split HTTP routing from validated request objects and workspace read models. Consolidated duplicated validation, centralized static routes, and cached chunk statistics by file signature. Chunk inspection now streams files and keeps only three samples, rather than retaining every chunk in memory on each request.
- Added safe structured JSON logging, correlated request/job IDs, endpoint timing, index-build/retrieval timing, remote fallback events, generation/verification outcomes, ingestion stages and market fallback/cache events. Console and private rotating files share the formatter. Exception records omit provider messages and source-code lines; configured secrets are redacted before JSON serialization, including nested fields and multiline values.
- Replaced silent Pinecone fallback with an observable event. Section retrieval avoids attempting an unsupported remote namespace. Local-only retrieval respects vector-versus-hybrid selection. Mixed dense/lexical retrieval has an accurate backend label. Retriever paths now honor its registry root, improving isolation in tests and alternate workspaces.
- Registry persistence uses unique temporary files and atomic publication; concurrent registry updates share a process lock. Failed publication preserves the previous file. Ingestion uses atomic file publication, synchronized progress snapshots, bounded recent job retention and background-job correlation IDs. The previous fiscal/unit verification limitations remain.
- Rebuilt the UI into separate views and consolidated its CSS rather than appending more overrides. Added active navigation, responsive layouts, light/dark themes, answer copy, explicit conversation export, evidence filter/expand, accurate response-status labels, request references, service configuration state, character count, native progress bars, recent ingestion jobs and delayed-price observation tables. There are shared API/error helpers and bounded request waits. Navigation aborts obsolete tool-view requests and stops abandoned polling. Conversation content is not placed in localStorage.

## Verification

42 unit tests pass. New regression coverage includes malformed settings/context, chunk-cache invalidation, failed atomic publication, JSON log redaction/correlation, exception-message privacy, handler idempotence, permissions after rotation, remote retrieval failure and respecting local vector-only mode.

Ruff lint and formatting checks, JavaScript syntax checks, and dependency compatibility checks pass. The expanded HTTP smoke checks pass for static assets, API request IDs, malformed JSON, cross-origin rejection, scope/refusal, balanced comparisons, follow-up years, chunk inspection, jobs, evaluation, ticker validation and one live Pinecone/Nebius answer. Saved result: `reports/ui-refactor-smoke.json`.

A log audit confirmed valid JSON lines, generation/retrieval events, private permissions, and no configured API keys, SEC contact identity or smoke-test prompts in the generated file. This is a targeted check, not a guarantee against every possible secret format.

Browser access was unavailable. Visual layout, clipboard/download interaction, keyboard navigation and screen-reader behavior still need an actual browser review. The code includes semantic labels, live status/error regions, table captions, visible focus and reduced-motion support, but those are not claimed as an accessibility certification.

No new financial-answer quality scores are claimed by this refactor. Existing benchmarks remain unchanged and are still development-set measurements. Live SEC filing ingestion was not triggered during this cleanup; existing mock tests and the earlier metadata-access check do not establish end-to-end filing ingestion quality.
