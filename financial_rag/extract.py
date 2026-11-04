"""Extract source-linked evidence from PDF and HTML reports.

Run: python -m financial_rag.extract data/manifest.json
"""

import argparse
import hashlib
import json
import re
from pathlib import Path

from .tables import expand_html_table


def clean(value):
    return re.sub(r"[ \t\u00a0]+", " ", value or "").strip()


def evidence(record, kind, location, text, **extra):
    identity = json.dumps([record["document_id"], kind, location, text], sort_keys=True)
    return {
        "block_id": hashlib.sha256(identity.encode()).hexdigest()[:24],
        "document_id": record["document_id"],
        "company": record["company"],
        "ticker": record.get("ticker"),
        "report_fiscal_year": record["fiscal_year"],
        "report_period_end": record.get("fiscal_period_end"),
        "document_type": record["document_type"],
        "source_url": record["source_url"],
        "source_sha256": record["sha256"],
        "kind": kind,
        "location": location,
        "text": text,
        **extra,
    }


def extract_html(path, record):
    from lxml import html

    root = html.fromstring(Path(path).read_bytes())
    for node in root.xpath("//script|//style|//nav|//header|//footer|//noscript"):
        node.drop_tree()
    blocks, warnings = [], []
    section = None
    # Walk once in document order. Leaf tables avoid duplicate nested table content.
    for index, node in enumerate(root.iter()):
        tag = node.tag.lower() if isinstance(node.tag, str) else ""
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            section = clean(node.text_content())
        if tag == "table" and not node.xpath(".//table"):
            rows, origins = expand_html_table(node)
            if rows:
                spans = bool(node.xpath(".//*[@rowspan or @colspan]"))
                blocks.append(
                    evidence(
                        record,
                        "table",
                        {"element_index": index, "html_id": node.get("id"), "section": section},
                        "\n".join(" | ".join(row) for row in rows),
                        rows=rows,
                        header_rows=[
                            i for i, row in enumerate(node.xpath(".//tr")) if row.xpath("./th")
                        ],
                        raw_html=html.tostring(node, encoding="unicode"),
                        cell_origins=origins,
                        normalization_method="expand_html_spans",
                        review_required=True,
                        merged_cells_present=spans,
                    )
                )
        elif tag in ("p", "li", "h1", "h2", "h3", "h4", "h5", "h6"):
            if node.xpath("ancestor::table") or (tag == "p" and node.xpath("ancestor::li")):
                continue
            text = clean(node.text_content())
            if text:
                blocks.append(
                    evidence(
                        record,
                        "text",
                        {"element_index": index, "html_id": node.get("id"), "section": section},
                        text,
                    )
                )
    if not blocks:
        warnings.append("No supported text blocks found; inspect HTML structure.")
    return blocks, warnings


def extract_pdf(path, record):
    import pdfplumber

    blocks, warnings = [], []
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            text = (page.extract_text(layout=False) or "").strip()
            if not text:
                warnings.append(f"PDF page {number}: no text; may require OCR.")
            else:
                blocks.append(
                    evidence(record, "text", {"pdf_page": number}, text, includes_table_text=True)
                )
            # Financial reports frequently use whitespace rather than grid lines.
            # These are candidate tables: inspection remains required.
            tables = page.find_tables()
            method = "lines"
            if not tables and re.search(
                r"in millions|in billions|income statement|balance sheet|cash flows", text, re.I
            ):
                tables = page.find_tables(
                    table_settings={
                        "vertical_strategy": "text",
                        "horizontal_strategy": "text",
                        "min_words_vertical": 3,
                    }
                )
                method = "text_alignment"
            for index, table in enumerate(tables):
                rows = [[clean(cell) for cell in row] for row in table.extract()]
                rows = [row for row in rows if any(row)]
                if len(rows) < 2 or max(map(len, rows), default=0) < 2:
                    continue
                bbox = list(table.bbox)
                surrounding = (
                    page.crop(
                        (0, max(0, bbox[1] - 80), page.width, min(page.height, bbox[3] + 60))
                    ).extract_text()
                    or ""
                )
                blocks.append(
                    evidence(
                        record,
                        "table",
                        {"pdf_page": number, "table_index": index, "bbox": bbox},
                        "\n".join(" | ".join(row) for row in rows),
                        rows=rows,
                        surrounding_text=surrounding,
                        detection_method=method,
                        review_required=True,
                    )
                )
    return blocks, warnings


def run(manifest_path, output_dir):
    from .__main__ import validate_manifest

    manifest_path = Path(manifest_path).resolve()
    records = validate_manifest(manifest_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    summary = []
    for record in records:
        path = manifest_path.parent / record["path"]
        extractor = {".pdf": extract_pdf, ".html": extract_html}.get(path.suffix.lower())
        if extractor is None:
            raise ValueError(f"Unsupported source format: {path.suffix}")
        blocks, warnings = extractor(path, record)
        destination = output / f"{record['document_id']}.jsonl"
        destination.write_text(
            "".join(json.dumps(block, ensure_ascii=False) + "\n" for block in blocks),
            encoding="utf-8",
        )
        item = {
            "document_id": record["document_id"],
            "text_blocks": sum(b["kind"] == "text" for b in blocks),
            "table_candidates": sum(b["kind"] == "table" for b in blocks),
            "warnings": warnings,
            "output": str(destination.resolve()),
        }
        summary.append(item)
        print(json.dumps(item), flush=True)
    (output / "extraction-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/processed"))
    args = parser.parse_args()
    run(args.manifest, args.output)


if __name__ == "__main__":
    main()
