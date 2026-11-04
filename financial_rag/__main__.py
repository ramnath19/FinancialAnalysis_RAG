"""Validate and fingerprint the exact documents used in an experiment."""

import argparse
import hashlib
import json
from pathlib import Path


def validate_manifest(manifest_path):
    manifest_path = Path(manifest_path).resolve()
    records = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(records, list) or not records:
        raise ValueError("Manifest must contain a nonempty list of documents.")
    seen = set()
    result = []
    for record in records:
        for field in (
            "document_id",
            "company",
            "fiscal_year",
            "document_type",
            "source_url",
            "path",
        ):
            if not record.get(field):
                raise ValueError(f"Missing field: {field}")
        identity = record["document_id"]
        if identity in seen:
            raise ValueError(f"Duplicate document_id: {identity}")
        seen.add(identity)
        year = record["fiscal_year"]
        if type(year) is not int or not 1900 <= year <= 2100:
            raise ValueError(f"Invalid fiscal_year for {identity}")
        path = (manifest_path.parent / record["path"]).resolve()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        result.append({**record, "sha256": digest, "size_bytes": path.stat().st_size})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        records = validate_manifest(args.manifest)
    except (ValueError, OSError, TypeError, AttributeError) as exc:
        parser.exit(1, f"Manifest validation failed: {exc}\n")
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
