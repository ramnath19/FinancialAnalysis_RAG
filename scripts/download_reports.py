"""Download the explicit public report URLs in the project manifest."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest = ROOT / "data/manifest.json"
    records = json.loads(manifest.read_text())
    for record in records:
        target = manifest.parent / record["path"]
        if not target.exists():
            request = Request(
                record["source_url"], headers={"User-Agent": "FinancialDocumentResearch/1.0"}
            )
            with urlopen(request, timeout=90) as response:
                content = response.read()
                record["resolved_url"] = response.url
            if target.suffix == ".pdf" and not content.startswith(b"%PDF-"):
                raise ValueError(f"Not a PDF: {record['document_id']}")
            if target.suffix == ".html" and b"<html" not in content.lower():
                raise ValueError(f"Not HTML: {record['document_id']}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            record["downloaded_at_utc"] = datetime.now(timezone.utc).isoformat()
        content = target.read_bytes()
        record["sha256"] = hashlib.sha256(content).hexdigest()
        record["size_bytes"] = len(content)
        manifest.write_text(json.dumps(records, indent=2) + "\n")
        print(record["document_id"], len(content), "bytes", flush=True)


if __name__ == "__main__":
    main()
