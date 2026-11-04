"""Conservative table normalization; ambiguous tables remain reviewable."""

import re


def expand_html_table(node):
    """Expand HTML spans into a rectangular grid, retaining cell provenance."""
    grid, origins = [], []
    occupied = {}
    for ri, row in enumerate(node.xpath(".//tr")):
        ci = 0
        for cell in row.xpath("./th|./td"):
            while (ri, ci) in occupied:
                ci += 1
            text = " ".join(cell.text_content().split())
            height = max(1, int(cell.get("rowspan", "1")))
            width = max(1, int(cell.get("colspan", "1")))
            if height > 1000 or width > 1000:
                raise ValueError("Unreasonable HTML table span")
            for dr in range(height):
                for dc in range(width):
                    key = (ri + dr, ci + dc)
                    if key in occupied:
                        raise ValueError("Overlapping HTML table spans")
                    occupied[key] = (text, [ri, ci])
            ci += width
    if not occupied:
        return [], []
    height = max(r for r, c in occupied) + 1
    width = max(c for r, c in occupied) + 1
    for ri in range(height):
        grid.append([occupied.get((ri, ci), ("", None))[0] for ci in range(width)])
        origins.append([occupied.get((ri, ci), ("", None))[1] for ci in range(width)])
    return grid, origins


def lines_from_words(words):
    lines = []
    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if not lines or abs(word["top"] - lines[-1][0]["top"]) > 3:
            lines.append([word])
        else:
            lines[-1].append(word)
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


VALUE = re.compile(r"^(?:\$\s*)?(?:\(?-?\d[\d,]*(?:\.\d+)?\)?|[—–-])\s*%?(?:\s*\([a-z]\))?$")


def year_column_tables(page):
    """Use explicit year headings as column anchors; never split numeric words.

    This adapter deliberately accepts only rows with a label and one valid value
    per year. Unaccepted rows remain available in original page/table evidence.
    """
    lines = lines_from_words(page.extract_words())
    headers = []
    for i, line in enumerate(lines):
        years = [w for w in line if re.fullmatch(r"20\d{2}", w["text"])]
        if 2 <= len(years) <= 4 and len({w["text"] for w in years}) == len(years):
            # Prose containing years is not a table heading.
            if all(w["text"].isdigit() or w["x1"] < years[0]["x0"] for w in line):
                headers.append((i, years))
    result = []
    for hi, (start, years) in enumerate(headers):
        stop = headers[hi + 1][0] if hi + 1 < len(headers) else len(lines)
        centers = [(w["x0"] + w["x1"]) / 2 for w in years]
        boundaries = [years[0]["x0"] - (centers[1] - centers[0]) / 2]
        boundaries += [(centers[i - 1] + centers[i]) / 2 for i in range(1, len(centers))]
        rows, rejected = [], []
        for line in lines[start + 1 : stop]:
            if line[0]["top"] > page.height - 35:
                continue
            # Accounting-style dollar signs sit in their own gutter and can fall
            # across a midpoint. Preserve them in source lines, not value columns.
            value_line = [w for w in line if w["text"] != "$"]
            label = " ".join(
                w["text"] for w in value_line if (w["x0"] + w["x1"]) / 2 < boundaries[0]
            )
            cells = []
            for col, left in enumerate(boundaries):
                right = boundaries[col + 1] if col + 1 < len(boundaries) else page.width
                cells.append(
                    " ".join(
                        w["text"] for w in value_line if left <= (w["x0"] + w["x1"]) / 2 < right
                    )
                )
            if label and all(VALUE.fullmatch(cell) for cell in cells):
                rows.append([label] + cells)
            elif any(cells):
                rejected.append(" ".join(w["text"] for w in line))
        if len(rows) >= 3:
            result.append(
                {
                    "rows": [["Metric"] + [w["text"] for w in years]] + rows,
                    "column_years": [w["text"] for w in years],
                    "header_top": years[0]["top"],
                    "column_boundaries": boundaries,
                    "source_lines": [
                        " ".join(w["text"] for w in line) for line in lines[start:stop]
                    ],
                    "currency_symbols": [
                        w["text"] for line in lines[start:stop] for w in line if w["text"] == "$"
                    ],
                    "rejected_lines": rejected,
                    "review_required": True,
                    "verification_status": "structurally_checked; source review required",
                    "detection_method": "explicit_year_columns",
                }
            )
    return result
