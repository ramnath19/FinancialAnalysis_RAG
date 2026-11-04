"""Traceable annual figures from checked table layouts or SEC company facts."""

import json
import re
from decimal import Decimal
from pathlib import Path

from .registry import ROOT, atomic_json

METRICS = {
    "revenue": r"(?:Total net sales|Total net revenue|Revenues|Revenue)",
    "net_income": r"Net income",
    "operating_income": r"(?:Operating income|Income from operations)",
}
TAGS = {
    "revenue": [
        "RevenuesNetOfInterestExpense",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "Revenues",
    ],
    "net_income": ["NetIncomeLoss"],
    "operating_income": ["OperatingIncomeLoss"],
}


def bootstrap(root=ROOT):
    figures = {}
    for path in sorted((Path(root) / "data/normalized").glob("*annual.jsonl")):
        for line in path.read_text().splitlines():
            b = json.loads(line)
            text = b["text"]
            if "million" not in text.lower():
                continue
            if b["kind"] == "text" and not re.search(
                r"consolidated statements of (?:income|operations)|financial highlights", text, re.I
            ):
                continue
            if b["kind"] == "table":
                rows = b.get("rows", [])
                headers = []
                for row in rows[:8]:
                    found = [
                        (i, int(cell.strip()))
                        for i, cell in enumerate(row)
                        if re.fullmatch(r"20\d{2}", cell.strip())
                    ]
                    if len({y for i, y in found}) >= 2:
                        headers = found
                        break
                if not headers:
                    continue
                for row in rows:
                    for metric, pattern in METRICS.items():
                        if not row or not re.fullmatch(pattern, row[0].strip(), re.I):
                            continue
                        for col, year in headers:
                            if col >= len(row):
                                continue
                            value = re.fullmatch(
                                r"\$?\s*(\(?[\d,]+(?:\.\d+)?\)?)", row[col].strip()
                            )
                            if value:
                                put(figures, b, metric, year, value.group(1))
            else:
                headers = []
                for header in text.splitlines()[:12]:
                    match = re.search(r"(20\d{2}(?:\s+20\d{2}){1,3})\s*$", header)
                    if match:
                        headers = [int(x) for x in match.group(1).split()]
                        break
                if not headers:
                    continue
                for row in text.splitlines():
                    for metric, pattern in METRICS.items():
                        match = re.match("^" + pattern + r"\s+(.*)$", row, re.I)
                        if not match:
                            continue
                        values = re.findall(r"\(?-?\d[\d,]*(?:\.\d+)?\)?", match.group(1))
                        if len(values) == len(headers):
                            for year, value in zip(headers, values):
                                put(figures, b, metric, year, value)
    rows = list(figures.values())
    atomic_json(Path(root) / "data/figures/bundled.json", rows)
    return rows


def put(figures, block, metric, year, value):
    signed = value.replace(",", "")
    signed = "-" + signed[1:-1] if signed.startswith("(") else signed
    key = (block["ticker"], metric, year)
    row = {
        "ticker": block["ticker"],
        "company": block["company"],
        "metric": metric,
        "fiscal_year": year,
        "value_usd": str(Decimal(signed) * 1000000),
        "reported_value": value,
        "reported_unit": "USD millions",
        "source_type": "annual_table",
        "document_id": block["document_id"],
        "source_url": block["source_url"],
        "source_location": block["location"],
        "source_block_id": block["block_id"],
        "report_fiscal_year": block["report_fiscal_year"],
    }
    if key not in figures or figures[key]["report_fiscal_year"] < row["report_fiscal_year"]:
        figures[key] = row


def from_company_facts(payload, ticker, company):
    from datetime import date

    result = []
    facts = payload.get("facts", {}).get("us-gaap", {})
    for metric, tags in TAGS.items():
        # Revenue tags are not universally interchangeable; net interest revenue
        # takes priority for banks, while a chosen tag is retained for audit.
        selected = next((tag for tag in tags if tag in facts), None)
        if not selected:
            continue
        grouped = {}
        for row in facts[selected].get("units", {}).get("USD", []):
            if (
                row.get("form") not in ("10-K", "10-K/A")
                or not row.get("start")
                or not row.get("end")
            ):
                continue
            duration = (date.fromisoformat(row["end"]) - date.fromisoformat(row["start"])).days
            if not 300 <= duration <= 400:
                continue
            period = row["end"]
            old = grouped.get(period)
            if old is None or row.get("filed", "") > old.get("filed", ""):
                grouped[period] = row
        for end, row in grouped.items():
            accession = row.get("accn", "")
            result.append(
                {
                    "ticker": ticker,
                    "company": company,
                    "metric": metric,
                    "fiscal_year": int(end[:4]),
                    "period_end": end,
                    "reported_fy": row.get("fy"),
                    "value_usd": str(row["val"]),
                    "reported_value": str(row["val"]),
                    "reported_unit": "USD",
                    "source_type": "sec_company_facts",
                    "tag": selected,
                    "accession": accession,
                    "source_url": f"https://www.sec.gov/Archives/edgar/data/{payload.get('cik')}/{accession.replace('-', '')}/",
                    "document_id": ticker.lower() + "-" + end + "-facts",
                    "source_location": {"period_end": end, "tag": selected},
                }
            )
    return result


class Figures:
    def __init__(self, root=ROOT):
        self.root = Path(root)

    def rows(self, selector="active"):
        path = self.root / "data/figures/bundled.json"
        rows = json.loads(path.read_text()) if path.exists() else []
        if selector != "bundled":
            for p in (self.root / "data/session").glob("*/figures.json"):
                rows += json.loads(p.read_text())
        if selector not in ("active", "bundled"):
            rows = [r for r in rows if r["ticker"] == selector]
        return rows

    def get(self, ticker, metric, year, selector="active"):
        rows = [
            r
            for r in self.rows(selector)
            if r["ticker"] == ticker and r["metric"] == metric and r["fiscal_year"] == year
        ]
        return (
            max(rows, key=lambda r: r.get("source_type") == "sec_company_facts") if rows else None
        )

    def latest_year(self, ticker, selector="active"):
        years = [r["fiscal_year"] for r in self.rows(selector) if r["ticker"] == ticker]
        return max(years) if years else None


def evidence(row):
    text = f"{row['company']} reported {row['metric'].replace('_', ' ')} of {row['value_usd']} USD for the annual period ending in {row['fiscal_year']}."
    return {
        "id": row.get("source_block_id", row["document_id"])
        + "-"
        + row["metric"]
        + "-"
        + str(row["fiscal_year"]),
        "text": text,
        "metadata": {
            "company": row["company"],
            "ticker": row["ticker"],
            "report_fiscal_year": row["fiscal_year"],
            "document_id": row["document_id"],
            "location_json": json.dumps(row["source_location"]),
            "source_url": row["source_url"],
            "figure": row,
        },
    }


if __name__ == "__main__":
    print("Annual figures:", len(bootstrap()))
