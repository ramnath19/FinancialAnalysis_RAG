# Step 2: extract evidence before chunking

The downloaded dataset contains eight reports for four companies and two fiscal
years (2024 and 2025). Google is represented by its parent, Alphabet Inc.
Six files are PDF; the Microsoft reports are HTML. The raw files are unchanged.
The download script uses fixed URLs rather than a moving latest-report query.

## What ingestion means

Ingestion converts the report into evidence records with text, document ID, company,
fiscal year, source URL, and location. PDF locations use a one-based PDF page number;
the printed report page can differ. HTML locations use section and table identifiers.

Start with JPMorgan Chase 2024. Extract text page by page, then extract financial
tables separately with their headings, column years, units, and footnotes. Inspect
one income statement, one balance sheet, and one risk passage against the original.
Only after those checks pass should we apply the parser to the other seven reports.

## Acceptance checks for the next implementation

- No silent empty pages; report pages requiring OCR.
- Preserve numbers, minus signs, parentheses, percentages, and currency units.
- Retain table column headings with rows, including comparative prior-year columns.
- Exclude navigation and repeated headers from searchable text, while keeping originals.
- Every extracted block has a source location and a stable identifier.
- Keep report fiscal year separate from the periods represented in a table.

The four companies introduce a useful additional challenge: a question about Apple's
revenue must not return a JPMorgan passage that happens to mention Apple. Metadata
filtering and cross-company evaluation questions will test this explicitly.

No embeddings, reranking, or model API calls are needed for this step. PDF and HTML
need separate extraction adapters; both must emit the same evidence-record format.
