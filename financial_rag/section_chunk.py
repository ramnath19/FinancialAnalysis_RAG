"""SEC Item-aware paragraph packing with section boundaries and source lineage."""

import hashlib
import json
import re
from pathlib import Path

ITEM = re.compile(
    r"(?im)^\s*(?:item\s*)(1a|1b|1c|7a|1|2|3|4|5|6|7|8|9a|9b|9|10|11|12|13|14|15|16)\s*[.：:]?\s+(?=[A-Za-z])"
)
FOOTER = re.compile(
    r"^(?:JPMorgan Chase & Co\./\d{4} Form 10-K \d+|Apple Inc\. \| \d{4} Form 10-K \| \d+|Part I Part II Part III Part IV)$"
)


def section_chunks(blocks, target=4000):
    if target < 100:
        raise ValueError("Chunk target must be at least 100 characters")
    segments = []
    current = "General"
    for block in blocks:
        if block.get("kind") != "text":
            continue
        text = block["text"]
        matches = list(ITEM.finditer(text))
        boundaries = [0] + [m.start() for m in matches if m.start() > 0] + [len(text)]
        starts = {m.start(): "Item " + m.group(1).upper() for m in matches}
        for a, b in zip(boundaries, boundaries[1:]):
            current = starts.get(a, block.get("location", {}).get("section") or current)
            clean = "\n".join(
                line for line in text[a:b].splitlines() if not FOOTER.fullmatch(line.strip())
            ).strip()
            if clean:
                segments.append((current, clean, block))
    chunks = []
    buffer = []
    length = 0
    section = None

    def flush():
        nonlocal buffer, length
        if not buffer:
            return
        text = "\n\n".join(x[0] for x in buffer)
        first = buffer[0][1]
        pages = sorted(
            {x[1]["location"]["pdf_page"] for x in buffer if "pdf_page" in x[1].get("location", {})}
        )
        loc = {"section": section}
        if pages:
            loc["pdf_pages"] = pages
            loc["pdf_page"] = pages[0]
        identity = first["document_id"] + section + text
        chunks.append(
            {
                k: v
                for k, v in first.items()
                if k
                in (
                    "document_id",
                    "company",
                    "ticker",
                    "report_fiscal_year",
                    "report_period_end",
                    "document_type",
                    "source_url",
                    "source_sha256",
                )
            }
            | {
                "chunk_id": hashlib.sha256(identity.encode()).hexdigest()[:24],
                "source_block_id": first["block_id"],
                "source_block_ids": list(dict.fromkeys(x[1]["block_id"] for x in buffer)),
                "strategy": "section",
                "profile": "item-aware-v1",
                "location": loc,
                "text": text,
                "exact_source_span": False,
            }
        )
        buffer = []
        length = 0

    for sec, text, block in segments:
        for paragraph in re.split(r"\n\s*\n", text):
            for start in range(0, len(paragraph), target):
                part = paragraph[start : start + target]
                if sec != section or length + len(part) + 2 > target:
                    flush()
                    section = sec
                buffer.append((part, block))
                length += len(part) + 2
    flush()
    return chunks


def build_bundled():
    destination = Path("data/chunks/reference/section.jsonl")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w") as output:
        count = 0
        for path in sorted(Path("data/normalized").glob("*.jsonl")):
            blocks = [json.loads(line) for line in path.read_text().splitlines()]
            for c in section_chunks(blocks):
                output.write(json.dumps(c, ensure_ascii=False) + "\n")
                count += 1
    print("Section-aware chunks:", count)


if __name__ == "__main__":
    build_bundled()
