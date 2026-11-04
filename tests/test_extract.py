import tempfile
import unittest
from pathlib import Path

from financial_rag.extract import extract_html, extract_pdf

RECORD = dict(
    document_id="demo-2025",
    company="Demo",
    ticker="DEMO",
    fiscal_year=2025,
    fiscal_period_end="2025-12-31",
    document_type="annual_report",
    source_url="https://example.com",
    sha256="example",
)


class ExtractionTests(unittest.TestCase):
    def test_html_preserves_numeric_cells_and_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.html"
            path.write_text("""<html><body><nav>Skip navigation</nav>
                <h2>Income statement (USD millions)</h2><p>Net income rose.</p>
                <table><tr><th>Metric</th><th>2025</th><th>2024</th></tr>
                <tr><td>Loss</td><td>(1,234)</td><td>-500</td></tr></table>
                <script>secret noise</script></body></html>""")
            blocks, warnings = extract_html(path, RECORD)
            table = next(b for b in blocks if b["kind"] == "table")
            self.assertEqual(table["rows"][1], ["Loss", "(1,234)", "-500"])
            self.assertIn("USD millions", table["location"]["section"])
            self.assertEqual(table["source_url"], RECORD["source_url"])
            self.assertEqual(table["block_id"], extract_html(path, RECORD)[0][-1]["block_id"])
            self.assertNotIn("Skip navigation", str(blocks))
            self.assertNotIn("secret noise", str(blocks))
            self.assertEqual(warnings, [])

    def test_pdf_table_and_empty_page_warning(self):
        from reportlab.pdfgen import canvas

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.pdf"
            c = canvas.Canvas(str(path))
            c.drawString(50, 760, "Income statement (USD millions)")
            for y in (720, 690, 660):
                c.line(50, y, 350, y)
            for x in (50, 200, 350):
                c.line(x, 660, x, 720)
            c.drawString(60, 700, "Year")
            c.drawString(210, 700, "2025")
            c.drawString(60, 670, "Loss")
            c.drawString(210, 670, "(1,234)")
            c.showPage()
            c.showPage()
            c.save()
            blocks, warnings = extract_pdf(path, RECORD)
            table = next(b for b in blocks if b["kind"] == "table")
            self.assertEqual(table["location"]["pdf_page"], 1)
            self.assertIn("(1,234)", table["text"])
            self.assertTrue(table["review_required"])
            self.assertTrue(any("page 2" in warning for warning in warnings))

    def test_merged_html_headers_remain_aligned(self):
        from lxml import html

        from financial_rag.tables import expand_html_table

        node = html.fromstring("""<table><tr><th rowspan="2">Metric</th>
            <th colspan="2">2025</th></tr><tr><th>GAAP</th><th>Adjusted</th></tr>
            <tr><td>Income</td><td>(100)</td><td>120</td></tr></table>""")
        rows, origins = expand_html_table(node)
        self.assertEqual(
            rows,
            [
                ["Metric", "2025", "2025"],
                ["Metric", "GAAP", "Adjusted"],
                ["Income", "(100)", "120"],
            ],
        )
        self.assertEqual(origins[1][0], origins[0][0])

    def test_year_columns_preserve_numbers_and_reject_ambiguous_rows(self):
        from financial_rag.tables import year_column_tables

        class Page:
            width = 600
            height = 800

            def extract_words(self):
                result = []
                for y, items in [
                    (50, [(400, "2025"), (500, "2024")]),
                    (70, [(20, "Revenue"), (400, "1,234"), (500, "1,100")]),
                    (90, [(20, "Loss"), (400, "(200)"), (500, "(100)")]),
                    (110, [(20, "Income"), (350, "$"), (400, "600"), (450, "$"), (500, "500")]),
                    (130, [(20, "Uncertain"), (400, "abc"), (500, "100")]),
                ]:
                    result.extend(dict(text=t, x0=x, x1=x + 20, top=y) for x, t in items)
                return result

        t = year_column_tables(Page())[0]
        self.assertIn(["Revenue", "1,234", "1,100"], t["rows"])
        self.assertIn(["Loss", "(200)", "(100)"], t["rows"])
        self.assertIn(["Income", "600", "500"], t["rows"])
        self.assertTrue(t["rejected_lines"])
