# Table normalization, step by step

1. Preserve original evidence in data/processed. New results go into data/normalized.
2. Expand HTML rowspan/colspan into a rectangular grid. Record each cell's origin,
   so repeated year headings and GAAP/adjusted headings can be traced to the markup.
3. For PDF candidate pages, locate lines with two to four distinct year headings.
   Use their positions as column anchors. Assign whole words to those columns;
   do not use every text alignment as a new vertical border.
4. Accounting dollar signs occupy separate gutters. Keep them in source_lines and
   currency_symbols while retaining financial value strings without those gutters.
5. Accept only labeled rows with a recognized numeric value in every year column.
   Keep rejected lines and original candidate tables. Missing values, wrapped labels,
   non-year columns, mixed units, and complicated layouts still need review.
6. Verify against independently source-reviewed rows on JPMorgan PDF pages 206 and
   208. The verification script compares both year order and exact value strings,
   including commas and parentheses. All five checks pass; this is a sampled check,
   not a certification of every report or table.
7. Keep index_eligible=false for all table records until review covers their complete
   headers, units, row labels, footnotes, and values. Text blocks remain available.
   Original and normalized table representations must not both enter retrieval.

Run after the initial extraction, from the project directory:

```sh
python -m scripts.normalize_tables
python -m scripts.verify_table_columns
python -m unittest discover -s tests -v
```

Dependencies are the same as extraction. Six tests cover spans, numeric preservation,
ambiguous-row rejection, provenance, and original extraction behavior. The normalizer
operates only on pages with candidates from the first pass; missed tables can still
require additional detection. It does not join tables across pages or infer units.
The full original page text remains the source for unit and footnote review.
