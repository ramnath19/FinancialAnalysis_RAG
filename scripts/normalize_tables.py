"""Normalize tables while retaining the first extraction for comparison."""

import json
from pathlib import Path

import pdfplumber

from financial_rag.__main__ import validate_manifest
from financial_rag.extract import evidence, extract_html
from financial_rag.tables import year_column_tables


def main():
    output = Path("data/normalized")
    output.mkdir(parents=True, exist_ok=True)
    summary = []
    for record in validate_manifest("data/manifest.json"):
        source = Path("data") / record["path"]
        original = Path("data/processed") / (record["document_id"] + ".jsonl")
        blocks = [json.loads(line) for line in original.read_text().splitlines()]
        if record["format"] == "html":
            blocks, _ = extract_html(source, record)
        else:
            # Visit pages already containing candidates. Unhandled layouts retain
            # their original candidates with review_required=True.
            pages = {b["location"]["pdf_page"] for b in blocks if b["kind"] == "table"}
            replacements = {}
            with pdfplumber.open(source) as pdf:
                for number in sorted(pages):
                    page = pdf.pages[number - 1]
                    tables = year_column_tables(page)
                    if tables:
                        replacements[number] = [
                            evidence(
                                record,
                                "table",
                                {
                                    "pdf_page": number,
                                    "table_index": i,
                                    "header_top": t["header_top"],
                                },
                                "\n".join(" | ".join(r) for r in t["rows"]),
                                **t,
                            )
                            for i, t in enumerate(tables)
                        ]
                    page.close()
            # Retain original candidates too: normalized tables may omit complex
            # rows or cover only part of a page. Exclude originals from indexing.
            for b in blocks:
                if b["kind"] == "table":
                    b["index_eligible"] = False
            for tables in replacements.values():
                blocks.extend(tables)
        for b in blocks:
            if b["kind"] == "table":
                b["index_eligible"] = False
                if b.get("detection_method") == "explicit_year_columns":
                    page_text = next(
                        x
                        for x in blocks
                        if x["kind"] == "text"
                        and x["location"]["pdf_page"] == b["location"]["pdf_page"]
                    )
                    b["source_text_block_id"] = page_text["block_id"]
                    b["source_page_text"] = page_text["text"]
        (output / (record["document_id"] + ".jsonl")).write_text(
            "".join(json.dumps(b, ensure_ascii=False) + "\n" for b in blocks)
        )
        item = {
            "document_id": record["document_id"],
            "normalized_tables": sum(
                b.get("detection_method") == "explicit_year_columns"
                or b.get("normalization_method") == "expand_html_spans"
                for b in blocks
            ),
            "review_required": True,
        }
        summary.append(item)
        print(item, flush=True)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
