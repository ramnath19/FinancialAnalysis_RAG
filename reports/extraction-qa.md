# Initial extraction QA

Checked JPMorgan Chase FY2024 PDF pages 206 and 208 against rendered originals.
These correspond to printed pages 172 and 174. Source images are under reports/qa/.

- Income statement page text retained the 2024/2023/2022 column headings, the
  millions unit, the total net revenue row, and parenthesized securities losses.
- Balance sheet page text retained the 2024/2023 headings, asset total row,
  parenthesized allowance for loan losses, and the following footnote.
- PDF page 2 whitespace table detection split several labels and numbers across
  cells. Candidate rows are NOT approved for numerical calculations or independent
  indexing. Page text and surrounding text retain a second representation for review.
- Microsoft's latest earnings-release HTML table retained revenue and income rows,
  period headings, currency-unit heading, percentages, and negative adjustments.
  Merged headers need expansion before treating rows as normalized financial data.

These are spot checks, not a full audit of all extracted pages or tables. Automated
fixture tests check numeric preservation, source locations, stable IDs, HTML boilerplate
removal, and warnings for empty PDF pages. Full financial table normalization remains
an explicit next improvement before chunking table records.

Full run completed on all 13 sources: 3,885 text blocks and 947 table candidates.
The sole empty-page warning is Alphabet FY2025 PDF page 2. Visual inspection
confirmed it is a solid-colour divider page with no visible text. PDF parser colour
warnings were also emitted for Alphabet FY2024; extraction completed successfully.
