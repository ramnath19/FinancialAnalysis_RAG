import json
import tempfile
import unittest
from pathlib import Path

from financial_rag.__main__ import validate_manifest


class ManifestTests(unittest.TestCase):
    def test_fingerprint_changes_when_source_changes_and_duplicates_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "filing.html"
            source.write_text("Original filing", encoding="utf-8")
            record = dict(
                document_id="demo-2024",
                company="Demo",
                fiscal_year=2024,
                document_type="10-K",
                source_url="https://example.com/filing",
                path="filing.html",
            )
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps([record]), encoding="utf-8")
            first = validate_manifest(manifest)[0]["sha256"]
            source.write_text("Changed filing", encoding="utf-8")
            self.assertNotEqual(first, validate_manifest(manifest)[0]["sha256"])
            manifest.write_text(json.dumps([record, record]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                validate_manifest(manifest)

    def test_missing_file_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text(
                json.dumps(
                    [
                        dict(
                            document_id="demo",
                            company="Demo",
                            fiscal_year=2024,
                            document_type="10-K",
                            source_url="https://example.com",
                            path="missing.html",
                        )
                    ]
                ),
                encoding="utf-8",
            )
            with self.assertRaises(FileNotFoundError):
                validate_manifest(manifest)
