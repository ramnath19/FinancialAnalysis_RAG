"""Check normalized columns against source-reviewed JPMorgan statement rows."""

import json
from pathlib import Path

# Reviewed against the rendered original PDF pages, not generated from extraction.
CHECKS = [
    (206, ["2024", "2023", "2022"], "Total net revenue", ["177,556", "158,104", "128,695"]),
    (206, ["2024", "2023", "2022"], "Net income", ["58,471", "49,552", "37,676"]),
    (
        206,
        ["2024", "2023", "2022"],
        "Investment securities losses",
        ["(1,021)", "(3,180)", "(2,380)"],
    ),
    (208, ["2024", "2023"], "Total assets(a)", ["4,002,814", "3,875,393"]),
    (208, ["2024", "2023"], "Allowance for loan losses", ["(24,345)", "(22,420)"]),
]


def main():
    path = Path("data/normalized/jpm-2024-annual.jsonl")
    blocks = [json.loads(line) for line in path.read_text().splitlines()]
    results = []
    for page, years, label, expected in CHECKS:
        tables = [
            b
            for b in blocks
            if b.get("detection_method") == "explicit_year_columns"
            and b["location"]["pdf_page"] == page
            and b["column_years"] == years
        ]
        rows = [row for b in tables for row in b["rows"] if row[0] == label]
        passed = any(row[1:] == expected for row in rows)
        results.append(
            dict(
                pdf_page=page,
                column_years=years,
                label=label,
                expected=expected,
                actual=rows,
                passed=passed,
            )
        )
    Path("reports/table-column-verification.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))
    if not all(r["passed"] for r in results):
        raise SystemExit("Column verification failed")


if __name__ == "__main__":
    main()
