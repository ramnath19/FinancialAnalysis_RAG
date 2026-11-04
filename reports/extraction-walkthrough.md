# Extraction walkthrough

## 1. Validate the inputs

`run()` reads the manifest and calls the existing manifest validator. Every source
must exist. Its SHA-256 fingerprint is recomputed and attached to each output block.
This identifies the exact file used, rather than relying on a filename alone.

## 2. Choose a reader

PDF sources use pdfplumber. HTML sources use lxml. Both adapters return evidence
blocks in the same format, so later chunking code does not need to know the format.

## 3. Read PDF pages

Each page produces a text block with a one-based PDF page number. Printed report
page numbers may differ. Empty pages are recorded as warnings; OCR is not implemented.
Text is not filtered by alphabetic content, so numeric evidence is retained.

The reader first looks for table rules (lines). On pages mentioning common financial
statement terms, it also tries whitespace alignment if no ruled table was found.
Each candidate table retains its rows, bounding box, nearby text, and detection method.
Nearby text can help recover titles, units, years, or footnotes, but these are not yet
parsed into verified fields. Tables continuing across pages are not joined yet.

PDF page text includes table text as well as separate candidate table records. This
is intentional for inspection. Before indexing, the chunking stage must choose a
representation or remove overlaps so duplicate evidence does not bias retrieval.
Repeated PDF headers and footers remain in this first extraction pass.

## 4. Read HTML in document order

The reader removes scripts, styles, and common navigation containers, then collects
headings, paragraphs, list items, and leaf tables. It attaches the most recent heading,
HTML element ID when available, and an element index. Table cell strings preserve
signs, parentheses, percentages, and years. Original table markup is retained for
review. Merged cells are flagged; this version does not expand rowspan/colspan.
CSS-only visibility and every possible layout container are not handled yet.

## 5. Save evidence

Each report gets a JSONL file in data/processed: one JSON object per line.
The extraction-summary.json file records text counts, table-candidate counts,
and warnings. IDs are stable for unchanged inputs and extraction behavior.
`report_fiscal_year` identifies the report; it does not assign that year to all
numbers inside a comparative table.

## 6. Inspect before chunking

Check an income statement, balance sheet, and risk passage from JPMorgan 2024.
Compare years, currency units, negative signs, and footnotes to the original page.
Table candidates need review: whitespace detection can mistake prose for a table,
and can miss unruled tables on pages without the configured trigger phrases.
Do not treat table counts as a quality score or these candidates as verified facts.

## Run locally

Use a project virtual environment with the extraction requirements installed:

```sh
python -m pip install -r requirements-extraction.txt
python -m financial_rag.extract data/manifest.json
```

For tests, install requirements-dev.txt and run:

```sh
python -m unittest discover -s tests -v
```

The execution in this chat uses the bundled Python 3.12 environment. The system
Python is 3.15; dependency compatibility there has not been tested. No model keys
or external AI service are used during extraction.
